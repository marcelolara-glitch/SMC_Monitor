"""
OBJETIVO
    Smoke test sintético da Onda 8 — Liquidity Sweep. Cobre os 10
    cenários A–J do briefing §9.1, materializando cada caso com
    fixture mínima (volume=0 por princípio anti-falso-positivo das
    ondas anteriores).

FONTE DE DADOS
    Fixtures construídas com OHLC fabricado e colunas Onda 3
    pré-preenchidas diretamente (sem rodar detect_pivots). Justifica:
    isola o detector da geometria dos pivots, reduz superfície de
    teste à lógica de sweep propriamente dita.

LIMITAÇÕES CONHECIDAS
    Cenário J documenta last-write-wins sobre `*_level_idx` quando
    múltiplos pivots disparam o mesmo evento na mesma candle. A
    coluna booleana permanece True (idempotente). Caso degenerado
    raro em dados reais.

NÃO FAZER
    Não importar de `smc_freqtrade.smc_engine` — pacote raiz é
        `smc_engine`.
    Não ajustar asserts para acomodar fixture quebrada — ajustar a
        fixture.
    Não pular nenhum dos 10 cenários — cada um cobre um vértice da
        especificação.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from smc_engine import (
    COL_EQUAL_HIGH_ALERT,
    COL_EQUAL_HIGH_IDX,
    COL_EQUAL_HIGH_LEVEL,
    COL_EQUAL_LOW_ALERT,
    COL_EQUAL_LOW_IDX,
    COL_EQUAL_LOW_LEVEL,
    COL_INTERNAL_HIGH_IDX,
    COL_INTERNAL_HIGH_LEVEL,
    COL_INTERNAL_LOW_IDX,
    COL_INTERNAL_LOW_LEVEL,
    COL_PD_ZONE,
    COL_SWEEP_BEARISH_LEVEL_IDX,
    COL_SWEEP_BEARISH_LEVEL_PRICE,
    COL_SWEEP_BEARISH_MITIGATED,
    COL_SWEEP_BEARISH_PD_ZONE,
    COL_SWEEP_BEARISH_RETEST,
    COL_SWEEP_BEARISH_WICK,
    COL_SWEEP_BULLISH_LEVEL_IDX,
    COL_SWEEP_BULLISH_LEVEL_PRICE,
    COL_SWEEP_BULLISH_MITIGATED,
    COL_SWEEP_BULLISH_RETEST,
    COL_SWEEP_BULLISH_WICK,
    detect_liquidity_sweeps,
)


# ============================================================
# Helpers
# ============================================================

def _empty_df(n: int, base_price: float = 100.0) -> pd.DataFrame:
    """DataFrame baseline com OHLC neutro (todos os candles fechando
    no `base_price`), volume=0, e colunas Onda 3 zeradas (NaN para
    *_level/idx, False para *_alert). Fixture mínima — cada cenário
    sobrescreve apenas as células relevantes.

    Inclui colunas das duas sources default (`equal` e `internal`).
    Cenários que precisam de mais colunas (ex.: `pd_zone`) adicionam
    explicitamente.
    """
    df = pd.DataFrame({
        'open': np.full(n, base_price),
        'high': np.full(n, base_price + 0.1),
        'low': np.full(n, base_price - 0.1),
        'close': np.full(n, base_price),
        'volume': np.zeros(n),
    })
    for col in (
        COL_EQUAL_HIGH_LEVEL, COL_EQUAL_HIGH_IDX,
        COL_EQUAL_LOW_LEVEL, COL_EQUAL_LOW_IDX,
        COL_INTERNAL_HIGH_LEVEL, COL_INTERNAL_HIGH_IDX,
        COL_INTERNAL_LOW_LEVEL, COL_INTERNAL_LOW_IDX,
    ):
        df[col] = np.nan
    df[COL_EQUAL_HIGH_ALERT] = False
    df[COL_EQUAL_LOW_ALERT] = False
    return df


def _set_candle(
    df: pd.DataFrame, t: int,
    high: float, low: float, close: float,
) -> None:
    df.at[t, 'high'] = high
    df.at[t, 'low'] = low
    df.at[t, 'close'] = close


# ============================================================
# Cenário A — Wick sweep bearish (one-shot)
# ============================================================

def test_smoke_wave8_cenario_a_wick_bearish_one_shot():
    """Pivot equal_high em t=10 (level=100, idx=10).
    t=15: high=101.5, close=99.5 → emite sweep_bearish_wick.
    t=16: mesmo padrão → NÃO re-emite (flag wic one-shot)."""
    df = _empty_df(20)
    df.at[10, COL_EQUAL_HIGH_LEVEL] = 100.0
    df.at[10, COL_EQUAL_HIGH_IDX] = 10

    _set_candle(df, 15, high=101.5, low=99.0, close=99.5)
    _set_candle(df, 16, high=101.5, low=99.0, close=99.5)

    out = detect_liquidity_sweeps(df)

    assert bool(out[COL_SWEEP_BEARISH_WICK].iloc[15])
    assert out[COL_SWEEP_BEARISH_LEVEL_PRICE].iloc[15] == 100.0
    assert int(out[COL_SWEEP_BEARISH_LEVEL_IDX].iloc[15]) == 10
    # One-shot: t=16 não dispara segundo wick sobre o mesmo pivot.
    assert not bool(out[COL_SWEEP_BEARISH_WICK].iloc[16])


# ============================================================
# Cenário B — Wick sweep bullish
# ============================================================

def test_smoke_wave8_cenario_b_wick_bullish():
    """Pivot equal_low em t=10 (level=100, idx=10).
    t=15: low=98.5, close=100.5 → emite sweep_bullish_wick."""
    df = _empty_df(20)
    df.at[10, COL_EQUAL_LOW_LEVEL] = 100.0
    df.at[10, COL_EQUAL_LOW_IDX] = 10

    _set_candle(df, 15, high=100.6, low=98.5, close=100.5)

    out = detect_liquidity_sweeps(df)

    assert bool(out[COL_SWEEP_BULLISH_WICK].iloc[15])
    assert out[COL_SWEEP_BULLISH_LEVEL_PRICE].iloc[15] == 100.0
    assert int(out[COL_SWEEP_BULLISH_LEVEL_IDX].iloc[15]) == 10


# ============================================================
# Cenário C — Outbreak & retest bullish
# ============================================================

def test_smoke_wave8_cenario_c_outbreak_retest_bullish():
    """Pivot equal_high em t=10 (level=100, idx=10).
    t=15: close=101.0 (close rompe → brk=True, sem wick fire).
    t=20: low=99.0, close=100.5 → emite sweep_bullish_retest."""
    df = _empty_df(25)
    df.at[10, COL_EQUAL_HIGH_LEVEL] = 100.0
    df.at[10, COL_EQUAL_HIGH_IDX] = 10

    # t=15: close acima do level → break (sem wick — close não voltou).
    _set_candle(df, 15, high=101.2, low=100.5, close=101.0)
    # t=16-19: filler acima do level para manter post-break.
    for t in range(16, 20):
        _set_candle(df, t, high=101.5, low=100.8, close=101.2)
    # t=20: mecha desce abaixo, close fecha de volta acima → retest.
    _set_candle(df, 20, high=101.0, low=99.0, close=100.5)

    out = detect_liquidity_sweeps(df)

    # Não emite wick em t=15 (close > price, não c < price).
    assert not bool(out[COL_SWEEP_BEARISH_WICK].iloc[15])
    assert bool(out[COL_SWEEP_BULLISH_RETEST].iloc[20])
    assert out[COL_SWEEP_BULLISH_LEVEL_PRICE].iloc[20] == 100.0
    assert int(out[COL_SWEEP_BULLISH_LEVEL_IDX].iloc[20]) == 10


# ============================================================
# Cenário D — Outbreak & retest bearish
# ============================================================

def test_smoke_wave8_cenario_d_outbreak_retest_bearish():
    """Pivot equal_low em t=10 (level=100, idx=10).
    t=15: close=99.0 (close rompe pra baixo → brk=True).
    t=20: high=101.0, close=99.5 → emite sweep_bearish_retest."""
    df = _empty_df(25)
    df.at[10, COL_EQUAL_LOW_LEVEL] = 100.0
    df.at[10, COL_EQUAL_LOW_IDX] = 10

    _set_candle(df, 15, high=99.5, low=98.5, close=99.0)
    for t in range(16, 20):
        _set_candle(df, t, high=99.2, low=98.5, close=98.8)
    _set_candle(df, 20, high=101.0, low=99.0, close=99.5)

    out = detect_liquidity_sweeps(df)

    assert not bool(out[COL_SWEEP_BULLISH_WICK].iloc[15])
    assert bool(out[COL_SWEEP_BEARISH_RETEST].iloc[20])
    assert out[COL_SWEEP_BEARISH_LEVEL_PRICE].iloc[20] == 100.0
    assert int(out[COL_SWEEP_BEARISH_LEVEL_IDX].iloc[20]) == 10


# ============================================================
# Cenário E — Mitigação de sweep area
# ============================================================

def test_smoke_wave8_cenario_e_sweep_area_mitigation():
    """Cenário A + t=30 com close=101.0 (close acima do level).
    Assertion: sweep_bearish_mitigated[30] == True.

    Confirma que a área da varredura permanece viva entre o sweep
    e a mitigação (sob a janela default de extensão=300)."""
    df = _empty_df(35)
    df.at[10, COL_EQUAL_HIGH_LEVEL] = 100.0
    df.at[10, COL_EQUAL_HIGH_IDX] = 10

    _set_candle(df, 15, high=101.5, low=99.0, close=99.5)
    # t=16-29: candles neutros abaixo do level, pivot stays in pre-break.
    for t in range(16, 30):
        _set_candle(df, t, high=99.8, low=99.0, close=99.5)
    # t=30: close acima do level → mitiga a área.
    _set_candle(df, 30, high=101.2, low=99.5, close=101.0)

    out = detect_liquidity_sweeps(df)

    assert bool(out[COL_SWEEP_BEARISH_WICK].iloc[15])
    assert bool(out[COL_SWEEP_BEARISH_MITIGATED].iloc[30])


# ============================================================
# Cenário F — Expiração por sweep_max_extension_bars
# ============================================================

def test_smoke_wave8_cenario_f_extension_expired():
    """Cenário A com `sweep_max_extension_bars=5`. Sweep em t=15,
    área expira em t=20 (15+5). Em t=25, close=101 NÃO mitiga
    (área já expirou).

    `sweep_max_pivot_age_bars` precisa ser >= 5 — usa 50 (>>
    extension) para não interferir."""
    df = _empty_df(30)
    df.at[10, COL_EQUAL_HIGH_LEVEL] = 100.0
    df.at[10, COL_EQUAL_HIGH_IDX] = 10

    _set_candle(df, 15, high=101.5, low=99.0, close=99.5)
    # t=16-24: filler neutro abaixo do level.
    for t in range(16, 25):
        _set_candle(df, t, high=99.8, low=99.0, close=99.5)
    _set_candle(df, 25, high=101.2, low=99.5, close=101.0)

    out = detect_liquidity_sweeps(
        df,
        sweep_max_extension_bars=5,
        sweep_max_pivot_age_bars=50,
    )

    assert bool(out[COL_SWEEP_BEARISH_WICK].iloc[15])
    # Mitigação NÃO ocorre — área expirou em t=20 < 25.
    assert not bool(out[COL_SWEEP_BEARISH_MITIGATED].iloc[25])


# ============================================================
# Cenário G — Cleanup por idade
# ============================================================

def test_smoke_wave8_cenario_g_pivot_age_cleanup():
    """Pivot em t=10, level=100. `sweep_max_pivot_age_bars=20`.
    Em t=31, t - confirmed_at = 21 > 20 → pivot é purgado.
    Em t=50, o pivot já não está no pool → wick NÃO dispara
    (mesmo com o padrão geométrico válido).

    `sweep_max_extension_bars` precisa ser <= 20 — usa 20."""
    df = _empty_df(55)
    df.at[10, COL_EQUAL_HIGH_LEVEL] = 100.0
    df.at[10, COL_EQUAL_HIGH_IDX] = 10

    # t=50: padrão geometricamente válido para wick sweep bearish.
    _set_candle(df, 50, high=101.0, low=98.5, close=99.0)

    out = detect_liquidity_sweeps(
        df,
        sweep_max_extension_bars=20,
        sweep_max_pivot_age_bars=20,
    )

    # Pivot foi purgado em t=31; wick em t=50 não dispara.
    assert not bool(out[COL_SWEEP_BEARISH_WICK].iloc[50])


# ============================================================
# Cenário H — PD qualification
# ============================================================

def test_smoke_wave8_cenario_h_pd_zone_qualification():
    """Cenário A + coluna `pd_zone` pré-preenchida com 'premium' em
    t=15. Detector com `qualify_with_pd_zone=True` anota a zona PD
    vigente no candle do sweep."""
    df = _empty_df(20)
    df.at[10, COL_EQUAL_HIGH_LEVEL] = 100.0
    df.at[10, COL_EQUAL_HIGH_IDX] = 10
    _set_candle(df, 15, high=101.5, low=99.0, close=99.5)

    # Pré-preenche pd_zone como pd.NA exceto em t=15 (premium).
    df[COL_PD_ZONE] = pd.array([pd.NA] * len(df), dtype='string')
    df.at[15, COL_PD_ZONE] = 'premium'

    out = detect_liquidity_sweeps(df, qualify_with_pd_zone=True)

    assert bool(out[COL_SWEEP_BEARISH_WICK].iloc[15])
    assert out[COL_SWEEP_BEARISH_PD_ZONE].iloc[15] == 'premium'


# ============================================================
# Cenário I — Validação de input
# ============================================================

def test_smoke_wave8_cenario_i_input_validation_pd_zone_missing():
    """`qualify_with_pd_zone=True` sem coluna `pd_zone` → ValueError."""
    df = _empty_df(20)
    with pytest.raises(ValueError, match='qualify_with_pd_zone'):
        detect_liquidity_sweeps(df, qualify_with_pd_zone=True)


def test_smoke_wave8_cenario_i_input_validation_empty_sources():
    """`pivot_sources=()` vazia → ValueError."""
    df = _empty_df(20)
    with pytest.raises(ValueError, match='pivot_sources'):
        detect_liquidity_sweeps(df, pivot_sources=())


def test_smoke_wave8_cenario_i_input_validation_invalid_source():
    """`pivot_sources=('inexistente',)` → ValueError."""
    df = _empty_df(20)
    with pytest.raises(ValueError, match='pivot_sources'):
        detect_liquidity_sweeps(df, pivot_sources=('inexistente',))


# ============================================================
# Cenário J — Múltiplos pivots adjacentes com mesmo nível (O2)
# ============================================================

def test_smoke_wave8_cenario_j_adjacent_pivots_same_level():
    """Dois pivots equal_high em t=10 e t=12 com level=100.0
    (distintos no pool por idx, mesmo preço). Em t=15, ambos
    disparam wick sweep bearish.

    Documenta last-write-wins sobre `sweep_bearish_level_idx[15]`:
    o pivot mais recente processado (t=12, ordem de inscrição
    posterior) sobrescreve `level_idx`. A coluna booleana permanece
    True (idempotente)."""
    df = _empty_df(20)
    # Dois pivots adjacentes, mesmo preço, idx distintos.
    df.at[10, COL_EQUAL_HIGH_LEVEL] = 100.0
    df.at[10, COL_EQUAL_HIGH_IDX] = 10
    df.at[12, COL_EQUAL_HIGH_LEVEL] = 100.0
    df.at[12, COL_EQUAL_HIGH_IDX] = 12

    _set_candle(df, 15, high=101.0, low=99.0, close=99.5)

    out = detect_liquidity_sweeps(df)

    assert bool(out[COL_SWEEP_BEARISH_WICK].iloc[15])
    # Last-write-wins: o pivot inscrito em t=12 é processado depois
    # do pivot inscrito em t=10 (ordem de inserção do dict).
    assert int(out[COL_SWEEP_BEARISH_LEVEL_IDX].iloc[15]) == 12
    assert out[COL_SWEEP_BEARISH_LEVEL_PRICE].iloc[15] == 100.0
