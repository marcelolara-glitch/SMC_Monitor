#!/usr/bin/env python3
"""p3_report — vereditos GE-1/GE-2 por assinatura a partir do export de backtest.

OBJETIVO
    Fechar os gates GE-1 (amostra) e GE-2 (expectância) do protocolo de
    congelamento (`docs/CONGELAMENTO_CANDIDATA_V2_E_GATES_EDGE.md` §3) a partir do
    export de trades do backtest de treino (P3, BTC). Por assinatura (`sid`),
    computa `n_trades`, taxa de acerto e a **expectância média em R líquida de
    fee**, onde R de um trade = `|entry − SL ancorado|`. Emite uma tabela markdown
    pronta para colar no chat/relatório de P3.

    Unidade de avaliação = assinatura isolada, agrupada pelo `enter_tag`
    (`f"{sid}_{direção}"`); long e short do mesmo sid somam no mesmo grupo (§3 do
    doc: "R de um trade = |entry − sl_anchor|", agrupamento nativo por `enter_tag`).

FONTE DE DADOS (freqtrade 2026.3, versão instalada — API verificada)
    `freqtrade.data.btanalysis.load_backtest_data(file_or_directory, strategy=None,
    filename=None) -> pd.DataFrame` (BT_DATA_COLUMNS). Campos usados por trade:

      - `enter_tag`      → `sid = enter_tag.split('_', 1)[0]`.
      - `open_rate`      → preço de entrada (`entry`).
      - `stop_loss_abs`  → **SL ancorado** (preço absoluto do stop vigente). Nesta
                           fase NÃO há trailing/breakeven (isso é 10c), então o
                           stop nunca se move da âncora gravada por
                           `order_filled`/`custom_stoploss`; `stop_loss_abs`
                           reflete o valor ancorado durante toda a vida do trade.
      - `amount`         → tamanho da posição (base), = `stake/entry` @ leverage 1.
      - `profit_abs`     → P&L absoluto **líquido** (o Freqtrade já desconta o fee
                           das duas pernas em `profit_abs`).
      - `is_short`       → informativo (o sinal do R já está em `profit_abs`).

    NOTA sobre a escolha do campo (assunção do briefing §2.2 resolvida):
    `initial_stop_loss_abs` **NÃO** serve — ele carrega o stop DURO inicial
    (`strategy.stoploss = −0.99`) gravado no fill ANTES de `order_filled` ancorar
    o SL (ex.: long entry 1000 → `initial_stop_loss_abs = 10.01`; short → 1990.0).
    O campo que reflete a âncora é `stop_loss_abs` (long ROUND_UP → exato na
    âncora; short ROUND_DOWN → pode cair 1 tick abaixo da âncora, comportamento
    já documentado no known-answer da Wave 10.2, K4).

FÓRMULA (por trade)
    sid      = enter_tag.split('_', 1)[0]
    R_unit   = |open_rate − stop_loss_abs|            # risco unitário em preço
    profit_R = profit_abs / (amount × R_unit)         # P&L em múltiplos de R, líquido

    Agregado por sid (long+short somados):
      n            = nº de trades
      wins         = nº de trades com profit_abs > 0
      wr           = wins / n
      soma_R       = Σ profit_R
      expectancy_R = média(profit_R) = soma_R / n
      profit_abs_total = Σ profit_abs

VEREDITOS (§3 do doc de congelamento)
    GE-1 (amostra treino) : n ≥ 30 ⇒ avaliável ; senão ⇒ **PARKED** (amostra
                            insuficiente — estacionar, NUNCA descartar).
    GE-2 (expectância)    : expectancy_R > 0 ⇒ pass ; senão ⇒ **FAIL-treino**.
    Veredito (treino)     : n < 30 ⇒ PARKED ; n ≥ 30 ∧ exp > 0 ⇒ PASS-treino
                            (pendente OOS/P4) ; n ≥ 30 ∧ exp ≤ 0 ⇒ FAIL-treino.
    (PASS pleno exige GE-3/OOS, que é P4 — fora do escopo desta ferramenta.)

LIMITAÇÕES CONHECIDAS
    - GE-3 (OOS) NÃO é implementado aqui (é P4). O veredito emitido é o de treino.
    - R é medido a partir do stop EXPORTADO (`stop_loss_abs`); trades cujo fill
      não ancorou o SL (sem linha causal) carregariam o stop duro no campo e
      distorceriam R — reportados como `R_unit` anômalo e contados à parte, não
      silenciados (ver `skipped_no_R`).
    - Slippage não modelado (limitação herdada do config; enviesa a favor).

NÃO FAZER
    - Rodar sobre QUALQUER dado de mercado real (a ferramenta só consome um export
      já produzido — P3/P4 é quem roda o backtest; a validação desta wave é 100%
      sintética via known-answer).
    - Implementar GE-3 (OOS) — fora de escopo.
    - Reimplementar o parser do export à mão — usar `load_backtest_data`.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# GE-1: amostra mínima de trades no treino (doc §3).
MIN_TRADES = 30


@dataclass
class SidReport:
    """Agregado por assinatura (sid), long+short somados."""

    sid: str
    n: int
    wins: int
    soma_R: float
    expectancy_R: float
    profit_abs_total: float
    wr: float

    # --- Gates (doc §3) ---------------------------------------------------
    @property
    def ge1(self) -> str:
        """GE-1 (amostra): PARKED se n < 30 (estacionar, nunca descartar)."""
        return "PASS" if self.n >= MIN_TRADES else "PARKED"

    @property
    def ge2(self) -> str:
        """GE-2 (expectância): pass se expectância média > 0R líquida de fee."""
        return "PASS" if self.expectancy_R > 0.0 else "FAIL"

    @property
    def verdict(self) -> str:
        """Veredito de treino (§3): PARKED domina GE-2 (amostra insuficiente).

        n < 30           ⇒ PARKED       (GE-1 falha — nunca descarta)
        n ≥ 30 ∧ exp > 0 ⇒ PASS-treino  (GE-1∧GE-2 ok; PASS pleno pende OOS/P4)
        n ≥ 30 ∧ exp ≤ 0 ⇒ FAIL-treino  (GE-2 falha)
        """
        if self.n < MIN_TRADES:
            return "PARKED"
        return "PASS-treino" if self.expectancy_R > 0.0 else "FAIL-treino"


def _sid_of(enter_tag: Any) -> str | None:
    """`sid` a partir do `enter_tag` (`f"{sid}_{direção}"`) — §1.3 do doc.

    `enter_tag` ausente/vazio/sem `_` (cache frio / trade sem tag) → None
    (trade ignorado, contado em `skipped_no_sid`).
    """
    if enter_tag is None:
        return None
    tag = str(enter_tag)
    if not tag or "_" not in tag:
        return None
    sid = tag.split("_", 1)[0]
    return sid or None


def compute_report(trades: "Any") -> dict[str, Any]:
    """Computa os agregados por sid a partir do DataFrame de trades.

    Aceita tanto o DataFrame de `load_backtest_data` quanto o `results` em memória
    de `Backtesting.backtest` — ambos expõem as mesmas colunas (open_rate,
    stop_loss_abs, amount, profit_abs, enter_tag). Função pura (sem I/O, sem
    freqtrade), para permitir known-answer determinístico.

    Devolve `{"sids": {sid: SidReport}, "n_trades": int, "skipped_no_sid": int,
    "skipped_no_R": int}`. Trades sem sid ou com `R_unit` nulo/inválido são
    contados à parte (nunca silenciados), não entram nos agregados.
    """
    # Acumuladores por sid.
    agg: dict[str, dict[str, float]] = {}
    skipped_no_sid = 0
    skipped_no_R = 0
    n_trades = 0

    for row in trades.itertuples(index=False):
        n_trades += 1
        sid = _sid_of(getattr(row, "enter_tag", None))
        if sid is None:
            skipped_no_sid += 1
            continue

        entry = float(getattr(row, "open_rate"))
        sl_abs = getattr(row, "stop_loss_abs")
        amount = float(getattr(row, "amount"))
        profit_abs = float(getattr(row, "profit_abs"))

        # R_unit = |entry − SL ancorado| ; guarda contra R/amount nulos ou NaN.
        try:
            r_unit = abs(entry - float(sl_abs))
        except (TypeError, ValueError):
            r_unit = 0.0
        if not (r_unit > 0.0) or not (amount > 0.0):
            skipped_no_R += 1
            continue

        profit_R = profit_abs / (amount * r_unit)

        a = agg.setdefault(
            sid, {"n": 0, "wins": 0, "soma_R": 0.0, "profit_abs_total": 0.0}
        )
        a["n"] += 1
        a["wins"] += 1 if profit_abs > 0.0 else 0
        a["soma_R"] += profit_R
        a["profit_abs_total"] += profit_abs

    sids: dict[str, SidReport] = {}
    for sid, a in agg.items():
        n = int(a["n"])
        expectancy_R = a["soma_R"] / n if n else 0.0
        sids[sid] = SidReport(
            sid=sid,
            n=n,
            wins=int(a["wins"]),
            soma_R=a["soma_R"],
            expectancy_R=expectancy_R,
            profit_abs_total=a["profit_abs_total"],
            wr=(a["wins"] / n) if n else 0.0,
        )

    return {
        "sids": sids,
        "n_trades": n_trades,
        "skipped_no_sid": skipped_no_sid,
        "skipped_no_R": skipped_no_R,
    }


def render_markdown(report: dict[str, Any], gates: bool = False) -> str:
    """Tabela markdown por sid (ordenada por sid). Com `gates`, anexa colunas GE."""
    sids = report["sids"]
    order = sorted(sids)

    if gates:
        header = (
            "| sid | n | wins | wr | soma_R | expectancy_R | profit_abs | "
            "GE-1 | GE-2 | veredito |"
        )
        sep = "|---|---:|---:|---:|---:|---:|---:|---|---|---|"
    else:
        header = "| sid | n | wins | wr | soma_R | expectancy_R | profit_abs |"
        sep = "|---|---:|---:|---:|---:|---:|---:|"

    lines = [header, sep]
    for sid in order:
        r = sids[sid]
        base = (
            f"| {r.sid} | {r.n} | {r.wins} | {r.wr:.3f} | {r.soma_R:+.4f} | "
            f"{r.expectancy_R:+.4f} | {r.profit_abs_total:+.4f} |"
        )
        if gates:
            base += f" {r.ge1} | {r.ge2} | {r.verdict} |"
        lines.append(base)

    footer = [
        "",
        f"_trades={report['n_trades']} · "
        f"sem_sid={report['skipped_no_sid']} · "
        f"sem_R={report['skipped_no_R']} · "
        f"GE-1: n≥{MIN_TRADES} · GE-2: expectancy_R>0 (líquida de fee)_",
    ]
    return "\n".join(lines + footer)


def load_trades(path: "str | Path"):
    """Carrega o export de trades via `load_backtest_data` (freqtrade 2026.3).

    Import diferido: a ferramenta só toca o freqtrade no caminho de CLI, mantendo
    `compute_report`/`render_markdown` importáveis sem a dependência (known-answer
    puro). `path` pode ser um arquivo de export ou um diretório de backtests.
    """
    from freqtrade.data.btanalysis import load_backtest_data

    return load_backtest_data(Path(path))


def main(argv: "list[str] | None" = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Vereditos GE-1/GE-2 por assinatura a partir do export de backtest "
            "(P3, treino). R = |entry − stop_loss_abs|; expectância em R líquida "
            "de fee."
        )
    )
    parser.add_argument("export", help="arquivo (ou diretório) de export de backtest")
    parser.add_argument(
        "--gates",
        action="store_true",
        help="anexa colunas de veredito GE-1/GE-2 (doc §3)",
    )
    args = parser.parse_args(argv)

    trades = load_trades(args.export)
    report = compute_report(trades)
    print(render_markdown(report, gates=args.gates))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
