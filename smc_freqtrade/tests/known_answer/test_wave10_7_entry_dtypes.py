"""Selo de regressão da Wave 10.7 (freqtrade; venv efêmero + VM) — entrada NA-safe.

OBJETIVO
    Fechar o end-to-end que faltava: o pipeline REAL da engine (sem NENHUMA
    coluna de setup injetada à mão) alimentando a `populate_entry_trend` REAL da
    `SMCStrategyCandidate`. É o teste que replica o crash do P3 (4ª tentativa,
    `SMCStrategyCandidate.py:341`, `TypeError: boolean value of NA is ambiguous`):
    `compute_setup_state_multi` emite `setup_state__{sid}` como pandas StringDtype
    (sentinela `pd.NA`); o consumo antigo (`.to_numpy(dtype=object)` + `==` + `|=`)
    propagava `pd.NA` até o `NAType.__bool__`. Os fixtures existentes (object/None)
    tinham paridade de VALOR sem paridade de DTYPE, então nunca pegaram o bug.

    Aqui NÃO há injeção: o df vem do MESMO pipeline que a Candidate roda em
    produção (`analyze`×3 desalinhado + `align_informative`×2 + `tag_sessions` +
    `compute_setup_state_multi`×2, padrão do `test_mtf_align_head.py::T3`), com a
    base 15m FATIADA para iniciar no meio de um candle 4h — o cenário exato do P3.
    Assim as colunas de estado chegam a `populate_entry_trend` como StringDtype
    real, exercitando o caminho NA-safe da correção (§2.1).

ASSERTS (§2.3 do briefing 10.7)
    T1 — `populate_entry_trend` NÃO levanta sobre o df de dtype real;
    T2 — colunas `enter_long/enter_short/enter_tag/setup_conflict_dirs` presentes;
    T3 — nenhuma linha com `enter_long`/`enter_short` verdadeiro sem `enter_tag`
         válido (`f"{sid}_{direção}"` parseável).

GUARD DE IMPORT (padrão wave10a/b/10.1-strategy/10.5-strategy)
    `pytest.importorskip("freqtrade")` no topo: sem freqtrade (sandbox do Code) o
    módulo NÃO coleta (skip), mantendo a suíte sandbox intocada. Roda na VM/venv
    efêmero. `populate_entry_trend` é chamado direto (sem loop de backtest): só a
    fronteira de consumo das colunas da engine está sob teste.

DADOS
    Goldens MTF reais (`tests/golden/data/btc_usdt_swap_{15m,1h,4h}_window.csv`),
    a base 15m fatiada para desalinhar (o head-fill do P3). Nenhuma injeção.

NÃO FAZER
    Tocar `smc_engine/`, `SMCStrategy.py`, `SMCStrategyCandidate.py`,
    `candidate_frozen.py`, config, `tools/`. Não afrouxar assert por dtype — um
    assert que quebre por dtype É o bug sendo pego (corrigir pelo §2.1).
"""
from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path

import pytest

# --- Guard de import: sem freqtrade, não coleta (skip) --------------------
pytest.importorskip("freqtrade")

import pandas as pd  # noqa: E402

_KA_DIR = Path(__file__).resolve().parent
_SUBPROJECT_ROOT = _KA_DIR.parents[1]
_STRATEGIES_DIR = _SUBPROJECT_ROOT / "user_data" / "strategies"
_GOLDEN_DIR = _SUBPROJECT_ROOT / "tests" / "golden" / "data"
for _p in (str(_SUBPROJECT_ROOT), str(_STRATEGIES_DIR), str(_KA_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from freqtrade.enums import CandleType  # noqa: E402

from SMCStrategyCandidate import (  # noqa: E402
    SMCStrategyCandidate,
    COL_SETUP_CONFLICT_DIRS,
    _ALL_SIDS,
)

_PAIR = "BTC/USDT:USDT"


def _load_ohlcv(name: str) -> pd.DataFrame:
    df = pd.read_csv(_GOLDEN_DIR / name)
    df["date"] = pd.to_datetime(df["timestamp_utc"], utc=True)
    return df[["date", "open", "high", "low", "close", "volume"]]


@lru_cache(maxsize=1)
def _real_pipeline_df() -> pd.DataFrame:
    """df de produção da Candidate — pipeline REAL, base 15m desalinhada (P3).

    Espelha `SMCStrategyCandidate.populate_indicators` (padrão
    `test_mtf_align_head.py::T3`): `analyze`×3 + `align_informative`×2 +
    `tag_sessions` + `compute_setup_state_multi`×2. Sem colunas injetadas — as
    `setup_state__{sid}` chegam como StringDtype real (sentinela `pd.NA`). Import
    tardio para não pagar `analyze`/`candidate_frozen` na coleta se deselecionado.
    """
    from smc_engine import analyze, tag_sessions
    from smc_engine.setup_state import compute_setup_state_multi
    from candidate_frozen import build_cfg_c, build_cfg_r
    from tools.mtf_align import align_informative

    raw_15m = _load_ohlcv("btc_usdt_swap_15m_window.csv")
    # 37 candles de 15m = 9h15 → base começa 09:15, MEIO do candle 4h 08:00 (P3).
    sliced = raw_15m.iloc[37:].reset_index(drop=True)
    assert sliced["date"].iloc[0] == pd.Timestamp("2026-01-01 09:15", tz="UTC")

    base = analyze(sliced).df
    res_1h = analyze(_load_ohlcv("btc_usdt_swap_1h_window.csv")).df
    res_4h = analyze(_load_ohlcv("btc_usdt_swap_4h_window.csv")).df

    merged = align_informative(base, res_1h, "15m", "1h", suffix="1h")
    merged = align_informative(merged, res_4h, "15m", "4h", suffix="4h")
    merged = tag_sessions(merged)
    merged = compute_setup_state_multi(merged, build_cfg_c())
    merged = compute_setup_state_multi(merged, build_cfg_r())
    return merged


def _strategy() -> SMCStrategyCandidate:
    return SMCStrategyCandidate({"candle_type_def": CandleType.FUTURES})


# ==========================================================================
# T1 — populate_entry_trend real sobre dtype real NÃO levanta (o crash do P3)
# ==========================================================================

def test_t1_entry_trend_no_raise_on_real_string_dtype():
    """A entrada real roda sobre `setup_state__{sid}` StringDtype sem `TypeError`.

    Antes da correção (§2.1) esta chamada crashava em
    `SMCStrategyCandidate.py:341` com `boolean value of NA is ambiguous` — o df
    tem `pd.NA` nas velas sem CONFIRMED, e o consumo object-array propagava o NA.
    """
    strat = _strategy()
    df = _real_pipeline_df().copy()
    # Prova de dtype: as colunas de estado são StringDtype (não object) — a
    # premissa do §1 e a razão de o crash surgir só na produção.
    for sid in _ALL_SIDS:
        assert isinstance(
            df[f"setup_state__{sid}"].dtype, pd.StringDtype
        ), f"setup_state__{sid} deveria ser StringDtype (paridade com a engine)"

    out = strat.populate_entry_trend(df, {"pair": _PAIR})  # não deve levantar
    assert out is not None


# ==========================================================================
# T2 — colunas de sinal presentes
# ==========================================================================

def test_t2_signal_columns_present():
    """`enter_long/enter_short/enter_tag/setup_conflict_dirs` presentes na saída."""
    strat = _strategy()
    out = strat.populate_entry_trend(_real_pipeline_df().copy(), {"pair": _PAIR})
    for col in ("enter_long", "enter_short", "enter_tag", COL_SETUP_CONFLICT_DIRS):
        assert col in out.columns, f"coluna de sinal ausente: {col}"


# ==========================================================================
# T3 — nenhuma entrada verdadeira sem enter_tag válido
# ==========================================================================

def test_t3_no_entry_without_valid_tag():
    """Toda linha com `enter_long`/`enter_short` == 1 tem `enter_tag` parseável.

    `enter_tag = f"{sid}_{direção}"`: não-vazio, com `_`, e a direção casa o lado
    (long→enter_long, short→enter_short). Um sinal sem tag válido seria um trade
    órfão (sem sid para ancorar SL/saída) — o contrato da arbitragem D3.
    """
    strat = _strategy()
    out = strat.populate_entry_trend(_real_pipeline_df().copy(), {"pair": _PAIR})

    entered = out[(out["enter_long"] == 1) | (out["enter_short"] == 1)]
    for _, row in entered.iterrows():
        tag = row["enter_tag"]
        assert isinstance(tag, str) and tag and "_" in tag, (
            f"entrada sem enter_tag válido: {tag!r}"
        )
        sid, direction = tag.split("_", 1)
        assert sid in _ALL_SIDS, f"sid do tag fora do registry: {sid!r}"
        if row["enter_long"] == 1:
            assert direction == "long", f"enter_long com tag {tag!r}"
        else:
            assert direction == "short", f"enter_short com tag {tag!r}"
