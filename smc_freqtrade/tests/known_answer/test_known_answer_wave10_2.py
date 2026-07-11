"""Known-answer da camada de execução (GE-0, Wave 10.2).

OBJETIVO
    Fechar o GE-0 do protocolo de congelamento (§4-P3 /
    `docs/CONGELAMENTO_CANDIDATA_V2_E_GATES_EDGE.md`): oito trades sintéticos de
    desfecho conhecido atravessam o **loop de backtest real do Freqtrade**
    (`Backtesting.backtest`) com o **código de entrada/execução real da
    `SMCStrategyCandidate`** (arbitragem D3, `populate_entry_trend`,
    `order_filled`, `custom_stoploss`, `custom_exit`, RESOLVED). As colunas de
    setup são **injetadas** por `KnownAnswerStrategy.populate_indicators`
    (subclasse de teste) — o desenho NÃO tenta fabricar OHLCV que dispare a FSM
    real (isso é frágil e já é coberto pelo golden da engine); aqui validamos a
    CAMADA DE EXECUÇÃO, nunca a engine.

    Cada cenário compara o resultado do backtest com uma **expectativa derivada à
    mão** (helpers puros em `ka_data`), não com o próprio Freqtrade — é um
    known-answer, não um snapshot.

REGRAS DA VERSÃO INSTALADA (confirmadas no código; ver `ka_data` para citações)
    - Entrada = open da vela seguinte ao sinal (shift(1) das colunas de sinal +
      fill em `row[OPEN_IDX]`).
    - Saída por `custom_exit` (R:R/estrutural) = open da vela do callback.
    - Saída por SL ancorado = preço do stop; para SHORT o stop passa por
      `price_to_precision(..., ROUND_DOWN)` e pode ficar 1 tick abaixo da âncora
      (por isso o assert de preço de SL usa tolerância de 1 tick; o de P&L é
      exato contra a âncora dentro de ~1 tick).
    - Fee aplicado nas DUAS pernas (config["fee"] -> fee_open=fee_close).

GUARD DE IMPORT (padrão wave10a/b/10.1-strategy)
    `pytest.importorskip("freqtrade")` no topo: sem freqtrade (sandbox do Code) o
    módulo **não coleta** (skip), mantendo a suíte sandbox em 372 passed. Roda na
    VM, onde o freqtrade existe — sua execução verde constitui o GE-0.

NÃO FAZER
    Tocar `smc_engine/`, `SMCStrategy.py`, `SMCStrategyCandidate.py`,
    `candidate_frozen.py` ou dados de mercado reais. Nenhum backtest sobre
    BTC/ETH/SOL — 100% sintético.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

# --- Guard de import: sem freqtrade, não coleta (skip) --------------------
pytest.importorskip("freqtrade")

import pandas as pd  # noqa: E402

_KA_DIR = Path(__file__).resolve().parent
_SUBPROJECT_ROOT = _KA_DIR.parents[1]
_STRATEGIES_DIR = _SUBPROJECT_ROOT / "user_data" / "strategies"
for _p in (str(_SUBPROJECT_ROOT), str(_STRATEGIES_DIR), str(_KA_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from freqtrade.enums import RunMode, CandleType  # noqa: E402
from freqtrade.resolvers import ExchangeResolver  # noqa: E402
from freqtrade.optimize.backtesting import Backtesting  # noqa: E402
from freqtrade.data.history import get_timerange  # noqa: E402

import ka_data  # noqa: E402
from ka_data import (  # noqa: E402
    PAIR, STAKE, FEE, RR, DIRECTION_LONG, DIRECTION_SHORT,
    sl_anchor, rr_target_price, profit_abs as hand_profit,
)

_CONFIG = _SUBPROJECT_ROOT / "config_backtest.json"
_PRICE_TICK = 0.01     # espelha o market sintético (precision.price)


# ==========================================================================
# Harness offline: loop de backtest REAL do Freqtrade, sem rede/mercado real
# ==========================================================================

def _make_market() -> dict:
    """Market sintético mínimo (swap linear USDT) para o par de teste.

    Injetado em `exchange._markets` para que o backtest rode 100% offline
    (sem carregar mercados da OKX): a known-answer é hermética — nenhum estado
    de exchange pode alterar o desfecho conhecido. `contractSize=1`,
    `precision.price=0.01`, `precision.amount=0.0001`.
    """
    return {
        "id": "SYNTH-USDT-SWAP", "symbol": PAIR, "base": "SYNTH", "quote": "USDT",
        "settle": "USDT", "baseId": "SYNTH", "quoteId": "USDT", "settleId": "USDT",
        "type": "swap", "spot": False, "margin": False, "swap": True,
        "future": False, "option": False, "active": True, "contract": True,
        "linear": True, "inverse": False, "contractSize": 1.0,
        "taker": 0.0005, "maker": 0.0002, "percentage": True, "tierBased": False,
        "precision": {"amount": 0.0001, "price": _PRICE_TICK,
                      "cost": None, "base": None, "quote": None},
        "limits": {"amount": {"min": 0.0001, "max": 1_000_000},
                   "price": {"min": None, "max": None},
                   "cost": {"min": 0.1, "max": None},
                   "leverage": {"min": 1, "max": 100}},
        "info": {},
    }


@pytest.fixture(scope="module")
def _datadir(tmp_path_factory) -> Path:
    """Datadir temporário (com subpasta `futures`) — nada é lido de disco real."""
    d = tmp_path_factory.mktemp("ka_data_dir")
    (d / "futures").mkdir(parents=True, exist_ok=True)
    return d


def _run(scenario: str, datadir: Path):
    """Roda o cenário no loop de backtest REAL e devolve (results, strat, processed).

    Deriva o config de teste do `config_backtest.json` real (mesmos fee/stoploss/
    trading_mode), com overrides mínimos: whitelist sintética, `strategy_path`
    apontando para `tests/known_answer/`, cenário ativo em `ka_scenario`. O
    caminho de execução é `Backtesting.backtest(processed=...)` — nunca uma
    reimplementação do loop.
    """
    cfg = copy.deepcopy(json.loads(_CONFIG.read_text()))
    cfg["runmode"] = RunMode.BACKTEST
    cfg["datadir"] = datadir
    cfg["user_data_dir"] = _SUBPROJECT_ROOT / "user_data"
    cfg["exchange"]["pair_whitelist"] = [PAIR]
    cfg["stake_amount"] = STAKE
    cfg["candle_type_def"] = CandleType.FUTURES
    cfg["strategy"] = "KnownAnswerStrategy"
    cfg["strategy_path"] = str(_KA_DIR)
    cfg["ka_scenario"] = scenario
    cfg.pop("api_server", None)   # evita validação de jwt_secret_key no backtest

    # Exchange offline: validate=False não recarrega mercados; injetamos o market
    # sintético e travamos o refresh para nunca tocar a rede.
    exch = ExchangeResolver.load_exchange(cfg, validate=False, load_leverage_tiers=False)
    exch._markets = {PAIR: _make_market()}
    exch._last_markets_refresh = 2 ** 60

    bt = Backtesting(cfg, exchange=exch)
    strat = bt.strategylist[0]
    bt._set_strategy(strat)
    # Futures sem funding real: df de funding/mark vazio -> funding fee = 0
    # (isola o P&L ao fee de trading das duas pernas, o objeto do GE-0).
    bt.futures_data = {PAIR: pd.DataFrame(columns=["date", "open_fund", "open_mark"])}
    bt.funding_fee_timeframe_secs = 8 * 3600

    df = ka_data.build_ohlcv(scenario)
    processed = strat.advise_all_indicators({PAIR: df})
    mind, maxd = get_timerange(processed)
    res = bt.backtest(processed=processed, start_date=mind, end_date=maxd)
    return res["results"], strat, processed[PAIR]


# ==========================================================================
# Cenários (cada assert traz a derivação à mão no comentário)
# ==========================================================================

def test_k1_long_rr_target(_datadir):
    """K1 — long → alvo R:R (custom_exit / smc_rr_target).

    Sinal A3 CONFIRMED na vela 1 -> entrada = open[2] = 1000.
    anchor = 990*(1-0.001) = 989.01 ; R = |1000-989.01| = 10.99 ;
    alvo = 1000 + 2*10.99 = 1021.98 ; 1o open >= alvo é a vela 4 (=1022) ->
    saída no open 1022.  profit_abs = 100*[(1022/1000)*(1-fee) - (1+fee)] = 2.0989.
    """
    res, strat, _ = _run("K1", _datadir)
    assert len(res) == 1
    t = res.iloc[0]
    entry, exit_ = 1000.0, 1022.0
    anchor = sl_anchor(DIRECTION_LONG, 990.0, 1010.0)
    assert anchor == pytest.approx(989.01, abs=1e-9)
    assert rr_target_price(DIRECTION_LONG, entry, anchor) == pytest.approx(1021.98, abs=1e-9)
    assert t["open_rate"] == pytest.approx(entry, abs=1e-9)
    assert t["close_rate"] == pytest.approx(exit_, abs=1e-9)
    assert t["exit_reason"] == "smc_rr_target"
    assert t["enter_tag"] == "A3_long"
    assert t["profit_abs"] == pytest.approx(hand_profit(DIRECTION_LONG, entry, exit_), rel=1e-6)
    assert t["profit_abs"] == pytest.approx(2.0989, abs=1e-4)


def test_k2_long_anchored_stoploss(_datadir):
    """K2 — long → SL ancorado (custom_stoploss).

    Entrada = open[2] = 1000 ; anchor = 989.01 ; R_quote = amount*R = 0.1*10.99 =
    1.099. A vela 4 varre o anchor (high>=989.01>=low) -> saída no preço do stop.
    Long usa ROUND_UP: o preço bate exato na âncora (989.01).
    profit_abs(1000->989.01) = 100*[(989.01/1000)*(1-fee)-(1+fee)] = -1.198451 (~ -1R).
    """
    res, strat, _ = _run("K2", _datadir)
    assert len(res) == 1
    t = res.iloc[0]
    entry = 1000.0
    anchor = sl_anchor(DIRECTION_LONG, 990.0, 1010.0)      # 989.01
    r_quote = (STAKE / entry) * abs(entry - anchor)         # 1.099
    assert t["open_rate"] == pytest.approx(entry, abs=1e-9)
    assert t["exit_reason"] in ("stop_loss", "trailing_stop_loss")
    # Preço de saída na âncora (long ROUND_UP -> exato), tolerância de 1 tick.
    assert t["close_rate"] == pytest.approx(anchor, abs=_PRICE_TICK)
    # P&L exato contra a âncora, dentro de ~1 tick de preço.
    assert t["profit_abs"] == pytest.approx(
        hand_profit(DIRECTION_LONG, entry, anchor), abs=STAKE / entry * _PRICE_TICK + 1e-6)
    # ~ -1R líquido (perda de ~1R + fee): entre -1.3R e -0.9R.
    assert -1.3 * r_quote < t["profit_abs"] < -0.9 * r_quote


def test_k3_short_rr_target(_datadir):
    """K3 — short → alvo R:R (espelho de K1).

    Sinal A5 CONFIRMED (short) na vela 1 -> entrada = open[2] = 1000.
    anchor(short) = 1010*(1+0.001) = 1011.01 ; R = 11.01 ;
    alvo(short) = 1000 - 2*11.01 = 977.98 ; 1o open <= alvo é a vela 4 (=977) ->
    saída no open 977.  profit_abs = 100*[(1-fee)-(977/1000)*(1+fee)] = 2.20115.
    """
    res, strat, _ = _run("K3", _datadir)
    assert len(res) == 1
    t = res.iloc[0]
    entry, exit_ = 1000.0, 977.0
    anchor = sl_anchor(DIRECTION_SHORT, 990.0, 1010.0)
    assert anchor == pytest.approx(1011.01, abs=1e-9)
    assert rr_target_price(DIRECTION_SHORT, entry, anchor) == pytest.approx(977.98, abs=1e-9)
    assert t["open_rate"] == pytest.approx(entry, abs=1e-9)
    assert t["close_rate"] == pytest.approx(exit_, abs=1e-9)
    assert t["exit_reason"] == "smc_rr_target"
    assert t["enter_tag"] == "A5_short"
    assert bool(t["is_short"]) is True
    assert t["profit_abs"] == pytest.approx(hand_profit(DIRECTION_SHORT, entry, exit_), rel=1e-6)
    assert t["profit_abs"] == pytest.approx(2.20115, abs=1e-4)


def test_k4_short_anchored_stoploss(_datadir):
    """K4 — short → SL ancorado (espelho de K2).

    Entrada = open[2] = 1000 ; anchor(short) = 1011.01 ; R_quote = 0.1*11.01 = 1.101.
    A vela 4 varre o anchor (low<=1011.01<=high) -> saída no stop. Short usa
    ROUND_DOWN em price_to_precision, então o stop pode cair 1 tick abaixo da
    âncora (observado: 1011.00). profit_abs(1000->1011.01) ~ -1.2016 (~ -1R).
    """
    res, strat, _ = _run("K4", _datadir)
    assert len(res) == 1
    t = res.iloc[0]
    entry = 1000.0
    anchor = sl_anchor(DIRECTION_SHORT, 990.0, 1010.0)      # 1011.01
    r_quote = (STAKE / entry) * abs(entry - anchor)          # 1.101
    assert t["open_rate"] == pytest.approx(entry, abs=1e-9)
    assert bool(t["is_short"]) is True
    assert t["exit_reason"] in ("stop_loss", "trailing_stop_loss")
    # Short ROUND_DOWN: até 1 tick abaixo da âncora.
    assert t["close_rate"] == pytest.approx(anchor, abs=_PRICE_TICK)
    assert t["close_rate"] <= anchor + 1e-9
    # P&L exato contra a âncora, dentro de ~1 tick de preço.
    assert t["profit_abs"] == pytest.approx(
        hand_profit(DIRECTION_SHORT, entry, anchor), abs=STAKE / entry * _PRICE_TICK + 1e-6)
    assert -1.3 * r_quote < t["profit_abs"] < -0.9 * r_quote


def test_k5_conflicting_directions_no_trade(_datadir):
    """K5 — sids em direções opostas na mesma vela -> 0 trades + conflito.

    A3 CONFIRMED long e A5 CONFIRMED short na vela 1 -> `arbitrate_d3` devolve
    `conflict_dirs` (evidência contraditória, §1.3-2): nenhuma entrada e
    `setup_conflict_dirs == 1` exatamente na vela 1.
    """
    res, strat, processed = _run("K5", _datadir)
    assert len(res) == 0
    conflict = list(processed["setup_conflict_dirs"])
    assert conflict[1] == 1                       # vela de sinal
    assert sum(conflict) == 1                     # só ela
    assert int(processed["enter_long"].sum()) == 0
    assert int(processed["enter_short"].sum()) == 0


def test_k6_two_sids_same_dir_priority(_datadir):
    """K6 — 2 sids CONFIRMED mesma direção -> vence maior prioridade D3.

    A3 e A6 CONFIRMED long na vela 1. Na prioridade D3 (ordem do registry) A3
    precede A6, então `arbitrate_d3` -> A3 (`priority_tiebreak`). enter_tag deve
    ser "A3_long" e o trade segue a zona/anchor da A3 (mesma aritmética de K1).
    """
    res, strat, _ = _run("K6", _datadir)
    assert len(res) == 1
    t = res.iloc[0]
    assert t["enter_tag"] == "A3_long"            # não "A6_long"
    assert t["open_rate"] == pytest.approx(1000.0, abs=1e-9)
    assert t["close_rate"] == pytest.approx(1022.0, abs=1e-9)
    assert t["exit_reason"] == "smc_rr_target"
    assert t["profit_abs"] == pytest.approx(hand_profit(DIRECTION_LONG, 1000.0, 1022.0), rel=1e-6)


def test_k7_fee_accounting(_datadir):
    """K7 — contabilidade de fee (falha se o fee não estiver sendo aplicado).

    Entrada = 1000 ; alvo R:R -> saída no open 1210 (números redondos).
    profit_abs = 100*[(1210/1000)*(1-0.0005) - (1+0.0005)] = 20.8895.
    Com fee=0 seria 100*[1.21 - 1] = 21.0 -> a diferença (0.1105) é o custo das
    duas pernas; o assert de desigualdade abaixo falha se o fee for ignorado.
    """
    res, strat, _ = _run("K7", _datadir)
    assert len(res) == 1
    t = res.iloc[0]
    entry, exit_ = 1000.0, 1210.0
    expected = hand_profit(DIRECTION_LONG, entry, exit_)       # 20.8895 (fee=0.0005)
    fee_zero = STAKE * ((exit_ / entry) - 1.0)                 # 21.0 (fee=0)
    assert t["close_rate"] == pytest.approx(exit_, abs=1e-9)
    assert t["profit_abs"] == pytest.approx(expected, rel=1e-6)
    assert t["profit_abs"] == pytest.approx(20.8895, abs=1e-4)
    # Prova direta de que o fee incide nas DUAS pernas: o custo total é
    # fee*(valor_abertura + valor_fecho) = fee*stake*(1 + exit/entry).
    fee_cost = FEE * STAKE * (1.0 + exit_ / entry)            # 0.1105
    assert (fee_zero - t["profit_abs"]) == pytest.approx(fee_cost, rel=1e-6)
    assert t["profit_abs"] < fee_zero - 0.1


def test_k8_stoploss_antitrap_and_config(_datadir):
    """K8 — anti-armadilha de stoploss + `strategy.stoploss == -0.99`.

    Long entra em 1000 com anchor em 500*(1-0.001)=499.5 (~ -50%, longe do dip).
    A vela 4 tem queda adversa de -15% intracandle (low=850). Com o config
    corrigido (`stoploss=-0.99`) e a âncora tão distante, o trade NÃO fecha por
    stoploss no dip: sobrevive até a vela 6, onde o setup fica INVALIDATED e o
    `custom_exit` sai por `smc_structural_invalidation` a preço 900.
    (Com o antigo `stoploss=-0.10`, o dip de -15% teria fechado o trade na vela 4
    por 'stoploss' — é a armadilha que a Entrega A remove.)

    Nota de causalidade: a invalidação estrutural é lida do dataframe analisado
    (`get_analyzed_dataframe`), que no loop de backtest fica 1 vela atrás da vela
    corrente (barreira anti-lookahead do Freqtrade). Logo o `custom_exit` enxerga
    o estado INVALIDATED da vela 6 quando avalia a vela 7 e sai no open[7]=900 —
    diferente das saídas por R:R/SL (K1-K4), que usam `current_rate` da vela e não
    têm esse atraso. As velas 5-8 têm open=900, então o preço de saída é 900
    independentemente da vela exata em que a barreira libera o estado.
    profit_abs(1000->900) = 100*[(900/1000)*(1-fee)-(1+fee)] = -10.095.
    """
    res, strat, _ = _run("K8", _datadir)
    # Assert direto do config carregado (Entrega A): o config sobrepõe o atributo.
    assert strat.stoploss == -0.99
    assert len(res) == 1
    t = res.iloc[0]
    assert t["exit_reason"] == "smc_structural_invalidation"
    assert t["close_rate"] == pytest.approx(900.0, abs=1e-9)
    open_dates = pd.to_datetime(ka_data.build_ohlcv("K8")["date"])
    close_date = pd.Timestamp(t["close_date"])
    # Anti-armadilha: o trade SOBREVIVE ao dip de -15% (vela 4) — não fecha nela.
    assert close_date > open_dates.iloc[4]
    # E sai pela invalidação estrutural (vela 6 em diante, +1 pela barreira causal).
    assert close_date >= open_dates.iloc[6]
    assert t["profit_abs"] == pytest.approx(hand_profit(DIRECTION_LONG, 1000.0, 900.0), rel=1e-6)
    assert t["profit_abs"] == pytest.approx(-10.095, abs=1e-4)
