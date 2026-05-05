"""
OBJETIVO
    Portagem Python pura, stateless e vetorizada em pandas dos 8
    operadores `ta.*` que o LuxAlgo SMC consome. Funções deste módulo
    são a fundação matemática consumida pelas Ondas 3-9.

    Os 8 operadores aqui implementados foram derivados por auditoria
    direta (`grep -nE 'ta\\.[a-zA-Z_]+'`) sobre o fonte
    tools/pynecore-validation/luxalgo_smc_compute_only.py:

        ta.tr        -> true_range          (linha 114 do Pine)
        ta.atr       -> atr_wilder          (linha 113)
        ta.cum       -> cum_sum             (linhas 114, 276)
        ta.highest   -> highest             (linha 127)
        ta.lowest    -> lowest              (linha 128)
        ta.change    -> change              (linhas 136, 139, 142)
        ta.crossover -> cross_over          (linha 236)
        ta.crossunder-> cross_under         (linha 250)

FONTE DE DADOS
    Cada operador recebe `pd.Series` e devolve `pd.Series` com mesmo
    índice e comprimento. NaN onde a janela ou shift não preenchem.
    Não consome dados externos; é puro sobre os argumentos.

LIMITAÇÕES CONHECIDAS
    Não valida que as Series compartilham o mesmo índice (assume isso,
    como faz o Pine com séries do mesmo símbolo/TF).
    `atr_wilder` tem um loop Python por ser recursivo (Wilder); demais
    operadores são totalmente vetorizados.
    `cum_sum` propaga NaN (Pine ignoraria).

NÃO FAZER
    Não introduzir `pandas-ta` ou outras deps — pandas/numpy entram
    apenas como deps transitivas do Freqtrade.
    Não remover `.shift(1)` em `cross_over`/`cross_under` — sem ele
    a função vira teste de estado, não de transição (lookahead).
    Não adicionar operadores fora desta lista nem omitir operadores
    desta lista.
    Não adicionar lógica SMC; este módulo é apenas matemática.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def true_range(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
) -> pd.Series:
    """
    OBJETIVO
        True Range clássico (Wilder, 1978). Para cada candle:
        max(H - L, |H - close[-1]|, |L - close[-1]|).

    FONTE DE DADOS
        3 Series pandas com mesmo índice (high, low, close de OHLCV).

    LIMITAÇÕES CONHECIDAS
        Primeiro valor é NaN (precisa de close[-1]).
        Não valida que as 3 Series têm o mesmo índice — assume isso.

    NÃO FAZER
        Não usar `(high - low)` como aproximação — perde gaps overnight.
    """
    prev_close = close.shift(1)
    # skipna=False garante que o primeiro candle (close[-1] ausente)
    # produz NaN — Pine `ta.tr(false)` (default) tem essa semântica.
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1, skipna=False)
    return tr


def atr_wilder(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    length: int = 14,
) -> pd.Series:
    """
    OBJETIVO
        Average True Range com smoothing Wilder (RMA), idêntico a
        `ta.atr(N)` do Pine Script.

    FONTE DE DADOS
        3 Series pandas com mesmo índice. `length` é o período Wilder.

    LIMITAÇÕES CONHECIDAS
        Os primeiros (length - 1) valores são NaN; primeiro valor
        válido aparece no índice posicional `length - 1`, calculado
        como SMA do TR sobre `tr.iloc[1:length]`. A partir daí, o
        smoothing recursivo Wilder produz cada valor.
        Implementação manual (não usa `.ewm()`) por escolha de
        legibilidade — fórmula auditável linha a linha.

    NÃO FAZER
        Não substituir por SMA do TR — Pine usa Wilder.
        Não usar `.ewm(alpha=1/length)` sem revisão — apesar de
        matematicamente equivalente, foge da forma auditável escolhida.
    """
    tr = true_range(high, low, close)
    atr = pd.Series(np.nan, index=tr.index, dtype=float)
    if len(tr) >= length:
        first_idx = length  # posicional
        atr.iloc[first_idx - 1] = tr.iloc[1:first_idx].mean()
        for i in range(first_idx, len(tr)):
            atr.iloc[i] = (atr.iloc[i - 1] * (length - 1) + tr.iloc[i]) / length
    return atr


def cum_sum(series: pd.Series) -> pd.Series:
    """
    OBJETIVO
        Soma cumulativa do início ao candle atual, idêntico a `ta.cum(x)`
        do Pine.

    FONTE DE DADOS
        Series pandas qualquer (numérica).

    LIMITAÇÕES CONHECIDAS
        NaN no input quebra a soma cumulativa (NaN propaga). Pine
        ignora NaN; aqui propaga. Para Onda 2 isso é aceito — os
        consumidores conhecidos (Pine `ta.cum(ta.tr)` e
        `ta.cum(math.abs(...))`) recebem séries onde o NaN inicial é
        esperado.

    NÃO FAZER
        Não usar `.fillna(0)` antes — muda semântica.
    """
    # skipna=False garante propagação real de NaN (default seria pular).
    return series.cumsum(skipna=False)


def highest(series: pd.Series, length: int) -> pd.Series:
    """
    OBJETIVO
        Máximo da série nas últimas `length` observações (rolling max),
        idêntico a `ta.highest(N)` do Pine.

    FONTE DE DADOS
        Series pandas numérica.

    LIMITAÇÕES CONHECIDAS
        Os primeiros (length - 1) valores são NaN.
        Janela inclui o candle atual (mesmo comportamento Pine).

    NÃO FAZER
        Não usar `.shift(1)` antes do `.rolling(...)` — esse `.shift(1)`
        é responsabilidade do consumidor (ver pivots na Onda 3, que
        consome `.shift(length)` para evitar lookahead conforme Mapa
        Camada 1 §6 Onda 3).
    """
    return series.rolling(window=length).max()


def lowest(series: pd.Series, length: int) -> pd.Series:
    """
    OBJETIVO
        Mínimo da série nas últimas `length` observações (rolling min),
        idêntico a `ta.lowest(N)` do Pine.

    FONTE DE DADOS
        Series pandas numérica.

    LIMITAÇÕES CONHECIDAS
        Os primeiros (length - 1) valores são NaN.
        Janela inclui o candle atual (mesmo comportamento Pine).

    NÃO FAZER
        Não usar `.shift(1)` antes do `.rolling(...)` — esse `.shift(1)`
        é responsabilidade do consumidor (ver pivots na Onda 3, que
        consome `.shift(length)` para evitar lookahead conforme Mapa
        Camada 1 §6 Onda 3).
    """
    return series.rolling(window=length).min()


def change(series: pd.Series, length: int = 1) -> pd.Series:
    """
    OBJETIVO
        Diferença entre o valor atual e o de `length` candles atrás,
        idêntico a `ta.change(x, length=1)` do Pine.

    FONTE DE DADOS
        Series pandas numérica.

    LIMITAÇÕES CONHECIDAS
        Os primeiros `length` valores são NaN.
        LuxAlgo SMC usa apenas `length=1` (em startOfNewLeg/Bullish/
        Bearish). Parâmetro fica opcional para portagem fiel da
        assinatura Pine.

    NÃO FAZER
        Não usar `length=0` — Pine não suporta e pandas retorna 0
        constante (sem semântica útil).
    """
    return series.diff(length)


def cross_over(a: pd.Series, b: pd.Series) -> pd.Series:
    """
    OBJETIVO
        True no candle exato em que `a` cruza `b` para cima:
        a[i] > b[i] AND a[i-1] <= b[i-1].

    FONTE DE DADOS
        2 Series pandas com mesmo índice.

    LIMITAÇÕES CONHECIDAS
        Primeiro valor é False (a[i-1] não existe; o `&` com NaN
        resulta em False).

    NÃO FAZER
        NÃO REMOVER `.shift(1)`. Sem ele, isso vira `a > b` (estado),
        não `cruzou` (transição). Esse erro destruiu estratégias SMC
        no sistema legado (ver SMC_PRINCIPIOS_E_LEGADO.md §5.3).
        Não usar `>=` no lado defasado em vez de `<=` — muda semântica
        em casos de igualdade prévia.
    """
    return (a > b) & (a.shift(1) <= b.shift(1))


def cross_under(a: pd.Series, b: pd.Series) -> pd.Series:
    """
    OBJETIVO
        True no candle exato em que `a` cruza `b` para baixo:
        a[i] < b[i] AND a[i-1] >= b[i-1].

    FONTE DE DADOS
        2 Series pandas com mesmo índice.

    LIMITAÇÕES CONHECIDAS
        Primeiro valor é False (a[i-1] não existe; o `&` com NaN
        resulta em False).

    NÃO FAZER
        NÃO REMOVER `.shift(1)`. Mesma razão de cross_over.
        Não usar `<=` no lado defasado em vez de `>=` — muda semântica
        em casos de igualdade prévia.
    """
    return (a < b) & (a.shift(1) >= b.shift(1))
