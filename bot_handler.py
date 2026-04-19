#!/usr/bin/env python3
"""
bot_handler.py — Bot Telegram bidirecional (SMC Monitor)
==========================================================

OBJETIVO:
    Receber comandos do operador via Telegram e responder com
    informações do estado atual do SMC Monitor. Roda em thread
    separada dentro do processo do daemon, fazendo long-polling
    contínuo no endpoint getUpdates da API Telegram.

FONTE DE DADOS:
    - smc_engine (estado em memória, read-only)
    - tracker (get_active_signals, get_signal, get_performance_summary)
    - state.py (SQLite smc_state.db, read-only exceto tabela bot_state)
    - /proc/meminfo, /proc/loadavg, shutil.disk_usage (VM)

LIMITAÇÕES CONHECIDAS:
    - Não envia mensagens proativas — apenas responde a comandos
    - Cooldown de 1s por (chat_id, command) em memória (reset a cada restart)
    - Thread morre junto com o daemon principal (daemon=True)

NÃO FAZER:
    - Não escrever em tabelas do engine ou tracker — read-only
    - Não bloquear o loop — todo I/O com timeout curto
    - Não usar python-telegram-bot — long-polling manual via requests
    - Não expor chat_id ou token em respostas de erro
"""

import logging
import os
import re
import shutil
import sqlite3
import threading
import time
from datetime import datetime, timezone, timedelta

import requests

import config
import state  # noqa: F401 — garante init de tabelas antes de queries
import signals  # noqa: F401 — importado conforme spec
import smc_engine
import tracker
import lib_version_check

# ─── Constantes ───────────────────────────────────────────────────────────────

VERSION = "0.1.5"
BRT = timezone(timedelta(hours=-3))

TELEGRAM_API_BASE = "https://api.telegram.org"
POLL_TIMEOUT_SECS = 60
REQUEST_TIMEOUT_SECS = 70
ERROR_BACKOFF_SECS = 5
COMMAND_COOLDOWN_SECS = 1.0
MAX_MESSAGE_CHARS = 4000
SEP = "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

_START_TS: float | None = None
_COOLDOWN: dict[tuple[int, str], float] = {}
_COOLDOWN_LOCK = threading.Lock()
_engine: smc_engine.SMCEngine | None = None

log = logging.getLogger(__name__)


# ─── Engine injection ─────────────────────────────────────────────────────────

def set_engine(engine: smc_engine.SMCEngine) -> None:
    """
    OBJETIVO: Injetar referência ao SMCEngine antes de iniciar a thread.
    FONTE DE DADOS: instância criada pelo main.py.
    LIMITAÇÕES CONHECIDAS: sem lock — deve ser chamado antes de start_bot_thread.
    NÃO FAZER: não chamar após a thread ter iniciado.
    """
    global _engine
    _engine = engine


# ─── Helpers privados ─────────────────────────────────────────────────────────

def _now_brt() -> datetime:
    return datetime.now(BRT)


def _ts() -> str:
    return _now_brt().strftime("%Y-%m-%d %H:%M BRT")


def _fmt_dt(ts_ms: int, fmt: str = "%d/%m %H:%M") -> str:
    try:
        dt = datetime.fromtimestamp(ts_ms / 1000.0, tz=BRT)
        return dt.strftime(fmt)
    except Exception:
        return "—"


def _fmt_duration(secs: float) -> str:
    secs = int(abs(secs))
    if secs < 60:
        return f"{secs}s"
    m, _ = divmod(secs, 60)
    if m < 60:
        return f"{m}min"
    h, m = divmod(m, 60)
    if m == 0:
        return f"{h}h"
    return f"{h}h {m}min"


def _truncate(text: str) -> str:
    limit = MAX_MESSAGE_CHARS - 30
    if len(text) <= limit:
        return text
    return text[:limit] + "\n... (truncado)"


def _tg_send(chat_id: int, text: str) -> bool:
    token = config.TELEGRAM_TOKEN
    if not token:
        return False
    text = _truncate(text)
    try:
        resp = requests.post(
            f"{TELEGRAM_API_BASE}/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
        return resp.status_code == 200
    except Exception as e:
        log.warning("_tg_send falhou: %s", e)
        return False


def _tg_register_commands() -> None:
    token = config.TELEGRAM_TOKEN
    if not token:
        return
    commands = [
        {"command": "status",      "description": "Saúde do daemon, WS, banco, VM"},
        {"command": "ping",        "description": "Heartbeat sob demanda"},
        {"command": "ajuda",       "description": "Lista de comandos"},
        {"command": "snapshot",    "description": "Estado atual do BTC + checklist SMC"},
        {"command": "sinais",      "description": "Sinais ativos no tracker"},
        {"command": "trades",      "description": "Histórico de sinais resolvidos (7d)"},
        {"command": "performance", "description": "Métricas agregadas do tracker (30d)"},
    ]
    try:
        resp = requests.post(
            f"{TELEGRAM_API_BASE}/bot{token}/setMyCommands",
            json={"commands": commands},
            timeout=10,
        )
        if resp.status_code == 200:
            log.info("_tg_register_commands: OK")
        else:
            log.warning("_tg_register_commands: HTTP %d", resp.status_code)
    except Exception as e:
        log.warning("_tg_register_commands falhou: %s", e)


def _extract_command(text: str) -> str | None:
    m = re.match(r"^(/\w+)(?:@\w+)?", text.strip())
    return m.group(1).lower() if m else None


def _check_cooldown(chat_id: int, command: str) -> bool:
    now = time.time()
    with _COOLDOWN_LOCK:
        key = (chat_id, command)
        last = _COOLDOWN.get(key, 0.0)
        if now - last < COMMAND_COOLDOWN_SECS:
            return False
        _COOLDOWN[key] = now
        return True


def _load_last_update_id() -> int:
    try:
        with sqlite3.connect(config.DB_PATH) as conn:
            row = conn.execute(
                "SELECT value FROM bot_state WHERE key='last_update_id'"
            ).fetchone()
            return int(row[0]) if row else 0
    except Exception as e:
        log.warning("_load_last_update_id falhou: %s", e)
        return 0


def _save_last_update_id(uid: int) -> None:
    try:
        now_iso = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(config.DB_PATH) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO bot_state (key, value, updated_at) VALUES (?, ?, ?)",
                ("last_update_id", str(uid), now_iso),
            )
            conn.commit()
    except Exception as e:
        log.warning("_save_last_update_id falhou: %s", e)


# ─── Handlers ─────────────────────────────────────────────────────────────────

def cmd_ajuda() -> str:
    """
    OBJETIVO: Retornar lista estática de comandos agrupados por categoria.
    FONTE DE DADOS: constante VERSION deste módulo.
    LIMITAÇÕES CONHECIDAS: lista é estática — atualizar manualmente a cada novo comando.
    NÃO FAZER: não fazer chamadas externas nem consultar banco.
    """
    return (
        f"🤖 <b>SMC Monitor v{VERSION} — Comandos</b>\n"
        f"{SEP}\n"
        "⚙️ <b>Sistema</b>\n"
        "/status          — saúde do daemon, WS, banco, VM\n"
        "/ping            — heartbeat sob demanda\n"
        "/help, /ajuda    — esta mensagem\n"
        f"{SEP}\n"
        "📊 <b>Mercado</b>\n"
        "/snapshot        — estado atual do BTC + checklist SMC\n"
        "/btc             — alias de /snapshot\n"
        f"{SEP}\n"
        "📈 <b>Sinais &amp; Tracker</b>\n"
        "/sinais          — sinais ativos no tracker\n"
        "/trades          — histórico de sinais resolvidos (7d)\n"
        "/performance     — métricas agregadas do tracker (30d)\n"
        "/perf            — alias de /performance"
    )


def cmd_ping() -> str:
    """
    OBJETIVO: Confirmar que o bot está vivo, com timestamp BRT e uptime.
    FONTE DE DADOS: _START_TS (setado no início de _poll_loop), time.time().
    LIMITAÇÕES CONHECIDAS: uptime conta desde o início da thread, não do daemon.
    NÃO FAZER: não consultar banco nem engine.
    """
    uptime_secs = (time.time() - _START_TS) if _START_TS else 0.0
    return (
        f"🏓 pong — {_ts()}\n"
        f"⏱️ Uptime: {_fmt_duration(uptime_secs)}"
    )


def cmd_status() -> str:
    """
    OBJETIVO: Snapshot operacional completo — engine/WS, persistência e VM.
    FONTE DE DADOS: _engine._buffers (último candle), SQLite signal_lifecycle,
                    /proc/meminfo, /proc/loadavg, shutil.disk_usage.
    LIMITAÇÕES CONHECIDAS: falhas em qualquer seção exibem '—' e seguem em frente.
    NÃO FAZER: não escrever em nenhuma tabela; não bloquear mais de 2s.
    """
    lines = [f"🤖 <b>SMC Monitor v{VERSION} — Status</b>", SEP]

    # Seção 1: WebSocket / Engine
    lines.append("📡 <b>WebSocket / Engine</b>")
    try:
        token = config.TOKENS[0] if config.TOKENS else "BTC-USDT-SWAP"
        eng = _engine
        if eng is not None:
            buf_15m = eng._buffers.get(token, {}).get("15m")
            if buf_15m:
                last_c = list(buf_15m)[-1]
                last_ts_ms = last_c.get("ts", 0)
                age_secs = (time.time() * 1000 - last_ts_ms) / 1000
                ws_icon = "✅" if age_secs < 1800 else ("⚠️" if age_secs < 3600 else "🔴")
                lines.append(f"  Último candle:   {_fmt_dt(last_ts_ms)} (15m) {ws_icon}")
            else:
                lines.append("  Último candle:   — (buffer vazio)")
            trend_4h = eng.get_state(token, "4H").get("trend", "neutral")
            trend_label = {"bullish": "LONG ↑", "bearish": "SHORT ↓"}.get(trend_4h, "NEUTRO")
            lines.append(f"  Trend 4H:        {trend_label}")
        else:
            lines.append("  Engine:          — (não inicializado)")
        lib_ver = lib_version_check.get_lib_version() or "?"
        lines.append(f"  SMC lib:         v{lib_ver}")
    except Exception as e:
        log.warning("cmd_status engine falhou: %s", e)
        lines.append("  (erro ao ler engine)")

    lines.append(SEP)

    # Seção 2: Persistência
    lines.append("💾 <b>Persistência</b>")
    try:
        db_path = config.DB_PATH
        if os.path.exists(db_path):
            sz = os.path.getsize(db_path)
            sz_str = f"{sz / 1_048_576:.1f} MB" if sz >= 1_048_576 else f"{sz / 1024:.1f} KB"
            lines.append(f"  DB size:         {sz_str}")
        else:
            lines.append("  DB size:         —")
        with sqlite3.connect(db_path) as conn:
            r = conn.execute(
                "SELECT COUNT(*), SUM(status='active'), SUM(status!='active') FROM signal_lifecycle"
            ).fetchone()
            total, active, resolved = (r[0] or 0), (r[1] or 0), (r[2] or 0)
            lines.append(f"  Sinais:          {total} total ({active} ativos, {resolved} resolvidos)")
            r2 = conn.execute(
                "SELECT resolved_at_ts FROM signal_lifecycle "
                "WHERE status!='active' ORDER BY resolved_at_ts DESC LIMIT 1"
            ).fetchone()
            lines.append(f"  Último fechado:  {_fmt_dt(r2[0]) if r2 and r2[0] else '—'}")
    except Exception as e:
        log.warning("cmd_status persistência falhou: %s", e)
        lines.append("  (erro ao ler banco)")

    lines.append(SEP)

    # Seção 3: VM
    lines.append("🖥️ <b>VM</b>")
    try:
        usage = shutil.disk_usage(os.path.expanduser("~"))
        free_gb = usage.free / 1_073_741_824
        disk_icon = "✅" if free_gb > 5 else ("⚠️" if free_gb > 1 else "🔴")
        lines.append(f"  Disco livre (~): {free_gb:.1f} GB {disk_icon}")
    except Exception as e:
        log.warning("cmd_status disk falhou: %s", e)
        lines.append("  Disco livre (~): —")
    try:
        mem_mb = None
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    mem_mb = int(line.split()[1]) // 1024
                    break
        if mem_mb is not None:
            mem_icon = "✅" if mem_mb > 500 else ("⚠️" if mem_mb > 200 else "🔴")
            lines.append(f"  Memória disp.:   {mem_mb} MB {mem_icon}")
        else:
            lines.append("  Memória disp.:   —")
    except Exception as e:
        log.warning("cmd_status mem falhou: %s", e)
        lines.append("  Memória disp.:   —")
    try:
        with open("/proc/loadavg") as f:
            load1 = f.read().split()[0]
        load_icon = "✅" if float(load1) < 1.0 else ("⚠️" if float(load1) < 2.0 else "🔴")
        lines.append(f"  Load avg (1min): {load1} {load_icon}")
    except Exception as e:
        log.warning("cmd_status loadavg falhou: %s", e)
        lines.append("  Load avg (1min): —")

    return "\n".join(lines)


def cmd_snapshot(arg: str | None = None) -> str:
    """
    OBJETIVO: Estado atual do BTC com checklist dos 6 critérios SMC.
    FONTE DE DADOS: _engine.get_state() e _engine._buffers (read-only).
    LIMITAÇÕES CONHECIDAS: requer todos os 3 timeframes ready=True; se não,
                           retorna mensagem de espera. Argumento ignorado.
    NÃO FAZER: não escrever no engine; não chamar signals.evaluate() (lê direto).
    """
    eng = _engine
    if eng is None:
        return "⏳ Aguardando dados iniciais do WebSocket..."

    token = config.TOKENS[0] if config.TOKENS else "BTC-USDT-SWAP"

    try:
        st4h  = eng.get_state(token, "4H")
        st1h  = eng.get_state(token, "1H")
        st15m = eng.get_state(token, "15m")

        if not (st4h.get("ready") and st1h.get("ready") and st15m.get("ready")):
            return "⏳ Aguardando dados iniciais do WebSocket..."

        # Preço atual e timestamp do último candle 15m
        try:
            buf = list(eng._buffers.get(token, {}).get("15m", []))
            last_c = buf[-1] if buf else {}
            current_price = float(last_c.get("close", 0.0))
            last_ts_ms    = last_c.get("ts", 0)
        except (IndexError, KeyError, TypeError):
            current_price = 0.0
            last_ts_ms    = 0

        # Direção a partir do trend 4H
        trend_4h = st4h.get("trend", "neutral")
        if trend_4h == "bullish":
            direction, ob_type = "LONG", "bull"
        elif trend_4h == "bearish":
            direction, ob_type = "SHORT", "bear"
        else:
            direction, ob_type = None, None

        trend_label = {"bullish": "LONG", "bearish": "SHORT"}.get(trend_4h, "NEUTRO")

        # Critério 1: trend 4H alinhado
        c1 = trend_4h != "neutral"

        # Critério 2: OB ativo 1H
        ref_ob = None
        if ob_type:
            obs = [o for o in st1h.get("active_obs", [])
                   if o.get("type") == ob_type and not o.get("mitigated", False)]
            ref_ob = obs[-1] if obs else None
        c2 = ref_ob is not None
        ob_val = f"{ref_ob['bottom']:,.0f}–{ref_ob['top']:,.0f}" if ref_ob else "—"

        # Critério 3: FVG adjacente
        matched_fvg = None
        if ob_type and ref_ob:
            fvgs = [f for f in st1h.get("active_fvgs", [])
                    if f.get("type") == ob_type and f.get("status") != "mitigated"]
            for fvg in fvgs:
                if fvg.get("bottom", 0) <= ref_ob["top"] and fvg.get("top", 0) >= ref_ob["bottom"]:
                    matched_fvg = fvg
                    break
        c3 = matched_fvg is not None
        fvg_val = f"{matched_fvg['bottom']:,.0f}–{matched_fvg['top']:,.0f}" if matched_fvg else "—"

        # Critério 4: Sweep recente
        _TF_MS = {"1H": 3_600_000, "15m": 900_000}
        now_ms = int(time.time() * 1000)
        c4, sweep_val = False, "—"
        for tf in ("1H", "15m"):
            sw = eng.get_state(token, tf).get("last_sweep")
            if sw and (now_ms - sw.get("ts", 0)) <= 10 * _TF_MS[tf]:
                age_min = int((now_ms - sw.get("ts", now_ms)) / 60_000)
                c4, sweep_val = True, f"{sw.get('direction', '')} ({age_min}min atrás)"
                break

        # Critério 5: Premium/Discount ok
        pd_label = st1h.get("premium_discount", "equilibrium")
        c5 = (pd_label == "discount" if direction == "LONG" else
              pd_label == "premium"  if direction == "SHORT" else False)
        sh, sl_ = st1h.get("swing_high", 0.0), st1h.get("swing_low", 0.0)
        if sh > sl_ > 0 and current_price > 0:
            pd_pct = (current_price - sl_) / (sh - sl_) * 100
            pd_val = f"{pd_label} ({pd_pct:.0f}%)"
        else:
            pd_val = pd_label

        # Critério 6: BOS/ChoCH 15m alinhado
        last_bos = st15m.get("last_bos")
        c6 = bool(ob_type and last_bos and last_bos.get("direction") == ob_type)
        if c6:
            bos_dir_str = "UP" if last_bos.get("direction") == "bull" else "DOWN"
            bos_val = f"{last_bos.get('type', 'BOS')} {bos_dir_str}"
        else:
            bos_val = "—"

        score = sum([c1, c2, c3, c4, c5, c6])

        def ico(v: bool) -> str:
            return "✅" if v else "❌"

        price_str = f"{current_price:,.2f}" if current_price else "—"

        return "\n".join([
            f"📊 <b>{token} — Snapshot</b>",
            SEP,
            f"💰 Preço: ${price_str}",
            f"🕐 Último candle: {_fmt_dt(last_ts_ms) if last_ts_ms else '—'} (15m)",
            SEP,
            "📈 <b>Checklist SMC</b>",
            f"  {ico(c1)} Trend 4H alinhado:      {trend_label}",
            f"  {ico(c2)} OB ativo 1H:            {ob_val}",
            f"  {ico(c3)} FVG adjacente:          {fvg_val}",
            f"  {ico(c4)} Sweep recente:          {sweep_val}",
            f"  {ico(c5)} Premium/Discount ok:    {pd_val}",
            f"  {ico(c6)} BOS/ChoCH 15m:          {bos_val}",
            SEP,
            f"🎯 Score: {score}/6 (threshold: {config.SIGNAL_THRESHOLD})",
        ])
    except Exception as e:
        log.warning("cmd_snapshot falhou: %s", e)
        return "❌ Erro ao ler estado do engine"


def cmd_sinais(arg: str | None = None) -> str:
    """
    OBJETIVO: Listar sinais ativos no tracker com detalhes de preço e tempo.
    FONTE DE DADOS: tracker.get_active_signals() via SQLite.
    LIMITAÇÕES CONHECIDAS: leitura snapshot; pode haver race com observe_candle_15m.
    NÃO FAZER: não modificar estado do tracker.
    """
    try:
        active = tracker.get_active_signals()
        if not active:
            return f"📋 <b>Sinais Ativos</b>\n{SEP}\n  Nenhum sinal ativo no momento"

        now_ms = int(time.time() * 1000)
        lines = ["📋 <b>Sinais Ativos</b>", SEP]
        for sig in active:
            direction = sig.get("direction", "")
            d_icon    = "🚀" if direction == "LONG" else "📉"
            tok       = sig.get("token", "")
            sig_id    = sig.get("signal_id", "?")
            entry_mid = (sig.get("entry_low", 0.0) + sig.get("entry_high", 0.0)) / 2.0
            sl        = sig.get("sl_price", 0.0)
            tp1       = sig.get("tp1_price", 0.0)
            emitted   = sig.get("emitted_at_ts", 0)
            age_secs  = (now_ms - emitted) / 1000.0 if emitted else 0.0
            reconf    = sig.get("reconfirmations", 0)

            lines.append(f"{d_icon} <b>{tok} {direction}</b> #{sig_id}")
            lines.append(f"  Entrada:    ${entry_mid:,.2f}")
            lines.append(f"  SL:         ${sl:,.2f}")
            lines.append(f"  TP1:        ${tp1:,.2f}" if tp1 else "  TP1:        —")
            lines.append(f"  Aberto há:  {_fmt_duration(age_secs)}")
            lines.append(f"  Reconfirms: {reconf}")
            lines.append(SEP)

        return "\n".join(lines)
    except Exception as e:
        log.warning("cmd_sinais falhou: %s", e)
        return "❌ Erro ao ler sinais ativos"


def cmd_trades(arg: str | None = None) -> str:
    """
    OBJETIVO: Listar sinais resolvidos nos últimos N dias (default 7d, max 90d).
    FONTE DE DADOS: tabela signal_lifecycle via SQLite (read-only).
    LIMITAÇÕES CONHECIDAS: limite de 20 registros; arg '30d' → 30 dias.
    NÃO FAZER: não modificar signal_lifecycle.
    """
    days = 7
    if arg:
        m = re.match(r"^(\d+)", arg.strip())
        if m:
            days = max(1, min(90, int(m.group(1))))

    cutoff_ms = int((time.time() - days * 86400) * 1000)

    def _status_icon(s: str) -> str:
        return "✅" if s == "tp1_hit" else ("❌" if s == "sl_hit" else "🟡")

    def _r_str(row: dict) -> str:
        entry_mid = (row.get("entry_low", 0.0) + row.get("entry_high", 0.0)) / 2.0
        sl        = row.get("sl_price", 0.0) or 0.0
        resolved  = row.get("resolved_price", 0.0) or 0.0
        direction = row.get("direction", "LONG")
        if entry_mid == 0 or sl == 0 or abs(entry_mid - sl) < 1e-10:
            return "(—R)"
        risk = entry_mid - sl if direction == "LONG" else sl - entry_mid
        r_mult = ((resolved - entry_mid) / risk if direction == "LONG"
                  else (entry_mid - resolved) / risk)
        return f"({r_mult:+.1f}R)"

    try:
        with sqlite3.connect(config.DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            rows = [dict(r) for r in conn.execute(
                """
                SELECT signal_id, token, direction, entry_low, entry_high,
                       sl_price, tp1_price, status, resolved_price, resolved_at_ts
                FROM signal_lifecycle
                WHERE status != 'active' AND resolved_at_ts >= ?
                ORDER BY resolved_at_ts DESC LIMIT 20
                """,
                (cutoff_ms,),
            ).fetchall()]

        if not rows:
            return f"📋 <b>Trades — últimos {days}d</b>\n{SEP}\n  Nenhum trade resolvido neste período"

        wins   = sum(1 for r in rows if r["status"] == "tp1_hit")
        losses = sum(1 for r in rows if r["status"] == "sl_hit")
        other  = len(rows) - wins - losses

        lines = [f"📋 <b>Trades — últimos {days}d</b>", SEP]
        for row in rows:
            dt_str = _fmt_dt(row["resolved_at_ts"]) if row["resolved_at_ts"] else "—"
            d_icon = "🚀" if row["direction"] == "LONG" else "📉"
            s_icon = _status_icon(row["status"])
            lines.append(
                f"  {dt_str} {d_icon} {row['direction']}  {row['token']}"
                f" → {s_icon} {row['status']}  {_r_str(row)}"
            )
        lines.append(SEP)
        lines.append(f"  Total: {len(rows)}  |  ✅ {wins} ❌ {losses} 🟡 {other}")
        return "\n".join(lines)
    except Exception as e:
        log.warning("cmd_trades falhou: %s", e)
        return "❌ Erro ao ler histórico de trades"


def cmd_performance(arg: str | None = None) -> str:
    """
    OBJETIVO: Métricas agregadas do tracker nos últimos 30 dias.
    FONTE DE DADOS: tracker.get_performance_summary() via SQLite.
    LIMITAÇÕES CONHECIDAS: requer mínimo 10 sinais resolvidos; não há breakdown
                           por direção (LONG/SHORT) — get_performance_summary
                           retorna dados agregados.
    NÃO FAZER: não alterar tracker.get_performance_summary(); não escrever no banco.
    """
    try:
        since_ts = int((time.time() - 30 * 86400) * 1000)
        perf = tracker.get_performance_summary(since_ts=since_ts)

        if not perf or perf.get("resolved", 0) < 10:
            return (
                f"📊 <b>Performance</b>\n{SEP}\n"
                "⚠️ Histórico insuficiente para métricas\n"
                "(mínimo 10 sinais resolvidos)"
            )

        total    = perf.get("total_signals", 0)
        active   = perf.get("active", 0)
        resolved = perf.get("resolved", 0)
        wins     = perf.get("wins", 0)
        losses   = perf.get("losses", 0)
        timeouts = perf.get("timeouts", 0)
        wr_pct   = perf.get("win_rate", 0.0) * 100
        avg_r_w  = perf.get("avg_r_on_wins", 0.0)
        avg_r_l  = perf.get("avg_r_on_losses", -1.0)
        wr       = wr_pct / 100.0
        exp      = (wr * avg_r_w + (1.0 - wr) * avg_r_l) if (wins + losses) > 0 else 0.0

        return "\n".join([
            "📊 <b>Performance — últimos 30d</b>",
            SEP,
            f"  Total sinais:    {total}",
            f"  Em aberto:       {active}",
            f"  Resolvidos:      {resolved}",
            SEP,
            f"  ✅ Win Rate:     {wr_pct:.0f}%  ({wins}/{wins + losses})",
            f"  ❌ Losses:       {losses}",
            f"  🟡 Timeouts:     {timeouts}",
            f"  Avg R (wins):    {avg_r_w:+.2f}",
            f"  Avg R (losses):  {avg_r_l:+.2f}",
            SEP,
            f"  Expectancy:      {exp:+.2f}R por trade",
        ])
    except Exception as e:
        log.warning("cmd_performance falhou: %s", e)
        return "❌ Erro ao ler métricas de performance"


# ─── Dispatcher ───────────────────────────────────────────────────────────────

HANDLERS_NO_ARG: dict = {
    "/ajuda":    cmd_ajuda,
    "/help":     cmd_ajuda,
    "/ping":     cmd_ping,
    "/status":   cmd_status,
    "/snapshot": cmd_snapshot,
    "/btc":      cmd_snapshot,
    "/sinais":   cmd_sinais,
}

HANDLERS_WITH_ARG: dict = {
    "/trades":      cmd_trades,
    "/performance": cmd_performance,
    "/perf":        cmd_performance,
}


def _dispatch(chat_id: int, command: str, arg: str | None) -> str:
    if command in HANDLERS_NO_ARG:
        return HANDLERS_NO_ARG[command]()
    if command in HANDLERS_WITH_ARG:
        return HANDLERS_WITH_ARG[command](arg)
    return cmd_ajuda()


# ─── Update processing & poll loop ───────────────────────────────────────────

def _process_update(update: dict, authorized_ids: list[int]) -> None:
    try:
        msg = update.get("message") or update.get("edited_message")
        if not msg:
            return

        chat_id = msg.get("chat", {}).get("id")
        if chat_id not in authorized_ids:
            log.info("unauthorized chat_id=%s", chat_id)
            return

        text    = msg.get("text", "")
        command = _extract_command(text)
        if not command:
            return

        parts = text.strip().split(maxsplit=1)
        arg   = parts[1] if len(parts) > 1 else None

        if not _check_cooldown(chat_id, command):
            log.info("cooldown: %s from %s", command, chat_id)
            return

        try:
            response = _dispatch(chat_id, command, arg)
        except Exception:
            log.exception("handler error: %s", command)
            response = f"❌ Erro interno ao processar {command}"

        ok = _tg_send(chat_id, response)
        log.info("%s arg=%r → %s", command, arg, "ok" if ok else "fail")
    except Exception:
        log.exception("unexpected error in _process_update")


def _poll_loop() -> None:
    """Loop principal de long-polling. Roda até o processo morrer."""
    global _START_TS
    _START_TS = time.time()

    token          = config.TELEGRAM_TOKEN
    authorized_ids = config.TELEGRAM_AUTHORIZED_CHAT_IDS

    if not token or not authorized_ids:
        log.warning("bot_handler inativo: token ou authorized_ids ausentes")
        return

    _tg_register_commands()
    log.info("bot_handler iniciado | authorized_ids=%s", authorized_ids)

    offset = _load_last_update_id() + 1

    while True:
        try:
            resp = requests.get(
                f"{TELEGRAM_API_BASE}/bot{token}/getUpdates",
                params={"offset": offset, "timeout": POLL_TIMEOUT_SECS, "limit": 10},
                timeout=REQUEST_TIMEOUT_SECS,
            )
            updates = resp.json().get("result", [])

            for update in updates:
                uid = update.get("update_id", 0)
                if uid >= offset:
                    offset = uid + 1
                _process_update(update, authorized_ids)

            if updates:
                _save_last_update_id(offset - 1)
        except Exception as e:
            log.warning("poll error: %s — aguardando %ds", e, ERROR_BACKOFF_SECS)
            time.sleep(ERROR_BACKOFF_SECS)


def start_bot_thread() -> threading.Thread:
    """
    OBJETIVO: Entry point chamado pelo main.py. Inicia thread daemon e retorna.
    FONTE DE DADOS: config.TELEGRAM_TOKEN, config.TELEGRAM_AUTHORIZED_CHAT_IDS.
    LIMITAÇÕES CONHECIDAS: chamar set_engine() antes; thread é daemon=True.
    NÃO FAZER: não chamar mais de uma vez por processo.
    """
    t = threading.Thread(target=_poll_loop, name="bot_handler", daemon=True)
    t.start()
    return t
