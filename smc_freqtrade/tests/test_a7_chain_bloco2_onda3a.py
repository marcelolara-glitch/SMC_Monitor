"""Bloco 2 / Onda 3a — A7 chain_v2 + tempo transversal (§2.8, D0-D5).

OBJETIVO
    T-A1–T-A7 do briefing: regressão byte-idêntica com defaults (T-A1,
    padrão do T1/T-D1), a máquina da cadeia em sintéticos determinísticos
    (T-A2 nascimento/não-nascimento; T-A4 lifecycle), dois asserts por
    construção sobre o golden 3-TF (T-A3 zonas 5 bull / 5 bear + igualdade
    de banda contra o ledger FVG; T-A6 zero armações da A1 fora de
    killzone), a confirmação sem sweep da A7 chain_v2 (T-A5) e a validação
    de config (T-A7).

FONTE DE DADOS
    Sintéticos scriptados à mão (esperado anotado independente da engine)
    + goldens reais em tests/golden/data com o pipeline da Fase A (fixture
    `merged_golden` importada do módulo do Bloco 1). A máquina da cadeia é
    exercitada tanto no nível do helper `_a7_chain_ffill` (arrays booleanos
    diretos — T-A2/T-A4) quanto ponta-a-ponta via `compute_setup_state`
    (displacement real — T-A5; golden — T-A3/T-A6).

LIMITAÇÕES CONHECIDAS
    Os absolutos de T-A3 (5 bull / 5 bear, L=16, F=2, D3) e a matriz da §0
    foram medidos no golden 15m e reproduzem o Briefing §0. A variante
    estrita (cadeia-inteira-na-janela) fica FORA (calibração — §8).

NÃO FAZER
    Não gerar a fixture esperada dos sintéticos com o próprio
    `compute_setup_state`; não testar a Onda 3b (OB estratégico) aqui.
"""
from __future__ import annotations

import hashlib

import numpy as np
import pandas as pd
import pytest

from smc_engine import (
    compute_setup_state,
    SetupConfig,
    STATE_ARMED,
    STATE_CONFIRMED,
    STATE_PENDING,
)
from smc_engine.fvg import detect_fair_value_gaps
from smc_engine.sessions import SESSION_COLUMNS
from smc_engine.setup_state import (
    A7_VARIANT_CHAIN_V2,
    SETUP_OUTPUT_COLUMNS,
    _a7_chain_ffill,
    _build_arrays,
    _SWEEP_PREMISE_SIGNATURE_IDS,
)

# Reuso do módulo do Bloco 1: baseline de regressão + fixture golden.
from .test_setup_state_bloco1 import (
    _BASELINE_DEFAULT_DIGEST,
    merged_golden,  # noqa: F401 (fixture)
)


# ============================================================
# T-A1 — regressão: defaults ⇒ byte-idêntico ao baseline pré-Bloco 1
# ============================================================

def test_ta1_default_regression_digest(merged_golden) -> None:
    """Config default (a7_variant='legacy', killzone_qualifier=()) no golden:
    digest das 7 colunas == baseline pré-Bloco 1 (defaults byte-idênticos)."""
    res = compute_setup_state(merged_golden)
    payload = res[list(SETUP_OUTPUT_COLUMNS)].to_csv(
        index=False, float_format='%.10g',
    )
    digest = hashlib.sha256(payload.encode('utf-8')).hexdigest()
    assert digest == _BASELINE_DEFAULT_DIGEST


def test_ta1_legacy_a7_unchanged_by_new_fields(merged_golden) -> None:
    """A7 legada é idêntica quando os campos novos ficam no default."""
    base = compute_setup_state(merged_golden, SetupConfig(signature='A7'))
    same = compute_setup_state(
        merged_golden,
        SetupConfig(signature='A7', a7_variant='legacy',
                    a7_fvg_window=2, killzone_qualifier=()),
    )
    for col in SETUP_OUTPUT_COLUMNS:
        assert base[col].equals(same[col]), col


# ============================================================
# T-A2 — cadeia sintética: nasce e não-nasce (máquina direta)
# ============================================================
# Máquina `_a7_chain_ffill` com arrays booleanos anotados à mão (esperado
# independente da engine). Lado bull, window=2, recency=16. OHLC escolhido
# para band = (bottom=high[t2-2], top=low[t2]) com close acima do bottom
# (sem morte por close-through). Cenário-base: sweep@1, MSS-d@3(kz),
# FVG@4 ⇒ nasce zona id=4 com banda [high[2], low[4]] = [10.5, 11.5].

_N = 8
_HIGH = np.full(_N, 10.0)
_HIGH[2] = 10.5           # band bottom (high[t2-2], t2=4)
_LOW = np.full(_N, 9.0)
_LOW[4] = 11.5            # band top (low[t2], t2=4)
_CLOSE = np.full(_N, 11.0)   # > band bottom ⇒ zona viva


def _flags(sweep_idx, mss_idx, kz_idx, fvg_idx):
    sweep = np.zeros(_N, bool)
    mss = np.zeros(_N, bool)
    kz = np.zeros(_N, bool)
    fvg = np.zeros(_N, bool)
    if sweep_idx is not None:
        sweep[sweep_idx] = True
    mss[mss_idx] = True
    if kz_idx is not None:
        kz[kz_idx] = True
    fvg[fvg_idx] = True
    return sweep, mss, kz, fvg


def _run_chain(sweep, mss, kz, fvg, window=2, recency=16):
    return _a7_chain_ffill(
        mss, sweep, fvg, kz, _HIGH, _LOW, _CLOSE, 'bull', window, recency,
    )


def test_ta2_chain_born_with_sweep_mssd_kz_fvg() -> None:
    """sweep→MSS-d(kz)→FVG≤F ⇒ nasce a zona (id=t2, banda do FVG)."""
    sweep, mss, kz, fvg = _flags(1, 3, 3, 4)
    lo, hi, zid = _run_chain(sweep, mss, kz, fvg)
    assert np.isnan(zid[:4]).all()          # nada antes do FVG
    assert (zid[4:] == 4).all()             # nasce em t2=4, forward-fill
    assert lo[4] == 10.5 and hi[4] == 11.5  # banda == geometria do FVG


def test_ta2_chain_not_born_without_recent_sweep() -> None:
    """MSS-d sem sweep recente (recency=1, sweep@1, MSS-d@3) ⇒ não nasce."""
    sweep, mss, kz, fvg = _flags(1, 3, 3, 4)
    _, _, zid = _run_chain(sweep, mss, kz, fvg, recency=1)
    assert np.isnan(zid).all()


def test_ta2_chain_not_born_mssd_outside_kz() -> None:
    """MSS-d fora de killzone (kz_idx=None) ⇒ não nasce (D3)."""
    sweep, mss, kz, fvg = _flags(1, 3, None, 4)
    _, _, zid = _run_chain(sweep, mss, kz, fvg)
    assert np.isnan(zid).all()


def test_ta2_chain_not_born_fvg_beyond_window() -> None:
    """FVG além de F (janela [3,5], FVG@6) ⇒ não nasce."""
    sweep, mss, kz, fvg = _flags(1, 3, 3, 6)
    _, _, zid = _run_chain(sweep, mss, kz, fvg)
    assert np.isnan(zid).all()


# ============================================================
# T-A3 — construção (golden MTF): 5 bull / 5 bear + banda == ledger
# ============================================================

def _chain_births(zid: np.ndarray) -> list[int]:
    """Índices onde `id` transiciona para uma nova zona (nascimentos)."""
    births = []
    prev = np.nan
    for i, v in enumerate(zid):
        if not np.isnan(v) and (np.isnan(prev) or v != prev):
            births.append(int(v))
        prev = v
    return births


def test_ta3_golden_chain_counts_and_band_equals_ledger(merged_golden) -> None:
    """L=16, F=2, D3: 5 zonas bull / 5 bear, e banda == ledger FVG (exata)."""
    cfg = SetupConfig(signature='A7', a7_variant='chain_v2')
    A = _build_arrays(merged_golden, cfg)
    births_bull = _chain_births(A['bull_a7chain_id'])
    births_bear = _chain_births(A['bear_a7chain_id'])
    assert len(births_bull) == 5, births_bull
    assert len(births_bear) == 5, births_bear

    # Banda de cada zona == banda do ledger FVG do evento (igualdade exata).
    _, ledger = detect_fair_value_gaps(merged_golden)
    dates = merged_golden['date'].to_numpy()
    for pre, bias, births, lo_arr, hi_arr in (
        ('bull', 1, births_bull, A['bull_a7chain_low'], A['bull_a7chain_high']),
        ('bear', -1, births_bear, A['bear_a7chain_low'], A['bear_a7chain_high']),
    ):
        for t2 in births:
            row = ledger[(ledger['t_creation'] == dates[t2])
                         & (ledger['bias'] == bias)]
            assert len(row) == 1, (pre, t2)
            # chain_low == ledger bottom, chain_high == ledger top (ambos lados).
            assert float(row['bottom'].iloc[0]) == lo_arr[t2], (pre, t2)
            assert float(row['top'].iloc[0]) == hi_arr[t2], (pre, t2)


# ============================================================
# T-A4 — lifecycle sintético: substituição e morte por close-through
# ============================================================

def test_ta4_lifecycle_replacement_by_new_chain() -> None:
    """Nova cadeia do mesmo lado substitui a ativa (UMA zona por lado)."""
    n = 12
    high = np.full(n, 10.0)
    low = np.full(n, 9.0)
    high[2] = 10.5   # 1ª banda bottom (t2=4)
    low[4] = 11.5    # 1ª banda top
    high[7] = 20.5   # 2ª banda bottom (t2=9)
    low[9] = 21.5    # 2ª banda top
    close = np.full(n, 30.0)   # acima de ambos os bottoms ⇒ sem morte
    sweep = np.zeros(n, bool); sweep[[1, 6]] = True
    mss = np.zeros(n, bool); mss[[3, 8]] = True
    kz = np.zeros(n, bool); kz[[3, 8]] = True
    fvg = np.zeros(n, bool); fvg[[4, 9]] = True
    lo, hi, zid = _a7_chain_ffill(mss, sweep, fvg, kz, high, low, close,
                                  'bull', 2, 16)
    assert _chain_births(zid) == [4, 9]      # duas zonas, a 2ª substitui
    assert (zid[4:9] == 4).all()             # 1ª zona ativa até a troca
    assert (zid[9:] == 9).all()              # 2ª zona ativa após
    assert lo[9] == 20.5 and hi[9] == 21.5   # banda da 2ª zona


def test_ta4_lifecycle_death_by_close_through() -> None:
    """Close além do lado oposto da banda mata a zona (bull: close<bottom)."""
    n = 8
    high = np.full(n, 10.0); high[2] = 10.5
    low = np.full(n, 9.0); low[4] = 11.5
    close = np.full(n, 30.0); close[6] = 5.0   # < band bottom (10.5) ⇒ morre
    sweep = np.zeros(n, bool); sweep[1] = True
    mss = np.zeros(n, bool); mss[3] = True
    kz = np.zeros(n, bool); kz[3] = True
    fvg = np.zeros(n, bool); fvg[4] = True
    _, _, zid = _a7_chain_ffill(mss, sweep, fvg, kz, high, low, close,
                                'bull', 2, 16)
    assert (zid[4:6] == 4).all()     # viva em 4,5
    assert np.isnan(zid[6:]).all()   # morta a partir de 6 (close-through)


# ============================================================
# T-A5 — confirmação sem sweep (chain_v2 + trigger='choch')
# ============================================================

_A5_DEF = dict(
    swing_trend_bias_4h=1.0,
    sweep_bullish_wick=False, sweep_bullish_retest=False,
    sweep_bearish_wick=False, sweep_bearish_retest=False,
    choch_internal_bullish=False, choch_internal_bearish=False,
    fvg_bullish_created=False, fvg_bearish_created=False,
    in_kz_silver_bullet_am=False, in_kz_silver_bullet_late=False,
    in_kz_silver_bullet_pm=False,
)


def _a5_cdl(o, h, l, c, **kw) -> dict:
    row = dict(_A5_DEF)
    row.update(open=o, high=h, low=l, close=c)
    row.update(kw)
    return row


def _a5_frame() -> pd.DataFrame:
    """Cadeia bull sintética que confirma por ChoCH SEM sweep recente.

    Nascimento: sweep@8, MSS-d (displacement+ChoCH+kz)@10, FVG@11 ⇒ banda
    [high[9]=100.5, low[11]=101.5]. ARMED@12, PENDING@14, e um ChoCH@25 —
    17 candles após o sweep (fora de `sweep_recency_candles=4`) ⇒ nenhum
    sweep recente. Só a A7 sem premissa de sweep confirma aqui.
    """
    rows = [_a5_cdl(100.0, 100.3, 100.0, 100.2) for _ in range(9)]  # 0..8 filler
    rows[8] = _a5_cdl(100.0, 100.5, 100.0, 100.2, sweep_bullish_wick=True)
    rows.append(_a5_cdl(100.0, 100.5, 100.0, 100.2))               # 9: high=band bottom
    rows.append(_a5_cdl(100.0, 103.0, 100.0, 103.0,                # 10: displacement MSS-d
                        choch_internal_bullish=True,
                        in_kz_silver_bullet_am=True))
    rows.append(_a5_cdl(102.0, 103.0, 101.5, 102.5,                # 11: FVG (low=band top)
                        fvg_bullish_created=True))
    rows.append(_a5_cdl(102.0, 102.5, 102.0, 102.3))               # 12: ARM (fora, acima)
    rows.append(_a5_cdl(102.0, 102.6, 101.8, 102.2))               # 13: ARMED
    rows.append(_a5_cdl(102.0, 102.0, 101.0, 101.6))               # 14: ENTRY → PENDING
    for _ in range(15, 25):                                        # 15..24 PENDING hold
        rows.append(_a5_cdl(101.5, 101.8, 101.0, 101.4))
    rows.append(_a5_cdl(101.4, 101.9, 101.0, 101.5,                # 25: ChoCH (sem sweep)
                        choch_internal_bullish=True))
    df = pd.DataFrame(rows)
    df['date'] = pd.date_range('2026-03-01', periods=len(df), freq='15min',
                               tz='UTC')
    return df


def test_ta5_confirm_without_sweep_mapping() -> None:
    """A7 legada É premissa-de-sweep; chain_v2 sai do conjunto (confirmação
    sem sweep). Comprovação observável: CONFIRMED num candle sem sweep
    recente com trigger='choch'."""
    assert 'A7' in _SWEEP_PREMISE_SIGNATURE_IDS   # legada exige sweep
    df = _a5_frame()
    cfg = SetupConfig(signature='A7', a7_variant='chain_v2',
                      confirmation_trigger='choch', sweep_recency_candles=4)
    # Sem sweep recente no candle de confirmação (25 − 8 = 17 > 4).
    A = _build_arrays(df, cfg)
    assert not bool(A['bull_sweep_recent'][25])
    res = compute_setup_state(df, cfg)
    states = [s if pd.notna(s) else None for s in res['setup_state']]
    assert STATE_ARMED in states and STATE_PENDING in states
    assert states[25] == STATE_CONFIRMED


# ============================================================
# T-A6 — qualificador transversal de killzone (§2.4, D5)
# ============================================================

_KZ_DEF = dict(
    swing_trend_bias_4h=1.0,
    active_bull_swing_ob_top_1h=102.0,
    active_bull_swing_ob_bottom_1h=100.0,
    active_bull_swing_ob_id_1h=5.0,
    active_bear_swing_ob_top_1h=np.nan,
    active_bear_swing_ob_bottom_1h=np.nan,
    active_bear_swing_ob_id_1h=np.nan,
    sweep_bullish_wick=False, sweep_bullish_retest=False,
    sweep_bearish_wick=False, sweep_bearish_retest=False,
    choch_internal_bullish=False, choch_internal_bearish=False,
    in_kz_silver_bullet_am=False, in_kz_silver_bullet_late=False,
    in_kz_silver_bullet_pm=False,
)


def _kz_frame(in_kz: bool) -> pd.DataFrame:
    """Um candle com OB bull presente + preço fora + trend bull; kz on/off."""
    row = dict(_KZ_DEF)
    row.update(open=105.0, high=108.0, low=105.0, close=105.5)
    if in_kz:
        row['in_kz_silver_bullet_am'] = True
    df = pd.DataFrame([row])
    df['date'] = pd.date_range('2026-03-01', periods=1, freq='15min', tz='UTC')
    return df


def test_ta6_qualifier_blocks_outside_kz_arms_inside() -> None:
    """A1 listada no qualifier: não arma fora de kz, arma dentro (sintético)."""
    cfg = SetupConfig(signature='A1', killzone_qualifier=('A1',))
    out = compute_setup_state(_kz_frame(in_kz=False), cfg)
    assert out['setup_state'].isna().all()          # não arma fora de kz
    inside = compute_setup_state(_kz_frame(in_kz=True), cfg)
    assert inside['setup_state'].iloc[0] == STATE_ARMED   # arma dentro


def test_ta6_golden_zero_a1_arms_outside_kz(merged_golden) -> None:
    """(golden) killzone_qualifier=('A1',): zero armações da A1 fora de kz."""
    in_kz = np.zeros(len(merged_golden), dtype=bool)
    for col in SESSION_COLUMNS:
        in_kz = in_kz | merged_golden[col].to_numpy(dtype=bool)
    res = compute_setup_state(
        merged_golden, SetupConfig(signature='A1', killzone_qualifier=('A1',)),
    )
    active = res.dropna(subset=['setup_id'])
    births = active.groupby('setup_id', sort=False).head(1)
    assert births.shape[0] > 0                       # há armações (sanidade)
    assert int((~in_kz[births.index.to_numpy()]).sum()) == 0


# ============================================================
# T-A7 — validação de config
# ============================================================

def test_ta7_invalid_a7_variant_raises() -> None:
    with pytest.raises(ValueError, match='a7_variant'):
        SetupConfig(a7_variant='chainv2')


def test_ta7_invalid_a7_fvg_window_raises() -> None:
    with pytest.raises(ValueError, match='a7_fvg_window'):
        SetupConfig(a7_fvg_window=0)


def test_ta7_invalid_qualifier_id_raises() -> None:
    with pytest.raises(ValueError, match='killzone_qualifier'):
        SetupConfig(killzone_qualifier=('A1', 'ZZ'))


def test_ta7_defaults_construct() -> None:
    cfg = SetupConfig()
    assert cfg.a7_variant == 'legacy'
    assert cfg.a7_fvg_window == 2
    assert cfg.killzone_qualifier == ()
