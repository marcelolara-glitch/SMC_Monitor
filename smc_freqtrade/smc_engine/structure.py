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

    CHoCH+ (Onda 5.5): variante "supported" do CHoCH, portada da
    spec conceitual do Doc PAC §4.1. Exige pré-condição estrutural
    na tendência anterior (failed HH/LL) antes do break formal.
    Escopos swing e internal; 4 colunas aditivas, saída Onda 5
    inalterada.

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

    Discrepância de orientação entre Doc PAC §4.1 (fonte da
    implementação swing original) e HOOKS §1: Doc PAC mapeia CHoCH+
    bullish ← lower high (failed HH) no segmento bearish prévio;
    HOOKS §1 mapeia CHoCH+ bullish ← higher low (HL). Internal usa
    mesma orientação que swing (Doc PAC §4.1) para consistência
    interna. Divergência registrada para ratificação visual.

NÃO FAZER
    Não usar shift(-N) em ponto algum.
    Não emitir efeitos colaterais sobre o DataFrame de entrada
        (operar sobre cópia).
    Não popular EngineState — Mapa §2 v1.1.
    Não consumir trailing.* (Onda 4) — irrelevante para BOS/CHoCH.
    Não inline-ar nomes de coluna — usar as 14 constantes COL_*.
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
# Nomes canônicos das 14 colunas produzidas por detect_structure.
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
COL_CHOCH_PLUS_SWING_BULLISH = 'choch_plus_swing_bullish'
COL_CHOCH_PLUS_SWING_BEARISH = 'choch_plus_swing_bearish'
COL_CHOCH_PLUS_INTERNAL_BULLISH = 'choch_plus_internal_bullish'
COL_CHOCH_PLUS_INTERNAL_BEARISH = 'choch_plus_internal_bearish'


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

        CHoCH+ (Onda 5.5): detecta a variante "supported" do CHoCH nos
        escopos swing e internal, portada da spec conceitual do Doc PAC
        §4.1. CHoCH+ bullish exige ≥1 lower high (failed HH) no
        segmento bearish prévio; CHoCH+ bearish exige ≥1 higher low
        (failed LL) no segmento bullish prévio. Saída: 4 colunas
        aditivas (choch_plus_swing_bullish, choch_plus_swing_bearish,
        choch_plus_internal_bullish, choch_plus_internal_bearish),
        cada uma subconjunto estrito do CHoCH correspondente.

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

        Discrepância de orientação entre Doc PAC §4.1 e HOOKS §1
            (ver docstring do módulo). Ambos escopos usam orientação
            Doc PAC §4.1 para consistência interna. Pendente
            ratificação visual.

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
        Não inline-ar nomes de coluna — usar as 14 constantes COL_*
            definidas no topo do módulo.
        Não popular EngineState (Mapa §2 v1.1).
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

    # ==== CHoCH+ (Onda 5.5) — Supported CHoCH, escopo swing ====
    # Detecta failed swing events: lower_high e higher_low nos candles
    # de confirmação dos swing pivots. Acumula por segmento de trend e
    # marca CHoCH+ na barra do flip.

    swing_high_level = df[COL_SWING_HIGH_LEVEL]
    swing_low_level = df[COL_SWING_LOW_LEVEL]

    # Nível do swing high/low anterior (último confirmado antes deste).
    prev_swing_high = swing_high_level.ffill().shift(1)
    prev_swing_low = swing_low_level.ffill().shift(1)

    # Failed swing events no candle de confirmação do pivot:
    # lower_high_event: swing high atual < swing high anterior
    # higher_low_event: swing low atual > swing low anterior
    is_swing_high_conf = swing_high_level.notna()
    is_swing_low_conf = swing_low_level.notna()
    lower_high_event = is_swing_high_conf & (swing_high_level < prev_swing_high)
    higher_low_event = is_swing_low_conf & (swing_low_level > prev_swing_low)

    # Segmentar por swing_trend_bias: running-OR de failed events
    # dentro de cada segmento de trend. Segmento muda quando bias muda.
    bias_segment_id = swing_bias.fillna(0).diff().ne(0).cumsum()

    # Acumular lower_high_event em segmentos bearish (para CHoCH+ bullish)
    lower_high_cum = lower_high_event.astype(int).groupby(bias_segment_id).cumsum()
    failed_high_in_segment = lower_high_cum > 0

    # Acumular higher_low_event em segmentos bullish (para CHoCH+ bearish)
    higher_low_cum = higher_low_event.astype(int).groupby(bias_segment_id).cumsum()
    failed_low_in_segment = higher_low_cum > 0

    # CHoCH+ bullish: o segmento bearish que está TERMINANDO acumulou
    # ≥1 lower_high. O CHoCH bullish marca o FIM do segmento bearish,
    # portanto usamos o valor de failed_high_in_segment no candle
    # imediatamente anterior (shift(1)) — que pertence ao segmento prévio.
    failed_high_at_flip = failed_high_in_segment.shift(1).fillna(False).astype(bool)
    choch_plus_bullish = swing_choch_bullish & failed_high_at_flip

    # CHoCH+ bearish: o segmento bullish que está TERMINANDO acumulou
    # ≥1 higher_low.
    failed_low_at_flip = failed_low_in_segment.shift(1).fillna(False).astype(bool)
    choch_plus_bearish = swing_choch_bearish & failed_low_at_flip

    # ==== CHoCH+ (Onda 5.5) — Supported CHoCH, escopo internal ====
    # Espelho mecânico do bloco swing acima, usando pivots e bias internal.

    int_high_level = df[COL_INTERNAL_HIGH_LEVEL]
    int_low_level = df[COL_INTERNAL_LOW_LEVEL]

    prev_int_high = int_high_level.ffill().shift(1)
    prev_int_low = int_low_level.ffill().shift(1)

    is_int_high_conf = int_high_level.notna()
    is_int_low_conf = int_low_level.notna()
    int_lower_high_event = is_int_high_conf & (int_high_level < prev_int_high)
    int_higher_low_event = is_int_low_conf & (int_low_level > prev_int_low)

    int_bias_segment_id = internal_bias.fillna(0).diff().ne(0).cumsum()

    int_lower_high_cum = int_lower_high_event.astype(int).groupby(int_bias_segment_id).cumsum()
    int_failed_high_in_segment = int_lower_high_cum > 0

    int_higher_low_cum = int_higher_low_event.astype(int).groupby(int_bias_segment_id).cumsum()
    int_failed_low_in_segment = int_higher_low_cum > 0

    int_failed_high_at_flip = int_failed_high_in_segment.shift(1).fillna(False).astype(bool)
    choch_plus_internal_bullish = internal_choch_bullish & int_failed_high_at_flip

    int_failed_low_at_flip = int_failed_low_in_segment.shift(1).fillna(False).astype(bool)
    choch_plus_internal_bearish = internal_choch_bearish & int_failed_low_at_flip

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
    result[COL_CHOCH_PLUS_SWING_BULLISH] = choch_plus_bullish.astype(bool)
    result[COL_CHOCH_PLUS_SWING_BEARISH] = choch_plus_bearish.astype(bool)
    result[COL_CHOCH_PLUS_INTERNAL_BULLISH] = choch_plus_internal_bullish.astype(bool)
    result[COL_CHOCH_PLUS_INTERNAL_BEARISH] = choch_plus_internal_bearish.astype(bool)

    return result
