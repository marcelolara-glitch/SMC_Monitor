"""Bloco 2 / Onda 2 — ciclo de vida v2 do OTE + gates da A10 (§2.7).

OBJETIVO
    T-O1–T-O7 do briefing: regressão byte-idêntica com defaults (T-O1,
    padrão do T1/T-D1), ciclo de vida em sintéticos determinísticos
    (T-O2: `replaced`, `opposite_mss`, `origin_break`, kills antes de
    criação no mesmo candle), asserts por construção sobre o golden 1h
    (T-O3: nº de zonas v2 == nº de linhas do ledger legado; persistência
    v2 < legada nos dois lados), EQ sticky com toque de pavio (T-O4),
    gates D4 por construção no golden MTF (T-O5), fonte legada
    byte-idêntica (T-O6) e guarda de config (T-O7).

FONTE DE DADOS
    Sintéticos scriptados à mão (esperado anotado independente da
    engine, padrão de test_smoke_wave9_5d) + goldens reais em
    tests/golden/data com o pipeline da Fase A (fixture `merged_golden`
    importada do módulo do Bloco 1).

LIMITAÇÕES CONHECIDAS
    As contagens do golden 1h (11 zonas bull / 8 bear, 19 eventos)
    reproduzem a sondagem de 2026-07-05 citada no briefing (identidade
    19/19; EQ-cross ~53%, toque na banda ~42%).

NÃO FAZER
    Não gerar a fixture esperada dos sintéticos com o próprio
    `project_ote_zones_v2`; não testar tier internal/both nem variante
    de EQ por close (não implementados — só registrados).
"""
from __future__ import annotations

import hashlib

import numpy as np
import pandas as pd
import pytest

from smc_engine import analyze, compute_setup_state, SetupConfig
from smc_engine.fib_ote import (
    OTE_RETRACE_HIGH,
    OTE_RETRACE_LOW,
    OTE_V2_COLUMNS,
    OTE_V2_KILL_OPPOSITE_MSS,
    OTE_V2_KILL_ORIGIN_BREAK,
    OTE_V2_KILL_REPLACED,
    _build_ote_ledger,
    project_ote_zones_v2,
)
from smc_engine.setup_state import (
    DIRECTION_LONG,
    SETUP_OUTPUT_COLUMNS,
    STATE_ARMED,
)
from smc_engine.structure import (
    COL_BOS_SWING_BEARISH,
    COL_BOS_SWING_BULLISH,
    COL_CHOCH_SWING_BEARISH,
    COL_CHOCH_SWING_BULLISH,
)
from smc_engine.trailing import COL_TRAILING_BOTTOM, COL_TRAILING_TOP
from smc_engine.types import BEARISH, BULLISH

# Reuso deliberado do módulo do Bloco 1: baseline de regressão e a
# fixture golden (importar uma função decorada com @pytest.fixture a
# registra neste módulo).
from .test_setup_state_bloco1 import (
    _BASELINE_DEFAULT_DIGEST,
    merged_golden,  # noqa: F401 (fixture)
)
from .test_smoke_wave9_5b_golden import _load_ohlcv


@pytest.fixture(scope='module')
def golden_1h() -> pd.DataFrame:
    """analyze() do golden 1h (inclui as 12 colunas v2 do engine)."""
    return analyze(_load_ohlcv('btc_usdt_swap_1h_window.csv')).df


def _ids(out: pd.DataFrame, col: str) -> list:
    """Coluna Int64 → lista de int/None (comparável a literais)."""
    return [int(x) if pd.notna(x) else None for x in out[col]]


# ============================================================
# Helpers sintéticos (padrão test_smoke_wave9_5d)
# ============================================================

def _v2_df(rows: list[dict]) -> pd.DataFrame:
    """DataFrame sintético mínimo para `project_ote_zones_v2`.

    Cada row: close (obrigatório), high/low (default close±1),
    leg=(low, high) marca MSS com a perna dada; kind ∈
    {'bos_bull','bos_bear','choch_bull','choch_bear'} (default
    'bos_bull').
    """
    n = len(rows)
    closes = np.array([r['close'] for r in rows], dtype='float64')
    highs = np.array([r.get('high', r['close'] + 1.0) for r in rows])
    lows = np.array([r.get('low', r['close'] - 1.0) for r in rows])
    ttop = np.full(n, np.nan)
    tbot = np.full(n, np.nan)
    flags = {
        'bos_bull': np.zeros(n, dtype=bool),
        'bos_bear': np.zeros(n, dtype=bool),
        'choch_bull': np.zeros(n, dtype=bool),
        'choch_bear': np.zeros(n, dtype=bool),
    }
    for i, r in enumerate(rows):
        if 'leg' in r:
            tbot[i], ttop[i] = r['leg']
            flags[r.get('kind', 'bos_bull')][i] = True
    return pd.DataFrame({
        'date': pd.date_range('2026-01-01', periods=n, freq='1h'),
        'open': closes, 'high': highs, 'low': lows, 'close': closes,
        COL_TRAILING_TOP: ttop,
        COL_TRAILING_BOTTOM: tbot,
        COL_BOS_SWING_BULLISH: flags['bos_bull'],
        COL_BOS_SWING_BEARISH: flags['bos_bear'],
        COL_CHOCH_SWING_BULLISH: flags['choch_bull'],
        COL_CHOCH_SWING_BEARISH: flags['choch_bear'],
    })


# ============================================================
# T-O1 — regressão: defaults ⇒ byte-idêntico + 12 colunas aditivas
# ============================================================

def test_to1_default_regression_digest(merged_golden) -> None:
    """Config default no golden: digest das 7 colunas da FSM == baseline
    pré-Bloco 1 (o MESMO hash do T1/T-D1)."""
    res = compute_setup_state(merged_golden)
    payload = res[list(SETUP_OUTPUT_COLUMNS)].to_csv(
        index=False, float_format='%.10g',
    )
    digest = hashlib.sha256(payload.encode('utf-8')).hexdigest()
    assert digest == _BASELINE_DEFAULT_DIGEST


def test_to1_analyze_additive_and_preexisting_untouched(golden_1h) -> None:
    """As 12 colunas novas presentes no analyze() com dtypes corretos;
    colunas pré-existentes inalteradas (reaplicar a v2 sobre o frame sem
    as 12 reproduz o frame do analyze byte-idêntico).

    Ordem de colunas normalizada explicitamente: o tail do `analyze` evolui
    por ondas (Onda 3b: `SOB_COLUMNS`); a invariante deste teste é
    conjunto+valores+dtypes, não posição."""
    for col in OTE_V2_COLUMNS:
        assert col in golden_1h.columns, col
    for pre in ('bull', 'bear'):
        assert golden_1h[f'{pre}_ote_v2_top'].dtype == 'float64'
        assert str(golden_1h[f'{pre}_ote_v2_id'].dtype) == 'Int64'
        assert golden_1h[f'{pre}_ote_v2_eq_crossed'].dtype == bool
    base = golden_1h.drop(columns=list(OTE_V2_COLUMNS))
    base_snapshot = base.copy()
    redone = project_ote_zones_v2(base)
    # Não muta o caller.
    pd.testing.assert_frame_equal(base, base_snapshot)
    # Pré-existentes intocadas + 12 novas idênticas às do engine.
    # `project_ote_zones_v2` reanexa a v2 ao fim; com o tail do analyze já
    # evoluído (Onda 3b: SOB_COLUMNS após OTE_V2), normaliza-se a ordem de
    # colunas pela referência antes do assert estrito (conjunto+valores+dtypes).
    redone = redone[golden_1h.columns]
    pd.testing.assert_frame_equal(redone, golden_1h)


# ============================================================
# T-O2 — lifecycle sintético: replaced / opposite_mss / origin_break
#         e a ordem kills-antes-de-criar no mesmo candle
# ============================================================

def test_to2_replaced_same_direction_mss() -> None:
    rows = [
        {'close': 150.0, 'leg': (100.0, 200.0)},   # zona A (id=0)
        {'close': 150.0},
        {'close': 260.0, 'leg': (150.0, 300.0)},   # MSS bull: A → replaced
        {'close': 260.0},
    ]
    out, stats = project_ote_zones_v2(_v2_df(rows), with_stats=True)
    assert _ids(out, 'bull_ote_v2_id') == [0, 0, 2, 2]
    # Banda emitida em t=2 já é a da zona nova (kills antes de criar).
    span = 300.0 - 150.0
    assert out['bull_ote_v2_top'].iloc[2] == pytest.approx(
        300.0 - OTE_RETRACE_LOW * span)
    assert out['bull_ote_v2_origin'].iloc[2] == 150.0
    assert stats['bull']['created'] == 2
    assert stats['bull']['kills'][OTE_V2_KILL_REPLACED] == 1


def test_to2_opposite_mss_kills_and_creates_other_side() -> None:
    rows = [
        {'close': 150.0, 'leg': (100.0, 200.0)},                # bull id=0
        {'close': 150.0},
        {'close': 150.0, 'leg': (100.0, 200.0), 'kind': 'choch_bear'},
        {'close': 150.0},
    ]
    out, stats = project_ote_zones_v2(_v2_df(rows), with_stats=True)
    # Bull inativa a partir do próprio candle do MSS oposto.
    assert _ids(out, 'bull_ote_v2_id') == [0, 0, None, None]
    # Bear nasce em t=2 e emite a partir de t=2.
    assert _ids(out, 'bear_ote_v2_id') == [None, None, 2, 2]
    assert stats['bull']['kills'][OTE_V2_KILL_OPPOSITE_MSS] == 1
    assert stats['bear']['created'] == 1


def test_to2_origin_break_inherited_rule() -> None:
    # Bull: origem 0.0 = low da perna; close < origem invalida no
    # próprio candle (regra herdada de _build_ote_ledger:147-156).
    rows = [
        {'close': 150.0, 'leg': (100.0, 200.0)},
        {'close': 110.0, 'low': 109.0},
        {'close': 99.0, 'low': 98.0},    # close < 100 → origin_break
        {'close': 150.0},
    ]
    out, stats = project_ote_zones_v2(_v2_df(rows), with_stats=True)
    assert _ids(out, 'bull_ote_v2_id') == [0, 0, None, None]
    assert stats['bull']['kills'][OTE_V2_KILL_ORIGIN_BREAK] == 1

    # Bear simétrico: origem = high da perna; close > origem invalida.
    rows = [
        {'close': 350.0, 'leg': (300.0, 400.0), 'kind': 'bos_bear'},
        {'close': 405.0, 'high': 406.0},  # close > 400 → origin_break
    ]
    out, stats = project_ote_zones_v2(_v2_df(rows), with_stats=True)
    assert _ids(out, 'bear_ote_v2_id') == [0, None]
    assert stats['bear']['kills'][OTE_V2_KILL_ORIGIN_BREAK] == 1


def test_to2_kill_priority_origin_break_before_replaced() -> None:
    """No mesmo candle, kills vêm antes da criação e na ordem do
    briefing: a zona antiga morre por origin_break (passo 2) antes do
    MSS da mesma direção criar a nova (passo 3)."""
    rows = [
        {'close': 150.0, 'leg': (100.0, 200.0)},               # zona A
        # Candle t=1: close 99 < origem 100 (mata A por origin_break)
        # E MSS bull com perna nova → zona B nasce e emite em t=1.
        {'close': 99.0, 'low': 98.0, 'leg': (90.0, 190.0)},
    ]
    out, stats = project_ote_zones_v2(_v2_df(rows), with_stats=True)
    assert stats['bull']['kills'][OTE_V2_KILL_ORIGIN_BREAK] == 1
    assert stats['bull']['kills'][OTE_V2_KILL_REPLACED] == 0
    assert _ids(out, 'bull_ote_v2_id') == [0, 1]
    assert out['bull_ote_v2_origin'].iloc[1] == 90.0


def test_to2_creation_candle_origin_break_never_emits() -> None:
    """Zona cujo candle de criação já fecha além da origem morre no
    próprio candle (legado varre j desde t) — nunca emite."""
    rows = [
        {'close': 99.0, 'low': 98.0, 'leg': (100.0, 200.0)},
        {'close': 150.0},
    ]
    out, stats = project_ote_zones_v2(_v2_df(rows), with_stats=True)
    assert out['bull_ote_v2_id'].isna().all()
    assert stats['bull']['created'] == 1
    assert stats['bull']['kills'][OTE_V2_KILL_ORIGIN_BREAK] == 1


# ============================================================
# T-O3 — construção (golden 1h): nº de zonas v2 == nº de linhas do
#         ledger legado; persistência v2 < legada nos dois lados
# ============================================================

def test_to3_golden_creation_parity_and_lower_persistence(
    golden_1h,
) -> None:
    base = golden_1h.drop(columns=list(OTE_V2_COLUMNS))
    out, stats = project_ote_zones_v2(base, with_stats=True)
    ledger = _build_ote_ledger(base)
    # Mesmos eventos e guardas ⇒ mesma contagem de criações por lado.
    assert stats['bull']['created'] == int((ledger['bias'] == BULLISH).sum())
    assert stats['bear']['created'] == int((ledger['bias'] == BEARISH).sum())
    assert stats['bull']['created'] + stats['bear']['created'] == len(ledger)
    # Persistência (fração de candles com zona ativa): v2 < legada.
    for pre in ('bull', 'bear'):
        v2_persist = float(out[f'{pre}_ote_v2_id'].notna().mean())
        legacy_persist = float(out[f'active_{pre}_ote_id'].notna().mean())
        assert 0.0 < v2_persist < legacy_persist, (
            f'{pre}: v2={v2_persist:.3f} legacy={legacy_persist:.3f}')


# ============================================================
# T-O4 — eq_crossed: sticky, toque de pavio conta, reset em zona nova
# ============================================================

def test_to4_eq_crossed_sticky_wick_and_reset() -> None:
    # Perna bull [100, 200] → eq_level = 150.
    rows = [
        {'close': 180.0, 'low': 179.0, 'leg': (100.0, 200.0)},  # acima do EQ
        {'close': 170.0, 'low': 169.0},                          # ainda acima
        {'close': 160.0, 'low': 149.5},   # pavio toca 150 → True (close acima)
        {'close': 180.0, 'low': 179.0},   # sticky: permanece True
        # Zona nova (mesma direção) → reset para False.
        {'close': 260.0, 'low': 259.0, 'leg': (200.0, 300.0)},   # eq=250: low 259 > 250
        {'close': 240.0, 'low': 239.0},   # low 239 <= 250 → True de novo
    ]
    out = project_ote_zones_v2(_v2_df(rows))
    eq = list(out['bull_ote_v2_eq_crossed'])
    assert eq == [False, False, True, True, False, True]
    assert out['bull_ote_v2_eq_level'].iloc[0] == pytest.approx(150.0)
    assert out['bull_ote_v2_eq_level'].iloc[4] == pytest.approx(250.0)

    # Bear simétrico: perna [300, 400] → eq=350; pavio high >= 350 conta.
    rows = [
        {'close': 320.0, 'high': 321.0, 'leg': (300.0, 400.0),
         'kind': 'bos_bear'},
        {'close': 330.0, 'high': 351.0},   # pavio toca 350 → True
        {'close': 320.0, 'high': 321.0},   # sticky
    ]
    out = project_ote_zones_v2(_v2_df(rows))
    assert list(out['bear_ote_v2_eq_crossed']) == [False, True, True]


# ============================================================
# T-O5 — construção (golden MTF): gates D4 zeram violações na armação
# ============================================================

def _armed_first_candles(res: pd.DataFrame) -> pd.DataFrame:
    active = res.dropna(subset=['setup_id'])
    first = active.groupby('setup_id', sort=False).head(1)
    assert (first['setup_state'] == STATE_ARMED).all()
    return first


def test_to5_golden_eq_cross_gate_by_construction(merged_golden) -> None:
    # Sanidade: a fonte v2 sem gates arma (a máquina funciona).
    plain = compute_setup_state(merged_golden, SetupConfig(
        signature='A10', ote_lifecycle='v2',
    ))
    assert plain['setup_id'].notna().any()

    res = compute_setup_state(merged_golden, SetupConfig(
        signature='A10', ote_lifecycle='v2', ote_require_eq_cross=True,
    ))
    first = _armed_first_candles(res)
    violations = 0
    for idx, row in first.iterrows():
        pre = 'bull' if row['setup_direction'] == DIRECTION_LONG else 'bear'
        crossed = merged_golden[f'{pre}_ote_v2_eq_crossed_1h'].loc[idx]
        if not bool(crossed):
            violations += 1
    assert violations == 0, f'{violations} armações sem eq_crossed'


def test_to5_golden_confluence_gate_by_construction(merged_golden) -> None:
    res = compute_setup_state(merged_golden, SetupConfig(
        signature='A10', ote_lifecycle='v2', ote_require_eq_cross=True,
        ote_require_confluence=True,
    ))
    first = _armed_first_candles(res)
    violations = 0
    for idx, row in first.iterrows():
        pre = 'bull' if row['setup_direction'] == DIRECTION_LONG else 'bear'
        v2_top = merged_golden[f'{pre}_ote_v2_top_1h'].loc[idx]
        v2_bot = merged_golden[f'{pre}_ote_v2_bottom_1h'].loc[idx]
        ob_top = merged_golden[f'active_{pre}_swing_ob_top_1h'].loc[idx]
        ob_bot = merged_golden[f'active_{pre}_swing_ob_bottom_1h'].loc[idx]
        fvg_top = merged_golden[f'active_{pre}_fvg_top_1h'].loc[idx]
        fvg_bot = merged_golden[f'active_{pre}_fvg_bottom_1h'].loc[idx]
        # Aritmética independente: overlap = max(bottoms) <= min(tops).
        ob_ov = (pd.notna(ob_top) and pd.notna(ob_bot)
                 and max(v2_bot, ob_bot) <= min(v2_top, ob_top))
        fvg_ov = (pd.notna(fvg_top) and pd.notna(fvg_bot)
                  and max(v2_bot, fvg_bot) <= min(v2_top, fvg_top))
        if not (ob_ov or fvg_ov):
            violations += 1
    assert violations == 0, f'{violations} armações sem overlap OB/FVG'


# ============================================================
# T-O6 — fonte legada: ote_lifecycle='legacy' ⇒ A10 byte-idêntica
# ============================================================

def test_to6_legacy_source_byte_identical(merged_golden) -> None:
    default = compute_setup_state(
        merged_golden, SetupConfig(signature='A10'))
    explicit = compute_setup_state(merged_golden, SetupConfig(
        signature='A10', ote_lifecycle='legacy',
        ote_require_eq_cross=False, ote_require_confluence=False,
    ))
    pd.testing.assert_frame_equal(default, explicit)


# ============================================================
# T-O7 — guarda de config
# ============================================================

def test_to7_flags_with_legacy_raise() -> None:
    with pytest.raises(ValueError, match="ote_lifecycle='v2'"):
        SetupConfig(ote_require_eq_cross=True)
    with pytest.raises(ValueError, match="ote_lifecycle='v2'"):
        SetupConfig(ote_require_confluence=True)
    with pytest.raises(ValueError, match="ote_lifecycle='v2'"):
        SetupConfig(ote_lifecycle='legacy', ote_require_eq_cross=True,
                    ote_require_confluence=True)
    with pytest.raises(ValueError, match='ote_lifecycle'):
        SetupConfig(ote_lifecycle='nope')


def test_to7_valid_combinations_construct() -> None:
    SetupConfig()                                      # defaults
    SetupConfig(ote_lifecycle='v2')                    # fonte v2 sem gates
    SetupConfig(ote_lifecycle='v2', ote_require_eq_cross=True)
    SetupConfig(ote_lifecycle='v2', ote_require_eq_cross=True,
                ote_require_confluence=True)
