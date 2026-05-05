"""
OBJETIVO
    Portagem vetorizada das 5 funções nested do LuxAlgo SMC que
    detectam swing/internal/equal pivots:
        leg(size)                       -> Pine linhas 122-130
        startOfNewLeg(leg)              -> Pine linhas 132-133
        startOfBearishLeg(leg)          -> Pine linhas 135-136
        startOfBullishLeg(leg)          -> Pine linhas 138-139
        getCurrentStructure(...)        -> Pine linhas 141-181

    A função pública é `detect_pivots`, que reproduz as 3 chamadas
    feitas no main() do Pine (linhas 285-287):
        getCurrentStructure(swingsLengthInput, False)
        getCurrentStructure(5, False, True)
        getCurrentStructure(equalHighsLowsLengthInput, True)

    Cada chamada produz 1 conjunto de colunas (level + idx) por par
    high/low, totalizando 14 colunas anexadas ao DataFrame de saída.

FONTE DE DADOS
    Os 4 helpers privados consomem `pd.Series` (high/low ou leg) com
    o mesmo índice do DataFrame de entrada.

    `detect_pivots` espera um DataFrame com no mínimo as colunas
    'high', 'low', 'close'. ATR (Wilder length=200, fiel ao Pine
    linha 113: `atrMeasure = ta.atr(200)`) é calculada internamente
    se não for fornecida.

    A semântica `Persistent[int] = 0` do Pine (estado inicial) é
    replicada via `ffill().fillna(0)`: o forward-fill propaga a
    última transição entre candles e o fillna(0) zera o estado nos
    candles anteriores ao primeiro evento.

LIMITAÇÕES CONHECIDAS
    Lookahead-safe por construção: cada coluna `*_level` / `*_idx`
    materializa apenas no candle X (= candle de confirmação), com X
    `size` candles à frente do candle do swing real (X-size). Os
    primeiros `swings_length` candles têm coluna swing_* NaN; idem
    para internal e equal nas suas escalas.

    Não atualiza `EngineState` — colunas no DataFrame são a interface
    canônica desta onda (Mapa Camada 1 §2 v1.1).

    Não atualiza `trailing.top` / `trailing.bottom` — Onda 4. Embora
    o Pine atualize trailing.* dentro de `getCurrentStructure` (linhas
    156-161 e 174-179), essa responsabilidade fica deliberadamente
    fora desta onda para preservar isolamento de escopo.

    Detecção de swing é one-sided (mesma do Pine fonte): valida que
    `high[X-size]` é maior que o máximo dos `size` candles seguintes,
    sem checar candles anteriores a X-size. A propagação por ffill
    do `_leg` é o que dá a continuidade temporal.

NÃO FAZER
    Não usar `shift(-N)` em ponto algum.
    Não retornar arrays de eventos — somente colunas (uma linha por
    candle).
    Não emitir efeitos colaterais sobre o DataFrame de entrada;
    operar sobre `df.copy()`.
    Não consumir trailing.* nem produzir colunas trailing_* — Onda 4.
    Não popular `EngineState` — Mapa §2 v1.1 fechou que estado vive
    no DataFrame em Python vetorizado.
    Não inline-ar nomes de coluna — use as constantes COL_* abaixo.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .operators import atr_wilder, change, highest, lowest
from .types import BEARISH_LEG, BULLISH_LEG


# ============================================================
# Nomes canônicos das 14 colunas produzidas por detect_pivots.
# Consumidores (Onda 5+) referenciam estas constantes — não
# inline-ar as strings.
# ============================================================
COL_SWING_HIGH_LEVEL = 'swing_high_level'
COL_SWING_HIGH_IDX = 'swing_high_idx'
COL_SWING_LOW_LEVEL = 'swing_low_level'
COL_SWING_LOW_IDX = 'swing_low_idx'
COL_INTERNAL_HIGH_LEVEL = 'internal_high_level'
COL_INTERNAL_HIGH_IDX = 'internal_high_idx'
COL_INTERNAL_LOW_LEVEL = 'internal_low_level'
COL_INTERNAL_LOW_IDX = 'internal_low_idx'
COL_EQUAL_HIGH_LEVEL = 'equal_high_level'
COL_EQUAL_HIGH_IDX = 'equal_high_idx'
COL_EQUAL_LOW_LEVEL = 'equal_low_level'
COL_EQUAL_LOW_IDX = 'equal_low_idx'
COL_EQUAL_HIGH_ALERT = 'equal_high_alert'
COL_EQUAL_LOW_ALERT = 'equal_low_alert'


# ============================================================
# Helpers privados (não exportados).
# ============================================================

def _leg(high: pd.Series, low: pd.Series, size: int) -> pd.Series:
    """
    OBJETIVO
        Portagem vetorizada de leg(size) do Pine (linhas 122-130).
        Retorna inteiros BULLISH_LEG (1) ou BEARISH_LEG (0). O
        estado inicial é 0 (replicando `Persistent[int] = 0`); entre
        transições, retém o último valor (replicando o Persistent
        retorno do Pine).

    FONTE DE DADOS
        high, low: pd.Series com mesmo índice. size: int > 0.

    LIMITAÇÕES CONHECIDAS
        Empate `high[size] == ta.highest(size)` não dispara
        new_leg_high (Pine usa `>` estrito); idem para low.
        Em pandas, `NaN > x` retorna False — `.fillna(False)` é
        aplicado por garantia em versões mais novas onde booleanos
        com NaN podem disparar warning.

    NÃO FAZER
        Não substituir `>` por `>=` — muda semântica do Pine fonte.
        Não remover `ffill().fillna(0)` — replica o Persistent[int]=0
        do Pine.
    """
    new_leg_high = high.shift(size) > highest(high, size)
    new_leg_low = low.shift(size) < lowest(low, size)

    leg_raw = pd.Series(np.nan, index=high.index, dtype='float64')
    leg_raw.loc[new_leg_high.fillna(False)] = float(BEARISH_LEG)
    leg_raw.loc[new_leg_low.fillna(False)] = float(BULLISH_LEG)
    return leg_raw.ffill().fillna(0).astype(int)


def _start_of_new_leg(leg: pd.Series) -> pd.Series:
    """
    OBJETIVO
        Pine: `ta.change(leg) != 0`.

    LIMITAÇÕES CONHECIDAS
        `change(leg).iloc[0]` é NaN; em pandas, `NaN != 0` retorna
        True (semântica IEEE invertida via `.diff()`). Forçamos
        NaN -> 0 antes da comparação para que iloc[0] seja False
        (não há transição sem candle anterior).

    NÃO FAZER
        Não retirar `.fillna(0)` — sem ele o primeiro candle dispara
        spurious new_leg, que escaparia mascarado apenas pelo `&` com
        start_of_bullish/bearish (que retornam False para NaN). Manter
        defesa local no helper.
    """
    return change(leg).fillna(0) != 0


def _start_of_bullish_leg(leg: pd.Series) -> pd.Series:
    """Pine: `ta.change(leg) == 1`. NaN no diff retorna False (correto)."""
    return change(leg) == 1


def _start_of_bearish_leg(leg: pd.Series) -> pd.Series:
    """Pine: `ta.change(leg) == -1`. NaN no diff retorna False (correto)."""
    return change(leg) == -1


def _detect_pivots_for_mode(
    df: pd.DataFrame,
    size: int,
    mode: str,
    atr: pd.Series | None = None,
    equal_threshold: float | None = None,
) -> dict[str, pd.Series]:
    """
    OBJETIVO
        Roda uma das 3 chamadas a getCurrentStructure() do Pine
        (linhas 141-181) em forma vetorizada. Para cada candle X
        onde houve transição de leg, materializa o nível e a
        posição do candle do swing real (X-size).

    FONTE DE DADOS
        df com colunas 'high'/'low'. Para mode='equal', exige `atr` e
        `equal_threshold` não-None.

    LIMITAÇÕES CONHECIDAS
        Para mode='equal', a comparação `prev_equal_*_level` usa
        ffill().shift(1) para pegar o último equal-pivot conhecido
        ANTES do candle atual — replica `p_ivot.currentLevel` do Pine
        (acessado antes de ser sobrescrito).

    NÃO FAZER
        Não materializar colunas trailing_* aqui — Onda 4.
        Não passar mode != {'swing','internal','equal'} — função
        privada, não há defesa contra chamada inválida.
    """
    leg_series = _leg(df['high'], df['low'], size)
    new_leg = _start_of_new_leg(leg_series)
    bullish_event = new_leg & _start_of_bullish_leg(leg_series)
    bearish_event = new_leg & _start_of_bearish_leg(leg_series)

    high_at_pivot = df['high'].shift(size)
    low_at_pivot = df['low'].shift(size)

    positions = pd.Series(np.arange(len(df), dtype='float64'), index=df.index)
    pivot_idx_at = positions - size

    high_level = pd.Series(np.nan, index=df.index, dtype='float64')
    high_idx = pd.Series(np.nan, index=df.index, dtype='float64')
    low_level = pd.Series(np.nan, index=df.index, dtype='float64')
    low_idx = pd.Series(np.nan, index=df.index, dtype='float64')

    high_level.loc[bearish_event] = high_at_pivot.loc[bearish_event]
    high_idx.loc[bearish_event] = pivot_idx_at.loc[bearish_event]
    low_level.loc[bullish_event] = low_at_pivot.loc[bullish_event]
    low_idx.loc[bullish_event] = pivot_idx_at.loc[bullish_event]

    if mode == 'swing':
        return {
            COL_SWING_HIGH_LEVEL: high_level,
            COL_SWING_HIGH_IDX: high_idx,
            COL_SWING_LOW_LEVEL: low_level,
            COL_SWING_LOW_IDX: low_idx,
        }
    if mode == 'internal':
        return {
            COL_INTERNAL_HIGH_LEVEL: high_level,
            COL_INTERNAL_HIGH_IDX: high_idx,
            COL_INTERNAL_LOW_LEVEL: low_level,
            COL_INTERNAL_LOW_IDX: low_idx,
        }
    # mode == 'equal' — replica Pine linhas 165-166 e 182-183.
    prev_high_level = high_level.ffill().shift(1)
    prev_low_level = low_level.ffill().shift(1)
    threshold_abs = equal_threshold * atr

    distance_high = (prev_high_level - high_at_pivot).abs()
    distance_low = (prev_low_level - low_at_pivot).abs()

    equal_high_alert = (
        bearish_event
        & distance_high.notna()
        & threshold_abs.notna()
        & (distance_high < threshold_abs)
    )
    equal_low_alert = (
        bullish_event
        & distance_low.notna()
        & threshold_abs.notna()
        & (distance_low < threshold_abs)
    )
    return {
        COL_EQUAL_HIGH_LEVEL: high_level,
        COL_EQUAL_HIGH_IDX: high_idx,
        COL_EQUAL_LOW_LEVEL: low_level,
        COL_EQUAL_LOW_IDX: low_idx,
        COL_EQUAL_HIGH_ALERT: equal_high_alert.fillna(False),
        COL_EQUAL_LOW_ALERT: equal_low_alert.fillna(False),
    }


# ============================================================
# Função pública.
# ============================================================

def detect_pivots(
    df: pd.DataFrame,
    swings_length: int = 50,
    internal_length: int = 5,
    equal_length: int = 3,
    equal_threshold: float = 0.1,
    atr: pd.Series | None = None,
) -> pd.DataFrame:
    """
    OBJETIVO
        Portagem vetorizada de getCurrentStructure() do LuxAlgo SMC
        (compute-only) para os 3 modos: swing, internal, equal.
        Adiciona 14 colunas ao DataFrame de entrada e devolve uma
        cópia.

    FONTE DE DADOS
        df: DataFrame com no mínimo 'high', 'low', 'close'.
        atr: Series opcional. Se None, é calculada internamente como
            `operators.atr_wilder(high, low, close, length=200)` —
            fiel ao Pine fonte (linha 113: `atrMeasure = ta.atr(200)`).
        Defaults dos 4 inputs equivalem aos defaults do Pine main():
            swingsLengthInput=50, equalHighsLowsLengthInput=3,
            equalHighsLowsThresholdInput=0.1.
        internal_length=5 é hardcoded na 2a chamada do Pine
            (linha 286: `getCurrentStructure(5, False, True)`) mas
            fica configurável aqui por simetria com os demais.

    LIMITAÇÕES CONHECIDAS
        Lookahead-safe por construção: cada coluna *_level/idx
        materializa apenas no candle X (X = candle do swing real
        + size). Os primeiros `swings_length` candles têm coluna
        swing NaN; idem para internal e equal nas suas escalas.
        Não atualiza EngineState — colunas no DataFrame são a interface
        canônica desta onda (Mapa Camada 1 §2 v1.1).
        Não toca trailing.top/bottom — isso é Onda 4.

    NÃO FAZER
        Não usar shift(-N) em ponto algum.
        Não retornar arrays de eventos — só colunas.
        Não emitir efeitos colaterais sobre o DataFrame de entrada
        (operar sobre cópia: `result = df.copy()`).
        Não consumir trailing.* — Onda 4.
        Não popular EngineState — Mapa §2 v1.1 fechou que estado vive
        no DataFrame em Python vetorizado.
    """
    if atr is None:
        atr = atr_wilder(df['high'], df['low'], df['close'], length=200)

    result = df.copy()

    swing = _detect_pivots_for_mode(df, swings_length, 'swing')
    internal = _detect_pivots_for_mode(df, internal_length, 'internal')
    equal = _detect_pivots_for_mode(
        df, equal_length, 'equal',
        atr=atr, equal_threshold=equal_threshold,
    )

    for name, series in {**swing, **internal, **equal}.items():
        result[name] = series

    return result
