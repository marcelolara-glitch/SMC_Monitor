"""
OBJETIVO
    Smoke test da Onda 4 — trailing extremes + premium/discount.

    Cobertura mínima:
      1. Trend-up monotônico sem swing reset → trailing_top rastreia
         high, trailing_bottom estagna no low inicial, pd_zone vai para
         'premium'.
      2. Trend-down monotônico sem swing reset → simétrico.
      3. Reset por swing pivot detectado pela Onda 3 → trailing_top
         no candle do reset é exatamente o nível do swing high.

FONTE DE DADOS
    Sintética: pequenos DataFrames construídos à mão, sem fixtures.

LIMITAÇÕES CONHECIDAS
    Não valida contra dataset real do Pine — equivalência golden vai
    para a Onda 5+ (briefing Onda 4 §2 ratifica que §7 do Mapa Camada 1
    fica fora deste PR).

NÃO FAZER
    Não importar de smc_freqtrade.smc_engine — o pacote raiz é
    `smc_engine` (ver tests/test_smoke_wave3.py).
    Não usar fixtures pytest aqui — cada teste é auto-contido.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from smc_engine import (
    compute_trailing_extremes,
    detect_pivots,
    COL_TRAILING_TOP,
    COL_TRAILING_BOTTOM,
    COL_PD_RATIO,
    COL_PD_ZONE,
    PD_ZONE_PREMIUM,
    PD_ZONE_DISCOUNT,
    COL_SWING_HIGH_LEVEL,
    COL_SWING_LOW_LEVEL,
)


def _make_df(highs, lows, closes):
    return pd.DataFrame({
        'high': highs,
        'low': lows,
        'close': closes,
    })


def test_trend_up_no_swing_reset() -> None:
    """Trend monotônico curto não dispara swing pivot (size=50 default).
    trailing_top deve ser cummax(high), trailing_bottom = low[0]."""
    n = 30
    highs = np.linspace(100, 130, n)
    lows = np.linspace(99, 129, n)
    closes = np.linspace(99.5, 129.5, n)
    df = _make_df(highs, lows, closes)

    df = detect_pivots(df)
    assert df[COL_SWING_HIGH_LEVEL].notna().sum() == 0
    assert df[COL_SWING_LOW_LEVEL].notna().sum() == 0

    out = compute_trailing_extremes(df)

    np.testing.assert_array_almost_equal(out[COL_TRAILING_TOP].values, highs)
    np.testing.assert_array_almost_equal(
        out[COL_TRAILING_BOTTOM].values, np.full(n, lows[0]),
    )

    # pd_ratio bem definido a partir do candle 1 (range > 0).
    assert out[COL_PD_RATIO].iloc[1:].notna().all()
    # Close > 50% do range em trend-up monotônico → premium predominante.
    assert (out[COL_PD_ZONE].iloc[1:] == PD_ZONE_PREMIUM).sum() > n // 2


def test_trend_down_no_swing_reset() -> None:
    """Simétrico do anterior."""
    n = 30
    highs = np.linspace(130, 100, n)
    lows = np.linspace(129, 99, n)
    closes = np.linspace(129.5, 99.5, n)
    df = _make_df(highs, lows, closes)

    df = detect_pivots(df)
    assert df[COL_SWING_HIGH_LEVEL].notna().sum() == 0

    out = compute_trailing_extremes(df)

    np.testing.assert_array_almost_equal(
        out[COL_TRAILING_TOP].values, np.full(n, highs[0]),
    )
    np.testing.assert_array_almost_equal(out[COL_TRAILING_BOTTOM].values, lows)

    assert (out[COL_PD_ZONE].iloc[1:] == PD_ZONE_DISCOUNT).sum() > n // 2


def test_swing_reset() -> None:
    """Cenário longo o bastante para a Onda 3 detectar swing pivots e
    a Onda 4 resetar trailing.

    Construção:
      - 60 candles subindo de 100 a 200 (cria swing high alto)
      - 60 candles descendo de 200 a 100
      - 60 candles subindo de 100 a 150

    Asserts:
      - existe pelo menos um swing_high_level não-NaN
      - trailing_top no candle do reset == swing_high_level naquele candle
    """
    n_seg = 60
    n = 3 * n_seg

    seg1_high = np.linspace(100, 200, n_seg)
    seg2_high = np.linspace(200, 100, n_seg)
    seg3_high = np.linspace(100, 150, n_seg)
    highs = np.concatenate([seg1_high, seg2_high, seg3_high])
    lows = highs - 1.0
    closes = highs - 0.5

    df = _make_df(highs, lows, closes)
    df = detect_pivots(df)

    assert df[COL_SWING_HIGH_LEVEL].notna().sum() >= 1, (
        'esperado pelo menos um swing high pivot detectado'
    )

    out = compute_trailing_extremes(df)

    pivot_candles = df[df[COL_SWING_HIGH_LEVEL].notna()].index
    first_pivot = pivot_candles[0]
    np.testing.assert_almost_equal(
        out.loc[first_pivot, COL_TRAILING_TOP],
        df.loc[first_pivot, COL_SWING_HIGH_LEVEL],
    )


if __name__ == '__main__':
    test_trend_up_no_swing_reset()
    test_trend_down_no_swing_reset()
    test_swing_reset()
    print('Onda 4 smoke OK.')
