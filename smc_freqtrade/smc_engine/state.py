"""
OBJETIVO
    Container de estado da engine SMC: 17 atributos persistentes do Pine
    fonte. Estado vive durante UMA chamada de analyze() (não persiste
    entre chamadas — Mapa Camada 1 §2 v1.1, e Verificação Freqtrade §1.2).

FONTE DE DADOS
    Inicialização verbatim do bloco `Persistent[...]` no main() do fonte
    Pine (linhas 78-94 de luxalgo_smc_compute_only.py).

    Pine fonte (verbatim):
        swingHigh: Persistent[pivot] = pivot(na, na, False)
        swingLow: Persistent[pivot] = pivot(na, na, False)
        internalHigh: Persistent[pivot] = pivot(na, na, False)
        internalLow: Persistent[pivot] = pivot(na, na, False)
        equalHigh: Persistent[pivot] = pivot(na, na, False)
        equalLow: Persistent[pivot] = pivot(na, na, False)
        swingTrend: Persistent[trend] = trend(0)
        internalTrend: Persistent[trend] = trend(0)
        fairValueGaps__global__: Persistent[list[fairValueGap]] = array.new(0, NA(fairValueGap))
        parsedHighs__global__: Persistent[list[float]] = array.new_float()
        parsedLows__global__: Persistent[list[float]] = array.new_float()
        highs__global__: Persistent[list[float]] = array.new_float()
        lows__global__: Persistent[list[float]] = array.new_float()
        times__global__: Persistent[list[int]] = array.new_int()
        trailing: Persistent[trailingExtremes] = trailingExtremes()
        swingOrderBlocks: Persistent[list[orderBlock]] = array.new(0, NA(orderBlock))
        internalOrderBlocks: Persistent[list[orderBlock]] = array.new(0, NA(orderBlock))

LIMITAÇÕES CONHECIDAS
    Não há método step() — lógica de transição vive nos módulos das
    ondas 3-9.
    Listas crescem sem bound nesta onda; decisão sliding-window adiada
    para Onda 6 (Order Blocks), conforme decisão pendente #2 do Mapa
    Camada 1 §8.

NÃO FAZER
    Não adicionar lógica SMC.
    Não serializar (sem demanda).
    Não compartilhar state entre TFs (cada @informative é isolado por
    construção do Freqtrade — Verificação Freqtrade §2.3).
    Não usar `deque(maxlen=...)`: incompatível com a semântica de
    `barIndex` posicional usada por `array.slice` no Pine.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .types import (
    FairValueGap,
    OrderBlock,
    Pivot,
    TrailingExtremes,
    Trend,
)


def _new_pivot_initial() -> Pivot:
    """Equivalente Python a `pivot(na, na, False)` do Pine.

    Reflete inicialização explícita das linhas 78-83 do Pine fonte:
        swingHigh: Persistent[pivot] = pivot(na, na, False)

    Os campos bar_time/bar_index permanecem None — Pine usa `time` e
    `bar_index` (símbolos do candle) como defaults da UDT, mas isso é
    uma quirk do Pine que não tem equivalente Python direto.
    Consumidor (Onda 3 em diante) trata o caso None.
    """
    return Pivot(current_level=None, last_level=None, crossed=False)


def _new_trend_zero() -> Trend:
    """Equivalente Python a `trend(0)` do Pine (linhas 84-85).

    O default do UDT Trend é `bias=None` (refletindo `na(int)`), mas o
    EngineState inicializa explicitamente com `bias=0` para fidelidade
    ao Pine fonte:
        swingTrend: Persistent[trend] = trend(0)
        internalTrend: Persistent[trend] = trend(0)
    """
    return Trend(bias=0)


@dataclass
class EngineState:
    """17 atributos persistentes do Pine fonte.

    Ordem 1:1 com a declaração no `main()` do Pine fonte, linhas 78-94.
    Total: 6 pivots + 2 trends + 6 listas globais (FVGs + OHLC parsed
    + tempos) + 1 trailing + 2 listas de OBs = 17.
    """
    # Pivots de longo/curto prazo (Pine linhas 78-83)
    swing_high: Pivot = field(default_factory=_new_pivot_initial)
    swing_low: Pivot = field(default_factory=_new_pivot_initial)
    internal_high: Pivot = field(default_factory=_new_pivot_initial)
    internal_low: Pivot = field(default_factory=_new_pivot_initial)
    equal_high: Pivot = field(default_factory=_new_pivot_initial)
    equal_low: Pivot = field(default_factory=_new_pivot_initial)

    # Trends (Pine linhas 84-85)
    swing_trend: Trend = field(default_factory=_new_trend_zero)
    internal_trend: Trend = field(default_factory=_new_trend_zero)

    # FVGs ativos (Pine linha 86)
    fair_value_gaps: list[FairValueGap] = field(default_factory=list)

    # Listas globais de OHLC processado (Pine linhas 87-91)
    parsed_highs: list[float] = field(default_factory=list)
    parsed_lows: list[float] = field(default_factory=list)
    highs: list[float] = field(default_factory=list)
    lows: list[float] = field(default_factory=list)
    times: list[int] = field(default_factory=list)

    # Trailing extremes (Pine linha 92)
    trailing: TrailingExtremes = field(default_factory=TrailingExtremes)

    # OBs ativos (Pine linhas 93-94)
    swing_order_blocks: list[OrderBlock] = field(default_factory=list)
    internal_order_blocks: list[OrderBlock] = field(default_factory=list)
