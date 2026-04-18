# SMC Monitor — state.py
# Versão: 0.1.2

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


# ─── Public API ──────────────────────────────────────────────────────────────

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
