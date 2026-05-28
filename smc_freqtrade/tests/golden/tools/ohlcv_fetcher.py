"""
OBJETIVO
    Fetch OHLCV de BTC-USDT-SWAP 4H da OKX REST e gerar CSV pronto para uso
    como base do golden dataset.

    Uso (CLI):
        python -m smc_freqtrade.tests.golden.tools.ohlcv_fetcher \
            --start 2026-01-08T00:00:00Z \
            --end 2026-05-08T00:00:00Z \
            --output tests/golden/data/btc_usdt_swap_4h_window.csv

    Apos geracao, o script imprime o SHA-256 do CSV. Esse valor deve ser
    copiado para `meta.ohlcv_csv_sha256` no golden.json.

FONTE DE DADOS
    OKX REST endpoint:
    https://www.okx.com/api/v5/market/history-candles
    Parametros: instId=BTC-USDT-SWAP, bar=4H, before/after em ms.

LIMITACOES CONHECIDAS
    - OKX retorna no maximo 100 candles por chamada. Implementa paginacao.
    - Endpoint history-candles tem janela limitada -- para janelas muito
      antigas (>1 ano), pode falhar. Para 120 dias do golden, e seguro.
    - Nao ha autenticacao para endpoint publico; sem rate limiting agressivo.
      Pausa 200ms entre chamadas como cortesia.

NAO FAZER
    - Nao usar pandas-ta, ccxt ou outras libs externas para fetch -- `requests`
      direto basta.
    - Nao escrever credenciais OKX no codigo (endpoint e publico).
    - Nao modificar o CSV apos geracao -- qualquer mudanca invalida o hash.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd

OKX_HISTORY_CANDLES_URL = "https://www.okx.com/api/v5/market/history-candles"
OKX_PAGE_LIMIT = 100
COURTESY_PAUSE_SECONDS = 0.2

# Mapping de timeframes OKX -> segundos por candle. Cobre os bars usados
# pelos goldens (4H principal + MTF 1H / 15m). Estender quando o projeto
# precisar de outros TFs.
TIMEFRAME_SECONDS: dict[str, int] = {
    "1m": 60,
    "3m": 180,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1H": 3600,
    "2H": 7200,
    "4H": 14400,
    "6H": 21600,
    "12H": 43200,
    "1D": 86400,
}


def _parse_iso_utc(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _to_ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def _from_ms(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


def _paginate(
    start_ms: int,
    end_ms: int,
    instrument: str,
    bar: str,
) -> list[list]:
    """Faz paginacao reversa do endpoint history-candles ate cobrir [start, end)."""
    import requests  # import local para nao acoplar import-time a rede

    rows: list[list] = []
    cursor_after = end_ms
    seen_ts: set[int] = set()

    while True:
        params = {
            "instId": instrument,
            "bar": bar,
            "limit": str(OKX_PAGE_LIMIT),
            "after": str(cursor_after),
        }
        response = requests.get(OKX_HISTORY_CANDLES_URL, params=params, timeout=15)
        response.raise_for_status()
        payload = response.json()
        if payload.get("code") not in ("0", 0):
            raise RuntimeError(
                f"OKX API erro: code={payload.get('code')} msg={payload.get('msg')}"
            )
        page = payload.get("data") or []
        if not page:
            break

        oldest_ts_in_page = None
        page_added = False
        for raw in page:
            ts = int(raw[0])
            if ts < start_ms or ts >= end_ms:
                if oldest_ts_in_page is None or ts < oldest_ts_in_page:
                    oldest_ts_in_page = ts
                continue
            if ts in seen_ts:
                continue
            seen_ts.add(ts)
            rows.append(raw)
            page_added = True
            if oldest_ts_in_page is None or ts < oldest_ts_in_page:
                oldest_ts_in_page = ts

        if oldest_ts_in_page is None or oldest_ts_in_page <= start_ms:
            break
        if not page_added and oldest_ts_in_page >= cursor_after:
            break
        cursor_after = oldest_ts_in_page
        time.sleep(COURTESY_PAUSE_SECONDS)

    return rows


def _rows_to_dataframe(rows: Iterable[list]) -> pd.DataFrame:
    parsed: list[dict] = []
    for raw in rows:
        ts_ms = int(raw[0])
        parsed.append(
            {
                "timestamp_utc": _from_ms(ts_ms).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "_ts_ms": ts_ms,
                "open": float(raw[1]),
                "high": float(raw[2]),
                "low": float(raw[3]),
                "close": float(raw[4]),
                "volume": float(raw[5]),
            }
        )
    df = pd.DataFrame(parsed)
    if df.empty:
        return pd.DataFrame(
            columns=["timestamp_utc", "open", "high", "low", "close", "volume"]
        )
    df = df.sort_values("_ts_ms").reset_index(drop=True)
    return df[["timestamp_utc", "open", "high", "low", "close", "volume"]]


def _validate_continuity(
    df: pd.DataFrame, expected_bar_seconds: int
) -> list[str]:
    errors: list[str] = []
    if df.empty:
        errors.append("CSV vazio: nenhum candle retornado pela API.")
        return errors

    timestamps = pd.to_datetime(df["timestamp_utc"], utc=True, format="%Y-%m-%dT%H:%M:%SZ")
    duplicates = timestamps[timestamps.duplicated()].tolist()
    if duplicates:
        errors.append(f"Timestamps duplicados detectados: {len(duplicates)} ocorrencias.")

    deltas = timestamps.diff().dropna().dt.total_seconds().astype(int)
    bad_gaps = deltas[deltas != expected_bar_seconds]
    if not bad_gaps.empty:
        sample = bad_gaps.head(5).tolist()
        errors.append(
            f"Gaps detectados: {len(bad_gaps)} delta(s) != {expected_bar_seconds}s "
            f"(primeiros: {sample})."
        )

    return errors


def fetch_window(
    start_utc: datetime,
    end_utc: datetime,
    instrument: str = "BTC-USDT-SWAP",
    timeframe: str = "4H",
) -> pd.DataFrame:
    if start_utc >= end_utc:
        raise ValueError("start_utc deve ser estritamente menor que end_utc.")
    if timeframe not in TIMEFRAME_SECONDS:
        raise ValueError(
            f"Timeframe {timeframe!r} nao suportado. "
            f"Validos: {sorted(TIMEFRAME_SECONDS)}."
        )
    rows = _paginate(_to_ms(start_utc), _to_ms(end_utc), instrument, timeframe)
    df = _rows_to_dataframe(rows)
    expected_bar_seconds = TIMEFRAME_SECONDS[timeframe]
    gaps = _validate_continuity(df, expected_bar_seconds)
    if gaps:
        raise RuntimeError("Janela de OHLCV invalida: " + "; ".join(gaps))
    return df


def write_csv(df: pd.DataFrame, output_path: Path) -> str:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False, lineterminator="\n")
    digest = hashlib.sha256(output_path.read_bytes()).hexdigest()
    sha_path = output_path.with_suffix(output_path.suffix + ".sha256")
    sha_path.write_text(digest + "\n", encoding="utf-8")
    return digest


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch OHLCV BTC-USDT-SWAP 4H da OKX.")
    parser.add_argument("--start", required=True, help="ISO 8601 UTC, ex: 2026-01-08T00:00:00Z")
    parser.add_argument("--end", required=True, help="ISO 8601 UTC, ex: 2026-05-08T00:00:00Z")
    parser.add_argument("--output", required=True, help="Caminho do CSV de saida.")
    parser.add_argument(
        "--instrument",
        default="BTC-USDT-SWAP",
        help="Identificador OKX (default: BTC-USDT-SWAP).",
    )
    parser.add_argument(
        "--timeframe",
        default="4H",
        help="Bar OKX (default: 4H).",
    )
    args = parser.parse_args(argv)

    start = _parse_iso_utc(args.start)
    end = _parse_iso_utc(args.end)
    df = fetch_window(start, end, instrument=args.instrument, timeframe=args.timeframe)
    digest = write_csv(df, Path(args.output))
    print(f"OK: {len(df)} candles escritos em {args.output}")
    print(f"SHA-256: {digest}")
    return 0


if __name__ == "__main__":
    sys.exit(_main())
