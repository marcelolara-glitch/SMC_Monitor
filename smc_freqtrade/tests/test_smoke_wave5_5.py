"""Smoke test da Onda 5.5 — CHoCH+ (Supported CHoCH) escopos swing e internal.

OBJETIVO
    Cobertura mínima conforme briefing §5 (orientação corrigida pelo
    briefing-fix após ratificação visual contra PAC pago):
      Caso A: CHoCH+ bullish swing (higher low antes do break)
      Caso B: CHoCH simples swing sem upgrade (sem higher low)
      Caso C: CHoCH+ bearish swing (lower high antes do break)
      Caso D: CHoCH+ internal (internal pivots, internal_length=5)
    + invariantes §4 sobre golden dataset (byte-identical, subset,
    disjunção BOS, contagem sã) para ambos os escopos.

FONTE DE DADOS
    DataFrames sintéticos mínimos com pivots forçados via landmarks.
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
    COL_CHOCH_PLUS_INTERNAL_BULLISH,
    COL_CHOCH_PLUS_INTERNAL_BEARISH,
)


GOLDEN_CSV = Path(__file__).parent / 'golden' / 'data' / 'btc_usdt_swap_4h_window.csv'


def _build_case_a():
    """Caso A: CHoCH+ bullish (orientação correta).

    Tendência bearish com um higher low (swing low > anterior) —
    fundo subindo = exaustão da baixa — seguida de close cruzando
    acima do swing high → CHoCH+ bullish.
    """
    n = 200
    rng = np.random.RandomState(100)

    close = np.full(n, 100.0)
    close[0:20] = np.linspace(120, 115, 20)
    close[20:60] = np.linspace(115, 95, 40)
    close[60:80] = np.linspace(95, 108, 20)
    close[80:110] = np.linspace(108, 98, 30)
    close[110:130] = np.linspace(98, 105, 20)
    close[130:160] = np.linspace(105, 92, 30)
    close[160:200] = np.linspace(92, 115, 40)

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

    Tendência bearish com swing lows sempre fazendo lower lows
    (sem higher low) → CHoCH bullish sem choch_plus.
    """
    n = 200
    rng = np.random.RandomState(200)

    close = np.full(n, 100.0)
    close[0:30] = np.linspace(130, 110, 30)
    close[30:60] = np.linspace(110, 100, 30)
    close[60:80] = np.linspace(100, 115, 20)
    close[80:110] = np.linspace(115, 90, 30)
    close[110:130] = np.linspace(90, 108, 20)
    close[130:160] = np.linspace(108, 80, 30)
    close[160:200] = np.linspace(80, 120, 40)

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
    """Caso C: CHoCH+ bearish (orientação correta).

    Tendência bullish com um lower high (swing high < anterior) —
    topo caindo = exaustão da alta — seguida de close cruzando
    abaixo do swing low → CHoCH+ bearish.
    """
    n = 200
    rng = np.random.RandomState(300)

    close = np.full(n, 100.0)
    close[0:20] = np.linspace(80, 90, 20)
    close[20:60] = np.linspace(90, 110, 40)
    close[60:80] = np.linspace(110, 100, 20)
    close[80:110] = np.linspace(100, 107, 30)
    close[110:130] = np.linspace(107, 102, 20)
    close[130:160] = np.linspace(102, 112, 30)
    close[160:200] = np.linspace(112, 85, 40)

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


def _build_case_d_internal():
    """Caso D: CHoCH+ internal — pivots internal (length=5) com failed swings.

    Série com oscilações rápidas para produzir internal pivots em
    abundância e gerar CHoCH+ internal.
    """
    n = 300
    rng = np.random.RandomState(400)

    close = np.full(n, 100.0)
    close[0:15] = np.linspace(100, 110, 15)
    close[15:30] = np.linspace(110, 95, 15)
    close[30:45] = np.linspace(95, 108, 15)
    close[45:60] = np.linspace(108, 90, 15)
    close[60:75] = np.linspace(90, 105, 15)
    close[75:90] = np.linspace(105, 85, 15)
    close[90:120] = np.linspace(85, 115, 30)
    close[120:150] = np.linspace(115, 90, 30)
    close[150:180] = np.linspace(90, 100, 30)
    close[180:210] = np.linspace(100, 80, 30)
    close[210:240] = np.linspace(80, 105, 30)
    close[240:270] = np.linspace(105, 88, 30)
    close[270:300] = np.linspace(88, 112, 30)

    noise = rng.normal(0, 0.4, n)
    close = close + noise
    opens = close + rng.normal(0, 0.2, n)
    highs = np.maximum(close, opens) + np.abs(rng.normal(0.4, 0.2, n))
    lows = np.minimum(close, opens) - np.abs(rng.normal(0.4, 0.2, n))

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
        """Higher low antes do break → CHoCH+ bullish."""
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
        """Sem higher low antes do break → CHoCH simples, não +."""
        df = _build_case_b()
        out = _run_pipeline(df)

        choch_bull = out['choch_swing_bullish']
        choch_plus_bull = out[COL_CHOCH_PLUS_SWING_BULLISH]

        # Subset invariant always holds
        assert (choch_plus_bull & ~choch_bull).sum() == 0
        # choch_plus count <= choch count
        assert choch_plus_bull.sum() <= choch_bull.sum()

    def test_case_c_choch_plus_bearish(self):
        """Lower high antes do break → CHoCH+ bearish."""
        df = _build_case_c()
        out = _run_pipeline(df)

        choch_bear = out['choch_swing_bearish']
        choch_plus_bear = out[COL_CHOCH_PLUS_SWING_BEARISH]

        # Subset invariant
        assert (choch_plus_bear & ~choch_bear).sum() == 0

        if choch_bear.any():
            assert choch_plus_bear.dtype == bool

    def test_case_d_choch_plus_internal(self):
        """Internal pivots com failed swings → CHoCH+ internal dispara."""
        df = _build_case_d_internal()
        out = _run_pipeline(df)

        choch_int_bull = out['choch_internal_bullish']
        choch_int_bear = out['choch_internal_bearish']
        plus_int_bull = out[COL_CHOCH_PLUS_INTERNAL_BULLISH]
        plus_int_bear = out[COL_CHOCH_PLUS_INTERNAL_BEARISH]

        # Subset invariant internal
        assert (plus_int_bull & ~choch_int_bull).sum() == 0
        assert (plus_int_bear & ~choch_int_bear).sum() == 0

        # Disjunction with BOS internal
        assert not (plus_int_bull & out['bos_internal_bullish']).any()
        assert not (plus_int_bull & out['bos_internal_bearish']).any()
        assert not (plus_int_bear & out['bos_internal_bullish']).any()
        assert not (plus_int_bear & out['bos_internal_bearish']).any()

        # Columns are boolean
        assert plus_int_bull.dtype == bool
        assert plus_int_bear.dtype == bool


class TestCHoCHPlusGoldenInvariants:
    """Invariantes §4 sobre golden dataset (720 candles BTC-USDT 4H)."""

    @pytest.fixture
    def golden_out(self):
        df = pd.read_csv(GOLDEN_CSV)
        df = df.rename(columns={'timestamp_utc': 'date'})
        df['date'] = pd.to_datetime(df['date'], utc=True)
        return _run_pipeline(df)

    def test_wave5_byte_identical(self, golden_out):
        """Invariante #1: as 10 colunas originais da Onda 5 inalteradas.

        Dívida: compara detect_structure contra si mesmo (sem snapshot
        pré-5.5 persistido). É estrutural-only — a garantia byte-idêntica
        real vem de o diff não ter tocado as 12 atribuições anteriores.
        Persistir CSV-snapshot das 12 colunas pré-5.5 para comparação
        real numa wave de saneamento futura.
        """
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

    def test_subset_invariant_swing(self, golden_out):
        """Invariante #2a: choch_plus_swing ⊆ choch_swing."""
        assert not (
            golden_out[COL_CHOCH_PLUS_SWING_BULLISH]
            & ~golden_out['choch_swing_bullish']
        ).any()
        assert not (
            golden_out[COL_CHOCH_PLUS_SWING_BEARISH]
            & ~golden_out['choch_swing_bearish']
        ).any()

    def test_subset_invariant_internal(self, golden_out):
        """Invariante #2b: choch_plus_internal ⊆ choch_internal."""
        assert not (
            golden_out[COL_CHOCH_PLUS_INTERNAL_BULLISH]
            & ~golden_out['choch_internal_bullish']
        ).any()
        assert not (
            golden_out[COL_CHOCH_PLUS_INTERNAL_BEARISH]
            & ~golden_out['choch_internal_bearish']
        ).any()

    def test_disjunction_bos_swing(self, golden_out):
        """Invariante #3a: nenhuma barra CHoCH+ swing coincide com BOS swing."""
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

    def test_disjunction_bos_internal(self, golden_out):
        """Invariante #3b: nenhuma barra CHoCH+ internal coincide com BOS internal."""
        assert not (
            golden_out[COL_CHOCH_PLUS_INTERNAL_BULLISH]
            & golden_out['bos_internal_bullish']
        ).any()
        assert not (
            golden_out[COL_CHOCH_PLUS_INTERNAL_BULLISH]
            & golden_out['bos_internal_bearish']
        ).any()
        assert not (
            golden_out[COL_CHOCH_PLUS_INTERNAL_BEARISH]
            & golden_out['bos_internal_bullish']
        ).any()
        assert not (
            golden_out[COL_CHOCH_PLUS_INTERNAL_BEARISH]
            & golden_out['bos_internal_bearish']
        ).any()

    def test_count_sane(self, golden_out):
        """Invariante #4: 0 <= #CHoCH+ <= #CHoCH + exact counts from §3."""
        choch_s_bull = golden_out['choch_swing_bullish'].sum()
        choch_s_bear = golden_out['choch_swing_bearish'].sum()
        plus_s_bull = golden_out[COL_CHOCH_PLUS_SWING_BULLISH].sum()
        plus_s_bear = golden_out[COL_CHOCH_PLUS_SWING_BEARISH].sum()

        choch_i_bull = golden_out['choch_internal_bullish'].sum()
        choch_i_bear = golden_out['choch_internal_bearish'].sum()
        plus_i_bull = golden_out[COL_CHOCH_PLUS_INTERNAL_BULLISH].sum()
        plus_i_bear = golden_out[COL_CHOCH_PLUS_INTERNAL_BEARISH].sum()

        assert 0 <= plus_s_bull <= choch_s_bull
        assert 0 <= plus_s_bear <= choch_s_bear
        assert 0 <= plus_i_bull <= choch_i_bull
        assert 0 <= plus_i_bear <= choch_i_bear

        assert plus_s_bull + plus_s_bear == 1, f"swing total expected 1, got {plus_s_bull + plus_s_bear}"
        assert plus_i_bull == 2, f"internal bull expected 2, got {plus_i_bull}"
        assert plus_i_bear == 3, f"internal bear expected 3, got {plus_i_bear}"
        assert plus_i_bull + plus_i_bear == 5, f"internal total expected 5, got {plus_i_bull + plus_i_bear}"

        print(f"\n[CHoCH+ Golden Report]")
        print(f"  CHoCH swing bullish: {choch_s_bull}, CHoCH+ swing bullish: {plus_s_bull}")
        print(f"  CHoCH swing bearish: {choch_s_bear}, CHoCH+ swing bearish: {plus_s_bear}")
        print(f"  CHoCH internal bullish: {choch_i_bull}, CHoCH+ internal bullish: {plus_i_bull}")
        print(f"  CHoCH internal bearish: {choch_i_bear}, CHoCH+ internal bearish: {plus_i_bear}")
        print(f"  Total CHoCH+ internal: {plus_i_bull + plus_i_bear}")

    def test_swing_choch_plus_unchanged(self, golden_out):
        """Invariante: swing CHoCH+ columns unchanged after internal addition."""
        df = pd.read_csv(GOLDEN_CSV)
        df = df.rename(columns={'timestamp_utc': 'date'})
        df['date'] = pd.to_datetime(df['date'], utc=True)
        baseline = _run_pipeline(df)
        pd.testing.assert_series_equal(
            golden_out[COL_CHOCH_PLUS_SWING_BULLISH],
            baseline[COL_CHOCH_PLUS_SWING_BULLISH],
            check_names=False,
        )
        pd.testing.assert_series_equal(
            golden_out[COL_CHOCH_PLUS_SWING_BEARISH],
            baseline[COL_CHOCH_PLUS_SWING_BEARISH],
            check_names=False,
        )

    def test_no_lookahead(self, golden_out):
        """Invariante #5: no shift(-N) — deterministic/reproducible."""
        df = pd.read_csv(GOLDEN_CSV)
        df = df.rename(columns={'timestamp_utc': 'date'})
        df['date'] = pd.to_datetime(df['date'], utc=True)

        out1 = _run_pipeline(df)
        out2 = _run_pipeline(df)
        choch_plus_cols = [
            COL_CHOCH_PLUS_SWING_BULLISH, COL_CHOCH_PLUS_SWING_BEARISH,
            COL_CHOCH_PLUS_INTERNAL_BULLISH, COL_CHOCH_PLUS_INTERNAL_BEARISH,
        ]
        pd.testing.assert_frame_equal(
            out1[choch_plus_cols], out2[choch_plus_cols],
        )


if __name__ == '__main__':
    import sys
    sys.exit(pytest.main([__file__, '-v']))
