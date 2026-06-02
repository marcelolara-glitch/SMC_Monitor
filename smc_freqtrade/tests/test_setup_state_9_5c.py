"""Trajetórias sintéticas da Wave 9.5c: catálogo A1/A9/A6.

OBJETIVO
    Forçar, em DataFrames mergeados scriptados à mão (esperado anotado
    independente da engine), as transições das 3 novas assinaturas:
    - A1 (continuação): ARMED→PENDING→CONFIRMED via OB + CHoCH + rejeição,
      **sem** sweep (distingue de A2) e **sem** FVG (distingue de A3).
    - A9 (reversão): sweep de fundos + OB long + retorno → CONFIRMED long,
      **sem** gate de trend (arma/confirma mesmo com trend contrário).
    - A6 (ICT Unicorn, reversão): OB bull mitigado vira breaker bearish +
      FVG bearish sobreposto → CONFIRMED **short** (armadilha de direção);
      a âncora (breaker_id, fvg_id) derruba o setup se o FVG sumir.

    Mais um cenário negativo por assinatura (falta um critério → não arma
    ou invalida pelo motivo esperado).

NÃO FAZER
    Não gerar a fixture esperada com o próprio `compute_setup_state`.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from smc_engine import (
    compute_setup_state,
    SetupConfig,
    STATE_ARMED,
    STATE_PENDING,
    STATE_CONFIRMED,
    STATE_INVALIDATED,
    REASON_MITIGATED,
    DIRECTION_LONG,
    DIRECTION_SHORT,
)

# Banda OB long canônica: [100, 102]; banda breaker/FVG bear: [103, 105].
OB_TOP, OB_BOT, OB_ID = 102.0, 100.0, 5
BRK_TOP, BRK_BOT, BRK_ID = 105.0, 103.0, 11
FVG_BEAR_TOP, FVG_BEAR_BOT, FVG_BEAR_ID = 105.0, 103.0, 4

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
    'active_bull_breaker_top_1h': np.nan,
    'active_bull_breaker_bottom_1h': np.nan,
    'active_bull_breaker_id_1h': np.nan,
    'active_bear_breaker_top_1h': np.nan,
    'active_bear_breaker_bottom_1h': np.nan,
    'active_bear_breaker_id_1h': np.nan,
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


_OB_LONG = {
    'active_bull_swing_ob_top_1h': OB_TOP,
    'active_bull_swing_ob_bottom_1h': OB_BOT,
    'active_bull_swing_ob_id_1h': float(OB_ID),
}
_BREAKER_BEAR = {
    'active_bear_breaker_top_1h': BRK_TOP,
    'active_bear_breaker_bottom_1h': BRK_BOT,
    'active_bear_breaker_id_1h': float(BRK_ID),
}
_FVG_BEAR = {
    'active_bear_fvg_top_1h': FVG_BEAR_TOP,
    'active_bear_fvg_bottom_1h': FVG_BEAR_BOT,
    'active_bear_fvg_id_1h': float(FVG_BEAR_ID),
}


# ============================================================
# A1 — OB Retest + CHoCH (continuação long), sem sweep, sem FVG
# ============================================================

def test_a1_long_to_confirmed_without_sweep() -> None:
    """A1: ARMED→PENDING→CONFIRMED com OB + CHoCH + rejeição, SEM sweep."""
    rows = [
        # 0: ARM — trend long, OB presente, preço acima da zona, sem sweep
        {**_cdl(105, 107, 106), **_OB_LONG},
        # 1: segue ARMED
        {**_cdl(103, 104, 103.5), **_OB_LONG},
        # 2: intersecta zona → PENDING
        {**_cdl(99, 103, 101), **_OB_LONG},
        # 3: CONFIRM — choch bull + rejeição bullish (sem exigir sweep)
        {**_cdl(98, 102, 101.8, open_=101, choch_internal_bullish=True), **_OB_LONG},
    ]
    res = compute_setup_state(_build(rows), SetupConfig(signature='A1'))
    assert _states(res) == [STATE_ARMED, STATE_ARMED, STATE_PENDING, STATE_CONFIRMED]
    assert res['setup_direction'].iloc[0] == DIRECTION_LONG
    assert res['setup_zone_low'].iloc[0] == OB_BOT
    assert res['setup_zone_high'].iloc[0] == OB_TOP


def test_a1_does_not_arm_without_ob() -> None:
    """A1 sem OB presente não arma (OB é o único insumo de armação)."""
    rows = [{**_cdl(105, 107, 106)}]  # sem _OB_LONG
    res = compute_setup_state(_build(rows), SetupConfig(signature='A1'))
    assert _states(res) == [None]


# ============================================================
# A9 — EQH/EQL Sweep + CHoCH (reversão), sem gate de trend
# ============================================================

def test_a9_reversal_long_no_trend_gate() -> None:
    """A9: sweep de fundos (→ sweep_bullish) + OB long → CONFIRMED long,
    mesmo com trend 4H contrário (short). Sem trend gate (reversão)."""
    rows = [
        # 0: ARM long — sweep bullish recente + OB long + preço acima; trend SHORT
        {**_cdl(105, 107, 106, sweep_bullish_wick=True,
                swing_trend_bias_4h=-1.0), **_OB_LONG},
        {**_cdl(103, 104, 103.5, swing_trend_bias_4h=-1.0), **_OB_LONG},
        # 2: intersecta zona → PENDING
        {**_cdl(99, 103, 101, swing_trend_bias_4h=-1.0), **_OB_LONG},
        # 3: CONFIRM long — choch bull + rejeição (sem exigir sweep no confirm)
        {**_cdl(98, 102, 101.8, open_=101, choch_internal_bullish=True,
                swing_trend_bias_4h=-1.0), **_OB_LONG},
    ]
    res = compute_setup_state(_build(rows), SetupConfig(signature='A9'))
    assert _states(res) == [STATE_ARMED, STATE_ARMED, STATE_PENDING, STATE_CONFIRMED]
    assert res['setup_direction'].iloc[0] == DIRECTION_LONG


def test_a9_does_not_arm_without_sweep() -> None:
    """A9 sem sweep recente: direção indefinida → não arma."""
    rows = [{**_cdl(105, 107, 106), **_OB_LONG}]  # sem sweep
    res = compute_setup_state(_build(rows), SetupConfig(signature='A9'))
    assert _states(res) == [None]


# ============================================================
# A6 — ICT Unicorn (Breaker + FVG) (reversão short)
# ============================================================

def test_a6_unicorn_short_to_confirmed() -> None:
    """A6: breaker bear + FVG bear sobreposto → CONFIRMED **short**
    (armadilha de direção D-C4: não long)."""
    rows = [
        # 0: ARM short — breaker+FVG bear sobrepostos, preço abaixo (high<103)
        {**_cdl(99, 101, 100), **_BREAKER_BEAR, **_FVG_BEAR},
        {**_cdl(99, 101, 100), **_BREAKER_BEAR, **_FVG_BEAR},
        # 2: sobe de volta à banda → PENDING
        {**_cdl(102, 104, 103), **_BREAKER_BEAR, **_FVG_BEAR},
        # 3: CONFIRM short — choch bear + rejeição bearish
        {**_cdl(102, 106, 102.5, open_=103, choch_internal_bearish=True),
         **_BREAKER_BEAR, **_FVG_BEAR},
    ]
    res = compute_setup_state(_build(rows), SetupConfig(signature='A6'))
    assert _states(res) == [STATE_ARMED, STATE_ARMED, STATE_PENDING, STATE_CONFIRMED]
    assert res['setup_direction'].iloc[0] == DIRECTION_SHORT
    assert res['setup_zone_low'].iloc[0] == BRK_BOT
    assert res['setup_zone_high'].iloc[0] == BRK_TOP


def test_a6_does_not_arm_without_fvg() -> None:
    """A6 sem FVG (só breaker) não arma — exige sobreposição breaker↔FVG."""
    rows = [{**_cdl(99, 101, 100), **_BREAKER_BEAR}]  # sem FVG
    res = compute_setup_state(_build(rows), SetupConfig(signature='A6'))
    assert _states(res) == [None]


def test_a6_invalidated_when_fvg_anchor_vanishes() -> None:
    """A âncora (breaker_id, fvg_id): se o FVG sumir, o setup ARMED cai por
    `mitigated` (briefing §3.4 — o fvg_id participa da âncora)."""
    rows = [
        {**_cdl(99, 101, 100), **_BREAKER_BEAR, **_FVG_BEAR},   # ARM short
        {**_cdl(99, 101, 100), **_BREAKER_BEAR},                # FVG sumiu
    ]
    res = compute_setup_state(_build(rows), SetupConfig(signature='A6'))
    assert _states(res) == [STATE_ARMED, STATE_INVALIDATED]
    assert res['setup_invalidation_reason'].iloc[1] == REASON_MITIGATED
