"""
OBJETIVO
    Pacote da engine SMC do projeto SMC_Freqtrade. Onda 1 expõe os
    tipos fundacionais e o container de estado. Onda 2 expõe os
    operadores ta.* stateless. Onda 3 expõe a detecção de pivots
    (swing/internal/equal). Lógica de BOS/CHoCH entra na Onda 5.

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
from .pivots import detect_pivots
from .state import EngineState
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
