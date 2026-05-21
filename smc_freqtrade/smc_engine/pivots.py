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

# Wave 8.1 — Metadados canônicos do EQH/EQL detectado.
# Banda é centrada no midpoint dos pivots dentro do match (Pine
# `Buyside Liquidity box` no nível `(minP+maxP)/2` com tolerância
# `atr/a`). Pivot count exclui pivots fora da banda.
COL_EQUAL_HIGH_BAND_HIGH = 'equal_high_band_high'
COL_EQUAL_HIGH_BAND_LOW = 'equal_high_band_low'
COL_EQUAL_HIGH_PIVOT_COUNT = 'equal_high_pivot_count'
COL_EQUAL_HIGH_LEVEL_MIDPOINT = 'equal_high_level_midpoint'
COL_EQUAL_HIGH_PIVOT_INDICES = 'equal_high_pivot_indices'
COL_EQUAL_LOW_BAND_HIGH = 'equal_low_band_high'
COL_EQUAL_LOW_BAND_LOW = 'equal_low_band_low'
COL_EQUAL_LOW_PIVOT_COUNT = 'equal_low_pivot_count'
COL_EQUAL_LOW_LEVEL_MIDPOINT = 'equal_low_level_midpoint'
COL_EQUAL_LOW_PIVOT_INDICES = 'equal_low_pivot_indices'


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
    # mode == 'equal' — replica Pine linhas 165-166 e 182-183 (LuxAlgo SMC).
    # OBSOLETO (Wave 8.1, briefing §4.3): `equal_high_alert` /
    # `equal_low_alert` aqui produzidos são SOBRESCRITOS por
    # `detect_eqh_eql()` na ordem da `engine.analyze()`. A fórmula
    # canônica (Pine `ICT Concepts`) usa banda dinâmica `atr/a` e exige
    # 3+ swings same-direction, não 2 com threshold estático. Mantido
    # neste módulo apenas para preservar a assinatura de
    # `detect_pivots()` (Wave 3) e produzir `equal_*_level/idx` (Wave 8
    # liquidity_sweep consome). Os booleans abaixo são placeholders
    # all-False — qualquer consumidor que precise da semântica antiga
    # deve usar o pacote dedicado, não esta detecção legada.
    # `equal_threshold` e `atr` retidos na assinatura para compatibilidade
    # (callers da Wave 3 ainda passam) mas não utilizados — fórmula
    # canônica vive em detect_eqh_eql() (Wave 8.1).
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
# Wave 8.1 — EQH/EQL canônico (Pine LuxAlgo `ICT Concepts`).
# ============================================================

def detect_eqh_eql(
    df: pd.DataFrame,
    *,
    atr: pd.Series | None = None,
    eq_atr_length: int = 10,
    eq_margin: float = 4.0,
    eq_lookback_pivots: int = 50,
    eq_min_pivots: int = 3,
) -> pd.DataFrame:
    """
    OBJETIVO
        Detectar Equal Highs (EQH) e Equal Lows (EQL) usando a fórmula
        canônica extraída do Pine LuxAlgo `ICT Concepts` (free), per
        briefing Wave 8.1 §4.1. Substitui a detecção legada (threshold
        estático `0.1 * atr(200)` sobre 2 pivots) por banda dinâmica
        `atr(eq_atr_length) / (10/eq_margin)` exigindo `eq_min_pivots`
        swings same-direction dentro da banda.

        Resolve issue §12.2 do `MAPA_LUXALGO_CAMADA_1_v1.1.md` (engine
        produzia 0 alerts EQH/EQL no golden 720 candles).

    FONTE DE DADOS
        df: DataFrame contendo as colunas produzidas por `detect_pivots`
            (equal_high_level/equal_low_level/idx) + OHLC (high/low/close
            para cálculo interno de ATR se `atr` não fornecida).

            Decisão arquitetural: pool de pivots = equal-length pivots
            (`getCurrentStructure(equal_length, true, false)`), não
            swing-length pivots. Razão: LuxAlgo SMC TradingView
            (visualmente verificado e ratificado) renderiza EQH/EQL
            labels sobre os equal-length pivots; o briefing Wave 8.1
            §4.1 cita Pine ICT Concepts cuja ZigZag interna usa lookback
            curto (compatível com length=3 do equalHighsLowsLengthInput).
            Usar swing-length (default 50) produziria ~5 pivots em
            720 candles 4H — insuficiente para EQH/EQL emergir.

        Pine source da fórmula: `LuxAlgo - ICT Concepts` (free), bloco
            de criação das Buyside/Sellside Liquidity boxes.

    PARÂMETROS
        atr: Series opcional. Se None, calculada como
            `atr_wilder(high, low, close, length=eq_atr_length)`. Pine
            usa `ta.atr(10)` por default.
        eq_atr_length: período do ATR Wilder. Pine: 10.
        eq_margin: margin Pine, range [2, 7]. Default 4 (Pine
            `input.float(4, minval=2, maxval=7)`). Banda = atr / a com
            `a = 10 / margin`; margin maior → banda mais estreita.
        eq_lookback_pivots: máximo de pivots same-direction prévios a
            iterar por confirmação. Pine: `math.min(sz, 50)`.
        eq_min_pivots: count mínimo de swings dentro da banda para
            disparar alert. Pine: `count > 2` (3+). Briefing §4.2:
            default 3.

    OUTPUT (colunas adicionadas/sobrescritas)
        equal_high_alert (bool)      — True no candle de confirmação.
        equal_low_alert  (bool)
        equal_high_band_high (float) — limite superior da banda no
            momento da confirmação: midpoint + atr/a.
        equal_high_band_low  (float) — midpoint - atr/a.
        equal_high_pivot_count (float, NaN onde sem alert) — quantos
            swings same-direction caíram dentro da banda (inclui o
            atual).
        equal_high_level_midpoint (float) — `(minMatch + maxMatch) / 2`,
            i.e., o nível médio dos pivots da banda. Pine usa este
            valor como centro da Buyside Liquidity box.
        equal_high_pivot_indices (object) — lista de bar_indices dos
            pivots que compõem o EQH (atual + prévios dentro da banda).
            Usa swing_high_idx (bar do swing real, não da confirmação).
        Mirror para EQL (equal_low_*).

    SEMÂNTICA DE DETECÇÃO (Pine verbatim)
        Para cada candle X com swing high confirmado (`swing_high_level[X]
        not NaN`):
            ph    = swing_high_level[X]
            atr_x = atr[X]
            a     = 10 / eq_margin
            band  = atr_x / a

            Walking back nos swing highs prévios (mais recentes primeiro),
            até eq_lookback_pivots pivots:
                if prev_level > ph + band: break  # acima da banda
                if ph - band < prev_level < ph + band:
                    count += 1
                    atualizar min/max do match
            count também inclui o pivot atual (ph cai trivialmente em
            (ph-band, ph+band) com band > 0).

            Se `count >= eq_min_pivots`, disparar alert em X com
            midpoint = (min_match + max_match) / 2.

        Mirror para EQL: swing lows, `break` se prev_level < pl - band.

    LIMITAÇÕES CONHECIDAS
        Loop por candle em Python — não vetorizado. Para o golden 720
        candles 4H com ~14 swing highs, ~200 operações totais —
        negligível. Para datasets multi-milhão de candles, otimizar
        depois (não é gargalo atual).
        Bandas usam comparação ESTRITA (`<` e `>`, Pine), não inclusiva.
        Pivots exatamente em `ph ± band` ficam de fora.
        Lookback é por pivots same-direction (não por candles); diverge
        de Pine que itera sobre o pool `aZZ` (mixed high/low). Briefing
        §4.3 explicita "só same-direction", divergência intencional.

    NÃO FAZER
        Não chamar antes de `detect_pivots` — requer `equal_high_level`
            e `equal_low_level` populados.
        Não consumir `equal_high_idx` para semântica de event timestamp
            — alerts são emitidos no candle de confirmação (X), não no
            candle do pivot (X - equal_length). bar_idx em pivot_indices
            é o do pivot real (via equal_*_idx).
        Não passar `eq_margin` fora de [2.0, 7.0] — validação canônica
            vive em SMCConfig.__post_init__.
    """
    if COL_EQUAL_HIGH_LEVEL not in df.columns or COL_EQUAL_LOW_LEVEL not in df.columns:
        raise ValueError(
            f"detect_eqh_eql requer colunas {COL_EQUAL_HIGH_LEVEL!r} e "
            f"{COL_EQUAL_LOW_LEVEL!r} populadas — rodar detect_pivots antes"
        )

    result = df.copy()
    n = len(df)

    if atr is None:
        atr = atr_wilder(df['high'], df['low'], df['close'], length=eq_atr_length)

    a = 10.0 / eq_margin

    eq_high_level = df[COL_EQUAL_HIGH_LEVEL].to_numpy()
    eq_low_level = df[COL_EQUAL_LOW_LEVEL].to_numpy()
    eq_high_idx = df[COL_EQUAL_HIGH_IDX].to_numpy()
    eq_low_idx = df[COL_EQUAL_LOW_IDX].to_numpy()
    atr_vals = atr.to_numpy()

    eqh_alert = np.zeros(n, dtype=bool)
    eqh_band_high = np.full(n, np.nan)
    eqh_band_low = np.full(n, np.nan)
    eqh_count = np.full(n, np.nan)
    eqh_midpoint = np.full(n, np.nan)
    eqh_pivots: list[list[int] | None] = [None] * n

    eql_alert = np.zeros(n, dtype=bool)
    eql_band_high = np.full(n, np.nan)
    eql_band_low = np.full(n, np.nan)
    eql_count = np.full(n, np.nan)
    eql_midpoint = np.full(n, np.nan)
    eql_pivots: list[list[int] | None] = [None] * n

    # Pools de swings same-direction confirmados (em ordem cronológica).
    # Cada entrada: (bar_idx_real_do_pivot, level).
    high_pool: list[tuple[int, float]] = []
    low_pool: list[tuple[int, float]] = []

    for i in range(n):
        # --- EQH detection no candle de confirmação ---
        ph = eq_high_level[i]
        if not np.isnan(ph):
            atr_i = atr_vals[i]
            if not np.isnan(atr_i) and atr_i > 0:
                band = atr_i / a
                upper = ph + band
                lower = ph - band
                count = 1  # inclui o atual
                band_max = ph
                band_min = ph
                pivot_idx_current = int(eq_high_idx[i])
                matched_pivots: list[int] = [pivot_idx_current]
                checked = 1  # já consideramos o atual

                # Walk back nos equal-length highs same-direction prévios.
                for (bar_b, level_b) in reversed(high_pool):
                    if checked >= eq_lookback_pivots:
                        break
                    checked += 1
                    if level_b > upper:
                        break  # Pine: out of band — parar
                    if level_b > lower and level_b < upper:
                        count += 1
                        if level_b > band_max:
                            band_max = level_b
                        if level_b < band_min:
                            band_min = level_b
                        matched_pivots.append(bar_b)

                if count >= eq_min_pivots:
                    midpoint = (band_max + band_min) / 2.0
                    eqh_alert[i] = True
                    eqh_band_high[i] = midpoint + band
                    eqh_band_low[i] = midpoint - band
                    eqh_count[i] = count
                    eqh_midpoint[i] = midpoint
                    eqh_pivots[i] = matched_pivots

            high_pool.append((int(eq_high_idx[i]), float(ph)))

        # --- EQL detection (mirror) ---
        pl = eq_low_level[i]
        if not np.isnan(pl):
            atr_i = atr_vals[i]
            if not np.isnan(atr_i) and atr_i > 0:
                band = atr_i / a
                upper = pl + band
                lower = pl - band
                count = 1
                band_max = pl
                band_min = pl
                pivot_idx_current = int(eq_low_idx[i])
                matched_pivots = [pivot_idx_current]
                checked = 1

                for (bar_b, level_b) in reversed(low_pool):
                    if checked >= eq_lookback_pivots:
                        break
                    checked += 1
                    if level_b < lower:
                        break  # mirror: out of band para baixo
                    if level_b > lower and level_b < upper:
                        count += 1
                        if level_b > band_max:
                            band_max = level_b
                        if level_b < band_min:
                            band_min = level_b
                        matched_pivots.append(bar_b)

                if count >= eq_min_pivots:
                    midpoint = (band_max + band_min) / 2.0
                    eql_alert[i] = True
                    eql_band_high[i] = midpoint + band
                    eql_band_low[i] = midpoint - band
                    eql_count[i] = count
                    eql_midpoint[i] = midpoint
                    eql_pivots[i] = matched_pivots

            low_pool.append((int(eq_low_idx[i]), float(pl)))

    result[COL_EQUAL_HIGH_ALERT] = eqh_alert
    result[COL_EQUAL_HIGH_BAND_HIGH] = eqh_band_high
    result[COL_EQUAL_HIGH_BAND_LOW] = eqh_band_low
    result[COL_EQUAL_HIGH_PIVOT_COUNT] = eqh_count
    result[COL_EQUAL_HIGH_LEVEL_MIDPOINT] = eqh_midpoint
    result[COL_EQUAL_HIGH_PIVOT_INDICES] = pd.Series(eqh_pivots, index=df.index, dtype='object')

    result[COL_EQUAL_LOW_ALERT] = eql_alert
    result[COL_EQUAL_LOW_BAND_HIGH] = eql_band_high
    result[COL_EQUAL_LOW_BAND_LOW] = eql_band_low
    result[COL_EQUAL_LOW_PIVOT_COUNT] = eql_count
    result[COL_EQUAL_LOW_LEVEL_MIDPOINT] = eql_midpoint
    result[COL_EQUAL_LOW_PIVOT_INDICES] = pd.Series(eql_pivots, index=df.index, dtype='object')

    return result
