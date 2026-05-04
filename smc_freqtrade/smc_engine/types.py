"""
OBJETIVO
    Definir os 6 UDTs do indicador LuxAlgo SMC (compute-only) como
    @dataclass Python, em fidelidade verbatim ao fonte Pine compilado em
    tools/pynecore-validation/luxalgo_smc_compute_only.py.

FONTE DE DADOS
    Apenas declarações de tipos. Não consome dados de runtime.

    Cada dataclass mapeia 1:1 um UDT do Pine. Defaults `Optional[T] = None`
    refletem `na(T)` do Pine. Ordem dos campos é verbatim do Pine.

LIMITAÇÕES CONHECIDAS
    Inicializações com valores específicos (ex.: `pivot(na, na, False)`,
    `trend(0)`) acontecem no EngineState (state.py), não aqui.

    Pine usa defaults `barTime: int = time` e `barIndex: int = bar_index`
    em `pivot` UDT — esses símbolos são valores do candle atual, não
    constantes. Em Python, default é `None`; consumidor (Onda 3 em
    diante) trata o caso `None` na primeira chamada.

NÃO FAZER
    Não adicionar lógica de detecção SMC.
    Não adicionar métodos comportamentais (is_mitigated, etc.) — vão
    nos módulos das ondas 5-7.
    Não inventar campos que não existem no Pine.
    Não reordenar campos em relação ao Pine.
    Não importar de freqtrade nem pandas — engine é Python puro.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


# ============================================================
# Constantes verbatim do main() em luxalgo_smc_compute_only.py
# ============================================================

# Linhas 73-76 do Pine fonte (dentro de def main):
#     BULLISH_LEG: int = 1
#     BEARISH_LEG: int = 0
#     BULLISH: int = 1
#     BEARISH = -1
BULLISH: int = 1
BEARISH: int = -1
BULLISH_LEG: int = 1
BEARISH_LEG: int = 0

# Linhas 53-56 do Pine fonte (constantes string para inputs):
#     ATR: str = 'Atr'
#     RANGE: str = 'Cumulative Mean Range'
#     CLOSE: str = 'Close'
#     HIGHLOW: str = 'High/Low'
ATR: str = 'Atr'
RANGE: str = 'Cumulative Mean Range'
CLOSE: str = 'Close'
HIGHLOW: str = 'High/Low'


# ============================================================
# 6 UDTs (User-Defined Types) — Pine linhas 14-50
# ============================================================

@dataclass
class Pivot:
    """Mapeia `pivot` UDT (Pine linhas 39-44).

    Pine fonte:
        @udt
        class pivot:
            currentLevel: float = na(float)
            lastLevel: float = na(float)
            crossed: bool = na(bool)
            barTime: int = time          # Pine: símbolo do candle atual
            barIndex: int = bar_index    # idem
    """
    current_level: Optional[float] = None
    last_level: Optional[float] = None
    crossed: Optional[bool] = None
    bar_time: Optional[int] = None
    bar_index: Optional[int] = None


@dataclass
class Trend:
    """Mapeia `trend` UDT (Pine linhas 35-37).

    Pine fonte:
        @udt
        class trend:
            bias: int = na(int)

    Convenção do Pine para `bias`: 1 = BULLISH, -1 = BEARISH, 0 = neutro
    (não nomeado no Pine; usado literalmente como `trend(0)` na
    inicialização do EngineState).
    """
    bias: Optional[int] = None


@dataclass
class Alerts:
    """Mapeia `alerts` UDT (Pine linhas 14-31).

    Pine fonte:
        @udt
        class alerts:
            internalBullishBOS: bool = False
            internalBearishBOS: bool = False
            internalBullishCHoCH: bool = False
            internalBearishCHoCH: bool = False
            swingBullishBOS: bool = False
            swingBearishBOS: bool = False
            swingBullishCHoCH: bool = False
            swingBearishCHoCH: bool = False
            internalBullishOrderBlock: bool = False
            internalBearishOrderBlock: bool = False
            swingBullishOrderBlock: bool = False
            swingBearishOrderBlock: bool = False
            equalHighs: bool = False
            equalLows: bool = False
            bullishFairValueGap: bool = False
            bearishFairValueGap: bool = False

    Reset a cada candle (não é Persistent no Pine — é instanciado
    como `currentAlerts: alerts = alerts()` no início de main).

    Ordem dos 16 campos: 1:1 com o Pine fonte. Não reordenar.
    """
    internal_bullish_bos: bool = False
    internal_bearish_bos: bool = False
    internal_bullish_choch: bool = False
    internal_bearish_choch: bool = False
    swing_bullish_bos: bool = False
    swing_bearish_bos: bool = False
    swing_bullish_choch: bool = False
    swing_bearish_choch: bool = False
    internal_bullish_order_block: bool = False
    internal_bearish_order_block: bool = False
    swing_bullish_order_block: bool = False
    swing_bearish_order_block: bool = False
    equal_highs: bool = False
    equal_lows: bool = False
    bullish_fair_value_gap: bool = False
    bearish_fair_value_gap: bool = False


@dataclass
class OrderBlock:
    """Mapeia `orderBlock` UDT (Pine linhas 46-50).

    Pine fonte:
        @udt
        class orderBlock:
            barHigh: float = na(float)
            barLow: float = na(float)
            barTime: int = na(int)
            bias: int = na(int)
    """
    bar_high: Optional[float] = None
    bar_low: Optional[float] = None
    bar_time: Optional[int] = None
    bias: Optional[int] = None


@dataclass
class FairValueGap:
    """Mapeia `fairValueGap` UDT (Pine linhas 30-33).

    Pine fonte:
        @udt
        class fairValueGap:
            top: float = na(float)
            bottom: float = na(float)
            bias: int = na(int)
    """
    top: Optional[float] = None
    bottom: Optional[float] = None
    bias: Optional[int] = None


@dataclass
class TrailingExtremes:
    """Mapeia `trailingExtremes` UDT (Pine linhas 22-28).

    Pine fonte:
        @udt
        class trailingExtremes:
            top: float = na(float)
            bottom: float = na(float)
            barTime: int = na(int)
            barIndex: int = na(int)
            lastTopTime: int = na(int)
            lastBottomTime: int = na(int)
    """
    top: Optional[float] = None
    bottom: Optional[float] = None
    bar_time: Optional[int] = None
    bar_index: Optional[int] = None
    last_top_time: Optional[int] = None
    last_bottom_time: Optional[int] = None
