"""Known-answer de `tools/p3_report.py` (Wave 10.3) — vereditos GE-1/GE-2.

OBJETIVO
    Validar, por resposta-conhecida, que `p3_report` computa a expectância em R
    líquida de fee e os vereditos GE-1/GE-2 (doc de congelamento §3) EXATAMENTE
    como derivado à mão. Reusa o harness de execução da Wave 10.2 (loop de
    backtest REAL do Freqtrade sobre trades sintéticos K1–K4/K6), coleta o
    `results` em memória e o passa por `compute_report`/`render_markdown`.

    A fórmula sob teste (por trade):
        sid      = enter_tag.split('_', 1)[0]
        R_unit   = |open_rate − stop_loss_abs|
        profit_R = profit_abs / (amount × R_unit)      # líquido (fee já em profit_abs)
    e a agregação por sid (n, wins, wr, soma_R, expectancy_R, profit_abs_total).

    CAMPO DO STOP (assunção do briefing §2.2 resolvida no código): o R usa
    `stop_loss_abs` (SL ancorado), NÃO `initial_stop_loss_abs` (stop duro −0.99
    pré-âncora). Long ROUND_UP → stop exato na âncora; short ROUND_DOWN → 1 tick
    abaixo da âncora (mesmo comportamento documentado no K4 da Wave 10.2). As
    expectativas à mão abaixo incorporam esse tick nos cenários short.

GUARD DE IMPORT (padrão wave10a/b/10.1/10.2)
    `pytest.importorskip("freqtrade")` no topo: sem freqtrade (sandbox do Code) o
    módulo não coleta (skip), mantendo a suíte sandbox verde. Roda na VM / venv
    efêmero com freqtrade, onde a execução verde constitui a validação.

NÃO FAZER
    Tocar qualquer arquivo existente; rodar sobre dados de mercado reais. 100%
    sintético (K1–K6 do `ka_data`).
"""
from __future__ import annotations

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

# Harness de execução real da Wave 10.2 (reuso — briefing §3).
from test_known_answer_wave10_2 import _run  # noqa: E402
from ka_data import (  # noqa: E402
    STAKE, DIRECTION_LONG, DIRECTION_SHORT,
    sl_anchor, profit_abs as hand_profit,
)
from tools.p3_report import (  # noqa: E402
    compute_report, render_markdown, filter_window, MIN_TRADES,
)

_PRICE_TICK = 0.01     # espelha o market sintético (precision.price) da 10.2
_ENTRY = 1000.0        # entrada = open[2] em todos os cenários KA
_ZL, _ZH = 990.0, 1010.0   # zona dos cenários K1–K4/K6


@pytest.fixture(scope="module")
def _datadir(tmp_path_factory) -> Path:
    """Datadir temporário (com subpasta `futures`) — nada é lido de disco real."""
    d = tmp_path_factory.mktemp("p3_report_dir")
    (d / "futures").mkdir(parents=True, exist_ok=True)
    return d


# --------------------------------------------------------------------------
# Derivação à mão (idêntica à aritmética do módulo p3_report)
# --------------------------------------------------------------------------

def _amount(entry: float = _ENTRY) -> float:
    """Tamanho da posição (base) @ leverage 1, contractSize 1 = stake/entry."""
    return STAKE / entry


def _sl_used(direction: str) -> float:
    """SL que o export carrega em `stop_loss_abs` para a zona KA (_ZL/_ZH).

    Long: ROUND_UP → exato na âncora. Short: ROUND_DOWN → 1 tick abaixo da âncora
    (comportamento selado no K4 da Wave 10.2).
    """
    anchor = sl_anchor(direction, _ZL, _ZH)
    if direction == DIRECTION_SHORT:
        return anchor - _PRICE_TICK
    return anchor


def _expected_profit_R(direction: str, exit_: float) -> float:
    """profit_R à mão = profit_abs(líquido) / (amount × |entry − stop_loss_abs|)."""
    r_unit = abs(_ENTRY - _sl_used(direction))
    return hand_profit(direction, _ENTRY, exit_) / (_amount() * r_unit)


def _report_for(scenario: str, datadir: Path) -> dict:
    """Roda o cenário no loop real e devolve o report do `p3_report`."""
    results, _strat, _processed = _run(scenario, datadir)
    return compute_report(results)


# ==========================================================================
# K1–K4 / K6 → expectância em R por sid (assert exato contra a mão, 1e-6)
# ==========================================================================

def test_k1_profit_R_long_rr_target(_datadir):
    """K1 — A3 long, alvo R:R. exit=1022 ; anchor=989.01 ; R_unit=10.99.

    profit_abs = 100*[(1022/1000)*(1-fee) - (1+fee)] = 2.0989 ->
    profit_R = 2.0989 / (0.1 * 10.99) = +1.909827115...  (~ +2R menos o fee em R).
    """
    rep = _report_for("K1", _datadir)
    assert rep["n_trades"] == 1
    assert rep["skipped_no_sid"] == 0 and rep["skipped_no_R"] == 0
    assert set(rep["sids"]) == {"A3"}
    r = rep["sids"]["A3"]
    assert r.n == 1 and r.wins == 1
    expected = _expected_profit_R(DIRECTION_LONG, 1022.0)
    assert r.expectancy_R == pytest.approx(expected, abs=1e-6)
    assert r.expectancy_R == pytest.approx(1.909827115560, abs=1e-6)
    assert r.soma_R == pytest.approx(expected, abs=1e-6)
    assert r.wr == pytest.approx(1.0, abs=1e-9)


def test_k2_profit_R_long_stoploss(_datadir):
    """K2 — A3 long, SL ancorado. exit=anchor=989.01 ; R_unit=10.99.

    profit_abs = 100*[(989.01/1000)*(1-fee)-(1+fee)] = -1.1984505 ->
    profit_R = -1.1984505 / (0.1 * 10.99) = -1.090491810...  (~ -1R líquido).
    """
    rep = _report_for("K2", _datadir)
    r = rep["sids"]["A3"]
    assert r.n == 1 and r.wins == 0
    expected = _expected_profit_R(DIRECTION_LONG, _sl_used(DIRECTION_LONG))
    assert r.expectancy_R == pytest.approx(expected, abs=1e-6)
    assert r.expectancy_R == pytest.approx(-1.090491810737, abs=1e-6)
    # ~ -1R líquido (perda de ~1R + fee): entre -1.3R e -0.9R.
    assert -1.3 < r.expectancy_R < -0.9


def test_k3_profit_R_short_rr_target(_datadir):
    """K3 — A5 short, alvo R:R (espelho de K1).

    anchor=1011.01 ; stop_loss_abs=1011.00 (ROUND_DOWN 1 tick) ; R_unit=11.00.
    exit=977 ; profit_abs = 100*[(1-fee)-(977/1000)*(1+fee)] = 2.20115 ->
    profit_R = 2.20115 / (0.1 * 11.00) = +2.001045454...
    """
    rep = _report_for("K3", _datadir)
    assert set(rep["sids"]) == {"A5"}
    r = rep["sids"]["A5"]
    assert r.n == 1 and r.wins == 1
    expected = _expected_profit_R(DIRECTION_SHORT, 977.0)
    assert r.expectancy_R == pytest.approx(expected, abs=1e-6)
    assert r.expectancy_R == pytest.approx(2.001045454545, abs=1e-6)


def test_k4_profit_R_short_stoploss(_datadir):
    """K4 — A5 short, SL ancorado (espelho de K2, com o tick de ROUND_DOWN).

    stop_loss_abs=1011.00 ; R_unit=11.00 ; exit=1011.00 ;
    profit_abs = 100*[(1-fee)-(1011.00/1000)*(1+fee)] = -1.2005500 ->
    profit_R = -1.2005500 / (0.1 * 11.00) = -1.091409090...  (~ -1R líquido).
    """
    rep = _report_for("K4", _datadir)
    r = rep["sids"]["A5"]
    assert r.n == 1 and r.wins == 0
    expected = _expected_profit_R(DIRECTION_SHORT, _sl_used(DIRECTION_SHORT))
    assert r.expectancy_R == pytest.approx(expected, abs=1e-6)
    assert r.expectancy_R == pytest.approx(-1.091409090909, abs=1e-6)
    assert -1.3 < r.expectancy_R < -0.9


def test_k6_attributed_to_priority_winner(_datadir):
    """K6 — 2 sids long mesma vela; vence A3 (prioridade D3). O trade é atribuído
    ao sid VENCEDOR (A3), nunca ao A6, e a aritmética espelha K1.
    """
    rep = _report_for("K6", _datadir)
    assert set(rep["sids"]) == {"A3"}          # A3, não A6
    r = rep["sids"]["A3"]
    assert r.n == 1
    assert r.expectancy_R == pytest.approx(
        _expected_profit_R(DIRECTION_LONG, 1022.0), abs=1e-6)
    assert r.expectancy_R == pytest.approx(1.909827115560, abs=1e-6)


# ==========================================================================
# Colunas de gate — n=1 (< 30) ⇒ PARKED, NÃO descarta (briefing §3)
# ==========================================================================

def test_gates_park_small_sample_not_discarded(_datadir):
    """Todo cenário KA tem n=1 (< 30). O gate GE-1 deve marcar PARKED e o sid
    deve **continuar presente** no relatório (estacionar, nunca descartar).
    Confirma também que a tabela `--gates` renderiza o veredito PARKED.
    """
    rep = _report_for("K1", _datadir)
    r = rep["sids"]["A3"]
    assert r.n < MIN_TRADES
    assert r.ge1 == "PARKED"
    assert r.verdict == "PARKED"        # PARKED domina, mesmo com GE-2 favorável
    # GE-2 é informacional aqui (n<30): K1 tem expectância > 0.
    assert r.ge2 == "PASS"
    # A assinatura NÃO some da tabela — o gate estaciona, não descarta.
    md = render_markdown(rep, gates=True)
    assert "| A3 |" in md
    assert "PARKED" in md
    assert "GE-1" in md and "GE-2" in md and "veredito" in md


def test_k2_loss_still_parked_not_failed(_datadir):
    """K2 tem expectância < 0, mas n<30 ⇒ o veredito é PARKED (amostra
    insuficiente domina), NÃO FAIL-treino. Garante que perdas com amostra pequena
    não são erroneamente reprovadas.
    """
    rep = _report_for("K2", _datadir)
    r = rep["sids"]["A3"]
    assert r.expectancy_R < 0
    assert r.ge1 == "PARKED" and r.ge2 == "FAIL"
    assert r.verdict == "PARKED"        # não FAIL-treino (n<30 domina)


# ==========================================================================
# Fronteira dos gates GE-1/GE-2 (DataFrame sintético — o KA tem sempre n=1)
# ==========================================================================

def _synthetic_trades(sid: str, profits_R: list[float]) -> pd.DataFrame:
    """DataFrame de trades com `profit_R` controlado por construção.

    Fixa entry=1000 e stop_loss_abs=990 → R_unit=10, amount=0.1 →
    amount*R_unit=1.0, logo profit_abs == profit_R (em quote). Permite exercitar
    a fronteira de GE-1 (n) e GE-2 (sinal da expectância) sem depender do harness.
    """
    entry, sl, amount = 1000.0, 990.0, 0.1     # amount*|entry-sl| = 0.1*10 = 1.0
    rows = []
    for pr in profits_R:
        rows.append({
            "enter_tag": f"{sid}_long",
            "open_rate": entry,
            "stop_loss_abs": sl,
            "amount": amount,
            "profit_abs": pr,               # == profit_R (amount*R_unit == 1.0)
            "is_short": False,
        })
    return pd.DataFrame(rows)


def test_ge1_boundary_park_below_30():
    """GE-1: n=29 ⇒ PARKED ; n=30 ⇒ avaliável (não PARKED)."""
    # n=29, expectância positiva: ainda PARKED por amostra.
    df29 = _synthetic_trades("A3", [0.5] * 29)
    r29 = compute_report(df29)["sids"]["A3"]
    assert r29.n == 29 and r29.ge1 == "PARKED" and r29.verdict == "PARKED"
    # n=30, expectância positiva: GE-1 pass ∧ GE-2 pass ⇒ PASS-treino.
    df30 = _synthetic_trades("A3", [0.5] * 30)
    r30 = compute_report(df30)["sids"]["A3"]
    assert r30.n == 30 and r30.ge1 == "PASS" and r30.ge2 == "PASS"
    assert r30.verdict == "PASS-treino"
    assert r30.expectancy_R == pytest.approx(0.5, abs=1e-9)
    assert r30.soma_R == pytest.approx(15.0, abs=1e-9)


def test_ge2_boundary_sign_of_expectancy():
    """GE-2: expectância > 0 ⇒ PASS-treino ; ≤ 0 ⇒ FAIL-treino (com n≥30)."""
    # Expectância exatamente 0 (soma nula) ⇒ FAIL (> 0 é estrito).
    zero = [1.0, -1.0] * 15                    # n=30, soma=0
    rz = compute_report(_synthetic_trades("A2", zero))["sids"]["A2"]
    assert rz.n == 30 and rz.expectancy_R == pytest.approx(0.0, abs=1e-12)
    assert rz.ge2 == "FAIL" and rz.verdict == "FAIL-treino"
    # Expectância negativa ⇒ FAIL-treino.
    neg = [-0.1] * 30
    rn = compute_report(_synthetic_trades("A2", neg))["sids"]["A2"]
    assert rn.ge2 == "FAIL" and rn.verdict == "FAIL-treino"
    # wins/wr coerentes.
    assert rn.wins == 0 and rn.wr == pytest.approx(0.0, abs=1e-9)


def test_skips_are_counted_not_silenced():
    """Trades sem sid (enter_tag vazio) ou com R nulo (entry==stop) são contados
    à parte, nunca somados aos agregados.
    """
    df = pd.DataFrame([
        {"enter_tag": "A3_long", "open_rate": 1000.0, "stop_loss_abs": 990.0,
         "amount": 0.1, "profit_abs": 0.5, "is_short": False},
        {"enter_tag": "", "open_rate": 1000.0, "stop_loss_abs": 990.0,
         "amount": 0.1, "profit_abs": 0.5, "is_short": False},        # sem sid
        {"enter_tag": "A3_long", "open_rate": 1000.0, "stop_loss_abs": 1000.0,
         "amount": 0.1, "profit_abs": 0.5, "is_short": False},        # R_unit=0
    ])
    rep = compute_report(df)
    assert rep["n_trades"] == 3
    assert rep["skipped_no_sid"] == 1
    assert rep["skipped_no_R"] == 1
    assert rep["sids"]["A3"].n == 1        # só o trade válido entra


# ==========================================================================
# Recorte de janela — `--window-start` (Wave 10.4): descarta pré-janela
# ANTES da agregação; sem a flag, tudo entra (regressão do atual).
# ==========================================================================

def _synthetic_trades_dated(sid: str, dated_profits: list) -> pd.DataFrame:
    """DataFrame sintético COM `open_date` por trade (para `--window-start`).

    `dated_profits`: lista de `(open_date_str, profit_R)`. Espelha o padrão de
    `_synthetic_trades` (entry=1000, stop=990 → amount*R_unit=1.0, logo
    profit_abs == profit_R), acrescentando `open_date` tz-aware (UTC), como no
    export real do freqtrade (`BT_DATA_COLUMNS`).
    """
    entry, sl, amount = 1000.0, 990.0, 0.1     # amount*|entry-sl| = 1.0
    rows = []
    for od, pr in dated_profits:
        rows.append({
            "enter_tag": f"{sid}_long",
            "open_rate": entry,
            "stop_loss_abs": sl,
            "amount": amount,
            "profit_abs": pr,                   # == profit_R
            "is_short": False,
            "open_date": pd.Timestamp(od, tz="UTC"),
        })
    return pd.DataFrame(rows)


def test_window_start_excludes_pre_window_from_aggregates():
    """Trades pré-janela NÃO entram em `n`/expectância; a contagem de descartados
    é exata e o intervalo (min/max de open_date) dos descartados é reportado.
    """
    df = _synthetic_trades_dated("A3", [
        ("2022-01-01", 0.5),    # pré-janela → descartado
        ("2022-06-30", -0.2),   # pré-janela → descartado
        ("2023-01-01", 1.0),    # na janela (== corte, inclusivo)
        ("2023-05-01", 0.8),    # na janela
    ])
    kept, info = filter_window(df, "2023-01-01")

    # (ii) contagem de descartados exata + intervalo dos descartados.
    assert info["total"] == 4
    assert info["discarded"] == 2
    assert str(info["discarded_min"])[:10] == "2022-01-01"
    assert str(info["discarded_max"])[:10] == "2022-06-30"

    # (i) os pré-janela não entram em n/expectância (só os 2 da janela).
    rep = compute_report(kept)
    r = rep["sids"]["A3"]
    assert r.n == 2
    assert rep["n_trades"] == 2
    assert r.soma_R == pytest.approx(1.8, abs=1e-9)          # 1.0 + 0.8
    assert r.expectancy_R == pytest.approx(0.9, abs=1e-9)


def test_window_start_boundary_is_inclusive():
    """O corte é `open_date < window_start`: um trade exatamente em window_start
    permanece na janela; um tick antes é descartado.
    """
    df = _synthetic_trades_dated("A3", [
        ("2023-01-01", 0.5),    # == corte → entra
        ("2022-12-31", 0.5),    # antes → descartado
    ])
    kept, info = filter_window(df, "2023-01-01")
    assert info["discarded"] == 1
    assert str(info["discarded_min"])[:10] == "2022-12-31"
    assert compute_report(kept)["sids"]["A3"].n == 1


def test_no_window_flag_keeps_all_trades():
    """Sem `--window-start`, tudo entra (regressão do comportamento atual):
    `compute_report` direto sobre o df completo conta todos os trades.
    """
    df = _synthetic_trades_dated("A3", [
        ("2022-01-01", 0.5),    # seria pré-janela, mas sem flag entra
        ("2023-01-01", 1.0),
    ])
    rep = compute_report(df)
    assert rep["n_trades"] == 2
    assert rep["sids"]["A3"].n == 2
    assert rep["sids"]["A3"].soma_R == pytest.approx(1.5, abs=1e-9)


def test_window_header_omits_pnl_of_discarded():
    """O cabeçalho de transparência reporta total/descartados/intervalo, mas NÃO
    imprime P&L dos descartados (§2.2 do briefing).
    """
    from tools.p3_report import render_window_header
    df = _synthetic_trades_dated("A3", [
        ("2022-01-01", 0.5),
        ("2023-01-01", 1.0),
    ])
    _kept, info = filter_window(df, "2023-01-01")
    header = render_window_header(info)
    assert "trades no export: 2" in header
    assert "descartados (pré-janela): 1" in header
    assert "2022-01-01" in header               # intervalo dos descartados
    # Nenhum P&L dos descartados vaza no cabeçalho.
    assert "0.5" not in header and "profit" not in header.lower()
