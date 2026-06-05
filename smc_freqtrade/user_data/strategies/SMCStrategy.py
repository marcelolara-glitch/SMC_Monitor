"""SMCStrategy — esqueleto IStrategy (Wave 10a): MTF + matcher, sem trade.

OBJETIVO
    Plumbing determinístico que (a) roda a engine SMC `analyze()` nos três
    timeframes (15m base, 1H, 4H), (b) deixa o Freqtrade fazer o merge
    multi-TF nativamente via `@informative`, e (c) roda o matcher de setups
    `compute_setup_state()` sobre o df já mergeado. A 10a NÃO toma decisão de
    trade: `populate_entry/exit_trend` são no-op (entrada/saída é a 10b).

FONTE DE DADOS
    - Engine `smc_engine.analyze(df) -> AnalyzeResult` (single-TF, causal):
      consome OHLCV e devolve `df` + 101 colunas + ledgers. Aqui só o `df` é
      usado; os ledgers são descartados de propósito (carregam `t_mitigation`
      futuro = vazamento — ver docs/AUDITORIA_CAUSALIDADE_W10.0.md §4).
    - Merge MTF: `@informative('4h')`/`@informative('1h')` do Freqtrade 2026.3
      sufixam cada coluna como `{coluna}_{tf}` e mergeiam ANTES de
      `populate_indicators` (verbatim `strategy/interface.py::advise_indicators`
      e `strategy/informative_decorator.py`). O shift anti-lookahead inter-TF
      é do `merge_informative_pair` (`strategy/strategy_helper.py`).
    - Matcher `smc_engine.compute_setup_state(df, SetupConfig())`: lê viés do
      sufixo `_4h` (`trend_suffix`), zona do `_1h` (`zone_suffix`) e
      confirmação da base 15m (sem sufixo). Exige as colunas já mergeadas.

LIMITAÇÕES CONHECIDAS
    - `startup_candle_count` é fixado empiricamente por `recursive-analysis`
      (variância 0%), não arbitrado. Dominado por `ta.atr(200)` no 4H, ou seja
      ~200 candles 4H × 16 = ~3200 candles base 15m.
    - Consome SOMENTE colunas causais (`active_*`, `setup_*`, OHLC, sweep,
      choch); NUNCA os ledgers em `populate_*`.
    - Sem lógica de entrada/saída, callbacks ou backtest aqui (10b/10c).
    - `minimal_roi`/`stoploss` são placeholders neutros que só satisfazem a
      interface; não são a estratégia.

NÃO FAZER
    - Não anexar ledgers ao df nem lê-los em `populate_*` (vazamento de futuro).
    - Não setar `enter_long`/`enter_short`/`exit_*` (é a 10b).
    - Não usar `tools/mtf_align.py` aqui (é espelho de teste; produção usa
      `@informative` nativo).
    - Não alterar o engine por motivo de lookahead (é causal por construção).
"""
from __future__ import annotations

import sys
from pathlib import Path

from pandas import DataFrame

from freqtrade.strategy import IStrategy, informative

# A engine SMC vive na raiz do subprojeto (`smc_freqtrade/smc_engine`), fora
# de `user_data/`. O resolver do Freqtrade só adiciona o diretório da
# estratégia ao path, então inserimos a raiz do subprojeto explicitamente.
_SUBPROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_SUBPROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_SUBPROJECT_ROOT))

from smc_engine import SetupConfig, analyze, compute_setup_state  # noqa: E402


class SMCStrategy(IStrategy):
    """Esqueleto MTF da engine SMC sobre o Freqtrade (Wave 10a, sem trade).

    OBJETIVO
        Carregar no Freqtrade 2026.3, rodar a engine nos 3 TFs (15m/1H/4H),
        deixar o Freqtrade mergear, e rodar o matcher sobre o df combinado.
        Estabelece o ponto de entrada da camada IStrategy; não decide trade.

    FONTE DE DADOS
        Ver docstring do módulo (engine `analyze`, merge `@informative`,
        matcher `compute_setup_state`).

    LIMITAÇÕES CONHECIDAS
        Sem sinais (no-op em entry/exit). `startup_candle_count` é PROVISÓRIO
        (cobre `ta.atr(200)` no 4H); a fixação empírica por `recursive-analysis`
        nativo (variância 0%) fica pendente de ratificação na VM — ver o
        comentário do atributo e o relatório do PR. Recomendação de bump-alvo
        no merge: minor `0.10.0` (decisão do Marcelo; o Code não bumpa
        `VERSION`).

    NÃO FAZER
        Não consumir ledgers; não setar colunas de sinal; não tocar o engine.
    """

    INTERFACE_VERSION = 3

    timeframe = "15m"
    can_short = True
    process_only_new_candles = True

    # PROVISÓRIO — cobre uma janela de `ta.atr(200)` no informativo 4H:
    # 200 candles 4H × (240/15) = 3200 candles base 15m. NÃO é o valor
    # ratificado por `recursive-analysis` (variância 0%): a fixação empírica
    # nativa está pendente na VM porque (a) o ambiente do Code bloqueia a API
    # da exchange (okx 403 → markets não carregam) e (b) a janela golden 4H
    # (720 candles) é mais curta que a convergência recursiva do `atr(200)`
    # com suavização de Wilder (~2,8k candles 4H p/ 1e-6). Ratificar na VM com
    # histórico 4H plurianual. Ver §5 do briefing 10a, docs/
    # AUDITORIA_CAUSALIDADE_W10.0.md §6.3 e o relatório do PR.
    startup_candle_count: int = 3200

    # Placeholders neutros — só satisfazem a interface. A camada de
    # entrada/saída (ROI/SL ancorado) é a 10b.
    minimal_roi = {"0": 100}
    stoploss = -0.99

    @informative("4h")
    def populate_indicators_4h(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """Engine SMC no 4H → colunas sufixadas `_4h` no merge nativo.

        OBJETIVO
            Rodar `analyze()` no informativo 4H; o Freqtrade sufixa cada
            coluna como `{coluna}_4h` e mergeia antes de `populate_indicators`.
        FONTE DE DADOS
            `analyze(dataframe).df` (single-TF, causal). Ledgers descartados.
        LIMITAÇÕES CONHECIDAS
            O viés de tendência (`swing_trend_bias_4h`) consumido pelo matcher
            vem daqui (`trend_suffix='4h'`).
        NÃO FAZER
            Não anexar ledgers; não decidir trade.
        """
        return analyze(dataframe).df

    @informative("1h")
    def populate_indicators_1h(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """Engine SMC no 1H → colunas sufixadas `_1h` no merge nativo.

        OBJETIVO
            Rodar `analyze()` no informativo 1H; o Freqtrade sufixa cada
            coluna como `{coluna}_1h` e mergeia antes de `populate_indicators`.
        FONTE DE DADOS
            `analyze(dataframe).df` (single-TF, causal). Ledgers descartados.
        LIMITAÇÕES CONHECIDAS
            As zonas ativas (`active_*_1h`) consumidas pelo matcher vêm daqui
            (`zone_suffix='1h'`).
        NÃO FAZER
            Não anexar ledgers; não decidir trade.
        """
        return analyze(dataframe).df

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """Engine base 15m + matcher sobre o df já mergeado com `_1h`/`_4h`.

        OBJETIVO
            Neste ponto o `dataframe` já contém as colunas `_1h`/`_4h` (o merge
            `@informative` ocorre antes — `interface.py::advise_indicators`).
            Roda `analyze()` para as colunas base 15m e depois
            `compute_setup_state()`, que lê `_4h` (viés), `_1h` (zona) e a base
            (confirmação).
        FONTE DE DADOS
            `analyze(dataframe).df` (base 15m) + `compute_setup_state(df,
            SetupConfig())`. `SetupConfig()` default casa com os TFs do
            scaffold: `trend_suffix='4h'`, `zone_suffix='1h'`, `signature='A3'`
            (a escolha de arquétipos é calibração da 10c).
        LIMITAÇÕES CONHECIDAS
            Ledgers descartados de propósito (não anexados ao df). Só colunas
            causais sobrevivem para `populate_*`.
        NÃO FAZER
            Não ler ledgers; não setar sinais aqui.
        """
        dataframe = analyze(dataframe).df
        dataframe = compute_setup_state(dataframe, SetupConfig())
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """NO-OP — a lógica de entrada é a 10b.

        OBJETIVO
            Satisfazer a interface sem emitir sinais. Não seta
            `enter_long`/`enter_short`.
        FONTE DE DADOS
            Nenhuma (passthrough).
        LIMITAÇÕES CONHECIDAS
            Zero entradas por construção (10a não decide trade).
        NÃO FAZER
            Não setar colunas de entrada (é a 10b).
        """
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """NO-OP — a lógica de saída é a 10b.

        OBJETIVO
            Satisfazer a interface sem emitir sinais. Não seta `exit_*`.
        FONTE DE DADOS
            Nenhuma (passthrough).
        LIMITAÇÕES CONHECIDAS
            Zero saídas por construção (10a não decide trade).
        NÃO FAZER
            Não setar colunas de saída (é a 10b).
        """
        return dataframe
