"""Fixtures compartilhadas entre os testes do smc_freqtrade.

OBJETIVO
    Centralizar geração de dados sintéticos reutilizáveis em
    múltiplos testes (smoke + integração).

FONTE DE DADOS
    OHLC determinístico com RandomState(42), 5 fases que produzem
    pivots swing/internal, BOS/CHoCH internos, OBs e FVGs.

LIMITAÇÕES CONHECIDAS
    450 candles é suficiente para todos os 6 detectores rodarem
    com defaults da SMCConfig (max(50, 200) + 3 = 203 mínimo).

    Conteúdo OHLC é verbatim da fixture original de
    test_smoke_wave5.py. Adicionou-se a coluna `date` (epoch ms,
    pd.date_range('2026-01-01', freq='4h')) para satisfazer o
    requisito de `analyze()` (Onda 9, REQUIRED_COLUMNS inclui
    'date') sem alterar o comportamento dos testes wave5 (que
    ignoram colunas extras).

NÃO FAZER
    Não usar para validação contra LuxAlgo TradingView — dados
    sintéticos não correspondem a comportamento de mercado real.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def synthetic_df() -> pd.DataFrame:
    """DataFrame OHLC sintético determinístico para smoke/integration tests.

    Reproduz a fixture original de test_smoke_wave5.py com 450
    candles em 5 fases (tendência alta → reversão → consolidação →
    tendência baixa → recuperação), gerada com np.random.RandomState(42).

    Adicionalmente expõe coluna `date` (epoch ms) para compatibilidade
    com detectores das Ondas 6-7 e com `analyze()` da Onda 9.
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

    dates = (
        pd.date_range('2026-01-01', periods=n, freq='4h')
        .astype('int64') // 10**6
    )

    return pd.DataFrame({
        'date': dates,
        'open': opens,
        'high': highs,
        'low': lows,
        'close': closes,
    })
