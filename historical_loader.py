#!/usr/bin/env python3
"""
historical_loader.py — Warm-up de histórico via OKX REST (SMC Monitor)
========================================================================

OBJETIVO:
    No boot do daemon, buscar candles históricos dos 3 timeframes
    (15m, 1H, 4H) via OKX REST API, auditar integridade, corrigir
    lacunas com estratégia híbrida (refetch + forward fill) e entregar
    DataFrames prontos para o engine. Garante que o SMC Monitor comece
    com estado populado em vez de aguardar dias de candles via WS.

FONTE DE DADOS:
    OKX REST API:
      - GET /api/v5/market/candles (últimos 300, sem paginação)
      - GET /api/v5/market/history-candles (paginação para trás)

LIMITAÇÕES CONHECIDAS:
    - Módulo de vida curta: roda APENAS no boot, não durante runtime
    - Requer conectividade com OKX no momento do boot
    - Se OKX estiver fora > 60s, aborta boot com RuntimeError
    - Forward fill introduz candles sintéticos com volume=0 — registrados
      em tabela historical_synthesis para auditoria posterior

NÃO FAZER:
    - Não chamar em runtime — apenas no boot via main.py
    - Não emitir sinais durante bootstrap do engine
    - Não persistir candles em candle_buffer (são históricos, não live)
    - Não incluir candles não-confirmados (confirm=0) — apenas fechados
"""

import logging
import sqlite3
import time
from datetime import datetime, timezone, timedelta

import pandas as pd
import requests

import config
import telegram

log = logging.getLogger(__name__)

VERSION = "0.1.6"


# ─── Entry point ─────────────────────────────────────────────────────────────

def load_and_heal(token: str = "BTC-USDT-SWAP") -> dict:
    """
    OBJETIVO:
        Busca, audita e corrige histórico de candles para todos os TFs
        configurados, retornando DataFrames prontos para o engine.
    FONTE DE DADOS: OKX REST API (market/candles + market/history-candles).
    LIMITAÇÕES CONHECIDAS: Levanta RuntimeError em falha catastrófica.
    NÃO FAZER: Não chamar em runtime — apenas no boot via main.py.

    Retorna {"15m": df, "1H": df, "4H": df} com DataFrames auditados
    e corrigidos. Levanta RuntimeError em falha catastrófica.
    """
    log.info("historical_loader v%s: iniciando warm-up para %s", VERSION, token)
    start = time.time()

    dfs: dict = {}

    for tf in ["15m", "1H", "4H"]:
        target = config.HIST_TARGET_BY_TF[tf]
        log.info("  → fetching %s (target=%d)", tf, target)
        try:
            df = _fetch_tf(token, tf, target)
            log.info("    fetched %d candles", len(df))
        except Exception as e:
            log.warning("    fetch failed: %s", e)
            df = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

        audit = _audit(df, tf)
        log.info(
            "    audit: %d gaps, %d dups, %d malformed",
            len(audit["gaps"]),
            len(audit["duplicates"]),
            len(audit["malformed"]),
        )

        df = _heal(df, audit, token, tf)
        log.info("    healed: final size = %d candles", len(df))

        dfs[tf] = df

    elapsed = time.time() - start
    log.info("historical_loader: concluído em %.1fs", elapsed)

    catastrophic, reason = _is_catastrophic(dfs)
    if catastrophic:
        log.critical("warm-up CATASTRÓFICO: %s", reason)
        try:
            telegram.send_critical_alert(
                f"❌ SMC Monitor boot FALHOU\n\nHistorical warm-up failed:\n{reason}"
            )
        except Exception:
            pass
        raise RuntimeError(f"historical warm-up failed: {reason}")

    return dfs


# ─── Fetch ────────────────────────────────────────────────────────────────────

def _fetch_tf(token: str, tf: str, target: int) -> pd.DataFrame:
    """
    OBJETIVO: Buscar `target` candles do timeframe `tf` via OKX REST.
    FONTE DE DADOS: OKX /market/candles e /market/history-candles.
    LIMITAÇÕES CONHECIDAS: Pagina usando history-candles quando necessário.
    NÃO FAZER: Não incluir candles não-confirmados (confirm != "1").

    Retorna DataFrame ordenado ASC por timestamp, schema OHLCV.
    """
    bar = config.HIST_TF_TO_OKX_BAR[tf]

    url = f"{config.HIST_OKX_REST_BASE}{config.HIST_CANDLES_ENDPOINT}"
    params = {"instId": token, "bar": bar, "limit": "300"}
    resp = requests.get(url, params=params, timeout=config.HIST_REQUEST_TIMEOUT_SECS)
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != "0":
        raise RuntimeError(f"OKX error: {data.get('msg')}")

    df = _parse_okx_candles(data.get("data", []))
    if df.empty:
        return df

    while len(df) < target:
        oldest_ts_ms = int(df.index[0].timestamp() * 1000)
        url_hist = f"{config.HIST_OKX_REST_BASE}{config.HIST_HISTORY_ENDPOINT}"
        params_hist = {
            "instId": token,
            "bar": bar,
            "after": str(oldest_ts_ms),
            "limit": "100",
        }
        try:
            resp2 = requests.get(
                url_hist, params=params_hist,
                timeout=config.HIST_REQUEST_TIMEOUT_SECS,
            )
            resp2.raise_for_status()
            data2 = resp2.json()
            if data2.get("code") != "0":
                log.warning("OKX pagination error: %s", data2.get("msg"))
                break
            new_df = _parse_okx_candles(data2.get("data", []))
            if new_df.empty:
                break
            df = pd.concat([new_df, df]).sort_index()
            df = df[~df.index.duplicated(keep="first")]
            time.sleep(0.1)  # respeitar rate limit
        except Exception as e:
            log.warning("pagination failed: %s", e)
            break

    if len(df) > target:
        df = df.iloc[-target:]

    return df


# ─── Audit ────────────────────────────────────────────────────────────────────

def _audit(df: pd.DataFrame, tf: str) -> dict:
    """
    OBJETIVO: Detectar problemas de integridade no DataFrame.
    FONTE DE DADOS: DataFrame retornado por _fetch_tf.
    LIMITAÇÕES CONHECIDAS: Apenas detecta — não corrige. Loga WARNING por problema.
    NÃO FAZER: Não modificar o DataFrame; não levantar exceções.

    Tipos detectados: gaps, duplicatas, desordem, malformação, gap-até-agora.
    Retorna dict com listas por tipo de problema.
    """
    report = {
        "gaps": [],         # (prev_ts, next_ts, n_missing)
        "duplicates": [],   # [ts, ...]
        "out_of_order": [], # [(index, ts), ...]
        "malformed": [],    # [(ts, reason), ...]
        "tail_gap": None,   # (last_ts, expected_last, n_missing) ou None
    }
    if df.empty:
        return report

    delta_min = config.HIST_TF_DELTA_MINUTES[tf]
    delta = timedelta(minutes=delta_min)

    if not df.index.is_monotonic_increasing:
        report["out_of_order"] = [
            (i, ts) for i, ts in enumerate(df.index)
            if i > 0 and ts <= df.index[i - 1]
        ]
        if report["out_of_order"]:
            log.warning("[%s] %d candles fora de ordem", tf, len(report["out_of_order"]))

    dup_mask = df.index.duplicated(keep=False)
    if dup_mask.any():
        report["duplicates"] = df.index[dup_mask].tolist()
        log.warning("[%s] %d timestamps duplicados", tf, len(report["duplicates"]))

    df_sorted = df[~df.index.duplicated(keep="first")].sort_index()

    for i in range(1, len(df_sorted)):
        prev_ts = df_sorted.index[i - 1]
        curr_ts = df_sorted.index[i]
        expected = prev_ts + delta
        if curr_ts > expected:
            n_missing = int((curr_ts - prev_ts) / delta) - 1
            report["gaps"].append((prev_ts, curr_ts, n_missing))
            log.warning(
                "[%s] gap de %d candle(s) entre %s e %s",
                tf, n_missing, prev_ts, curr_ts,
            )

    for ts, row in df_sorted.iterrows():
        if pd.isna(row[["open", "high", "low", "close", "volume"]]).any():
            report["malformed"].append((ts, "NaN in OHLCV"))
            log.warning("[%s] candle malformado em %s: NaN", tf, ts)
        elif row["high"] < row["low"]:
            report["malformed"].append(
                (ts, f"high<low {row['high']}<{row['low']}")
            )
            log.warning("[%s] candle malformado em %s: high<low", tf, ts)
        elif row["volume"] < 0:
            report["malformed"].append((ts, f"volume<0 {row['volume']}"))
            log.warning("[%s] candle malformado em %s: volume<0", tf, ts)

    if len(df_sorted) > 0:
        last_ts = df_sorted.index[-1]
        now = datetime.now(timezone.utc)
        expected_last = _floor_to_tf(now, tf) - delta
        if last_ts < expected_last:
            n_missing = int((expected_last - last_ts) / delta)
            report["tail_gap"] = (last_ts, expected_last, n_missing)
            log.warning(
                "[%s] tail gap de %d candle(s): último=%s esperado=%s",
                tf, n_missing, last_ts, expected_last,
            )

    return report


# ─── Heal ────────────────────────────────────────────────────────────────────

def _heal(df: pd.DataFrame, audit: dict, token: str, tf: str) -> pd.DataFrame:
    """
    OBJETIVO: Corrigir lacunas com estratégia híbrida.
    FONTE DE DADOS: DataFrame + audit report de _audit.
    LIMITAÇÕES CONHECIDAS: Forward fill usa volume=0 para evitar falso-positivo em OB.
    NÃO FAZER: Não levantar exceções — falhas de síntese são silenciosas.

    Estratégia: refetch (A) → forward fill com volume=0 (B).
    Registra cada candle sintetizado em historical_synthesis.
    """
    if df.empty:
        return df

    df = df[~df.index.duplicated(keep="first")].sort_index()

    delta_min = config.HIST_TF_DELTA_MINUTES[tf]
    delta = timedelta(minutes=delta_min)

    synthesized: list = []

    for prev_ts, next_ts, n_missing in audit["gaps"]:
        missing_tss = [prev_ts + delta * (k + 1) for k in range(n_missing)]

        refetched = _refetch_gap(token, tf, prev_ts, next_ts)

        if refetched and len(refetched) == n_missing:
            for c in refetched:
                synthesized.append({**c, "_source": "refetch"})
                _record_synthesis(token, tf, c["ts"], "refetch")
        else:
            last_row = df.loc[prev_ts]
            for ts in missing_tss:
                synthesized.append({
                    "ts": ts,
                    "open": float(last_row["close"]),
                    "high": float(last_row["close"]),
                    "low": float(last_row["close"]),
                    "close": float(last_row["close"]),
                    "volume": 0.0,
                    "_source": "forward_fill",
                })
                _record_synthesis(token, tf, ts, "forward_fill")

    if audit["tail_gap"]:
        last_ts, expected_last, n_missing = audit["tail_gap"]
        missing_tss = [last_ts + delta * (k + 1) for k in range(n_missing)]

        refetched = _refetch_gap(token, tf, last_ts, expected_last + delta)
        if refetched and len(refetched) >= n_missing:
            for c in refetched[:n_missing]:
                synthesized.append({**c, "_source": "refetch"})
                _record_synthesis(token, tf, c["ts"], "refetch")
        else:
            last_row = df.loc[last_ts]
            for ts in missing_tss:
                synthesized.append({
                    "ts": ts,
                    "open": float(last_row["close"]),
                    "high": float(last_row["close"]),
                    "low": float(last_row["close"]),
                    "close": float(last_row["close"]),
                    "volume": 0.0,
                    "_source": "forward_fill",
                })
                _record_synthesis(token, tf, ts, "forward_fill")

    if synthesized:
        syn_df = pd.DataFrame(synthesized).set_index("ts")
        syn_df = syn_df.drop(columns=["_source"], errors="ignore")
        df = pd.concat([df, syn_df]).sort_index()
        df = df[~df.index.duplicated(keep="first")]

    log.info(
        "    [%s] %d candle(s) sintetizados (refetch + forward_fill)", tf, len(synthesized)
    )
    return df


# ─── Refetch gap ─────────────────────────────────────────────────────────────

def _refetch_gap(
    token: str,
    tf: str,
    start_ts: pd.Timestamp,
    end_ts: pd.Timestamp,
) -> list | None:
    """
    OBJETIVO: Buscar candles faltantes via history-candles para um gap específico.
    FONTE DE DADOS: OKX /api/v5/market/history-candles.
    LIMITAÇÕES CONHECIDAS: Timeout de 10s; retorna None em qualquer falha.
    NÃO FAZER: Não levantar exceções — falha silenciosa com warning.

    Retorna lista de dicts {ts, open, high, low, close, volume} ou None.
    """
    bar = config.HIST_TF_TO_OKX_BAR[tf]
    url = f"{config.HIST_OKX_REST_BASE}{config.HIST_HISTORY_ENDPOINT}"

    after_ms = int(end_ts.timestamp() * 1000)
    before_ms = int(start_ts.timestamp() * 1000)

    params = {
        "instId": token,
        "bar": bar,
        "after": str(after_ms),
        "before": str(before_ms),
        "limit": "100",
    }
    try:
        resp = requests.get(
            url, params=params,
            timeout=config.HIST_REQUEST_TIMEOUT_SECS,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != "0":
            return None
        df = _parse_okx_candles(data.get("data", []))
        if df.empty:
            return None
        return [
            {
                "ts": ts,
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row["volume"]),
            }
            for ts, row in df.iterrows()
            if start_ts < ts < end_ts
        ]
    except Exception as e:
        log.warning("_refetch_gap failed: %s", e)
        return None


# ─── Forward fill (helper) ────────────────────────────────────────────────────

def _forward_fill_gap(last_candle: pd.Series, missing_timestamps: list) -> list:
    """
    OBJETIVO: Gerar candles sintéticos para timestamps ausentes.
    FONTE DE DADOS: Último candle conhecido antes do gap.
    LIMITAÇÕES CONHECIDAS: Volume=0 intencional — evita falso-positivo de OB.
    NÃO FAZER: Não interpolar preços — OHLC = close do candle anterior.
    """
    close = float(last_candle["close"])
    return [
        {
            "ts": ts,
            "open": close,
            "high": close,
            "low": close,
            "close": close,
            "volume": 0.0,
        }
        for ts in missing_timestamps
    ]


# ─── Record synthesis ─────────────────────────────────────────────────────────

def _record_synthesis(token: str, tf: str, ts: pd.Timestamp, source: str) -> None:
    """
    OBJETIVO: Registrar candle sintetizado/refetchado em historical_synthesis.
    FONTE DE DADOS: N/A (escrita de auditoria).
    LIMITAÇÕES CONHECIDAS: Falha silenciosa — auditoria não derruba boot.
    NÃO FAZER: Não levantar exceção; não registrar candles de source='api'.
    """
    try:
        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(config.DB_PATH) as conn:
            conn.execute(
                """INSERT INTO historical_synthesis
                   (token, timeframe, candle_ts, source, synthesized_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (token, tf, ts.isoformat(), source, now),
            )
            conn.commit()
    except Exception as e:
        log.warning("_record_synthesis failed: %s", e)


# ─── Catastrophic check ───────────────────────────────────────────────────────

def _is_catastrophic(dfs_by_tf: dict) -> tuple:
    """
    OBJETIVO: Detectar falha catastrófica quando qualquer TF tem dados insuficientes.
    FONTE DE DADOS: DataFrames retornados por _fetch_tf + _heal.
    LIMITAÇÕES CONHECIDAS: Threshold = 50% do HIST_TARGET_BY_TF.
    NÃO FAZER: Não levantar exceção — retorna tuple (bool, reason).

    Retorna (True, reason) se qualquer TF tem < HIST_CATASTROPHIC_MIN_PCT do alvo.
    """
    reasons = []
    for tf, target in config.HIST_TARGET_BY_TF.items():
        min_required = int(target * config.HIST_CATASTROPHIC_MIN_PCT)
        actual = len(dfs_by_tf.get(tf, pd.DataFrame()))
        if actual < min_required:
            reasons.append(f"{tf}: {actual}/{target} (<{min_required})")
    if reasons:
        return True, "; ".join(reasons)
    return False, ""


# ─── OKX parser ──────────────────────────────────────────────────────────────

def _parse_okx_candles(raw: list) -> pd.DataFrame:
    """
    OBJETIVO: Converter retorno da OKX em DataFrame OHLCV.
    FONTE DE DADOS: Lista de listas retornada pela OKX REST API.
    LIMITAÇÕES CONHECIDAS: Filtra confirm != "1" (candles não-confirmados).
    NÃO FAZER: Não incluir candles em formação (confirm="0").

    Input:  [[ts_ms, o, h, l, c, vol, volCcy, volCcyQuote, confirm], ...]
    Output: DataFrame com índice UTC, colunas [open, high, low, close, volume].
    """
    rows = []
    for c in raw:
        if len(c) < 9 or c[8] != "1":
            continue
        ts = datetime.fromtimestamp(int(c[0]) / 1000, tz=timezone.utc)
        rows.append({
            "ts": ts,
            "open": float(c[1]),
            "high": float(c[2]),
            "low": float(c[3]),
            "close": float(c[4]),
            "volume": float(c[5]),
        })
    if not rows:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    return pd.DataFrame(rows).set_index("ts").sort_index()


# ─── TF floor helper ─────────────────────────────────────────────────────────

def _floor_to_tf(dt: datetime, tf: str) -> datetime:
    """
    OBJETIVO: Arredondar datetime para o início do candle atual no timeframe.
    FONTE DE DADOS: N/A (cálculo puro).
    LIMITAÇÕES CONHECIDAS: Suporta apenas 15m, 1H, 4H.
    NÃO FAZER: Não usar para timeframes não listados.
    """
    if tf == "15m":
        minute = (dt.minute // 15) * 15
        return dt.replace(minute=minute, second=0, microsecond=0)
    elif tf == "1H":
        return dt.replace(minute=0, second=0, microsecond=0)
    elif tf == "4H":
        hour = (dt.hour // 4) * 4
        return dt.replace(hour=hour, minute=0, second=0, microsecond=0)
    raise ValueError(f"unknown tf: {tf}")
