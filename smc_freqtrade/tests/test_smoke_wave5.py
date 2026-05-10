"""
OBJETIVO
    Smoke test da Onda 5 — BOS / CHoCH formal sobre swing e internal
    pivots da Onda 3.

    Cobertura mínima conforme briefing §5:
      1. Sequência swing (BOS bull → CHoCH bear → CHoCH bull → BOS bull)
      2. Sequência internal (primeiro evento de neutro = BOS, não CHoCH)
      3. Mutual exclusion BOS×CHoCH por escopo×direção
      4. Flag `crossed` por segmento (parametrizado pelos 4 quadrantes)
      5. Confluence filter só remove eventos internal; swing inafetado

FONTE DE DADOS
    Fixture sintética determinística (RandomState=42) de 450 candles
    construída por landmarks-de-preço com wiggle gaussiano e wicks
    variáveis. Briefing §5.1 sugere ~300 candles; este teste estendeu
    para 450 a fim de produzir Fase 5 (BOS bullish após CHoCH bullish),
    que requer a formação de um swing_high adicional após o evento de
    Fase 4. Ajuste vale-se da liberdade declarada no briefing
    ("Se a fixture não produzir a sequência exata, ajustar a fixture
    (não os asserts)").

LIMITAÇÕES CONHECIDAS
    Restrição de pivots.py: leg inicial = BEARISH_LEG=0; primeiro pivot
    detectado é sempre swing_low (transição BEARISH→BULLISH). Logo, a
    fixture é desenhada para que o primeiro CLOSE-CROSS seja bullish
    sobre um swing_high já materializado — produzindo BOS bullish a
    partir de bias neutro.

    Não valida output contra dataset real do LuxAlgo Pine — equivalência
    golden é Onda 9.

NÃO FAZER
    Não importar de smc_freqtrade.smc_engine — pacote raiz é `smc_engine`.
    Não ajustar asserts para acomodar fixture quebrada — ajustar a
        fixture, conforme briefing §5.1.
    Não consumir trailing.* aqui — irrelevante para esta onda; é
        chamado apenas para reproduzir o pipeline canônico do briefing
        §5.2 (detect_pivots → compute_trailing_extremes → detect_structure).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from smc_engine import (
    BEARISH,
    BULLISH,
    compute_trailing_extremes,
    detect_pivots,
    detect_structure,
)


@pytest.fixture
def synthetic_df() -> pd.DataFrame:
    """Fixture §5.1 — 450 candles com 5 fases de price action.

    Fase 1 (0-129):     setup — forma swing_low (low[0]=89.5,
                        detectado em X=50) e swing_high (close peak
                        ~candle 80, detectado em X=130).
    Fase 2 (130-153):   close cruza swing_high_level upward → BOS
                        bullish (bias prévio = pd.NA).
    Fase 3 (210-214):   close cruza swing_low_level downward →
                        CHoCH bearish (bias prévio = BULLISH).
    Fase 4 (300-311):   close cruza novo swing_high_level upward →
                        CHoCH bullish (bias prévio = BEARISH).
    Fase 5 (390-413):   close cruza outro novo swing_high_level
                        upward → BOS bullish (bias atual = BULLISH).

    Wiggle gaussiano + wicks variáveis garantem internal pivots
    (length=5) ao longo da série, fornecendo eventos para
    test_smoke_wave5_internal_sequence e
    test_smoke_wave5_confluence_filter.
    """
    n = 450
    rng = np.random.RandomState(42)

    landmarks = [
        (0, 90.0), (5, 100.0), (50, 100.0), (80, 115.0), (110, 100.0),
        (130, 100.0), (170, 130.0), (210, 130.0), (215, 85.0), (245, 85.0),
        (250, 120.0), (270, 100.0), (300, 100.0), (320, 140.0), (340, 150.0),
        (370, 130.0), (390, 130.0), (430, 165.0), (449, 160.0),
    ]
    base = np.zeros(n)
    for (i_a, p_a), (i_b, p_b) in zip(landmarks, landmarks[1:]):
        base[i_a:i_b + 1] = np.linspace(p_a, p_b, i_b - i_a + 1)

    closes = base + rng.normal(0, 1.5, n)
    opens = closes + rng.normal(0, 0.8, n)
    upper_wicks = np.abs(rng.normal(0.5, 0.4, n))
    lower_wicks = np.abs(rng.normal(0.5, 0.4, n))
    highs = np.maximum(opens, closes) + upper_wicks
    lows = np.minimum(opens, closes) - lower_wicks

    return pd.DataFrame({
        'open': opens,
        'high': highs,
        'low': lows,
        'close': closes,
    })


def test_smoke_wave5_swing_sequence(synthetic_df):
    """Sequência swing canônica: BOS bull → CHoCH bear → CHoCH bull → BOS bull.

    Asserts seguem briefing §5.2 verbatim. Posições temporais são lidas
    via out.index.get_loc() para preservar correção sob qualquer tipo de
    índice (RangeIndex hoje, DatetimeIndex futuro).
    """
    df = detect_pivots(synthetic_df, swings_length=50, internal_length=5, equal_length=3)
    df = compute_trailing_extremes(df)
    out = detect_structure(df)

    # Fase 2: primeiro break bullish a partir de neutro = BOS, não CHoCH
    x = out.index[out["bos_swing_bullish"]][0]
    assert not out.loc[x, "choch_swing_bullish"]
    assert out.loc[x, "swing_trend_bias"] == BULLISH

    # Fase 3: break bearish após BULLISH = CHoCH
    y = out.index[out["choch_swing_bearish"]][0]
    assert not out.loc[y, "bos_swing_bearish"]
    assert out.loc[y, "swing_trend_bias"] == BEARISH
    y_pos = out.index.get_loc(y)
    prev_y = out.index[y_pos - 1]
    assert out.loc[prev_y, "swing_trend_bias"] == BULLISH

    # Fase 4: break bullish após BEARISH = CHoCH
    z = out.index[out["choch_swing_bullish"]][0]
    assert out.loc[z, "swing_trend_bias"] == BULLISH
    z_pos = out.index.get_loc(z)
    prev_z = out.index[z_pos - 1]
    assert out.loc[prev_z, "swing_trend_bias"] == BEARISH

    # Fase 5: último break bullish após o CHoCH bullish = BOS
    w = out.index[out["bos_swing_bullish"]][-1]
    assert out.index.get_loc(w) > z_pos
    assert not out.loc[w, "choch_swing_bullish"]


def test_smoke_wave5_internal_sequence(synthetic_df):
    """Paralelo a swing_sequence: cobre os 4 booleans internal e
    internal_trend_bias.

    A fixture §5.1 produz pivots internal (length=5) ao longo dos 450
    candles; eventos internal naturalmente ocorrem entre fases swing.
    """
    df = detect_pivots(synthetic_df, swings_length=50, internal_length=5, equal_length=3)
    df = compute_trailing_extremes(df)
    out = detect_structure(df)

    internal_events = (
        out["bos_internal_bullish"]
        | out["bos_internal_bearish"]
        | out["choch_internal_bullish"]
        | out["choch_internal_bearish"]
    )
    assert internal_events.any()

    # Primeiro evento internal a partir de neutro: bias prévio é pd.NA;
    # primeira detecção colapsa para BOS (Pine: tag = 'CHoCH' if bias == BEARISH else 'BOS').
    first_idx = out.index[internal_events][0]
    first_pos = out.index.get_loc(first_idx)
    if first_pos > 0:
        prev_idx = out.index[first_pos - 1]
        assert pd.isna(out.loc[prev_idx, "internal_trend_bias"])
    assert (
        out.loc[first_idx, "bos_internal_bullish"]
        or out.loc[first_idx, "bos_internal_bearish"]
    )
    assert not (
        out.loc[first_idx, "choch_internal_bullish"]
        or out.loc[first_idx, "choch_internal_bearish"]
    )
    if out.loc[first_idx, "bos_internal_bullish"]:
        assert out.loc[first_idx, "internal_trend_bias"] == BULLISH
    else:
        assert out.loc[first_idx, "internal_trend_bias"] == BEARISH


def test_smoke_wave5_mutual_exclusion(synthetic_df):
    """Invariante §4.4 #1 — em qualquer candle, BOS e CHoCH do mesmo
    escopo×direção são mutuamente exclusivos."""
    df = detect_pivots(synthetic_df, swings_length=50, internal_length=5, equal_length=3)
    df = compute_trailing_extremes(df)
    out = detect_structure(df)

    assert not (out["bos_swing_bullish"] & out["choch_swing_bullish"]).any()
    assert not (out["bos_swing_bearish"] & out["choch_swing_bearish"]).any()
    assert not (out["bos_internal_bullish"] & out["choch_internal_bullish"]).any()
    assert not (out["bos_internal_bearish"] & out["choch_internal_bearish"]).any()


@pytest.mark.parametrize("idx_col,event_cols", [
    ("swing_high_idx", ("bos_swing_bullish", "choch_swing_bullish")),
    ("swing_low_idx", ("bos_swing_bearish", "choch_swing_bearish")),
    ("internal_high_idx", ("bos_internal_bullish", "choch_internal_bullish")),
    ("internal_low_idx", ("bos_internal_bearish", "choch_internal_bearish")),
])
def test_smoke_wave5_crossed_flag_per_segment(synthetic_df, idx_col, event_cols):
    """Invariante §4.4 #3 — mesmo segmento (= mesmo pivot) não dispara
    duas vezes mesmo com close-cross persistente."""
    df = detect_pivots(synthetic_df, swings_length=50, internal_length=5, equal_length=3)
    df = compute_trailing_extremes(df)
    out = detect_structure(df)

    segment_id = out[idx_col].notna().cumsum()
    events = out[event_cols[0]] | out[event_cols[1]]
    counts = events.groupby(segment_id).sum()
    assert (counts <= 1).all()


def test_smoke_wave5_confluence_filter(synthetic_df):
    """internal_filter_confluence=True só remove eventos internal;
    swing inafetado.

    Nota sobre a invariante: o briefing §5.2 prescreve assert per-candle
    `(default[col] >= filtered[col]).all()`. Esse assert não corresponde
    à semântica Pine sob shift de evento dentro do mesmo segmento: se
    bullish_bar=False no primeiro `ta.crossover` de um segmento, o
    crossed flag permanece False e um crossover posterior (após dip e
    re-cross) com bullish_bar=True dispara o evento — em candle DIFERENTE
    do default. Per-candle: filtered=True onde default=False (assert
    falha). Per-coluna agregada (total ou per-segment): filtered <=
    default (Pine-faithful). Deviação registrada no body do PR.
    """
    df = detect_pivots(synthetic_df, swings_length=50, internal_length=5, equal_length=3)
    df = compute_trailing_extremes(df)
    out_default = detect_structure(df, internal_filter_confluence=False)
    out_filtered = detect_structure(df, internal_filter_confluence=True)

    internal_cols = [
        "bos_internal_bullish",
        "bos_internal_bearish",
        "choch_internal_bullish",
        "choch_internal_bearish",
    ]
    swing_cols = [
        "bos_swing_bullish",
        "bos_swing_bearish",
        "choch_swing_bullish",
        "choch_swing_bearish",
    ]

    # Filtro só remove eventos no agregado por coluna (Pine-faithful;
    # ver docstring acima).
    for col in internal_cols:
        assert out_default[col].sum() >= out_filtered[col].sum()

    # Swing inafetado pelo filtro.
    for col in swing_cols:
        assert (out_default[col] == out_filtered[col]).all()

    # Algum evento internal é de fato filtrado — caso contrário o teste
    # seria vacuamente verdadeiro.
    assert (
        out_filtered[internal_cols].sum().sum()
        < out_default[internal_cols].sum().sum()
    )


if __name__ == '__main__':
    import sys
    sys.exit(pytest.main([__file__, '-v']))
