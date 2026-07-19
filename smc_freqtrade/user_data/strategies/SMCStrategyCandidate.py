"""SMCStrategyCandidate — estratégia paralela que executa a candidata congelada (Wave 10.1).

OBJETIVO
    Executar a **configuração-candidata congelada** (dois grupos, `docs/
    CONGELAMENTO_CANDIDATA_V2_E_GATES_EDGE.md`) sobre a camada IStrategy, com
    arbitragem D3 no consumidor (§1.3 do doc), SEM tocar em nada existente. É
    uma subclasse **paralela** de `SMCStrategy`: reusa toda a maquinaria de
    execução por trade (SL ancorado, saída por invalidação/R:R, RESOLVED) e
    sobrescreve apenas (1) os indicadores — `analyze` → `tag_sessions` →
    duas chamadas de `compute_setup_state_multi` (Grupo C, depois Grupo R);
    (2) a entrada — coleta os sids CONFIRMED por vela, arbitra D3 e emite
    `enter_long`/`enter_short` + `enter_tag = f"{sid}_{direção}"` só quando há
    vencedor; e (3) a resolução da linha causal dos callbacks, que passa a ler
    colunas sufixadas `{col}__{sid}` com `sid` parseado do `enter_tag`.

FONTE DE DADOS
    - Indicadores: `smc_engine.analyze` chamado 3× (base 15m + informativos 1h e
      4h obtidos por `self.dp.get_pair_dataframe`), mergeados pelo pipeline de
      paridade golden (`tools.mtf_align.align_informative`, sufixos `_1h`/`_4h`)
      — NÃO mais pelo `@informative` herdado (neutralizado nesta wave, §1 do
      briefing 10.5); `smc_engine.tag_sessions` (as 3 killzones que a A7 exige em
      `required_base`) e
      `smc_engine.setup_state.compute_setup_state_multi` (uma chamada por
      grupo; anexa `{col}__{sid}` para as 7 `SETUP_OUTPUT_COLUMNS`, sids
      disjuntos entre grupos → sem colisão).
    - Configs congeladas + arbitragem: `candidate_frozen` (`build_cfg_c`,
      `build_cfg_r`, `arbitrate_d3`, `SIDS_GRUPO_C`, `SIDS_GRUPO_R`).
    - Callbacks/helpers de execução: herdados de `SMCStrategy` (SL ancorado,
      `custom_stoploss`, `custom_exit`, RESOLVED); só a leitura causal muda
      de coluna não-sufixada para `{col}__{sid}`.

LIMITAÇÕES CONHECIDAS
    - `entry_mode` permanece `'strict'` (entra só em CONFIRMED); `hybrid`
      continua stub (`NotImplementedError`, herdado).
    - Sem known-answer harness (é a Wave 10.2) e sem backtest real (rede da
      exchange bloqueada no sandbox) — ratificação por smoke sintético.
    - Semântica de SL/RR/invalidação **idêntica** à base; nenhuma calibração
      nova nesta wave.

NÃO FAZER
    - Não tocar `SMCStrategy.py` nem `smc_engine/` (byte-idênticos).
    - Não arbitrar prioridade dentro de `compute_setup_state_multi` (D3 é do
      consumidor); não bumpar VERSION; não implementar known-answer (10.2).
    - Não ler colunas não-sufixadas nos callbacks (a candidata não emite
      colunas `setup_*` agregadas — só `{col}__{sid}`).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from pandas import DataFrame

# A engine SMC vive na raiz do subprojeto (`smc_freqtrade/smc_engine`), fora
# de `user_data/`. Mesmo mecanismo `_SUBPROJECT_ROOT` da SMCStrategy base.
_SUBPROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_SUBPROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_SUBPROJECT_ROOT))

from smc_engine import analyze, tag_sessions  # noqa: E402
from smc_engine.setup_state import (  # noqa: E402
    compute_setup_state_multi,
    SETUP_OUTPUT_COLUMNS,
    STATE_CONFIRMED,
    DIRECTION_LONG,
    DIRECTION_SHORT,
)

# Pipeline de paridade teste↔produção (Wave 10.5): a Candidate monta o MTF pelo
# MESMO helper que TODOS os testes golden/engine usam (`align_informative`,
# espelho de `merge_informative_pair`) em vez do merge herdado do `@informative`.
# Importado pelo mesmo mecanismo `_SUBPROJECT_ROOT` já usado para `smc_engine`
# (o resolver do Freqtrade só adiciona o diretório da estratégia ao path). A nota
# "não usar em produção" na docstring de `tools/mtf_align.py` reflete a
# arquitetura Wave 10 (@informative herdado) e é superada por esta wave — ver a
# adjudicação §1 do briefing 10.5 (paridade teste↔produção) e a docstring de
# `populate_indicators` abaixo. `tools/mtf_align.py` NÃO é tocado (§4).
from tools.mtf_align import align_informative  # noqa: E402

# Import da base e das configs congeladas (mesmo diretório de estratégias, que
# o resolver do Freqtrade adiciona ao path).
from SMCStrategy import SMCStrategy  # noqa: E402
from candidate_frozen import (  # noqa: E402
    build_cfg_c,
    build_cfg_r,
    arbitrate_d3,
    require_candidate_columns,
    SIDS_GRUPO_C,
    SIDS_GRUPO_R,
)

# Todos os sids da candidata, na ordem dos grupos (C depois R). A prioridade
# D3 é resolvida por `arbitrate_d3` — esta ordem é só de layout/iteração.
_ALL_SIDS: tuple = SIDS_GRUPO_C + SIDS_GRUPO_R

# Coluna diagnóstica: 1 na vela em que houve direções conflitantes (§1.3-2).
COL_SETUP_CONFLICT_DIRS = "setup_conflict_dirs"


def _na_to_none(v):
    """Coerção NA-safe de um valor escalar lido de coluna da engine → `None`.

    A engine emite `setup_state/direction/id/signature/invalidation_reason` como
    pandas StringDtype (`setup_state.py:1977-1983`), cujo sentinela de ausência é
    `pd.NA`; as zonas (`setup_zone_low/high`) são float64 (sentinela `NaN`). Um
    `pd.NA`/`NaN` avaliado em contexto booleano (`if v`, `v in (...)`) ou
    formatado numa tag levanta `TypeError: boolean value of NA is ambiguous`. Esta
    coerção normaliza qualquer nulo (`pd.NA`/`NaN`/`None`) para `None` — que é
    falsy e comparável sem ambiguidade — preservando o valor real quando presente.
    Escalar apenas (as 7 `SETUP_OUTPUT_COLUMNS` são escalares por vela).
    """
    return None if pd.isna(v) else v


class SMCStrategyCandidate(SMCStrategy):
    """Executa a candidata congelada (2 grupos) com arbitragem D3 no consumidor.

    OBJETIVO
        Ver a docstring do módulo. Subclasse paralela de `SMCStrategy` que só
        troca indicadores (multi por grupo), entrada (arbitragem D3) e a
        resolução causal dos callbacks (colunas `{col}__{sid}`).

    LIMITAÇÕES CONHECIDAS
        `entry_mode='strict'`; `hybrid` stub. Sem known-answer/backtest real
        (10.2/VM). Execução por trade idêntica à base.

    NÃO FAZER
        Não tocar a base nem a engine; não arbitrar no multi; não bumpar
        VERSION.
    """

    # Entra só em CONFIRMED (herdado). Explícito para deixar claro que a
    # candidata NÃO reabre `hybrid` nesta wave.
    entry_mode: str = "strict"

    # Warm-up (Wave 10.4 — ratificação; base `SMCStrategy` intocada em 3200).
    # Sobrescrito SÓ na Candidate para caber no teto de startup da OKX:
    #   (i) teto OKX 5×300 — `freqtrade/exchange/okx.py:78-79` retorna 300
    #       (`if candle_type in (CandleType.FUTURES, CandleType.SPOT): return
    #       300`) e `freqtrade/exchange/exchange.py:873`
    #       (`validate_required_startup_candles`, linhas ~887-897) só admite 5
    #       chamadas por par ⇒ máx. `candle_limit*5 − 1` = 300*5 − 1 = 1499
    #       (versão instalada: freqtrade 2026.3). O antigo 3200 estourava esse
    #       teto e reprovava na validação de startup do freqtrade.
    #   (ii) a convergência do ATR(200) 4H NÃO depende mais do startup: ela é
    #       garantida operacionalmente pelo **timerange estendido** do P3 (início
    #       ≥ 466 dias antes da janela congelada), já que `analyze()` é stateless
    #       sobre o dataframe carregado inteiro — o warm-up de 3200 candles 15m
    #       (≈200 candles 4H) era insuficiente para os ~2,8k candles 4H de
    #       convergência de qualquer forma. A janela congelada é recortada no
    #       relatório (`tools/p3_report.py --window-start`).
    #   (iii) ratificação: Wave 10.4; docs/AUDITORIA_CAUSALIDADE_W10.0.md §6.3
    #       (ratificação concluída — a fixação empírica do startup deixa de ser
    #       o mecanismo de warm-up).
    startup_candle_count: int = 1499

    # ------------------------------------------------------------------
    # Neutralização dos `@informative` herdados (Wave 10.5, §2.1 do briefing)
    #
    # A base `SMCStrategy` decora `populate_indicators_4h`/`populate_indicators_1h`
    # com `@informative`, o que registra os informativos em `_ft_informative` (o
    # Freqtrade coleta os informativos varrendo `dir(self.__class__)` por métodos
    # com o atributo `_ft_informative`). Sobrescrevendo esses métodos SEM o
    # decorador, a versão do filho não carrega `_ft_informative` e o registro sai
    # de `SMCStrategyCandidate._ft_informative` (fica vazio) — mecanismo já provado
    # na `KnownAnswerStrategy`. Assim o merge `@informative` herdado (e seu branch
    # de preenchimento de head em `merge_informative_pair`, que crashou o P3 em
    # `freqtrade/strategy/strategy_helper.py:96-109` com warm-up de 1499) sai do
    # grafo de execução; o MTF passa a ser montado pelo pipeline golden em
    # `populate_indicators`. Corpos no-op (não fazem merge nem tocam o df).
    # ------------------------------------------------------------------

    def populate_indicators_4h(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """No-op — substituído pelo pipeline de paridade (ver populate_indicators).

        Sobrescreve o método `@informative('4h')` da base SEM decorador para
        esvaziar `_ft_informative` (§2.1). O 4H passa a entrar pela chamada
        `analyze(dp.get_pair_dataframe(pair, '4h')).df` +
        `align_informative(..., suffix='4h')` em `populate_indicators`.
        """
        return dataframe

    def populate_indicators_1h(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """No-op — substituído pelo pipeline de paridade (ver populate_indicators).

        Sobrescreve o método `@informative('1h')` da base SEM decorador para
        esvaziar `_ft_informative` (§2.1). O 1H passa a entrar pela chamada
        `analyze(dp.get_pair_dataframe(pair, '1h')).df` +
        `align_informative(..., suffix='1h')` em `populate_indicators`.
        """
        return dataframe

    def informative_pairs(self):
        """Registra os informativos 1h/4h do par corrente (mecanismo clássico).

        OBJETIVO
            Como os `@informative` herdados foram neutralizados (§2.1), o
            Freqtrade precisa saber quais pares/TFs pré-carregar para que
            `self.dp.get_pair_dataframe(pair, '1h'|'4h')` (consumido em
            `populate_indicators`) tenha dados. Retorna as tuplas
            `(pair, '1h')`/`(pair, '4h')` para cada par da whitelist corrente —
            o formato canônico do Freqtrade ("The pairs need to be specified as
            tuples in the format `("pair", "timeframe")`" — doc verificado em
            `docs/VERIFICACAO_FREQTRADE.md §2.1`, verbatim da versão instalada).
        FONTE DE DADOS
            `self.dp.current_whitelist()` (padrão canônico do `informative_pairs`
            clássico — cobre backtest/live sem hardcodar o par).
        LIMITAÇÕES CONHECIDAS
            Sem `self.dp` (não injetado ainda) → lista vazia; o fail-loud da
            ausência de informativo fica em `populate_indicators` (guarda §2.4).
        NÃO FAZER
            Não retornar TFs fora de {'1h','4h'} (os únicos que a candidata
            mergeia); não reativar o `@informative` herdado.
        """
        if self.dp is None:
            return []
        pairs = self.dp.current_whitelist()
        return [(pair, tf) for pair in pairs for tf in ("1h", "4h")]

    # ------------------------------------------------------------------
    # Indicadores — pipeline de paridade golden:
    #   analyze(15m) → analyze(1h) → analyze(4h)
    #   → align_informative(_1h) → align_informative(_4h)
    #   → tag_sessions → multi(Grupo C) → multi(Grupo R)
    # ------------------------------------------------------------------

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """Pipeline MTF de paridade teste↔produção + FSM multi por grupo.

        OBJETIVO
            Montar o input multi-TF pelo MESMO pipeline que TODOS os testes
            golden/engine usam (§1 do briefing 10.5), abandonando o merge
            `@informative` herdado (neutralizado em `populate_indicators_1h/4h`):
            (1) `analyze()` na base 15m; (2) `analyze()` nos informativos 1h e 4h
            (`self.dp.get_pair_dataframe(pair, '1h'|'4h')`); (3)
            `align_informative` (espelho de `merge_informative_pair`,
            lookahead-safe) mergeando 1h e depois 4h com sufixos `_1h`/`_4h`
            idênticos aos dos testes; (4) `tag_sessions()` para as 3 killzones
            Silver Bullet (a A7 do Grupo R as exige em `required_base`, e a base
            não as taggeia); (5) `compute_setup_state_multi(df, build_cfg_c())` e,
            sobre o df já com as colunas do Grupo C,
            `compute_setup_state_multi(df, build_cfg_r())`. Sids disjuntos entre
            grupos → colunas `{col}__{sid}` não colidem (a função copia e anexa).
        FONTE DE DADOS
            `analyze(dataframe).df` (base 15m); `analyze(dp.get_pair_dataframe(
            pair, '1h'|'4h')).df` (informativos); `align_informative` (de
            `tools.mtf_align`); `tag_sessions`; `compute_setup_state_multi` (uma
            chamada por grupo, configs congeladas de `candidate_frozen`). `pair`
            vem de `metadata['pair']`.
        LIMITAÇÕES CONHECIDAS
            Não emite colunas `setup_*` agregadas (sem sufixo): a decisão D3 é
            de `populate_entry_trend`. Ledgers descartados (idioma da base).
        NÃO FAZER
            Não arbitrar prioridade aqui; não setar sinais (é na entrada); não
            prosseguir com informativo ausente (guarda fail-loud abaixo — §2.4).
        """
        pair = metadata["pair"]

        # Guarda fail-loud (§2.4): sem `dp` ou informativo vazio, PARAR — nunca
        # prosseguir com colunas `_1h`/`_4h` ausentes (o merge silencioso
        # produziria um df sem viés/zona e uma candidata muda, indistinguível de
        # "sem edge"). `require_candidate_columns` cobre a jusante, mas aqui a
        # causa é a fonte de dados, não a fiação da FSM.
        if self.dp is None:
            raise RuntimeError(
                "SMCStrategyCandidate.populate_indicators: self.dp indisponível — "
                "o pipeline de paridade (Wave 10.5) exige os informativos 1h/4h "
                "via dp.get_pair_dataframe; sem DataProvider não há como montar o "
                "MTF (§2.4). Verifique informative_pairs()/config."
            )

        inf_1h = self.dp.get_pair_dataframe(pair, "1h")
        inf_4h = self.dp.get_pair_dataframe(pair, "4h")
        for tf, inf in (("1h", inf_1h), ("4h", inf_4h)):
            if inf is None or len(inf) == 0:
                raise RuntimeError(
                    f"SMCStrategyCandidate.populate_indicators: informativo {tf} "
                    f"vazio/ausente para {pair!r} — o pipeline de paridade exige "
                    f"1h e 4h não-vazios para align_informative (§2.4). Verifique "
                    f"informative_pairs() e o histórico disponível do par."
                )

        base = analyze(dataframe).df
        res_1h = analyze(inf_1h).df
        res_4h = analyze(inf_4h).df

        merged = align_informative(base, res_1h, "15m", "1h", suffix="1h")
        merged = align_informative(merged, res_4h, "15m", "4h", suffix="4h")
        merged = tag_sessions(merged)
        merged = compute_setup_state_multi(merged, build_cfg_c())
        merged = compute_setup_state_multi(merged, build_cfg_r())
        return merged

    # ------------------------------------------------------------------
    # Entrada — coleta CONFIRMED por sid, arbitra D3, emite vencedor
    # ------------------------------------------------------------------

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """Entrada por arbitragem D3 sobre os sids CONFIRMED da vela (§1.3).

        OBJETIVO
            Por vela, coletar `(sid, direção)` onde `setup_state__{sid} ==
            'CONFIRMED'` (9 sids), aplicar `arbitrate_d3` e, quando há
            vencedor, marcar `enter_long`/`enter_short` + `enter_tag =
            f"{sid}_{direção}"`. Direções conflitantes na mesma vela ⇒ nenhuma
            entrada e `setup_conflict_dirs = 1` (coluna diagnóstica, §1.3-2).
        FONTE DE DADOS
            Colunas `setup_state__{sid}`/`setup_direction__{sid}` de
            `compute_setup_state_multi` (já no df após `populate_indicators`);
            arbitragem pura de `candidate_frozen.arbitrate_d3`.
        LIMITAÇÕES CONHECIDAS
            `entry_mode='hybrid'` é stub (`NotImplementedError` herdado). Só
            velas com >=1 CONFIRMED entram no laço (as demais são varridas
            vetorialmente) — custo dominado pela esparsidade dos CONFIRMED.
            As colunas `setup_state__{sid}`/`setup_direction__{sid}` dos 9 sids
            são **obrigatórias** aqui: `require_candidate_columns` falha alto se
            faltar qualquer uma (bug de fiação, não "sid inativo") — sem
            fallback silencioso (emenda de auditoria, precedente PR #85).
        NÃO FAZER
            Não entrar fora de CONFIRMED; não arbitrar por outra ordem que não
            a prioridade D3; não emitir quando as direções conflitam; não
            tolerar coluna sufixada ausente.
        """
        if self.entry_mode == "hybrid":
            raise NotImplementedError(
                "entry_mode='hybrid' é stub nesta wave (§3.1): antecipar a "
                "entrada em ARMED/PENDING é otimização não medida. Use "
                "entry_mode='strict'."
            )

        # Fail-loud: as 18 colunas sufixadas consumidas abaixo são obrigatórias
        # após populate_indicators; ausência é bug de fiação, não sid inativo.
        require_candidate_columns(dataframe.columns)

        n = len(dataframe)
        enter_long = np.zeros(n, dtype="int64")
        enter_short = np.zeros(n, dtype="int64")
        enter_tag = np.array([""] * n, dtype=object)
        conflict = np.zeros(n, dtype="int64")

        # Extrai estado/direção por sid (colunas garantidas presentes pela
        # guarda `require_candidate_columns` acima — acesso direto, sem fallback).
        #
        # `setup_state__{sid}` é StringDtype (sentinela `pd.NA`); a máscara
        # CONFIRMED é derivada na **Series**, com `.fillna(False)` — nunca no
        # ndarray object — para não propagar `pd.NA` até o `|=` (que chamaria
        # `NAType.__bool__` e levantaria `boolean value of NA is ambiguous`).
        # Mesmo padrão NA-safe da engine (`setup_state.py:533`), robusto a
        # object/None e string/NA. A direção é lida por valor e coagida com
        # `_na_to_none` antes de qualquer teste booleano (`in (...)`).
        confirmed: dict = {}
        dirs: dict = {}
        for sid in _ALL_SIDS:
            scol = f"setup_state__{sid}"
            dcol = f"setup_direction__{sid}"
            confirmed[sid] = (
                (dataframe[scol] == STATE_CONFIRMED).fillna(False).to_numpy(dtype=bool)
            )
            dirs[sid] = dataframe[dcol].to_numpy(dtype=object)

        # Máscara vetorizada: velas com pelo menos um sid CONFIRMED.
        any_confirmed = np.zeros(n, dtype=bool)
        for sid in _ALL_SIDS:
            any_confirmed |= confirmed[sid]

        for i in np.nonzero(any_confirmed)[0]:
            cands: list = []
            for sid in _ALL_SIDS:
                if confirmed[sid][i]:
                    d = _na_to_none(dirs[sid][i])
                    if d in (DIRECTION_LONG, DIRECTION_SHORT):
                        cands.append((sid, d))
            winner_sid, direction, reason = arbitrate_d3(cands)
            if reason == "conflict_dirs":
                conflict[i] = 1
            if winner_sid is not None:
                if direction == DIRECTION_LONG:
                    enter_long[i] = 1
                else:
                    enter_short[i] = 1
                enter_tag[i] = f"{winner_sid}_{direction}"

        dataframe["enter_long"] = enter_long
        dataframe["enter_short"] = enter_short
        dataframe["enter_tag"] = enter_tag
        dataframe[COL_SETUP_CONFLICT_DIRS] = conflict
        return dataframe

    # ------------------------------------------------------------------
    # Resolução causal dos callbacks — colunas sufixadas `{col}__{sid}`
    # (sid parseado do `enter_tag`); reusa `_compute_sl_anchor`,
    # `_is_structurally_invalidated`, `_rr_target_reached`, `_record_resolved`
    # e `custom_stoploss`/`custom_exit` da base sem alteração.
    # ------------------------------------------------------------------

    @staticmethod
    def _sid_from_trade(trade) -> str | None:
        """Sid parseado do `enter_tag` do trade (`f"{sid}_{direção}"`).

        OBJETIVO
            Recuperar o sid vencedor gravado na entrada (`split('_', 1)[0]`);
            ids de assinatura não contêm `_`, então o parse é inequívoco (P6).
        LIMITAÇÕES CONHECIDAS
            `enter_tag` ausente/sem `_` (cache frio / trade sem tag) → `None`
            (os callbacks então não ancoram/saem por estrutura — honesto).
        """
        tag = getattr(trade, "enter_tag", None)
        if not tag or "_" not in tag:
            return None
        return tag.split("_", 1)[0]

    def _causal_setup_id(self, pair, current_time, sid=None):
        """`setup_id__{sid}` da última linha causal com setup ativo do sid.

        OBJETIVO
            Análogo ao `_causal_setup_id` da base, mas na coluna sufixada do
            sid vencedor: última linha (Series) com `date <= current_time` e
            `setup_id__{sid}` não-nulo. FSM single por sid → um setup ativo por
            sid no candle do fill. Usado por `order_filled` para gravar
            `custom_data['setup_id']` (chave de casamento da âncora/saída).
        FONTE DE DADOS
            `self.dp.get_analyzed_dataframe(pair, self.timeframe)`; `sid` vem
            do `enter_tag` (via `order_filled`).
        LIMITAÇÕES CONHECIDAS
            `sid=None`, df vazio (cache frio) ou coluna/valor ausente → `None`.
        NÃO FAZER
            Não usar `iloc` futuro; o filtro `date <= current_time` é a
            barreira anti-lookahead.
        """
        if sid is None:
            return None
        df, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        idcol = f"setup_id__{sid}"
        if df is None or df.empty or idcol not in df.columns:
            return None
        causal = df[df["date"] <= current_time]
        rows = causal[causal[idcol].notna()]
        if rows.empty:
            return None
        # `setup_id__{sid}` é StringDtype: coage o escalar (`pd.NA`→`None`) antes
        # de virar chave de `custom_data` (§2.1). `.notna()` já filtrou nulos, mas
        # a coerção mantém o contrato de valor limpo (nunca devolver `pd.NA`).
        return _na_to_none(rows.iloc[-1][idcol])

    def _causal_setup_row(self, pair, trade, current_time):
        """Última linha causal do sid do trade, normalizada para nomes base.

        OBJETIVO
            Devolver a linha (Series) mais recente com `date <= current_time` e
            `setup_id__{sid} == custom_data['setup_id']`, com as 7
            `SETUP_OUTPUT_COLUMNS` renomeadas do sufixo `__{sid}` para o nome
            base (`setup_zone_low`, `setup_state`, ...). Assim os helpers da
            base (`_compute_sl_anchor`, `_is_structurally_invalidated`) leem os
            campos sem saber do sufixo — reuso total da execução por trade.
        FONTE DE DADOS
            `self.dp.get_analyzed_dataframe`; `sid` ← `enter_tag`; chave de
            casamento ← `custom_data['setup_id']` (gravada em `order_filled`).
        LIMITAÇÕES CONHECIDAS
            `sid`/`setup_id` ausente, df vazio ou sem a linha causal → `None`.
        NÃO FAZER
            Não usar `iloc` futuro (filtro `date <= current_time`).
        """
        df, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if df is None or df.empty:
            return None
        sid = self._sid_from_trade(trade)
        if sid is None:
            return None
        idcol = f"setup_id__{sid}"
        if idcol not in df.columns:
            return None
        setup_id = trade.get_custom_data(self.SETUP_ID_KEY)
        if setup_id is None:
            return None
        causal = df[df["date"] <= current_time]
        # `setup_id__{sid} == setup_id` sobre StringDtype devolve um BooleanArray
        # anulável (NA onde o id é `pd.NA`); indexar com NA levantaria
        # `cannot mask with array containing NA`. `.fillna(False)` densifica a
        # máscara (mesmo padrão NA-safe do consumo de estado, §2.1).
        mask = (causal[idcol] == setup_id).fillna(False).to_numpy(dtype=bool)
        rows = causal[mask]
        if rows.empty:
            return None
        row = rows.iloc[-1]
        # Normaliza `{col}__{sid}` → `{col}` para os helpers herdados, coagindo
        # nulos StringDtype/float (`pd.NA`/`NaN`) para `None` antes que os helpers
        # da base os avaliem em contexto booleano (`setup_state == INVALIDATED`,
        # checagem NaN da zona) — §2.1.
        return pd.Series(
            {col: _na_to_none(row.get(f"{col}__{sid}")) for col in SETUP_OUTPUT_COLUMNS}
        )

    def order_filled(self, pair, trade, order, current_time, **kwargs):
        """Grava âncora do SL no fill de entrada; RESOLVED na saída (multi-sid).

        OBJETIVO
            Idêntico à base, mas a captura do `setup_id` usa o sid parseado do
            `enter_tag` (coluna `setup_id__{sid}`). No fill de ENTRADA: grava
            `custom_data['setup_id']` = id causal do sid e ancora o SL uma vez.
            No fill de SAÍDA (trade fechado): grava RESOLVED (herdado).
        FONTE DE DADOS
            `order.ft_order_side == trade.entry_side` (entrada vs saída);
            `_sid_from_trade` (sid); `_causal_setup_id` (id causal do sid);
            `_compute_sl_anchor` (herdado; lê a linha normalizada).
        LIMITAÇÕES CONHECIDAS
            Sem sid (enter_tag ausente) ou sem linha causal → não grava; o SL
            cai no `stoploss` duro até haver âncora. Idempotente (não re-grava).
        NÃO FAZER
            Não indexar o df por posição futura; não remontar a zona.
        """
        if order.ft_order_side != trade.entry_side:
            # Fill de saída → trade fechando: registra o desfecho RESOLVED.
            if not trade.is_open:
                self._record_resolved(trade)
            return

        sid = self._sid_from_trade(trade)
        if sid is None:
            return

        # Fill de ENTRADA: captura o `setup_id` causal do sid vencedor (uma vez).
        if trade.get_custom_data(self.SETUP_ID_KEY) is None:
            setup_id = self._causal_setup_id(pair, current_time, sid=sid)
            if setup_id is not None:
                trade.set_custom_data(self.SETUP_ID_KEY, setup_id)

        # Ancora o SL uma única vez (helper herdado lê a linha normalizada).
        if trade.get_custom_data(self.SL_ANCHOR_KEY) is not None:
            return
        anchor = self._compute_sl_anchor(pair, trade, current_time)
        if anchor is not None:
            trade.set_custom_data(self.SL_ANCHOR_KEY, anchor)
