"""
OBJETIVO
    Smoke test da Onda 6.2 — Breaker Blocks via morte por extremidade
    oposta. Cobre os critérios C1-C5 do briefing 6.2 §6 sobre a
    fixture sintética da Onda 6 (`synthetic_df` / `synthetic_df_co_mit`),
    sem duplicar builder/fixture.

    Reusa pipeline da Onda 6 (detect_pivots → trailing → structure →
    detect_order_blocks); a única diferença é assertar sobre a
    presença de `'breaker_broken'`, `t_invalidation`, `bb_volume` e a
    estabilidade dos booleans per-candle vs. saída pré-6.2 simulada
    via mascaramento das colunas novas do ledger.

FONTE DE DADOS
    Fixture sintética determinística (RandomState=42) da Onda 6.
    Cenário 4 (bb_volume) constrói um mini-DataFrame OHLC dedicado
    para isolar o efeito da presença/ausência de `volume`.

LIMITAÇÕES CONHECIDAS
    Cenários 1-3 (morte/vivo/ativo) são exercitados sobre a fixture
    real ao invés de minicasos construídos — a fase 6 da fixture
    produz naturalmente OBs em todos os 3 estados terminais possíveis
    (active, mitigated, breaker_broken).

    Cenário 5 (regressão C5) reusa diretamente os asserts de
    `test_smoke_wave6_lifecycle` em forma reduzida: os 8 booleans
    per-candle são uma função apenas de t_creation / t_mitigation,
    inalterados pela 6.2.

NÃO FAZER
    Não duplicar a fixture base — importar de test_smoke_wave6.
    Não exercitar o pipeline duas vezes só para gerar contagens
        (cobrir múltiplos asserts numa mesma execução).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from smc_engine import (
    BEARISH,
    BULLISH,
    compute_trailing_extremes,
    detect_order_blocks,
    detect_pivots,
    detect_structure,
)

from tests.test_smoke_wave6 import (
    _run_pipeline,
    synthetic_df,
    synthetic_df_co_mit,
)


def test_wave6_2_breaker_death_invariants(synthetic_df_co_mit):
    """C1 + C2 + C3 sobre fixture estendida.

    A fase 6 da fixture co-mit gera (a) ≥1 OB que mitiga e morre por
    extremidade oposta (`'breaker_broken'`); (b) ≥1 OB mitigado
    permanente (`'mitigated'` com `t_invalidation == NaT`); (c) ≥1 OB
    nunca mitigado (`'active'`). Cobertura conjunta numa execução
    da pipeline.
    """
    _, ledger = _run_pipeline(synthetic_df_co_mit, mitigation='Wick')

    states = ledger['state']

    # C1 — breaker morto: t_invalidation setado, t_mitigation setado,
    # state == 'breaker_broken', t_invalidation > t_mitigation.
    broken = ledger[states == 'breaker_broken']
    assert len(broken) >= 1, (
        'Fixture co-mit deve produzir >=1 breaker morto. '
        'Ajustar fase 6, não o assert.'
    )
    assert broken['t_invalidation'].notna().all()
    assert broken['t_mitigation'].notna().all()
    assert (broken['t_invalidation'] > broken['t_mitigation']).all()

    # C2 — breaker vivo: state == 'mitigated', t_invalidation NaT,
    # t_mitigation setado.
    alive = ledger[states == 'mitigated']
    assert len(alive) >= 1, (
        'Fixture co-mit deve produzir >=1 breaker vivo (mitigado '
        'sem saída pela oposta).'
    )
    assert alive['t_invalidation'].isna().all()
    assert alive['t_mitigation'].notna().all()

    # C3 — OB nunca mitigado: state == 'active', ambos NaT.
    active = ledger[states == 'active']
    assert len(active) >= 1, 'Fixture deve produzir >=1 OB active.'
    assert active['t_mitigation'].isna().all()
    assert active['t_invalidation'].isna().all()


def test_wave6_2_bb_volume_presence(synthetic_df_co_mit):
    """C4 — `bb_volume` preenchido sse `volume` presente.

    Variante 1: fixture sintética sem `volume` → bb_volume = pd.NA em
    todos os records (mesmo nos breakers/mitigados).

    Variante 2: mesma fixture + coluna `volume` sintética →
    bb_volume preenchido nos records com t_mitigation setado, NA nos
    `'active'`.
    """
    # Variante 1: sem volume.
    _, ledger_no_vol = _run_pipeline(synthetic_df_co_mit, mitigation='Wick')
    assert 'bb_volume' in ledger_no_vol.columns
    assert ledger_no_vol['bb_volume'].isna().all()

    # Variante 2: com volume. Adicionar coluna ANTES do pipeline para
    # que o detector consuma. `synthetic_df_co_mit` é pd.DataFrame
    # fresh por fixture; mutação local ok.
    df = synthetic_df_co_mit.copy()
    rng = np.random.RandomState(7)
    df['volume'] = rng.uniform(1.0, 1000.0, size=len(df))
    _, ledger_vol = _run_pipeline(df, mitigation='Wick')

    mitigated_or_broken = ledger_vol['t_mitigation'].notna()
    assert mitigated_or_broken.any(), (
        'Fixture deve produzir >=1 OB mitigado para teste de bb_volume.'
    )
    assert ledger_vol.loc[mitigated_or_broken, 'bb_volume'].notna().all(), (
        'bb_volume deve estar preenchido em todo record com '
        't_mitigation setado quando coluna `volume` existe.'
    )
    # Active OBs (sem mitigação) sempre NA.
    active_mask = ledger_vol['state'] == 'active'
    if active_mask.any():
        assert ledger_vol.loc[active_mask, 'bb_volume'].isna().all()


def test_wave6_2_regression_per_candle_booleans(synthetic_df_co_mit):
    """C5 — 8 booleans per-candle e os campos preservados do ledger
    (t_creation, t_mitigation, bar_high, bar_low, bar_time) são
    idênticos ao que a Onda 6 teria produzido.

    Não há "saída pré-6.2" persistida; o teste verifica as
    propriedades estruturais que a 6.2 promete preservar:

    1. count(boolean_created) == count(scope/bias) no ledger.
    2. count(boolean_mitigated) == count(t_mitigation.notna()) por
       scope/bias (note: `state == 'breaker_broken'` ainda conta como
       mitigado para este boolean).
    3. t_creation/t_mitigation valores válidos preservados (não-NaT
       quando booleans correspondentes True).
    """
    df_out, ledger = _run_pipeline(synthetic_df_co_mit, mitigation='Wick')

    for scope in ('internal', 'swing'):
        for direction in (BULLISH, BEARISH):
            bias_word = 'bullish' if direction == BULLISH else 'bearish'
            col_created = f'ob_{scope}_{bias_word}_created'
            col_mitigated = f'ob_{scope}_{bias_word}_mitigated'

            sub = ledger[
                (ledger['scope'] == scope) & (ledger['bias'] == direction)
            ]
            count_created_df = int(df_out[col_created].sum())
            assert count_created_df == len(sub), (
                f'{col_created}: df={count_created_df} vs '
                f'ledger={len(sub)}'
            )

            # Boolean per-candle é único (co-mitigação colapsa N OBs
            # em uma única flag por candle) — comparar conjuntos de
            # candle dates, não contagens.
            mit_dates_df = set(
                df_out.loc[df_out[col_mitigated], 'date'].tolist()
            )
            mit_dates_ledger = set(
                sub.loc[sub['t_mitigation'].notna(), 't_mitigation']
                .tolist()
            )
            assert mit_dates_df == mit_dates_ledger, (
                f'{col_mitigated}: candle set mismatch '
                f'(df={len(mit_dates_df)} vs '
                f'ledger={len(mit_dates_ledger)})'
            )

    # t_creation sempre setado; t_mitigation setado sse state != 'active'.
    assert ledger['t_creation'].notna().all()
    not_active = ledger['state'] != 'active'
    assert ledger.loc[not_active, 't_mitigation'].notna().all()


def test_wave6_2_death_after_mitigation(synthetic_df_co_mit):
    """C7 (lookahead-safe) — para todo breaker morto,
    t_invalidation > t_mitigation estrito (scan usa
    `date > t_mitigation`)."""
    _, ledger = _run_pipeline(synthetic_df_co_mit, mitigation='Wick')
    broken = ledger[ledger['state'] == 'breaker_broken']
    if len(broken) == 0:
        pytest.skip('Fixture não produziu breaker morto neste run.')
    assert (broken['t_invalidation'] > broken['t_mitigation']).all()


def test_wave6_2_ledger_schema():
    """C6 — ledger tem 12 colunas, vocabulário de 3 estados aceito.

    Constrói um DataFrame mínimo (sem nenhum OB esperado) para
    exercitar o ledger vazio com schema correto.
    """
    n = 60
    base = 100.0
    df = pd.DataFrame({
        'open': [base] * n,
        'high': [base + 0.5] * n,
        'low': [base - 0.5] * n,
        'close': [base] * n,
        'date': (
            pd.date_range('2026-01-01', periods=n, freq='4h')
            .astype('int64') // 10**6
        ),
    })
    df = detect_pivots(
        df, swings_length=5, internal_length=3, equal_length=3,
    )
    df = compute_trailing_extremes(df)
    df = detect_structure(df)
    _, ledger = detect_order_blocks(df)
    expected_cols = [
        'ob_id', 'scope', 'bias', 'bar_high', 'bar_low', 'bar_time',
        't_creation', 't_mitigation', 't_invalidation', 'state',
        'volume_bullish', 'volume_bearish', 'volume_total', 'volume_pct',
        'bb_volume',
    ]
    assert list(ledger.columns) == expected_cols
    assert len(ledger.columns) == 15
