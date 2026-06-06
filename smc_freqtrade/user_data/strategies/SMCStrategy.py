"""SMCStrategy — execução por trade (Wave 10b): entrada + SL ancorado + saída.

OBJETIVO
    Sobre o scaffold MTF da 10a (que já roda `analyze()` nos 3 TFs e o matcher
    `compute_setup_state` sobre o df mergeado), montar a maquinaria de execução
    por trade:
      1. **Entrada STRICT em `CONFIRMED`** (§3.1 do briefing 10b): `enter_long`/
         `enter_short` só quando `setup_state == 'CONFIRMED'` e `setup_direction`
         casa; `enter_tag = f"{setup_signature}_{setup_direction}"` (instrumentação
         10c: rótulo por assinatura×direção, agrupado nativamente pelo relatório
         de backtest). A identidade única (`setup_id`) migra para
         `custom_data['setup_id']` no fill, seguindo como chave da âncora/saída.
      2. **SL ancorado na zona do setup** (§3.2, caso canônico dos helpers
         nativos): `order_filled` lê, no candle causal, `setup_zone_low` (long) /
         `setup_zone_high` (short) e grava em `custom_data['sl_anchor']` (+ um
         buffer pequeno fora da zona). `custom_stoploss` lê a âncora e devolve
         `stoploss_from_absolute(...)`.
      3. **Saída determinística mínima** (§3.3): `custom_exit` sai por (a)
         invalidação estrutural — o `setup_id` do trade aparece `INVALIDATED` na
         linha causal atual — ou (b) alvo por R:R (default 2.0) ancorado em
         `|entry − sl_anchor|`; o que vier primeiro.
      4. **RESOLVED = tracking por trade** (§3.4): ao fechar, grava o desfecho
         (TP/SL/invalidação) em `custom_data['resolved']`. Estado pós-trade do
         Freqtrade — NÃO do engine (a FSM permanece `{ARMED, PENDING, CONFIRMED,
         INVALIDATED}`; `RESOLVED` não existe nela).

FONTE DE DADOS
    - MTF/matcher: ver as docstrings de `populate_indicators*` (herdadas da 10a,
      inalteradas). Colunas `setup_*` vêm de `compute_setup_state`; a âncora
      pronta é `setup_zone_low`/`setup_zone_high` (`setup_state.py:115-116`) —
      NÃO se remonta a zona das `active_*`.
    - Callbacks (assinaturas verbatim do Freqtrade 2026.3, confirmadas no venv):
      `order_filled(self, pair, trade, order, current_time, **kwargs)`
      (`interface.py:427`); `custom_stoploss(self, pair, trade, current_time,
      current_rate, current_profit, after_fill, **kwargs)` (`interface.py:441`);
      `custom_exit(self, pair, trade, current_time, current_rate, current_profit,
      **kwargs)` (`interface.py:589`).
    - `stoploss_from_absolute(stop_rate, current_rate, is_short, leverage)`
      (`strategy_helper.py:156`) converte preço de stop absoluto → stop relativo;
      o retorno positivo é consumido por `Trade.adjust_stop_loss` via
      `abs(stoploss/leverage)` (`trade_model.py:833-836`), produzindo o stop
      ABAIXO do preço em long e ACIMA em short. NÃO reimplementar o cálculo.
    - Persistência por trade: `Trade.set_custom_data(key, value)` /
      `Trade.get_custom_data(key, default=None)` (`trade_model.py:1386/1394`),
      sobrevive a reinício.
    - Dataframe analisado nos callbacks: `self.dp.get_analyzed_dataframe(pair,
      timeframe)` (`dataprovider.py:397`) — lido SEMPRE com filtro causal
      `date <= current_time` (§4).

LIMITAÇÕES CONHECIDAS
    - **Sem calibração** (10c): TP multi-nível (TP1/2/3), breakeven pós-TP1,
      trailing, ajuste de tamanho e poda/threshold de A3/A10 ficam para a 10c.
      Aqui é SL único ancorado + alvo único por R:R + invalidação estrutural.
    - `entry_mode='hybrid'` permanece stub (`NotImplementedError`) — antecipar
      entrada (ARMED/PENDING) é otimização não medida (§3.1). Só a 10c decide.
    - `startup_candle_count` é PROVISÓRIO (herdado da 10a); fixação empírica por
      `recursive-analysis` é gate da VM/10c.
    - Ratificação por **smoke sintético** (`tests/test_smoke_wave10b.py`): o
      ambiente do Code tem a rede da exchange bloqueada e golden com 0 CONFIRMED,
      então `lookahead-analysis`/`backtesting` com trades reais é gate da VM/10c.
    - `minimal_roi`/`stoploss` são floors neutros: `minimal_roi` praticamente
      desligado (saída é por `custom_exit`); `stoploss` é o teto de perda duro,
      abaixo do qual o SL ancorado nunca pode ir (`interface.py` docstring).

NÃO FAZER
    - Não consumir ledgers nem indexar o dataframe analisado por posição futura
      nos callbacks (§4 — lookahead migra do engine para cá no backtest). Só
      `trade`, `current_rate`, `current_time`, `current_profit`, `get_custom_data`
      e o df filtrado por `date <= current_time`.
    - Não reativar `hybrid`; não fazer TP multi-nível/breakeven/trailing (10c).
    - Não tocar `smc_engine/` nem a statelessness do `analyze()`.
    - Não bumpar `VERSION` (AGENTS §1.3) — decisão do Marcelo no merge.
"""
from __future__ import annotations

import sys
from pathlib import Path

from pandas import DataFrame

from freqtrade.strategy import IStrategy, informative, stoploss_from_absolute

# A engine SMC vive na raiz do subprojeto (`smc_freqtrade/smc_engine`), fora
# de `user_data/`. O resolver do Freqtrade só adiciona o diretório da
# estratégia ao path, então inserimos a raiz do subprojeto explicitamente.
_SUBPROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_SUBPROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_SUBPROJECT_ROOT))

from smc_engine import SetupConfig, analyze, compute_setup_state  # noqa: E402
from smc_engine.setup_state import (  # noqa: E402
    STATE_CONFIRMED,
    STATE_INVALIDATED,
    DIRECTION_LONG,
    DIRECTION_SHORT,
)


class SMCStrategy(IStrategy):
    """Execução por trade da engine SMC sobre o Freqtrade (Wave 10b).

    OBJETIVO
        Estender o scaffold MTF da 10a com a maquinaria de execução por trade:
        entrada strict em `CONFIRMED`, SL ancorado na zona do setup, saída
        determinística (invalidação estrutural | R:R) e tracking RESOLVED. Ver a
        docstring do módulo para o detalhamento de cada peça.

    FONTE DE DADOS
        MTF/matcher herdados da 10a (ver `populate_indicators*`). Callbacks e
        helpers nativos do Freqtrade 2026.3 (ver docstring do módulo, assinaturas
        verbatim do venv).

    LIMITAÇÕES CONHECIDAS
        Sem calibração (10c): SL único + alvo único por R:R + invalidação
        estrutural; sem TP multi-nível/breakeven/trailing. `hybrid` stub.
        `startup_candle_count` provisório (gate VM/10c). Ratificado por smoke
        sintético; selo empírico (lookahead-analysis + backtesting com trades
        reais) é gate da VM/10c.

    NÃO FAZER
        Não consumir ledgers; não indexar o df analisado por posição futura nos
        callbacks; não reativar `hybrid`; não tocar o engine; não bumpar VERSION.
    """

    INTERFACE_VERSION = 3

    timeframe = "15m"
    can_short = True
    process_only_new_candles = True

    # 10b: o SL ancorado por trade exige `custom_stoploss` ligado — sem isto o
    # callback nunca é chamado (`interface.py:1548`). Fonte: `interface.py:85`
    # (`use_custom_stoploss: bool = False`).
    use_custom_stoploss = True

    # PROVISÓRIO — cobre uma janela de `ta.atr(200)` no informativo 4H:
    # 200 candles 4H × (240/15) = 3200 candles base 15m. NÃO é o valor
    # ratificado por `recursive-analysis` (variância 0%): a fixação empírica
    # nativa está pendente na VM porque (a) o ambiente do Code bloqueia a API
    # da exchange (okx 403 → markets não carregam) e (b) a janela golden 4H
    # (720 candles) é mais curta que a convergência recursiva do `atr(200)`
    # com suavização de Wilder (~2,8k candles 4H p/ 1e-6). Ratificar na VM com
    # histórico 4H plurianual. Ver §5 do briefing 10a, docs/
    # AUDITORIA_CAUSALIDADE_W10.0.md §6.3 e o relatório do PR. (Herdado da 10a.)
    startup_candle_count: int = 3200

    # `minimal_roi` praticamente desligado (saída é por `custom_exit`, R:R/
    # invalidação). `stoploss` é o teto de perda duro: o SL ancorado nunca pode
    # ir abaixo dele (`interface.py` docstring do `custom_stoploss`).
    minimal_roi = {"0": 100}
    stoploss = -0.99

    # === Parâmetros 10b (sem calibração — defaults firmes, varredura é 10c) ===

    # `strict`: entra só em CONFIRMED (§3.1). `hybrid`: stub (NotImplementedError)
    # — antecipar ARMED/PENDING é otimização não medida; só a 10c decide.
    entry_mode: str = "strict"

    # Buffer pequeno FORA da zona ao ancorar o SL (§3.2): long → abaixo de
    # `zone_low`; short → acima de `zone_high`. Default de engenharia (a
    # varredura do buffer é 10c).
    sl_zone_buffer_pct: float = 0.001

    # Alvo por risco:retorno ancorado em `|entry − sl_anchor|` (§3.3b). Default
    # 2.0; TP multi-nível é 10c.
    rr_target: float = 2.0

    # === Chaves de `custom_data` (persistência por trade) ===
    # `setup_id`: a identidade única (hash da âncora) do setup causal do fill.
    # Movida do `enter_tag` para `custom_data` na 10c — o `enter_tag` passou a
    # carregar a assinatura×direção (`setup_signature_setup_direction`), legível
    # pelo relatório de backtest. O `setup_id` segue sendo a chave de casamento
    # da âncora/saída por trade (`_causal_setup_row`).
    SETUP_ID_KEY = "setup_id"
    SL_ANCHOR_KEY = "sl_anchor"
    RESOLVED_KEY = "resolved"

    # === Razões de saída de `custom_exit` (≤64 chars; `interface.py:606`) ===
    EXIT_STRUCTURAL = "smc_structural_invalidation"
    EXIT_RR = "smc_rr_target"

    # ------------------------------------------------------------------
    # Indicadores MTF + matcher (herdados da 10a — inalterados na 10b)
    # ------------------------------------------------------------------

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
            Não ler ledgers; não setar sinais aqui (é em `populate_entry_trend`).
        """
        dataframe = analyze(dataframe).df
        dataframe = compute_setup_state(dataframe, SetupConfig())
        return dataframe

    # ------------------------------------------------------------------
    # Entrada — STRICT em CONFIRMED (§3.1)
    # ------------------------------------------------------------------

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """Entrada STRICT: `enter_long`/`enter_short` em `CONFIRMED`, tag=assinatura×direção.

        OBJETIVO
            Emitir entrada exatamente nas linhas onde `setup_state ==
            'CONFIRMED'` e `setup_direction` casa com o lado, marcando
            `enter_tag = f"{setup_signature}_{setup_direction}"` (ex.: `"A3_long"`)
            — rótulo legível por assinatura×direção que o relatório de backtest
            agrupa nativamente (10c). A identidade única (`setup_id`) migra para
            `custom_data` no fill (`order_filled`), seguindo como chave da âncora/
            saída por trade.
        FONTE DE DADOS
            Colunas `setup_state`/`setup_direction`/`setup_signature` de
            `compute_setup_state` (já no df após `populate_indicators`).
        LIMITAÇÕES CONHECIDAS
            `entry_mode='hybrid'` é stub (`NotImplementedError`): antecipar
            ARMED/PENDING é otimização não medida (§3.1); só a 10c decide. Modo
            efetivo é `strict`.
        NÃO FAZER
            Não entrar fora de `CONFIRMED`; não inferir direção do trend (vem do
            matcher); não reativar `hybrid`.
        """
        if self.entry_mode == "hybrid":
            raise NotImplementedError(
                "entry_mode='hybrid' é stub nesta wave (§3.1 do briefing 10b): "
                "antecipar a entrada em ARMED/PENDING é otimização não medida. "
                "Reaberto só na 10c se o backtest provar necessidade. Use "
                "entry_mode='strict'."
            )

        confirmed = dataframe["setup_state"] == STATE_CONFIRMED
        long_sig = confirmed & (dataframe["setup_direction"] == DIRECTION_LONG)
        short_sig = confirmed & (dataframe["setup_direction"] == DIRECTION_SHORT)

        dataframe.loc[long_sig, "enter_long"] = 1
        dataframe.loc[short_sig, "enter_short"] = 1
        # `enter_tag = f"{setup_signature}_{setup_direction}"` (ex.: "A3_long"):
        # rótulo por assinatura×direção (agrupado nativamente pelo relatório de
        # backtest da 10c). `setup_signature`/`setup_direction` são não-nulos onde
        # o estado é CONFIRMED. A identidade única (`setup_id`) migra para
        # `custom_data` no fill (`order_filled`).
        dataframe.loc[long_sig, "enter_tag"] = (
            dataframe.loc[long_sig, "setup_signature"].astype(str)
            + "_" + dataframe.loc[long_sig, "setup_direction"].astype(str)
        )
        dataframe.loc[short_sig, "enter_tag"] = (
            dataframe.loc[short_sig, "setup_signature"].astype(str)
            + "_" + dataframe.loc[short_sig, "setup_direction"].astype(str)
        )
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """NO-OP — a saída determinística da 10b vive em `custom_exit` (callback).

        OBJETIVO
            Satisfazer a interface sem emitir sinais de saída vetorizados: a
            saída por invalidação estrutural e por R:R é decidida por trade em
            `custom_exit` (precisa de `trade`/`sl_anchor`, indisponíveis num
            `populate_*` vetorizado). Não seta `exit_*`.
        FONTE DE DADOS
            Nenhuma (passthrough). A decisão de saída lê `trade` +
            `get_custom_data` + df causal em `custom_exit`.
        LIMITAÇÕES CONHECIDAS
            Toda a saída 10b é por callback; este `populate_*` é deliberadamente
            vazio (idioma 2026.3 para saída dependente de estado por trade).
        NÃO FAZER
            Não setar `exit_long`/`exit_short` aqui (duplicaria a lógica de
            `custom_exit` sem acesso a `sl_anchor`).
        """
        return dataframe

    # ------------------------------------------------------------------
    # SL ancorado na zona (§3.2) — order_filled grava, custom_stoploss aplica
    # ------------------------------------------------------------------

    def order_filled(self, pair, trade, order, current_time, **kwargs):
        """Grava a âncora do SL no preenchimento da entrada; RESOLVED na saída.

        OBJETIVO
            (a) No fill da ORDEM DE ENTRADA, capturar o `setup_id` (identidade
            única) do setup ativo na linha causal e gravá-lo em
            `custom_data['setup_id']` — a chave de casamento da âncora/saída, já
            que o `enter_tag` agora carrega a assinatura×direção (10c). Em
            seguida, ler a zona do setup na linha causal (`setup_zone_low` long /
            `setup_zone_high` short) e gravar `custom_data['sl_anchor']` = borda
            da zona ± buffer (fora da zona). (b) No fill de uma ordem de SAÍDA
            (trade fechado), gravar o desfecho RESOLVED em
            `custom_data['resolved']` (§3.4).
        FONTE DE DADOS
            `order.ft_order_side == trade.entry_side` distingue entrada de saída
            (`trade_model.py:315`). `setup_id`: última linha causal com
            `setup_id` não-nulo (`date <= current_time`; FSM single → um setup
            ativo no candle do fill). Zona: `_causal_setup_row` casa por
            `custom_data['setup_id']` (causal — §4). RESOLVED: `trade.exit_reason`.
        LIMITAÇÕES CONHECIDAS
            A captura do `setup_id` e a âncora são gravadas uma vez (idempotente:
            se já existem, não re-gravam — cobre fills parciais/ajustes de
            posição, fora de escopo aqui). Sem a linha causal correspondente (df
            vazio/sem `setup_id`), não grava — `custom_stoploss` cai no `stoploss`
            duro até haver âncora.
        NÃO FAZER
            Não indexar o df por posição futura (§4); não remontar a zona das
            `active_*` (usar a âncora pronta `setup_zone_*`).
        """
        if order.ft_order_side != trade.entry_side:
            # Fill de saída → trade fechando: registra o desfecho RESOLVED.
            if not trade.is_open:
                self._record_resolved(trade)
            return

        # Fill de ENTRADA: captura o `setup_id` causal (chave da âncora/saída)
        # uma única vez. FSM single → no candle do fill há um setup ativo.
        if trade.get_custom_data(self.SETUP_ID_KEY) is None:
            setup_id = self._causal_setup_id(pair, current_time)
            if setup_id is not None:
                trade.set_custom_data(self.SETUP_ID_KEY, setup_id)

        # Ancora o SL uma única vez (lê a zona pela chave `custom_data['setup_id']`).
        if trade.get_custom_data(self.SL_ANCHOR_KEY) is not None:
            return
        anchor = self._compute_sl_anchor(pair, trade, current_time)
        if anchor is not None:
            trade.set_custom_data(self.SL_ANCHOR_KEY, anchor)

    def custom_stoploss(
        self, pair, trade, current_time, current_rate, current_profit,
        after_fill, **kwargs,
    ):
        """SL ancorado: converte o preço de âncora em stop relativo (nativo).

        OBJETIVO
            Ler `custom_data['sl_anchor']` (preço absoluto gravado em
            `order_filled`) e devolver o stop relativo via
            `stoploss_from_absolute(...)`. Em `after_fill=True`, fixa o SL
            inicial; nas chamadas seguintes, mantém o mesmo nível ancorado (sem
            trailing — isso é 10c).
        FONTE DE DADOS
            `trade.get_custom_data('sl_anchor')`, `current_rate`, `trade.is_short`,
            `trade.leverage`. `stoploss_from_absolute` (`strategy_helper.py:156`);
            o retorno positivo é aplicado por `adjust_stop_loss` como
            `abs(stoploss/leverage)` (`trade_model.py:833-836`) → stop ABAIXO do
            preço em long, ACIMA em short.
        LIMITAÇÕES CONHECIDAS
            Sem âncora ainda (entrada não preenchida / sem linha causal) →
            retorna `None`, mantendo o `stoploss` duro vigente. SL fixo (sem
            trailing/breakeven — 10c). O nível efetivo nunca passa do teto
            `self.stoploss`.
        NÃO FAZER
            Não reimplementar a conversão preço→ratio (usar o helper); não
            indexar dataframe aqui (a decisão é só `trade` + âncora).
        """
        anchor = trade.get_custom_data(self.SL_ANCHOR_KEY)
        if anchor is None:
            return None
        return stoploss_from_absolute(
            float(anchor),
            current_rate,
            is_short=trade.is_short,
            leverage=trade.leverage or 1.0,
        )

    # ------------------------------------------------------------------
    # Saída determinística (§3.3) — invalidação estrutural | R:R
    # ------------------------------------------------------------------

    def custom_exit(
        self, pair, trade, current_time, current_rate, current_profit, **kwargs,
    ):
        """Saída determinística: invalidação estrutural OU alvo por R:R.

        OBJETIVO
            Sair quando, o que vier primeiro: (a) o `setup_id` do trade aparece
            `INVALIDATED` na linha causal atual (invalidação estrutural); ou (b)
            o alvo por R:R (`rr_target`, default 2.0) ancorado em `|entry −
            sl_anchor|` é atingido por `current_rate`.
        FONTE DE DADOS
            (a) `self.dp.get_analyzed_dataframe` filtrado por `date <=
            current_time` e `setup_id == custom_data['setup_id']` (causal — §4),
            checando `setup_state == 'INVALIDATED'`. (b) `trade.open_rate`,
            `custom_data['sl_anchor']`, `current_rate`, `trade.is_short`.
        LIMITAÇÕES CONHECIDAS
            TP multi-nível, breakeven pós-TP1 e trailing são 10c — aqui é alvo
            único. Sem âncora, o ramo R:R fica inativo (só a invalidação
            estrutural pode disparar). A invalidação estrutural depende do
            `setup_id` reaparecer `INVALIDATED` na fonte (mecanismo selado por
            smoke; a frequência real é território da VM/10c).
        NÃO FAZER
            Não indexar o df por posição futura (§4); não ancorar o R:R em algo
            que não seja `|entry − sl_anchor|`.
        """
        if self._is_structurally_invalidated(pair, trade, current_time):
            return self.EXIT_STRUCTURAL
        if self._rr_target_reached(trade, current_rate):
            return self.EXIT_RR
        return None

    # ------------------------------------------------------------------
    # Helpers (puros o suficiente para o smoke sintético — §7)
    # ------------------------------------------------------------------

    def _causal_setup_id(self, pair, current_time):
        """`setup_id` da última linha causal com setup ativo (captura no fill).

        OBJETIVO
            Devolver o `setup_id` (identidade única) da linha (Series) mais
            recente com `date <= current_time` e `setup_id` não-nulo, ou `None`
            se não houver. FSM single-setup → no candle do fill há exatamente um
            setup ativo, então a última linha causal com `setup_id` é a
            inequívoca do trade. Usado por `order_filled` para mover a chave de
            casamento para `custom_data['setup_id']` (o `enter_tag` virou
            assinatura×direção).
        FONTE DE DADOS
            `self.dp.get_analyzed_dataframe(pair, self.timeframe)`.
        LIMITAÇÕES CONHECIDAS
            Df vazio (cache frio) ou sem nenhuma linha causal com `setup_id` →
            `None`.
        NÃO FAZER
            Não usar `iloc` futuro; o filtro `date <= current_time` é a barreira
            anti-lookahead.
        """
        df, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if df is None or df.empty or "setup_id" not in df.columns:
            return None
        causal = df[df["date"] <= current_time]
        rows = causal[causal["setup_id"].notna()]
        if rows.empty:
            return None
        return rows.iloc[-1]["setup_id"]

    def _causal_setup_row(self, pair, trade, current_time):
        """Última linha causal do df analisado para o `setup_id` deste trade.

        OBJETIVO
            Devolver a linha (Series) mais recente com `date <= current_time` e
            `setup_id == trade.get_custom_data('setup_id')`, ou `None` se não
            houver. É o ponto único de leitura causal do df nos callbacks (§4):
            liga a âncora/saída à identidade exata do trade pela chave em
            `custom_data` (o `enter_tag` agora carrega a assinatura×direção, não
            o hash). Lógica idêntica à 10b; só muda a chave de casamento.
        FONTE DE DADOS
            `self.dp.get_analyzed_dataframe(pair, self.timeframe)`;
            `trade.get_custom_data('setup_id')` (gravado em `order_filled`).
        LIMITAÇÕES CONHECIDAS
            Df vazio (cache frio), `setup_id` ainda não capturado, ou sem o
            `setup_id` no df causal → `None`.
        NÃO FAZER
            Não usar `iloc` futuro; o filtro `date <= current_time` é a barreira
            anti-lookahead.
        """
        df, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if df is None or df.empty or "setup_id" not in df.columns:
            return None
        setup_id = trade.get_custom_data(self.SETUP_ID_KEY)
        if setup_id is None:
            return None
        causal = df[df["date"] <= current_time]
        rows = causal[causal["setup_id"] == setup_id]
        if rows.empty:
            return None
        return rows.iloc[-1]

    def _compute_sl_anchor(self, pair, trade, current_time):
        """Preço de âncora do SL a partir da zona do setup (± buffer, fora dela).

        OBJETIVO
            Long → `setup_zone_low * (1 − sl_zone_buffer_pct)`; short →
            `setup_zone_high * (1 + sl_zone_buffer_pct)`. Buffer pequeno para
            colocar o stop FORA da zona (§3.2).
        FONTE DE DADOS
            `_causal_setup_row` → `setup_zone_low`/`setup_zone_high`.
        LIMITAÇÕES CONHECIDAS
            Sem linha causal / borda da zona NaN → `None` (não ancora).
        NÃO FAZER
            Não remontar a zona das `active_*` (usar a âncora pronta).
        """
        row = self._causal_setup_row(pair, trade, current_time)
        if row is None:
            return None
        if trade.is_short:
            zone_high = row["setup_zone_high"]
            if zone_high is None or zone_high != zone_high:  # NaN-safe
                return None
            return float(zone_high) * (1.0 + self.sl_zone_buffer_pct)
        zone_low = row["setup_zone_low"]
        if zone_low is None or zone_low != zone_low:  # NaN-safe
            return None
        return float(zone_low) * (1.0 - self.sl_zone_buffer_pct)

    def _is_structurally_invalidated(self, pair, trade, current_time):
        """True se o `setup_id` do trade está `INVALIDATED` na linha causal atual.

        OBJETIVO
            Saída por invalidação estrutural (§3.3a): a última linha causal com o
            `setup_id` do trade carrega `setup_state == 'INVALIDATED'`.
        FONTE DE DADOS
            `_causal_setup_row` → `setup_state`.
        LIMITAÇÕES CONHECIDAS
            Mecanismo selado por smoke; a frequência real é gate da VM/10c.
        NÃO FAZER
            Não olhar linhas com `date > current_time` (§4 — garantido por
            `_causal_setup_row`).
        """
        row = self._causal_setup_row(pair, trade, current_time)
        if row is None:
            return False
        return row["setup_state"] == STATE_INVALIDATED

    def _rr_target_reached(self, trade, current_rate):
        """True se `current_rate` atingiu o alvo por R:R ancorado em |entry−SL|.

        OBJETIVO
            Long → `current_rate >= entry + rr_target * risk`; short →
            `current_rate <= entry − rr_target * risk`, com `risk = |entry −
            sl_anchor|` (§3.3b).
        FONTE DE DADOS
            `trade.open_rate`, `custom_data['sl_anchor']`, `current_rate`,
            `trade.is_short`.
        LIMITAÇÕES CONHECIDAS
            Sem âncora ou `risk <= 0` → `False` (ramo inativo). Alvo único (TP
            multi-nível é 10c).
        NÃO FAZER
            Não ancorar o R:R em outra referência que não `|entry − sl_anchor|`.
        """
        anchor = trade.get_custom_data(self.SL_ANCHOR_KEY)
        if anchor is None:
            return False
        risk = abs(trade.open_rate - float(anchor))
        if risk <= 0.0:
            return False
        if trade.is_short:
            target = trade.open_rate - self.rr_target * risk
            return current_rate <= target
        target = trade.open_rate + self.rr_target * risk
        return current_rate >= target

    def _record_resolved(self, trade):
        """Grava o desfecho RESOLVED do trade fechado em `custom_data` (§3.4).

        OBJETIVO
            Classificar o desfecho a partir de `trade.exit_reason` em
            {`tp`, `sl`, `invalidation`, `other`} e gravar
            `custom_data['resolved']` = `{outcome, exit_reason, setup_id}`.
            RESOLVED é estado pós-trade do Freqtrade — NÃO do engine (§3.4).
        FONTE DE DADOS
            `trade.exit_reason` (`EXIT_RR` → tp; `EXIT_STRUCTURAL` →
            invalidation; `'stoploss'` → sl), `trade.enter_tag`.
        LIMITAÇÕES CONHECIDAS
            Idempotente (não re-grava se já existe). `other` cobre saídas não
            mapeadas (ex.: `force_exit`).
        NÃO FAZER
            Não escrever RESOLVED na coluna do engine (a FSM permanece de 4
            estados); é só `custom_data`.
        """
        if trade.get_custom_data(self.RESOLVED_KEY) is not None:
            return
        reason = trade.exit_reason
        if reason == self.EXIT_RR:
            outcome = "tp"
        elif reason == self.EXIT_STRUCTURAL:
            outcome = "invalidation"
        elif reason == "stoploss":
            outcome = "sl"
        else:
            outcome = "other"
        trade.set_custom_data(
            self.RESOLVED_KEY,
            {
                "outcome": outcome,
                "exit_reason": reason,
                "setup_id": trade.enter_tag,
            },
        )
