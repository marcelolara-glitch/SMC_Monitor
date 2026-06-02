"""Trajetórias sintéticas da Wave 9.5b: motor multi-modo + A2/A4a/A5.

OBJETIVO
    Forçar, em DataFrames mergeados scriptados à mão (esperado anotado
    independente da engine), as transições das 3 novas assinaturas e dos
    modos de entrada:
    - P4 A2 (continuação): ARMED→PENDING→CONFIRMED via OB+sweep (sem FVG).
    - P5 A4a (reversão short): IFVG bear → retorno → CONFIRMED short.
    - P6 A5 (tap, modo risk): toque no OB com volume → CONFIRMED direto,
      SEM PENDING.
    - Modo risk genérico: toque → CONFIRMED sem PENDING; escape → escaped.
    - P1 regressão: A3 em `confirmation` inalterada; `hybrid` levanta.
    - D3 prioridade: empate de armação no mesmo candle → A3 vence.

NÃO FAZER
    Não gerar a fixture esperada com o próprio `compute_setup_state`.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from smc_engine import (
    compute_setup_state,
    SetupConfig,
    STATE_ARMED,
    STATE_PENDING,
    STATE_CONFIRMED,
    STATE_INVALIDATED,
    REASON_ESCAPED,
    DIRECTION_LONG,
    DIRECTION_SHORT,
)
from smc_engine.setup_state import _make_setup_id_anchors

# Banda OB long canônica: [100, 102]; banda IFVG bear: [103, 105].
OB_TOP, OB_BOT, OB_ID = 102.0, 100.0, 5
IFVG_TOP, IFVG_BOT, IFVG_ID = 105.0, 103.0, 9

# Defaults completos (todas as colunas que algum predicado pode ler).
_DEFAULTS = {
    'swing_trend_bias_4h': 1.0,
    'active_bull_swing_ob_top_1h': np.nan,
    'active_bull_swing_ob_bottom_1h': np.nan,
    'active_bull_swing_ob_id_1h': np.nan,
    'active_bull_swing_ob_volume_pct_1h': np.nan,
    'active_bear_swing_ob_top_1h': np.nan,
    'active_bear_swing_ob_bottom_1h': np.nan,
    'active_bear_swing_ob_id_1h': np.nan,
    'active_bear_swing_ob_volume_pct_1h': np.nan,
    'active_bull_fvg_top_1h': np.nan,
    'active_bull_fvg_bottom_1h': np.nan,
    'active_bull_fvg_id_1h': np.nan,
    'active_bear_fvg_top_1h': np.nan,
    'active_bear_fvg_bottom_1h': np.nan,
    'active_bear_fvg_id_1h': np.nan,
    'active_bull_ifvg_top_1h': np.nan,
    'active_bull_ifvg_bottom_1h': np.nan,
    'active_bull_ifvg_id_1h': np.nan,
    'active_bear_ifvg_top_1h': np.nan,
    'active_bear_ifvg_bottom_1h': np.nan,
    'active_bear_ifvg_id_1h': np.nan,
    'sweep_bullish_wick': False,
    'sweep_bullish_retest': False,
    'sweep_bearish_wick': False,
    'sweep_bearish_retest': False,
    'choch_internal_bullish': False,
    'choch_internal_bearish': False,
}

_ALL_COLS = ['open', 'high', 'low', 'close'] + list(_DEFAULTS)


def _build(rows: list[dict]) -> pd.DataFrame:
    n = len(rows)
    data: dict[str, list] = {c: [] for c in _ALL_COLS}
    for row in rows:
        for c in ('open', 'high', 'low', 'close'):
            data[c].append(row[c])
        for c, d in _DEFAULTS.items():
            data[c].append(row.get(c, d))
    df = pd.DataFrame(data)
    df['date'] = pd.date_range('2026-03-01', periods=n, freq='15min', tz='UTC')
    return df


def _cdl(low, high, close, open_=None, **overrides) -> dict:
    row = {
        'open': close if open_ is None else open_,
        'high': high, 'low': low, 'close': close,
    }
    row.update(overrides)
    return row


def _states(res: pd.DataFrame) -> list:
    return [s if pd.notna(s) else None for s in res['setup_state']]


# Zona OB long ativa (top/bottom/id).
_OB_LONG = {
    'active_bull_swing_ob_top_1h': OB_TOP,
    'active_bull_swing_ob_bottom_1h': OB_BOT,
    'active_bull_swing_ob_id_1h': float(OB_ID),
}
# Zona IFVG bear ativa.
_IFVG_BEAR = {
    'active_bear_ifvg_top_1h': IFVG_TOP,
    'active_bear_ifvg_bottom_1h': IFVG_BOT,
    'active_bear_ifvg_id_1h': float(IFVG_ID),
}


# ============================================================
# P4 — A2 (continuação long, OB + sweep, sem FVG)
# ============================================================

def test_a2_long_to_confirmed() -> None:
    """A2: ARMED→PENDING→CONFIRMED via OB + sweep recente (sem FVG)."""
    rows = [
        # 0: ARM — preço acima da zona + sweep bullish recente
        {**_cdl(105, 107, 106, sweep_bullish_wick=True), **_OB_LONG},
        # 1: segue ARMED
        {**_cdl(103, 104, 103.5), **_OB_LONG},
        # 2: intersecta zona → PENDING
        {**_cdl(99, 103, 101), **_OB_LONG},
        # 3: CONFIRM — choch + rejeição bullish + sweep ainda recente
        {**_cdl(98, 102, 101.8, open_=101, choch_internal_bullish=True), **_OB_LONG},
    ]
    res = compute_setup_state(_build(rows), SetupConfig(signature='A2'))
    assert _states(res) == [STATE_ARMED, STATE_ARMED, STATE_PENDING, STATE_CONFIRMED]
    assert res['setup_direction'].iloc[0] == DIRECTION_LONG
    assert res['setup_zone_low'].iloc[0] == OB_BOT
    assert res['setup_zone_high'].iloc[0] == OB_TOP
    # âncora = (ob_id,) — id estável do ARMED ao CONFIRMED
    ids = res['setup_id'].tolist()
    assert ids[:4] == [ids[0]] * 4


def test_a2_does_not_arm_without_sweep() -> None:
    """A2 sem sweep recente não arma (diferença-chave vs A3: sem FVG, com sweep)."""
    rows = [{**_cdl(105, 107, 106), **_OB_LONG}]  # sem sweep
    res = compute_setup_state(_build(rows), SetupConfig(signature='A2'))
    assert _states(res) == [None]


# ============================================================
# P5 — A4a (reversão short, IFVG bear)
# ============================================================

def test_a4a_reversal_short_to_confirmed() -> None:
    """A4a: IFVG bear presente, preço abaixo → retorno à banda → ChoCH
    bear + rejeição → CONFIRMED short. Zona = banda IFVG; sem gate de trend."""
    rows = [
        # 0: ARM SHORT — preço abaixo da banda IFVG (high < ifvg_bottom)
        {**_cdl(99, 101, 100), **_IFVG_BEAR},
        # 1: segue ARMED (ainda abaixo)
        {**_cdl(99, 101, 100), **_IFVG_BEAR},
        # 2: sobe de volta à banda → PENDING
        {**_cdl(102, 104, 103), **_IFVG_BEAR},
        # 3: CONFIRM short — choch bear + rejeição bearish
        {**_cdl(102, 106, 102.5, open_=103, choch_internal_bearish=True), **_IFVG_BEAR},
    ]
    res = compute_setup_state(_build(rows), SetupConfig(signature='A4a'))
    assert _states(res) == [STATE_ARMED, STATE_ARMED, STATE_PENDING, STATE_CONFIRMED]
    assert res['setup_direction'].iloc[0] == DIRECTION_SHORT
    assert res['setup_zone_low'].iloc[0] == IFVG_BOT
    assert res['setup_zone_high'].iloc[0] == IFVG_TOP


def test_a4a_has_no_trend_gate() -> None:
    """A4a é contra-tendência: trend 4H bull não impede um short de IFVG bear."""
    rows = [
        {**_cdl(99, 101, 100, swing_trend_bias_4h=1.0), **_IFVG_BEAR},
        {**_cdl(99, 101, 100, swing_trend_bias_4h=1.0), **_IFVG_BEAR},
    ]
    res = compute_setup_state(_build(rows), SetupConfig(signature='A4a'))
    # arma e segue ARMED apesar do trend bull (sem trend_changed)
    assert _states(res) == [STATE_ARMED, STATE_ARMED]
    assert res['setup_direction'].iloc[0] == DIRECTION_SHORT


# ============================================================
# P6 — A5 (tap, modo risk)
# ============================================================

_OB_LONG_VOL = {**_OB_LONG, 'active_bull_swing_ob_volume_pct_1h': 0.5}


def test_a5_risk_tap_to_confirmed_no_pending() -> None:
    """A5 risk: ARMED → CONFIRMED direto no toque, SEM PENDING (D2)."""
    rows = [
        {**_cdl(105, 107, 106), **_OB_LONG_VOL},   # ARM (volume_pct 0.5 > 0.2)
        {**_cdl(99, 103, 101), **_OB_LONG_VOL},    # toque → CONFIRMED direto
    ]
    res = compute_setup_state(
        _build(rows), SetupConfig(signature='A5', entry_mode='risk'),
    )
    assert _states(res) == [STATE_ARMED, STATE_CONFIRMED]
    assert STATE_PENDING not in _states(res)


def test_a5_does_not_arm_below_volume_threshold() -> None:
    """A5 não arma se volume_pct <= volume_pct_min."""
    low_vol = {**_OB_LONG, 'active_bull_swing_ob_volume_pct_1h': 0.1}
    rows = [{**_cdl(105, 107, 106), **low_vol}]
    res = compute_setup_state(
        _build(rows), SetupConfig(signature='A5', entry_mode='risk'),
    )
    assert _states(res) == [None]


# ============================================================
# Modo risk genérico (§6): toque → CONFIRMED; escape → escaped
# ============================================================

def test_risk_mode_escape_before_touch() -> None:
    """Risk: preço escapa antes do toque → INVALIDATED(escaped)."""
    rows = [
        {**_cdl(105, 107, 106), **_OB_LONG_VOL},   # ARM
        {**_cdl(110, 112, 111), **_OB_LONG_VOL},   # low>104.04 → escaped
    ]
    res = compute_setup_state(
        _build(rows), SetupConfig(signature='A5', entry_mode='risk'),
    )
    assert _states(res) == [STATE_ARMED, STATE_INVALIDATED]
    assert res['setup_invalidation_reason'].iloc[1] == REASON_ESCAPED


def test_risk_mode_never_emits_pending() -> None:
    """Em risk, mesmo uma trajetória longa nunca passa por PENDING."""
    rows = [{**_cdl(105, 107, 106), **_OB_LONG_VOL}]
    for _ in range(5):
        rows.append({**_cdl(100.5, 101.5, 101.0), **_OB_LONG_VOL})  # dentro da zona
    res = compute_setup_state(
        _build(rows), SetupConfig(signature='A5', entry_mode='risk'),
    )
    assert STATE_PENDING not in _states(res)
    assert STATE_CONFIRMED in _states(res)


# ============================================================
# P1 — regressão multi-modo + hybrid stub
# ============================================================

def test_a3_confirmation_equals_default() -> None:
    """A3 com entry_mode='confirmation' explícito == default (regressão P1)."""
    fvg = {
        'active_bull_fvg_top_1h': 103.0,
        'active_bull_fvg_bottom_1h': 101.0,
        'active_bull_fvg_id_1h': 7.0,
    }
    rows = [
        {**_cdl(105, 107, 106), **_OB_LONG, **fvg},
        {**_cdl(99, 103, 101), **_OB_LONG, **fvg},
        {**_cdl(98, 102, 101.8, open_=101, choch_internal_bullish=True,
                sweep_bullish_wick=True), **_OB_LONG, **fvg},
    ]
    df = _build(rows)
    default = compute_setup_state(df)
    explicit = compute_setup_state(
        df, SetupConfig(signature='A3', entry_mode='confirmation'),
    )
    pd.testing.assert_frame_equal(default, explicit)


def test_hybrid_raises_not_implemented() -> None:
    """D1: entry_mode='hybrid' levanta NotImplementedError com ponteiro."""
    rows = [{**_cdl(105, 107, 106), **_OB_LONG}]
    with pytest.raises(NotImplementedError, match='hybrid'):
        compute_setup_state(_build(rows), SetupConfig(entry_mode='hybrid'))


def test_invalid_entry_mode_rejected() -> None:
    with pytest.raises(ValueError, match='entry_mode'):
        SetupConfig(entry_mode='nope')


def test_invalid_signature_rejected() -> None:
    with pytest.raises(ValueError, match='signature'):
        SetupConfig(signature='A99')


# ============================================================
# D3 — prioridade: empate de armação no mesmo candle → A3 vence
# ============================================================

def test_priority_a3_beats_a2_on_tie() -> None:
    """Quando A3 e A2 armam no mesmo candle, A3 (prioridade 0) vence."""
    fvg = {
        'active_bull_fvg_top_1h': 103.0,
        'active_bull_fvg_bottom_1h': 101.0,
        'active_bull_fvg_id_1h': 7.0,
    }
    # candle arma A3 (OB+FVG adjacentes) e A2 (OB+sweep) simultaneamente
    rows = [{**_cdl(105, 107, 106, sweep_bullish_wick=True), **_OB_LONG, **fvg}]
    df = _build(rows)
    res = compute_setup_state(df, SetupConfig(signature=('A2', 'A3')))
    assert _states(res) == [STATE_ARMED]
    # id == id da A3 (âncoras ob_id, fvg_id), não da A2 (só ob_id)
    expected_a3 = _make_setup_id_anchors(
        'A3', DIRECTION_LONG, (float(OB_ID), 7.0), df['date'].iloc[0],
    )
    assert res['setup_id'].iloc[0] == expected_a3
