"""Smoke da Wave 10.1 (exige freqtrade; VM) — estratégia candidata paralela.

OBJETIVO
    Ratificar `SMCStrategyCandidate` por smoke sintético (o ambiente do Code
    bloqueia a rede da exchange → sem trades reais; selo empírico via
    backtesting é gate da VM). Este módulo importa freqtrade no topo, então
    **não coleta no sandbox** — esperado, mesmo padrão de wave10a/b:
      T1 — a estratégia carrega/instancia; `entry_mode == 'strict'`.
      T2 — `populate_indicators` roda sobre o golden mergeado e anexa as 9
           colunas `setup_state__{sid}` (Grupo C + R).
      T3 — `populate_entry_trend` sobre df sintético: entra só onde há vencedor
           D3; `enter_tag` parseável (`sid_direção`); conflito de direções ⇒
           nenhuma entrada + `setup_conflict_dirs == 1`; priority tiebreak.
      T4 — `entry_mode='hybrid'` levanta `NotImplementedError` (herdado).

FONTE DE DADOS
    Golden CSV (`_merged_base`, padrão wave10a) para T2; DataFrames sintéticos
    com colunas `setup_state__{sid}`/`setup_direction__{sid}` construídos
    in-loco para T3 (estado conhecido, exercita o caminho `CONFIRMED__{sid} →
    enter_long/short → enter_tag`).

LIMITAÇÕES CONHECIDAS
    Não roda backtest/lookahead (gate VM). Sintético mínimo: valida a mecânica
    da entrada/arbitragem, não mede nada.

NÃO FAZER
    Não validar contra LuxAlgo TradingView; não introduzir calibração.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_SUBPROJECT_ROOT = Path(__file__).resolve().parents[1]
_STRATEGIES_DIR = _SUBPROJECT_ROOT / "user_data" / "strategies"
_GOLDEN_DIR = _SUBPROJECT_ROOT / "tests" / "golden" / "data"

for _p in (str(_SUBPROJECT_ROOT), str(_STRATEGIES_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from smc_engine import analyze  # noqa: E402
from tools.mtf_align import align_informative  # noqa: E402

from SMCStrategyCandidate import (  # noqa: E402
    SMCStrategyCandidate,
    COL_SETUP_CONFLICT_DIRS,
    _ALL_SIDS,
)


def _load_golden(tf: str) -> pd.DataFrame:
    df = pd.read_csv(_GOLDEN_DIR / f"btc_usdt_swap_{tf}_window.csv")
    df = df.rename(columns={"timestamp_utc": "date"})
    df["date"] = pd.to_datetime(df["date"], utc=True).dt.tz_localize(None)
    return df[["date", "open", "high", "low", "close", "volume"]]


def _merged_base() -> pd.DataFrame:
    """df base 15m mergeado com `_4h`/`_1h` (padrão wave10a `_merged_base`)."""
    base = _load_golden("15m")
    inf_4h = analyze(_load_golden("4h")).df
    inf_1h = analyze(_load_golden("1h")).df
    merged = align_informative(base, inf_4h, "15m", "4h", suffix="4h")
    merged = align_informative(merged, inf_1h, "15m", "1h", suffix="1h")
    return merged


def _strategy() -> SMCStrategyCandidate:
    from freqtrade.enums import CandleType

    return SMCStrategyCandidate({"candle_type_def": CandleType.FUTURES})


def _dt(i: int) -> pd.Timestamp:
    return pd.Timestamp("2026-01-01", tz="UTC") + pd.Timedelta(minutes=15 * i)


def _entry_df(rows: list[dict], n: int) -> pd.DataFrame:
    """df sintético com as 9 colunas `setup_state__{sid}`/`setup_direction__{sid}`.

    `rows` é uma lista de dicts `{sid: (state, direction)}` por vela; sids não
    citados ficam neutros (None/None)."""
    data: dict = {"date": [_dt(i) for i in range(n)]}
    for sid in _ALL_SIDS:
        data[f"setup_state__{sid}"] = [None] * n
        data[f"setup_direction__{sid}"] = [None] * n
    df = pd.DataFrame(data)
    for i, row in enumerate(rows):
        for sid, (state, direction) in row.items():
            df.at[i, f"setup_state__{sid}"] = state
            df.at[i, f"setup_direction__{sid}"] = direction
    return df


# ============================================================
# T1 — carga
# ============================================================

def test_t1_strategy_loads_strict():
    strat = _strategy()
    assert isinstance(strat, SMCStrategyCandidate)
    assert strat.entry_mode == "strict"


# ============================================================
# T2 — populate_indicators anexa as 9 colunas de estado
# ============================================================

def test_t2_populate_indicators_appends_nine_state_columns():
    strat = _strategy()
    out = strat.populate_indicators(_merged_base(), {"pair": "BTC/USDT:USDT"})
    for sid in _ALL_SIDS:
        assert f"setup_state__{sid}" in out.columns
        assert f"setup_zone_low__{sid}" in out.columns
    assert len(_ALL_SIDS) == 9


# ============================================================
# T3 — populate_entry_trend: vencedor D3, tag, conflito
# ============================================================

def test_t3_entry_single_winner_tag_parseable():
    """Um único CONFIRMED long → enter_long==1, enter_tag='A3_long' parseável."""
    strat = _strategy()
    df = _entry_df([{"A3": ("CONFIRMED", "long")}], n=3)
    out = strat.populate_entry_trend(df, {"pair": "BTC/USDT:USDT"})
    assert out["enter_long"].iloc[0] == 1
    assert out["enter_short"].iloc[0] == 0
    assert out["enter_tag"].iloc[0] == "A3_long"
    # Parseável por split('_', 1) → sid vencedor.
    assert out["enter_tag"].iloc[0].split("_", 1)[0] == "A3"
    assert out[COL_SETUP_CONFLICT_DIRS].iloc[0] == 0
    # Velas sem CONFIRMED → nenhuma entrada.
    assert out["enter_long"].iloc[1] == 0 and out["enter_short"].iloc[1] == 0


def test_t3_entry_priority_tiebreak_same_direction():
    """Dois CONFIRMED mesmo lado → vence a maior prioridade D3 (A3 sobre A9)."""
    strat = _strategy()
    df = _entry_df([{"A9": ("CONFIRMED", "long"), "A3": ("CONFIRMED", "long")}], n=1)
    out = strat.populate_entry_trend(df, {"pair": "BTC/USDT:USDT"})
    assert out["enter_long"].iloc[0] == 1
    assert out["enter_tag"].iloc[0] == "A3_long"


def test_t3_entry_conflict_dirs_no_entry():
    """Direções opostas → nenhuma entrada + setup_conflict_dirs==1 (§1.3-2)."""
    strat = _strategy()
    df = _entry_df([{"A3": ("CONFIRMED", "long"), "A2": ("CONFIRMED", "short")}], n=1)
    out = strat.populate_entry_trend(df, {"pair": "BTC/USDT:USDT"})
    assert out["enter_long"].iloc[0] == 0
    assert out["enter_short"].iloc[0] == 0
    assert out["enter_tag"].iloc[0] == ""
    assert out[COL_SETUP_CONFLICT_DIRS].iloc[0] == 1


def test_t3_entry_group_r_short_confirmed():
    """Um CONFIRMED short do Grupo R (A5) → enter_short==1, tag 'A5_short'."""
    strat = _strategy()
    df = _entry_df([{"A5": ("CONFIRMED", "short")}], n=1)
    out = strat.populate_entry_trend(df, {"pair": "BTC/USDT:USDT"})
    assert out["enter_short"].iloc[0] == 1
    assert out["enter_tag"].iloc[0] == "A5_short"


# ============================================================
# T4 — hybrid é stub
# ============================================================

def test_t4_hybrid_is_stub():
    strat = _strategy()
    strat.entry_mode = "hybrid"
    df = _entry_df([{"A3": ("CONFIRMED", "long")}], n=1)
    with pytest.raises(NotImplementedError):
        strat.populate_entry_trend(df, {"pair": "BTC/USDT:USDT"})
