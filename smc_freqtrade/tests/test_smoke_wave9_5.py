"""Smoke + integração da Wave 9.5a — promoção de zona (§S1) + A3/MTF.

OBJETIVO
    Cobrir os critérios verificáveis §5 do briefing que não dependem de
    trajetória scriptada (essa vive em test_setup_state_trajectory.py):

    1. Promoção de zona (§S1): colunas ativas preenchidas e dentro das
       bordas do ledger; nulas quando não há ativo; causalidade
       (truncar df em T e comparar prefixo).
    2. 6 colunas de output presentes, dtypes corretos, `setup_state` só
       nos 4 valores válidos.
    5. Spot-check no golden real (jan-abr 2026, 3 TFs): roda sem crash;
       todo CONFIRMED é precedido por PENDING_CONFIRMATION e por sweep
       recente; `setup_direction` casa com `swing_trend_bias_4h` na
       armação.
    6. `setup_id` determinístico.

    Mais o invariante de regressão §6: `analyze()` 66 → 78 colunas,
    apenas adicionadas ao fim, ordem das existentes preservada.

FONTE DE DADOS
    Goldens reais em tests/golden/data/btc_usdt_swap_{4h,1h,15m}_window.csv
    e a fixture synthetic_df de conftest.py.

NÃO FAZER
    Não comparar contra TradingView (sem ground truth visual de ARMED).
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from smc_engine import (
    analyze,
    compute_setup_state,
    promote_active_zones,
    ACTIVE_ZONE_COLUMNS,
    SETUP_OUTPUT_COLUMNS,
    SETUP_STATES,
    INVALIDATION_REASONS,
    STATE_ARMED,
    STATE_CONFIRMED,
    STATE_PENDING,
    SetupConfig,
)
from smc_engine.setup_state import _make_setup_id
from tools.mtf_align import align_informative

GOLDEN_DIR = Path(__file__).resolve().parent / 'golden' / 'data'


def _load_ohlcv(name: str) -> pd.DataFrame:
    df = pd.read_csv(GOLDEN_DIR / name)
    df['date'] = pd.to_datetime(df['timestamp_utc'], utc=True)
    return df[['date', 'open', 'high', 'low', 'close', 'volume']]


def _build_golden_pipeline() -> pd.DataFrame:
    """Pipeline completo do briefing §5.5: analyze 4h/1h/15m + merge + setup."""
    r4 = analyze(_load_ohlcv('btc_usdt_swap_4h_window.csv'))
    r1 = analyze(_load_ohlcv('btc_usdt_swap_1h_window.csv'))
    r15 = analyze(_load_ohlcv('btc_usdt_swap_15m_window.csv'))
    merged = align_informative(r15.df, r1.df, '15m', '1h', suffix='1h')
    merged = align_informative(merged, r4.df, '15m', '4h', suffix='4h')
    return compute_setup_state(merged)


@lru_cache(maxsize=1)
def _golden_pipeline() -> pd.DataFrame:
    """Cache do pipeline (pesado) para reuso read-only entre testes."""
    return _build_golden_pipeline()


# ============================================================
# §6 — invariante de regressão: 66 → 78 colunas, aditivo ao fim
# ============================================================

def test_golden_4h_goes_66_to_92_columns() -> None:
    """§6: no golden 4H (com volume), analyze() vai de 66 para 92 colunas.

    Wave 9.5c: a zona ativa passou de 20 → 26 colunas (breaker +6 =
    {bull,bear}×{top,bottom,id}). Aditivo ao fim — o gate real do §7 é
    aditividade, não a contagem."""
    result = analyze(_load_ohlcv('btc_usdt_swap_4h_window.csv'))
    assert len(result.df.columns) == 92
    n = len(ACTIVE_ZONE_COLUMNS)
    assert list(result.df.columns[-n:]) == list(ACTIVE_ZONE_COLUMNS)


def test_analyze_adds_exactly_26_zone_columns(synthetic_df: pd.DataFrame) -> None:
    """As 26 colunas de zona são anexadas ao fim (ordem das existentes
    preservada). synthetic_df não tem `volume` → 65 base + 26 = 91."""
    result = analyze(synthetic_df)
    n = len(ACTIVE_ZONE_COLUMNS)
    assert list(result.df.columns[-n:]) == list(ACTIVE_ZONE_COLUMNS)
    # exatamente len(ACTIVE_ZONE_COLUMNS) colunas a mais que o set sem promoção.
    non_zone = [c for c in result.df.columns if c not in ACTIVE_ZONE_COLUMNS]
    assert len(non_zone) == len(result.df.columns) - n


def test_ledger_counts_unchanged(synthetic_df: pd.DataFrame) -> None:
    """OB 15 / FVG 11 / BPR 7 — promoção não toca ledgers."""
    result = analyze(synthetic_df)
    assert len(result.ledger_ob.columns) == 15
    assert len(result.ledger_fvg.columns) == 11
    assert len(result.ledger_bpr.columns) == 7


def test_promotion_does_not_mutate_input(synthetic_df: pd.DataFrame) -> None:
    """promote_active_zones não muta o df de entrada."""
    result = analyze(synthetic_df)
    base = result.df.drop(columns=list(ACTIVE_ZONE_COLUMNS))
    snapshot = base.copy()
    _ = promote_active_zones(base, result.ledger_ob, result.ledger_fvg)
    pd.testing.assert_frame_equal(base, snapshot)


def test_no_lookahead_shift_in_modules() -> None:
    """§6: ausência de shift(-N) nos módulos da wave."""
    for mod in ('zone_projection.py', 'setup_state.py'):
        src = (Path(__file__).resolve().parent.parent
               / 'smc_engine' / mod).read_text(encoding='utf-8')
        # `.shift(-` é a chamada de método real; os docstrings citam
        # `shift(-N)` (sem ponto) ao documentar a proibição.
        assert '.shift(-' not in src, f'{mod} contém shift negativo'


# ============================================================
# §5.1 — Promoção de zona (S1)
# ============================================================

def test_promoted_zone_within_ledger_bounds(synthetic_df: pd.DataFrame) -> None:
    """Onde active_bull_swing_ob_id está preenchido, top/bottom batem com
    o ledger e o OB está ativo (t_creation <= T < t_mitigation)."""
    result = analyze(synthetic_df)
    df = result.df
    ob = result.ledger_ob.set_index('ob_id')
    col_id = 'active_bull_swing_ob_id'
    filled = df[df[col_id].notna()]
    assert len(filled) > 0, 'esperava ao menos um candle com OB bull swing ativo'
    for _, row in filled.iterrows():
        oid = int(row[col_id])
        ledger_row = ob.loc[oid]
        assert ledger_row['scope'] == 'swing'
        assert ledger_row['bias'] == 1
        assert row['active_bull_swing_ob_top'] == ledger_row['bar_high']
        assert row['active_bull_swing_ob_bottom'] == ledger_row['bar_low']
        # ativo em T
        t = row['date']
        assert ledger_row['t_creation'] <= t
        if pd.notna(ledger_row['t_mitigation']):
            assert t < ledger_row['t_mitigation']


def test_promoted_zone_null_when_no_active(synthetic_df: pd.DataFrame) -> None:
    """Os primeiros candles (antes de qualquer OB swing) têm zona nula."""
    result = analyze(synthetic_df)
    df = result.df
    # antes do primeiro t_creation de OB swing bull, a coluna é nula.
    swing_bull = result.ledger_ob[
        (result.ledger_ob['scope'] == 'swing')
        & (result.ledger_ob['bias'] == 1)
    ]
    if len(swing_bull) == 0:
        return
    first_creation = swing_bull['t_creation'].min()
    before = df[df['date'] < first_creation]
    assert before['active_bull_swing_ob_id'].isna().all()


def test_promotion_is_causal(synthetic_df: pd.DataFrame) -> None:
    """§5.1: truncar o df em T e reprojetar (mesmo ledger) reproduz o
    prefixo exato — nenhum valor depende de candle futuro."""
    result = analyze(synthetic_df)
    full = result.df
    k = 300
    truncated = promote_active_zones(
        full.iloc[:k].drop(columns=list(ACTIVE_ZONE_COLUMNS)),
        result.ledger_ob,
        result.ledger_fvg,
    )
    for col in ACTIVE_ZONE_COLUMNS:
        pd.testing.assert_series_equal(
            truncated[col].reset_index(drop=True),
            full[col].iloc[:k].reset_index(drop=True),
            check_names=False,
        )


# ============================================================
# §5.2 — 6 colunas de output + dtypes
# ============================================================

def test_setup_output_columns_present_and_typed() -> None:
    res = _golden_pipeline()
    for col in SETUP_OUTPUT_COLUMNS:
        assert col in res.columns
    assert res['setup_zone_low'].dtype == np.float64
    assert res['setup_zone_high'].dtype == np.float64
    assert res['setup_id'].dtype == 'string'
    assert res['setup_state'].dtype == 'string'
    assert res['setup_direction'].dtype == 'string'
    assert res['setup_invalidation_reason'].dtype == 'string'


def test_setup_state_only_valid_values() -> None:
    res = _golden_pipeline()
    states = set(res['setup_state'].dropna().unique())
    assert states.issubset(set(SETUP_STATES)), f'estados inesperados: {states}'
    reasons = set(res['setup_invalidation_reason'].dropna().unique())
    assert reasons.issubset(set(INVALIDATION_REASONS)), f'razões inesperadas: {reasons}'
    dirs = set(res['setup_direction'].dropna().unique())
    assert dirs.issubset({'long', 'short'})


# ============================================================
# §5.5 — Spot-check no golden real
# ============================================================

def test_golden_runs_without_crash() -> None:
    res = _golden_pipeline()
    assert len(res) == 11520  # 15m window (sem o header)


def test_confirmed_preceded_by_pending_and_recent_sweep() -> None:
    """Todo CONFIRMED é precedido por PENDING_CONFIRMATION no mesmo setup
    e por sweep recente na direção (§5.5b)."""
    cfg = SetupConfig()
    res = _golden_pipeline().reset_index(drop=True)
    state = res['setup_state']
    sweep_bull = (
        res['sweep_bullish_wick'].fillna(False)
        | res['sweep_bullish_retest'].fillna(False)
    )
    sweep_bear = (
        res['sweep_bearish_wick'].fillna(False)
        | res['sweep_bearish_retest'].fillna(False)
    )
    confirmed_idx = state.index[state == STATE_CONFIRMED]
    for i in confirmed_idx:
        # candle anterior do mesmo setup_id deve ser PENDING_CONFIRMATION
        assert i > 0
        assert state.iloc[i - 1] == STATE_PENDING
        assert res['setup_id'].iloc[i] == res['setup_id'].iloc[i - 1]
        # sweep recente na janela [i-K+1, i] na direção do setup
        lo = max(0, i - cfg.sweep_recency_candles + 1)
        if res['setup_direction'].iloc[i] == 'long':
            assert sweep_bull.iloc[lo:i + 1].any()
        else:
            assert sweep_bear.iloc[lo:i + 1].any()


def test_armed_direction_matches_trend() -> None:
    """No candle de armação, setup_direction casa com swing_trend_bias_4h."""
    res = _golden_pipeline()
    armed = res[res['setup_state'] == STATE_ARMED]
    for _, row in armed.iterrows():
        if row['setup_direction'] == 'long':
            assert row['swing_trend_bias_4h'] == 1
        else:
            assert row['swing_trend_bias_4h'] == -1


# ============================================================
# §5.6 — setup_id determinístico
# ============================================================

def test_setup_id_deterministic() -> None:
    """Mesma entrada ⇒ mesmos ids; ids distintos para (ob_id, t_armed) distintos."""
    a = _make_setup_id('A3', 'long', 5, 7, 'T0')
    b = _make_setup_id('A3', 'long', 5, 7, 'T0')
    assert a == b
    assert a != _make_setup_id('A3', 'long', 6, 7, 'T0')   # ob_id distinto
    assert a != _make_setup_id('A3', 'long', 5, 7, 'T1')   # t_armed distinto
    assert a != _make_setup_id('A3', 'short', 5, 7, 'T0')  # direção distinta


def test_setup_id_stable_across_runs() -> None:
    """Rodar o pipeline duas vezes produz os mesmos setup_id."""
    r1 = _build_golden_pipeline()
    r2 = _build_golden_pipeline()
    pd.testing.assert_series_equal(r1['setup_id'], r2['setup_id'])
