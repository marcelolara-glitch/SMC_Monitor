"""Trajetórias sintéticas da Wave 9.5e: assinaturas A7 (Silver Bullet) + A10 (OTE).

OBJETIVO
    Forçar, em DataFrames mergeados scriptados à mão (esperado anotado
    independente da engine), as transições das 2 novas assinaturas:
    - A10 (OTE, continuação): banda OTE da direção + ChoCH + rejeição →
      ARMED→PENDING→CONFIRMED. **Não inverte** direção (bull→long,
      bear→short, por construção do hook); não arma fora da zona / sem OTE.
    - A7 (Silver Bullet, continuação): FVG(dir) + sweep recente + killzone
      ativa → arma; gate de killzone só na armação; exige sweep e FVG.

    Mais um teste de regressão de prioridade: com `signature=('A3','A10')`,
    no candle em que ambas armariam, A3 (priority 0) vence A10 (priority 8).

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
    DIRECTION_LONG,
    DIRECTION_SHORT,
)
from smc_engine.setup_state import _make_setup_id_anchors

# Bandas canônicas (zonas como qualquer outra: top/bottom/id).
OB_TOP, OB_BOT, OB_ID = 102.0, 100.0, 5
FVG_TOP, FVG_BOT, FVG_ID = 102.0, 100.0, 7
OTE_TOP, OTE_BOT, OTE_ID = 102.0, 100.0, 9
# Banda OTE premium (short), acima do preço inicial.
OTE_BEAR_TOP, OTE_BEAR_BOT, OTE_BEAR_ID = 105.0, 103.0, 12

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
    'active_bull_ote_top_1h': np.nan,
    'active_bull_ote_bottom_1h': np.nan,
    'active_bull_ote_id_1h': np.nan,
    'active_bear_ote_top_1h': np.nan,
    'active_bear_ote_bottom_1h': np.nan,
    'active_bear_ote_id_1h': np.nan,
    'sweep_bullish_wick': False,
    'sweep_bullish_retest': False,
    'sweep_bearish_wick': False,
    'sweep_bearish_retest': False,
    'choch_internal_bullish': False,
    'choch_internal_bearish': False,
    'in_kz_silver_bullet_am': False,
    'in_kz_silver_bullet_late': False,
    'in_kz_silver_bullet_pm': False,
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


_OTE_BULL = {
    'active_bull_ote_top_1h': OTE_TOP,
    'active_bull_ote_bottom_1h': OTE_BOT,
    'active_bull_ote_id_1h': float(OTE_ID),
}
_OTE_BEAR = {
    'active_bear_ote_top_1h': OTE_BEAR_TOP,
    'active_bear_ote_bottom_1h': OTE_BEAR_BOT,
    'active_bear_ote_id_1h': float(OTE_BEAR_ID),
}
_FVG_BULL = {
    'active_bull_fvg_top_1h': FVG_TOP,
    'active_bull_fvg_bottom_1h': FVG_BOT,
    'active_bull_fvg_id_1h': float(FVG_ID),
}
_OB_BULL = {
    'active_bull_swing_ob_top_1h': OB_TOP,
    'active_bull_swing_ob_bottom_1h': OB_BOT,
    'active_bull_swing_ob_id_1h': float(OB_ID),
}


# ============================================================
# A10 — OTE (Fib 62–79%), continuação trend-gated
# ============================================================

def test_a10_long_to_confirmed() -> None:
    """A10: trend +1 + OTE bull (banda discount) → ARMED→PENDING→CONFIRMED."""
    rows = [
        # 0: ARM long — OTE bull presente, preço acima da banda
        {**_cdl(105, 107, 106), **_OTE_BULL},
        # 1: segue ARMED
        {**_cdl(103, 104, 103.5), **_OTE_BULL},
        # 2: intersecta a banda → PENDING
        {**_cdl(99, 103, 101), **_OTE_BULL},
        # 3: CONFIRM — choch bull + rejeição bullish (A10 não exige sweep)
        {**_cdl(98, 102, 101.8, open_=101, choch_internal_bullish=True), **_OTE_BULL},
    ]
    res = compute_setup_state(_build(rows), SetupConfig(signature='A10'))
    assert _states(res) == [STATE_ARMED, STATE_ARMED, STATE_PENDING, STATE_CONFIRMED]
    assert res['setup_direction'].iloc[0] == DIRECTION_LONG
    assert res['setup_zone_low'].iloc[0] == OTE_BOT
    assert res['setup_zone_high'].iloc[0] == OTE_TOP


def test_a10_short_to_confirmed() -> None:
    """A10 simétrico: trend −1 + OTE bear (banda premium) → CONFIRMED short."""
    rows = [
        # 0: ARM short — OTE bear acima do preço (high < zlow)
        {**_cdl(99, 101, 100, swing_trend_bias_4h=-1.0), **_OTE_BEAR},
        {**_cdl(99, 101, 100, swing_trend_bias_4h=-1.0), **_OTE_BEAR},
        # 2: sobe à banda [103, 105] → PENDING
        {**_cdl(102, 104, 103, swing_trend_bias_4h=-1.0), **_OTE_BEAR},
        # 3: CONFIRM short — choch bear + rejeição bearish
        {**_cdl(102, 106, 102.5, open_=103, choch_internal_bearish=True,
                swing_trend_bias_4h=-1.0), **_OTE_BEAR},
    ]
    res = compute_setup_state(_build(rows), SetupConfig(signature='A10'))
    assert _states(res) == [STATE_ARMED, STATE_ARMED, STATE_PENDING, STATE_CONFIRMED]
    assert res['setup_direction'].iloc[0] == DIRECTION_SHORT
    assert res['setup_zone_low'].iloc[0] == OTE_BEAR_BOT
    assert res['setup_zone_high'].iloc[0] == OTE_BEAR_TOP


def test_a10_does_not_invert_direction() -> None:
    """A10 não inverte (D3): trend +1 (long) com só OTE bear presente não
    encontra zona bull → não arma."""
    rows = [{**_cdl(105, 107, 106), **_OTE_BEAR}]  # trend +1, só bear OTE
    res = compute_setup_state(_build(rows), SetupConfig(signature='A10'))
    assert _states(res) == [None]


def test_a10_does_not_arm_without_ote() -> None:
    """A10 sem OTE presente (id NaN) não arma."""
    rows = [{**_cdl(105, 107, 106)}]  # sem _OTE_BULL
    res = compute_setup_state(_build(rows), SetupConfig(signature='A10'))
    assert _states(res) == [None]


# ============================================================
# A7 — Silver Bullet (Sweep + FVG + killzone), continuação
# ============================================================

def test_a7_arms_inside_killzone() -> None:
    """A7 caso A: FVG(dir) + sweep recente + killzone AM ativa → arma long."""
    rows = [{**_cdl(105, 107, 106, sweep_bullish_wick=True,
                    in_kz_silver_bullet_am=True), **_FVG_BULL}]
    res = compute_setup_state(_build(rows), SetupConfig(signature='A7'))
    assert _states(res) == [STATE_ARMED]
    assert res['setup_direction'].iloc[0] == DIRECTION_LONG
    assert res['setup_zone_low'].iloc[0] == FVG_BOT
    assert res['setup_zone_high'].iloc[0] == FVG_TOP


def test_a7_does_not_arm_outside_killzone() -> None:
    """A7 caso B: as 3 colunas `in_kz_*` False → não arma (gate killzone)."""
    rows = [{**_cdl(105, 107, 106, sweep_bullish_wick=True), **_FVG_BULL}]
    res = compute_setup_state(_build(rows), SetupConfig(signature='A7'))
    assert _states(res) == [None]


def test_a7_requires_sweep() -> None:
    """A7 sem sweep recente (mas dentro da killzone, com FVG) não arma."""
    rows = [{**_cdl(105, 107, 106, in_kz_silver_bullet_am=True), **_FVG_BULL}]
    res = compute_setup_state(_build(rows), SetupConfig(signature='A7'))
    assert _states(res) == [None]


def test_a7_requires_fvg() -> None:
    """A7 sem FVG (mas com sweep + killzone) não arma."""
    rows = [{**_cdl(105, 107, 106, sweep_bullish_wick=True,
                    in_kz_silver_bullet_am=True)}]  # sem _FVG_BULL
    res = compute_setup_state(_build(rows), SetupConfig(signature='A7'))
    assert _states(res) == [None]


def test_a7_long_to_confirmed() -> None:
    """A7 trajetória completa: arma na killzone, confirma depois (gate de
    killzone só na armação) via ChoCH + rejeição + sweep recente."""
    rows = [
        # 0: ARM — FVG + sweep + killzone AM, preço acima da banda
        {**_cdl(105, 107, 106, sweep_bullish_wick=True,
                in_kz_silver_bullet_am=True), **_FVG_BULL},
        # 1: fora da killzone, segue ARMED (gate só na armação)
        {**_cdl(103, 104, 103.5), **_FVG_BULL},
        # 2: intersecta a banda → PENDING
        {**_cdl(99, 103, 101), **_FVG_BULL},
        # 3: CONFIRM — choch bull + rejeição; sweep do candle 0 ainda recente
        {**_cdl(98, 102, 101.8, open_=101, choch_internal_bullish=True), **_FVG_BULL},
    ]
    res = compute_setup_state(_build(rows), SetupConfig(signature='A7'))
    assert _states(res) == [STATE_ARMED, STATE_ARMED, STATE_PENDING, STATE_CONFIRMED]
    assert res['setup_direction'].iloc[0] == DIRECTION_LONG


# ============================================================
# Regressão de prioridade — A3 (0) vence A10 (8) no empate
# ============================================================

def test_priority_a3_beats_a10_on_tie() -> None:
    """Com `signature=('A3','A10')`, num candle em que ambas armariam, A3
    (priority 0) vence A10 (priority 8): a zona emitida é a do OB (A3)."""
    rows = [{**_cdl(105, 107, 106), **_OB_BULL, **_FVG_BULL, **_OTE_BULL}]
    df = _build(rows)
    res = compute_setup_state(df, SetupConfig(signature=('A3', 'A10')))
    assert _states(res) == [STATE_ARMED]
    assert res['setup_direction'].iloc[0] == DIRECTION_LONG
    # id == id da A3 (âncoras ob_id, fvg_id), não da A10 (só ote_id) →
    # discrimina o vencedor mesmo quando as bandas coincidem em valor.
    expected_a3 = _make_setup_id_anchors(
        'A3', DIRECTION_LONG, (float(OB_ID), float(FVG_ID)), df['date'].iloc[0],
    )
    assert res['setup_id'].iloc[0] == expected_a3
