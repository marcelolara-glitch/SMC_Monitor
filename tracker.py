# SMC Monitor — tracker.py
# Versão: v0.1.3

"""
OBJETIVO
--------
Registrar cada sinal emitido pelo signals.py e acompanhar seu ciclo
de vida de forma totalmente autônoma, observando candles 15m fechados
para detectar toque em SL, TP1 ou expiração por timeout. Fecha o
sinal automaticamente quando qualquer condição terminal ocorre. Gera
o dataset histórico de performance que alimenta a calibração do
threshold do score e prepara o sistema para o executor automático
da Fase 3.

FONTE DE DADOS
--------------
- signals.py chama register_signal() quando um sinal novo é emitido
- main.py chama observe_candle_15m() a cada candle 15m fechado
- state.py fornece o cursor SQLite compartilhado

LIMITAÇÕES CONHECIDAS
---------------------
- Detecção é por candle fechado, não tick-by-tick. Toques intrabar
  são capturados via high/low do candle, mas a ordem temporal
  exata de múltiplos toques no mesmo candle é perdida (regra de
  empate: SL vence).
- Apenas TP1 participa do fechamento automático. TP2 e TP3 ficam
  no schema para uso futuro mas não afetam status.
- Um único sinal ativo por (token, direction) por vez.

NÃO FAZER
---------
- Não expor comandos Telegram aqui (Passo 11 fará isso)
- Não chamar smc_engine nem signals.py (fluxo é unidirecional)
- Não modificar o cursor SQLite fora das transações internas
- Não assumir ordem de execução entre observe_candle_15m e
  register_signal no mesmo tick — usar transações para isolar
"""

import json
import logging
import sqlite3
import time

import config

VERSION = "v0.1.3"

logger = logging.getLogger(__name__)


# ─── Public API ───────────────────────────────────────────────────────────────

def register_signal(
    token: str,
    direction: str,
    timeframe_of_signal: str,
    emitted_at_ts: int,
    score: int,
    criteria_snapshot: dict,
    entry_low: float,
    entry_high: float,
    sl_price: float,
    tp1_price: float,
    tp2_price: float = None,
    tp3_price: float = None,
) -> int | None:
    """
    OBJETIVO: Registra um novo sinal ou incrementa reconfirmações se já ativo.
    FONTE DE DADOS: signals.py via chamada direta após avaliação de confluência.
    LIMITAÇÕES CONHECIDAS: operação atômica via transação SQLite; retorna None
                           tanto em reconfirmação quanto em falha de I/O.
    NÃO FAZER: não chamar smc_engine, não enviar Telegram.

    Registra um novo sinal. Se já existir sinal ativo para
    (token, direction), incrementa reconfirmations do ativo e
    retorna None (não abre nova entrada).
    Caso contrário, cria registro em signal_lifecycle com
    status='active', timeout_at_ts = emitted_at_ts + SIGNAL_TIMEOUT_SECONDS,
    e retorna o signal_id criado.
    """
    try:
        with sqlite3.connect(config.DB_PATH) as conn:
            cursor = conn.execute(
                "SELECT signal_id FROM signal_lifecycle "
                "WHERE token=? AND direction=? AND status='active'",
                (token, direction),
            )
            row = cursor.fetchone()
            if row:
                signal_id = row[0]
                _log_reconfirmation(signal_id, emitted_at_ts, None, conn=conn)
                conn.commit()
                logger.info(
                    "tracker.register_signal: reconfirmação signal_id=%d (%s %s)",
                    signal_id, token, direction,
                )
                return None

            timeout_at_ts = emitted_at_ts + config.SIGNAL_TIMEOUT_SECONDS
            cur = conn.execute(
                """
                INSERT INTO signal_lifecycle (
                    token, direction, timeframe_of_signal, emitted_at_ts,
                    score, criteria_snapshot, entry_low, entry_high,
                    sl_price, tp1_price, tp2_price, tp3_price,
                    timeout_at_ts, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')
                """,
                (
                    token, direction, timeframe_of_signal, emitted_at_ts,
                    score, json.dumps(criteria_snapshot),
                    entry_low, entry_high,
                    sl_price, tp1_price, tp2_price, tp3_price,
                    timeout_at_ts,
                ),
            )
            new_id = cur.lastrowid
            conn.commit()
            logger.info(
                "tracker.register_signal: novo sinal signal_id=%d (%s %s score=%d)",
                new_id, token, direction, score,
            )
            return new_id
    except Exception as e:
        logger.warning("tracker.register_signal falhou: %s", e)
        return None


def observe_candle_15m(token: str, candle: dict) -> list[dict]:
    """
    OBJETIVO: Observar candle 15m fechado e fechar sinais ativos que tocaram
              SL, TP1 ou expiraram por timeout.
    FONTE DE DADOS: candle dict da ws_feed via main.py; sinais ativos do SQLite.
    LIMITAÇÕES CONHECIDAS: empate intracandle (SL e TP no mesmo candle) — SL
                           vence; tp1_price=0 é tratado como ausente.
    NÃO FAZER: não enviar Telegram (responsabilidade do main.py); não chamar
               signals.py ou smc_engine.

    candle = {'ts': int, 'open': float, 'high': float, 'low': float,
              'close': float, 'volume': float, 'confirm': 1}

    Para cada sinal ativo do token:
      1. Se now() >= timeout_at_ts: fecha como 'timed_out'
      2. Senão, verifica toques:
         LONG:  sl_touched = candle.low <= sl_price
                tp1_touched = candle.high >= tp1_price
         SHORT: sl_touched = candle.high >= sl_price
                tp1_touched = candle.low <= tp1_price
      3. Se ambos no mesmo candle: SL vence (fecha como 'sl_hit')
      4. Se apenas SL: fecha como 'sl_hit'
      5. Se apenas TP1: fecha como 'tp1_hit'
      6. Se nenhum: não faz nada

    Retorna lista de dicts com as transições ocorridas:
      [{'signal_id': int, 'outcome': str, 'resolved_price': float, ...}]

    Chamador (main.py) é responsável por iterar a lista e disparar
    notificações Telegram via telegram.send_signal_closed().
    """
    transitions = []
    candle_ts = int(candle.get("ts", int(time.time() * 1000)))
    candle_high = float(candle.get("high", 0.0))
    candle_low = float(candle.get("low", 0.0))
    candle_close = float(candle.get("close", 0.0))

    try:
        with sqlite3.connect(config.DB_PATH) as conn:
            cursor = conn.execute(
                """
                SELECT signal_id, direction, sl_price, tp1_price,
                       timeout_at_ts, entry_low, entry_high,
                       emitted_at_ts, token
                FROM signal_lifecycle
                WHERE token=? AND status='active'
                """,
                (token,),
            )
            rows = cursor.fetchall()

        for row in rows:
            (signal_id, direction, sl_price, tp1_price,
             timeout_at_ts, entry_low, entry_high,
             emitted_at_ts, tok) = row

            now_ms = int(time.time() * 1000)
            outcome = None
            resolved_price = candle_close
            note = None

            if now_ms >= timeout_at_ts:
                outcome = "timed_out"
                resolved_price = candle_close
                note = "timeout após 24h"
            else:
                if direction == "LONG":
                    sl_touched = candle_low <= sl_price
                    tp1_touched = (
                        tp1_price is not None
                        and tp1_price > 0
                        and candle_high >= tp1_price
                    )
                else:
                    sl_touched = candle_high >= sl_price
                    tp1_touched = (
                        tp1_price is not None
                        and tp1_price > 0
                        and candle_low <= tp1_price
                    )

                if sl_touched:
                    outcome = "sl_hit"
                    resolved_price = sl_price
                elif tp1_touched:
                    outcome = "tp1_hit"
                    resolved_price = tp1_price

            if outcome:
                _close_signal(
                    signal_id=signal_id,
                    outcome=outcome,
                    event_ts=candle_ts,
                    candle_high=candle_high,
                    candle_low=candle_low,
                    candle_close=candle_close,
                    note=note,
                    resolved_price=resolved_price,
                )
                entry_mid = (entry_low + entry_high) / 2.0
                r_multiple = _calculate_r_multiple(
                    direction, entry_low, entry_high, sl_price, resolved_price
                )
                duration_seconds = max(0, int((candle_ts - emitted_at_ts) / 1000))
                transitions.append({
                    "signal_id": signal_id,
                    "token": tok,
                    "direction": direction,
                    "outcome": outcome,
                    "resolved_price": resolved_price,
                    "entry_mid": entry_mid,
                    "sl_price": sl_price,
                    "tp1_price": tp1_price,
                    "r_multiple": r_multiple,
                    "duration_seconds": duration_seconds,
                })
                logger.info(
                    "tracker.observe_candle_15m: signal_id=%d %s %s → %s r=%.2f",
                    signal_id, tok, direction, outcome, r_multiple,
                )
    except Exception as e:
        logger.warning("tracker.observe_candle_15m falhou: %s", e)

    return transitions


def get_active_signals(token: str = None, direction: str = None) -> list[dict]:
    """
    OBJETIVO: Retornar sinais ativos para checagem de concorrência.
    FONTE DE DADOS: tabela signal_lifecycle no SQLite.
    LIMITAÇÕES CONHECIDAS: leitura snapshot; pode haver race se chamado entre
                           observe_candle_15m e register_signal no mesmo tick.
    NÃO FAZER: não modificar estado, não calcular R.

    Retorna sinais com status='active'. Filtros opcionais por token e direção.
    Usado por main.py para detectar reconfirmação antes de chamar register_signal.
    """
    try:
        query = "SELECT * FROM signal_lifecycle WHERE status='active'"
        params: list = []
        if token is not None:
            query += " AND token=?"
            params.append(token)
        if direction is not None:
            query += " AND direction=?"
            params.append(direction)

        with sqlite3.connect(config.DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(query, params)
            return [dict(r) for r in cursor.fetchall()]
    except Exception as e:
        logger.warning("tracker.get_active_signals falhou: %s", e)
        return []


def get_signal(signal_id: int) -> dict | None:
    """
    OBJETIVO: Recuperar sinal específico por ID para consultas pontuais.
    FONTE DE DADOS: tabela signal_lifecycle.
    LIMITAÇÕES CONHECIDAS: retorna None se não encontrado ou em falha de I/O.
    NÃO FAZER: não modificar estado.
    """
    try:
        with sqlite3.connect(config.DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM signal_lifecycle WHERE signal_id=?",
                (signal_id,),
            )
            row = cursor.fetchone()
            return dict(row) if row else None
    except Exception as e:
        logger.warning("tracker.get_signal falhou: %s", e)
        return None


def get_performance_summary(token: str = None, since_ts: int = None) -> dict:
    """
    OBJETIVO: Fornecer resumo agregado de performance para calibração do
              threshold do score e análise histórica.
    FONTE DE DADOS: tabela signal_lifecycle.
    LIMITAÇÕES CONHECIDAS: avg_r_on_wins usa tp1_price como resolved_price;
                           win_rate exclui timed_out do denominador;
                           avg_r_on_losses é constante -1.0 por definição.
    NÃO FAZER: não modificar estado, não enviar Telegram.

    Retorna resumo agregado:
    {
      'total_signals': int,
      'resolved': int,
      'active': int,
      'wins': int,              # tp1_hit
      'losses': int,            # sl_hit
      'timeouts': int,
      'win_rate': float,        # wins / (wins + losses), 0.0 se denom=0
      'avg_r_on_wins': float,
      'avg_r_on_losses': float  # -1.0 sempre (SL = 1R por definição)
    }
    """
    _empty = {
        "total_signals": 0, "resolved": 0, "active": 0,
        "wins": 0, "losses": 0, "timeouts": 0,
        "win_rate": 0.0, "avg_r_on_wins": 0.0, "avg_r_on_losses": -1.0,
    }
    try:
        query = "SELECT * FROM signal_lifecycle WHERE 1=1"
        params: list = []
        if token is not None:
            query += " AND token=?"
            params.append(token)
        if since_ts is not None:
            query += " AND emitted_at_ts >= ?"
            params.append(since_ts)

        with sqlite3.connect(config.DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(query, params)
            rows = [dict(r) for r in cursor.fetchall()]

        total = len(rows)
        active = sum(1 for r in rows if r["status"] == "active")
        wins = sum(1 for r in rows if r["status"] == "tp1_hit")
        losses = sum(1 for r in rows if r["status"] == "sl_hit")
        timeouts = sum(1 for r in rows if r["status"] == "timed_out")
        resolved = wins + losses + timeouts

        denom = wins + losses
        win_rate = wins / denom if denom > 0 else 0.0

        r_wins = []
        for r in rows:
            if r["status"] == "tp1_hit" and r.get("resolved_price") is not None:
                rv = _calculate_r_multiple(
                    r["direction"],
                    r["entry_low"], r["entry_high"],
                    r["sl_price"], r["resolved_price"],
                )
                r_wins.append(rv)
        avg_r_on_wins = sum(r_wins) / len(r_wins) if r_wins else 0.0

        return {
            "total_signals": total,
            "resolved": resolved,
            "active": active,
            "wins": wins,
            "losses": losses,
            "timeouts": timeouts,
            "win_rate": win_rate,
            "avg_r_on_wins": avg_r_on_wins,
            "avg_r_on_losses": -1.0,
        }
    except Exception as e:
        logger.warning("tracker.get_performance_summary falhou: %s", e)
        return _empty


# ─── Private helpers ──────────────────────────────────────────────────────────

def _close_signal(
    signal_id: int,
    outcome: str,
    event_ts: int,
    candle_high: float,
    candle_low: float,
    candle_close: float,
    note: str | None,
    resolved_price: float,
) -> None:
    try:
        with sqlite3.connect(config.DB_PATH) as conn:
            conn.execute(
                """
                UPDATE signal_lifecycle
                SET status=?, resolved_at_ts=?, resolved_price=?, resolution_note=?
                WHERE signal_id=?
                """,
                (outcome, event_ts, resolved_price, note, signal_id),
            )
            conn.execute(
                """
                INSERT INTO signal_events
                    (signal_id, event_type, event_ts, candle_high, candle_low,
                     candle_close, note)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (signal_id, outcome, event_ts, candle_high, candle_low,
                 candle_close, note),
            )
            conn.commit()
    except Exception as e:
        logger.warning("tracker._close_signal signal_id=%d falhou: %s", signal_id, e)


def _log_reconfirmation(
    signal_id: int,
    event_ts: int,
    candle_close: float | None,
    conn: sqlite3.Connection | None = None,
) -> None:
    def _exec(c: sqlite3.Connection) -> None:
        c.execute(
            "UPDATE signal_lifecycle "
            "SET reconfirmations = reconfirmations + 1 WHERE signal_id=?",
            (signal_id,),
        )
        c.execute(
            """
            INSERT INTO signal_events
                (signal_id, event_type, event_ts, candle_close, note)
            VALUES (?, 'reconfirmation', ?, ?, 'reconfirmação detectada')
            """,
            (signal_id, event_ts, candle_close),
        )

    try:
        if conn is not None:
            _exec(conn)
        else:
            with sqlite3.connect(config.DB_PATH) as c:
                _exec(c)
                c.commit()
    except Exception as e:
        logger.warning(
            "tracker._log_reconfirmation signal_id=%d falhou: %s", signal_id, e
        )


def _calculate_r_multiple(
    direction: str,
    entry_low: float,
    entry_high: float,
    sl_price: float,
    resolved_price: float,
) -> float:
    entry_mid = (entry_low + entry_high) / 2.0
    try:
        if direction == "LONG":
            risk = entry_mid - sl_price
            return (resolved_price - entry_mid) / risk if risk != 0 else 0.0
        else:
            risk = sl_price - entry_mid
            return (entry_mid - resolved_price) / risk if risk != 0 else 0.0
    except Exception:
        return 0.0
