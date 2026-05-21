"""SMCConfig — Configuração unificada da engine SMC.

OBJETIVO
    Centralizar os parâmetros das Ondas 3-8 (+ Wave 8.1 EQH/EQL fix)
    numa única dataclass imutável, com validação semântica e defaults
    LuxAlgo-aligned.

FONTE DE DADOS
    Defaults extraídos verbatim das assinaturas dos 6 detectores em
    smc_engine/{pivots,trailing,structure,order_blocks,fvg,
    liquidity_sweep}.py. Wave 8.1: defaults canônicos do Pine LuxAlgo
    `ICT Concepts` (margin=4, lookback=50, count>2 → eq_min_pivots=3,
    ta.atr(10)).

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
# Wave 8.1 — Pine LuxAlgo `ICT Concepts`: input.float(4, minval=2, maxval=7).
EQ_MARGIN_MIN = 2.0
EQ_MARGIN_MAX = 7.0


@dataclass(frozen=True)
class SMCConfig:
    # Onda 3 — Pivots (4 params)
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
    # Onda 7 — FVG (1 param)
    fvg_auto_threshold: bool = True
    # Onda 8 — Liquidity Sweep (4 params)
    sweep_pivot_sources: tuple[str, ...] = ('equal', 'internal')
    sweep_max_extension_bars: int = 300
    sweep_max_pivot_age_bars: int = 2000
    sweep_qualify_with_pd_zone: bool = False
    # Wave 8.1 — EQH/EQL canônico (Pine LuxAlgo `ICT Concepts`)
    # Banda dinâmica: atr(eq_atr_length) / (10 / eq_margin).
    # Detecção: 3+ swings same-direction dentro da banda, look-back de
    # eq_lookback_pivots pivots prévios.
    eq_atr_length: int = 10
    eq_margin: float = 4.0
    eq_lookback_pivots: int = 50
    eq_min_pivots: int = 3

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
        # Wave 8.1 — EQH/EQL canônico.
        if self.eq_atr_length < 1:
            raise ValueError(
                f"eq_atr_length deve ser >= 1, recebeu {self.eq_atr_length}"
            )
        if not EQ_MARGIN_MIN <= self.eq_margin <= EQ_MARGIN_MAX:
            raise ValueError(
                f"eq_margin deve estar em [{EQ_MARGIN_MIN}, {EQ_MARGIN_MAX}] "
                f"(Pine LuxAlgo input.float minval/maxval); recebeu {self.eq_margin}"
            )
        if self.eq_lookback_pivots < 1:
            raise ValueError(
                f"eq_lookback_pivots deve ser >= 1, recebeu {self.eq_lookback_pivots}"
            )
        if self.eq_min_pivots < 2:
            raise ValueError(
                f"eq_min_pivots deve ser >= 2 (Pine `count > 2` exige 3+; "
                f"valor mínimo conceitual é 2 — duas observações iguais formam "
                f"uma 'igualdade'); recebeu {self.eq_min_pivots}"
            )
