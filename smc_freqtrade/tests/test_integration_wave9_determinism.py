"""Determinismo -- analyze() e idempotente sobre o mesmo input.

OBJETIVO
    Garantir que duas chamadas de analyze() no mesmo df produzem
    AnalyzeResult bit-identico em df, ledger_ob e ledger_fvg.
    Critico para reprodutibilidade de hash do golden JSON.

FONTE DE DADOS
    synthetic_df de conftest.py.

LIMITACOES CONHECIDAS
    Compara apenas df, ledger_ob, ledger_fvg (campos persistentes).
    meta tem campos derivados de config (sem timestamps de relogio).

NAO FAZER
    Nao duplicar testes de invariantes (vide
    test_integration_wave9_invariants.py).
"""
from __future__ import annotations

import pandas as pd

from smc_engine import SMCConfig, analyze


def test_analyze_is_deterministic_df(synthetic_df: pd.DataFrame) -> None:
    """Duas chamadas -> result.df identicos."""
    r1 = analyze(synthetic_df)
    r2 = analyze(synthetic_df)
    pd.testing.assert_frame_equal(r1.df, r2.df)


def test_analyze_is_deterministic_ledger_ob(synthetic_df: pd.DataFrame) -> None:
    """Duas chamadas -> ledger_ob identicos."""
    r1 = analyze(synthetic_df)
    r2 = analyze(synthetic_df)
    pd.testing.assert_frame_equal(r1.ledger_ob, r2.ledger_ob)


def test_analyze_is_deterministic_ledger_fvg(synthetic_df: pd.DataFrame) -> None:
    """Duas chamadas -> ledger_fvg identicos."""
    r1 = analyze(synthetic_df)
    r2 = analyze(synthetic_df)
    pd.testing.assert_frame_equal(r1.ledger_fvg, r2.ledger_fvg)


def test_analyze_is_deterministic_meta_persistent(synthetic_df: pd.DataFrame) -> None:
    """Duas chamadas -> meta com campos persistentes identicos."""
    r1 = analyze(synthetic_df)
    r2 = analyze(synthetic_df)
    assert r1.meta['engine_version'] == r2.meta['engine_version']
    assert r1.meta['modules_run'] == r2.meta['modules_run']
    assert r1.meta['candle_count'] == r2.meta['candle_count']
    assert r1.meta['config_used'] == r2.meta['config_used']


def test_analyze_deterministic_across_configs(synthetic_df: pd.DataFrame) -> None:
    """Mesma config em duas instancias separadas -> mesmo output."""
    c1 = SMCConfig()
    c2 = SMCConfig()
    r1 = analyze(synthetic_df, c1)
    r2 = analyze(synthetic_df, c2)
    pd.testing.assert_frame_equal(r1.df, r2.df)
    pd.testing.assert_frame_equal(r1.ledger_ob, r2.ledger_ob)
    pd.testing.assert_frame_equal(r1.ledger_fvg, r2.ledger_fvg)
