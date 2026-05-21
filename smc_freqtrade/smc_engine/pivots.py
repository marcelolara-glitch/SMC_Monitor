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

# Wave 8.2 — Metadados canônicos do EQH/EQL detectado (SMC Concepts).
# Pine compara 2 pivots same-direction consecutivos contra `0.1 * atr(200)`.
# Midpoint = média dos 2 pivots; pivot_indices = bar_indices dos dois.
COL_EQUAL_HIGH_LEVEL_MIDPOINT = 'equal_high_level_midpoint'
COL_EQUAL_HIGH_PIVOT_INDICES = 'equal_high_pivot_indices'
COL_EQUAL_LOW_LEVEL_MIDPOINT = 'equal_low_level_midpoint'
COL_EQUAL_LOW_PIVOT_INDICES = 'equal_low_pivot_indices'

# Constante canônica: o Pine LuxAlgo SMC Concepts usa `ta.atr(200)`
# hardcoded para o threshold de EQH/EQL (linhas 124 e 165/182 do
# Pine fonte em tools/pynecore-validation/luxalgo_smc_compute_only.py).
# Não parametrizado em SMCConfig — fiel à fonte.
EQ_ATR_LENGTH_CANONICAL = 200


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
    # mode == 'equal' — emite só os pivots (level/idx). A detecção do
    # alerta vive em `detect_eqh_eql()` (Wave 8.2, fiel ao Pine SMC
    # Concepts: 2 pivots consecutivos vs threshold estático
    # `0.1 * atr(200)`). Os booleans `equal_*_alert` abaixo são
    # placeholders all-False — sobrescritos quando `engine.analyze()`
    # orquestra. Consumidores diretos de `detect_pivots()` que precisem
    # da semântica nova devem chamar `detect_eqh_eql()` em seguida.
    # `equal_threshold` e `atr` retidos na assinatura para compatibilidade
    # (callers Wave 3 ainda passam) mas não utilizados aqui.
    del equal_threshold, atr
    equal_high_alert_legacy = pd.Series(False, index=df.index, dtype='bool')
    equal_low_alert_legacy = pd.Series(False, index=df.index, dtype='bool')
    return {
        COL_EQUAL_HIGH_LEVEL: high_level,
        COL_EQUAL_HIGH_IDX: high_idx,
        COL_EQUAL_LOW_LEVEL: low_level,
        COL_EQUAL_LOW_IDX: low_idx,
        COL_EQUAL_HIGH_ALERT: equal_high_alert_legacy,
        COL_EQUAL_LOW_ALERT: equal_low_alert_legacy,
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


# ============================================================
# Wave 8.2 — EQH/EQL canônico (Pine LuxAlgo `SMC Concepts`).
# ============================================================

def detect_eqh_eql(
    df: pd.DataFrame,
    *,
    atr: pd.Series | None = None,
    threshold: float = 0.1,
) -> pd.DataFrame:
    """Detecta Equal Highs (EQH) e Equal Lows (EQL) fiel ao Pine canônico.

    OBJETIVO
        Reescreve a detecção EQH/EQL conforme o Pine LuxAlgo
        `SMC Concepts` (gratuito), substituindo a Wave 8.1 — que portou
        por engano o indicador `ICT Concepts` (banda dinâmica `atr/a` +
        3+ swings). A fórmula canônica:

            for each new pivot high confirmed at candle X:
                if abs(equalHigh.currentLevel - high[size]) < 0.1 * atr(200):
                    currentAlerts.equalHighs = True
                equalHigh.lastLevel    = equalHigh.currentLevel
                equalHigh.currentLevel = high[size]

        i.e., compara o pivot novo APENAS contra o pivot imediatamente
        anterior (`currentLevel`), com threshold ESTÁTICO `0.1 * atr(200)`
        — não janela de 50 pivots nem banda dinâmica.

        Pine fonte verificado em
        `tools/pynecore-validation/luxalgo_smc_compute_only.py` linhas
        89-90 (inputs), 124 (`atrMeasure = ta.atr(200)`), 155-195
        (`getCurrentStructure` no modo equalHighLow=True).

    FONTE DE DADOS
        df: DataFrame contendo as colunas produzidas por `detect_pivots`
            no modo equal (length=3) — `equal_high_level`,
            `equal_low_level`, `equal_high_idx`, `equal_low_idx` —
            mais OHLC (high/low/close para cálculo de ATR(200) se `atr`
            não for fornecida).

        ATR length=200 é HARDCODED (`EQ_ATR_LENGTH_CANONICAL`), fiel ao
        Pine `ta.atr(200)`. Não exposto em SMCConfig.

    PARÂMETROS
        atr: Series opcional. Se None, calculada como
            `atr_wilder(high, low, close, length=200)`.
        threshold: fator multiplicativo do ATR (Pine
            `equalHighsLowsThresholdInput`, default 0.1, range [0, 0.5]).
            Reutiliza `SMCConfig.pivot_equal_threshold` (idêntico).

    OUTPUT (colunas adicionadas/sobrescritas)
        equal_high_alert (bool)      — True no candle de confirmação do
            2o pivot (X = candle do pivot real + equal_length).
        equal_low_alert  (bool)
        equal_high_level_midpoint (float, NaN onde sem alert) — média
            aritmética dos 2 pivots: `(prev_currentLevel + new) / 2`.
        equal_low_level_midpoint  (float)
        equal_high_pivot_indices (object) — lista `[bar_idx_anterior,
            bar_idx_novo]` dos 2 pivots reais (não dos candles de
            confirmação). Útil para rastreabilidade visual.
        equal_low_pivot_indices  (object)

    SEMÂNTICA DE DETECÇÃO (estado persistente; equivalente ao Pine
    `Persistent[pivot] equalHigh`/`equalLow`):

        Estado:
            eq_high_current_level, eq_high_current_idx  (NaN/-1 inicial)
            eq_low_current_level,  eq_low_current_idx   (NaN/-1 inicial)

        Para cada candle X em ordem cronológica:
            se equal_high_level[X] não-NaN (novo pivot high confirmado):
                novo = equal_high_level[X]
                se eq_high_current_level não-NaN e atr[X] não-NaN:
                    se abs(eq_high_current_level - novo) < threshold * atr[X]:
                        equal_high_alert[X] = True
                        midpoint = média(eq_high_current_level, novo)
                eq_high_current_level = novo
                eq_high_current_idx   = equal_high_idx[X]
            espelho para EQL.

    LIMITAÇÕES CONHECIDAS
        Loop por candle em Python (n iterações); só ~14 pivots equal-mode
        em 720 candles 4H, dominado pelo overhead do `range(n)`. Para
        datasets multi-milhão otimizar depois (não é gargalo atual).

        Comparação ESTRITA `<` (Pine usa `<`, não `<=`). Pivots
        exatamente em `threshold * atr` ficam de fora.

        ATR(200) Wilder leva ~200 candles para estabilizar; janelas
        curtas terão ATR=NaN no início, então EQH/EQL não dispara — o
        ramp-up replica o Pine fonte (que também usa ta.atr(200)).

    NÃO FAZER
        Não chamar antes de `detect_pivots` — requer `equal_high_level`,
            `equal_low_level`, `equal_high_idx`, `equal_low_idx`
            populados.
        Não usar `swing_*_level` como pool — o Pine usa o pool
            equal-length (`getCurrentStructure(equal_length, true,
            false)`). O rendering visual do LuxAlgo SMC casa
            exatamente com esses pivots.
        Não parametrizar ATR length — Pine hardcoded `ta.atr(200)`.
    """
    if COL_EQUAL_HIGH_LEVEL not in df.columns or COL_EQUAL_LOW_LEVEL not in df.columns:
        raise ValueError(
            f"detect_eqh_eql requer colunas {COL_EQUAL_HIGH_LEVEL!r} e "
            f"{COL_EQUAL_LOW_LEVEL!r} populadas — rodar detect_pivots antes"
        )

    result = df.copy()
    n = len(df)

    if atr is None:
        atr = atr_wilder(
            df['high'], df['low'], df['close'],
            length=EQ_ATR_LENGTH_CANONICAL,
        )

    eq_high_level = df[COL_EQUAL_HIGH_LEVEL].to_numpy()
    eq_low_level = df[COL_EQUAL_LOW_LEVEL].to_numpy()
    eq_high_idx = df[COL_EQUAL_HIGH_IDX].to_numpy()
    eq_low_idx = df[COL_EQUAL_LOW_IDX].to_numpy()
    atr_vals = atr.to_numpy()

    eqh_alert = np.zeros(n, dtype=bool)
    eqh_midpoint = np.full(n, np.nan)
    eqh_pivots: list[list[int] | None] = [None] * n

    eql_alert = np.zeros(n, dtype=bool)
    eql_midpoint = np.full(n, np.nan)
    eql_pivots: list[list[int] | None] = [None] * n

    # Estado persistente — replica Pine `Persistent[pivot]
    # equalHigh`/`equalLow` (linha 107-108 do fonte). NaN/-1 inicial.
    eq_high_current_level = np.nan
    eq_high_current_idx = -1
    eq_low_current_level = np.nan
    eq_low_current_idx = -1

    for i in range(n):
        # --- EQH: novo pivot high confirmado no candle i ---
        ph = eq_high_level[i]
        if not np.isnan(ph):
            new_idx = int(eq_high_idx[i])
            atr_i = atr_vals[i]
            if not np.isnan(eq_high_current_level) and not np.isnan(atr_i):
                if abs(eq_high_current_level - ph) < threshold * atr_i:
                    eqh_alert[i] = True
                    eqh_midpoint[i] = (eq_high_current_level + ph) / 2.0
                    eqh_pivots[i] = [eq_high_current_idx, new_idx]
            eq_high_current_level = float(ph)
            eq_high_current_idx = new_idx

        # --- EQL: espelho ---
        pl = eq_low_level[i]
        if not np.isnan(pl):
            new_idx = int(eq_low_idx[i])
            atr_i = atr_vals[i]
            if not np.isnan(eq_low_current_level) and not np.isnan(atr_i):
                if abs(eq_low_current_level - pl) < threshold * atr_i:
                    eql_alert[i] = True
                    eql_midpoint[i] = (eq_low_current_level + pl) / 2.0
                    eql_pivots[i] = [eq_low_current_idx, new_idx]
            eq_low_current_level = float(pl)
            eq_low_current_idx = new_idx

    result[COL_EQUAL_HIGH_ALERT] = eqh_alert
    result[COL_EQUAL_HIGH_LEVEL_MIDPOINT] = eqh_midpoint
    result[COL_EQUAL_HIGH_PIVOT_INDICES] = pd.Series(
        eqh_pivots, index=df.index, dtype='object',
    )

    result[COL_EQUAL_LOW_ALERT] = eql_alert
    result[COL_EQUAL_LOW_LEVEL_MIDPOINT] = eql_midpoint
    result[COL_EQUAL_LOW_PIVOT_INDICES] = pd.Series(
        eql_pivots, index=df.index, dtype='object',
    )

    return result
