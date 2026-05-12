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
from .fvg import (
    detect_fair_value_gaps,
    COL_FVG_BULLISH_CREATED,
    COL_FVG_BEARISH_CREATED,
    COL_FVG_BULLISH_MITIGATED,
    COL_FVG_BEARISH_MITIGATED,
)
from .order_blocks import (
    detect_order_blocks,
    COL_OB_INTERNAL_BEARISH_CREATED,
    COL_OB_INTERNAL_BEARISH_MITIGATED,
    COL_OB_INTERNAL_BULLISH_CREATED,
    COL_OB_INTERNAL_BULLISH_MITIGATED,
    COL_OB_SWING_BEARISH_CREATED,
    COL_OB_SWING_BEARISH_MITIGATED,
    COL_OB_SWING_BULLISH_CREATED,
    COL_OB_SWING_BULLISH_MITIGATED,
)
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
    "COL_SWING_HIGH_LEVEL",
    "COL_SWING_LOW_LEVEL",
    # Onda 4 — trailing extremes + Premium/Discount
    "compute_trailing_extremes",
    "COL_TRAILING_TOP",
    "COL_TRAILING_BOTTOM",
    "COL_PD_RATIO",
    "COL_PD_ZONE",
    "PD_ZONE_PREMIUM",
    "PD_ZONE_DISCOUNT",
    "PD_ZONE_EQUILIBRIUM",
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
    # Onda 6 — Order Blocks com mitigação
    "detect_order_blocks",
    "COL_OB_INTERNAL_BEARISH_CREATED",
    "COL_OB_INTERNAL_BEARISH_MITIGATED",
    "COL_OB_INTERNAL_BULLISH_CREATED",
    "COL_OB_INTERNAL_BULLISH_MITIGATED",
    "COL_OB_SWING_BEARISH_CREATED",
    "COL_OB_SWING_BEARISH_MITIGATED",
    "COL_OB_SWING_BULLISH_CREATED",
    "COL_OB_SWING_BULLISH_MITIGATED",
    # Onda 7 — Fair Value Gaps com mitigação
    "detect_fair_value_gaps",
    "COL_FVG_BULLISH_CREATED",
    "COL_FVG_BEARISH_CREATED",
    "COL_FVG_BULLISH_MITIGATED",
    "COL_FVG_BEARISH_MITIGATED",
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
