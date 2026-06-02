"""Projetor de zona breaker (Wave 9.5c §3.1/§5.1, D-C9).

OBJETIVO
    Cobrir o critério verificável §5.1: o projetor de zona breaker inverte
    a direção corretamente (a armadilha de rótulo D-C4) e a zona é ativa
    **só** em `[t_mitigation, t_invalidation)` — vazia antes da mitigação e
    a partir da invalidação:
    - OB **BULLISH** mitigado → `active_bear_breaker_*` (resistência/short).
    - OB **BEARISH** mitigado → `active_bull_breaker_*` (suporte/long).

    Filtro de origem por `t_mitigation.notna()` (NÃO `state`), restrito por
    `breaker_scope` (default 'swing'). Expectativas anotadas à mão sobre
    ledgers construídos diretamente (sem rodar `analyze()`) — sem
    circularidade.

NÃO FAZER
    Não gerar a fixture esperada a partir do próprio projetor.
"""
from __future__ import annotations

import pandas as pd

from smc_engine import promote_active_zones
from smc_engine.types import BEARISH, BULLISH

_OB_COLS = [
    'ob_id', 'scope', 'bias', 'bar_high', 'bar_low', 'bar_time',
    't_creation', 't_mitigation', 't_invalidation', 'state',
    'volume_bullish', 'volume_bearish', 'volume_total', 'volume_pct',
    'bb_volume',
]
_FVG_COLS = [
    'fvg_id', 'bias', 'top', 'bottom', 'bar_time', 't_creation',
    't_mitigation', 't_invalidation', 'state', 'is_inverse', 'is_double',
]


def _dates(n: int) -> pd.DatetimeIndex:
    return pd.date_range('2026-03-01', periods=n, freq='15min', tz='UTC')


def _empty_fvg() -> pd.DataFrame:
    return pd.DataFrame({c: pd.Series(dtype='object') for c in _FVG_COLS})


def _df(dates, close: float = 101.0) -> pd.DataFrame:
    return pd.DataFrame({'date': dates, 'close': [close] * len(dates)})


def _ob_row(**kw) -> dict:
    base = {
        'ob_id': 0, 'scope': 'swing', 'bias': BULLISH,
        'bar_high': 102.0, 'bar_low': 100.0, 'bar_time': None,
        't_creation': None, 't_mitigation': pd.NaT, 't_invalidation': pd.NaT,
        'state': 'active', 'volume_bullish': pd.NA, 'volume_bearish': pd.NA,
        'volume_total': pd.NA, 'volume_pct': pd.NA, 'bb_volume': pd.NA,
    }
    base.update(kw)
    return base


def _ob(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=_OB_COLS)


def test_bullish_ob_mitigated_appears_in_bear_breaker() -> None:
    """Armadilha de rótulo (D-C4): OB **BULLISH** mitigado → zona BEAR
    breaker (resistência/short), ativa só em [t_mit, t_inv)."""
    dates = _dates(10)
    ob = _ob([_ob_row(
        ob_id=2, bias=BULLISH, bar_high=102.0, bar_low=100.0,
        bar_time=dates[0], t_creation=dates[1],
        t_mitigation=dates[4], t_invalidation=dates[7],
        state='breaker_broken',
    )])
    out = promote_active_zones(_df(dates), ob, _empty_fvg())

    bear_id = out['active_bear_breaker_id']
    # inversão: bullish → BEAR; bull_breaker permanece vazio
    assert out['active_bull_breaker_id'].isna().all()
    # ativo só em [t_mit, t_inv) = candles 4,5,6
    active_idx = [i for i in range(10) if pd.notna(bear_id.iloc[i])]
    assert active_idx == [4, 5, 6]
    for i in active_idx:
        assert int(bear_id.iloc[i]) == 2
        assert out['active_bear_breaker_top'].iloc[i] == 102.0
        assert out['active_bear_breaker_bottom'].iloc[i] == 100.0
    # vazio antes da mitigação e a partir da invalidação
    assert bear_id.iloc[:4].isna().all()
    assert bear_id.iloc[7:].isna().all()


def test_bearish_ob_mitigated_appears_in_bull_breaker() -> None:
    """Simétrico: OB **BEARISH** mitigado → zona BULL breaker (suporte/long).

    Sem invalidação (`t_invalidation` NaT) → ativo de t_mit até o fim."""
    dates = _dates(8)
    ob = _ob([_ob_row(
        ob_id=5, bias=BEARISH, bar_high=99.0, bar_low=97.0,
        bar_time=dates[0], t_creation=dates[1],
        t_mitigation=dates[3], t_invalidation=pd.NaT, state='mitigated',
    )])
    out = promote_active_zones(_df(dates, close=98.0), ob, _empty_fvg())

    bull_id = out['active_bull_breaker_id']
    assert out['active_bear_breaker_id'].isna().all()
    active_idx = [i for i in range(8) if pd.notna(bull_id.iloc[i])]
    assert active_idx == [3, 4, 5, 6, 7]
    assert int(bull_id.iloc[3]) == 5
    assert out['active_bull_breaker_top'].iloc[3] == 99.0
    assert out['active_bull_breaker_bottom'].iloc[3] == 97.0


def test_unmitigated_ob_is_not_a_breaker() -> None:
    """OB ativo (sem mitigação, `t_mitigation` NaT) não vira breaker."""
    dates = _dates(5)
    ob = _ob([_ob_row(
        ob_id=1, bias=BULLISH, bar_time=dates[0], t_creation=dates[1],
        t_mitigation=pd.NaT, t_invalidation=pd.NaT, state='active',
    )])
    out = promote_active_zones(_df(dates), ob, _empty_fvg())
    assert out['active_bull_breaker_id'].isna().all()
    assert out['active_bear_breaker_id'].isna().all()


def test_breaker_scope_filters_origin() -> None:
    """`breaker_scope` filtra o OB de origem por `scope` (HOOKS §12.1: o
    filtro é por `t_mitigation.notna()`, nunca por `state`)."""
    dates = _dates(6)
    ob = _ob([_ob_row(
        ob_id=3, scope='internal', bias=BEARISH,
        bar_high=99.0, bar_low=97.0, bar_time=dates[0],
        t_creation=dates[1], t_mitigation=dates[2], t_invalidation=pd.NaT,
        state='mitigated',
    )])
    # default 'swing' → ignora o OB internal
    out_swing = promote_active_zones(_df(dates, close=98.0), ob, _empty_fvg())
    assert out_swing['active_bull_breaker_id'].isna().all()
    # 'internal' → projeta o breaker
    out_int = promote_active_zones(
        _df(dates, close=98.0), ob, _empty_fvg(), breaker_scope='internal',
    )
    active = [i for i in range(6) if pd.notna(out_int['active_bull_breaker_id'].iloc[i])]
    assert active == [2, 3, 4, 5]
    # 'both' → também projeta
    out_both = promote_active_zones(
        _df(dates, close=98.0), ob, _empty_fvg(), breaker_scope='both',
    )
    assert not out_both['active_bull_breaker_id'].isna().all()


def test_invalid_breaker_scope_rejected() -> None:
    import pytest
    dates = _dates(3)
    with pytest.raises(ValueError, match='breaker_scope'):
        promote_active_zones(
            _df(dates), _ob([]), _empty_fvg(), breaker_scope='nope',
        )
