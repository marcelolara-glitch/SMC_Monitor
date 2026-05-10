"""
OBJETIVO
    Pacote da engine SMC do projeto SMC_Freqtrade. Onda 1 expõe os
    tipos fundacionais e o container de estado. Onda 2 expõe os
    operadores ta.* stateless. Onda 3 expõe a detecção de pivots
    (swing/internal/equal). Onda 4 expõe trailing extremes +
    Premium/Discount. Onda 5 expõe BOS/CHoCH formal.

FONTE DE DADOS
    Não consome dados — apenas declarações. Os tipos espelham verbatim
    os UDTs e Persistent do fonte Pine compilado em
    tools/pynecore-validation/luxalgo_smc_compute_only.py.

LIMITAÇÕES CONHECIDAS
    Não há função analyze() ainda. Tentativa de uso para detecção SMC
    completa falha com ImportError até Onda 9.

NÃO FAZER
    Não importar de freqtrade aqui (engine é Python puro).
    Não adicionar lógica SMC neste módulo.
"""
from .pivots import (
    detect_pivots,
    COL_SWING_HIGH_LEVEL,
    COL_SWING_LOW_LEVEL,
)
from .state import EngineState
from .structure import (
    detect_structure,
    COL_BOS_INTERNAL_BEARISH,
    COL_BOS_INTERNAL_BULLISH,
    COL_BOS_SWING_BEARISH,
    COL_BOS_SWING_BULLISH,
    COL_CHOCH_INTERNAL_BEARISH,
    COL_CHOCH_INTERNAL_BULLISH,
    COL_CHOCH_SWING_BEARISH,
    COL_CHOCH_SWING_BULLISH,
    COL_INTERNAL_TREND_BIAS,
    COL_SWING_TREND_BIAS,
)
from .trailing import (
    compute_trailing_extremes,
    COL_TRAILING_TOP,
    COL_TRAILING_BOTTOM,
    COL_PD_RATIO,
    COL_PD_ZONE,
    PD_ZONE_PREMIUM,
    PD_ZONE_DISCOUNT,
    PD_ZONE_EQUILIBRIUM,
)
from .types import (
    ATR,
    BEARISH,
    BEARISH_LEG,
    BULLISH,
    BULLISH_LEG,
    CLOSE,
    HIGHLOW,
    RANGE,
    Alerts,
    FairValueGap,
    OrderBlock,
    Pivot,
    TrailingExtremes,
    Trend,
)

__all__ = [
    # Dataclasses (UDTs)
    "Pivot",
    "Trend",
    "Alerts",
    "OrderBlock",
    "FairValueGap",
    "TrailingExtremes",
    # State container
    "EngineState",
    # Onda 3 — detecção de pivots
    "detect_pivots",
    # Onda 5 — BOS / CHoCH formal
    "detect_structure",
    "COL_BOS_INTERNAL_BEARISH",
    "COL_BOS_INTERNAL_BULLISH",
    "COL_BOS_SWING_BEARISH",
    "COL_BOS_SWING_BULLISH",
    "COL_CHOCH_INTERNAL_BEARISH",
    "COL_CHOCH_INTERNAL_BULLISH",
    "COL_CHOCH_SWING_BEARISH",
    "COL_CHOCH_SWING_BULLISH",
    "COL_INTERNAL_TREND_BIAS",
    "COL_SWING_TREND_BIAS",
    # Constantes int (Pine main() linhas 73-76)
    "BULLISH",
    "BEARISH",
    "BULLISH_LEG",
    "BEARISH_LEG",
    # Constantes string (Pine linhas 53-56)
    "ATR",
    "RANGE",
    "CLOSE",
    "HIGHLOW",
]
