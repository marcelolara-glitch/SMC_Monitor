"""Smoke tests sintéticos da Wave 10b — execução por trade + SL ancorado.

OBJETIVO
    Ratificar a maquinaria de execução da 10b por smoke SINTÉTICO (o ambiente
    do Code tem rede de exchange bloqueada e golden com 0 CONFIRMED → sem trades
    reais; o selo empírico via `lookahead-analysis`/`backtesting` é gate da
    VM/10c). Cobre §7 do briefing (atualizado pela instrumentação por
    assinatura — 10c):
      T1 — entrada STRICT em CONFIRMED, `enter_tag ==
           f"{setup_signature}_{setup_direction}"` (ex.: "A3_long", não mais o
           hash `setup_id`); nada em ARMED/PENDING/INVALIDATED.
      T2 — `order_filled` captura `custom_data['setup_id']` (identidade única da
           linha causal) e grava `sl_anchor` = `setup_zone_low` (long) /
           `setup_zone_high` (short) da linha causal (± buffer fora da zona); o
           casamento da âncora/saída passa a ser por `custom_data['setup_id']`.
      T3 — `custom_stoploss` devolve o stop relativo coerente com
           `stoploss_from_absolute` (abaixo do preço em long, acima em short).
      T4 — `custom_exit` sai por (a) invalidação estrutural e (b) R:R.
      T5 — nenhum callback indexa linha futura (`date > current_time`): o filtro
           causal é provado por um df com linha futura "armadilha".
      T6 — ao fechar, o desfecho é gravado em `custom_data['resolved']`.

FONTE DE DADOS
    DataFrames sintéticos construídos in-loco (zona/estado conhecidos) +
    dublês mínimos (`_FakeDP`, `_FakeOrder`, `_FakeTrade`) que reproduzem só a
    superfície que os callbacks tocam (assinaturas verbatim do Freqtrade 2026.3
    confirmadas no venv). `stoploss_from_absolute` é o helper nativo real.

LIMITAÇÕES CONHECIDAS
    Não roda backtest/`lookahead-analysis`/`recursive-analysis` (gate VM/10c).
    Os dublês de `Trade`/`Order`/`DataProvider` cobrem apenas os atributos/
    métodos usados pela 10b — não são fixtures completas do Freqtrade.

NÃO FAZER
    Não validar contra LuxAlgo TradingView (mecânica, não oráculo visual). Não
    introduzir calibração (TP multi-nível/trailing são 10c).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_SUBPROJECT_ROOT = Path(__file__).resolve().parents[1]
_STRATEGIES_DIR = _SUBPROJECT_ROOT / "user_data" / "strategies"

for _p in (str(_SUBPROJECT_ROOT), str(_STRATEGIES_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from freqtrade.strategy import stoploss_from_absolute  # noqa: E402

from SMCStrategy import SMCStrategy  # noqa: E402


# ============================================================
# Dublês mínimos (só a superfície que a 10b toca)
# ============================================================

class _FakeDP:
    """DataProvider stub: devolve um df fixo em `get_analyzed_dataframe`."""

    def __init__(self, df: pd.DataFrame) -> None:
        self._df = df

    def get_analyzed_dataframe(self, pair, timeframe):
        last = self._df["date"].max() if not self._df.empty else pd.Timestamp(0, tz="UTC")
        return self._df, last


class _FakeOrder:
    """Order stub: só `ft_order_side` (entrada vs saída)."""

    def __init__(self, ft_order_side: str) -> None:
        self.ft_order_side = ft_order_side


class _FakeTrade:
    """Trade stub: superfície usada pelos callbacks da 10b + custom_data dict."""

    def __init__(
        self, enter_tag, is_short=False, open_rate=100.0, leverage=1.0,
        entry_side="buy", exit_side="sell", is_open=True, exit_reason=None,
    ) -> None:
        self.enter_tag = enter_tag
        self.is_short = is_short
        self.open_rate = open_rate
        self.leverage = leverage
        self.entry_side = entry_side
        self.exit_side = exit_side
        self.is_open = is_open
        self.exit_reason = exit_reason
        self._custom: dict = {}

    def set_custom_data(self, key, value):
        self._custom[key] = value

    def get_custom_data(self, key, default=None):
        return self._custom.get(key, default)


def _strategy() -> SMCStrategy:
    from freqtrade.enums import CandleType

    return SMCStrategy({"candle_type_def": CandleType.FUTURES})


def _dt(i: int) -> pd.Timestamp:
    """Timestamp tz-aware UTC (mirror do que o Freqtrade passa aos callbacks)."""
    return pd.Timestamp("2026-01-01", tz="UTC") + pd.Timedelta(minutes=15 * i)


# ============================================================
# T1 — entrada STRICT em CONFIRMED
# ============================================================

def test_t1_entry_strict_confirmed_only():
    """`enter_long`/`enter_short`==1 só em CONFIRMED casando direção;
    `enter_tag == f"{setup_signature}_{setup_direction}"` (10c, não mais o
    hash `setup_id`); nada em ARMED/PENDING/INVALIDATED."""
    strat = _strategy()
    df = pd.DataFrame({
        "date": [_dt(i) for i in range(6)],
        "setup_state": [
            "ARMED", "PENDING_CONFIRMATION", "CONFIRMED",
            "CONFIRMED", "INVALIDATED", "CONFIRMED",
        ],
        "setup_direction": ["long", "long", "long", "short", "long", None],
        "setup_signature": ["A3", "A3", "A3", "A3", "A3", None],
        "setup_id": ["idA", "idA", "idLONG", "idSHORT", "idA", None],
    })

    out = strat.populate_entry_trend(df.copy(), {"pair": "BTC/USDT:USDT"})

    el = out["enter_long"].fillna(0) if "enter_long" in out else pd.Series([0] * len(out))
    es = out["enter_short"].fillna(0) if "enter_short" in out else pd.Series([0] * len(out))

    # Linha 2: CONFIRMED long → enter_long==1, tag "A3_long" (assinatura×direção).
    assert el.iloc[2] == 1
    assert out["enter_tag"].iloc[2] == "A3_long"
    # Linha 3: CONFIRMED short → enter_short==1, tag "A3_short".
    assert es.iloc[3] == 1
    assert out["enter_tag"].iloc[3] == "A3_short"
    # Nada em ARMED/PENDING/INVALIDATED.
    for i in (0, 1, 4):
        assert el.iloc[i] == 0
        assert es.iloc[i] == 0
    # CONFIRMED com direção nula (linha 5) não entra (não casa long nem short).
    assert el.iloc[5] == 0 and es.iloc[5] == 0
    # Total de entradas: exatamente 1 long + 1 short.
    assert el.sum() == 1 and es.sum() == 1


def test_t1_hybrid_is_stub():
    """`entry_mode='hybrid'` levanta `NotImplementedError` (não reativar — §3.1)."""
    strat = _strategy()
    strat.entry_mode = "hybrid"
    df = pd.DataFrame({
        "setup_state": ["CONFIRMED"], "setup_direction": ["long"],
        "setup_signature": ["A3"], "setup_id": ["x"],
    })
    with pytest.raises(NotImplementedError):
        strat.populate_entry_trend(df, {"pair": "BTC/USDT:USDT"})


# ============================================================
# T2 — âncora gravada por order_filled (= borda da zona ± buffer)
# ============================================================

def _df_with_setup(setup_id, zone_low, zone_high, state="CONFIRMED",
                   direction="long", signature="A3", n_lead=3):
    """Df causal com `n_lead` linhas neutras + 1 linha do setup (última)."""
    rows = {
        "date": [_dt(i) for i in range(n_lead + 1)],
        "setup_id": [None] * n_lead + [setup_id],
        "setup_signature": [None] * n_lead + [signature],
        "setup_state": [None] * n_lead + [state],
        "setup_direction": [None] * n_lead + [direction],
        "setup_zone_low": [np.nan] * n_lead + [zone_low],
        "setup_zone_high": [np.nan] * n_lead + [zone_high],
    }
    return pd.DataFrame(rows)


def test_t2_order_filled_captures_setup_id_and_anchor_long():
    """Long: `order_filled` captura `custom_data['setup_id']` (= setup_id da
    linha causal) e grava `sl_anchor == setup_zone_low * (1 - buffer)`.

    `enter_tag` é a assinatura×direção ("A3_long"); o casamento da âncora passa
    a ser pela chave `custom_data['setup_id']` (10c), não mais pelo `enter_tag`.
    O SL resultante é IDÊNTICO ao da 10b (mesma zona, mesma fórmula)."""
    strat = _strategy()
    zlow, zhigh = 95.0, 98.0
    df = _df_with_setup("hashLONG", zlow, zhigh, direction="long")
    strat.dp = _FakeDP(df)
    trade = _FakeTrade("A3_long", is_short=False)

    strat.order_filled(
        "BTC/USDT:USDT", trade, _FakeOrder("buy"), _dt(3),
    )
    # Identidade única capturada em custom_data (não no enter_tag).
    assert trade.get_custom_data(strat.SETUP_ID_KEY) == "hashLONG"
    expected = zlow * (1.0 - strat.sl_zone_buffer_pct)
    assert trade.get_custom_data(strat.SL_ANCHOR_KEY) == pytest.approx(expected)


def test_t2_order_filled_captures_setup_id_and_anchor_short():
    """Short: captura `custom_data['setup_id']` e grava
    `sl_anchor == setup_zone_high * (1 + buffer)` da linha causal."""
    strat = _strategy()
    zlow, zhigh = 102.0, 105.0
    df = _df_with_setup("hashSHORT", zlow, zhigh, direction="short")
    strat.dp = _FakeDP(df)
    trade = _FakeTrade("A3_short", is_short=True, entry_side="sell", exit_side="buy")

    strat.order_filled(
        "BTC/USDT:USDT", trade, _FakeOrder("sell"), _dt(3),
    )
    assert trade.get_custom_data(strat.SETUP_ID_KEY) == "hashSHORT"
    expected = zhigh * (1.0 + strat.sl_zone_buffer_pct)
    assert trade.get_custom_data(strat.SL_ANCHOR_KEY) == pytest.approx(expected)


def test_t2_anchor_idempotent_and_exit_skips():
    """Âncora e setup_id não são re-gravados; fill de saída não toca `sl_anchor`."""
    strat = _strategy()
    df = _df_with_setup("hashLONG", 95.0, 98.0)
    strat.dp = _FakeDP(df)
    trade = _FakeTrade("A3_long")
    trade.set_custom_data(strat.SETUP_ID_KEY, "preexisting")  # já capturado
    trade.set_custom_data(strat.SL_ANCHOR_KEY, 1.23)  # já ancorado

    strat.order_filled("BTC/USDT:USDT", trade, _FakeOrder("buy"), _dt(3))
    assert trade.get_custom_data(strat.SETUP_ID_KEY) == "preexisting"  # inalterado
    assert trade.get_custom_data(strat.SL_ANCHOR_KEY) == 1.23  # inalterado


# ============================================================
# T3 — custom_stoploss coerente com stoploss_from_absolute
# ============================================================

def test_t3_custom_stoploss_long_below_price():
    """Long: retorno == helper; o stop implícito fica ABAIXO do preço atual."""
    strat = _strategy()
    anchor, current = 95.0, 100.0
    trade = _FakeTrade("idLONG", is_short=False)
    trade.set_custom_data(strat.SL_ANCHOR_KEY, anchor)

    ratio = strat.custom_stoploss(
        "BTC/USDT:USDT", trade, _dt(5), current, 0.0, after_fill=True,
    )
    assert ratio == pytest.approx(
        stoploss_from_absolute(anchor, current, is_short=False, leverage=1.0)
    )
    # adjust_stop_loss aplica como current*(1 - abs(ratio)) em long → stop < preço.
    implied_stop = current * (1.0 - abs(ratio))
    assert implied_stop < current
    assert implied_stop == pytest.approx(anchor)


def test_t3_custom_stoploss_short_above_price():
    """Short: retorno == helper; o stop implícito fica ACIMA do preço atual."""
    strat = _strategy()
    anchor, current = 105.0, 100.0
    trade = _FakeTrade("idSHORT", is_short=True)
    trade.set_custom_data(strat.SL_ANCHOR_KEY, anchor)

    ratio = strat.custom_stoploss(
        "BTC/USDT:USDT", trade, _dt(5), current, 0.0, after_fill=True,
    )
    assert ratio == pytest.approx(
        stoploss_from_absolute(anchor, current, is_short=True, leverage=1.0)
    )
    # adjust_stop_loss aplica como current*(1 + abs(ratio)) em short → stop > preço.
    implied_stop = current * (1.0 + abs(ratio))
    assert implied_stop > current
    assert implied_stop == pytest.approx(anchor)


def test_t3_custom_stoploss_none_without_anchor():
    """Sem âncora → `None` (mantém o `stoploss` duro vigente)."""
    strat = _strategy()
    trade = _FakeTrade("idLONG")
    assert strat.custom_stoploss(
        "BTC/USDT:USDT", trade, _dt(5), 100.0, 0.0, after_fill=False,
    ) is None


# ============================================================
# T4 — custom_exit: (a) invalidação estrutural, (b) R:R
# ============================================================

def test_t4a_exit_on_structural_invalidation():
    """`custom_exit` sai com EXIT_STRUCTURAL quando o `setup_id` aparece
    INVALIDATED na linha causal atual."""
    strat = _strategy()
    df = _df_with_setup("hashLONG", 95.0, 98.0, state="INVALIDATED")
    strat.dp = _FakeDP(df)
    trade = _FakeTrade("A3_long", open_rate=100.0)
    trade.set_custom_data(strat.SETUP_ID_KEY, "hashLONG")
    trade.set_custom_data(strat.SL_ANCHOR_KEY, 95.0)

    reason = strat.custom_exit(
        "BTC/USDT:USDT", trade, _dt(3), 100.0, 0.0,
    )
    assert reason == strat.EXIT_STRUCTURAL


def test_t4b_exit_on_rr_target_long():
    """Long: `custom_exit` sai com EXIT_RR quando current_rate atinge o alvo R:R.

    entry=100, anchor=95 → risk=5; rr=2 → alvo=110. Sem invalidação na fonte.
    """
    strat = _strategy()
    df = _df_with_setup("hashLONG", 95.0, 98.0, state="CONFIRMED")
    strat.dp = _FakeDP(df)
    trade = _FakeTrade("A3_long", open_rate=100.0)
    trade.set_custom_data(strat.SETUP_ID_KEY, "hashLONG")
    trade.set_custom_data(strat.SL_ANCHOR_KEY, 95.0)

    # Abaixo do alvo → não sai.
    assert strat.custom_exit("BTC/USDT:USDT", trade, _dt(3), 109.9, 0.099) is None
    # No alvo → sai por R:R.
    assert strat.custom_exit(
        "BTC/USDT:USDT", trade, _dt(3), 110.0, 0.10,
    ) == strat.EXIT_RR


def test_t4b_exit_on_rr_target_short():
    """Short: entry=100, anchor=105 → risk=5; rr=2 → alvo=90."""
    strat = _strategy()
    df = _df_with_setup("hashSHORT", 102.0, 105.0, state="CONFIRMED", direction="short")
    strat.dp = _FakeDP(df)
    trade = _FakeTrade("A3_short", is_short=True, open_rate=100.0)
    trade.set_custom_data(strat.SETUP_ID_KEY, "hashSHORT")
    trade.set_custom_data(strat.SL_ANCHOR_KEY, 105.0)

    assert strat.custom_exit("BTC/USDT:USDT", trade, _dt(3), 90.1, 0.099) is None
    assert strat.custom_exit(
        "BTC/USDT:USDT", trade, _dt(3), 90.0, 0.10,
    ) == strat.EXIT_RR


def test_t4_no_exit_when_neither():
    """Sem invalidação e antes do alvo → `None` (segura o trade)."""
    strat = _strategy()
    df = _df_with_setup("hashLONG", 95.0, 98.0, state="CONFIRMED")
    strat.dp = _FakeDP(df)
    trade = _FakeTrade("A3_long", open_rate=100.0)
    trade.set_custom_data(strat.SETUP_ID_KEY, "hashLONG")
    trade.set_custom_data(strat.SL_ANCHOR_KEY, 95.0)
    assert strat.custom_exit("BTC/USDT:USDT", trade, _dt(3), 103.0, 0.03) is None


# ============================================================
# T5 — sem lookahead: filtro causal date <= current_time
# ============================================================

def test_t5_anchor_ignores_future_row():
    """Uma linha FUTURA (date > current_time) com zona diferente é ignorada:
    a âncora usa a linha causal, não a futura."""
    strat = _strategy()
    # Linha causal (i=2): zona_low=95. Linha futura (i=5): zona_low=80 (armadilha).
    df = pd.DataFrame({
        "date": [_dt(0), _dt(1), _dt(2), _dt(5)],
        "setup_id": [None, None, "idLONG", "idLONG"],
        "setup_state": [None, None, "CONFIRMED", "CONFIRMED"],
        "setup_direction": [None, None, "long", "long"],
        "setup_zone_low": [np.nan, np.nan, 95.0, 80.0],
        "setup_zone_high": [np.nan, np.nan, 98.0, 83.0],
    })
    strat.dp = _FakeDP(df)
    trade = _FakeTrade("A3_long")

    # current_time = i=2: a linha i=5 é futura e NÃO pode influenciar.
    strat.order_filled("BTC/USDT:USDT", trade, _FakeOrder("buy"), _dt(2))
    # O setup_id capturado é o da linha causal (i=2), não o da futura.
    assert trade.get_custom_data(strat.SETUP_ID_KEY) == "idLONG"
    expected = 95.0 * (1.0 - strat.sl_zone_buffer_pct)
    assert trade.get_custom_data(strat.SL_ANCHOR_KEY) == pytest.approx(expected)


def test_t5_invalidation_ignores_future_row():
    """Uma INVALIDATED futura não dispara saída estrutural no presente."""
    strat = _strategy()
    df = pd.DataFrame({
        "date": [_dt(2), _dt(5)],
        "setup_id": ["idLONG", "idLONG"],
        "setup_state": ["CONFIRMED", "INVALIDATED"],  # INVALIDATED é futura
        "setup_direction": ["long", "long"],
        "setup_zone_low": [95.0, 95.0],
        "setup_zone_high": [98.0, 98.0],
    })
    strat.dp = _FakeDP(df)
    trade = _FakeTrade("A3_long", open_rate=100.0)
    trade.set_custom_data(strat.SETUP_ID_KEY, "idLONG")
    trade.set_custom_data(strat.SL_ANCHOR_KEY, 95.0)

    # current_time = i=2: a INVALIDATED (i=5) é futura → não sai por estrutura.
    assert strat.custom_exit("BTC/USDT:USDT", trade, _dt(2), 100.0, 0.0) is None


# ============================================================
# T6 — RESOLVED gravado ao fechar
# ============================================================

@pytest.mark.parametrize("reason,outcome", [
    (SMCStrategy.EXIT_RR, "tp"),
    (SMCStrategy.EXIT_STRUCTURAL, "invalidation"),
    ("stoploss", "sl"),
    ("force_exit", "other"),
])
def test_t6_resolved_recorded_on_close(reason, outcome):
    """Ao fechar (fill de saída), o desfecho é classificado e gravado em
    `custom_data['resolved']`."""
    strat = _strategy()
    strat.dp = _FakeDP(pd.DataFrame())  # não usado no ramo de saída
    trade = _FakeTrade(
        "A3_long", entry_side="buy", exit_side="sell",
        is_open=False, exit_reason=reason,
    )
    # enter_tag = rótulo `assinatura_direção`; o hash vem do custom_data.
    trade.set_custom_data(strat.SETUP_ID_KEY, "hashLONG")
    strat.order_filled("BTC/USDT:USDT", trade, _FakeOrder("sell"), _dt(9))

    resolved = trade.get_custom_data(strat.RESOLVED_KEY)
    assert resolved is not None
    assert resolved["outcome"] == outcome
    assert resolved["exit_reason"] == reason
    assert resolved["setup_id"] == "hashLONG"  # o hash, não o rótulo
    assert resolved["enter_tag"] == "A3_long"  # o rótulo assinatura_direção


def test_t6_resolved_not_written_on_open_exit_fill():
    """Fill de saída parcial com trade ainda aberto não grava RESOLVED."""
    strat = _strategy()
    strat.dp = _FakeDP(pd.DataFrame())
    trade = _FakeTrade("idLONG", exit_side="sell", is_open=True, exit_reason=None)
    strat.order_filled("BTC/USDT:USDT", trade, _FakeOrder("sell"), _dt(9))
    assert trade.get_custom_data(strat.RESOLVED_KEY) is None
