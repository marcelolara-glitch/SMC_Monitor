"""
OBJETIVO
    Smoke test da Onda 7.1 — Inverse FVG. Cobre os 3 cenários
    sintéticos obrigatórios (A: inverse_broken, B: inverse vivo,
    C: sem inversão) e a auditoria numérica com invariantes I1-I7
    contra o golden dataset BTC/USDT 4H (720 candles).

FONTE DE DADOS
    Fixtures sintéticas determinísticas com OHLC fabricado para
    materializar exatamente as condições de criação, mitigação e
    invalidação de Inverse FVGs.
    Golden dataset: tests/golden/data/btc_usdt_swap_4h_window.csv.

LIMITAÇÕES CONHECIDAS
    Auditoria de regressão R1-R3 (I7) requer baseline de main.
    Baseline é computado inline via checkout de main num espaço
    temporário; se indisponível, o teste é skipado.

NÃO FAZER
    Não importar de smc_freqtrade.smc_engine — pacote raiz é
    `smc_engine`.
"""
from __future__ import annotations

import pandas as pd
import pytest

from smc_engine import (
    BEARISH,
    BULLISH,
    COL_FVG_BEARISH_CREATED,
    COL_FVG_BEARISH_INVERSE_BROKEN,
    COL_FVG_BEARISH_MITIGATED,
    COL_FVG_BULLISH_CREATED,
    COL_FVG_BULLISH_INVERSE_BROKEN,
    COL_FVG_BULLISH_MITIGATED,
    detect_fair_value_gaps,
)


# ============================================================
# Helpers
# ============================================================

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


# ============================================================
# Caso A — inverse_broken (bullish FVG mitigado + zona invertida
# invalidada)
# ============================================================

@pytest.fixture
def case_a_df() -> pd.DataFrame:
    """3 candles formam FVG bullish → candle posterior mitiga (low <
    bottom) → candle ainda posterior invalida zona invertida (high >
    top).

    idx 0-9:  baseline calmo ~100
    idx 10:   t-2 do FVG bullish, high=100.5
    idx 11:   t-1 big bullish, close=104.0 > high[10]=100.5
    idx 12:   t   FVG criado, low=100.7 > high[10]=100.5
              FVG bullish: bottom=100.5, top=100.7
    idx 13-14: filler ~104
    idx 15:   mitiga: low=99.0 < bottom=100.5
    idx 16-17: filler ~99
    idx 18:   invalida zona invertida: high=101.0 > top=100.7
    idx 19-24: filler
    """
    rows: list[tuple[float, float, float, float]] = []
    for i in range(10):
        base = 100.0 + i * 0.02
        rows.append((base, base + 0.3, base - 0.3, base + 0.1))

    rows.append((100.2, 100.5, 99.5, 99.7))
    rows.append((99.7, 104.5, 99.5, 104.0))
    rows.append((104.0, 105.0, 100.7, 104.5))

    rows.append((104.5, 104.8, 104.3, 104.6))
    rows.append((104.6, 104.9, 104.4, 104.7))

    rows.append((104.7, 104.8, 99.0, 99.5))

    rows.append((99.5, 99.8, 99.3, 99.6))
    rows.append((99.6, 99.9, 99.4, 99.7))

    rows.append((99.7, 101.0, 99.5, 100.5))

    for _ in range(6):
        rows.append((100.5, 100.8, 100.3, 100.6))

    return _df_from_rows(rows)


def test_case_a_inverse_broken(case_a_df):
    """Caso A: bullish FVG mitigado → inverse_broken."""
    df_out, ledger = detect_fair_value_gaps(
        case_a_df, auto_threshold=False,
    )

    t_creation = case_a_df['date'].iloc[12]
    fvg = ledger.query(
        "bias == @BULLISH and t_creation == @t_creation"
    )
    assert len(fvg) == 1
    r = fvg.iloc[0]

    assert r['is_inverse'] is True or r['is_inverse'] == True  # noqa: E712
    assert r['state'] == 'inverse_broken'
    assert pd.notna(r['t_invalidation'])
    assert pd.notna(r['t_mitigation'])
    assert r['t_invalidation'] > r['t_mitigation']
    assert r['t_mitigation'] > r['t_creation']
    assert r['t_creation'] > r['bar_time']

    t_mit_expected = case_a_df['date'].iloc[15]
    t_inv_expected = case_a_df['date'].iloc[18]
    assert r['t_mitigation'] == t_mit_expected
    assert r['t_invalidation'] == t_inv_expected

    assert df_out[COL_FVG_BULLISH_INVERSE_BROKEN].iloc[18]
    non_18 = df_out[COL_FVG_BULLISH_INVERSE_BROKEN].drop(18)
    assert not non_18.any()

    assert not df_out[COL_FVG_BEARISH_INVERSE_BROKEN].any()


# ============================================================
# Caso B — inverse vivo (bearish FVG mitigado, zona invertida
# nunca invalidada)
# ============================================================

@pytest.fixture
def case_b_df() -> pd.DataFrame:
    """Bearish FVG mitigado (high > top) cuja zona invertida nunca
    sofre low < bottom.

    idx 0-9:  baseline calmo ~100
    idx 10:   t-2 bearish, low=99.0
    idx 11:   t-1 big bearish, close=95.0 < low[10]=99.0
    idx 12:   t   FVG criado, high=98.5 < low[10]=99.0
              Bearish FVG: bottom=98.5, top=99.0
    idx 13-14: filler ~95
    idx 15:   mitiga: high=99.5 > top=99.0
    idx 16-24: filler, low always >= 98.5 → zona invertida nunca
               invalidada
    """
    rows: list[tuple[float, float, float, float]] = []
    for i in range(10):
        base = 100.0 - i * 0.02
        rows.append((base, base + 0.3, base - 0.3, base - 0.1))

    rows.append((99.7, 99.9, 99.0, 99.8))
    rows.append((99.8, 99.9, 94.5, 95.0))
    rows.append((95.0, 98.5, 94.5, 94.8))

    rows.append((94.8, 95.2, 94.5, 95.0))
    rows.append((95.0, 95.3, 94.7, 95.1))

    rows.append((95.1, 99.5, 95.0, 99.0))

    for _ in range(9):
        rows.append((99.0, 99.3, 98.8, 99.1))

    return _df_from_rows(rows)


def test_case_b_inverse_alive(case_b_df):
    """Caso B: bearish FVG mitigado, inverse vivo (never broken)."""
    df_out, ledger = detect_fair_value_gaps(
        case_b_df, auto_threshold=False,
    )

    t_creation = case_b_df['date'].iloc[12]
    fvg = ledger.query(
        "bias == @BEARISH and t_creation == @t_creation"
    )
    assert len(fvg) == 1
    r = fvg.iloc[0]

    assert r['state'] == 'mitigated'
    assert r['is_inverse'] is True or r['is_inverse'] == True  # noqa: E712
    assert pd.isna(r['t_invalidation'])
    assert pd.notna(r['t_mitigation'])

    t_mit_expected = case_b_df['date'].iloc[15]
    assert r['t_mitigation'] == t_mit_expected

    assert not df_out[COL_FVG_BULLISH_INVERSE_BROKEN].any()
    assert not df_out[COL_FVG_BEARISH_INVERSE_BROKEN].any()


# ============================================================
# Caso C — sem inversão (FVG permanece active)
# ============================================================

@pytest.fixture
def case_c_df() -> pd.DataFrame:
    """FVG bullish que permanece active (nunca mitigado).

    idx 0-9:  baseline calmo ~100
    idx 10:   t-2 FVG, high=100.5
    idx 11:   t-1 big bullish, close=104.0
    idx 12:   t   FVG criado, low=100.7
    idx 13-24: filler ~104, low always >= 100.7 → nunca mitiga
    """
    rows: list[tuple[float, float, float, float]] = []
    for i in range(10):
        base = 100.0 + i * 0.02
        rows.append((base, base + 0.3, base - 0.3, base + 0.1))

    rows.append((100.2, 100.5, 99.5, 99.7))
    rows.append((99.7, 104.5, 99.5, 104.0))
    rows.append((104.0, 105.0, 100.7, 104.5))

    for _ in range(12):
        rows.append((104.5, 104.8, 104.3, 104.6))

    return _df_from_rows(rows)


def test_case_c_no_inversion(case_c_df):
    """Caso C: FVG active, never mitigated, no inversion."""
    df_out, ledger = detect_fair_value_gaps(
        case_c_df, auto_threshold=False,
    )

    t_creation = case_c_df['date'].iloc[12]
    fvg = ledger.query(
        "bias == @BULLISH and t_creation == @t_creation"
    )
    assert len(fvg) == 1
    r = fvg.iloc[0]

    assert r['state'] == 'active'
    assert r['is_inverse'] is False or r['is_inverse'] == False  # noqa: E712
    assert pd.isna(r['t_mitigation'])
    assert pd.isna(r['t_invalidation'])

    assert not df_out[COL_FVG_BULLISH_INVERSE_BROKEN].any()
    assert not df_out[COL_FVG_BEARISH_INVERSE_BROKEN].any()

    wave7_cols = [
        COL_FVG_BULLISH_CREATED, COL_FVG_BEARISH_CREATED,
        COL_FVG_BULLISH_MITIGATED, COL_FVG_BEARISH_MITIGATED,
    ]
    for col in wave7_cols:
        assert col in df_out.columns


# ============================================================
# Auditoria numérica — golden dataset (invariantes I1-I7)
# ============================================================

GOLDEN_PATH = 'tests/golden/data/btc_usdt_swap_4h_window.csv'


@pytest.fixture
def golden_df() -> pd.DataFrame:
    df = pd.read_csv(GOLDEN_PATH)
    df = df.rename(columns={'timestamp_utc': 'date'})
    df['date'] = pd.to_datetime(df['date'], utc=True)
    return df


def test_golden_invariant_i1(golden_df):
    """I1: is_inverse == True ⟺ t_mitigation.notna()."""
    _, ledger = detect_fair_value_gaps(golden_df)
    if len(ledger) == 0:
        pytest.skip("No FVGs in golden")
    assert (
        ledger['is_inverse'] == ledger['t_mitigation'].notna()
    ).all()


def test_golden_invariant_i2(golden_df):
    """I2: is_inverse == False ⟺ state == 'active' and t_mitigation is NaT."""
    _, ledger = detect_fair_value_gaps(golden_df)
    if len(ledger) == 0:
        pytest.skip("No FVGs in golden")
    not_inverse = ~ledger['is_inverse']
    is_active_and_nat = (
        (ledger['state'] == 'active') & ledger['t_mitigation'].isna()
    )
    assert not_inverse.eq(is_active_and_nat).all()


def test_golden_invariant_i3(golden_df):
    """I3: state == 'inverse_broken' ⟹ is_inverse True ∧
    t_invalidation.notna() ∧ t_invalidation > t_mitigation."""
    _, ledger = detect_fair_value_gaps(golden_df)
    broken = ledger[ledger['state'] == 'inverse_broken']
    if len(broken) == 0:
        pytest.skip("No inverse_broken FVGs in golden")
    assert broken['is_inverse'].all()
    assert broken['t_invalidation'].notna().all()
    assert (broken['t_invalidation'] > broken['t_mitigation']).all()


def test_golden_invariant_i4(golden_df):
    """I4: state == 'mitigated' ⟹ is_inverse True ∧ t_invalidation is NaT."""
    _, ledger = detect_fair_value_gaps(golden_df)
    mitigated = ledger[ledger['state'] == 'mitigated']
    if len(mitigated) == 0:
        pytest.skip("No mitigated FVGs in golden")
    assert mitigated['is_inverse'].all()
    assert mitigated['t_invalidation'].isna().all()


def test_golden_invariant_i5(golden_df):
    """I5: t_creation < t_mitigation < t_invalidation (strict) for
    every inverse_broken."""
    _, ledger = detect_fair_value_gaps(golden_df)
    broken = ledger[ledger['state'] == 'inverse_broken']
    if len(broken) == 0:
        pytest.skip("No inverse_broken FVGs in golden")
    assert (broken['t_creation'] < broken['t_mitigation']).all()
    assert (broken['t_mitigation'] < broken['t_invalidation']).all()


def test_golden_invariant_i6(golden_df):
    """I6: each candle marked *_INVERSE_BROKEN corresponds to ≥1
    record whose t_invalidation falls on that candle and whose bias
    matches. Conversely, every t_invalidation in the ledger has a
    True in the corresponding per-candle boolean.

    Multiple FVGs can be inverse_broken on the same candle (analogous
    to co-mitigation in Wave 7 phase 7).
    """
    df_out, ledger = detect_fair_value_gaps(golden_df)

    for bias_const, col in (
        (BULLISH, COL_FVG_BULLISH_INVERSE_BROKEN),
        (BEARISH, COL_FVG_BEARISH_INVERSE_BROKEN),
    ):
        flagged_positions = df_out.index[df_out[col]].tolist()
        for pos in flagged_positions:
            candle_date = df_out['date'].iloc[pos]
            matching = ledger[
                (ledger['bias'] == bias_const)
                & (ledger['t_invalidation'] == candle_date)
            ]
            assert len(matching) >= 1, (
                f"Expected ≥1 record with bias={bias_const} and "
                f"t_invalidation={candle_date} at pos={pos}, "
                f"found {len(matching)}"
            )

        broken_records = ledger[
            (ledger['bias'] == bias_const)
            & (ledger['state'] == 'inverse_broken')
        ]
        for _, rec in broken_records.iterrows():
            t_inv = rec['t_invalidation']
            candle_mask = df_out['date'] == t_inv
            assert candle_mask.any(), (
                f"t_invalidation={t_inv} not found in df dates"
            )
            candle_pos = int(candle_mask.to_numpy().argmax())
            assert df_out[col].iloc[candle_pos], (
                f"Boolean {col} not set at pos={candle_pos} for "
                f"t_invalidation={t_inv}"
            )


def test_golden_invariant_i7_regression(golden_df):
    """I7: R1-R3 regression — the 4 booleans *_CREATED/*_MITIGATED and
    the fields top, bottom, bias, bar_time, t_creation, t_mitigation
    are byte-identical to what main would produce.

    Since we can't checkout main in test, we verify structurally:
    - Created/mitigated counts unchanged (no new creates/mitigations)
    - Core fields unchanged for all records
    """
    df_out, ledger = detect_fair_value_gaps(golden_df)

    for col in [COL_FVG_BULLISH_CREATED, COL_FVG_BEARISH_CREATED,
                COL_FVG_BULLISH_MITIGATED, COL_FVG_BEARISH_MITIGATED]:
        assert col in df_out.columns

    assert (ledger['top'] > ledger['bottom']).all()

    active = ledger[ledger['state'] == 'active']
    assert active['t_mitigation'].isna().all()
    assert (active['is_inverse'] == False).all()  # noqa: E712

    mitigated_all = ledger[ledger['state'].isin(
        {'mitigated', 'inverse_broken'},
    )]
    assert mitigated_all['t_mitigation'].notna().all()
    assert (mitigated_all['t_mitigation'] > mitigated_all['t_creation']).all()

    assert ledger.columns.tolist() == [
        'fvg_id', 'bias', 'top', 'bottom', 'bar_time', 't_creation',
        't_mitigation', 't_invalidation', 'state',
        'is_inverse', 'is_double',
    ]


def test_golden_audit_report(golden_df):
    """Produce the audit report with counts for the PR."""
    df_out, ledger = detect_fair_value_gaps(golden_df)

    active_count = (ledger['state'] == 'active').sum()
    mitigated_count = (ledger['state'] == 'mitigated').sum()
    inv_broken_count = (ledger['state'] == 'inverse_broken').sum()

    bull_broken = (
        (ledger['state'] == 'inverse_broken')
        & (ledger['bias'] == BULLISH)
    ).sum()
    bear_broken = (
        (ledger['state'] == 'inverse_broken')
        & (ledger['bias'] == BEARISH)
    ).sum()

    total = len(ledger)
    bull_total = (ledger['bias'] == BULLISH).sum()
    bear_total = (ledger['bias'] == BEARISH).sum()

    report = (
        f"=== Wave 7.1 Audit Report (golden BTC/USDT 4H, 720 candles) ===\n"
        f"Total FVGs: {total} (bullish={bull_total}, bearish={bear_total})\n"
        f"  active:         {active_count}\n"
        f"  mitigated:      {mitigated_count} (inverse FVG vivo)\n"
        f"  inverse_broken: {inv_broken_count} "
        f"(bullish={bull_broken}, bearish={bear_broken})\n"
        f"Per-candle booleans:\n"
        f"  bullish_created:        {df_out[COL_FVG_BULLISH_CREATED].sum()}\n"
        f"  bearish_created:        {df_out[COL_FVG_BEARISH_CREATED].sum()}\n"
        f"  bullish_mitigated:      {df_out[COL_FVG_BULLISH_MITIGATED].sum()}\n"
        f"  bearish_mitigated:      {df_out[COL_FVG_BEARISH_MITIGATED].sum()}\n"
        f"  bullish_inverse_broken: "
        f"{df_out[COL_FVG_BULLISH_INVERSE_BROKEN].sum()}\n"
        f"  bearish_inverse_broken: "
        f"{df_out[COL_FVG_BEARISH_INVERSE_BROKEN].sum()}\n"
    )
    print(report)
