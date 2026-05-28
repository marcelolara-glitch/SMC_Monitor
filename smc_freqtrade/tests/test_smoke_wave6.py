"""
OBJETIVO
    Smoke test da Onda 6 — Order Blocks com mitigação. Cobre as 13
    invariantes do briefing §4.4 distribuídas em 5 funções de teste
    conforme briefing §5.2.

    Fixture sintética de 6 fases (briefing §5.1) deriva da fixture da
    Onda 5 (450 candles, 5 fases de price action) acrescida de fase 6
    (queda profunda que co-mitiga ≥2 OBs bullish swing simultaneamente,
    cobrindo invariante 13).

FONTE DE DADOS
    Fixture sintética determinística (RandomState=42) baseada na
    fixture da Onda 5 + extensão de fase 6 para co-mitigação.

LIMITAÇÕES CONHECIDAS
    `test_smoke_wave6_parsed_high_low_inversion` testa a inversão
    diretamente sobre o helper `_compute_parsed_high_low` em vez de
    via ledger — opção mais clara que reconstruir o estado interno
    do ledger; alinhado com a flexibilidade declarada no briefing
    §5.2 ("teste mais detalhado em implementation review").

    Co-mitigação SWING bullish exige fixture estendida (fase 6); a
    fixture base produz co-mitigação INTERNAL bullish naturalmente
    como subproduto. Briefing §5.1 fase 6 prescreve SWING — fixture
    `synthetic_df_co_mit` adiciona um candle de drop sharp que fura
    `bar_low` de OBs swing bullish 15 e 18 simultaneamente.

NÃO FAZER
    Não importar de smc_freqtrade.smc_engine — pacote raiz é
    `smc_engine`.
    Não ajustar asserts para acomodar fixture quebrada — ajustar a
    fixture (briefing §5.1).
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
from smc_engine.order_blocks import _compute_parsed_high_low


def _build_fixture(n: int, landmarks: list[tuple[int, float]]) -> pd.DataFrame:
    rng = np.random.RandomState(42)
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
        'open': opens,
        'high': highs,
        'low': lows,
        'close': closes,
        'date': dates,
    })


@pytest.fixture
def synthetic_df() -> pd.DataFrame:
    """Fixture base — 450 candles com 5 fases derivadas da fixture da
    Onda 5. Adiciona coluna `date` (epoch ms) requerida pelo briefing
    Onda 6 §4.1.

    Fase 1 (0-129):     setup — forma swing_low (low[0]=89.5,
                        detectado em X=50) e swing_high (close peak
                        ~candle 80, detectado em X=130).
    Fase 2 (130-153):   close cruza swing_high_level upward → BOS
                        bullish (cria 1+ bullish swing OBs).
    Fase 3 (210-214):   close cruza swing_low_level downward → CHoCH
                        bearish (cria bearish swing OB; mitiga
                        bullish OB anterior por Wick).
    Fase 4 (300-311):   close cruza novo swing_high_level upward →
                        CHoCH bullish (cria novo bullish swing OB).
    Fase 5 (390-413):   close cruza outro novo swing_high_level
                        upward → BOS bullish (cria mais 1 bullish
                        swing OB; mantém múltiplos OBs ativos
                        simultaneamente).
    """
    landmarks = [
        (0, 90.0), (5, 100.0), (50, 100.0), (80, 115.0), (110, 100.0),
        (130, 100.0), (170, 130.0), (210, 130.0), (215, 85.0),
        (245, 85.0), (250, 120.0), (270, 100.0), (300, 100.0),
        (320, 140.0), (340, 150.0), (370, 130.0), (390, 130.0),
        (430, 165.0), (449, 160.0),
    ]
    return _build_fixture(450, landmarks)


@pytest.fixture
def synthetic_df_co_mit() -> pd.DataFrame:
    """Fixture estendida — base de 450 candles + fase 6 (~451-510)
    com queda profunda que co-mitiga ≥2 bullish swing OBs no mesmo
    candle.

    Fase 6 (450-509): preço desce de 160 (close fim fase 5) para 130
                      em 50 candles (gradual), seguido de candle 510
                      de drop sharp (low ~85) que fura bar_low de
                      múltiplos bullish swing OBs no mesmo candle.
                      Cobre invariante 13.
    """
    landmarks = [
        (0, 90.0), (5, 100.0), (50, 100.0), (80, 115.0), (110, 100.0),
        (130, 100.0), (170, 130.0), (210, 130.0), (215, 85.0),
        (245, 85.0), (250, 120.0), (270, 100.0), (300, 100.0),
        (320, 140.0), (340, 150.0), (370, 130.0), (390, 130.0),
        (430, 165.0), (449, 160.0),
        # Fase 6: gradual decline + sharp drop final.
        (480, 145.0), (510, 130.0),
    ]
    df = _build_fixture(515, landmarks)
    # Candle 511: sharp drop — close cai para ~100, low fura todos
    # bullish OBs swing (bar_low de OB 15 ~95.87 e OB 18 ~125.52).
    df.loc[511, 'open'] = 130.0
    df.loc[511, 'close'] = 90.0
    df.loc[511, 'high'] = 130.5
    df.loc[511, 'low'] = 85.0
    # Candles 512-514: rebote leve, mantém preço baixo.
    df.loc[512, ['open', 'high', 'low', 'close']] = [90.0, 95.0, 88.0, 92.0]
    df.loc[513, ['open', 'high', 'low', 'close']] = [92.0, 96.0, 90.0, 94.0]
    df.loc[514, ['open', 'high', 'low', 'close']] = [94.0, 97.0, 92.0, 95.0]
    return df


def _run_pipeline(df: pd.DataFrame, mitigation: str = 'Wick'):
    df = detect_pivots(
        df, swings_length=50, internal_length=5, equal_length=3,
    )
    df = compute_trailing_extremes(df)
    df = detect_structure(df)
    return detect_order_blocks(df, mitigation=mitigation)


def test_smoke_wave6_lifecycle(synthetic_df):
    """Cobertura conjunta de invariantes 1, 4, 5, 7, 8, 9, 10, 11.

    Não fragmenta em sub-testes — cada invariante é uma asserção do
    mesmo ciclo de vida, e fragmentar exigiria executar a pipeline
    completa N vezes (custo O(n) por execução, sem ganho de sinal).
    """
    df_out, ledger = _run_pipeline(synthetic_df, mitigation='Wick')

    assert len(ledger) > 0, (
        'Fixture deve produzir ao menos 1 OB. Bug em fixture ou pipeline.'
    )

    # Invariante 1 — re-emissão controlada.
    for scope in ('internal', 'swing'):
        for direction in (BULLISH, BEARISH):
            bias_word = 'bullish' if direction == BULLISH else 'bearish'
            col_created = f'ob_{scope}_{bias_word}_created'
            count_df = int(df_out[col_created].sum())
            count_ledger = int(
                ((ledger['scope'] == scope) & (ledger['bias'] == direction))
                .sum()
            )
            assert count_df == count_ledger, (
                f'{col_created}: df={count_df} vs ledger={count_ledger}'
            )

    # Invariante 4 — t_mitigation > t_creation estrito (P11).
    mitigated = ledger.dropna(subset=['t_mitigation'])
    assert (mitigated['t_mitigation'] > mitigated['t_creation']).all()

    # Invariante 5 — bar_high >= bar_low.
    assert (ledger['bar_high'] >= ledger['bar_low']).all()

    # Invariante 7 — scope ∈ {'internal', 'swing'}.
    assert set(ledger['scope'].unique()).issubset({'internal', 'swing'})

    # Invariante 8 — state ∈ {'active','mitigated','breaker_broken'}
    # (vocabulário ampliado pela Onda 6.2).
    assert set(ledger['state'].unique()).issubset(
        {'active', 'mitigated', 'breaker_broken'}
    )

    # Invariante 9 — state == 'active' ⇔ t_mitigation is pd.NaT.
    # `'mitigated'` e `'breaker_broken'` ambos têm t_mitigation
    # preenchido (6.2 §2 P2: morte preserva t_mitigation original).
    active_mask = ledger['state'] == 'active'
    assert active_mask.eq(ledger['t_mitigation'].isna()).all()

    # Invariante 10 — t_invalidation preenchido sse state ==
    # 'breaker_broken' (6.2 §2 P5).
    breaker_broken_mask = ledger['state'] == 'breaker_broken'
    assert breaker_broken_mask.eq(ledger['t_invalidation'].notna()).all()

    # Invariante 11 — volumetric fields present (Wave 6.1).
    assert 'volume_bullish' in ledger.columns
    assert 'volume_bearish' in ledger.columns
    assert 'volume_total' in ledger.columns
    assert 'volume_pct' in ledger.columns

    # Cobertura mínima da fixture: pelo menos 1 mitigated e 1 active.
    # Mitigated agrega `'mitigated'` (breaker vivo) + `'breaker_broken'`
    # (breaker morto) — ambos descendem da mitigação Wave 6.
    n_mitigated_or_broken = (
        (ledger['state'] == 'mitigated')
        | (ledger['state'] == 'breaker_broken')
    ).sum()
    assert n_mitigated_or_broken >= 1
    assert (ledger['state'] == 'active').sum() >= 1


def test_smoke_wave6_mitigation_close_mode(synthetic_df):
    """Modo Close usa close como source, não high/low.

    Assert forte (não-tautológico): pelo menos um OB do ledger tem
    comportamento de mitigação diferente entre Wick e Close. Sem
    isso, o teste passaria mesmo se a engine ignorasse o parâmetro
    `mitigation` (Wick é estritamente mais permissivo que Close
    para qualquer OHLC válido — então `n_mit_close <= n_mit_wick`
    é tautológico).
    """
    _, ledger_wick = _run_pipeline(synthetic_df, mitigation='Wick')
    _, ledger_close = _run_pipeline(synthetic_df, mitigation='Close')

    joined = ledger_wick.merge(
        ledger_close, on='ob_id', suffixes=('_wick', '_close'),
    )
    strictly_earlier = (
        joined['t_mitigation_wick'].notna()
        & joined['t_mitigation_close'].notna()
        & (joined['t_mitigation_wick'] < joined['t_mitigation_close'])
    ).any()
    wick_only = (
        joined['t_mitigation_wick'].notna()
        & joined['t_mitigation_close'].isna()
    ).any()
    assert strictly_earlier or wick_only, (
        'Parâmetro mitigation parece estar sendo ignorado: Wick e '
        'Close produzem ledgers indistinguíveis. Verificar '
        'implementação de _resolve_mitigations.'
    )


def test_smoke_wave6_bar_time_within_window(synthetic_df):
    """Invariantes 2 e 3 — bar_time (= t_origin) cai dentro da janela
    `[pivot_time, t_creation)`.

    A invariante mínima sobre o ledger sem reconstruir pivot_time é
    `bar_time < t_creation` — bar_time é necessariamente um candle
    da janela `[pivot_idx, break_idx)`, então tem date < date do
    break. Equivalente a invariante 3 do briefing §4.4 sob a
    convenção `bar_time ≡ t_origin` (P12).
    """
    _, ledger = _run_pipeline(synthetic_df)
    assert (ledger['bar_time'] < ledger['t_creation']).all()


def test_smoke_wave6_parsed_high_low_inversion(synthetic_df):
    """Pine linhas 127-128 — velas high-volatility (HL >= 2 * volatility)
    invertem parsed_high/parsed_low.

    Smoke direto sobre o helper `_compute_parsed_high_low`: constrói
    um DataFrame curto cujo último candle tem H-L manifestamente
    grande comparado ao ATR aproximado da janela, e verifica que
    parsed_high == low e parsed_low == high naquele candle.

    NOTA: usa atr_length=14 (sem aguardar 200 candles para o ATR
    estabilizar) — `_compute_parsed_high_low` é vetorizado sobre o
    DataFrame inteiro, e atr_length só afeta a fórmula do
    volatility, não o algoritmo.
    """
    # Constrói série calma de 30 candles (range ~1) seguida de 1
    # candle high-volatility (range = 10) — manifestamente >= 2 *
    # ATR pequeno.
    n = 30
    base_price = 100.0
    df = pd.DataFrame({
        'open': [base_price] * n,
        'high': [base_price + 0.5] * n,
        'low': [base_price - 0.5] * n,
        'close': [base_price] * n,
    })
    df.loc[n - 1, 'high'] = 110.0
    df.loc[n - 1, 'low'] = 100.0

    parsed_high, parsed_low = _compute_parsed_high_low(
        df, ob_filter='Atr', atr_length=14,
    )
    last = n - 1
    assert parsed_high.iloc[last] == df.loc[last, 'low']
    assert parsed_low.iloc[last] == df.loc[last, 'high']
    # Sanity: candles não-high-volatility não invertem.
    assert parsed_high.iloc[last - 1] == df.loc[last - 1, 'high']
    assert parsed_low.iloc[last - 1] == df.loc[last - 1, 'low']


def test_smoke_wave6_co_mitigation(synthetic_df_co_mit):
    """Invariante 13 — múltiplos OBs do mesmo (scope, direction)
    mitigados no mesmo candle.

    Fixture estendida com fase 6: candle de drop sharp onde low
    fura bar_low de ≥2 bullish swing OBs simultaneamente.
    """
    df_out, ledger = _run_pipeline(synthetic_df_co_mit, mitigation='Wick')

    co_mit_candles = df_out.index[df_out['ob_swing_bullish_mitigated']]
    found_co_mitigation = False
    for Z in co_mit_candles:
        ts_Z = df_out.loc[Z, 'date']
        co_mit_obs = ledger.query(
            "scope == 'swing' and bias == @BULLISH "
            "and t_mitigation == @ts_Z"
        )
        if len(co_mit_obs) >= 2:
            found_co_mitigation = True
            assert df_out.loc[Z, 'ob_swing_bullish_mitigated']
            assert (co_mit_obs['t_mitigation'] == ts_Z).all()
    assert found_co_mitigation, (
        'Fixture deve gerar >=1 candle de co-mitigação SWING bullish '
        '(invariante 13). Ajustar fase 6 da fixture, não os asserts.'
    )
