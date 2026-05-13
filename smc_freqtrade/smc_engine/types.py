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
    """Mapeia `orderBlock` UDT (Pine linhas 46-50), estendido na Onda 6.

    OBJETIVO
        UDT canônico de Order Block produzido por
        `smc_engine.order_blocks.detect_order_blocks` (Onda 6). Os 4
        campos originais (`bar_high`, `bar_low`, `bar_time`, `bias`)
        mapeiam 1:1 o UDT Pine. Os 6 campos novos
        (`t_creation`, `t_mitigation`, `t_invalidation`, `scope`,
        `state`, `volumetric_intensity`) suportam o ciclo de vida
        multi-candle do OB em pandas, sem equivalente direto no Pine
        (que mantém o ciclo via remoção de array global).

    FONTE DE DADOS
        Pine fonte:
            @udt
            class orderBlock:
                barHigh: float = na(float)
                barLow: float = na(float)
                barTime: int = na(int)
                bias: int = na(int)

        Convenção temporal: `bar_time` ≡ t_origin = timestamp da vela
        parsed-extreme dentro da janela `[pivot_idx, break_idx)`.
        Briefing Onda 6 §2 P12 — interface preservation, NÃO renomear.

    LIMITAÇÕES CONHECIDAS
        Wave 6 emite apenas `state ∈ {'active', 'mitigated'}`. Valor
            `'breaker'` é hook reservado para Onda 6.2 (Breaker
            Blocks).
        Wave 6 NÃO computa `volumetric_intensity` — sempre None. Hook
            para Onda 6.1 (Volumetric OB), que preencherá com fração
            `buy_volume / total_volume` da janela.
        Wave 6 NÃO computa `t_invalidation` — sempre None. Hook para
            semântica futura de invalidação pós-mitigação (Onda 6.2).

    NÃO FAZER
        Não renomear `bar_time` → `t_origin` (briefing Onda 6 §2 P12).
        Não preencher os 3 campos reservados em Wave 6.
        Não adicionar métodos comportamentais (is_mitigated, etc.) —
            ciclo de vida é responsabilidade do módulo `order_blocks`.
    """
    bar_high: Optional[float] = None
    bar_low: Optional[float] = None
    bar_time: Optional[int] = None
    bias: Optional[int] = None
    t_creation: Optional[int] = None
    t_mitigation: Optional[int] = None
    t_invalidation: Optional[int] = None
    scope: str = 'swing'
    state: str = 'active'
    volumetric_intensity: Optional[float] = None


@dataclass
class FairValueGap:
    """Mapeia `fairValueGap` UDT (Pine linhas 30-33), estendido na Onda 7.

    OBJETIVO
        UDT canônico de Fair Value Gap produzido por
        `smc_engine.fvg.detect_fair_value_gaps` (Onda 7). Os 3 campos
        originais (`top`, `bottom`, `bias`) mapeiam 1:1 o UDT Pine. Os
        7 campos novos (`bar_time`, `t_creation`, `t_mitigation`,
        `t_invalidation`, `state`, `is_inverse`, `is_double`)
        suportam o ciclo de vida multi-candle do FVG em pandas e
        reservam hooks para as Ondas 7.1 (Inverse FVG) e 7.2
        (Double FVG / BPR).

    FONTE DE DADOS
        Pine fonte:
            @udt
            class fairValueGap:
                top: float = na(float)
                bottom: float = na(float)
                bias: int = na(int)

        Convenção temporal (briefing Onda 7 §4.5 + D5):
            `bar_time` = timestamp do **primeiro** candle do padrão
                de 3 (= âncora estrutural; define o nível do gap).
            `t_creation` = timestamp do **terceiro** candle (momento
                em que o gap fica conhecido; alinhado com Mapa
                §7.6.1).
            Em FVG, `bar_time ≠ t_creation` por construção — diferente
                da Wave 6 OB onde coincidem (P12).

        Convenção geométrica do gap (briefing Onda 7 §4.4 invariante 1):
            `top` = limite superior do gap (sempre maior).
            `bottom` = limite inferior do gap (sempre menor).
            Para bullish: top = low[t], bottom = high[t-2].
            Para bearish: top = low[t-2], bottom = high[t]
                (normalizado — diferente do Pine literal onde
                top = high[t] < bottom = low[t-2]).

    LIMITAÇÕES CONHECIDAS
        Wave 7 emite apenas `state ∈ {'active', 'mitigated'}`. Hook
            para futuro `'breaker'` análogo à Onda 6.2 fica reservado
            implicitamente via campo string.
        Wave 7 NÃO popula `t_invalidation` — sempre None. Hook para
            semântica futura de invalidação pós-mitigação.
        Wave 7 NÃO detecta Inverse FVG (Onda 7.1) — campo
            `is_inverse` sempre False.
        Wave 7 NÃO detecta Double FVG / BPR (Onda 7.2) — campo
            `is_double` sempre False.
        Wave 7 NÃO consume timeframe MTF (Onda 7.3) — assinatura
            atual é single-TF.
        Wave 7 NÃO aplica multiplicador `volatility_threshold` do
            LuxAlgo pago — hook reservado em assinatura futura.

    NÃO FAZER
        Não renomear `top`, `bottom`, `bias` — fiel ao Pine linhas
            46-50 e à Wave 1.
        Não preencher os 4 campos hook (`is_inverse`, `is_double`,
            e parâmetros MTF/volatility_threshold da assinatura) em
            Wave 7.
        Não adicionar métodos comportamentais (is_mitigated, etc.) —
            ciclo de vida é responsabilidade do módulo `fvg`.
        Não inferir `bar_time = t_creation` por analogia com Wave 6
            P12 — em FVG são distintos por construção (D5).
    """
    top: Optional[float] = None
    bottom: Optional[float] = None
    bias: Optional[int] = None
    bar_time: Optional[int] = None
    t_creation: Optional[int] = None
    t_mitigation: Optional[int] = None
    t_invalidation: Optional[int] = None
    state: str = 'active'
    is_inverse: bool = False
    is_double: bool = False


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
