"""Smoke test da Wave 8.1: EQH/EQL canônico (Pine LuxAlgo ICT Concepts).

OBJETIVO
    Provar que `smc_engine.pivots.detect_eqh_eql` implementa a fórmula
    canônica do Pine LuxAlgo `ICT Concepts` (free), conforme briefing
    Wave 8.1 §7. Cobre os 6 cenários sintéticos do briefing:

      1. EQH bullish detectado (3 pivots highs próximos)
      2. EQH NÃO detectado (fora da banda)
      3. EQH NÃO detectado (apenas 2 pivots)
      4. EQL espelho (3 pivots lows próximos)
      5. Lookback finito (eq_lookback_pivots)
      6. ATR indefinido (período inicial)

FONTE DE DADOS
    Sintética: DataFrames construídos à mão com pivots em posições
    controladas. ATR fornecida via parâmetro explícito quando possível
    para isolar comportamento da banda dinâmica.

LIMITAÇÕES CONHECIDAS
    Não valida contra dataset real do Pine — ratificação visual contra
    o golden 720 candles fica em PR separado (Marcelo) consumindo
    `tests/golden/wave8_1_eqheql_events.csv`.

NÃO FAZER
    Não testar o legado `equal_*_alert` produzido por `detect_pivots`
    (Wave 8.1 sobrescreve via detect_eqh_eql). Testes do legado em
    test_smoke_wave3.py validam apenas que continua emitindo
    placeholder all-False.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from smc_engine import SMCConfig, analyze
from smc_engine.pivots import detect_eqh_eql, detect_pivots


# ============================================================
# Helpers
# ============================================================

def _make_base_df(n: int, base_high: float = 50.0, base_low: float = 49.0) -> pd.DataFrame:
    """Base flat para overlay de pivots."""
    return pd.DataFrame({
        'open': np.full(n, (base_high + base_low) / 2.0),
        'high': np.full(n, base_high, dtype=float),
        'low': np.full(n, base_low, dtype=float),
        'close': np.full(n, (base_high + base_low) / 2.0, dtype=float),
        'date': (
            pd.date_range('2026-01-01', periods=n, freq='4h')
            .astype('int64') // 10**6
        ),
    })


def _plant_swing_high(df: pd.DataFrame, idx: int, level: float) -> None:
    """Eleva um candle isolado para gerar um swing high.

    Mantém o low padrão (49.0) — pivot é detectado apenas em high.
    """
    df.loc[idx, 'high'] = level
    df.loc[idx, 'open'] = level - 1.0
    df.loc[idx, 'close'] = level - 1.0


def _plant_swing_low(df: pd.DataFrame, idx: int, level: float) -> None:
    """Rebaixa um candle isolado para gerar um swing low."""
    df.loc[idx, 'low'] = level
    df.loc[idx, 'open'] = level + 1.0
    df.loc[idx, 'close'] = level + 1.0


def _run_pivots_then_eqh(
    df: pd.DataFrame,
    *,
    swings_length: int = 50,
    equal_length: int = 3,
    atr: pd.Series | None = None,
    eq_atr_length: int = 10,
    eq_margin: float = 4.0,
    eq_lookback_pivots: int = 50,
    eq_min_pivots: int = 3,
) -> pd.DataFrame:
    """Atalho: roda detect_pivots + detect_eqh_eql encadeados.

    O detector novo consome equal_*_level (length=3 default), não
    swing_*_level (length=50). Cenários sintéticos abaixo dimensionam
    confirmações a partir de equal_length.
    """
    with_pivots = detect_pivots(
        df,
        swings_length=swings_length,
        equal_length=equal_length,
        atr=atr,
    )
    return detect_eqh_eql(
        with_pivots,
        atr=atr,
        eq_atr_length=eq_atr_length,
        eq_margin=eq_margin,
        eq_lookback_pivots=eq_lookback_pivots,
        eq_min_pivots=eq_min_pivots,
    )


# ============================================================
# Cenário 1 — EQH bullish detectado (3 pivots próximos)
# ============================================================

def test_eqh_detected_when_three_swings_within_band() -> None:
    """3 equal-length highs em 100.00, 100.05, 100.10 com ATR=2,
    margin=4: banda = 2 / (10/4) = 0.8. Todos dentro de
    [-0.8, +0.8] do centro.

    Com equal_length=3 (default LuxAlgo SMC), cada peak em bar B
    confirma equal_high_level em bar B+3.

    Expectativa: 1 evento EQH no candle de confirmação do 3o pivot
    (bar 43).
    """
    n = 60
    df = _make_base_df(n)
    equal_length = 3

    # Pivots reais nos índices 10, 25, 40; confirmações em +3 (13, 28, 43).
    _plant_swing_low(df, 5, 30.0)  # Necessário para 1a transição BULLISH_LEG
    _plant_swing_high(df, 10, 100.00)
    _plant_swing_low(df, 18, 30.0)
    _plant_swing_high(df, 25, 100.05)
    _plant_swing_low(df, 32, 30.0)
    _plant_swing_high(df, 40, 100.10)

    atr = pd.Series(np.full(n, 2.0), index=df.index)
    out = _run_pivots_then_eqh(
        df, equal_length=equal_length, atr=atr,
        eq_margin=4.0, eq_min_pivots=3,
    )

    # Confirmação 3a equal-length high em X=40+3=43 — espera-se 1 alert.
    assert bool(out['equal_high_alert'].iloc[43]), (
        f'EQH deveria disparar em X=43 (3o equal high dentro da banda). '
        f'Conta pivot_count={out["equal_high_pivot_count"].iloc[43]}'
    )
    # Antes do 3o pivot, count nunca atinge 3.
    assert int(out['equal_high_alert'].iloc[:43].sum()) == 0, (
        'Não deveria haver EQH antes da confirmação do 3o pivot'
    )
    # Metadados consistentes.
    assert int(out['equal_high_pivot_count'].iloc[43]) == 3
    midpoint = out['equal_high_level_midpoint'].iloc[43]
    # Midpoint = (100.10 + 100.00) / 2 = 100.05.
    assert abs(midpoint - 100.05) < 1e-9
    # Banda = 0.8 → band_high = 100.05 + 0.8 = 100.85, band_low = 99.25.
    assert abs(out['equal_high_band_high'].iloc[43] - 100.85) < 1e-9
    assert abs(out['equal_high_band_low'].iloc[43] - 99.25) < 1e-9
    # pivot_indices: bar_indices REAIS dos pivots (10, 25, 40).
    indices = out['equal_high_pivot_indices'].iloc[43]
    assert set(indices) == {10, 25, 40}


# ============================================================
# Cenário 2 — EQH NÃO detectado (pivots fora da banda)
# ============================================================

def test_eqh_not_detected_when_swings_outside_band() -> None:
    """3 swing highs em 100, 102, 104 com ATR=2, margin=4 (banda=0.8).
    Diferenças (2 e 2) excedem a banda.

    Pine: `break` quando prev_level > ph + band — o swing em 102
    (acima de 100+0.8) interrompe o look-back ao chegar no swing
    em 100. Mas para o swing em 104, todo prev fica acima da banda.
    Expectativa: 0 alerts EQH.
    """
    n = 60
    df = _make_base_df(n)
    _plant_swing_low(df, 5, 30.0)
    _plant_swing_high(df, 10, 100.0)
    _plant_swing_low(df, 18, 30.0)
    _plant_swing_high(df, 25, 102.0)
    _plant_swing_low(df, 32, 30.0)
    _plant_swing_high(df, 40, 104.0)

    atr = pd.Series(np.full(n, 2.0), index=df.index)
    out = _run_pivots_then_eqh(
        df, equal_length=3, atr=atr,
        eq_margin=4.0, eq_min_pivots=3,
    )

    assert int(out['equal_high_alert'].sum()) == 0, (
        f'EQH não deveria disparar (pivots fora da banda). '
        f'Disparos: {int(out["equal_high_alert"].sum())}'
    )


# ============================================================
# Cenário 3 — Insuficiência: apenas 2 pivots
# ============================================================

def test_eqh_not_detected_when_only_two_swings() -> None:
    """2 swing highs no mesmo nível: precisa de eq_min_pivots=3 para
    disparar. Sem 3o pivot, count=2 < 3 — nenhum evento."""
    n = 40
    df = _make_base_df(n)
    _plant_swing_low(df, 5, 30.0)
    _plant_swing_high(df, 10, 100.0)
    _plant_swing_low(df, 18, 30.0)
    _plant_swing_high(df, 25, 100.0)

    atr = pd.Series(np.full(n, 2.0), index=df.index)
    out = _run_pivots_then_eqh(
        df, equal_length=3, atr=atr,
        eq_margin=4.0, eq_min_pivots=3,
    )

    assert int(out['equal_high_alert'].sum()) == 0, (
        'EQH não deveria disparar com apenas 2 pivots'
    )


# ============================================================
# Cenário 4 — EQL espelho (3 pivots lows próximos)
# ============================================================

def test_eql_detected_when_three_lows_within_band() -> None:
    """Espelho do cenário 1 para equal-length lows (equal_length=3)."""
    n = 60
    df = _make_base_df(n, base_high=50.0, base_low=49.0)

    # Sequência peak → trough → peak → trough → peak → trough.
    _plant_swing_high(df, 5, 80.0)
    _plant_swing_low(df, 10, 30.00)
    _plant_swing_high(df, 18, 80.0)
    _plant_swing_low(df, 25, 30.05)
    _plant_swing_high(df, 32, 80.0)
    _plant_swing_low(df, 40, 30.10)

    atr = pd.Series(np.full(n, 2.0), index=df.index)
    out = _run_pivots_then_eqh(
        df, equal_length=3, atr=atr,
        eq_margin=4.0, eq_min_pivots=3,
    )

    # 3o equal_low confirma em X=40+3=43.
    assert bool(out['equal_low_alert'].iloc[43]), (
        f'EQL deveria disparar em X=43 (3o equal-length low). '
        f'count={out["equal_low_pivot_count"].iloc[43]}'
    )
    assert int(out['equal_low_pivot_count'].iloc[43]) == 3
    midpoint = out['equal_low_level_midpoint'].iloc[43]
    assert abs(midpoint - 30.05) < 1e-9


# ============================================================
# Cenário 5 — Lookback finito (eq_lookback_pivots)
# ============================================================

def test_eqh_respects_lookback_finite_pivot_count() -> None:
    """Com eq_lookback_pivots=3, ao confirmar um 4o equal-length high
    dentro da banda, o count se limita ao look-back (3 = atual + 2
    prévios).

    Plantamos 4 equal highs próximos: 100.00, 100.02, 100.04, 100.06.
    Confirmações em +3 (13, 28, 43, 58). No X=58, com lookback=3, o
    pivot em 100.00 fica de fora — count = 3 (100.02, 100.04, 100.06),
    o que ainda dispara EQH.

    Mas pivot_count deve refletir 3, não 4.
    """
    n = 80
    df = _make_base_df(n)
    _plant_swing_low(df, 5, 30.0)
    _plant_swing_high(df, 10, 100.00)
    _plant_swing_low(df, 18, 30.0)
    _plant_swing_high(df, 25, 100.02)
    _plant_swing_low(df, 32, 30.0)
    _plant_swing_high(df, 40, 100.04)
    _plant_swing_low(df, 47, 30.0)
    _plant_swing_high(df, 55, 100.06)

    atr = pd.Series(np.full(n, 2.0), index=df.index)
    out = _run_pivots_then_eqh(
        df, equal_length=3, atr=atr,
        eq_margin=4.0, eq_lookback_pivots=3, eq_min_pivots=3,
    )

    # No candle de confirmação do 4o pivot (X=58), pivot_count <= 3.
    count_at_58 = out['equal_high_pivot_count'].iloc[58]
    assert int(count_at_58) == 3, (
        f'pivot_count em X=58 deveria estar capado em 3 (lookback=3 '
        f'inclui o atual). Observado: {count_at_58}'
    )


# ============================================================
# Cenário 6 — ATR indefinido (período inicial)
# ============================================================

def test_no_eqh_emitted_when_atr_undefined() -> None:
    """Período inicial onde ATR ainda não estabilizou → não emitir
    eventos. Aqui forçamos ATR=NaN para todos os candles via passagem
    explícita.
    """
    n = 40
    df = _make_base_df(n)
    _plant_swing_low(df, 5, 30.0)
    _plant_swing_high(df, 10, 100.0)
    _plant_swing_low(df, 18, 30.0)
    _plant_swing_high(df, 25, 100.0)
    _plant_swing_low(df, 32, 30.0)

    # Forçamos ATR=NaN em toda a série.
    atr_nan = pd.Series(np.nan, index=df.index, dtype='float64')
    out = _run_pivots_then_eqh(
        df, equal_length=3, atr=atr_nan,
        eq_margin=4.0, eq_min_pivots=3,
    )

    assert int(out['equal_high_alert'].sum()) == 0
    assert int(out['equal_low_alert'].sum()) == 0


# ============================================================
# Integração: analyze() chama detect_eqh_eql no pipeline
# ============================================================

def test_analyze_pipeline_includes_eqh_eql_detection(synthetic_df: pd.DataFrame) -> None:
    """analyze() agora roda detect_eqh_eql após detect_pivots; as
    colunas de metadados aparecem no df do AnalyzeResult.
    """
    result = analyze(synthetic_df)
    expected_cols = {
        'equal_high_band_high', 'equal_high_band_low',
        'equal_high_pivot_count', 'equal_high_level_midpoint',
        'equal_high_pivot_indices',
        'equal_low_band_high', 'equal_low_band_low',
        'equal_low_pivot_count', 'equal_low_level_midpoint',
        'equal_low_pivot_indices',
    }
    missing = expected_cols - set(result.df.columns)
    assert not missing, f'Colunas EQH/EQL ausentes no df do analyze(): {missing}'
    assert 'detect_eqh_eql' in result.meta['modules_run']


def test_smcconfig_eqh_params_validated() -> None:
    """SMCConfig valida eq_margin, eq_min_pivots, etc."""
    import pytest

    # eq_margin fora de [2, 7] → ValueError.
    with pytest.raises(ValueError, match='eq_margin'):
        SMCConfig(eq_margin=1.0)
    with pytest.raises(ValueError, match='eq_margin'):
        SMCConfig(eq_margin=8.0)
    # eq_min_pivots < 2 → ValueError.
    with pytest.raises(ValueError, match='eq_min_pivots'):
        SMCConfig(eq_min_pivots=1)
    # eq_lookback_pivots < 1 → ValueError.
    with pytest.raises(ValueError, match='eq_lookback_pivots'):
        SMCConfig(eq_lookback_pivots=0)
    # eq_atr_length < 1 → ValueError.
    with pytest.raises(ValueError, match='eq_atr_length'):
        SMCConfig(eq_atr_length=0)


def test_detect_eqh_eql_requires_equal_columns() -> None:
    """Chamar detect_eqh_eql antes de detect_pivots → ValueError
    (requer equal_high_level/equal_low_level)."""
    import pytest

    df = _make_base_df(20)
    with pytest.raises(ValueError, match='equal_high_level'):
        detect_eqh_eql(df)
