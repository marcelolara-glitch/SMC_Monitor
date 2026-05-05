"""
OBJETIVO
    Smoke test da Onda 2: prova que os 8 operadores stateless do
    `smc_engine.operators` são vetorizados, NaN-safe nas bordas
    declaradas, anti-lookahead em `cross_over`/`cross_under` e
    matematicamente fiéis ao Pine fonte.

FONTE DE DADOS
    Sintética: pequenas Series construídas à mão dentro de cada teste,
    de modo que o resultado esperado seja calculável manualmente e
    auditável linha a linha contra a fórmula declarada na docstring
    do operador correspondente em smc_engine/operators.py.

LIMITAÇÕES CONHECIDAS
    Não testa contra dataset real do Pine — validação cruzada com
    Pine real fica para a Onda 9 (Verificação Freqtrade §3).
    `cum_sum` é coberto apenas em comportamento básico (incluindo a
    propagação de NaN explicitamente listada como limitação conhecida).

NÃO FAZER
    Não usar este teste como prova de equivalência total ao Pine —
    é smoke, não golden. Equivalência golden vem na Onda 9.
    Não adicionar dep nova (pandas-ta etc.).
    Não relaxar o teste de anti-lookahead (4.7.2 / 4.8.2): ele é o
    ponto desta onda.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from smc_engine.operators import (
    atr_wilder,
    change,
    cross_over,
    cross_under,
    cum_sum,
    highest,
    lowest,
    true_range,
)


# ============================================================
# 4.1 true_range
# ============================================================

def test_true_range_first_value_is_nan() -> None:
    """ta.tr precisa de close[-1]; primeiro valor é NaN por construção."""
    high = pd.Series([10.0, 11.0, 12.0])
    low = pd.Series([9.0, 10.0, 11.0])
    close = pd.Series([9.5, 10.5, 11.5])
    tr = true_range(high, low, close)
    assert np.isnan(tr.iloc[0])


def test_true_range_matches_manual_formula() -> None:
    """5 candles à mão; TR = max(H-L, |H-close[-1]|, |L-close[-1]|)."""
    high = pd.Series([10.0, 12.0, 11.0, 13.0, 14.0])
    low = pd.Series([9.0, 10.5, 10.0, 11.0, 12.5])
    close = pd.Series([9.5, 11.0, 10.5, 12.5, 13.0])
    tr = true_range(high, low, close)

    assert np.isnan(tr.iloc[0])
    # i=1: H-L=1.5, |H-close[0]|=|12-9.5|=2.5, |L-close[0]|=|10.5-9.5|=1.0
    assert tr.iloc[1] == 2.5
    # i=2: H-L=1.0, |11-11|=0,    |10-11|=1.0
    assert tr.iloc[2] == 1.0
    # i=3: H-L=2.0, |13-10.5|=2.5, |11-10.5|=0.5
    assert tr.iloc[3] == 2.5
    # i=4: H-L=1.5, |14-12.5|=1.5, |12.5-12.5|=0
    assert tr.iloc[4] == 1.5


def test_true_range_captures_overnight_gap() -> None:
    """Gap up: H=110, L=109, close[-1]=100 -> TR=10 (não 1)."""
    high = pd.Series([100.0, 110.0])
    low = pd.Series([99.0, 109.0])
    close = pd.Series([100.0, 109.5])
    tr = true_range(high, low, close)
    assert tr.iloc[1] == 10.0


# ============================================================
# 4.2 atr_wilder
# ============================================================

def _ohlc_constant_tr(n: int, tr_value: float) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Helper: gera 3 series (H,L,C) tais que TR é constante = tr_value
    em todos os índices a partir de i=1.

    Construção: close[i] = close[i-1], high[i] = close[i] + tr/2,
    low[i] = close[i] - tr/2 -> H-L = tr e |H-C[-1]| = |L-C[-1]| = tr/2.
    """
    close = pd.Series([100.0] * n)
    high = close + tr_value / 2.0
    low = close - tr_value / 2.0
    return high, low, close


def test_atr_wilder_first_n_minus_1_are_nan() -> None:
    """Com length=14, primeiros 13 valores NaN; primeiro válido em i=13.

    Decorre da fórmula em §3.2: SMA inicial em `tr.iloc[1:length]`
    (length-1 valores válidos) atribuída a `atr.iloc[length-1]`.
    """
    high, low, close = _ohlc_constant_tr(20, tr_value=2.0)
    atr = atr_wilder(high, low, close, length=14)
    for i in range(13):
        assert np.isnan(atr.iloc[i]), f"atr[{i}] deveria ser NaN"
    assert not np.isnan(atr.iloc[13])


def test_atr_wilder_first_value_is_sma_of_tr() -> None:
    """Primeiro valor não-NaN = média dos TR válidos iniciais.

    Conforme implementação verbatim de §3.2:
        atr.iloc[length - 1] = tr.iloc[1:length].mean()
    """
    n = 20
    length = 14
    high = pd.Series(np.linspace(10.0, 30.0, n))
    low = pd.Series(np.linspace(9.0, 28.0, n))
    close = pd.Series(np.linspace(9.5, 29.0, n))

    tr = true_range(high, low, close)
    atr = atr_wilder(high, low, close, length=length)

    expected_first = tr.iloc[1:length].mean()
    assert np.isclose(atr.iloc[length - 1], expected_first)


def test_atr_wilder_recursive_formula() -> None:
    """Segundo valor não-NaN segue (atr_anterior * (N-1) + tr_atual) / N."""
    n = 20
    length = 14
    high = pd.Series(np.linspace(10.0, 30.0, n))
    low = pd.Series(np.linspace(9.0, 28.0, n))
    close = pd.Series(np.linspace(9.5, 29.0, n))

    tr = true_range(high, low, close)
    atr = atr_wilder(high, low, close, length=length)

    expected_second = (atr.iloc[length - 1] * (length - 1) + tr.iloc[length]) / length
    assert np.isclose(atr.iloc[length], expected_second)


def test_atr_wilder_constant_series_converges() -> None:
    """TR constante = K -> ATR(K, ...) também = K em todo índice válido."""
    K = 2.0
    length = 14
    n = 30
    high, low, close = _ohlc_constant_tr(n, tr_value=K)
    atr = atr_wilder(high, low, close, length=length)

    for i in range(length - 1, n):
        assert np.isclose(atr.iloc[i], K), f"atr[{i}] = {atr.iloc[i]}, esperado {K}"


def test_atr_wilder_preserves_index_and_length() -> None:
    """Output tem mesmo len() e mesmo index do input."""
    idx = pd.date_range("2024-01-01", periods=20, freq="h")
    high = pd.Series(np.linspace(10.0, 30.0, 20), index=idx)
    low = pd.Series(np.linspace(9.0, 28.0, 20), index=idx)
    close = pd.Series(np.linspace(9.5, 29.0, 20), index=idx)
    atr = atr_wilder(high, low, close, length=14)
    assert len(atr) == 20
    assert atr.index.equals(idx)


# ============================================================
# 4.3 cum_sum
# ============================================================

def test_cum_sum_basic() -> None:
    """[1,2,3,4] -> [1,3,6,10]."""
    s = pd.Series([1.0, 2.0, 3.0, 4.0])
    expected = pd.Series([1.0, 3.0, 6.0, 10.0])
    pd.testing.assert_series_equal(cum_sum(s), expected)


def test_cum_sum_propagates_nan() -> None:
    """[1, NaN, 3] -> [1, NaN, NaN]. Documenta limitação (vs Pine ignora)."""
    s = pd.Series([1.0, np.nan, 3.0])
    result = cum_sum(s)
    assert result.iloc[0] == 1.0
    assert np.isnan(result.iloc[1])
    assert np.isnan(result.iloc[2])


# ============================================================
# 4.4 highest
# ============================================================

def test_highest_first_n_minus_1_are_nan() -> None:
    """length=3 -> primeiros 2 valores NaN."""
    s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    h = highest(s, length=3)
    assert np.isnan(h.iloc[0])
    assert np.isnan(h.iloc[1])
    assert not np.isnan(h.iloc[2])


def test_highest_monotonic_series() -> None:
    """Crescente [1..5], length=3 -> [NaN, NaN, 3, 4, 5]."""
    s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    h = highest(s, length=3)
    assert np.isnan(h.iloc[0])
    assert np.isnan(h.iloc[1])
    assert h.iloc[2] == 3.0
    assert h.iloc[3] == 4.0
    assert h.iloc[4] == 5.0


def test_highest_peak_in_middle() -> None:
    """[1,5,2,3,1] length=3 -> pico 5 aparece nas janelas que o cobrem."""
    s = pd.Series([1.0, 5.0, 2.0, 3.0, 1.0])
    h = highest(s, length=3)
    assert np.isnan(h.iloc[0])
    assert np.isnan(h.iloc[1])
    # janelas: [1,5,2]=5, [5,2,3]=5, [2,3,1]=3
    assert h.iloc[2] == 5.0
    assert h.iloc[3] == 5.0
    assert h.iloc[4] == 3.0


# ============================================================
# 4.5 lowest
# ============================================================

def test_lowest_monotonic_series() -> None:
    """Decrescente [5..1], length=3 -> [NaN, NaN, 3, 2, 1]."""
    s = pd.Series([5.0, 4.0, 3.0, 2.0, 1.0])
    low = lowest(s, length=3)
    assert np.isnan(low.iloc[0])
    assert np.isnan(low.iloc[1])
    assert low.iloc[2] == 3.0
    assert low.iloc[3] == 2.0
    assert low.iloc[4] == 1.0


def test_lowest_trough_in_middle() -> None:
    """[5,1,4,3,5] length=3 -> vale 1 nas janelas que o cobrem."""
    s = pd.Series([5.0, 1.0, 4.0, 3.0, 5.0])
    low = lowest(s, length=3)
    assert np.isnan(low.iloc[0])
    assert np.isnan(low.iloc[1])
    # janelas: [5,1,4]=1, [1,4,3]=1, [4,3,5]=3
    assert low.iloc[2] == 1.0
    assert low.iloc[3] == 1.0
    assert low.iloc[4] == 3.0


# ============================================================
# 4.6 change
# ============================================================

def test_change_default_length_one() -> None:
    """[1,3,6,10] -> [NaN, 2, 3, 4]."""
    s = pd.Series([1.0, 3.0, 6.0, 10.0])
    c = change(s)
    assert np.isnan(c.iloc[0])
    assert c.iloc[1] == 2.0
    assert c.iloc[2] == 3.0
    assert c.iloc[3] == 4.0


def test_change_with_length_two() -> None:
    """[1,3,6,10,15] length=2 -> [NaN, NaN, 5, 7, 9]."""
    s = pd.Series([1.0, 3.0, 6.0, 10.0, 15.0])
    c = change(s, length=2)
    assert np.isnan(c.iloc[0])
    assert np.isnan(c.iloc[1])
    assert c.iloc[2] == 5.0
    assert c.iloc[3] == 7.0
    assert c.iloc[4] == 9.0


# ============================================================
# 4.7 cross_over (inclui anti-lookahead)
# ============================================================

def test_cross_over_dispara_no_candle_do_cruzamento() -> None:
    """a=[1,2,3], b=[2,2,2] -> cruzamento em i=2."""
    a = pd.Series([1.0, 2.0, 3.0])
    b = pd.Series([2.0, 2.0, 2.0])
    result = cross_over(a, b)
    assert bool(result.iloc[0]) is False
    assert bool(result.iloc[1]) is False
    assert bool(result.iloc[2]) is True


def test_cross_over_anti_lookahead_nao_dispara_no_candle_anterior() -> None:
    """CRÍTICO: sem .shift(1), result.iloc[1] viraria True (lookahead).

    Se este teste falhar, alguém removeu o `.shift(1)` em cross_over.
    Ler SMC_PRINCIPIOS_E_LEGADO.md §5.3 antes de "consertar".
    """
    a = pd.Series([1.0, 2.0, 3.0])
    b = pd.Series([2.0, 2.0, 2.0])
    result = cross_over(a, b)
    assert bool(result.iloc[1]) is False


def test_cross_over_toque_sem_cruzamento_eh_false() -> None:
    """a=[1,2,1], b=[2,2,2] -> a toca b em i=1 mas não cruza; tudo False."""
    a = pd.Series([1.0, 2.0, 1.0])
    b = pd.Series([2.0, 2.0, 2.0])
    result = cross_over(a, b)
    assert bool(result.iloc[0]) is False
    assert bool(result.iloc[1]) is False
    assert bool(result.iloc[2]) is False


def test_cross_over_com_igualdade_previa() -> None:
    """a=[2,3], b=[2,2]: igualdade em i=0, cruzamento em i=1.

    Valida o `<=` (não `<`) no lado defasado: a[0]=b[0]=2 deve permitir
    o cruzamento ser detectado em i=1.
    """
    a = pd.Series([2.0, 3.0])
    b = pd.Series([2.0, 2.0])
    result = cross_over(a, b)
    assert bool(result.iloc[0]) is False
    assert bool(result.iloc[1]) is True


# ============================================================
# 4.8 cross_under
# ============================================================

def test_cross_under_dispara_no_candle_do_cruzamento() -> None:
    """a=[3,2,1], b=[2,2,2] -> cruzamento para baixo em i=2."""
    a = pd.Series([3.0, 2.0, 1.0])
    b = pd.Series([2.0, 2.0, 2.0])
    result = cross_under(a, b)
    assert bool(result.iloc[0]) is False
    assert bool(result.iloc[1]) is False
    assert bool(result.iloc[2]) is True


def test_cross_under_anti_lookahead_nao_dispara_no_candle_anterior() -> None:
    """CRÍTICO: sem .shift(1), result.iloc[1] viraria True (lookahead).

    Se este teste falhar, alguém removeu o `.shift(1)` em cross_under.
    """
    a = pd.Series([3.0, 2.0, 1.0])
    b = pd.Series([2.0, 2.0, 2.0])
    result = cross_under(a, b)
    assert bool(result.iloc[1]) is False


# ============================================================
# 4.9 Sanidade geral
# ============================================================

def test_operators_preservam_index_da_serie_de_input() -> None:
    """Index customizado (datas) é preservado em atr_wilder e cross_over."""
    idx = pd.date_range("2024-01-01", periods=20, freq="h")
    high = pd.Series(np.linspace(10.0, 30.0, 20), index=idx)
    low = pd.Series(np.linspace(9.0, 28.0, 20), index=idx)
    close = pd.Series(np.linspace(9.5, 29.0, 20), index=idx)

    atr = atr_wilder(high, low, close, length=14)
    assert atr.index.equals(idx)

    a = pd.Series(np.linspace(1.0, 5.0, 20), index=idx)
    b = pd.Series([3.0] * 20, index=idx)
    co = cross_over(a, b)
    assert co.index.equals(idx)


def test_operators_nao_mutam_input() -> None:
    """cum_sum não deve alterar a Series de entrada."""
    s = pd.Series([1.0, 2.0, 3.0, 4.0])
    snapshot = s.copy()
    _ = cum_sum(s)
    pd.testing.assert_series_equal(s, snapshot)
