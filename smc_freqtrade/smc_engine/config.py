"""SMCConfig — Configuração unificada da engine SMC.

OBJETIVO
    Centralizar os parâmetros das Ondas 3-8 numa única dataclass
    imutável, com validação semântica e defaults LuxAlgo-aligned.

    Wave 8.2: removidos `eq_atr_length`/`eq_margin`/`eq_lookback_pivots`/
    `eq_min_pivots` introduzidos por engano na Wave 8.1 (eram do
    indicador `ICT Concepts`). A fórmula canônica do `SMC Concepts`
    reusa `pivot_equal_threshold` (0.1) já existente desde a Wave 3 e
    hardcoda ATR length=200 fiel ao Pine `ta.atr(200)`.

FONTE DE DADOS
    Defaults extraídos verbatim das assinaturas dos 6 detectores em
    smc_engine/{pivots,trailing,structure,order_blocks,fvg,
    liquidity_sweep}.py.

LIMITAÇÕES CONHECIDAS
    Presets (luxalgo_default, conservative, aggressive) adiados para
    Onda 10 conforme plano §2.5 — instanciação direta de SMCConfig()
    é o caminho atual.

NÃO FAZER
    Não adicionar campos para hooks futuros (is_inverse, is_double,
    volumetric_intensity, sweep_atr_threshold etc.) — esses ficam
    nas sub-ondas reservadas.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

PIVOT_MIN_LENGTH = 2
SWEEP_VALID_SOURCES = ('swing', 'internal', 'equal')


@dataclass(frozen=True)
class SMCConfig:
    # Onda 3 — Pivots (4 params; também usado pela detecção EQH/EQL
    # Wave 8.2: `pivot_equal_threshold` é o fator do Pine
    # `equalHighsLowsThresholdInput`; `pivot_equal_length` é o
    # `equalHighsLowsLengthInput`).
    pivot_swings_length: int = 50
    pivot_internal_length: int = 5
    pivot_equal_length: int = 3
    pivot_equal_threshold: float = 0.1
    # Onda 5 — Structure (1 param)
    structure_internal_filter_confluence: bool = False
    # Onda 6 — Order Blocks (3 params)
    ob_filter: Literal['Atr', 'Range'] = 'Atr'
    ob_mitigation: Literal['Close', 'Wick'] = 'Wick'
    ob_atr_length: int = 200
    # Onda 7 — FVG (2 params)
    fvg_auto_threshold: bool = True
    fvg_volatility_threshold: float | None = None
    # Onda 8 — Liquidity Sweep (4 params)
    sweep_pivot_sources: tuple[str, ...] = ('equal', 'internal')
    sweep_max_extension_bars: int = 300
    sweep_max_pivot_age_bars: int = 2000
    sweep_qualify_with_pd_zone: bool = False

    def __post_init__(self) -> None:
        """Validações semânticas. Levanta ValueError em violações."""
        if self.pivot_swings_length < PIVOT_MIN_LENGTH:
            raise ValueError(
                f"pivot_swings_length deve ser >= {PIVOT_MIN_LENGTH}, "
                f"recebeu {self.pivot_swings_length}"
            )
        if self.pivot_internal_length < PIVOT_MIN_LENGTH:
            raise ValueError(
                f"pivot_internal_length deve ser >= {PIVOT_MIN_LENGTH}, "
                f"recebeu {self.pivot_internal_length}"
            )
        if self.pivot_equal_length < PIVOT_MIN_LENGTH:
            raise ValueError(
                f"pivot_equal_length deve ser >= {PIVOT_MIN_LENGTH}, "
                f"recebeu {self.pivot_equal_length}"
            )
        if self.pivot_equal_threshold <= 0:
            raise ValueError(
                f"pivot_equal_threshold deve ser > 0, "
                f"recebeu {self.pivot_equal_threshold}"
            )
        if self.ob_atr_length < 1:
            raise ValueError(
                f"ob_atr_length deve ser >= 1, "
                f"recebeu {self.ob_atr_length}"
            )
        if self.sweep_max_extension_bars < 1:
            raise ValueError(
                f"sweep_max_extension_bars deve ser >= 1, "
                f"recebeu {self.sweep_max_extension_bars}"
            )
        if self.sweep_max_pivot_age_bars < 1:
            raise ValueError(
                f"sweep_max_pivot_age_bars deve ser >= 1, "
                f"recebeu {self.sweep_max_pivot_age_bars}"
            )
        if not self.sweep_pivot_sources:
            raise ValueError("sweep_pivot_sources não pode ser vazio")
        invalid_sources = set(self.sweep_pivot_sources) - set(SWEEP_VALID_SOURCES)
        if invalid_sources:
            raise ValueError(
                f"sweep_pivot_sources contém valores inválidos: {invalid_sources}. "
                f"Aceitos: {SWEEP_VALID_SOURCES}"
            )
