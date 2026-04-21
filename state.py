# SMC Monitor — state.py
# Versão: 0.1.10

"""
OBJETIVO: Persistência SQLite do estado SMC para crash-recovery.
Salva estado SMC completo periodicamente e restaura na inicialização.
FONTE DE DADOS: Dicts retornados por SMCEngine.get_all_states() e buffers de candles.
LIMITAÇÕES CONHECIDAS: Falhas de I/O são silenciosas — apenas warning no log.
NÃO FAZER: sem cálculo SMC, sem chamadas diretas ao smc_engine, sem bloqueio do loop principal.
"""

import json
import logging
import os
import sqlite3
import time

import config

VERSION = "0.1.10"

logger = logging.getLogger(__name__)

# ─── Schema ──────────────────────────────────────────────────────────────────

_DDL_SMC_STATE = """
CREATE TABLE IF NOT EXISTS smc_state (
    token       TEXT    NOT NULL,
    timeframe   TEXT    NOT NULL,
    state_json  TEXT    NOT NULL,
    updated_at  INTEGER NOT NULL,
    PRIMARY KEY (token, timeframe)
)
"""

_DDL_CANDLE_BUFFER = """
CREATE TABLE IF NOT EXISTS candle_buffer (
    token        TEXT    NOT NULL,
    timeframe    TEXT    NOT NULL,
    candles_json TEXT    NOT NULL,
    updated_at   INTEGER NOT NULL,
    PRIMARY KEY (token, timeframe)
)
"""

_DDL_EVENT_TRACKING = """
CREATE TABLE IF NOT EXISTS event_tracking (
    token         TEXT    NOT NULL,
    timeframe     TEXT    NOT NULL,
    event_type    TEXT    NOT NULL,
    last_event_ts INTEGER NOT NULL,
    last_value    TEXT,
    updated_at    INTEGER NOT NULL,
    PRIMARY KEY (token, timeframe, event_type)
)
"""

_DDL_SIGNAL_LIFECYCLE = """
CREATE TABLE IF NOT EXISTS signal_lifecycle (
  signal_id          INTEGER PRIMARY KEY AUTOINCREMENT,
  token              TEXT    NOT NULL,
  direction          TEXT    NOT NULL CHECK(direction IN ('LONG', 'SHORT')),
  timeframe_of_signal TEXT   NOT NULL,
  emitted_at_ts      INTEGER NOT NULL,
  score              INTEGER NOT NULL,
  criteria_snapshot  TEXT    NOT NULL,
  entry_low          REAL    NOT NULL,
  entry_high         REAL    NOT NULL,
  sl_price           REAL    NOT NULL,
  tp1_price          REAL    NOT NULL,
  tp2_price          REAL,
  tp3_price          REAL,
  timeout_at_ts      INTEGER NOT NULL,
  status             TEXT    NOT NULL CHECK(status IN (
                       'active', 'sl_hit', 'tp1_hit', 'timed_out'
                     )),
  resolved_at_ts     INTEGER,
  resolved_price     REAL,
  resolution_note    TEXT,
  reconfirmations    INTEGER NOT NULL DEFAULT 0,
  UNIQUE(token, direction, emitted_at_ts)
)
"""

_DDL_SIGNAL_LIFECYCLE_IDX1 = """
CREATE INDEX IF NOT EXISTS idx_signal_lifecycle_status
  ON signal_lifecycle(status)
"""

_DDL_SIGNAL_LIFECYCLE_IDX2 = """
CREATE INDEX IF NOT EXISTS idx_signal_lifecycle_token_direction_status
  ON signal_lifecycle(token, direction, status)
"""

_DDL_SIGNAL_EVENTS = """
CREATE TABLE IF NOT EXISTS signal_events (
  event_id    INTEGER PRIMARY KEY AUTOINCREMENT,
  signal_id   INTEGER NOT NULL,
  event_type  TEXT    NOT NULL CHECK(event_type IN (
                'sl_hit', 'tp1_hit', 'timed_out', 'reconfirmation'
              )),
  event_ts    INTEGER NOT NULL,
  candle_high REAL,
  candle_low  REAL,
  candle_close REAL,
  note        TEXT,
  FOREIGN KEY(signal_id) REFERENCES signal_lifecycle(signal_id)
)
"""

_DDL_SIGNAL_EVENTS_IDX = """
CREATE INDEX IF NOT EXISTS idx_signal_events_signal_id
  ON signal_events(signal_id)
"""

_DDL_BOT_STATE = """
CREATE TABLE IF NOT EXISTS bot_state (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""

_DDL_HISTORICAL_SYNTHESIS = """
CREATE TABLE IF NOT EXISTS historical_synthesis (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    token           TEXT NOT NULL,
    timeframe       TEXT NOT NULL,
    candle_ts       TEXT NOT NULL,
    source          TEXT NOT NULL,
    synthesized_at  TEXT NOT NULL
)
"""

_DDL_HISTORICAL_SYNTHESIS_IDX = """
CREATE INDEX IF NOT EXISTS idx_hist_synth_token_tf
    ON historical_synthesis(token, timeframe)
"""

_DDL_SIGNAL_EMISSION_TRACKING = """
CREATE TABLE IF NOT EXISTS signal_emission_tracking (
    key_hash         TEXT    PRIMARY KEY,
    token            TEXT    NOT NULL,
    direction        TEXT    NOT NULL,
    ob_range_hash    TEXT    NOT NULL,
    fvg_range_hash   TEXT    NOT NULL,
    first_emitted_ts INTEGER NOT NULL,
    last_emitted_ts  INTEGER NOT NULL,
    peak_score       INTEGER NOT NULL,
    emission_count   INTEGER NOT NULL DEFAULT 1
)
"""


# ─── Public API ──────────────────────────────────────────────────────────────

def ensure_bot_state_table(conn: sqlite3.Connection) -> None:
    """
    OBJETIVO: Garantir tabela bot_state (migration idempotente).
    FONTE DE DADOS: conexão SQLite existente passada pelo chamador.
    LIMITAÇÕES CONHECIDAS: Nenhuma — CREATE TABLE IF NOT EXISTS é idempotente.
    NÃO FAZER: não dropar tabela existente, não commitar (responsabilidade do chamador).
    """
    conn.execute(_DDL_BOT_STATE)
    conn.commit()


def ensure_historical_synthesis_table(conn: sqlite3.Connection) -> None:
    """
    OBJETIVO:
        Garantir existência da tabela historical_synthesis e índice
        associado. Migration idempotente.
    FONTE DE DADOS: N/A (DDL).
    LIMITAÇÕES CONHECIDAS: Nenhuma — CREATE TABLE IF NOT EXISTS é idempotente.
    NÃO FAZER: Não dropar a tabela existente.
    """
    conn.execute(_DDL_HISTORICAL_SYNTHESIS)
    conn.execute(_DDL_HISTORICAL_SYNTHESIS_IDX)
    conn.commit()


def init_db() -> None:
    """
    Cria o banco SQLite e as tabelas se não existirem.
    Chamado uma vez na inicialização do daemon.
    Nunca dropa tabelas existentes.
    """
    try:
        os.makedirs(os.path.dirname(config.DB_PATH), exist_ok=True)
        with sqlite3.connect(config.DB_PATH) as conn:
            conn.execute(_DDL_SMC_STATE)
            conn.execute(_DDL_CANDLE_BUFFER)
            conn.execute(_DDL_EVENT_TRACKING)
            conn.execute(_DDL_SIGNAL_LIFECYCLE)
            conn.execute(_DDL_SIGNAL_LIFECYCLE_IDX1)
            conn.execute(_DDL_SIGNAL_LIFECYCLE_IDX2)
            conn.execute(_DDL_SIGNAL_EVENTS)
            conn.execute(_DDL_SIGNAL_EVENTS_IDX)
            conn.execute(_DDL_SIGNAL_EMISSION_TRACKING)
            ensure_bot_state_table(conn)
            ensure_historical_synthesis_table(conn)
            conn.commit()
    except Exception as e:
        logger.warning("state.init_db falhou: %s", e)


def save_state(all_states: dict) -> None:
    """
    Persiste snapshot completo do estado SMC.
    Recebe o retorno de SMCEngine.get_all_states().
    Falhas de I/O são silenciosas — log warning, nunca raise.
    """
    try:
        now_ms = int(time.time() * 1000)
        rows = []
        for token, tf_states in all_states.items():
            for timeframe, state in tf_states.items():
                rows.append((token, timeframe, json.dumps(state), now_ms))

        with sqlite3.connect(config.DB_PATH) as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO smc_state (token, timeframe, state_json, updated_at) "
                "VALUES (?, ?, ?, ?)",
                rows,
            )
            conn.commit()
    except Exception as e:
        logger.warning("state.save_state falhou: %s", e)


def load_state() -> dict:
    """
    Restaura último estado salvo na inicialização.
    Retorna dict vazio se banco não existe ou está corrompido.
    Falhas de I/O são silenciosas — log warning, retorna dict vazio.
    """
    try:
        if not os.path.exists(config.DB_PATH):
            return {}

        result: dict = {}
        with sqlite3.connect(config.DB_PATH) as conn:
            cursor = conn.execute(
                "SELECT token, timeframe, state_json FROM smc_state"
            )
            for token, timeframe, state_json in cursor:
                if token not in result:
                    result[token] = {}
                result[token][timeframe] = json.loads(state_json)

        return result
    except Exception as e:
        logger.warning("state.load_state falhou: %s", e)
        return {}


def save_candle_buffer(token: str, timeframe: str, candles: list) -> None:
    """
    Persiste buffer de candles para um par token/timeframe.
    Permite reconstruir estado SMC sem aguardar buffer encher do zero.
    Falhas de I/O são silenciosas.
    """
    try:
        now_ms = int(time.time() * 1000)
        with sqlite3.connect(config.DB_PATH) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO candle_buffer (token, timeframe, candles_json, updated_at) "
                "VALUES (?, ?, ?, ?)",
                (token, timeframe, json.dumps(candles), now_ms),
            )
            conn.commit()
    except Exception as e:
        logger.warning("state.save_candle_buffer falhou: %s", e)


def load_candle_buffers() -> dict:
    """
    Restaura buffers de candles salvos.
    Retorna dict vazio se não houver dados.
    Estrutura do retorno: token -> timeframe -> lista de candles.
    Falhas de I/O são silenciosas.
    """
    try:
        if not os.path.exists(config.DB_PATH):
            return {}

        result: dict = {}
        with sqlite3.connect(config.DB_PATH) as conn:
            cursor = conn.execute(
                "SELECT token, timeframe, candles_json FROM candle_buffer"
            )
            for token, timeframe, candles_json in cursor:
                if token not in result:
                    result[token] = {}
                result[token][timeframe] = json.loads(candles_json)

        return result
    except Exception as e:
        logger.warning("state.load_candle_buffers falhou: %s", e)
        return {}


def load_event_tracking() -> dict:
    """
    OBJETIVO: restaurar cache de rastreamento de eventos do SQLite na inicialização.
    FONTE DE DADOS: tabela event_tracking no banco SQLite (config.DB_PATH).
    LIMITAÇÕES CONHECIDAS: falhas de I/O são silenciosas — retorna dict vazio.
    NÃO FAZER: sem cálculo SMC; sem acesso direto ao engine.

    Retorna dict no formato:
        {(token, timeframe, event_type): {"ts": int, "value": str | None}}
    """
    try:
        if not os.path.exists(config.DB_PATH):
            return {}

        result: dict = {}
        with sqlite3.connect(config.DB_PATH) as conn:
            cursor = conn.execute(
                "SELECT token, timeframe, event_type, last_event_ts, last_value "
                "FROM event_tracking"
            )
            for token, timeframe, event_type, last_event_ts, last_value in cursor:
                result[(token, timeframe, event_type)] = {
                    "ts": last_event_ts,
                    "value": last_value,
                }

        return result
    except Exception as e:
        logger.warning("state.load_event_tracking falhou: %s", e)
        return {}


def save_event_tracking(cache: dict) -> None:
    """
    OBJETIVO: persistir cache de rastreamento de eventos no SQLite.
    FONTE DE DADOS: dict {(token, timeframe, event_type): {"ts": int, "value": str | None}}.
    LIMITAÇÕES CONHECIDAS: falhas de I/O são silenciosas — warning no log, sem raise.
                           Usa INSERT OR REPLACE — chaves órfãs no DB nunca são apagadas
                           (OK para o volume esperado, baixa cardinalidade).
    NÃO FAZER: sem cálculo SMC; sem acesso direto ao engine.
    """
    try:
        now_ms = int(time.time() * 1000)
        rows = []
        for (token, timeframe, event_type), entry in cache.items():
            rows.append((
                token, timeframe, event_type,
                entry["ts"], entry.get("value"),
                now_ms,
            ))
        with sqlite3.connect(config.DB_PATH) as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO event_tracking "
                "(token, timeframe, event_type, last_event_ts, last_value, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                rows,
            )
            conn.commit()
    except Exception as e:
        logger.warning("state.save_event_tracking falhou: %s", e)


# ─── Signal emission tracking (PR B3) ────────────────────────────────────────

def get_emission_context(key_hash: str) -> dict | None:
    """
    OBJETIVO: recuperar contexto de emissão de sinal persistido por key_hash.
    FONTE DE DADOS: tabela signal_emission_tracking.
    LIMITAÇÕES CONHECIDAS: falhas de I/O são silenciosas — retorna None.
    NÃO FAZER: sem cálculo SMC, sem acesso direto ao engine.

    Retorna dict com campos token, direction, ob_range_hash, fvg_range_hash,
    first_emitted_ts, last_emitted_ts, peak_score, emission_count — ou None
    se a chave não existe.
    """
    try:
        if not os.path.exists(config.DB_PATH):
            return None
        with sqlite3.connect(config.DB_PATH) as conn:
            cursor = conn.execute(
                "SELECT token, direction, ob_range_hash, fvg_range_hash, "
                "first_emitted_ts, last_emitted_ts, peak_score, emission_count "
                "FROM signal_emission_tracking WHERE key_hash = ?",
                (key_hash,),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return {
                "token":            row[0],
                "direction":        row[1],
                "ob_range_hash":    row[2],
                "fvg_range_hash":   row[3],
                "first_emitted_ts": row[4],
                "last_emitted_ts":  row[5],
                "peak_score":       row[6],
                "emission_count":   row[7],
            }
    except Exception as e:
        logger.warning("state.get_emission_context falhou: %s", e)
        return None


def record_emission(
    key_hash: str,
    token: str,
    direction: str,
    ob_hash: str,
    fvg_hash: str,
    score: int,
    ts: int,
) -> None:
    """
    OBJETIVO: upsert de contexto de emissão. Se o key_hash é novo, insere
              com emission_count=1 e first_emitted_ts=ts. Se já existe,
              atualiza last_emitted_ts, peak_score (=max) e incrementa
              emission_count.
    FONTE DE DADOS: argumentos passados pelo chamador (signals.evaluate).
    LIMITAÇÕES CONHECIDAS: falhas de I/O são silenciosas — warning.
    NÃO FAZER: sem cálculo SMC; sem acesso direto ao engine.
    """
    try:
        with sqlite3.connect(config.DB_PATH) as conn:
            cursor = conn.execute(
                "SELECT peak_score, emission_count, first_emitted_ts "
                "FROM signal_emission_tracking WHERE key_hash = ?",
                (key_hash,),
            )
            row = cursor.fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO signal_emission_tracking "
                    "(key_hash, token, direction, ob_range_hash, fvg_range_hash, "
                    " first_emitted_ts, last_emitted_ts, peak_score, emission_count) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)",
                    (key_hash, token, direction, ob_hash, fvg_hash,
                     ts, ts, score),
                )
            else:
                prev_peak, prev_count, first_ts = row
                new_peak = max(int(prev_peak), int(score))
                conn.execute(
                    "UPDATE signal_emission_tracking "
                    "SET last_emitted_ts = ?, peak_score = ?, "
                    "    emission_count = ? "
                    "WHERE key_hash = ?",
                    (ts, new_peak, int(prev_count) + 1, key_hash),
                )
            conn.commit()
    except Exception as e:
        logger.warning("state.record_emission falhou: %s", e)


def invalidate_emission_context(key_hash: str) -> None:
    """
    OBJETIVO: remover contexto de emissão (OB/FVG mitigado, preço escapou
              da zona, ou outra invalidação imediata).
    FONTE DE DADOS: key_hash do contexto a remover.
    LIMITAÇÕES CONHECIDAS: falhas de I/O são silenciosas.
    NÃO FAZER: sem cálculo SMC.
    """
    try:
        with sqlite3.connect(config.DB_PATH) as conn:
            conn.execute(
                "DELETE FROM signal_emission_tracking WHERE key_hash = ?",
                (key_hash,),
            )
            conn.commit()
    except Exception as e:
        logger.warning("state.invalidate_emission_context falhou: %s", e)


def prune_emission_contexts(max_age_seconds: int = 21600) -> int:
    """
    OBJETIVO: remover contextos de emissão que não tiveram atividade nos
              últimos max_age_seconds. Padrão: 6h (21600s).
    FONTE DE DADOS: tabela signal_emission_tracking, comparando
                    last_emitted_ts com o now atual.
    LIMITAÇÕES CONHECIDAS: falhas de I/O são silenciosas — retorna 0.
    NÃO FAZER: sem cálculo SMC.

    Retorna a quantidade de linhas removidas.
    """
    try:
        cutoff_ms = int(time.time() * 1000) - int(max_age_seconds) * 1000
        with sqlite3.connect(config.DB_PATH) as conn:
            cursor = conn.execute(
                "DELETE FROM signal_emission_tracking "
                "WHERE last_emitted_ts < ?",
                (cutoff_ms,),
            )
            conn.commit()
            return cursor.rowcount or 0
    except Exception as e:
        logger.warning("state.prune_emission_contexts falhou: %s", e)
        return 0
