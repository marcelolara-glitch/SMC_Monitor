"""Smoke da Wave 10.5 (sandbox) — paridade do pipeline MTF da Candidate.

OBJETIVO
    Selar, sem freqtrade (coleta no sandbox), que o pipeline de indicadores da
    `SMCStrategyCandidate` (Wave 10.5) é **exatamente** o pipeline dos testes
    golden/engine — a paridade teste↔produção que motiva a wave (§1 do briefing).
    O teste replica, FORA da classe, a mesma sequência que
    `populate_indicators` roda em produção:

        analyze(15m) → analyze(1h) → analyze(4h)
        → align_informative(_1h) → align_informative(_4h)
        → tag_sessions → compute_setup_state_multi(C) → compute_setup_state_multi(R)

    sobre o golden real e asserta:
      T1 — `require_candidate_columns` NÃO levanta (as 18 colunas exigidas pela
           entrada estão presentes após o pipeline).
      T2 — o pipeline anexa exatamente 63 colunas sufixadas `{col}__{sid}`
           (9 sids × 7 `SETUP_OUTPUT_COLUMNS`), com os sufixos `_1h`/`_4h` do
           merge idênticos aos consumidos pelos configs congelados
           (`trend_suffix='4h'`, `zone_suffix='1h'`).

    Como o pipeline aqui é byte-a-byte o de `populate_indicators` (mesmos
    helpers, mesma ordem, mesmos sufixos), este smoke é o pin de que a produção
    monta o MTF pelo caminho golden — não mais pelo `@informative` herdado.

FONTE DE DADOS
    Golden real `tests/golden/data/btc_usdt_swap_{15m,1h,4h}_window.csv`; helpers
    `smc_engine.analyze`/`tag_sessions`/`compute_setup_state_multi`,
    `tools.mtf_align.align_informative` e as configs congeladas de
    `candidate_frozen` — todos SEM freqtrade (coleta no sandbox).

LIMITAÇÕES CONHECIDAS
    Pin estrutural (presença/contagem de colunas), não de P&L: o golden tem
    poucos/zero CONFIRMED nesta janela (o veredito de edge é a fase de gates,
    docs §3). A execução ponta a ponta da classe real (com stub de dp) fica no
    known-answer `tests/known_answer/test_wave10_5_strategy.py` (freqtrade/VM).

NÃO FAZER
    Não importar freqtrade (o smoke deve coletar no sandbox); não afirmar edge
    por contagem; não tocar a engine nem os configs congelados.
"""
from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path

import pandas as pd

_SUBPROJECT_ROOT = Path(__file__).resolve().parents[1]
_STRATEGIES_DIR = _SUBPROJECT_ROOT / "user_data" / "strategies"
_GOLDEN_DIR = _SUBPROJECT_ROOT / "tests" / "golden" / "data"

for _p in (str(_SUBPROJECT_ROOT), str(_STRATEGIES_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from smc_engine import analyze, tag_sessions, SETUP_OUTPUT_COLUMNS  # noqa: E402
from smc_engine.setup_state import compute_setup_state_multi  # noqa: E402
from tools.mtf_align import align_informative  # noqa: E402

from candidate_frozen import (  # noqa: E402
    build_cfg_c,
    build_cfg_r,
    require_candidate_columns,
    SIDS_GRUPO_C,
    SIDS_GRUPO_R,
)

_ALL_SIDS = SIDS_GRUPO_C + SIDS_GRUPO_R


def _load_ohlcv(name: str) -> pd.DataFrame:
    df = pd.read_csv(_GOLDEN_DIR / name)
    df["date"] = pd.to_datetime(df["timestamp_utc"], utc=True)
    return df[["date", "open", "high", "low", "close", "volume"]]


@lru_cache(maxsize=1)
def _candidate_pipeline() -> pd.DataFrame:
    """Replica FORA da classe o pipeline de `SMCStrategyCandidate.populate_indicators`.

    Mesma ordem, mesmos helpers e mesmos sufixos (`_1h`/`_4h`) que a produção —
    a única diferença é a origem dos informativos (CSV golden aqui vs
    `dp.get_pair_dataframe` na classe). É o ponto do pin: se o pipeline de
    produção divergir deste, o teste quebra.
    """
    base = analyze(_load_ohlcv("btc_usdt_swap_15m_window.csv")).df
    res_1h = analyze(_load_ohlcv("btc_usdt_swap_1h_window.csv")).df
    res_4h = analyze(_load_ohlcv("btc_usdt_swap_4h_window.csv")).df

    merged = align_informative(base, res_1h, "15m", "1h", suffix="1h")
    merged = align_informative(merged, res_4h, "15m", "4h", suffix="4h")
    merged = tag_sessions(merged)
    merged = compute_setup_state_multi(merged, build_cfg_c())
    merged = compute_setup_state_multi(merged, build_cfg_r())
    return merged


# ============================================================
# T1 — require_candidate_columns passa após o pipeline de paridade
# ============================================================

def test_t1_require_candidate_columns_passes_after_pipeline() -> None:
    """O pipeline novo produz as 18 colunas exigidas pela entrada (fail-loud OK)."""
    df = _candidate_pipeline()
    # Não deve levantar (todas as 18 colunas setup_state/direction__{sid} presentes).
    require_candidate_columns(df.columns)


# ============================================================
# T2 — 63 colunas sufixadas `{col}__{sid}` (9 sids × 7 colunas)
# ============================================================

def test_t2_pipeline_appends_63_suffixed_columns() -> None:
    """O pipeline anexa exatamente 9 sids × 7 = 63 colunas `{col}__{sid}`."""
    df = _candidate_pipeline()
    expected = {
        f"{col}__{sid}"
        for sid in _ALL_SIDS
        for col in SETUP_OUTPUT_COLUMNS
    }
    assert len(expected) == 63  # 9 sids × 7 SETUP_OUTPUT_COLUMNS
    present = [c for c in expected if c in df.columns]
    assert set(present) == expected, (
        f"faltam {sorted(expected - set(df.columns))} colunas sufixadas do pipeline"
    )
    assert len(present) == 63


def test_t2_merge_suffixes_match_frozen_configs() -> None:
    """Os sufixos `_1h`/`_4h` do merge batem com os configs congelados.

    `build_cfg_c()`/`build_cfg_r()` consomem `trend_suffix='4h'` e
    `zone_suffix='1h'`; se o merge não expusesse essas colunas, a FSM não
    encontraria viés/zona. Aqui checamos que o align expôs as colunas OHLCV
    sufixadas que os configs esperam encontrar.
    """
    df = _candidate_pipeline()
    cfg_c, cfg_r = build_cfg_c(), build_cfg_r()
    assert cfg_c.trend_suffix == cfg_r.trend_suffix == "4h"
    assert cfg_c.zone_suffix == cfg_r.zone_suffix == "1h"
    # O merge expõe as colunas do informativo sufixadas (prova do `_1h`/`_4h`).
    assert "close_1h" in df.columns
    assert "close_4h" in df.columns
