"""
OBJETIVO
    Smoke test da Onda 7 — Fair Value Gaps com mitigação. Cobre a
    validação isolada do threshold + 7 fases sintéticas + 12 invariantes
    do briefing §4.4 (com separação 11a/11b).

FONTE DE DADOS
    Fixtures sintéticas determinísticas com OHLC fabricado para
    materializar exatamente as condições Pine de cada fase. Não usa
    RandomState — geometria controlada explicitamente para garantir
    detecção/não-detecção determinística e isolar falhas em fixture.

LIMITAÇÕES CONHECIDAS
    Pré-fase de threshold é testada via import privado
    `_compute_threshold` — opção análoga ao
    `test_smoke_wave6_parsed_high_low_inversion` da Wave 6 (que testa
    `_compute_parsed_high_low` privadamente). Justificativa idêntica:
    isolar o cálculo cumulativo dos efeitos colaterais da detecção
    completa.

    Tolerâncias float comparam valores derivados de aritmética OHLC
    com `abs(... - expected) < 1e-9` (`top`, `bottom`). Comparações
    de threshold usam `np.testing.assert_allclose` com rtol=1e-12.

NÃO FAZER
    Não importar de smc_freqtrade.smc_engine — pacote raiz é
    `smc_engine`.
    Não ajustar asserts para acomodar fixture quebrada — ajustar a
    fixture (briefing §5).
    Não pular nenhuma das 12 invariantes — cada uma tem um teste
    dedicado ou é coberta dentro de um teste de lifecycle conjunto.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from smc_engine import (
    BEARISH,
    BULLISH,
    COL_FVG_BEARISH_CREATED,
    COL_FVG_BEARISH_MITIGATED,
    COL_FVG_BULLISH_CREATED,
    COL_FVG_BULLISH_MITIGATED,
    detect_fair_value_gaps,
)
from smc_engine.fvg import _compute_threshold


# ============================================================
# Helpers
# ============================================================

def _make_dates(n: int) -> pd.Series:
    """Datas em epoch ms (Int64), step 4h — padrão Wave 6."""
    return (
        pd.date_range('2026-01-01', periods=n, freq='4h')
        .astype('int64') // 10**6
    )


def _df_from_rows(
    rows: list[tuple[float, float, float, float]],
) -> pd.DataFrame:
    opens, highs, lows, closes = zip(*rows)
    return pd.DataFrame({
        'open': list(opens),
        'high': list(highs),
        'low': list(lows),
        'close': list(closes),
        'date': _make_dates(len(rows)),
    })


# ============================================================
# Pré-fase — Validação isolada do threshold (briefing §4.5,
# resolve item A2)
# ============================================================

def test_smoke_wave7_threshold_isolated():
    """`_compute_threshold` reproduz Pine linha 287 bit-a-bit.

    Fixture mínima de 5 candles com `barDeltaPercent` computado
    manualmente. Edge case `bar_index=0` clamped (threshold[0]=0,
    sem divisão por zero).
    """
    opens = pd.Series([100.0, 100.5, 101.0, 100.7, 102.0])
    closes = pd.Series([100.5, 101.0, 100.7, 102.0, 102.3])

    # barDeltaPercent[i] = (close[i-1] - open[i-1]) / (open[i-1] * 100)
    expected_delta = np.array([
        np.nan,
        (100.5 - 100.0) / (100.0 * 100),
        (101.0 - 100.5) / (100.5 * 100),
        (100.7 - 101.0) / (101.0 * 100),
        (102.0 - 100.7) / (100.7 * 100),
    ])
    expected_abs = np.where(
        np.isnan(expected_delta), 0.0, np.abs(expected_delta),
    )
    expected_cum = np.cumsum(expected_abs)
    # bar_index_clamped: [1, 1, 2, 3, 4]
    expected_div = np.array([1.0, 1.0, 2.0, 3.0, 4.0])
    expected_threshold = expected_cum / expected_div * 2.0

    actual = _compute_threshold(opens, closes, auto_threshold=True)
    np.testing.assert_allclose(actual, expected_threshold, rtol=1e-12)

    # Edge case bar_index=0 clamped → threshold[0]=0 (cum começa em 0).
    assert actual[0] == 0.0

    # auto_threshold=False produz zeros.
    zeros = _compute_threshold(opens, closes, auto_threshold=False)
    assert len(zeros) == 5
    assert np.all(zeros == 0.0)


# ============================================================
# Fixtures sintéticas
# ============================================================

@pytest.fixture
def synthetic_df_bullish() -> pd.DataFrame:
    """Fixture primária — cobre Fases 1, 2, 3, 5, 7 + invariantes
    1-11a.

    Estrutura:
        idx 0-9    (Fase 1):    baseline calmo ~100, sem FVG.
        idx 10-12  (Fase 2):    bullish FVG 1, gap [100.5, 100.7].
        idx 15-17  (Fase 2):    bullish FVG 2, gap [105.5, 106.0].
        idx 18-21:              filler estável ~109.
        idx 22     (Fase 7):    drop sharp (low=95) mitiga FVG 1 e 2
                                simultaneamente.
        idx 24-26  (Fase 5):    bullish FVG 3 minúsculo (gap
                                [96.30, 96.32]) com `barDeltaPercent`
                                pequeno que o threshold cumulativo
                                filtra (presente em False, ausente
                                em True).
        idx 27-30:              filler.
    """
    rows: list[tuple[float, float, float, float]] = []
    # 0-9 baseline: candles narrow ~100.0, sem padrão de 3 candles
    # válido (sem gap geométrico).
    for i in range(10):
        base = 100.0 + i * 0.02
        rows.append((base, base + 0.3, base - 0.3, base + 0.1))

    # 10 (t-2 FVG1): high=100.5
    rows.append((100.2, 100.5, 99.5, 99.7))
    # 11 (t-1 FVG1): BIG BULLISH, close=104.0 > high[10]=100.5
    rows.append((99.7, 104.5, 99.5, 104.0))
    # 12 (t FVG1): low=100.7 > high[10]=100.5
    rows.append((104.0, 105.0, 100.7, 104.5))

    # 13-14 filler.
    rows.append((104.5, 104.8, 104.3, 104.6))
    rows.append((104.6, 104.9, 104.4, 104.7))

    # 15 (t-2 FVG2): high=105.5
    rows.append((104.7, 105.5, 104.6, 104.8))
    # 16 (t-1 FVG2): BIG BULLISH, close=109.0 > high[15]=105.5
    rows.append((104.8, 109.5, 104.6, 109.0))
    # 17 (t FVG2): low=106.0 > high[15]=105.5
    rows.append((109.0, 110.0, 106.0, 109.5))

    # 18-21 filler estável.
    rows.append((109.5, 109.8, 109.3, 109.6))
    rows.append((109.6, 109.9, 109.4, 109.7))
    rows.append((109.7, 109.9, 109.5, 109.8))
    rows.append((109.8, 109.95, 109.6, 109.85))

    # 22 sharp drop — mitiga FVG1 (bottom=100.5) e FVG2 (bottom=105.5).
    rows.append((109.85, 110.0, 95.0, 96.0))

    # 23 filler depois do drop.
    rows.append((96.0, 96.4, 95.8, 96.1))

    # 24 (t-2 FVG3 pequeno): high=96.30
    rows.append((96.10, 96.30, 95.95, 96.20))
    # 25 (t-1 FVG3): TINY bullish, close=96.31 > high[24]=96.30
    rows.append((96.20, 96.32, 96.18, 96.31))
    # 26 (t FVG3): low=96.32 > high[24]=96.30 — gap [96.30, 96.32]
    rows.append((96.31, 96.40, 96.32, 96.38))

    # 27-30 filler.
    for _ in range(4):
        rows.append((96.30, 96.50, 96.20, 96.35))

    return _df_from_rows(rows)


@pytest.fixture
def synthetic_df_bearish() -> pd.DataFrame:
    """Fase 4 — bearish FVG criado e ativo.

    idx 0-9:    baseline calmo ~100.
    idx 10-12:  bearish FVG, gap [98.5, 99.0].
    idx 13-29:  filler ~94, high nunca > 99.0 → FVG permanece active.
    """
    rows: list[tuple[float, float, float, float]] = []
    for i in range(10):
        base = 100.0 - i * 0.02
        rows.append((base, base + 0.3, base - 0.3, base - 0.1))

    # 10 (t-2): low=99.0
    rows.append((99.7, 99.9, 99.0, 99.8))
    # 11 (t-1): BIG BEARISH, close=95.0 < low[10]=99.0
    rows.append((99.8, 99.9, 94.5, 95.0))
    # 12 (t): high=98.5 < low[10]=99.0
    rows.append((95.0, 98.5, 94.5, 94.8))

    # 13-29: stable around 94, high <= 95.0 → FVG ativo.
    for _ in range(17):
        rows.append((94.5, 95.0, 94.0, 94.7))

    return _df_from_rows(rows)


@pytest.fixture
def synthetic_df_no_create_mid_candle() -> pd.DataFrame:
    """Fase 6 — gap geométrico falha pela condição do candle do meio.

    idx 0-9:    baseline calmo.
    idx 10-12:  low[12] > high[10] geometricamente, mas
                close[11] == high[10] (tangenciamento exato, falha o
                strict > do Pine: `close[t-1] > high[t-2]`).

    Sem CREATE bullish nesse padrão.
    """
    rows: list[tuple[float, float, float, float]] = []
    for i in range(10):
        base = 100.0 + i * 0.02
        rows.append((base, base + 0.3, base - 0.3, base + 0.1))

    # 10 (t-2): high=100.50
    rows.append((100.2, 100.50, 99.5, 99.7))
    # 11 (t-1): close == high[10] exatamente — falha `close > high[10]`.
    rows.append((99.7, 100.50, 99.5, 100.50))
    # 12 (t): low=100.60 > high[10]=100.50 (geométrico OK), mas pine
    # exige close[t-1] > high[t-2] estritamente. close[11]=100.50 ==
    # high[10]=100.50 → condição falha → SEM FVG.
    rows.append((100.50, 101.0, 100.60, 100.80))

    # 13-29 filler.
    for _ in range(17):
        rows.append((100.5, 100.8, 100.3, 100.6))

    return _df_from_rows(rows)


@pytest.fixture
def synthetic_df_opposite_co_mit() -> pd.DataFrame:
    """Invariante 11b — bullish e bearish mitigados no MESMO candle Z.

    Cria bullish FVG abaixo (bottom~100), bearish FVG acima
    (top~120), depois candle outside-bar com low<100 e high>120 que
    mitiga ambos simultaneamente. Verifica coexistência de
    BULLISH_MITIGATED[Z] e BEARISH_MITIGATED[Z] como True.
    """
    rows: list[tuple[float, float, float, float]] = []
    # 0-9 baseline mid-range ~108.
    for i in range(10):
        base = 108.0 + i * 0.02
        rows.append((base, base + 0.3, base - 0.3, base + 0.1))

    # 10 (t-2 bullish): high=100.5 (vela cai p/ baixo)
    rows.append((108.2, 108.4, 99.5, 99.7))
    # 11 (t-1 bullish): BIG bullish que sobe a 104
    rows.append((99.7, 104.5, 99.5, 104.0))
    # 12 (t bullish): low=100.7 > high[10]=100.5
    rows.append((104.0, 110.0, 100.7, 109.0))
    # Bullish FVG: bottom=100.5, top=100.7

    # 13 filler.
    rows.append((109.0, 115.0, 108.8, 114.5))

    # 14 (t-2 bearish): low=120.0 (vela sobe alto)
    rows.append((114.5, 121.0, 120.0, 120.5))
    # 15 (t-1 bearish): BIG bearish que cai p/ 115
    rows.append((120.5, 121.0, 114.5, 115.0))
    # 16 (t bearish): high=119.5 < low[14]=120.0
    rows.append((115.0, 119.5, 110.0, 111.0))
    # Bearish FVG: bottom=119.5, top=120.0

    # 17-19 filler estável ~111.
    rows.append((111.0, 111.5, 110.8, 111.2))
    rows.append((111.2, 111.5, 111.0, 111.3))
    rows.append((111.3, 111.5, 111.0, 111.2))

    # 20 OUTSIDE BAR: low < 100.5 (mitiga bullish) AND
    # high > 120.0 (mitiga bearish). Wave 7 valida ambas no mesmo Z.
    rows.append((111.2, 125.0, 95.0, 105.0))

    # 21-25 filler.
    for _ in range(5):
        rows.append((105.0, 106.0, 104.0, 105.5))

    return _df_from_rows(rows)


# ============================================================
# Tests — Fases 1 a 7
# ============================================================

def test_smoke_wave7_phase1_baseline_no_fvg(synthetic_df_bullish):
    """Fase 1 — primeiros 10 candles do baseline não emitem FVG."""
    df_out, _ = detect_fair_value_gaps(synthetic_df_bullish)
    early = df_out.iloc[:10]
    assert not early[COL_FVG_BULLISH_CREATED].any()
    assert not early[COL_FVG_BEARISH_CREATED].any()


def test_smoke_wave7_phase2_bullish_created(synthetic_df_bullish):
    """Fase 2 — padrão idx 10-12 cria bullish FVG ativo (antes da
    mitigação)."""
    df_out, ledger = detect_fair_value_gaps(synthetic_df_bullish)
    expected_t = synthetic_df_bullish['date'].iloc[12]
    fvg1 = ledger.query(
        "bias == @BULLISH and t_creation == @expected_t"
    )
    assert len(fvg1) == 1
    record = fvg1.iloc[0]
    # Storage normalizado: top > bottom (briefing §4.4 invariante 1).
    assert record['top'] > record['bottom']
    # Geometria: bottom = high[10] = 100.5, top = low[12] = 100.7.
    assert abs(record['bottom'] - 100.5) < 1e-9
    assert abs(record['top'] - 100.7) < 1e-9
    # bar_time = date[10] (t-2), t_creation = date[12].
    assert record['bar_time'] == synthetic_df_bullish['date'].iloc[10]
    assert record['t_creation'] == expected_t


def test_smoke_wave7_phase3_bullish_mitigated(synthetic_df_bullish):
    """Fase 3 — bullish FVG mitigado pelo drop em idx 22.

    Cobre invariantes 9 (t_mitigation > t_creation) e 4 (state).
    """
    df_out, ledger = detect_fair_value_gaps(synthetic_df_bullish)
    expected_t_creation = synthetic_df_bullish['date'].iloc[12]  # noqa: F841 (usado em .query)
    expected_mit = synthetic_df_bullish['date'].iloc[22]
    fvg1 = ledger.query(
        "bias == @BULLISH and t_creation == @expected_t_creation"
    ).iloc[0]
    assert fvg1['state'] == 'mitigated'
    assert fvg1['t_mitigation'] == expected_mit
    assert fvg1['t_mitigation'] > fvg1['t_creation']
    # Bool agregado per-candle no idx 22.
    assert df_out[COL_FVG_BULLISH_MITIGATED].iloc[22]


def test_smoke_wave7_phase4_bearish_active(synthetic_df_bearish):
    """Fase 4 — bearish FVG criado e ativo até fim da janela."""
    _, ledger = detect_fair_value_gaps(synthetic_df_bearish)
    expected_t_creation = synthetic_df_bearish['date'].iloc[12]  # noqa: F841 (usado em .query)
    fvg = ledger.query(
        "bias == @BEARISH and t_creation == @expected_t_creation"
    )
    assert len(fvg) == 1
    record = fvg.iloc[0]
    assert record['state'] == 'active'
    assert pd.isna(record['t_mitigation'])
    # Storage normalizado: top > bottom.
    assert record['top'] > record['bottom']
    # bottom = high[12] = 98.5, top = low[10] = 99.0.
    assert abs(record['bottom'] - 98.5) < 1e-9
    assert abs(record['top'] - 99.0) < 1e-9


def test_smoke_wave7_phase5_auto_threshold_false_strictly_more(
    synthetic_df_bullish,
):
    """Fase 5 — `auto_threshold=False` detecta estritamente mais FVGs
    do que True; ao menos 1 FVG exclusivo no modo False.

    Briefing §5 fase 5: invariante de diferenciação garante que o
    parâmetro não está sendo ignorado.
    """
    _, ledger_true = detect_fair_value_gaps(
        synthetic_df_bullish, auto_threshold=True,
    )
    _, ledger_false = detect_fair_value_gaps(
        synthetic_df_bullish, auto_threshold=False,
    )
    assert len(ledger_false) > len(ledger_true), (
        f'auto_threshold=False ({len(ledger_false)}) deve detectar '
        f'estritamente mais FVGs que True ({len(ledger_true)}). '
        'Fixture deve conter ao menos 1 FVG pequeno cujo '
        'barDeltaPercent fique abaixo do threshold cumulativo.'
    )
    key_cols = ['bias', 't_creation', 'top', 'bottom']
    keys_true = set(map(tuple, ledger_true[key_cols].values))
    keys_false = set(map(tuple, ledger_false[key_cols].values))
    only_false = keys_false - keys_true
    assert len(only_false) >= 1, (
        '≥1 FVG deve aparecer exclusivamente no modo False. '
        'Verificar que o FVG pequeno (idx 24-26) é filtrado por '
        'threshold em True mas passa em False.'
    )


def test_smoke_wave7_phase6_no_create_strict_mid_candle(
    synthetic_df_no_create_mid_candle,
):
    """Fase 6 — gap geométrico falha porque `close[t-1] > high[t-2]`
    é tangenciamento (==) e Pine exige strict >.

    Não emite FVG no padrão idx 10-12 nem em qualquer outro candle.
    """
    _, ledger = detect_fair_value_gaps(synthetic_df_no_create_mid_candle)
    assert len(ledger) == 0


def test_smoke_wave7_phase7_co_mitigation(synthetic_df_bullish):
    """Fase 7 — drop sharp em idx 22 mitiga ≥2 bullish FVGs.

    Cobre invariante 11a: múltiplos FVGs mitigados no mesmo candle Z
    compartilham `t_mitigation = ts(Z)` exatamente.
    """
    df_out, ledger = detect_fair_value_gaps(synthetic_df_bullish)
    ts_Z = synthetic_df_bullish['date'].iloc[22]
    co_mit = ledger.query(
        "bias == @BULLISH and t_mitigation == @ts_Z"
    )
    assert len(co_mit) >= 2, (
        f'Esperado ≥2 bullish FVGs mitigados em idx 22 (ts={ts_Z}); '
        f'encontrado {len(co_mit)}'
    )
    # Invariante 11a: t_mitigation idêntico para todos.
    assert (co_mit['t_mitigation'] == ts_Z).all()
    # Bool per-candle agregado.
    assert df_out[COL_FVG_BULLISH_MITIGATED].iloc[22]


# ============================================================
# Tests — Invariantes
# ============================================================

def test_smoke_wave7_invariants_universal(synthetic_df_bullish):
    """Invariantes universais sobre o ledger (1, 2, 3, 4, 5, 6, 7, 8).

    1 — top > bottom (gap não-degenerado).
    2 — bias ∈ {BULLISH, BEARISH}.
    3 — state ∈ {'active', 'mitigated'}.
    4 — state='active' ⇔ t_mitigation is pd.NaT.
    5 — t_invalidation is pd.NaT para todos.
    6 — is_inverse == False para todos.
    7 — is_double == False para todos.
    8 — t_creation - bar_time = 2 candles (deslocamento estrito).
    """
    _, ledger = detect_fair_value_gaps(synthetic_df_bullish)
    assert len(ledger) > 0, 'Fixture deve produzir ≥1 FVG.'

    # 1 — top > bottom.
    assert (ledger['top'] > ledger['bottom']).all()

    # 2 — bias ∈ {±1}.
    assert set(ledger['bias'].unique()).issubset({BULLISH, BEARISH})

    # 3 — state ∈ {'active', 'mitigated'}.
    assert set(ledger['state'].unique()).issubset({'active', 'mitigated'})

    # 4 — state='active' ⇔ t_mitigation is pd.NaT.
    active_mask = ledger['state'] == 'active'
    mit_nat_mask = ledger['t_mitigation'].isna()
    assert active_mask.eq(mit_nat_mask).all()

    # 5 — t_invalidation sempre pd.NaT em Wave 7.
    assert ledger['t_invalidation'].isna().all()

    # 6, 7 — hooks Onda 7.1 / 7.2 sempre False.
    assert (ledger['is_inverse'] == False).all()  # noqa: E712
    assert (ledger['is_double'] == False).all()  # noqa: E712

    # 8 — t_creation - bar_time = 2 candles. Deriva o passo do
    # próprio DataFrame (unit do `date` pode ser seg, ms ou ns
    # dependendo do build pandas; o relacionamento `2 * step` é
    # invariante).
    candle_step = (
        synthetic_df_bullish['date'].iloc[1]
        - synthetic_df_bullish['date'].iloc[0]
    )
    diff = ledger['t_creation'] - ledger['bar_time']
    assert (diff == 2 * candle_step).all()


def test_smoke_wave7_invariant9_strict_mitigation_after_creation(
    synthetic_df_bullish,
):
    """Invariante 9 — `t_mitigation > t_creation` estrito para todo
    FVG mitigado. Corolário (invariante 10): CREATE×MITIGATE no
    mesmo candle é impossível por construção.
    """
    _, ledger = detect_fair_value_gaps(synthetic_df_bullish)
    mitigated = ledger.dropna(subset=['t_mitigation'])
    assert len(mitigated) >= 1, 'Fixture deve produzir ≥1 mitigação.'
    assert (mitigated['t_mitigation'] > mitigated['t_creation']).all()


def test_smoke_wave7_invariant10_no_create_and_mit_same_candle(
    synthetic_df_bullish,
):
    """Invariante 10 — mutual exclusion CREATE×MITIGATE no mesmo
    candle no MESMO FVG (corolário de invariante 9).

    Nenhuma linha do ledger tem `t_mitigation == t_creation`.
    """
    _, ledger = detect_fair_value_gaps(synthetic_df_bullish)
    same_candle = ledger['t_mitigation'] == ledger['t_creation']
    # NaT == NaT é False em pandas; só candidatos válidos são checados.
    assert not same_candle.any()


def test_smoke_wave7_invariant11b_opposite_co_mit(
    synthetic_df_opposite_co_mit,
):
    """Invariante 11b — `COL_FVG_BULLISH_MITIGATED[Z]` e
    `COL_FVG_BEARISH_MITIGATED[Z]` podem coexistir como True no mesmo
    candle Z (direções opostas mitigam simultaneamente).

    Resolve item A4 do briefing §11.
    """
    df_out, ledger = detect_fair_value_gaps(synthetic_df_opposite_co_mit)

    # Localiza candle Z em que ambas flags são True.
    both = (
        df_out[COL_FVG_BULLISH_MITIGATED]
        & df_out[COL_FVG_BEARISH_MITIGATED]
    )
    assert both.any(), (
        'Fixture opposite_co_mit deve produzir ≥1 candle com bullish '
        'e bearish mitigated simultâneos. Ajustar fixture, não asserts.'
    )

    Z_pos = int(both.to_numpy().argmax())
    z_ts = df_out['date'].iloc[Z_pos]  # noqa: F841 (usado em .query)

    bull_mit_Z = ledger.query(
        "bias == @BULLISH and t_mitigation == @z_ts"
    )
    bear_mit_Z = ledger.query(
        "bias == @BEARISH and t_mitigation == @z_ts"
    )
    assert len(bull_mit_Z) >= 1
    assert len(bear_mit_Z) >= 1


def test_smoke_wave7_create_count_matches_ledger(synthetic_df_bullish):
    """Sanity: contagem das booleans CREATED bate com contagem do
    ledger por bias. Análogo à invariante 1 da Wave 6 (re-emissão
    controlada).
    """
    df_out, ledger = detect_fair_value_gaps(synthetic_df_bullish)
    for bias_const, col in (
        (BULLISH, COL_FVG_BULLISH_CREATED),
        (BEARISH, COL_FVG_BEARISH_CREATED),
    ):
        count_df = int(df_out[col].sum())
        count_ledger = int((ledger['bias'] == bias_const).sum())
        assert count_df == count_ledger, (
            f'{col}: df={count_df} vs ledger={count_ledger}'
        )
