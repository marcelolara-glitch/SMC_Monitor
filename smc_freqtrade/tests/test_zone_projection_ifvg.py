"""Projetor IFVG + volume_pct do OB swing (Wave 9.5b §5.3, P3).

OBJETIVO
    Cobrir o critério verificável P3: o projetor de zona IFVG inverte a
    direção corretamente (FVG **bearish** mitigado surge em
    `active_bull_ifvg_*`; FVG **bullish** mitigado em `active_bear_ifvg_*`)
    e a zona é ativa **só** em `(t_mitigation, t_invalidation)` — vazia
    antes da mitigação e após a invalidação. Mais a promoção do
    `volume_pct` do OB swing vencedor (A5/D5).

    Expectativas anotadas à mão sobre ledgers construídos diretamente
    (sem rodar `analyze()`) — sem circularidade.

NÃO FAZER
    Não gerar a fixture esperada a partir do próprio projetor.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from smc_engine import promote_active_zones
from smc_engine.types import BEARISH, BULLISH

_FVG_COLS = [
    'fvg_id', 'bias', 'top', 'bottom', 'bar_time', 't_creation',
    't_mitigation', 't_invalidation', 'state', 'is_inverse', 'is_double',
]
_OB_COLS = [
    'ob_id', 'scope', 'bias', 'bar_high', 'bar_low', 'bar_time',
    't_creation', 't_mitigation', 't_invalidation', 'state',
    'volume_bullish', 'volume_bearish', 'volume_total', 'volume_pct',
    'bb_volume',
]


def _dates(n: int) -> pd.DatetimeIndex:
    return pd.date_range('2026-03-01', periods=n, freq='15min', tz='UTC')


def _empty_ob() -> pd.DataFrame:
    return pd.DataFrame({c: pd.Series(dtype='object') for c in _OB_COLS})


def _df(dates, close: float = 104.0) -> pd.DataFrame:
    return pd.DataFrame({'date': dates, 'close': [close] * len(dates)})


def test_bullish_fvg_mitigated_appears_in_bear_ifvg() -> None:
    """Armadilha de rótulo (P3): FVG **bullish** mitigado → zona BEAR
    negociável, ativa só em (t_mitigation, t_invalidation)."""
    dates = _dates(10)
    fvg = pd.DataFrame([{
        'fvg_id': 1, 'bias': BULLISH, 'top': 105.0, 'bottom': 103.0,
        'bar_time': dates[0], 't_creation': dates[2],
        't_mitigation': dates[4], 't_invalidation': dates[7],
        'state': 'inverse_broken', 'is_inverse': True, 'is_double': False,
    }], columns=_FVG_COLS)
    out = promote_active_zones(_df(dates), _empty_ob(), fvg)

    bear_id = out['active_bear_ifvg_id']
    # inversão: bullish → BEAR; bull_ifvg permanece vazio
    assert out['active_bull_ifvg_id'].isna().all()
    # ativo só em [t_mit, t_inv) = candles 4,5,6
    active_idx = [i for i in range(10) if pd.notna(bear_id.iloc[i])]
    assert active_idx == [4, 5, 6]
    for i in active_idx:
        assert int(bear_id.iloc[i]) == 1
        assert out['active_bear_ifvg_top'].iloc[i] == 105.0
        assert out['active_bear_ifvg_bottom'].iloc[i] == 103.0
    # vazio antes da mitigação e a partir da invalidação
    assert bear_id.iloc[:4].isna().all()
    assert bear_id.iloc[7:].isna().all()


def test_bearish_fvg_mitigated_appears_in_bull_ifvg() -> None:
    """Simétrico: FVG **bearish** mitigado → zona BULL negociável (P3)."""
    dates = _dates(8)
    fvg = pd.DataFrame([{
        'fvg_id': 3, 'bias': BEARISH, 'top': 99.0, 'bottom': 97.0,
        'bar_time': dates[0], 't_creation': dates[1],
        't_mitigation': dates[3], 't_invalidation': pd.NaT,
        'state': 'mitigated', 'is_inverse': True, 'is_double': False,
    }], columns=_FVG_COLS)
    out = promote_active_zones(_df(dates, close=98.0), _empty_ob(), fvg)

    bull_id = out['active_bull_ifvg_id']
    assert out['active_bear_ifvg_id'].isna().all()
    # mitigado sem invalidação → ativo de t_mit (candle 3) até o fim
    active_idx = [i for i in range(8) if pd.notna(bull_id.iloc[i])]
    assert active_idx == [3, 4, 5, 6, 7]
    assert int(bull_id.iloc[3]) == 3
    assert out['active_bull_ifvg_top'].iloc[3] == 99.0


def test_active_fvg_not_an_ifvg() -> None:
    """FVG ativo (não mitigado, is_inverse False) não vira IFVG."""
    dates = _dates(5)
    fvg = pd.DataFrame([{
        'fvg_id': 1, 'bias': BULLISH, 'top': 105.0, 'bottom': 103.0,
        'bar_time': dates[0], 't_creation': dates[1],
        't_mitigation': pd.NaT, 't_invalidation': pd.NaT,
        'state': 'active', 'is_inverse': False, 'is_double': False,
    }], columns=_FVG_COLS)
    out = promote_active_zones(_df(dates), _empty_ob(), fvg)
    assert out['active_bull_ifvg_id'].isna().all()
    assert out['active_bear_ifvg_id'].isna().all()


def test_volume_pct_promoted_for_winning_ob() -> None:
    """A5/D5: `active_{dir}_swing_ob_volume_pct` = volume_pct do MESMO OB
    vencedor (mesmo `ob_id` de top/bottom/id), NaN sem OB ativo."""
    dates = _dates(6)
    ob = pd.DataFrame([{
        'ob_id': 7, 'scope': 'swing', 'bias': BULLISH,
        'bar_high': 102.0, 'bar_low': 100.0, 'bar_time': dates[0],
        't_creation': dates[1], 't_mitigation': dates[4],
        't_invalidation': pd.NaT, 'state': 'mitigated',
        'volume_bullish': 10.0, 'volume_bearish': 5.0, 'volume_total': 15.0,
        'volume_pct': 0.42, 'bb_volume': pd.NA,
    }], columns=_OB_COLS)
    empty_fvg = pd.DataFrame({c: pd.Series(dtype='object') for c in _FVG_COLS})
    out = promote_active_zones(_df(dates, close=101.0), ob, empty_fvg)

    vp = out['active_bull_swing_ob_volume_pct']
    oid = out['active_bull_swing_ob_id']
    # ativo em [t_creation=1, t_mitigation=4) = candles 1,2,3
    for i in range(6):
        if pd.notna(oid.iloc[i]):
            assert vp.iloc[i] == 0.42
        else:
            assert np.isnan(vp.iloc[i])
    assert [i for i in range(6) if pd.notna(oid.iloc[i])] == [1, 2, 3]
