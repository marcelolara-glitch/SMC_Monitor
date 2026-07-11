"""ka_strategy — subclasse de teste que injeta setup determinístico (Wave 10.2).

OBJETIVO
    `KnownAnswerStrategy(SMCStrategyCandidate)` executa o código de
    entrada/execução **de produção** da candidata (arbitragem D3,
    `populate_entry_trend`, `order_filled`, `custom_stoploss`, `custom_exit`,
    RESOLVED) sobre colunas de setup **injetadas** de forma determinística — em
    vez de tentar fabricar OHLCV que dispare a FSM real (isso é frágil e já é
    coberto pelo golden da engine). É o harness que fecha o GE-0: valida a
    **camada de execução**, não a engine.

CRITÉRIO DE PUREZA (§3.1 do briefing 10.2)
    Esta subclasse SÓ pode sobrescrever:
      (i)  `populate_indicators` — trocado por injeção das colunas de setup
           (as 7 `SETUP_OUTPUT_COLUMNS` sufixadas `{col}__{sid}` dos 9 sids,
           via `ka_data.build_setup_columns`);
      (ii) `populate_indicators_1h` / `populate_indicators_4h` — reescritos SEM
           o decorador `@informative`, o que remove seu registro em
           `self._ft_informative` (o Freqtrade coleta os informativos varrendo
           `dir(self.__class__)` por métodos com o atributo `_ft_informative`, e
           o método sobrescrito no filho não o carrega — confirmado no código da
           versão instalada, `strategy/interface.py`); assim o backtest não exige
           dados 1h/4h.
      (iii) `startup_candle_count = 0` — o warmup de 3200 velas da candidata
           descartaria todo o OHLCV sintético curto; a injeção não precisa de
           warmup.
    `populate_entry_trend`, `order_filled`, `custom_stoploss`, `custom_exit` e a
    arbitragem D3 NÃO são tocados — o teste vale porque roda o código real.

NÃO FAZER
    - Não reimplementar nenhum callback de execução nem a arbitragem.
    - Não chamar `analyze()`/`compute_setup_state_multi` aqui (a injeção é o
      ponto do harness).
"""
from __future__ import annotations

import sys
from pathlib import Path

from pandas import DataFrame

_KA_DIR = Path(__file__).resolve().parent
_SUBPROJECT_ROOT = _KA_DIR.parents[1]
_STRATEGIES_DIR = _SUBPROJECT_ROOT / "user_data" / "strategies"
for _p in (str(_SUBPROJECT_ROOT), str(_STRATEGIES_DIR), str(_KA_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from SMCStrategyCandidate import SMCStrategyCandidate  # noqa: E402

import ka_data  # noqa: E402


class KnownAnswerStrategy(SMCStrategyCandidate):
    """Candidata com `populate_indicators` trocado por injeção determinística.

    O cenário ativo vem de `self.config['ka_scenario']` (setado pelo teste antes
    do backtest). Ver a docstring do módulo para o critério de pureza.
    """

    # Warmup neutralizado: a injeção não depende de histórico (a candidata usa
    # 3200 por causa do `atr(200)` no 4h informativo, aqui inexistente).
    startup_candle_count: int = 0

    # ------------------------------------------------------------------
    # Neutralização dos informativos herdados (@informative 1h/4h): reescrever
    # SEM o decorador remove o registro em `_ft_informative` (ver docstring).
    # ------------------------------------------------------------------
    def populate_indicators_4h(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        return dataframe

    def populate_indicators_1h(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        return dataframe

    # ------------------------------------------------------------------
    # Injeção determinística das colunas de setup (substitui analyze()+FSM).
    # ------------------------------------------------------------------
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """Injeta as colunas `{col}__{sid}` do cenário ativo (sem rodar a engine).

        O cenário vem de `self.config['ka_scenario']`. `ka_data.build_setup_columns`
        anexa, para os 9 sids, as 7 `SETUP_OUTPUT_COLUMNS` sufixadas — o material
        que `populate_entry_trend` (real) arbitra e que os callbacks (reais) leem.
        """
        scenario = self.config["ka_scenario"]
        return ka_data.build_setup_columns(scenario, dataframe)
