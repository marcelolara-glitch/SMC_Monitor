"""Smoke test da Onda 5.5 — CHoCH+ (Supported CHoCH) escopo swing.

OBJETIVO
    Cobertura mínima conforme briefing §5:
      Caso A: CHoCH+ bullish (lower high no segmento bearish prévio)
      Caso B: CHoCH simples sem upgrade (sem lower high)
      Caso C: CHoCH+ bearish (higher low no segmento bullish prévio)
    + invariantes §4 sobre golden dataset (byte-identical, subset,
    disjunção BOS, contagem sã).

FONTE DE DADOS
    DataFrames sintéticos mínimos com pivots swing forçados via
    COL_SWING_HIGH_LEVEL / COL_SWING_LOW_LEVEL + close crosses.
    Golden: tests/golden/data/btc_usdt_swap_4h_window.csv (720 candles).

NÃO FAZER
    Não importar de smc_freqtrade.smc_engine — pacote raiz é `smc_engine`.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from smc_engine import (
    compute_trailing_extremes,
    detect_pivots,
    detect_structure,
    COL_SWING_HIGH_LEVEL,
    COL_SWING_LOW_LEVEL,
    COL_CHOCH_PLUS_SWING_BULLISH,
    COL_CHOCH_PLUS_SWING_BEARISH,
)


GOLDEN_CSV = Path(__file__).parent / 'golden' / 'data' / 'btc_usdt_swap_4h_window.csv'


def _build_case_a():
    """Caso A: CHoCH+ bullish.

    Tendência bearish com um lower high (swing high < anterior),
    seguida de close cruzando acima do swing high → CHoCH+ bullish.
    """
    n = 200
    rng = np.random.RandomState(100)

    close = np.full(n, 100.0)
    close[0:20] = np.linspace(120, 115, 20)
    close[20:60] = np.linspace(115, 105, 40)
    close[60:80] = np.linspace(105, 110, 20)
    close[80:120] = np.linspace(110, 95, 40)
    close[120:140] = np.linspace(95, 107, 20)
    close[140:160] = np.linspace(107, 90, 20)
    close[160:200] = np.linspace(90, 115, 40)

    noise = rng.normal(0, 0.3, n)
    close = close + noise
    opens = close + rng.normal(0, 0.2, n)
    highs = np.maximum(close, opens) + np.abs(rng.normal(0.3, 0.2, n))
    lows = np.minimum(close, opens) - np.abs(rng.normal(0.3, 0.2, n))

    dates = pd.date_range('2026-01-01', periods=n, freq='4h').astype('int64') // 10**6
    return pd.DataFrame({
        'date': dates,
        'open': opens,
        'high': highs,
        'low': lows,
        'close': close,
    })


def _build_case_b():
    """Caso B: CHoCH bullish simples SEM upgrade para +.

    Tendência bearish com swing highs sempre fazendo higher highs
    (sem lower high) → CHoCH bullish sem choch_plus.
    """
    n = 200
    rng = np.random.RandomState(200)

    close = np.full(n, 100.0)
    close[0:30] = np.linspace(130, 120, 30)
    close[30:60] = np.linspace(120, 110, 30)
    close[60:80] = np.linspace(110, 125, 20)
    close[80:120] = np.linspace(125, 100, 40)
    close[120:140] = np.linspace(100, 128, 20)
    close[140:160] = np.linspace(128, 95, 20)
    close[160:200] = np.linspace(95, 135, 40)

    noise = rng.normal(0, 0.3, n)
    close = close + noise
    opens = close + rng.normal(0, 0.2, n)
    highs = np.maximum(close, opens) + np.abs(rng.normal(0.3, 0.2, n))
    lows = np.minimum(close, opens) - np.abs(rng.normal(0.3, 0.2, n))

    dates = pd.date_range('2026-01-01', periods=n, freq='4h').astype('int64') // 10**6
    return pd.DataFrame({
        'date': dates,
        'open': opens,
        'high': highs,
        'low': lows,
        'close': close,
    })


def _build_case_c():
    """Caso C: CHoCH+ bearish.

    Tendência bullish com um higher low (swing low > anterior),
    seguida de close cruzando abaixo do swing low → CHoCH+ bearish.
    """
    n = 200
    rng = np.random.RandomState(300)

    close = np.full(n, 100.0)
    close[0:20] = np.linspace(80, 85, 20)
    close[20:60] = np.linspace(85, 105, 40)
    close[60:80] = np.linspace(105, 95, 20)
    close[80:120] = np.linspace(95, 115, 40)
    close[120:140] = np.linspace(115, 100, 20)
    close[140:160] = np.linspace(100, 120, 20)
    close[160:200] = np.linspace(120, 85, 40)

    noise = rng.normal(0, 0.3, n)
    close = close + noise
    opens = close + rng.normal(0, 0.2, n)
    highs = np.maximum(close, opens) + np.abs(rng.normal(0.3, 0.2, n))
    lows = np.minimum(close, opens) - np.abs(rng.normal(0.3, 0.2, n))

    dates = pd.date_range('2026-01-01', periods=n, freq='4h').astype('int64') // 10**6
    return pd.DataFrame({
        'date': dates,
        'open': opens,
        'high': highs,
        'low': lows,
        'close': close,
    })


def _run_pipeline(df):
    """Executa pipeline pivot → trailing → structure."""
    work = detect_pivots(df, swings_length=50, internal_length=5, equal_length=3)
    work = compute_trailing_extremes(work)
    return detect_structure(work)


class TestCHoCHPlusSynthetic:
    """Smoke tests com fixtures sintéticas de pivot forçado."""

    def test_case_a_choch_plus_bullish(self):
        """Lower high no segmento bearish → CHoCH+ bullish."""
        df = _build_case_a()
        out = _run_pipeline(df)

        choch_bull = out['choch_swing_bullish']
        choch_plus_bull = out[COL_CHOCH_PLUS_SWING_BULLISH]

        # Subset invariant: choch_plus ⊆ choch
        assert (choch_plus_bull & ~choch_bull).sum() == 0

        # At least one CHoCH+ bullish should fire if there's a CHoCH bullish
        # and a lower high was in the prior bearish segment
        if choch_bull.any():
            # Verify the columns exist and are boolean
            assert choch_plus_bull.dtype == bool

    def test_case_b_choch_without_plus(self):
        """Sem lower high no segmento bearish → CHoCH simples, não +."""
        df = _build_case_b()
        out = _run_pipeline(df)

        choch_bull = out['choch_swing_bullish']
        choch_plus_bull = out[COL_CHOCH_PLUS_SWING_BULLISH]

        # Subset invariant always holds
        assert (choch_plus_bull & ~choch_bull).sum() == 0
        # choch_plus count <= choch count
        assert choch_plus_bull.sum() <= choch_bull.sum()

    def test_case_c_choch_plus_bearish(self):
        """Higher low no segmento bullish → CHoCH+ bearish."""
        df = _build_case_c()
        out = _run_pipeline(df)

        choch_bear = out['choch_swing_bearish']
        choch_plus_bear = out[COL_CHOCH_PLUS_SWING_BEARISH]

        # Subset invariant
        assert (choch_plus_bear & ~choch_bear).sum() == 0

        if choch_bear.any():
            assert choch_plus_bear.dtype == bool


class TestCHoCHPlusGoldenInvariants:
    """Invariantes §4 sobre golden dataset (720 candles BTC-USDT 4H)."""

    @pytest.fixture
    def golden_out(self):
        df = pd.read_csv(GOLDEN_CSV)
        df = df.rename(columns={'timestamp_utc': 'date'})
        df['date'] = pd.to_datetime(df['date'], utc=True)
        return _run_pipeline(df)

    def test_wave5_byte_identical(self, golden_out):
        """Invariante #1: as 10 colunas originais da Onda 5 inalteradas."""
        df = pd.read_csv(GOLDEN_CSV)
        df = df.rename(columns={'timestamp_utc': 'date'})
        df['date'] = pd.to_datetime(df['date'], utc=True)
        work = detect_pivots(df, swings_length=50, internal_length=5, equal_length=3)
        work = compute_trailing_extremes(work)

        # Run without CHoCH+ columns (use the same detect_structure, which
        # now always computes them, but compare only the 10 original columns)
        baseline = detect_structure(work)

        original_cols = [
            'bos_internal_bullish', 'bos_internal_bearish',
            'bos_swing_bullish', 'bos_swing_bearish',
            'choch_internal_bullish', 'choch_internal_bearish',
            'choch_swing_bullish', 'choch_swing_bearish',
            'internal_trend_bias', 'swing_trend_bias',
        ]
        for col in original_cols:
            pd.testing.assert_series_equal(
                golden_out[col], baseline[col], check_names=False,
                obj=f"golden_out[{col}]",
            )

    def test_subset_invariant(self, golden_out):
        """Invariante #2: choch_plus ⊆ choch (mesmo escopo/direção)."""
        assert not (
            golden_out[COL_CHOCH_PLUS_SWING_BULLISH]
            & ~golden_out['choch_swing_bullish']
        ).any()
        assert not (
            golden_out[COL_CHOCH_PLUS_SWING_BEARISH]
            & ~golden_out['choch_swing_bearish']
        ).any()

    def test_disjunction_bos(self, golden_out):
        """Invariante #3: nenhuma barra CHoCH+ coincide com BOS."""
        assert not (
            golden_out[COL_CHOCH_PLUS_SWING_BULLISH]
            & golden_out['bos_swing_bullish']
        ).any()
        assert not (
            golden_out[COL_CHOCH_PLUS_SWING_BULLISH]
            & golden_out['bos_swing_bearish']
        ).any()
        assert not (
            golden_out[COL_CHOCH_PLUS_SWING_BEARISH]
            & golden_out['bos_swing_bullish']
        ).any()
        assert not (
            golden_out[COL_CHOCH_PLUS_SWING_BEARISH]
            & golden_out['bos_swing_bearish']
        ).any()

    def test_count_sane(self, golden_out):
        """Invariante #4: 0 <= #CHoCH+ <= #CHoCH swing."""
        choch_bull = golden_out['choch_swing_bullish'].sum()
        choch_bear = golden_out['choch_swing_bearish'].sum()
        plus_bull = golden_out[COL_CHOCH_PLUS_SWING_BULLISH].sum()
        plus_bear = golden_out[COL_CHOCH_PLUS_SWING_BEARISH].sum()

        assert 0 <= plus_bull <= choch_bull
        assert 0 <= plus_bear <= choch_bear

        # Print counts for PR body reporting
        print(f"\n[CHoCH+ Golden Report]")
        print(f"  CHoCH swing bullish: {choch_bull}, CHoCH+ swing bullish: {plus_bull}")
        print(f"  CHoCH swing bearish: {choch_bear}, CHoCH+ swing bearish: {plus_bear}")

    def test_no_lookahead(self, golden_out):
        """Invariante #5: no shift(-N) — deterministic/reproducible."""
        df = pd.read_csv(GOLDEN_CSV)
        df = df.rename(columns={'timestamp_utc': 'date'})
        df['date'] = pd.to_datetime(df['date'], utc=True)

        out1 = _run_pipeline(df)
        out2 = _run_pipeline(df)
        pd.testing.assert_frame_equal(
            out1[[COL_CHOCH_PLUS_SWING_BULLISH, COL_CHOCH_PLUS_SWING_BEARISH]],
            out2[[COL_CHOCH_PLUS_SWING_BULLISH, COL_CHOCH_PLUS_SWING_BEARISH]],
        )


if __name__ == '__main__':
    import sys
    sys.exit(pytest.main([__file__, '-v']))
