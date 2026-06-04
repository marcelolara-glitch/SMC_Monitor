"""AnalyzeResult — Container imutável do output de analyze().

OBJETIVO
    Empacotar df expandido + ledgers de OB e FVG + meta de execução
    numa única estrutura tipada, com semântica imutável.

FONTE DE DADOS
    Produzido exclusivamente por smc_engine.engine.analyze().

LIMITAÇÕES CONHECIDAS
    frozen=True + eq=False são deliberados:
    - frozen=True garante imutabilidade semântica
    - eq=False impede __eq__ default que falharia em DataFrames
      ("ambiguous truth value"). Comparação programática deve usar
      pd.testing.assert_frame_equal por campo.
    Novos campos serão adicionados em ondas futuras (ex.: Onda 9.5
    adicionará df_setup_state) e devem ter default para não quebrar
    callers existentes.

NÃO FAZER
    Não serializar AnalyzeResult diretamente (ex.: JSON dump da
    instância inteira). Use mapping explícito de cada campo no
    consumidor (ex.: generate_golden_engine_output.py do PR 2).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd


@dataclass(frozen=True, eq=False)
class AnalyzeResult:
    """Output empacotado de smc_engine.engine.analyze().

    Campos:
        df: DataFrame original + 95 colunas dos 6 módulos das Ondas 3-8.
        ledger_ob: ledger de Order Blocks (12 colunas, ver
            order_blocks._build_ledger). 1 row por OB.
        ledger_fvg: ledger de Fair Value Gaps (11 colunas, ver
            fvg._build_ledger). 1 row por FVG. is_double populado
            pela Onda 7.2 (BPR).
        ledger_bpr: ledger de Balanced Price Ranges (7 colunas, ver
            fvg.compose_balanced_price_ranges). 1 row por BPR.
            Onda 7.2.
        meta: dict com metadados de execução:
            - engine_version: str (de smc_engine.__version__)
            - modules_run: list[str] (nomes das funções chamadas)
            - candle_count: int (len(df))
            - config_used: dict[str, Any] (asdict(config))
    """
    df: pd.DataFrame
    ledger_ob: pd.DataFrame
    ledger_fvg: pd.DataFrame
    ledger_bpr: pd.DataFrame = field(default_factory=pd.DataFrame)
    meta: dict[str, Any] = field(default_factory=dict)
    # Onda 9.5a — campo antecipado para a máquina de estados de setup.
    # Aditivo/opcional: `analyze()` não o popula (contrato primário é
    # df-only via compute_setup_state); default None para não quebrar
    # callers existentes (D3).
    df_setup_state: pd.DataFrame | None = None
