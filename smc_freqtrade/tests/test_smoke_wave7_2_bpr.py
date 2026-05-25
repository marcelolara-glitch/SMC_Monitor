"""
OBJETIVO
    Smoke test da Onda 7.2 — Balanced Price Range (BPR) + 7.x
    Volatility threshold. Cobre 4 cenários sintéticos (§8 do briefing)
    + invariantes B1-B5 sobre os resultados.

FONTE DE DADOS
    Fixtures sintéticas determinísticas com OHLC fabricado para
    materializar exatamente as condições geométricas de overlap entre
    FVGs bullish e bearish. auto_threshold=False isola a lógica de
    composição BPR da interação com o threshold.

NÃO FAZER
    Não importar de smc_freqtrade.smc_engine — pacote raiz é
    `smc_engine`.
"""
from __future__ import annotations

import pandas as pd
import pytest

from smc_engine import BEARISH, BULLISH, detect_fair_value_gaps
from smc_engine.fvg import compose_balanced_price_ranges


def _make_dates(n: int) -> pd.Series:
    return (
        pd.date_range('2026-01-01', periods=n, freq='4h')
        .astype('int64') // 10**6
    )


def _df_from_rows(
    rows: list[tuple[float, float, float, float]],
) -> pd.DataFrame:
    opens, highs, lows, closes = zip(*rows)
    return pd.DataFrame({
        'open': list(opens),
        'high': list(highs),
        'low': list(lows),
        'close': list(closes),
        'date': _make_dates(len(rows)),
    })


def _flat(base: float, n: int) -> list[tuple[float, float, float, float]]:
    """Generate n flat candles that never create FVG patterns."""
    return [(base, base + 0.2, base - 0.2, base + 0.1) for _ in range(n)]


# ============================================================
# Smoke A — BPR_UP
#
# bear created first: top=104.0, bottom=101.0
# bull created second: top=103.0, bottom=102.0
# bear still active when bull forms (no high > 104.0 in between)
#
# BPR_UP: bull.bottom(102.0) < bear.top(104.0) ✓
#         bear.bottom(101.0) < bull.bottom(102.0) ✓
# Zone: top=bear.top=104.0, bottom=bull.bottom=102.0
# ============================================================

@pytest.fixture
def fixture_bpr_up() -> pd.DataFrame:
    rows: list[tuple[float, float, float, float]] = []
    rows.extend(_flat(102.0, 5))

    # idx 5 (t-2 bear): low=104.0
    rows.append((102.2, 102.5, 104.0, 102.3))
    # oops, low can't be > high. Fix OHLC:
    # Need a candle with low=104.0. It must have high >= 104.0.
    rows[-1] = (104.5, 105.0, 104.0, 104.8)
    # idx 6 (t-1 bear): close=101.5 < low[5]=104.0, big bearish
    rows.append((104.8, 105.0, 101.0, 101.5))
    # idx 7 (t bear): high=101.0 < low[5]=104.0
    rows.append((101.0, 101.0, 100.5, 100.8))
    # bear: top=104.0, bottom=101.0

    # idx 8-9: flat near 101 — highs < 104.0, lows overlap with idx 6-7
    rows.append((100.8, 101.5, 100.5, 101.0))
    rows.append((101.0, 101.5, 100.8, 101.2))

    # idx 10 (t-2 bull): high=102.0
    rows.append((101.2, 102.0, 101.0, 101.5))
    # idx 11 (t-1 bull): close=103.0 > high[10]=102.0
    # high must stay < 104.0 to not mitigate bear
    rows.append((101.5, 103.5, 101.2, 103.0))
    # idx 12 (t bull): low=103.0 > high[10]=102.0
    rows.append((103.0, 103.5, 103.0, 103.2))
    # bull: top=103.0, bottom=102.0

    # Check no unintended FVGs:
    # idx 9 as t: low[9]=100.8, high[7]=101.0 → low < high[t-2]: 100.8<101.0 → no bullish
    #   high[9]=101.5, low[7]=100.5 → high > low[t-2]: yes, but is bearish check
    #   For bearish: high[t] < low[t-2]. high[9]=101.5, low[7]=100.5 → 101.5 < 100.5? NO
    # idx 10 as t: low[10]=101.0, high[8]=101.5 → 101.0 < 101.5? YES but need low > high
    #   bullish: low[t] > high[t-2]? 101.0 > 101.5? NO
    # idx 11 as t: low[11]=101.2, high[9]=101.5 → 101.2 > 101.5? NO → no bullish at 11

    rows.extend(_flat(103.0, 5))
    return _df_from_rows(rows)


def test_smoke_a_bpr_up(fixture_bpr_up):
    """Smoke A — BPR_UP formed from bear + bull FVGs with overlap."""
    _, ledger = detect_fair_value_gaps(
        fixture_bpr_up, auto_threshold=False,
    )
    ledger_bpr, ledger_marked = compose_balanced_price_ranges(ledger)

    assert len(ledger_bpr) == 1
    bpr = ledger_bpr.iloc[0]
    assert bpr['bias'] == BULLISH
    assert abs(bpr['top'] - 104.0) < 1e-9
    assert abs(bpr['bottom'] - 102.0) < 1e-9

    bull_t = fixture_bpr_up['date'].iloc[12]
    assert bpr['t_creation'] == bull_t

    bull_id = int(bpr['fvg_id_bull'])
    bear_id = int(bpr['fvg_id_bear'])
    assert ledger_marked.loc[
        ledger_marked['fvg_id'] == bull_id, 'is_double'
    ].iloc[0] == True  # noqa: E712
    assert ledger_marked.loc[
        ledger_marked['fvg_id'] == bear_id, 'is_double'
    ].iloc[0] == True  # noqa: E712

    bull_row = ledger_marked.loc[ledger_marked['fvg_id'] == bull_id].iloc[0]
    bear_row = ledger_marked.loc[ledger_marked['fvg_id'] == bear_id].iloc[0]
    assert bull_row['bias'] == BULLISH
    assert bear_row['bias'] == BEARISH


# ============================================================
# Smoke B — no overlap: bull and bear fully disjoint
# ============================================================

@pytest.fixture
def fixture_no_overlap() -> pd.DataFrame:
    """Bear zone at 120-118, bull zone at 97-96. Disjoint.
    Transition uses tight flat candles to avoid extra FVGs.
    """
    rows: list[tuple[float, float, float, float]] = []
    rows.extend(_flat(120.0, 5))

    # idx 5-7: bearish FVG
    rows.append((120.2, 120.5, 120.0, 120.3))  # t-2: low=120.0
    rows.append((120.3, 120.5, 117.0, 117.5))  # t-1: close=117.5 < 120.0
    rows.append((117.5, 118.0, 117.0, 117.5))  # t: high=118.0 < 120.0
    # bear: top=120.0, bottom=118.0

    # idx 8-14: gradual descent to 96 area, tight candles
    for i, lvl in enumerate([117.0, 115.0, 113.0, 111.0, 109.0, 107.0, 105.0]):
        rows.append((lvl + 1, lvl + 2.5, lvl, lvl + 0.5))

    # idx 15-17: bullish FVG
    rows.append((97.5, 96.0, 95.5, 95.8))   # t-2: high=96.0
    rows.append((95.8, 98.0, 95.5, 97.5))   # t-1: close=97.5 > 96.0
    rows.append((97.5, 98.0, 97.0, 97.8))   # t: low=97.0 > 96.0
    # bull: top=97.0, bottom=96.0

    # bear(118-120), bull(96-97) → completely disjoint
    rows.extend(_flat(97.0, 5))
    return _df_from_rows(rows)


def test_smoke_b_no_overlap(fixture_no_overlap):
    """Smoke B — no overlap produces empty BPR ledger."""
    _, ledger = detect_fair_value_gaps(
        fixture_no_overlap, auto_threshold=False,
    )
    # Verify we have at least one bull and one bear
    assert (ledger['bias'] == BULLISH).any()
    assert (ledger['bias'] == BEARISH).any()

    ledger_bpr, ledger_marked = compose_balanced_price_ranges(ledger)
    assert len(ledger_bpr) == 0
    assert (ledger_marked['is_double'] == False).all()  # noqa: E712


# ============================================================
# Smoke C — opposite dead before pair
# ============================================================

@pytest.fixture
def fixture_dead_opposite() -> pd.DataFrame:
    """Bear first (top=104.0, bottom=101.0), mitigated at idx 8,
    then bull (top=103.0, bottom=102.0) at idx 14 — same geometry as
    fixture_bpr_up but bear is dead. Tight candles avoid extra FVGs.
    """
    rows: list[tuple[float, float, float, float]] = []
    rows.extend(_flat(102.0, 5))

    # idx 5-7: bearish FVG
    rows.append((104.5, 105.0, 104.0, 104.8))  # t-2: low=104.0
    rows.append((104.8, 105.0, 101.0, 101.5))  # t-1: close=101.5 < 104.0
    rows.append((101.0, 101.0, 100.5, 100.8))  # t: high=101.0 < 104.0
    # bear: top=104.0, bottom=101.0

    # idx 8: mitigates bear (high > 104.0)
    rows.append((100.8, 106.0, 100.5, 105.5))

    # idx 9-11: tight flat around 102.0 to avoid extra FVGs
    # Must ensure no 3-candle gaps form from the big candle at idx 8.
    # idx 8: high=106.0, low=100.5
    # idx 9 needs overlap with both idx 7 and idx 8 to avoid gaps
    rows.append((105.5, 106.0, 102.0, 102.5))  # overlaps idx 7 (low=100.5)
    rows.append((102.5, 103.0, 102.0, 102.5))  # tight
    rows.append((102.5, 103.0, 102.0, 102.5))  # tight

    # idx 12-14: bullish FVG
    rows.append((102.0, 102.0, 101.5, 101.8))  # t-2: high=102.0
    rows.append((101.8, 103.5, 101.5, 103.0))  # t-1: close=103.0 > 102.0
    rows.append((103.0, 103.5, 103.0, 103.2))  # t: low=103.0 > 102.0
    # bull: top=103.0, bottom=102.0

    # bull would BPR_UP with bear if bear were active, but bear was
    # mitigated at idx 8. bear.t_mitigation < bull.t_creation → no BPR.

    rows.extend(_flat(103.0, 5))
    return _df_from_rows(rows)


def test_smoke_c_dead_opposite(fixture_dead_opposite):
    """Smoke C — bear mitigated before bull created → no BPR."""
    _, ledger = detect_fair_value_gaps(
        fixture_dead_opposite, auto_threshold=False,
    )

    bear = ledger[ledger['bias'] == BEARISH]
    assert len(bear) >= 1
    assert bear.iloc[0]['state'] in ('mitigated', 'inverse_broken')

    ledger_bpr, ledger_marked = compose_balanced_price_ranges(ledger)
    assert len(ledger_bpr) == 0
    assert (ledger_marked['is_double'] == False).all()  # noqa: E712


# ============================================================
# Smoke D — Volatility threshold no-op and filtering
# ============================================================

def test_smoke_d_volatility_noop(fixture_bpr_up):
    """Smoke D — volatility_threshold=None is identical to baseline."""
    df_base, ledger_base = detect_fair_value_gaps(
        fixture_bpr_up, auto_threshold=True,
    )
    df_none, ledger_none = detect_fair_value_gaps(
        fixture_bpr_up, auto_threshold=True, volatility_threshold=None,
    )

    pd.testing.assert_frame_equal(df_base, df_none)
    pd.testing.assert_frame_equal(ledger_base, ledger_none)


def test_smoke_d_volatility_high_filters(fixture_bpr_up):
    """Smoke D — high volatility_threshold produces subset of FVGs."""
    _, ledger_base = detect_fair_value_gaps(
        fixture_bpr_up, auto_threshold=True, volatility_threshold=None,
    )
    _, ledger_strict = detect_fair_value_gaps(
        fixture_bpr_up, auto_threshold=True, volatility_threshold=5.0,
    )

    assert len(ledger_strict) <= len(ledger_base)

    if len(ledger_strict) > 0:
        key_cols = ['bias', 't_creation', 'top', 'bottom']
        keys_base = set(map(tuple, ledger_base[key_cols].values))
        keys_strict = set(map(tuple, ledger_strict[key_cols].values))
        assert keys_strict.issubset(keys_base)


# ============================================================
# Invariants B1-B5
# ============================================================

def test_invariant_b1_member_bias(fixture_bpr_up):
    """B1 — fvg_id_bull references BULLISH, fvg_id_bear references BEARISH."""
    _, ledger = detect_fair_value_gaps(
        fixture_bpr_up, auto_threshold=False,
    )
    ledger_bpr, _ = compose_balanced_price_ranges(ledger)
    assert len(ledger_bpr) > 0

    for _, bpr in ledger_bpr.iterrows():
        bull_row = ledger[ledger['fvg_id'] == bpr['fvg_id_bull']]
        bear_row = ledger[ledger['fvg_id'] == bpr['fvg_id_bear']]
        assert len(bull_row) == 1
        assert len(bear_row) == 1
        assert bull_row.iloc[0]['bias'] == BULLISH
        assert bear_row.iloc[0]['bias'] == BEARISH


def test_invariant_b2_overlap_geometry(fixture_bpr_up):
    """B2 — members satisfy strict overlap condition and zone matches."""
    _, ledger = detect_fair_value_gaps(
        fixture_bpr_up, auto_threshold=False,
    )
    ledger_bpr, _ = compose_balanced_price_ranges(ledger)
    assert len(ledger_bpr) > 0

    for _, bpr in ledger_bpr.iterrows():
        bull = ledger[ledger['fvg_id'] == bpr['fvg_id_bull']].iloc[0]
        bear = ledger[ledger['fvg_id'] == bpr['fvg_id_bear']].iloc[0]

        if bpr['bias'] == BULLISH:
            assert bull['bottom'] < bear['top']
            assert bear['bottom'] < bull['bottom']
            assert abs(bpr['top'] - bear['top']) < 1e-9
            assert abs(bpr['bottom'] - bull['bottom']) < 1e-9
        else:
            assert bear['bottom'] < bull['top']
            assert bull['bottom'] < bear['bottom']
            assert abs(bpr['top'] - bull['top']) < 1e-9
            assert abs(bpr['bottom'] - bear['bottom']) < 1e-9

        assert bpr['top'] > bpr['bottom']


def test_invariant_b3_t_creation(fixture_bpr_up):
    """B3 — BPR.t_creation == max(t_creation of both members)."""
    _, ledger = detect_fair_value_gaps(
        fixture_bpr_up, auto_threshold=False,
    )
    ledger_bpr, _ = compose_balanced_price_ranges(ledger)
    assert len(ledger_bpr) > 0

    for _, bpr in ledger_bpr.iterrows():
        bull = ledger[ledger['fvg_id'] == bpr['fvg_id_bull']].iloc[0]
        bear = ledger[ledger['fvg_id'] == bpr['fvg_id_bear']].iloc[0]
        expected_t = max(bull['t_creation'], bear['t_creation'])
        assert bpr['t_creation'] == expected_t


def test_invariant_b4_members_active(fixture_bpr_up):
    """B4 — both members active at BPR.t_creation."""
    _, ledger = detect_fair_value_gaps(
        fixture_bpr_up, auto_threshold=False,
    )
    ledger_bpr, _ = compose_balanced_price_ranges(ledger)
    assert len(ledger_bpr) > 0

    for _, bpr in ledger_bpr.iterrows():
        bull = ledger[ledger['fvg_id'] == bpr['fvg_id_bull']].iloc[0]
        bear = ledger[ledger['fvg_id'] == bpr['fvg_id_bear']].iloc[0]
        t_bpr = bpr['t_creation']

        for member in (bull, bear):
            assert member['t_creation'] <= t_bpr
            if not pd.isna(member['t_mitigation']):
                assert member['t_mitigation'] > t_bpr


def test_invariant_b5_is_double(fixture_bpr_up):
    """B5 — is_double==True iff fvg_id appears as member of >=1 BPR."""
    _, ledger = detect_fair_value_gaps(
        fixture_bpr_up, auto_threshold=False,
    )
    ledger_bpr, ledger_marked = compose_balanced_price_ranges(ledger)

    member_ids = set()
    for _, bpr in ledger_bpr.iterrows():
        member_ids.add(int(bpr['fvg_id_bull']))
        member_ids.add(int(bpr['fvg_id_bear']))

    for _, fvg in ledger_marked.iterrows():
        if int(fvg['fvg_id']) in member_ids:
            assert fvg['is_double'] == True  # noqa: E712
        else:
            assert fvg['is_double'] == False  # noqa: E712


# ============================================================
# BPR schema validation
# ============================================================

def test_bpr_schema_columns(fixture_bpr_up):
    """BPR ledger has exactly the 7 columns in the correct order."""
    _, ledger = detect_fair_value_gaps(
        fixture_bpr_up, auto_threshold=False,
    )
    ledger_bpr, _ = compose_balanced_price_ranges(ledger)
    expected = [
        'bpr_id', 'bias', 'top', 'bottom', 't_creation',
        'fvg_id_bull', 'fvg_id_bear',
    ]
    assert list(ledger_bpr.columns) == expected


def test_bpr_schema_dtypes(fixture_bpr_up):
    """BPR ledger columns have the correct dtypes."""
    _, ledger = detect_fair_value_gaps(
        fixture_bpr_up, auto_threshold=False,
    )
    ledger_bpr, _ = compose_balanced_price_ranges(ledger)
    assert len(ledger_bpr) > 0

    assert ledger_bpr['bpr_id'].dtype == 'int64'
    assert ledger_bpr['bias'].dtype == 'int64'
    assert ledger_bpr['top'].dtype == 'float64'
    assert ledger_bpr['bottom'].dtype == 'float64'
    assert ledger_bpr['fvg_id_bull'].dtype == 'int64'
    assert ledger_bpr['fvg_id_bear'].dtype == 'int64'


def test_bpr_empty_ledger():
    """Empty FVG ledger produces empty BPR ledger with correct schema."""
    empty_fvg = pd.DataFrame({
        'fvg_id': pd.Series(dtype='int64'),
        'bias': pd.Series(dtype='int64'),
        'top': pd.Series(dtype='float64'),
        'bottom': pd.Series(dtype='float64'),
        'bar_time': pd.Series(dtype='object'),
        't_creation': pd.Series(dtype='object'),
        't_mitigation': pd.Series(dtype='object'),
        't_invalidation': pd.Series(dtype='object'),
        'state': pd.Series(dtype='object'),
        'is_inverse': pd.Series(dtype='bool'),
        'is_double': pd.Series(dtype='bool'),
    })
    ledger_bpr, ledger_marked = compose_balanced_price_ranges(empty_fvg)
    assert len(ledger_bpr) == 0
    expected = [
        'bpr_id', 'bias', 'top', 'bottom', 't_creation',
        'fvg_id_bull', 'fvg_id_bear',
    ]
    assert list(ledger_bpr.columns) == expected
    assert len(ledger_marked) == 0


# ============================================================
# BPR_DN test
#
# bull created first: top=105.0, bottom=100.0
# bear created second: top=108.0, bottom=103.0
#
# BPR_DN: bear.bottom(103) < bull.top(105) ✓
#         bull.bottom(100) < bear.bottom(103) ✓
# Zone: top=bull.top=105.0, bottom=bear.bottom=103.0
# ============================================================

@pytest.fixture
def fixture_bpr_dn() -> pd.DataFrame:
    rows: list[tuple[float, float, float, float]] = []
    rows.extend(_flat(100.0, 5))

    # idx 5-7: bullish FVG
    rows.append((100.0, 100.0, 99.5, 99.8))    # t-2: high=100.0
    rows.append((99.8, 107.0, 99.5, 106.5))    # t-1: close=106.5 > 100.0
    rows.append((106.5, 107.5, 105.0, 107.0))  # t: low=105.0 > 100.0
    # bull: top=105.0, bottom=100.0

    # idx 8-9: flat near 108 — lows > 100.0 to keep bull active
    rows.append((107.0, 108.5, 106.5, 108.0))
    rows.append((108.0, 108.5, 107.5, 108.2))

    # idx 10-12: bearish FVG
    rows.append((108.2, 108.5, 108.0, 108.3))  # t-2: low=108.0
    rows.append((108.3, 108.5, 102.0, 102.5))  # t-1: close=102.5 < 108.0, low=102 > 100
    rows.append((102.5, 103.0, 101.5, 102.0))  # t: high=103.0 < 108.0
    # bear: top=108.0, bottom=103.0

    # Check bull not mitigated: all lows after idx 7 must be >= 100.0
    # idx 8: 106.5 ✓, idx 9: 107.5 ✓, idx 10: 108.0 ✓
    # idx 11: 102.0 ✓, idx 12: 101.5 ✓

    # Check no unintended FVGs at idx 9:
    # bullish: low[9]=107.5 > high[7]=107.5? NO (not strict >)
    # bearish: high[9]=108.5 < low[7]=105.0? NO

    # Check idx 10: bullish: low[10]=108.0 > high[8]=108.5? NO
    # Check idx 11: bullish: low[11]=102.0 > high[9]=108.5? NO
    #               bearish: high[11]=108.5 < low[9]=107.5? NO

    rows.extend(_flat(102.0, 5))
    return _df_from_rows(rows)


def test_bpr_dn(fixture_bpr_dn):
    """BPR_DN formed correctly with bull created first, bear second."""
    _, ledger = detect_fair_value_gaps(
        fixture_bpr_dn, auto_threshold=False,
    )
    ledger_bpr, ledger_marked = compose_balanced_price_ranges(ledger)

    assert len(ledger_bpr) == 1
    bpr = ledger_bpr.iloc[0]
    assert bpr['bias'] == BEARISH
    assert abs(bpr['top'] - 105.0) < 1e-9
    assert abs(bpr['bottom'] - 103.0) < 1e-9

    bear_t = fixture_bpr_dn['date'].iloc[12]
    assert bpr['t_creation'] == bear_t

    bull_id = int(bpr['fvg_id_bull'])
    bear_id = int(bpr['fvg_id_bear'])
    assert ledger_marked.loc[
        ledger_marked['fvg_id'] == bull_id, 'is_double'
    ].iloc[0] == True  # noqa: E712
    assert ledger_marked.loc[
        ledger_marked['fvg_id'] == bear_id, 'is_double'
    ].iloc[0] == True  # noqa: E712
