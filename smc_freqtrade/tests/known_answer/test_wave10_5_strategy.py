"""Known-answer da Wave 10.5 (freqtrade; venv efêmero + VM) — pipeline de paridade.

OBJETIVO
    Selar, com o `SMCStrategyCandidate` REAL instanciado sob freqtrade, o
    entregável da Wave 10.5 (§2/§3 do briefing): a Candidate abandona o merge
    `@informative` herdado e monta o MTF pelo pipeline de paridade golden
    (`analyze`×3 + `align_informative`×2 + `tag_sessions` + `multi`×2), buscando
    os informativos 1h/4h por `self.dp.get_pair_dataframe`. Um DataProvider
    duck-typed (só `get_pair_dataframe`) devolve OHLCV sintético 15m/1h/4h e o
    `populate_indicators` real roda ponta a ponta:

      T1 — Neutralização dos `@informative` herdados: `_ft_informative` da
           instância da Candidate é VAZIO (os métodos `populate_indicators_1h/4h`
           foram sobrescritos SEM decorador, §2.1). Prova de que o branch de
           preenchimento de head de `merge_informative_pair`
           (`freqtrade/strategy/strategy_helper.py:96-109`) — que crashou o P3 —
           saiu do grafo de execução.
      T2 — `populate_indicators` real (com o stub de dp) produz as colunas
           exigidas: `require_candidate_columns` NÃO levanta e as 9
           `setup_state__{sid}` estão presentes.
      T3 — Guarda fail-loud (§2.4): sem `dp`, `populate_indicators` levanta
           exceção clara (`RuntimeError`), nunca prosseguindo com colunas
           `_1h`/`_4h` ausentes. Idem informativo vazio.

GUARD DE IMPORT (padrão wave10a/b/10.1-strategy/10.2)
    `pytest.importorskip("freqtrade")` no topo: sem freqtrade (sandbox do Code) o
    módulo NÃO coleta (skip), mantendo a suíte sandbox intocada. Roda na VM/venv
    efêmero, onde o freqtrade existe.

DADOS
    100% sintético (random walk determinístico por TF) — nenhum backtest sobre
    BTC/ETH/SOL. O objeto é a CAMADA DE MONTAGEM MTF da Candidate, não a engine
    (coberta pelo golden) nem P&L.

NÃO FAZER
    Tocar `smc_engine/`, `SMCStrategy.py`, `SMCStrategyCandidate.py`,
    `candidate_frozen.py`, config ou `tools/mtf_align.py`. Não validar edge.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# --- Guard de import: sem freqtrade, não coleta (skip) --------------------
pytest.importorskip("freqtrade")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

_KA_DIR = Path(__file__).resolve().parent
_SUBPROJECT_ROOT = _KA_DIR.parents[1]
_STRATEGIES_DIR = _SUBPROJECT_ROOT / "user_data" / "strategies"
for _p in (str(_SUBPROJECT_ROOT), str(_STRATEGIES_DIR), str(_KA_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from freqtrade.enums import CandleType  # noqa: E402

from SMCStrategyCandidate import SMCStrategyCandidate, _ALL_SIDS  # noqa: E402
from candidate_frozen import require_candidate_columns  # noqa: E402

_PAIR = "SYNTH/USDT:USDT"


# ==========================================================================
# Dados sintéticos + DataProvider duck-typed
# ==========================================================================

def _synth_ohlcv(freq: str, n: int, seed: int) -> pd.DataFrame:
    """OHLCV sintético determinístico (random walk) para um TF.

    Coberto por `analyze()` (n ≥ ~203 satisfaz os detectores com defaults —
    ver nota do `conftest.py`). Datas tz-aware UTC no `freq` do TF, como as que
    `dp.get_pair_dataframe` devolveria.
    """
    rng = np.random.RandomState(seed)
    dates = pd.date_range("2026-01-01", periods=n, freq=freq, tz="UTC")
    close = 1000.0 + rng.normal(0, 1, n).cumsum()
    open_ = close + rng.normal(0, 0.5, n)
    high = np.maximum(open_, close) + np.abs(rng.normal(0, 0.5, n))
    low = np.minimum(open_, close) - np.abs(rng.normal(0, 0.5, n))
    vol = np.abs(rng.normal(100, 10, n))
    return pd.DataFrame(
        {"date": dates, "open": open_, "high": high, "low": low,
         "close": close, "volume": vol}
    )


class _StubDataProvider:
    """DataProvider duck-typed: só `get_pair_dataframe` (o que a Candidate usa).

    Devolve o informativo sintético do TF pedido. Suficiente para o pipeline de
    paridade (§2.3): `populate_indicators` só chama `get_pair_dataframe(pair,
    '1h'|'4h')`. Sids/whitelist não são exercitados aqui (isso é
    `informative_pairs`, testado indiretamente pela presença dos informativos).
    """

    def __init__(self) -> None:
        # Informativos mais longos que a base para cobrir o span do align.
        self._inf = {
            "1h": _synth_ohlcv("1h", 400, seed=2),
            "4h": _synth_ohlcv("4h", 300, seed=3),
        }

    def get_pair_dataframe(self, pair: str, timeframe: str) -> pd.DataFrame:
        return self._inf[timeframe].copy()


def _strategy() -> SMCStrategyCandidate:
    return SMCStrategyCandidate({"candle_type_def": CandleType.FUTURES})


def _base_15m() -> pd.DataFrame:
    return _synth_ohlcv("15min", 800, seed=1)


# ==========================================================================
# T1 — @informative herdados neutralizados (_ft_informative vazio)
# ==========================================================================

def test_t1_ft_informative_is_empty():
    """A Candidate não registra informativos via decorador (§2.1).

    `populate_indicators_1h/4h` foram sobrescritos SEM `@informative`, então
    `_ft_informative` (coletado varrendo `dir(self.__class__)` por métodos com
    o atributo `_ft_informative`) fica vazio — o merge herdado (e seu branch de
    head problemático em `strategy_helper.py:96-109`) sai do grafo.
    """
    strat = _strategy()
    assert list(strat._ft_informative) == []


def test_t1_neutralized_methods_are_noops():
    """Os métodos neutralizados devolvem o df intacto (corpos no-op)."""
    strat = _strategy()
    df = _base_15m()
    assert strat.populate_indicators_1h(df, {"pair": _PAIR}) is df
    assert strat.populate_indicators_4h(df, {"pair": _PAIR}) is df


# ==========================================================================
# T2 — populate_indicators real (com stub de dp) produz as colunas exigidas
# ==========================================================================

def test_t2_populate_indicators_end_to_end_produces_required_columns():
    """Pipeline de paridade real roda ponta a ponta e emite as colunas da entrada."""
    strat = _strategy()
    strat.dp = _StubDataProvider()
    out = strat.populate_indicators(_base_15m(), {"pair": _PAIR})

    # Fail-loud a jusante NÃO levanta: as 18 colunas exigidas estão presentes.
    require_candidate_columns(out.columns)
    # As 9 colunas de estado (Grupo C + R) presentes.
    for sid in _ALL_SIDS:
        assert f"setup_state__{sid}" in out.columns
    assert len(_ALL_SIDS) == 9
    # Prova do merge de paridade: colunas OHLCV sufixadas `_1h`/`_4h`.
    assert "close_1h" in out.columns
    assert "close_4h" in out.columns
    # O número de linhas é o da base 15m (align nunca cria linhas).
    assert len(out) == len(_base_15m())


# ==========================================================================
# T3 — guarda fail-loud (§2.4): dp ausente / informativo vazio → exceção clara
# ==========================================================================

def test_t3_missing_dp_raises_clear_error():
    """Sem `dp`, `populate_indicators` levanta RuntimeError (não prossegue mudo)."""
    strat = _strategy()
    strat.dp = None
    with pytest.raises(RuntimeError, match="dp"):
        strat.populate_indicators(_base_15m(), {"pair": _PAIR})


def test_t3_empty_informative_raises_clear_error():
    """Informativo vazio → RuntimeError citando o TF (§2.4)."""

    class _EmptyDP:
        def get_pair_dataframe(self, pair: str, timeframe: str) -> pd.DataFrame:
            return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])

    strat = _strategy()
    strat.dp = _EmptyDP()
    with pytest.raises(RuntimeError, match="1h|informativo"):
        strat.populate_indicators(_base_15m(), {"pair": _PAIR})
