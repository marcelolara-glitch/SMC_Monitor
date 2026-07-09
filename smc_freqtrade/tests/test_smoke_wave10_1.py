"""Smoke da Wave 10.1 (sandbox) — configs congeladas + multi por grupo + D3.

OBJETIVO
    Selar, sem freqtrade (coleta no sandbox), a candidata congelada da Wave
    10.1 (`docs/CONGELAMENTO_CANDIDATA_V2_E_GATES_EDGE.md`):
      T1 — `build_cfg_c()`/`build_cfg_r()` constroem sem `ValueError` (guardas
           passam) e cada campo confere com a tabela congelada (§1.1/§1.2). O
           teste É o pin do congelamento.
      T2 — `compute_setup_state_multi(golden, build_cfg_c())` anexa 7 sids × 7
           colunas; a chamada do Grupo R anexa 2 × 7; zero colisão; colunas
           pré-existentes byte-idênticas.
      T3 — unit de `arbitrate_d3`: vazio/single/priority_tiebreak/conflict.
      T4 — sanity: contagem de CONFIRMED por sid no golden (sem assert de
           valor — golden de 4 meses, referência de handoff usa outra config).

FONTE DE DADOS
    Golden real `tests/golden/data/btc_usdt_swap_{15m,1h,4h}_window.csv`
    mergeado com `align_informative` (espelho de `merge_informative_pair`) +
    `tag_sessions` na base (as killzones que a A7 exige). Configs/arbitragem de
    `candidate_frozen` (sem freqtrade).

LIMITAÇÕES CONHECIDAS
    Golden com poucos/zero CONFIRMED nesta janela — T4 é sanity, não P&L (o
    veredito de edge é a fase de gates, docs §3). Sem backtest/lookahead (VM).

NÃO FAZER
    Não validar contra LuxAlgo TradingView; não afirmar edge por contagem.
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

from smc_engine import (  # noqa: E402
    analyze,
    tag_sessions,
    STATE_CONFIRMED,
    SETUP_OUTPUT_COLUMNS,
)
from smc_engine.setup_state import compute_setup_state_multi  # noqa: E402
from tools.mtf_align import align_informative  # noqa: E402

import pytest  # noqa: E402

from candidate_frozen import (  # noqa: E402
    build_cfg_c,
    build_cfg_r,
    arbitrate_d3,
    require_candidate_columns,
    D3_PRIORITY,
    SIDS_GRUPO_C,
    SIDS_GRUPO_R,
)


def _load_ohlcv(name: str) -> pd.DataFrame:
    df = pd.read_csv(_GOLDEN_DIR / name)
    df["date"] = pd.to_datetime(df["timestamp_utc"], utc=True)
    return df[["date", "open", "high", "low", "close", "volume"]]


@lru_cache(maxsize=1)
def _merged_golden() -> pd.DataFrame:
    """df 15m mergeado com 1h/4h + `tag_sessions` (killzones da A7)."""
    r4 = analyze(_load_ohlcv("btc_usdt_swap_4h_window.csv"))
    r1 = analyze(_load_ohlcv("btc_usdt_swap_1h_window.csv"))
    r15 = analyze(_load_ohlcv("btc_usdt_swap_15m_window.csv"))
    merged = align_informative(r15.df, r1.df, "15m", "1h", suffix="1h")
    merged = align_informative(merged, r4.df, "15m", "4h", suffix="4h")
    merged = tag_sessions(merged)
    return merged


# ============================================================
# T1 — pin campo-a-campo das duas configs congeladas
# ============================================================

# Valores esperados verbatim do doc §1.1 (Grupo C).
_EXPECTED_C = {
    "signature": SIDS_GRUPO_C,
    "entry_mode": "confirmation",
    "armed_escape_pct": 0.02,
    "armed_timeout_candles": 24,
    "pending_timeout_candles": 16,
    "sweep_recency_candles": 16,
    "fvg_ob_adjacency_pct": 0.003,
    "rejection_wick_frac": 0.5,
    "rejection_close_frac": 0.667,
    "volume_pct_min": 0.2,
    "trend_suffix": "4h",
    "zone_suffix": "1h",
    "arming_proximity_pct": 0.02,
    "confirmation_trigger": "choch",
    "anchor_invalidation": "frozen_band",
    "a9_variant": "sweep_band",
    "displacement_gate": "confirm",
    "displacement_body_len": 10,
    "displacement_wick_frac": 0.36,
    "ote_lifecycle": "v2",
    "ote_require_eq_cross": True,
    "ote_require_confluence": True,
    "a7_variant": "legacy",
    "a7_fvg_window": 2,
    "killzone_qualifier": (),
    "ob_semantics": "strategic",
}

# Valores esperados verbatim do doc §1.2 (Grupo R). "Demais campos idênticos
# ao Grupo C" (última linha da tabela) → reproduzidos explícitos.
_EXPECTED_R = {
    "signature": SIDS_GRUPO_R,
    "entry_mode": "risk",
    "armed_escape_pct": 0.02,
    "armed_timeout_candles": 24,
    "pending_timeout_candles": 16,
    "sweep_recency_candles": 16,
    "fvg_ob_adjacency_pct": 0.003,
    "rejection_wick_frac": 0.5,
    "rejection_close_frac": 0.667,
    "volume_pct_min": 0.2,
    "trend_suffix": "4h",
    "zone_suffix": "1h",
    "arming_proximity_pct": 0.02,
    "confirmation_trigger": "legacy",
    "anchor_invalidation": "frozen_band",
    "a9_variant": "legacy_ob",
    "displacement_gate": "off",
    "displacement_body_len": 10,
    "displacement_wick_frac": 0.36,
    "ote_lifecycle": "legacy",
    "ote_require_eq_cross": False,
    "ote_require_confluence": False,
    "a7_variant": "chain_v2",
    "a7_fvg_window": 2,
    "killzone_qualifier": (),
    "ob_semantics": "primitive",
}


def test_t1_cfg_c_builds_and_pins_all_fields() -> None:
    """Grupo C constrói sem ValueError e cada campo confere com o doc §1.1."""
    cfg = build_cfg_c()  # não deve levantar (guardas passam)
    for field, expected in _EXPECTED_C.items():
        assert getattr(cfg, field) == expected, (
            f"Grupo C campo {field!r}: {getattr(cfg, field)!r} != {expected!r}"
        )


def test_t1_cfg_r_builds_and_pins_all_fields() -> None:
    """Grupo R constrói sem ValueError e cada campo confere com o doc §1.2."""
    cfg = build_cfg_r()  # não deve levantar (guardas passam)
    for field, expected in _EXPECTED_R.items():
        assert getattr(cfg, field) == expected, (
            f"Grupo R campo {field!r}: {getattr(cfg, field)!r} != {expected!r}"
        )


def test_t1_field_sets_cover_the_whole_config() -> None:
    """As tabelas pinam TODOS os campos do SetupConfig (nenhum implícito)."""
    from dataclasses import fields

    all_fields = {f.name for f in fields(build_cfg_c())}
    assert set(_EXPECTED_C) == all_fields
    assert set(_EXPECTED_R) == all_fields


# ============================================================
# T2 — multi por grupo: 7×7 + 2×7, zero colisão, base intacta
# ============================================================

def test_t2_multi_appends_disjoint_columns_without_collision() -> None:
    """Grupo C anexa 7 sids × 7 colunas; Grupo R anexa 2 × 7; sem colisão;
    colunas pré-existentes byte-idênticas."""
    golden = _merged_golden()
    orig_cols = list(golden.columns)

    res_c = compute_setup_state_multi(golden, build_cfg_c())
    new_c = [c for c in res_c.columns if c not in orig_cols]
    expected_c = {
        f"{col}__{sid}" for col in SETUP_OUTPUT_COLUMNS for sid in SIDS_GRUPO_C
    }
    assert set(new_c) == expected_c
    assert len(new_c) == 7 * 7  # 7 sids × 7 colunas de output
    # Colunas originais byte-idênticas após a 1ª chamada.
    assert res_c[orig_cols].equals(golden[orig_cols])

    res_r = compute_setup_state_multi(res_c, build_cfg_r())
    new_r = [c for c in res_r.columns if c not in res_c.columns]
    expected_r = {
        f"{col}__{sid}" for col in SETUP_OUTPUT_COLUMNS for sid in SIDS_GRUPO_R
    }
    assert set(new_r) == expected_r
    assert len(new_r) == 2 * 7  # 2 sids × 7 colunas
    # Zero colisão entre os grupos (sids disjuntos).
    assert expected_c.isdisjoint(expected_r)
    # As colunas do Grupo C (e as originais) sobrevivem byte-idênticas.
    assert res_r[list(res_c.columns)].equals(res_c)


# ============================================================
# T3 — arbitragem D3 (unit puro)
# ============================================================

def test_t3_arbitrate_empty() -> None:
    assert arbitrate_d3([]) == (None, None, "empty")


def test_t3_arbitrate_single() -> None:
    assert arbitrate_d3([("A3", "long")]) == ("A3", "long", "single")
    assert arbitrate_d3([("A7", "short")]) == ("A7", "short", "single")


def test_t3_arbitrate_priority_tiebreak_same_direction() -> None:
    """Dois no mesmo lado → vence a maior prioridade D3 (menor índice)."""
    # A3 (0) > A2 (1): A3 vence.
    assert arbitrate_d3([("A2", "long"), ("A3", "long")]) == (
        "A3", "long", "priority_tiebreak",
    )
    # A5 (3) > A9 (5) > A10 (8): A5 vence, ordem de entrada irrelevante.
    assert arbitrate_d3([("A10", "short"), ("A9", "short"), ("A5", "short")]) == (
        "A5", "short", "priority_tiebreak",
    )


def test_t3_arbitrate_conflict_dirs() -> None:
    """Direções opostas na mesma vela → nenhuma entrada (§1.3-2)."""
    assert arbitrate_d3([("A3", "long"), ("A2", "short")]) == (
        None, None, "conflict_dirs",
    )


def test_t3_priority_order_matches_registry() -> None:
    """A ordem D3 derivada do registry bate com a canônica do doc §1.3."""
    canonical = ["A3", "A2", "A4a", "A5", "A1", "A9", "A6", "A7", "A10"]
    assert sorted(D3_PRIORITY, key=lambda s: D3_PRIORITY[s]) == canonical


# ============================================================
# T4 — sanity: contagem de CONFIRMED por sid (sem assert de valor)
# ============================================================

def test_t4_confirmed_counts_per_sid_report() -> None:
    """Reporta a contagem de CONFIRMED por sid no golden (sanity, não P&L)."""
    golden = _merged_golden()
    res = compute_setup_state_multi(golden, build_cfg_c())
    res = compute_setup_state_multi(res, build_cfg_r())
    report: list[str] = []
    for sid in SIDS_GRUPO_C + SIDS_GRUPO_R:
        col = f"setup_state__{sid}"
        n_conf = int((res[col] == STATE_CONFIRMED).sum())
        report.append(f"{sid:>5}: CONFIRMED={n_conf}")
    print("\n[Wave 10.1 sanity — CONFIRMED por sid no golden BTC (4 meses)]")
    print("\n".join(report))
    # Sanity estrutural: todas as 9 colunas de estado existem.
    for sid in SIDS_GRUPO_C + SIDS_GRUPO_R:
        assert f"setup_state__{sid}" in res.columns


# ============================================================
# T5 — fail-loud em coluna sufixada ausente (emenda de auditoria)
# ============================================================

def test_t5_require_columns_passes_on_wired_df() -> None:
    """Sobre o df já processado pelas duas chamadas de multi (fiação
    completa), `require_candidate_columns` não levanta."""
    golden = _merged_golden()
    res = compute_setup_state_multi(golden, build_cfg_c())
    res = compute_setup_state_multi(res, build_cfg_r())
    # Não deve levantar (todas as 18 colunas exigidas presentes).
    require_candidate_columns(res.columns)


def test_t5_require_columns_fails_loud_listing_missing() -> None:
    """Dropar 2 colunas de sids distintos ⇒ ValueError citando AMBAS."""
    golden = _merged_golden()
    res = compute_setup_state_multi(golden, build_cfg_c())
    res = compute_setup_state_multi(res, build_cfg_r())
    dropped = res.drop(columns=["setup_state__A3", "setup_direction__A7"])
    with pytest.raises(ValueError) as excinfo:
        require_candidate_columns(dropped.columns)
    msg = str(excinfo.value)
    assert "setup_state__A3" in msg
    assert "setup_direction__A7" in msg
