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
    compose_balanced_price_ranges,
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
    COL_CHOCH_PLUS_SWING_BULLISH,
    COL_CHOCH_PLUS_SWING_BEARISH,
    COL_CHOCH_PLUS_INTERNAL_BULLISH,
    COL_CHOCH_PLUS_INTERNAL_BEARISH,
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

# === Onda 9.5a — Promoção de zona ativa + máquina de estados A3 ===
from .zone_projection import (
    promote_active_zones,
    ACTIVE_ZONE_COLUMNS,
    COL_ACTIVE_BULL_SWING_OB_TOP,
    COL_ACTIVE_BULL_SWING_OB_BOTTOM,
    COL_ACTIVE_BULL_SWING_OB_ID,
    COL_ACTIVE_BEAR_SWING_OB_TOP,
    COL_ACTIVE_BEAR_SWING_OB_BOTTOM,
    COL_ACTIVE_BEAR_SWING_OB_ID,
    COL_ACTIVE_BULL_FVG_TOP,
    COL_ACTIVE_BULL_FVG_BOTTOM,
    COL_ACTIVE_BULL_FVG_ID,
    COL_ACTIVE_BEAR_FVG_TOP,
    COL_ACTIVE_BEAR_FVG_BOTTOM,
    COL_ACTIVE_BEAR_FVG_ID,
    COL_ACTIVE_BULL_SWING_OB_VOLUME_PCT,
    COL_ACTIVE_BEAR_SWING_OB_VOLUME_PCT,
    COL_ACTIVE_BULL_IFVG_TOP,
    COL_ACTIVE_BULL_IFVG_BOTTOM,
    COL_ACTIVE_BULL_IFVG_ID,
    COL_ACTIVE_BEAR_IFVG_TOP,
    COL_ACTIVE_BEAR_IFVG_BOTTOM,
    COL_ACTIVE_BEAR_IFVG_ID,
)
# === Onda 9.5d — hooks Sessions (§10.6) + Fib/OTE (§10.3) ===
from .sessions import (
    tag_sessions,
    SESSION_COLUMNS,
    COL_IN_KZ_SILVER_BULLET_AM,
    COL_IN_KZ_SILVER_BULLET_LATE,
    COL_IN_KZ_SILVER_BULLET_PM,
)
from .fib_ote import (
    project_ote_zones,
    OTE_COLUMNS,
    OTE_RETRACE_LOW,
    OTE_RETRACE_HIGH,
    COL_ACTIVE_BULL_OTE_TOP,
    COL_ACTIVE_BULL_OTE_BOTTOM,
    COL_ACTIVE_BULL_OTE_ID,
    COL_ACTIVE_BEAR_OTE_TOP,
    COL_ACTIVE_BEAR_OTE_BOTTOM,
    COL_ACTIVE_BEAR_OTE_ID,
)
from .setup_state import (
    compute_setup_state,
    SetupConfig,
    Signature,
    SIGNATURES,
    SETUP_OUTPUT_COLUMNS,
    SETUP_STATES,
    INVALIDATION_REASONS,
    ENTRY_MODE_CONFIRMATION,
    ENTRY_MODE_RISK,
    ENTRY_MODE_HYBRID,
    ENTRY_MODES,
    STATE_ARMED,
    STATE_PENDING,
    STATE_CONFIRMED,
    STATE_INVALIDATED,
    DIRECTION_LONG,
    DIRECTION_SHORT,
    REASON_ESCAPED,
    REASON_TIMEOUT,
    REASON_TREND_CHANGED,
    REASON_ZONE_CROSSED,
    REASON_MITIGATED,
    COL_SETUP_ID,
    COL_SETUP_STATE,
    COL_SETUP_DIRECTION,
    COL_SETUP_ZONE_LOW,
    COL_SETUP_ZONE_HIGH,
    COL_SETUP_INVALIDATION_REASON,
)

__all__ = [
    "__version__",
    # Onda 9 — engine orquestradora
    "analyze",
    "SMCConfig",
    "AnalyzeResult",
    # Onda 9.5a — promoção de zona ativa por candle (§S1)
    "promote_active_zones",
    "ACTIVE_ZONE_COLUMNS",
    "COL_ACTIVE_BULL_SWING_OB_TOP",
    "COL_ACTIVE_BULL_SWING_OB_BOTTOM",
    "COL_ACTIVE_BULL_SWING_OB_ID",
    "COL_ACTIVE_BEAR_SWING_OB_TOP",
    "COL_ACTIVE_BEAR_SWING_OB_BOTTOM",
    "COL_ACTIVE_BEAR_SWING_OB_ID",
    "COL_ACTIVE_BULL_FVG_TOP",
    "COL_ACTIVE_BULL_FVG_BOTTOM",
    "COL_ACTIVE_BULL_FVG_ID",
    "COL_ACTIVE_BEAR_FVG_TOP",
    "COL_ACTIVE_BEAR_FVG_BOTTOM",
    "COL_ACTIVE_BEAR_FVG_ID",
    # Onda 9.5b — volume_pct do OB swing (A5) + zona IFVG (A4a)
    "COL_ACTIVE_BULL_SWING_OB_VOLUME_PCT",
    "COL_ACTIVE_BEAR_SWING_OB_VOLUME_PCT",
    "COL_ACTIVE_BULL_IFVG_TOP",
    "COL_ACTIVE_BULL_IFVG_BOTTOM",
    "COL_ACTIVE_BULL_IFVG_ID",
    "COL_ACTIVE_BEAR_IFVG_TOP",
    "COL_ACTIVE_BEAR_IFVG_BOTTOM",
    "COL_ACTIVE_BEAR_IFVG_ID",
    # Onda 9.5d — hooks Sessions (Silver Bullet §10.6)
    "tag_sessions",
    "SESSION_COLUMNS",
    "COL_IN_KZ_SILVER_BULLET_AM",
    "COL_IN_KZ_SILVER_BULLET_LATE",
    "COL_IN_KZ_SILVER_BULLET_PM",
    # Onda 9.5d — hook Fib/OTE (§10.3)
    "project_ote_zones",
    "OTE_COLUMNS",
    "OTE_RETRACE_LOW",
    "OTE_RETRACE_HIGH",
    "COL_ACTIVE_BULL_OTE_TOP",
    "COL_ACTIVE_BULL_OTE_BOTTOM",
    "COL_ACTIVE_BULL_OTE_ID",
    "COL_ACTIVE_BEAR_OTE_TOP",
    "COL_ACTIVE_BEAR_OTE_BOTTOM",
    "COL_ACTIVE_BEAR_OTE_ID",
    # Onda 9.5a/9.5b — máquina de estados + matcher declarativo
    "compute_setup_state",
    "SetupConfig",
    "Signature",
    "SIGNATURES",
    "SETUP_OUTPUT_COLUMNS",
    "SETUP_STATES",
    "INVALIDATION_REASONS",
    "ENTRY_MODE_CONFIRMATION",
    "ENTRY_MODE_RISK",
    "ENTRY_MODE_HYBRID",
    "ENTRY_MODES",
    "STATE_ARMED",
    "STATE_PENDING",
    "STATE_CONFIRMED",
    "STATE_INVALIDATED",
    "DIRECTION_LONG",
    "DIRECTION_SHORT",
    "REASON_ESCAPED",
    "REASON_TIMEOUT",
    "REASON_TREND_CHANGED",
    "REASON_ZONE_CROSSED",
    "REASON_MITIGATED",
    "COL_SETUP_ID",
    "COL_SETUP_STATE",
    "COL_SETUP_DIRECTION",
    "COL_SETUP_ZONE_LOW",
    "COL_SETUP_ZONE_HIGH",
    "COL_SETUP_INVALIDATION_REASON",
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
    "COL_CHOCH_PLUS_SWING_BULLISH",
    "COL_CHOCH_PLUS_SWING_BEARISH",
    "COL_CHOCH_PLUS_INTERNAL_BULLISH",
    "COL_CHOCH_PLUS_INTERNAL_BEARISH",
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
    # Onda 7.2 — Balanced Price Range (BPR)
    "compose_balanced_price_ranges",
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
