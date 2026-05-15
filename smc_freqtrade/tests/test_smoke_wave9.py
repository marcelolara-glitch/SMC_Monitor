"""Smoke E2E da Onda 9 — analyze() ponta-a-ponta.

OBJETIVO
    Garantir que analyze() retorna AnalyzeResult bem-formado quando
    chamado sobre synthetic_df. Não valida correção dos eventos
    detectados (isso vem nos integration tests do PR 2).

FONTE DE DADOS
    Fixture synthetic_df de conftest.py (450 candles, RandomState=42).

LIMITAÇÕES CONHECIDAS
    Não valida valores específicos de eventos — apenas estrutura.

NÃO FAZER
    Não acrescentar asserts sobre conteúdo do golden ratificado —
    isso é responsabilidade dos integration tests do PR 2.
"""
from __future__ import annotations

import pandas as pd
import pytest

from smc_engine import (
    __version__,
    AnalyzeResult,
    SMCConfig,
    analyze,
)


def test_analyze_returns_analyze_result(synthetic_df: pd.DataFrame) -> None:
    """analyze() retorna instância de AnalyzeResult."""
    result = analyze(synthetic_df)
    assert isinstance(result, AnalyzeResult)


def test_analyze_default_config(synthetic_df: pd.DataFrame) -> None:
    """analyze() funciona com config=None (usa defaults)."""
    result = analyze(synthetic_df, config=None)
    assert isinstance(result, AnalyzeResult)


def test_analyze_explicit_config(synthetic_df: pd.DataFrame) -> None:
    """analyze() aceita SMCConfig explícito."""
    config = SMCConfig()
    result = analyze(synthetic_df, config=config)
    assert isinstance(result, AnalyzeResult)


def test_analyze_df_has_expected_columns(synthetic_df: pd.DataFrame) -> None:
    """df do result tem as 5 colunas obrigatórias + colunas dos 6 detectores."""
    result = analyze(synthetic_df)
    for col in ('date', 'open', 'high', 'low', 'close'):
        assert col in result.df.columns
    assert 'swing_high_level' in result.df.columns
    assert 'trailing_top' in result.df.columns
    assert 'bos_swing_bullish' in result.df.columns
    assert 'ob_swing_bullish_created' in result.df.columns
    assert 'fvg_bullish_created' in result.df.columns
    assert 'sweep_bullish_wick' in result.df.columns


def test_analyze_ledgers_are_dataframes(synthetic_df: pd.DataFrame) -> None:
    """Ledgers OB e FVG são pd.DataFrame com 11 colunas cada."""
    result = analyze(synthetic_df)
    assert isinstance(result.ledger_ob, pd.DataFrame)
    assert isinstance(result.ledger_fvg, pd.DataFrame)
    assert len(result.ledger_ob.columns) == 11
    assert len(result.ledger_fvg.columns) == 11


def test_analyze_meta_fields(synthetic_df: pd.DataFrame) -> None:
    """meta tem 4 campos obrigatórios."""
    result = analyze(synthetic_df)
    assert result.meta['engine_version'] == __version__
    assert result.meta['engine_version'] == '0.9.0'
    assert len(result.meta['modules_run']) == 6
    assert result.meta['candle_count'] == len(synthetic_df)
    assert isinstance(result.meta['config_used'], dict)
    assert 'pivot_swings_length' in result.meta['config_used']


def test_analyze_rejects_empty_df() -> None:
    """analyze() levanta ValueError em df vazio."""
    with pytest.raises(ValueError, match="não-vazio"):
        analyze(pd.DataFrame())


def test_analyze_rejects_missing_columns(synthetic_df: pd.DataFrame) -> None:
    """analyze() levanta ValueError com mensagem clara quando faltam colunas."""
    df_broken = synthetic_df.drop(columns=['close'])
    with pytest.raises(ValueError, match="close"):
        analyze(df_broken)


def test_analyze_rejects_short_df(synthetic_df: pd.DataFrame) -> None:
    """analyze() levanta ValueError quando len(df) < threshold."""
    df_short = synthetic_df.head(100)
    with pytest.raises(ValueError, match="requer len"):
        analyze(df_short)


def test_smcconfig_validates_negative_pivot_length() -> None:
    """SMCConfig levanta ValueError em parâmetros inválidos."""
    with pytest.raises(ValueError, match="pivot_swings_length"):
        SMCConfig(pivot_swings_length=1)


def test_smcconfig_validates_invalid_sweep_source() -> None:
    """SMCConfig levanta ValueError com source inválido."""
    with pytest.raises(ValueError, match="sweep_pivot_sources"):
        SMCConfig(sweep_pivot_sources=('invalid',))


def test_smcconfig_validates_empty_sweep_sources() -> None:
    """SMCConfig levanta ValueError com sweep_pivot_sources vazio."""
    with pytest.raises(ValueError, match="não pode ser vazio"):
        SMCConfig(sweep_pivot_sources=())


def test_analyze_result_is_frozen(synthetic_df: pd.DataFrame) -> None:
    """AnalyzeResult é frozen — atribuições levantam FrozenInstanceError."""
    from dataclasses import FrozenInstanceError
    result = analyze(synthetic_df)
    with pytest.raises(FrozenInstanceError):
        result.df = pd.DataFrame()  # type: ignore[misc]
