"""Bloco 2 / Onda 3b — OB estratégico (§2.10 + §2.6-ii) + consumo A1 + G7.

OBJETIVO
    T-B1–T-B7 do briefing: regressão byte-idêntica com defaults (T-B1,
    padrão do T1/T-A1), a máquina do detector em sintéticos determinísticos
    (T-B2 nascimento/não-nascimento + doji pulado + banda; T-B3 lifecycle
    replaced/mitigated com kill-antes-de-criar), os absolutos por construção
    sobre o golden (T-B4 28 bull / 40 bear + banda idêntica ao primitivo ==
    0; T-B5 consumo pela A1 estratégica = banda sob no candle da armação, 0
    violações), a paridade congelada do G7 (T-B6, golden 15m) e a validação
    de config + alias de interface (T-B7).

FONTE DE DADOS
    Sintéticos scriptados à mão (esperado anotado independente da engine)
    + goldens reais em tests/golden/data com o pipeline da Fase A (fixture
    `merged_golden` importada do módulo do Bloco 1). O detector é exercitado
    tanto direto (`project_strategic_obs` — T-B2/T-B3) quanto ponta-a-ponta
    via `analyze`/`compute_setup_state` (golden — T-B4/T-B5).

LIMITAÇÕES CONHECIDAS
    Os absolutos de T-B4 (28 bull / 40 bear, K=5, banda idêntica 0) e de
    T-B6 (4 flips internal high-vol) foram medidos no golden e reproduzem o
    Briefing §0. O refinamento mean-threshold 50% fica FORA (§11).

NÃO FAZER
    Não gerar o esperado dos sintéticos com o próprio `project_strategic_obs`;
    não testar calibração (mean-threshold, K exposto) nem consumo A2/A3/A5.
"""
from __future__ import annotations

import hashlib

import numpy as np
import pandas as pd
import pytest

from smc_engine import (
    analyze,
    compute_setup_state,
    SetupConfig,
    STATE_ARMED,
)
from smc_engine.operators import atr_wilder, displacement_flags
from smc_engine.order_blocks import project_strategic_obs
from smc_engine.setup_state import (
    OB_SEMANTICS,
    _displacement_flags,
)

# Reuso do módulo do Bloco 1: baseline de regressão + fixture golden.
from .test_setup_state_bloco1 import (
    _BASELINE_DEFAULT_DIGEST,
    merged_golden,  # noqa: F401 (fixture)
)
from .test_smoke_wave9_5b_golden import _load_ohlcv

# Config "Bloco-1-ON" do briefing (§8; espelha o diag e o T-O da Onda 2).
_BLOCO1_ON = dict(
    arming_proximity_pct=0.02,
    confirmation_trigger='choch',
    anchor_invalidation='frozen_band',
    a9_variant='sweep_band',
    displacement_gate='confirm',
)


# ============================================================
# Builder sintético do detector (esperado independente da engine)
# ============================================================

_STRUCT_COLS = (
    'bos_internal_bullish', 'bos_internal_bearish',
    'choch_internal_bullish', 'choch_internal_bearish',
)


def _sob_df(rows: list[dict]) -> pd.DataFrame:
    """DataFrame OHLC + 4 booleans de estrutura internal (default False)."""
    data: dict[str, list] = {c: [] for c in ('open', 'high', 'low', 'close')}
    for c in _STRUCT_COLS:
        data[c] = []
    for row in rows:
        for c in ('open', 'high', 'low', 'close'):
            data[c].append(row[c])
        for c in _STRUCT_COLS:
            data[c].append(bool(row.get(c, False)))
    df = pd.DataFrame(data)
    df['date'] = pd.date_range('2026-03-01', periods=len(df), freq='15min',
                               tz='UTC')
    return df


def _tiny_bull(o: float = 100.0) -> dict:
    """Candle de corpo pequeno bull (filler; não dispara displacement)."""
    return {'open': o, 'high': o + 0.6, 'low': o - 0.1, 'close': o + 0.5}


def _anchor_bull(o: float = 100.0, body: float = 10.0, **flags) -> dict:
    """Candle de displacement bull grande (corpo >> filler, wicks << corpo)."""
    c = o + body
    row = {'open': o, 'high': c + 0.1, 'low': o - 0.1, 'close': c}
    row.update(flags)
    return row


# ============================================================
# T-B1 — regressão: defaults ⇒ byte-idêntico ao baseline pré-Bloco 1
# ============================================================

def test_tb1_default_regression_digest(merged_golden) -> None:
    """Config default (ob_semantics='primitive') no golden: digest das 7
    colunas == baseline pré-Bloco 1 (A1 byte-idêntica; sob inertes)."""
    from smc_engine.setup_state import SETUP_OUTPUT_COLUMNS
    res = compute_setup_state(merged_golden)
    payload = res[list(SETUP_OUTPUT_COLUMNS)].to_csv(
        index=False, float_format='%.10g',
    )
    digest = hashlib.sha256(payload.encode('utf-8')).hexdigest()
    assert digest == _BASELINE_DEFAULT_DIGEST


def test_tb1_six_new_columns_present(merged_golden) -> None:
    """As 6 colunas sob (suffixadas _1h) presentes no golden mergeado."""
    for field in ('top', 'bottom', 'id'):
        for pre in ('bull', 'bear'):
            assert f'{pre}_sob_{field}_1h' in merged_golden.columns


def test_tb1_a1_primitive_unchanged_by_new_field(merged_golden) -> None:
    """A1 primitiva é idêntica com o campo novo no default explícito."""
    base = compute_setup_state(merged_golden, SetupConfig(signature='A1'))
    same = compute_setup_state(
        merged_golden, SetupConfig(signature='A1', ob_semantics='primitive'),
    )
    from smc_engine.setup_state import SETUP_OUTPUT_COLUMNS
    for col in SETUP_OUTPUT_COLUMNS:
        assert base[col].equals(same[col]), col


# ============================================================
# T-B2 — detector sintético: acha a última vela oposta em ≤5 (doji pulado)
# ============================================================

def test_tb2_finds_last_opposite_skipping_doji() -> None:
    """Âncora bull acha a 1ª vela de corpo bear a partir de t−1 (doji
    pulado); banda == range integral dessa vela."""
    rows = [_tiny_bull() for _ in range(15)]           # 0..14 filler bull
    rows.append({'open': 101.0, 'high': 101.1, 'low': 99.9, 'close': 100.0})  # 15 bear (OB)
    rows.append({'open': 100.5, 'high': 100.6, 'low': 100.4, 'close': 100.5})  # 16 doji
    rows.append(_anchor_bull(choch_internal_bullish=True))                    # 17 âncora
    df = _sob_df(rows)
    out = project_strategic_obs(df)
    # Nasce em t=17, âncora na vela 15 (doji 16 pulado).
    assert pd.isna(out['bull_sob_id'].iloc[16])
    assert int(out['bull_sob_id'].iloc[17]) == 15
    # Banda == range integral da vela 15.
    assert out['bull_sob_bottom'].iloc[17] == 99.9
    assert out['bull_sob_top'].iloc[17] == 101.1


def test_tb2_no_zone_when_no_opposite_in_k() -> None:
    """Sem vela de corpo oposto em K=5 ⇒ o evento não gera zona."""
    rows = [_tiny_bull() for _ in range(17)]           # 0..16 todos bull
    rows.append(_anchor_bull(choch_internal_bullish=True))   # 17 âncora
    df = _sob_df(rows)
    out = project_strategic_obs(df)
    assert out['bull_sob_id'].isna().all()


def test_tb2_anchor_requires_displacement() -> None:
    """Estrutura-tomada SEM displacement (corpo pequeno) ⇒ sem zona
    (fecha §2.6-ii por construção)."""
    rows = [_tiny_bull() for _ in range(15)]
    rows.append({'open': 101.0, 'high': 101.1, 'low': 99.9, 'close': 100.0})  # 15 bear
    rows.append(_tiny_bull())                                                 # 16
    # ChoCH num candle de corpo pequeno (não-displacement).
    rows.append({'open': 100.0, 'high': 100.6, 'low': 99.9, 'close': 100.5,
                 'choch_internal_bullish': True})                             # 17
    out = project_strategic_obs(_sob_df(rows))
    assert out['bull_sob_id'].isna().all()


# ============================================================
# T-B3 — lifecycle sintético: replaced e mitigated (kill antes de criar)
# ============================================================

def test_tb3_replaced_by_new_anchor() -> None:
    """Novo evento-âncora do mesmo lado substitui a zona ativa (UMA por
    lado); a banda emitida no candle da troca já é a da zona nova."""
    rows = [_tiny_bull() for _ in range(15)]
    rows.append({'open': 101.0, 'high': 101.1, 'low': 99.9, 'close': 100.0})  # 15 bear (OB1)
    rows.append(_tiny_bull())                                                 # 16
    rows.append(_anchor_bull(choch_internal_bullish=True))                    # 17 âncora1 → zona id=15
    rows += [_tiny_bull(110.0) for _ in range(5)]      # 18..22 hold (acima da banda)
    rows.append({'open': 112.0, 'high': 112.1, 'low': 110.5, 'close': 111.0})  # 23 bear (OB2)
    rows.append(_tiny_bull(111.0))                                            # 24
    rows.append(_anchor_bull(o=111.0, choch_internal_bullish=True))           # 25 âncora2 → zona id=23
    out = project_strategic_obs(_sob_df(rows))
    assert int(out['bull_sob_id'].iloc[17]) == 15   # 1ª zona
    assert int(out['bull_sob_id'].iloc[24]) == 15   # ainda a 1ª antes da troca
    assert int(out['bull_sob_id'].iloc[25]) == 23   # substituída (kill+create)
    # Banda em t=25 já é a da vela 23 (create ocorreu no mesmo candle).
    assert out['bull_sob_bottom'].iloc[25] == 110.5
    assert out['bull_sob_top'].iloc[25] == 112.1


def test_tb3_mitigated_by_close_through() -> None:
    """Close além do lado oposto da banda mata a zona (bull: close <
    bottom); zona viva antes, morta a partir do candle do close-through."""
    rows = [_tiny_bull() for _ in range(15)]
    rows.append({'open': 101.0, 'high': 101.1, 'low': 99.9, 'close': 100.0})  # 15 bear (OB), bottom=99.9
    rows.append(_tiny_bull())                                                 # 16
    rows.append(_anchor_bull(choch_internal_bullish=True))                    # 17 nasce zona
    rows.append(_tiny_bull(110.0))                                            # 18 viva
    rows.append(_tiny_bull(110.0))                                            # 19 viva
    rows.append({'open': 100.0, 'high': 100.1, 'low': 89.0, 'close': 90.0})   # 20 close<99.9 ⇒ morre
    rows.append(_tiny_bull(90.0))                                             # 21 sem zona
    out = project_strategic_obs(_sob_df(rows))
    assert (out['bull_sob_id'].iloc[17:20].notna()).all()   # viva 17,18,19
    assert out['bull_sob_id'].iloc[20:].isna().all()        # morta a partir de 20


# ============================================================
# T-B4 — construção (golden 1h): 28 bull / 40 bear + banda idêntica == 0
# ============================================================

def _sob_births(sid: pd.Series) -> int:
    """Nº de nascimentos: transições para uma nova zona (id muda)."""
    prev = None
    births = 0
    for v in sid:
        cur = None if pd.isna(v) else int(v)
        if cur is not None and cur != prev:
            births += 1
        prev = cur
    return births


def test_tb4_golden_1h_zone_counts() -> None:
    """Golden 1h, K=5: 28 zonas bull / 40 bear criadas (§0)."""
    df = analyze(_load_ohlcv('btc_usdt_swap_1h_window.csv')).df
    assert _sob_births(df['bull_sob_id']) == 28
    assert _sob_births(df['bear_sob_id']) == 40


def test_tb4_golden_1h_band_never_equals_primitive() -> None:
    """Na co-presença com o primitivo promovido (swing OB ativo), a banda
    do OB estratégico nunca é idêntica (0 casos — §0/F5)."""
    df = analyze(_load_ohlcv('btc_usdt_swap_1h_window.csv')).df
    for pre in ('bull', 'bear'):
        copres = df[f'{pre}_sob_id'].notna() & df[f'active_{pre}_swing_ob_id'].notna()
        assert int(copres.sum()) > 0, pre   # há co-presença (sanidade)
        identical = (
            copres
            & (df[f'{pre}_sob_top'] == df[f'active_{pre}_swing_ob_top'])
            & (df[f'{pre}_sob_bottom'] == df[f'active_{pre}_swing_ob_bottom'])
        )
        assert int(identical.sum()) == 0, pre


# ============================================================
# T-B5 — construção (golden MTF): A1 estratégica arma na banda sob vigente
# ============================================================

def test_tb5_golden_a1_strategic_zone_equals_sob_band(merged_golden) -> None:
    """ob_semantics='strategic' + Bloco-1-ON + displacement: toda zona
    armada pela A1 == banda sob vigente no candle da armação (0 violações)."""
    cfg = SetupConfig(signature='A1', ob_semantics='strategic', **_BLOCO1_ON)
    res = compute_setup_state(merged_golden, cfg).reset_index(drop=True)
    m = merged_golden.reset_index(drop=True)
    active = res.dropna(subset=['setup_id'])
    births = active.groupby('setup_id', sort=False).head(1)
    assert births.shape[0] > 0                       # há armações (sanidade)
    violations = 0
    for i, row in births.iterrows():
        assert row['setup_state'] == STATE_ARMED
        pre = 'bull' if row['setup_direction'] == 'long' else 'bear'
        if not (row['setup_zone_low'] == m[f'{pre}_sob_bottom_1h'].iloc[i]
                and row['setup_zone_high'] == m[f'{pre}_sob_top_1h'].iloc[i]):
            violations += 1
    assert violations == 0


# ============================================================
# T-B6 — G7: paridade congelada do parsed-extreme (golden 15m)
# ============================================================

def test_tb6_golden_15m_flip_rows_frozen() -> None:
    """Ledger OB do golden 15m: exatamente 4 linhas com bar_high <= bar_low,
    todas `internal`, e as 4 satisfazem a condição high-vol sob o modo
    default do engine ('Atr', atr_wilder(200)). Paridade Pine :126-128."""
    raw = _load_ohlcv('btc_usdt_swap_15m_window.csv')
    ledger = analyze(raw).ledger_ob
    flip = ledger[ledger['bar_high'] <= ledger['bar_low']]
    assert len(flip) == 4
    assert set(flip['scope'].unique()) == {'internal'}
    # Condição high-vol no candle da vela do OB (bar_time), modo 'Atr'.
    vol = atr_wilder(raw['high'], raw['low'], raw['close'], length=200)
    raw_pos = raw.reset_index(drop=True)
    date_to_pos = {d: i for i, d in enumerate(raw_pos['date'])}
    high_vol = (raw['high'] - raw['low']) >= (2.0 * vol)
    for _, row in flip.iterrows():
        pos = date_to_pos[row['bar_time']]
        assert bool(high_vol.iloc[pos]), row['bar_time']


# ============================================================
# T-B7 — validação de config + alias de interface preservado
# ============================================================

def test_tb7_invalid_ob_semantics_raises() -> None:
    with pytest.raises(ValueError, match='ob_semantics'):
        SetupConfig(ob_semantics='primitivo')


def test_tb7_ob_semantics_enum_and_defaults() -> None:
    assert OB_SEMANTICS == ('primitive', 'strategic')
    assert SetupConfig().ob_semantics == 'primitive'
    # Ambos os valores válidos constroem.
    assert SetupConfig(ob_semantics='strategic').ob_semantics == 'strategic'


def test_tb7_displacement_flags_alias_preserved() -> None:
    """`setup_state._displacement_flags` continua importável e é o mesmo
    objeto que `operators.displacement_flags` (interface preservation, D4);
    comportamento idêntico num frame sintético."""
    assert _displacement_flags is displacement_flags
    rng = np.random.RandomState(7)
    o = 100.0 + rng.normal(0, 1.0, 60)
    c = o + rng.normal(0, 1.0, 60)
    h = np.maximum(o, c) + np.abs(rng.normal(0, 0.3, 60))
    low = np.minimum(o, c) - np.abs(rng.normal(0, 0.3, 60))
    a_bull, a_bear = _displacement_flags(o, h, low, c, 10, 0.36)
    b_bull, b_bear = displacement_flags(o, h, low, c, 10, 0.36)
    assert np.array_equal(a_bull, b_bull)
    assert np.array_equal(a_bear, b_bear)
