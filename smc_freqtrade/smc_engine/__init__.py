"""
OBJETIVO
    Pacote da engine SMC do projeto SMC_Freqtrade. Onda 1 expõe os
    tipos fundacionais e o container de estado. Onda 2 expõe os
    operadores ta.* stateless. Onda 3 expõe a detecção de pivots
    (swing/internal/equal). Onda 4 expõe trailing extremes +
    Premium/Discount. Onda 5 expõe BOS/CHoCH formal. Onda 6 expõe
    Order Blocks com mitigação. Onda 7 expõe Fair Value Gaps com
    mitigação. Onda 8 expõe Liquidity Sweep (indicador gratuito do
    LuxAlgo, separado do SMC principal). Onda 9: `analyze()`
    orquestra os 6 detectores das Ondas 3-8. Vide
    `smc_engine.engine.analyze`.

FONTE DE DADOS
    Não consome dados — apenas declarações. Os tipos espelham verbatim
    os UDTs e Persistent do fonte Pine compilado em
    tools/pynecore-validation/luxalgo_smc_compute_only.py.

LIMITAÇÕES CONHECIDAS
    Presets de SMCConfig (luxalgo_default, conservative, aggressive)
    adiados para Onda 10.

NÃO FAZER
    Não importar de freqtrade aqui (engine é Python puro).
    Não adicionar lógica SMC neste módulo.
"""
from pathlib import Path as _Path

_VERSION_PATH = _Path(__file__).resolve().parent.parent / "VERSION"
__version__ = _VERSION_PATH.read_text(encoding="utf-8").strip()

from .fvg import (
    detect_fair_value_gaps,
    COL_FVG_BULLISH_CREATED,
    COL_FVG_BEARISH_CREATED,
    COL_FVG_BULLISH_MITIGATED,
    COL_FVG_BEARISH_MITIGATED,
    COL_FVG_BULLISH_INVERSE_BROKEN,
    COL_FVG_BEARISH_INVERSE_BROKEN,
)
from .liquidity_sweep import (
    detect_liquidity_sweeps,
    COL_SWEEP_BULLISH_WICK,
    COL_SWEEP_BEARISH_WICK,
    COL_SWEEP_BULLISH_RETEST,
    COL_SWEEP_BEARISH_RETEST,
    COL_SWEEP_BULLISH_LEVEL_IDX,
    COL_SWEEP_BEARISH_LEVEL_IDX,
    COL_SWEEP_BULLISH_LEVEL_PRICE,
    COL_SWEEP_BEARISH_LEVEL_PRICE,
    COL_SWEEP_BULLISH_MITIGATED,
    COL_SWEEP_BEARISH_MITIGATED,
    COL_SWEEP_BULLISH_PD_ZONE,
    COL_SWEEP_BEARISH_PD_ZONE,
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
    detect_eqh_eql,
    detect_pivots,
    COL_SWING_HIGH_LEVEL,
    COL_SWING_HIGH_IDX,
    COL_SWING_LOW_LEVEL,
    COL_SWING_LOW_IDX,
    COL_INTERNAL_HIGH_LEVEL,
    COL_INTERNAL_HIGH_IDX,
    COL_INTERNAL_LOW_LEVEL,
    COL_INTERNAL_LOW_IDX,
    COL_EQUAL_HIGH_LEVEL,
    COL_EQUAL_HIGH_IDX,
    COL_EQUAL_HIGH_ALERT,
    COL_EQUAL_LOW_LEVEL,
    COL_EQUAL_LOW_IDX,
    COL_EQUAL_LOW_ALERT,
    COL_EQUAL_HIGH_LEVEL_MIDPOINT,
    COL_EQUAL_HIGH_PIVOT_INDICES,
    COL_EQUAL_LOW_LEVEL_MIDPOINT,
    COL_EQUAL_LOW_PIVOT_INDICES,
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
    LiquiditySweep,
    OrderBlock,
    Pivot,
    TrailingExtremes,
    Trend,
)

# === Onda 9 — Engine ===
from .config import SMCConfig
from .engine import analyze
from .result import AnalyzeResult

__all__ = [
    "__version__",
    # Onda 9 — engine orquestradora
    "analyze",
    "SMCConfig",
    "AnalyzeResult",
    # Dataclasses (UDTs)
    "Pivot",
    "Trend",
    "Alerts",
    "OrderBlock",
    "FairValueGap",
    "LiquiditySweep",
    "TrailingExtremes",
    # State container
    "EngineState",
    # Onda 3 — detecção de pivots (expansão completa para uso pela Onda 8)
    "detect_pivots",
    "COL_SWING_HIGH_LEVEL",
    "COL_SWING_HIGH_IDX",
    "COL_SWING_LOW_LEVEL",
    "COL_SWING_LOW_IDX",
    "COL_INTERNAL_HIGH_LEVEL",
    "COL_INTERNAL_HIGH_IDX",
    "COL_INTERNAL_LOW_LEVEL",
    "COL_INTERNAL_LOW_IDX",
    "COL_EQUAL_HIGH_LEVEL",
    "COL_EQUAL_HIGH_IDX",
    "COL_EQUAL_HIGH_ALERT",
    "COL_EQUAL_LOW_LEVEL",
    "COL_EQUAL_LOW_IDX",
    "COL_EQUAL_LOW_ALERT",
    # Wave 8.2 — EQH/EQL canônico (Pine LuxAlgo `SMC Concepts`)
    "detect_eqh_eql",
    "COL_EQUAL_HIGH_LEVEL_MIDPOINT",
    "COL_EQUAL_HIGH_PIVOT_INDICES",
    "COL_EQUAL_LOW_LEVEL_MIDPOINT",
    "COL_EQUAL_LOW_PIVOT_INDICES",
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
    "COL_FVG_BULLISH_INVERSE_BROKEN",
    "COL_FVG_BEARISH_INVERSE_BROKEN",
    # Onda 8 — Liquidity Sweep (LuxAlgo gratuito, separado do SMC)
    "detect_liquidity_sweeps",
    "COL_SWEEP_BULLISH_WICK",
    "COL_SWEEP_BEARISH_WICK",
    "COL_SWEEP_BULLISH_RETEST",
    "COL_SWEEP_BEARISH_RETEST",
    "COL_SWEEP_BULLISH_LEVEL_IDX",
    "COL_SWEEP_BEARISH_LEVEL_IDX",
    "COL_SWEEP_BULLISH_LEVEL_PRICE",
    "COL_SWEEP_BEARISH_LEVEL_PRICE",
    "COL_SWEEP_BULLISH_MITIGATED",
    "COL_SWEEP_BEARISH_MITIGATED",
    "COL_SWEEP_BULLISH_PD_ZONE",
    "COL_SWEEP_BEARISH_PD_ZONE",
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
