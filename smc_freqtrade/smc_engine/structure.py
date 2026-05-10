"""
OBJETIVO
    Portagem vetorizada de displayStructure() do LuxAlgo SMC
    (Pine linhas 238-272). Detecta Break of Structure (BOS) e Change
    of Character (CHoCH) sobre os pivots produzidos por detect_pivots()
    (Onda 3), em duas escalas independentes: internal (length=5) e
    swing (length=swings_length=50).

    Algoritmo β do briefing §4.5 (vetorização com cycle-breaking):
    detecta eventos brutos por escopo×direção, constrói bias_running
    via cumsum/ffill com sinal, classifica BOS/CHoCH posteriormente
    via bias_pre_event = bias_running.shift(1). Sem loop por candle.

FONTE DE DADOS
    DataFrame com 'close', 'open', 'high', 'low' + as 8 colunas
    COL_*_LEVEL e COL_*_IDX produzidas por detect_pivots() para os
    escopos swing e internal. Equal pivots NÃO são consumidos.

LIMITAÇÕES CONHECIDAS
    Lookahead-safe por construção: consome apenas COL_*_LEVEL já
    materializados pela Onda 3 (que são lookahead-safe).

    Suppressão internal vs swing convergindo (Pine linhas 246, 259):
    quando swing_*_level.ffill() é NaN (antes do primeiro swing
    pivot), `internal_*_level.ffill() != NaN` retorna False —
    nenhum evento internal dispara. Equivalente a `na != value = na`
    (falsy) do Pine.

    CHoCH+ (variante "supported") NÃO é detectado nesta onda — Onda
    5.5 (hook documentado em detect_structure).

NÃO FAZER
    Não usar shift(-N) em ponto algum.
    Não emitir efeitos colaterais sobre o DataFrame de entrada
        (operar sobre cópia).
    Não detectar CHoCH+ — Onda 5.5.
    Não popular EngineState — Mapa §2 v1.1.
    Não consumir trailing.* (Onda 4) — irrelevante para BOS/CHoCH.
    Não inline-ar nomes de coluna — usar as 10 constantes COL_*.
"""
from __future__ import annotations

import pandas as pd

from .pivots import (
    COL_INTERNAL_HIGH_IDX,
    COL_INTERNAL_HIGH_LEVEL,
    COL_INTERNAL_LOW_IDX,
    COL_INTERNAL_LOW_LEVEL,
    COL_SWING_HIGH_IDX,
    COL_SWING_HIGH_LEVEL,
    COL_SWING_LOW_IDX,
    COL_SWING_LOW_LEVEL,
)
from .types import BEARISH, BULLISH


# ============================================================
# Nomes canônicos das 10 colunas produzidas por detect_structure.
# Consumidores (Onda 6+) referenciam estas constantes — não
# inline-ar as strings.
# ============================================================
COL_BOS_INTERNAL_BULLISH = 'bos_internal_bullish'
COL_BOS_INTERNAL_BEARISH = 'bos_internal_bearish'
COL_BOS_SWING_BULLISH = 'bos_swing_bullish'
COL_BOS_SWING_BEARISH = 'bos_swing_bearish'
COL_CHOCH_INTERNAL_BULLISH = 'choch_internal_bullish'
COL_CHOCH_INTERNAL_BEARISH = 'choch_internal_bearish'
COL_CHOCH_SWING_BULLISH = 'choch_swing_bullish'
COL_CHOCH_SWING_BEARISH = 'choch_swing_bearish'
COL_INTERNAL_TREND_BIAS = 'internal_trend_bias'
COL_SWING_TREND_BIAS = 'swing_trend_bias'


# ============================================================
# Helpers privados (vetorizados, sem loops por candle).
# ============================================================

def _first_event_per_segment(
    event_raw: pd.Series,
    segment_id: pd.Series,
) -> pd.Series:
    """Reduz event_raw para apenas o PRIMEIRO True dentro de cada
    segmento de segment_id, replicando a flag `crossed` por pivot do
    Pine (linhas 256, 270).

    Implementação: a primeira ocorrência de True em cada grupo tem
    cumsum-por-grupo igual a 1; demais Trues têm cumsum >= 2; False
    mantém cumsum constante. Padrão sem leak entre segmentos.

    Nota: o briefing §4.5 passo 6 prescreve
    `~(cumsum().shift(1) > 0)`, que sofre leak de cumsum do último
    candle do segmento K-1 para o primeiro candle do segmento K (a
    `shift` é fora do groupby). Fórmula `cumsum() == 1` corrige sem
    alterar a intenção (primeiro evento por segmento = invariante
    §4.4 #3 do briefing). Deviação documentada no body do PR.
    """
    cum_per_segment = event_raw.astype(int).groupby(segment_id).cumsum()
    return event_raw & (cum_per_segment == 1)


def _detect_directional_events(
    close: pd.Series,
    level_col: pd.Series,
    idx_col: pd.Series,
    extra_condition: pd.Series,
    direction: int,
) -> pd.Series:
    """Detecta candles de evento bruto por escopo×direção.

    direction: BULLISH (+1) ou BEARISH (-1).
    Retorna boolean Series alinhada ao close. Cada True é o primeiro
    candle do segmento (pivot) onde a condição close-cross + extra
    é satisfeita.
    """
    level_active = level_col.ffill()
    if direction == BULLISH:
        cross = (close > level_active) & (close.shift(1) <= level_active.shift(1))
    else:
        cross = (close < level_active) & (close.shift(1) >= level_active.shift(1))
    cross = cross.fillna(False).astype(bool)
    event_raw = cross & extra_condition.fillna(False).astype(bool)
    segment_id = idx_col.notna().cumsum()
    return _first_event_per_segment(event_raw, segment_id)


def _build_bias_running(
    bullish_event: pd.Series,
    bearish_event: pd.Series,
) -> pd.Series:
    """Constrói trend bias acumulado por escopo a partir dos eventos
    brutos por direção. Inicial pd.NA, sobrescreve em cada evento
    com sinal (BULLISH/BEARISH), ffill entre eventos.

    Output: pd.Series Int8 nullable, com pd.NA antes do primeiro
    evento e {BULLISH=+1, BEARISH=-1} depois.
    """
    bias = pd.Series(pd.NA, index=bullish_event.index, dtype='Int8')
    bias.loc[bullish_event] = BULLISH
    bias.loc[bearish_event] = BEARISH
    return bias.ffill().astype('Int8')


# ============================================================
# Função pública.
# ============================================================

def detect_structure(
    df: pd.DataFrame,
    *,
    internal_filter_confluence: bool = False,
) -> pd.DataFrame:
    """
    OBJETIVO
        Portagem vetorizada de displayStructure() do LuxAlgo SMC
        (Pine linhas 238-272). Detecta Break of Structure (BOS) e Change
        of Character (CHoCH) sobre os pivots produzidos por
        detect_pivots() (Onda 3), em duas escalas independentes:
        internal (length=5) e swing (length=swings_length=50).

    FONTE DE DADOS
        df: DataFrame com no mínimo 'close' + as 8 colunas COL_*_LEVEL e
            COL_*_IDX produzidas por detect_pivots() para os escopos
            swing e internal. Equal pivots NÃO são consumidos.
        internal_filter_confluence: replica internalFilterConfluenceInput
            do Pine (linhas 241-243). Quando True, exige bullishBar /
            bearishBar (computados verbatim, ver linhas 242-243 do Pine
            fonte) como condição extra para breaks internal. NUNCA afeta
            swing.
        A semântica `Persistent[trend].bias = 0` do Pine (estado neutro
            inicial) é mapeada para `pd.NA` nas colunas
            internal_trend_bias / swing_trend_bias. Equivalência:
            `0 != BEARISH` e `pd.NA != BEARISH` ambos colapsam para
            tag = 'BOS' na primeira detecção.

    LIMITAÇÕES CONHECIDAS
        Lookahead-safe por construção: consome apenas COL_*_LEVEL já
            materializados pela Onda 3 (que são lookahead-safe). Nenhum
            shift(-N) interno.

        CHoCH+ (variante "supported" do CHoCH com pré-condição estrutural
            de failed HH/LL na tendência prévia) NÃO é detectado nesta
            onda. Decisão arquitetural fechada no briefing da Onda 5:
            feature do LuxAlgo Price Action Concepts pago, adiada para
            Onda 5.5 com hook explícito. Ver
            docs/AVALIACAO_LUXALGO_PRICE_ACTION_CONCEPTS_v1.0.md §4.1
            (spec conceitual) e §6.2 (classificação como Categoria B —
            extensão sem mudança arquitetural; adiciona regra dentro de
            detect_structure + estado failed_swing_observed por trend).

        Ordem de declaração no Pine (linha 313: displayStructure(True)
            antes de linha 314: displayStructure()) é irrelevante na
            porta vetorizada porque os dois escopos têm trends
            independentes.

    NÃO FAZER
        Não usar shift(-N) em ponto algum.
        Não consumir trailing.* (Onda 4) — irrelevante para BOS/CHoCH.
        Não emitir efeitos colaterais sobre o DataFrame de entrada
            (operar sobre df.copy()).
        Não alterar order_blocks.py (Onda 6) — apesar de Pine chamar
            storeOrdeBlock dentro de displayStructure (linhas 257, 271),
            a Onda 6 lê os 8 booleans da Onda 5 + os COL_*_IDX da Onda 3
            para localizar o pivot do break.
        Não inline-ar nomes de coluna — usar as 10 constantes COL_*
            definidas no topo do módulo.
        Não popular EngineState (Mapa §2 v1.1).
        Não detectar CHoCH+ — Onda 5.5.
    """
    result = df.copy()

    close = df['close']
    open_ = df['open']
    high = df['high']
    low = df['low']

    # bullishBar / bearishBar — Pine linhas 240-243.
    # Persistent[bool] = True inicial; só sobrescritos quando filter=True.
    # Verbatim do Pine: math.min(close, open - low), NÃO min(close,open) - low.
    if internal_filter_confluence:
        max_co = pd.concat([close, open_], axis=1).max(axis=1)
        min_co_ol = pd.concat([close, open_ - low], axis=1).min(axis=1)
        bullish_bar = (high - max_co) > min_co_ol
        bearish_bar = (high - max_co) < min_co_ol
    else:
        bullish_bar = pd.Series(True, index=df.index)
        bearish_bar = pd.Series(True, index=df.index)

    # Convergência internal vs swing — Pine linhas 246, 259.
    # `!=` em pandas retorna False quando algum lado é NaN — semântica
    # equivalente a `na != value = na` (falsy) do Pine. Mantém eventos
    # internal suprimidos antes do primeiro swing pivot correspondente.
    internal_high_active = df[COL_INTERNAL_HIGH_LEVEL].ffill()
    internal_low_active = df[COL_INTERNAL_LOW_LEVEL].ffill()
    swing_high_active = df[COL_SWING_HIGH_LEVEL].ffill()
    swing_low_active = df[COL_SWING_LOW_LEVEL].ffill()

    extra_internal_bullish = (internal_high_active != swing_high_active) & bullish_bar
    extra_internal_bearish = (internal_low_active != swing_low_active) & bearish_bar
    extra_swing_true = pd.Series(True, index=df.index)

    # Algoritmo β passo (a) — eventos brutos por escopo×direção.
    swing_bullish_raw = _detect_directional_events(
        close, df[COL_SWING_HIGH_LEVEL], df[COL_SWING_HIGH_IDX],
        extra_swing_true, BULLISH,
    )
    swing_bearish_raw = _detect_directional_events(
        close, df[COL_SWING_LOW_LEVEL], df[COL_SWING_LOW_IDX],
        extra_swing_true, BEARISH,
    )
    internal_bullish_raw = _detect_directional_events(
        close, df[COL_INTERNAL_HIGH_LEVEL], df[COL_INTERNAL_HIGH_IDX],
        extra_internal_bullish, BULLISH,
    )
    internal_bearish_raw = _detect_directional_events(
        close, df[COL_INTERNAL_LOW_LEVEL], df[COL_INTERNAL_LOW_IDX],
        extra_internal_bearish, BEARISH,
    )

    # Algoritmo β passo (b) — bias_running por escopo via cumsum/ffill.
    swing_bias = _build_bias_running(swing_bullish_raw, swing_bearish_raw)
    internal_bias = _build_bias_running(internal_bullish_raw, internal_bearish_raw)

    # Algoritmo β passo (c) — bias_pre_event = bias_running.shift(1);
    # CHoCH ⇔ bias prévio oposto ao lado do break. Pré-event neutro
    # (pd.NA) → BOS (matching Pine: `tag = 'CHoCH' if bias == BEARISH`).
    swing_bias_pre = swing_bias.shift(1)
    internal_bias_pre = internal_bias.shift(1)

    swing_choch_bullish = swing_bullish_raw & swing_bias_pre.eq(BEARISH).fillna(False).astype(bool)
    swing_bos_bullish = swing_bullish_raw & ~swing_choch_bullish
    swing_choch_bearish = swing_bearish_raw & swing_bias_pre.eq(BULLISH).fillna(False).astype(bool)
    swing_bos_bearish = swing_bearish_raw & ~swing_choch_bearish

    internal_choch_bullish = internal_bullish_raw & internal_bias_pre.eq(BEARISH).fillna(False).astype(bool)
    internal_bos_bullish = internal_bullish_raw & ~internal_choch_bullish
    internal_choch_bearish = internal_bearish_raw & internal_bias_pre.eq(BULLISH).fillna(False).astype(bool)
    internal_bos_bearish = internal_bearish_raw & ~internal_choch_bearish

    result[COL_BOS_INTERNAL_BULLISH] = internal_bos_bullish.astype(bool)
    result[COL_BOS_INTERNAL_BEARISH] = internal_bos_bearish.astype(bool)
    result[COL_BOS_SWING_BULLISH] = swing_bos_bullish.astype(bool)
    result[COL_BOS_SWING_BEARISH] = swing_bos_bearish.astype(bool)
    result[COL_CHOCH_INTERNAL_BULLISH] = internal_choch_bullish.astype(bool)
    result[COL_CHOCH_INTERNAL_BEARISH] = internal_choch_bearish.astype(bool)
    result[COL_CHOCH_SWING_BULLISH] = swing_choch_bullish.astype(bool)
    result[COL_CHOCH_SWING_BEARISH] = swing_choch_bearish.astype(bool)
    result[COL_INTERNAL_TREND_BIAS] = internal_bias
    result[COL_SWING_TREND_BIAS] = swing_bias

    return result
