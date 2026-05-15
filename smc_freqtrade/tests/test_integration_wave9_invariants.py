"""Testes de integracao -- invariantes inter-modulares da Onda 9.

OBJETIVO
    Asserir invariantes a-g sobre o output de analyze():
    a. Estrutura do AnalyzeResult (55 cols df, 11 cols/ledger)
    b. Tipos de colunas chave consistentes
    c. Tracking de OB requer BOS/CHoCH previo NO MESMO scope
       (relaxado; initial bias por CHoCH e aceitavel)
    d. OB/FVG mitigado tem t_mitigation > t_creation
    e. pd_ratio e consistente com pd_zone
    f. Ids unicos nos ledgers (primary key)
    g. Anti-mutacao: analyze() nao muta o df do caller

FONTE DE DADOS
    Fixture synthetic_df de conftest.py (450 candles).

LIMITACOES CONHECIDAS
    Nao compara contra TradingView ratificado -- invariantes
    apenas. Match contra golden ratificado vive em
    test_integration_wave9_golden_match.py. Determinismo vive
    em test_integration_wave9_determinism.py.

NAO FAZER
    Nao duplicar testes do smoke (ja cobertos em
    test_smoke_wave9.py).
"""
from __future__ import annotations

import pandas as pd
import pytest

from smc_engine import SMCConfig, analyze


# === Invariante (a) -- Estrutura do AnalyzeResult ===

def test_invariant_a_df_has_added_detector_columns(synthetic_df: pd.DataFrame) -> None:
    """df do result tem 5 OHLC originais + 50 cols dos 6 detectores = 55."""
    result = analyze(synthetic_df)
    assert len(result.df.columns) >= 55


def test_invariant_a_ledgers_have_11_columns(synthetic_df: pd.DataFrame) -> None:
    """Ledgers OB e FVG tem exatamente 11 colunas conforme schema canonico."""
    result = analyze(synthetic_df)
    expected_ob_cols = {
        'ob_id', 'scope', 'bias', 'bar_high', 'bar_low', 'bar_time',
        't_creation', 't_mitigation', 't_invalidation', 'state',
        'volumetric_intensity',
    }
    expected_fvg_cols = {
        'fvg_id', 'bias', 'top', 'bottom', 'bar_time',
        't_creation', 't_mitigation', 't_invalidation', 'state',
        'is_inverse', 'is_double',
    }
    assert set(result.ledger_ob.columns) == expected_ob_cols
    assert set(result.ledger_fvg.columns) == expected_fvg_cols


# === Invariante (b) -- Tipos consistentes ===

def test_invariant_b_ob_bias_is_int(synthetic_df: pd.DataFrame) -> None:
    """ledger_ob.bias contem apenas 1 (BULLISH) ou -1 (BEARISH)."""
    result = analyze(synthetic_df)
    if len(result.ledger_ob) > 0:
        biases = set(result.ledger_ob['bias'].dropna().astype(int))
        assert biases.issubset({1, -1}), f"biases inesperados: {biases}"


def test_invariant_b_ob_scope_is_valid(synthetic_df: pd.DataFrame) -> None:
    """ledger_ob.scope contem apenas 'internal' ou 'swing'."""
    result = analyze(synthetic_df)
    if len(result.ledger_ob) > 0:
        scopes = set(result.ledger_ob['scope'].dropna())
        assert scopes.issubset({'internal', 'swing'}), f"scopes inesperados: {scopes}"


def test_invariant_b_ob_state_is_valid(synthetic_df: pd.DataFrame) -> None:
    """ledger_ob.state contem valores conhecidos."""
    result = analyze(synthetic_df)
    if len(result.ledger_ob) > 0:
        states = set(result.ledger_ob['state'].dropna())
        assert states.issubset({'active', 'mitigated'}), f"states inesperados: {states}"


def test_invariant_b_fvg_bias_is_int(synthetic_df: pd.DataFrame) -> None:
    """ledger_fvg.bias contem apenas 1 ou -1."""
    result = analyze(synthetic_df)
    if len(result.ledger_fvg) > 0:
        biases = set(result.ledger_fvg['bias'].dropna().astype(int))
        assert biases.issubset({1, -1}), f"biases inesperados: {biases}"


# === Invariante (c) -- OB requer estrutura previa (relaxado) ===

def test_invariant_c_ob_creation_has_structure_context(synthetic_df: pd.DataFrame) -> None:
    """Para cada OB criado, ha algum BOS/CHoCH em candle <= t_creation
    no mesmo scope.

    Relaxado: CHoCH inicial sem BOS previo e aceitavel (initial bias
    em structure.py).
    """
    result = analyze(synthetic_df)
    if len(result.ledger_ob) == 0:
        pytest.skip("Sem OBs detectados em synthetic_df")

    for _, ob in result.ledger_ob.iterrows():
        scope = ob['scope']
        structure_cols = [
            f'bos_{scope}_bullish', f'bos_{scope}_bearish',
            f'choch_{scope}_bullish', f'choch_{scope}_bearish',
        ]
        mask_prior = result.df['date'] <= int(ob['t_creation'])
        any_structure = (
            result.df.loc[mask_prior, structure_cols]
            .fillna(False).any().any()
        )
        assert any_structure, (
            f"OB id={ob['ob_id']} criado em t={ob['t_creation']} "
            f"sem BOS/CHoCH previo no scope={scope}"
        )


# === Invariante (d) -- mitigation > creation ===

def test_invariant_d_fvg_mitigation_after_creation(synthetic_df: pd.DataFrame) -> None:
    """Para todo FVG state=mitigated, t_mitigation > t_creation."""
    result = analyze(synthetic_df)
    if len(result.ledger_fvg) == 0:
        pytest.skip("Sem FVGs detectados em synthetic_df")

    mitigated = result.ledger_fvg[result.ledger_fvg['state'] == 'mitigated']
    for _, fvg in mitigated.iterrows():
        assert pd.notna(fvg['t_mitigation']), (
            f"FVG id={fvg['fvg_id']} state=mitigated sem t_mitigation"
        )
        assert int(fvg['t_mitigation']) > int(fvg['t_creation']), (
            f"FVG id={fvg['fvg_id']}: t_mitigation={fvg['t_mitigation']} "
            f"<= t_creation={fvg['t_creation']}"
        )


def test_invariant_d_ob_mitigation_after_creation(synthetic_df: pd.DataFrame) -> None:
    """Para todo OB state=mitigated, t_mitigation > t_creation."""
    result = analyze(synthetic_df)
    if len(result.ledger_ob) == 0:
        pytest.skip("Sem OBs detectados em synthetic_df")

    mitigated = result.ledger_ob[result.ledger_ob['state'] == 'mitigated']
    for _, ob in mitigated.iterrows():
        assert pd.notna(ob['t_mitigation']), (
            f"OB id={ob['ob_id']} state=mitigated sem t_mitigation"
        )
        assert int(ob['t_mitigation']) > int(ob['t_creation']), (
            f"OB id={ob['ob_id']}: t_mitigation={ob['t_mitigation']} "
            f"<= t_creation={ob['t_creation']}"
        )


# === Invariante (e) -- pd_ratio consistente com pd_zone ===

def test_invariant_e_pd_zone_matches_ratio(synthetic_df: pd.DataFrame) -> None:
    """pd_zone segue regras canonicas vs pd_ratio:
    ratio > 0.5 -> premium; < 0.5 -> discount; == 0.5 -> equilibrium.
    """
    result = analyze(synthetic_df)
    df = result.df.dropna(subset=['pd_ratio', 'pd_zone'])
    if len(df) == 0:
        pytest.skip("Sem rows com pd_ratio e pd_zone definidos")

    for _, row in df.iterrows():
        ratio = float(row['pd_ratio'])
        zone = str(row['pd_zone'])
        if ratio > 0.5:
            assert zone == 'premium', f"ratio={ratio} -> esperado premium, got {zone}"
        elif ratio < 0.5:
            assert zone == 'discount', f"ratio={ratio} -> esperado discount, got {zone}"
        else:
            assert zone == 'equilibrium', f"ratio={ratio} -> esperado equilibrium, got {zone}"


# === Invariante (f) -- ids unicos no ledger ===

def test_invariant_f_ledger_ob_id_is_unique(synthetic_df: pd.DataFrame) -> None:
    """ob_id e unico no ledger_ob (primary key)."""
    result = analyze(synthetic_df)
    if len(result.ledger_ob) > 0:
        ids = result.ledger_ob['ob_id']
        assert ids.is_unique, f"ob_id duplicados: {ids[ids.duplicated()].tolist()}"


def test_invariant_f_ledger_fvg_id_is_unique(synthetic_df: pd.DataFrame) -> None:
    """fvg_id e unico no ledger_fvg (primary key)."""
    result = analyze(synthetic_df)
    if len(result.ledger_fvg) > 0:
        ids = result.ledger_fvg['fvg_id']
        assert ids.is_unique, f"fvg_id duplicados: {ids[ids.duplicated()].tolist()}"


# === Invariante (g) -- analyze() nao muta input ===

def test_invariant_g_analyze_does_not_mutate_input(synthetic_df: pd.DataFrame) -> None:
    """analyze() nao muta o df do caller."""
    df_before = synthetic_df.copy()
    snapshot = synthetic_df.copy()
    _ = analyze(df_before)
    pd.testing.assert_frame_equal(df_before, snapshot)


# === Sanity: configs diferentes produzem outputs diferentes ===

def test_different_configs_produce_different_outputs(synthetic_df: pd.DataFrame) -> None:
    """Mudar pivot_swings_length altera os pivots (sanity)."""
    r1 = analyze(synthetic_df, SMCConfig(pivot_swings_length=50))
    r2 = analyze(synthetic_df, SMCConfig(pivot_swings_length=20))
    pivots_diff = (
        r1.df['swing_high_idx'].fillna(-1) != r2.df['swing_high_idx'].fillna(-1)
    ).any()
    assert pivots_diff, "configs diferentes produziram mesmos pivots -- inesperado"
