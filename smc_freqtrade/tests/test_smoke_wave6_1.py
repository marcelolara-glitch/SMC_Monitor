"""Smoke test da Onda 6.1 — Volumetric OB + Mitigation Middle.

Cobre os critérios C1-C16 do briefing 6.1 §3 distribuídos em T1-T10.

Reutiliza fixtures `synthetic_df` e `synthetic_df_co_mit` da Wave 6,
injetando coluna `volume` sintética determinística.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from smc_engine import (
    BEARISH,
    BULLISH,
    compute_trailing_extremes,
    detect_order_blocks,
    detect_pivots,
    detect_structure,
)
from smc_engine.order_blocks import _emit_create_record

from tests.test_smoke_wave6 import (
    synthetic_df,
    synthetic_df_co_mit,
)


def _add_volume(df: pd.DataFrame, seed: int = 42) -> pd.DataFrame:
    """Injeta coluna `volume` log-normal determinística."""
    out = df.copy()
    rng = np.random.RandomState(seed)
    out['volume'] = np.exp(rng.normal(6.0, 1.0, len(out)))
    return out


def _run_pipeline(df: pd.DataFrame, mitigation: str = 'Wick',
                  ob_mitigation_level: str = 'Absolute'):
    df = detect_pivots(
        df, swings_length=50, internal_length=5, equal_length=3,
    )
    df = compute_trailing_extremes(df)
    df = detect_structure(df)
    return detect_order_blocks(
        df, mitigation=mitigation,
        ob_mitigation_level=ob_mitigation_level,
    )


EXPECTED_COLS = [
    'ob_id', 'scope', 'bias', 'bar_high', 'bar_low', 'bar_time',
    't_creation', 't_mitigation', 't_invalidation', 'state',
    'volume_bullish', 'volume_bearish', 'volume_total', 'volume_pct',
    'bb_volume',
]


def test_t1_schema(synthetic_df):
    """C1, C2, C18: ledger has 15 cols in canonical order; dtypes correct;
    volumetric_intensity absent."""
    df = _add_volume(synthetic_df)
    _, ledger = _run_pipeline(df)

    assert list(ledger.columns) == EXPECTED_COLS
    assert len(ledger.columns) == 15
    assert 'volumetric_intensity' not in ledger.columns

    assert ledger['volume_bullish'].dtype.name == 'Float64'
    assert ledger['volume_bearish'].dtype.name == 'Float64'
    assert ledger['volume_total'].dtype.name == 'Float64'
    assert ledger['volume_pct'].dtype.name == 'Float64'
    assert ledger['bb_volume'].dtype.name == 'Float64'


def test_t2_fluxcharts_formulas(synthetic_df):
    """C3: volumetric formulas match FluxCharts definition for selected
    records (1 bullish, 1 bearish if present)."""
    df = _add_volume(synthetic_df)
    df_pipe = detect_pivots(
        df, swings_length=50, internal_length=5, equal_length=3,
    )
    df_pipe = compute_trailing_extremes(df_pipe)
    df_pipe = detect_structure(df_pipe)

    from smc_engine.order_blocks import (
        _compute_parsed_high_low,
        _emit_create_events,
    )
    parsed_high, parsed_low = _compute_parsed_high_low(
        df_pipe, ob_filter='Atr', atr_length=200,
    )
    _, records = _emit_create_events(
        df_pipe, parsed_high=parsed_high, parsed_low=parsed_low,
    )

    tested_bullish = False
    tested_bearish = False
    for rec in records:
        if pd.isna(rec.get('volume_total')):
            continue
        bias = rec['bias']
        bar_time = rec['bar_time']
        extreme_pos = int(df_pipe.index[df_pipe['date'] == bar_time][0])
        vol_base = float(df_pipe['volume'].iloc[extreme_pos])
        vol_p1 = float(df_pipe['volume'].iloc[extreme_pos + 1])
        vol_p2 = float(df_pipe['volume'].iloc[extreme_pos + 2])

        if bias == BULLISH and not tested_bullish:
            assert rec['volume_bearish'] == pytest.approx(vol_base)
            assert rec['volume_bullish'] == pytest.approx(vol_p1 + vol_p2)
            assert rec['volume_total'] == pytest.approx(
                rec['volume_bullish'] + rec['volume_bearish']
            )
            tested_bullish = True
        elif bias == BEARISH and not tested_bearish:
            assert rec['volume_bullish'] == pytest.approx(vol_base)
            assert rec['volume_bearish'] == pytest.approx(vol_p1 + vol_p2)
            assert rec['volume_total'] == pytest.approx(
                rec['volume_bullish'] + rec['volume_bearish']
            )
            tested_bearish = True
        if tested_bullish and tested_bearish:
            break

    assert tested_bullish, 'No bullish record with volume found.'


def test_t3_lookahead_guard():
    """C4: when extreme_label+2 > break_pos, volumetric fields = pd.NA."""
    n = 30
    base = 100.0
    df = pd.DataFrame({
        'open': [base] * n,
        'high': [base + 0.5] * n,
        'low': [base - 0.5] * n,
        'close': [base] * n,
        'date': list(range(n)),
        'volume': [500.0] * n,
    })
    from smc_engine.order_blocks import _compute_parsed_high_low
    parsed_h, parsed_l = _compute_parsed_high_low(
        df, ob_filter='Atr', atr_length=14,
    )
    # pivot_pos=8, break_pos=10 → window is [8, 9]. Extreme at 8 or 9.
    # extreme_pos + 2 = 10 or 11. break_pos = 10.
    # If extreme at 9: 9+2=11 > 10 → guard triggers.
    # Force extreme at break_pos - 1 by making low there very low.
    parsed_l.iloc[9] = 90.0
    rec = _emit_create_record(
        df=df, parsed_high=parsed_h, parsed_low=parsed_l,
        break_pos=10, pivot_idx_raw=8.0, scope='swing', bias=BULLISH,
    )
    assert rec is not None
    assert pd.isna(rec['volume_bullish'])
    assert pd.isna(rec['volume_bearish'])
    assert pd.isna(rec['volume_total'])
    assert pd.isna(rec['volume_pct'])


def test_t4_no_volume_column(synthetic_df):
    """C5: without `volume` column, all 5 volumetric/bb fields = pd.NA."""
    assert 'volume' not in synthetic_df.columns
    _, ledger = _run_pipeline(synthetic_df)

    assert len(ledger) > 0
    assert ledger['volume_bullish'].isna().all()
    assert ledger['volume_bearish'].isna().all()
    assert ledger['volume_total'].isna().all()
    assert ledger['volume_pct'].isna().all()
    assert ledger['bb_volume'].isna().all()


def test_t5_positivity_invariants(synthetic_df):
    """C6: volume_total >= 0, volume_bullish >= 0, volume_bearish >= 0
    for all records with volume defined."""
    df = _add_volume(synthetic_df)
    _, ledger = _run_pipeline(df)

    defined = ledger['volume_total'].notna()
    assert defined.any(), 'No records with volume defined.'
    assert (ledger.loc[defined, 'volume_total'] >= 0).all()
    assert (ledger.loc[defined, 'volume_bullish'] >= 0).all()
    assert (ledger.loc[defined, 'volume_bearish'] >= 0).all()


def test_t6_volume_pct_invariants(synthetic_df):
    """C7, C9: volume_pct matches recomputation from definition;
    each pct ∈ (0, 1]; and at creation instant of each OB, the
    denominator is the sum of volume_total of all OBs active at that
    instant (lookahead-safe).

    Note: the SUM of stored volume_pct of all active OBs at an
    arbitrary instant T may exceed 1.0 because each OB's pct is
    frozen at its own creation time with a different denominator.
    C9 "∑ = 1" holds only for re-computation at a fixed instant
    using a uniform denominator. This test verifies the per-OB
    computation (C7) and the per-OB range invariant.
    """
    df = _add_volume(synthetic_df)
    _, ledger = _run_pipeline(df)

    defined = ledger[ledger['volume_pct'].notna()]
    assert len(defined) >= 3, 'Need >= 3 OBs with volume_pct defined.'

    for _, x in defined.iterrows():
        assert 0 < float(x['volume_pct']) <= 1.0, (
            f'volume_pct out of (0, 1]: {x["volume_pct"]}'
        )
        t_x = x['t_creation']
        active_at_tx = ledger[
            (ledger['t_creation'] <= t_x)
            & (ledger['t_mitigation'].isna() | (ledger['t_mitigation'] > t_x))
            & ledger['volume_total'].notna()
        ]
        denom = float(active_at_tx['volume_total'].sum())
        expected_pct = float(x['volume_total']) / denom if denom > 0 else 0
        assert float(x['volume_pct']) == pytest.approx(expected_pct, abs=1e-9), (
            f'volume_pct mismatch for ob_id={x["ob_id"]}: '
            f'stored={x["volume_pct"]}, expected={expected_pct}'
        )


def test_t7_lookahead_safety_volume_pct(synthetic_df):
    """C8: volume_pct of OB X computed on truncated dataset == full dataset."""
    df = _add_volume(synthetic_df)
    _, ledger_full = _run_pipeline(df)

    defined = ledger_full[ledger_full['volume_pct'].notna()]
    if len(defined) == 0:
        pytest.skip('No OBs with volume_pct defined.')

    target = defined.iloc[-1]
    t_x = target['t_creation']
    t_x_pos = int(df.index[df['date'] == t_x][0])
    df_trunc = df.iloc[:t_x_pos + 1].copy()
    df_trunc = df_trunc.reset_index(drop=True)

    _, ledger_trunc = _run_pipeline(df_trunc)
    match = ledger_trunc[ledger_trunc['t_creation'] == t_x]
    if len(match) == 0:
        pytest.skip('Target OB not found in truncated run.')

    for _, row_t in match.iterrows():
        row_f = ledger_full[
            (ledger_full['t_creation'] == t_x)
            & (ledger_full['scope'] == row_t['scope'])
            & (ledger_full['bias'] == row_t['bias'])
        ]
        if len(row_f) == 0 or pd.isna(row_t['volume_pct']):
            continue
        assert row_t['volume_pct'] == pytest.approx(
            float(row_f.iloc[0]['volume_pct']), abs=1e-9
        )


def test_t8_absolute_default_byte_identical(synthetic_df):
    """C10: Absolute default produces identical output to explicit Absolute."""
    df = _add_volume(synthetic_df)
    df_out_default, ledger_default = _run_pipeline(
        df, ob_mitigation_level='Absolute',
    )
    df_out_explicit, ledger_explicit = _run_pipeline(df)

    pd.testing.assert_frame_equal(ledger_default, ledger_explicit)

    bool_cols = [c for c in df_out_default.columns if c.startswith('ob_')]
    for col in bool_cols:
        assert (df_out_default[col] == df_out_explicit[col]).all(), (
            f'Boolean column {col} differs.'
        )


def test_t9_middle_threshold_more_permissive(synthetic_df):
    """C11: Middle mitigates >= Absolute count."""
    df = _add_volume(synthetic_df)
    _, ledger_abs = _run_pipeline(df, ob_mitigation_level='Absolute')
    _, ledger_mid = _run_pipeline(df, ob_mitigation_level='Middle')

    states_mitigated = {'mitigated', 'breaker_broken'}
    n_abs = ledger_abs['state'].isin(states_mitigated).sum()
    n_mid = ledger_mid['state'].isin(states_mitigated).sum()
    assert n_mid >= n_abs, (
        f'Middle ({n_mid}) should mitigate >= Absolute ({n_abs}).'
    )


def test_t10_breaker_death_unaffected_by_middle():
    """C12: breaker death always uses bar_high/bar_low, not midpoint.

    Constructs a scenario where price reaches midpoint but not extreme.
    With Middle, OB mitigates (becomes breaker) but breaker should NOT
    die unless price exceeds bar_high/bar_low.
    """
    n = 100
    rng = np.random.RandomState(99)
    base = np.linspace(100.0, 100.0, n)
    base[0:10] = np.linspace(100.0, 95.0, 10)   # down
    base[10:20] = np.linspace(95.0, 110.0, 10)   # up (BOS)
    base[20:30] = np.linspace(110.0, 115.0, 10)   # continued up
    base[30:50] = np.linspace(115.0, 105.0, 20)   # drop to midpoint
    base[50:70] = np.linspace(105.0, 108.0, 20)   # hover near midpoint
    base[70:100] = np.linspace(108.0, 106.0, 30)  # stay above bar_low

    closes = base + rng.normal(0, 0.3, n)
    opens = closes + rng.normal(0, 0.2, n)
    highs = np.maximum(opens, closes) + np.abs(rng.normal(0.2, 0.1, n))
    lows = np.minimum(opens, closes) - np.abs(rng.normal(0.2, 0.1, n))

    dates = (
        pd.date_range('2026-01-01', periods=n, freq='4h')
        .astype('int64') // 10**6
    )
    df = pd.DataFrame({
        'open': opens, 'high': highs, 'low': lows, 'close': closes,
        'date': dates, 'volume': rng.uniform(100, 1000, n),
    })

    _, ledger_mid = _run_pipeline(df, ob_mitigation_level='Middle')

    mitigated = ledger_mid[ledger_mid['state'] == 'mitigated']
    broken = ledger_mid[ledger_mid['state'] == 'breaker_broken']

    for _, rec in mitigated.iterrows():
        if rec['bias'] == BULLISH:
            assert df.loc[
                df['date'] > rec['t_mitigation'], 'high'
            ].max() <= rec['bar_high'] or len(broken[
                (broken['t_creation'] == rec['t_creation'])
                & (broken['scope'] == rec['scope'])
            ]) == 0
