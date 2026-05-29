"""Trajetória sintética determinística da máquina de estados A3 (Wave 9.5a §5.3-§5.4).

OBJETIVO
    Forçar, em candles conhecidos de DataFrames mergeados scriptados à
    mão, cada transição da máquina de estados:
    vazio→ARMED→PENDING_CONFIRMATION→CONFIRMED e cada caminho de
    INVALIDATED (escaped, timeout, trend_changed, zone_crossed,
    mitigated). Assertions candle-a-candle na coluna `setup_state`.

    O esperado é anotado à mão, **independente da engine** (o df é
    construído sem chamar `analyze()` — evita circularidade).

FONTE DE DADOS
    DataFrames sintéticos construídos por `_build_merged_df` com as
    colunas `_4h`/`_1h`/15m que `compute_setup_state` consome (S4).

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
    REASON_ESCAPED,
    REASON_TIMEOUT,
    REASON_TREND_CHANGED,
    REASON_ZONE_CROSSED,
    REASON_MITIGATED,
)

# Zona LONG canônica usada nas trajetórias: OB [100, 102], FVG [101, 103]
# (sobrepostas → adjacentes). ob_mid = 101.
OB_TOP, OB_BOT, OB_ID = 102.0, 100.0, 5
FVG_TOP, FVG_BOT, FVG_ID = 103.0, 101.0, 7

# Colunas que `compute_setup_state` consome.
_ZONE_DEFAULTS = {
    'swing_trend_bias_4h': 1.0,
    'active_bull_swing_ob_top_1h': OB_TOP,
    'active_bull_swing_ob_bottom_1h': OB_BOT,
    'active_bull_swing_ob_id_1h': float(OB_ID),
    'active_bull_fvg_top_1h': FVG_TOP,
    'active_bull_fvg_bottom_1h': FVG_BOT,
    'active_bull_fvg_id_1h': float(FVG_ID),
    'active_bear_swing_ob_top_1h': np.nan,
    'active_bear_swing_ob_bottom_1h': np.nan,
    'active_bear_swing_ob_id_1h': np.nan,
    'active_bear_fvg_top_1h': np.nan,
    'active_bear_fvg_bottom_1h': np.nan,
    'active_bear_fvg_id_1h': np.nan,
    'sweep_bullish_wick': False,
    'sweep_bullish_retest': False,
    'sweep_bearish_wick': False,
    'sweep_bearish_retest': False,
    'choch_internal_bullish': False,
    'choch_internal_bearish': False,
}

_ALL_COLS = ['open', 'high', 'low', 'close'] + list(_ZONE_DEFAULTS)


def _states(res: pd.DataFrame) -> list:
    """Coluna setup_state como lista com <NA>/None normalizado para None."""
    return [s if pd.notna(s) else None for s in res['setup_state']]


def _build_merged_df(rows: list[dict]) -> pd.DataFrame:
    """Constrói um df mergeado à mão a partir de uma lista de row-dicts.

    Chaves ausentes em cada row recebem o default de `_ZONE_DEFAULTS`;
    OHLC deve ser sempre fornecido. `date` é gerada (15m).
    """
    n = len(rows)
    data: dict[str, list] = {col: [] for col in _ALL_COLS}
    for row in rows:
        for col in ('open', 'high', 'low', 'close'):
            data[col].append(row[col])
        for col, default in _ZONE_DEFAULTS.items():
            data[col].append(row.get(col, default))
    df = pd.DataFrame(data)
    df['date'] = pd.date_range('2026-03-01', periods=n, freq='15min', tz='UTC')
    return df


def _candle(low, high, close, open_=None, **overrides) -> dict:
    """Atalho para construir um candle; open default = close."""
    row = {
        'open': close if open_ is None else open_,
        'high': high, 'low': low, 'close': close,
    }
    row.update(overrides)
    return row


# Candle que mantém ARMED: preço acima da zona, sem intersectar nem
# escapar (escape threshold = 102 * 1.02 = 104.04).
def _hold_armed() -> dict:
    return _candle(low=103.0, high=104.0, close=103.5)


def test_trajectory_long_to_confirmed():
    """vazio→ARMED→PENDING_CONFIRMATION→CONFIRMED, candle-a-candle."""
    rows = [
        # 0: ARM — preço acima da zona (low > OB_TOP)
        _candle(low=105.0, high=107.0, close=106.0),
        # 1: segue ARMED
        _hold_armed(),
        # 2: intersecta zona → PENDING (low<=102 e high>=100)
        _candle(low=99.0, high=103.0, close=101.0),
        # 3: segue PENDING; arma o sweep recente (catalisador)
        _candle(low=100.0, high=102.0, close=101.0, sweep_bullish_wick=True),
        # 4: CONFIRM — choch + rejeição bullish + sweep recente
        #    rng=4; (min(o,c)-low)/rng = (101-98)/4 = 0.75 >= 0.5;
        #    close 101.8 >= low + 0.667*rng = 98 + 2.668 = 100.668
        _candle(low=98.0, high=102.0, close=101.8, open_=101.0,
                choch_internal_bullish=True),
        # 5: setup resolvido → vazio; preço dentro da zona não re-arma
        _candle(low=101.0, high=101.5, close=101.2),
    ]
    res = compute_setup_state(_build_merged_df(rows))
    expected = [STATE_ARMED, STATE_ARMED, STATE_PENDING, STATE_PENDING,
                STATE_CONFIRMED, None]
    assert _states(res) == expected
    # setup_id estável e presente do ARMED ao CONFIRMED
    ids = res['setup_id'].tolist()
    assert ids[0] is not None and ids[:5] == [ids[0]] * 5
    assert pd.isna(ids[5])
    # direção e zona corretas
    assert res['setup_direction'].iloc[0] == 'long'
    assert res['setup_zone_low'].iloc[0] == OB_BOT
    assert res['setup_zone_high'].iloc[0] == OB_TOP


def test_trajectory_invalidated_escaped():
    """ARMED → INVALIDATED(escaped): preço >2% acima da zona sem entrar."""
    rows = [
        _candle(low=105.0, high=107.0, close=106.0),   # ARM
        _candle(low=110.0, high=112.0, close=111.0),   # low>104.04 → escaped
    ]
    res = compute_setup_state(_build_merged_df(rows))
    assert _states(res) == [STATE_ARMED, STATE_INVALIDATED]
    assert res['setup_invalidation_reason'].iloc[1] == REASON_ESCAPED


def test_trajectory_invalidated_trend_changed():
    """ARMED → INVALIDATED(trend_changed): trend 4H deixa de ser +1."""
    rows = [
        _candle(low=105.0, high=107.0, close=106.0),                 # ARM
        _candle(low=103.0, high=104.0, close=103.5,
                swing_trend_bias_4h=-1.0),                           # trend flip
    ]
    res = compute_setup_state(_build_merged_df(rows))
    assert _states(res) == [STATE_ARMED, STATE_INVALIDATED]
    assert res['setup_invalidation_reason'].iloc[1] == REASON_TREND_CHANGED


def test_trajectory_invalidated_mitigated():
    """ARMED → INVALIDATED(mitigated): a zona OB promovida some (id→NaN)."""
    rows = [
        _candle(low=105.0, high=107.0, close=106.0),                  # ARM
        _candle(low=103.0, high=104.0, close=103.5,
                active_bull_swing_ob_id_1h=np.nan),                   # zona sumiu
    ]
    res = compute_setup_state(_build_merged_df(rows))
    assert _states(res) == [STATE_ARMED, STATE_INVALIDATED]
    assert res['setup_invalidation_reason'].iloc[1] == REASON_MITIGATED


def test_trajectory_invalidated_timeout_armed():
    """ARMED → INVALIDATED(timeout): armed_timeout_candles sem entrar."""
    cfg = SetupConfig()
    rows = [_candle(low=105.0, high=107.0, close=106.0)]              # ARM em 0
    # candles 1..armed_timeout: seguem ARMED (sem intersect/escape)
    for _ in range(cfg.armed_timeout_candles):
        rows.append(_hold_armed())
    res = compute_setup_state(_build_merged_df(rows), cfg)
    states = res['setup_state'].tolist()
    # ARMED de 0 até armed_timeout-1; INVALIDATED em armed_timeout
    assert states[:cfg.armed_timeout_candles] == [STATE_ARMED] * cfg.armed_timeout_candles
    assert states[cfg.armed_timeout_candles] == STATE_INVALIDATED
    assert res['setup_invalidation_reason'].iloc[cfg.armed_timeout_candles] == REASON_TIMEOUT


def test_trajectory_invalidated_zone_crossed():
    """PENDING → INVALIDATED(zone_crossed): close abaixo de toda a zona."""
    rows = [
        _candle(low=105.0, high=107.0, close=106.0),   # ARM
        _candle(low=99.0, high=103.0, close=101.0),    # intersect → PENDING
        _candle(low=97.0, high=99.0, close=98.0),      # close<100 → zone_crossed
    ]
    res = compute_setup_state(_build_merged_df(rows))
    assert _states(res) == [
        STATE_ARMED, STATE_PENDING, STATE_INVALIDATED,
    ]
    assert res['setup_invalidation_reason'].iloc[2] == REASON_ZONE_CROSSED


def test_a3_does_not_confirm_without_sweep():
    """§5.4: trajetória idêntica à de confirmação mas SEM sweep recente
    → permanece PENDING e timeouta; nunca CONFIRMED."""
    cfg = SetupConfig()
    rows = [
        _candle(low=105.0, high=107.0, close=106.0),   # 0: ARM
        _candle(low=99.0, high=103.0, close=101.0),    # 1: intersect → PENDING
    ]
    pending_start = 1
    # candles em PENDING com choch+rejeição mas SEM sweep: confirm falha.
    for _ in range(cfg.pending_timeout_candles):
        rows.append(_candle(low=98.0, high=102.0, close=101.8, open_=101.0,
                            choch_internal_bullish=True))
    res = compute_setup_state(_build_merged_df(rows), cfg)
    states = res['setup_state'].tolist()
    assert STATE_CONFIRMED not in states
    # PENDING do candle 1 até o timeout; INVALIDATED(timeout) ao fim.
    timeout_idx = pending_start + cfg.pending_timeout_candles
    assert states[pending_start] == STATE_PENDING
    assert states[timeout_idx] == STATE_INVALIDATED
    assert res['setup_invalidation_reason'].iloc[timeout_idx] == REASON_TIMEOUT


def test_short_trajectory_to_pending():
    """Direção SHORT (simétrica): vazio→ARMED→PENDING via zona bear."""
    bear_defaults = {
        'swing_trend_bias_4h': -1.0,
        'active_bull_swing_ob_id_1h': np.nan,
        'active_bull_fvg_id_1h': np.nan,
        'active_bear_swing_ob_top_1h': OB_TOP,
        'active_bear_swing_ob_bottom_1h': OB_BOT,
        'active_bear_swing_ob_id_1h': float(OB_ID),
        'active_bear_fvg_top_1h': FVG_TOP,
        'active_bear_fvg_bottom_1h': FVG_BOT,
        'active_bear_fvg_id_1h': float(FVG_ID),
    }
    rows = [
        # 0: ARM SHORT — preço abaixo da zona (high < OB_BOT)
        {**_candle(low=95.0, high=98.0, close=96.0), **bear_defaults},
        # 1: intersecta zona → PENDING
        {**_candle(low=99.0, high=103.0, close=101.0), **bear_defaults},
    ]
    res = compute_setup_state(_build_merged_df(rows))
    assert _states(res) == [STATE_ARMED, STATE_PENDING]
    assert res['setup_direction'].iloc[0] == 'short'
