"""Smoke test da Wave 8.2: EQH/EQL canônico (Pine LuxAlgo SMC Concepts).

OBJETIVO
    Provar que `smc_engine.pivots.detect_eqh_eql` implementa a fórmula
    canônica do Pine LuxAlgo `SMC Concepts` (gratuito), conforme briefing
    Wave 8.2 §3.1. Substitui o smoke test da Wave 8.1 (que validava a
    fórmula errada do indicador `ICT Concepts`).

    Cenários cobertos (briefing §4.5):

      1. 2 pivots highs consecutivos dentro de `0.1 × atr200` → 1 EQH
      2. 2 pivots highs consecutivos fora do threshold → 0 EQH
      3. 3 pivots onde só os 2 últimos são próximos → 1 EQH no 3o
      4. EQL espelho
      5. ATR indefinido (período inicial) → sem alert
      6. Integração: analyze() roda detect_eqh_eql no pipeline

FONTE DE DADOS
    Sintética: DataFrames construídos à mão com pivots em posições
    controladas. ATR fornecida via parâmetro explícito quando possível
    para isolar comportamento do threshold canônico.

LIMITAÇÕES CONHECIDAS
    Não valida contra dataset real do Pine — ratificação visual contra
    o golden 720 candles fica em PR separado (Marcelo) consumindo
    `tests/golden/wave8_2_eqheql_events.csv`.

NÃO FAZER
    Não testar o legado `equal_*_alert` produzido por `detect_pivots`
    (Wave 8.2 sobrescreve via detect_eqh_eql). Testes do legado em
    test_smoke_wave3.py validam apenas que continua emitindo
    placeholder all-False.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from smc_engine import analyze
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
    threshold: float = 0.1,
) -> pd.DataFrame:
    """Atalho: roda detect_pivots + detect_eqh_eql encadeados.

    O detector consome equal_*_level (length=3 default), não
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
        threshold=threshold,
    )


# ============================================================
# Cenário 1 — EQH detectado (2 pivots consecutivos dentro do threshold)
# ============================================================

def test_eqh_detected_when_two_consecutive_swings_within_threshold() -> None:
    """2 equal-length highs em 100.00 e 100.05 com ATR=2 e
    threshold=0.1 → tolerância = 0.2. Diferença 0.05 < 0.2 → EQH.

    Pivots reais em 10 e 25; confirmações em +3 (13, 28). O 2o confirma
    em X=28 — único candle com alert.
    """
    n = 40
    df = _make_base_df(n)
    equal_length = 3

    _plant_swing_low(df, 5, 30.0)  # transição inicial 0 -> BULLISH
    _plant_swing_high(df, 10, 100.00)
    _plant_swing_low(df, 18, 30.0)
    _plant_swing_high(df, 25, 100.05)

    atr = pd.Series(np.full(n, 2.0), index=df.index)
    out = _run_pivots_then_eqh(
        df, equal_length=equal_length, atr=atr, threshold=0.1,
    )

    # 2o equal-length high confirma em X=25+3=28 — espera-se 1 alert.
    assert bool(out['equal_high_alert'].iloc[28]), (
        'EQH deveria disparar em X=28 (2o equal high dentro do threshold). '
        f'Diferença: 0.05, tolerância: {0.1 * 2.0}'
    )
    # Exatamente 1 alert em toda a série.
    assert int(out['equal_high_alert'].sum()) == 1
    # Midpoint = (100.00 + 100.05) / 2 = 100.025
    midpoint = out['equal_high_level_midpoint'].iloc[28]
    assert abs(midpoint - 100.025) < 1e-9
    # pivot_indices: bar_indices REAIS dos 2 pivots = [10, 25]
    indices = out['equal_high_pivot_indices'].iloc[28]
    assert list(indices) == [10, 25]


# ============================================================
# Cenário 2 — EQH NÃO detectado (2 pivots fora do threshold)
# ============================================================

def test_eqh_not_detected_when_consecutive_swings_outside_threshold() -> None:
    """2 swing highs em 100 e 102 com ATR=2 e threshold=0.1 → tolerância
    = 0.2. Diferença 2.0 > 0.2 → sem alert.
    """
    n = 40
    df = _make_base_df(n)
    _plant_swing_low(df, 5, 30.0)
    _plant_swing_high(df, 10, 100.0)
    _plant_swing_low(df, 18, 30.0)
    _plant_swing_high(df, 25, 102.0)

    atr = pd.Series(np.full(n, 2.0), index=df.index)
    out = _run_pivots_then_eqh(
        df, equal_length=3, atr=atr, threshold=0.1,
    )

    assert int(out['equal_high_alert'].sum()) == 0, (
        f'EQH não deveria disparar (diferença 2.0 > tolerância 0.2). '
        f'Disparos: {int(out["equal_high_alert"].sum())}'
    )


# ============================================================
# Cenário 3 — 3 pivots, só os 2 últimos próximos → 1 EQH no 3o
# ============================================================

def test_eqh_detected_only_on_last_pair_when_first_pivot_is_far() -> None:
    """3 swing highs: 90.0 (longe), 100.0, 100.05.
    - Comparação no 2o pivot (em X=10+3=13... mas o 2o é 100.0): 90 vs 100,
      diferença 10 > 0.2 → sem alert.
    - Comparação no 3o pivot (em X=40+3=43): currentLevel=100.0 vs 100.05,
      diferença 0.05 < 0.2 → ALERT.
    Total: 1 EQH no candle de confirmação do 3o pivot.
    """
    n = 60
    df = _make_base_df(n)
    _plant_swing_low(df, 5, 30.0)
    _plant_swing_high(df, 10, 90.0)
    _plant_swing_low(df, 18, 30.0)
    _plant_swing_high(df, 25, 100.0)
    _plant_swing_low(df, 32, 30.0)
    _plant_swing_high(df, 40, 100.05)

    atr = pd.Series(np.full(n, 2.0), index=df.index)
    out = _run_pivots_then_eqh(
        df, equal_length=3, atr=atr, threshold=0.1,
    )

    # Apenas 1 alert, no X=43 (confirmação do 3o pivot).
    assert int(out['equal_high_alert'].sum()) == 1
    assert bool(out['equal_high_alert'].iloc[43])

    # Midpoint deve ser média dos 2 últimos pivots: (100.0 + 100.05)/2
    midpoint = out['equal_high_level_midpoint'].iloc[43]
    assert abs(midpoint - 100.025) < 1e-9
    # pivot_indices = [25, 40] (o 10 não entra; compara só com o anterior).
    indices = out['equal_high_pivot_indices'].iloc[43]
    assert list(indices) == [25, 40]


# ============================================================
# Cenário 4 — EQL espelho
# ============================================================

def test_eql_detected_when_two_consecutive_lows_within_threshold() -> None:
    """Espelho do cenário 1 para equal-length lows."""
    n = 40
    df = _make_base_df(n, base_high=50.0, base_low=49.0)

    # Sequência peak → trough → peak → trough.
    _plant_swing_high(df, 5, 80.0)
    _plant_swing_low(df, 10, 30.00)
    _plant_swing_high(df, 18, 80.0)
    _plant_swing_low(df, 25, 30.05)

    atr = pd.Series(np.full(n, 2.0), index=df.index)
    out = _run_pivots_then_eqh(
        df, equal_length=3, atr=atr, threshold=0.1,
    )

    # 2o equal_low confirma em X=25+3=28.
    assert bool(out['equal_low_alert'].iloc[28]), (
        'EQL deveria disparar em X=28 (2o equal-length low). '
        f'midpoint={out["equal_low_level_midpoint"].iloc[28]}'
    )
    assert int(out['equal_low_alert'].sum()) == 1
    midpoint = out['equal_low_level_midpoint'].iloc[28]
    assert abs(midpoint - 30.025) < 1e-9
    indices = out['equal_low_pivot_indices'].iloc[28]
    assert list(indices) == [10, 25]


# ============================================================
# Cenário 5 — ATR indefinido (período inicial) → sem alert, sem crash
# ============================================================

def test_no_alert_emitted_when_atr_undefined() -> None:
    """Período inicial onde ATR(200) ainda não estabilizou → não emitir
    eventos. Aqui forçamos ATR=NaN para todos os candles via passagem
    explícita.
    """
    n = 40
    df = _make_base_df(n)
    _plant_swing_low(df, 5, 30.0)
    _plant_swing_high(df, 10, 100.0)
    _plant_swing_low(df, 18, 30.0)
    _plant_swing_high(df, 25, 100.0)

    atr_nan = pd.Series(np.nan, index=df.index, dtype='float64')
    out = _run_pivots_then_eqh(
        df, equal_length=3, atr=atr_nan, threshold=0.1,
    )

    assert int(out['equal_high_alert'].sum()) == 0
    assert int(out['equal_low_alert'].sum()) == 0


# ============================================================
# Integração: analyze() chama detect_eqh_eql no pipeline
# ============================================================

def test_analyze_pipeline_includes_eqh_eql_detection(synthetic_df: pd.DataFrame) -> None:
    """analyze() roda detect_eqh_eql após detect_pivots; as colunas
    canônicas de metadados aparecem no df do AnalyzeResult.
    """
    result = analyze(synthetic_df)
    expected_cols = {
        'equal_high_alert',
        'equal_low_alert',
        'equal_high_level_midpoint',
        'equal_high_pivot_indices',
        'equal_low_level_midpoint',
        'equal_low_pivot_indices',
    }
    missing = expected_cols - set(result.df.columns)
    assert not missing, f'Colunas EQH/EQL ausentes no df do analyze(): {missing}'
    assert 'detect_eqh_eql' in result.meta['modules_run']


def test_detect_eqh_eql_requires_equal_columns() -> None:
    """Chamar detect_eqh_eql antes de detect_pivots → ValueError
    (requer equal_high_level/equal_low_level)."""
    import pytest

    df = _make_base_df(20)
    with pytest.raises(ValueError, match='equal_high_level'):
        detect_eqh_eql(df)


def test_eqh_strict_less_than_threshold() -> None:
    """Comparação é estrita `<` (Pine usa `<`, não `<=`).

    Construímos 2 pivots cuja diferença é EXATAMENTE igual ao threshold:
    threshold=0.1, ATR=2.0 → tolerância 0.2; diferença = 0.2 → NÃO
    dispara (Pine `< threshold * atr`, comparação estrita).
    """
    n = 40
    df = _make_base_df(n)
    _plant_swing_low(df, 5, 30.0)
    _plant_swing_high(df, 10, 100.0)
    _plant_swing_low(df, 18, 30.0)
    _plant_swing_high(df, 25, 100.2)  # diferença = 0.2 == tolerância

    atr = pd.Series(np.full(n, 2.0), index=df.index)
    out = _run_pivots_then_eqh(
        df, equal_length=3, atr=atr, threshold=0.1,
    )

    assert int(out['equal_high_alert'].sum()) == 0, (
        'Pine usa comparação estrita `<`; diferença == threshold não dispara.'
    )
