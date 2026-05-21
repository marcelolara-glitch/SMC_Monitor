"""Engine SMC — orquestrador principal analyze().

OBJETIVO
    Receber um DataFrame OHLCV e produzir AnalyzeResult com df
    expandido (52 colunas) + 2 ledgers (OB, FVG) + meta de execução.

FONTE DE DADOS
    DataFrame OHLCV com colunas: date, open, high, low, close
    (volume é opcional). Tipo de date deve ser homogêneo (todo
    pd.Timestamp OU todo int64).

LIMITAÇÕES CONHECIDAS
    - NaN nas primeiras linhas do OHLC é tolerado (warm-up dos
      indicadores). NaN no meio da série produz output indefinido
      nos candles afetados (sem crash).
    - Engine é stateless; cada chamada constrói output from-scratch.
      EngineState não é tocado (reservado para Onda 10).
    - df.copy() outer não é feito; cada detector já faz cópia
      interna. Teste de invariante (test_integration_wave9_invariants)
      cobre regressão.

NÃO FAZER
    - Não chamar detectores fora de ordem (pivots → trailing →
      structure → order_blocks; fvg e liquidity_sweep podem rodar
      em paralelo após dependências).
    - Não mutar o df do caller.
    - Não emitir analyze() com modos especiais ('swing_only' etc.) —
      isso vem na Onda 10 via SMCConfig presets.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

import pandas as pd

from .config import SMCConfig
from .fvg import detect_fair_value_gaps
from .liquidity_sweep import detect_liquidity_sweeps
from .order_blocks import detect_order_blocks
from .pivots import detect_eqh_eql, detect_pivots
from .result import AnalyzeResult
from .structure import detect_structure
from .trailing import compute_trailing_extremes

REQUIRED_COLUMNS = ('date', 'open', 'high', 'low', 'close')


def _validate_input(df: pd.DataFrame, config: SMCConfig) -> None:
    """Valida fronteira de input do analyze().

    Verifica:
        1. df é pd.DataFrame não-vazio.
        2. Colunas obrigatórias presentes.
        3. Tipo do 'date' homogêneo.
        4. len(df) >= threshold derivado de config.

    Não valida:
        - NaN em OHLC (warm-up tolerado; documentado).
        - Conteúdo semântico (high >= low etc.) — responsabilidade
          do caller.

    Raises:
        ValueError com mensagem explicativa.
    """
    if not isinstance(df, pd.DataFrame):
        raise ValueError(
            f"analyze() exige pd.DataFrame, recebeu {type(df).__name__}"
        )
    if len(df) == 0:
        raise ValueError("analyze() exige df não-vazio")
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(
            f"analyze() exige colunas {REQUIRED_COLUMNS}, "
            f"faltam: {missing}"
        )
    date_types = df['date'].map(type).unique()
    if len(date_types) > 1:
        raise ValueError(
            f"df['date'] tem tipos heterogêneos: {list(date_types)}. "
            f"Esperado: todos pd.Timestamp ou todos int."
        )
    min_required = max(
        config.pivot_swings_length,
        config.ob_atr_length,
    ) + 3
    if len(df) < min_required:
        raise ValueError(
            f"analyze() requer len(df) >= {min_required} candles "
            f"(max(pivot_swings_length={config.pivot_swings_length}, "
            f"ob_atr_length={config.ob_atr_length}) + 3); "
            f"recebeu len(df)={len(df)}."
        )


def analyze(
    df: pd.DataFrame,
    config: SMCConfig | None = None,
) -> AnalyzeResult:
    """Orquestra os 6 detectores SMC e retorna AnalyzeResult.

    Args:
        df: DataFrame OHLCV com colunas obrigatórias date, open, high,
            low, close. 'date' deve ter tipo homogêneo. len(df) deve
            ser >= max(config.pivot_swings_length,
            config.ob_atr_length) + 3.
        config: Configuração SMC. Se None, usa SMCConfig() com
            defaults LuxAlgo-aligned.

    Returns:
        AnalyzeResult com:
            - df: input + 52 colunas dos 6 detectores
            - ledger_ob: ledger de Order Blocks (11 colunas)
            - ledger_fvg: ledger de FVGs (11 colunas)
            - meta: dict com engine_version, modules_run,
              candle_count, config_used

    Raises:
        ValueError: input inválido (vide _validate_input).

    Notas:
        - Não muta o df do caller (cada detector faz cópia interna).
        - Engine é stateless (não usa EngineState).
        - Smoke E2E: 450 candles sintéticos com synthetic_df de
          tests/conftest.py.
    """
    if config is None:
        config = SMCConfig()
    _validate_input(df, config)

    work = df
    work = detect_pivots(
        work,
        swings_length=config.pivot_swings_length,
        internal_length=config.pivot_internal_length,
        equal_length=config.pivot_equal_length,
        equal_threshold=config.pivot_equal_threshold,
    )
    # Wave 8.1 — sobrescreve equal_*_alert legados com a fórmula
    # canônica do Pine LuxAlgo `ICT Concepts` (banda dinâmica
    # atr(10)/a + 3+ swings same-direction).
    work = detect_eqh_eql(
        work,
        eq_atr_length=config.eq_atr_length,
        eq_margin=config.eq_margin,
        eq_lookback_pivots=config.eq_lookback_pivots,
        eq_min_pivots=config.eq_min_pivots,
    )
    work = compute_trailing_extremes(work)
    work = detect_structure(
        work,
        internal_filter_confluence=config.structure_internal_filter_confluence,
    )
    work, ledger_ob = detect_order_blocks(
        work,
        ob_filter=config.ob_filter,
        mitigation=config.ob_mitigation,
        atr_length=config.ob_atr_length,
    )
    work, ledger_fvg = detect_fair_value_gaps(
        work,
        auto_threshold=config.fvg_auto_threshold,
    )
    work = detect_liquidity_sweeps(
        work,
        pivot_sources=config.sweep_pivot_sources,
        sweep_max_extension_bars=config.sweep_max_extension_bars,
        sweep_max_pivot_age_bars=config.sweep_max_pivot_age_bars,
        qualify_with_pd_zone=config.sweep_qualify_with_pd_zone,
    )

    from . import __version__
    meta: dict[str, Any] = {
        'engine_version': __version__,
        'modules_run': [
            'detect_pivots',
            'detect_eqh_eql',
            'compute_trailing_extremes',
            'detect_structure',
            'detect_order_blocks',
            'detect_fair_value_gaps',
            'detect_liquidity_sweeps',
        ],
        'candle_count': len(work),
        'config_used': asdict(config),
    }
    return AnalyzeResult(
        df=work,
        ledger_ob=ledger_ob,
        ledger_fvg=ledger_fvg,
        meta=meta,
    )
