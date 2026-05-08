"""
OBJETIVO
    Validar um arquivo de golden dataset SMC contra:
    1. Schema estrutural (campos obrigatorios, tipos, enums).
    2. Coerencia interna (timestamps dentro da janela, candle_idx
       coerente com timestamp_utc, screenshots nao-sobrepostos).
    3. Integridade do CSV de OHLCV (hash SHA-256 bate com meta).

    Uso (CLI):
        python -m smc_freqtrade.tests.golden.tools.golden_validator \
            --golden tests/golden/golden/btc_usdt_swap_4h_luxalgo_smc.json \
            --csv tests/golden/data/btc_usdt_swap_4h_window.csv

    Uso programatico:
        from smc_freqtrade.tests.golden.tools.golden_validator import validate
        result = validate(golden_path, csv_path)
        # result e namedtuple (is_valid: bool, errors: list[str])

FONTE DE DADOS
    - Arquivo JSON do golden (path fornecido)
    - CSV de OHLCV em formato `timestamp_utc,open,high,low,close,volume`
      (path fornecido)

LIMITACOES CONHECIDAS
    - Validacao nao checa correcao semantica dos eventos (nao roda a engine).
      E responsabilidade dos testes das Ondas 5+.
    - Nao valida `produced_at_utc` contra clock real (apenas formato).
    - Implementacao manual sem `jsonschema`; adicionar dependencia seria
      overhead para um schema simples.

NAO FAZER
    - Nao adicionar dependencia a `jsonschema` ou outras libs de validacao
      JSON.
    - Nao rodar a engine SMC para checar eventos (escopo de testes futuros).
    - Nao modificar o golden ou o CSV durante validacao -- script e read-only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import namedtuple
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ValidationResult = namedtuple("ValidationResult", ["is_valid", "errors"])

EVENT_TYPES = {
    "bos_bullish_internal",
    "bos_bearish_internal",
    "bos_bullish_swing",
    "bos_bearish_swing",
    "choch_bullish_internal",
    "choch_bearish_internal",
    "choch_bullish_swing",
    "choch_bearish_swing",
    "ob_bullish_internal_formed",
    "ob_bearish_internal_formed",
    "ob_bullish_swing_formed",
    "ob_bearish_swing_formed",
    "ob_bullish_internal_mitigated",
    "ob_bearish_internal_mitigated",
    "ob_bullish_swing_mitigated",
    "ob_bearish_swing_mitigated",
    "fvg_bullish_formed",
    "fvg_bearish_formed",
    "fvg_bullish_mitigated",
    "fvg_bearish_mitigated",
    "eqh_alert",
    "eql_alert",
}

OB_FORMED_EVENTS = {
    "ob_bullish_internal_formed",
    "ob_bearish_internal_formed",
    "ob_bullish_swing_formed",
    "ob_bearish_swing_formed",
}

FVG_FORMED_EVENTS = {
    "fvg_bullish_formed",
    "fvg_bearish_formed",
}

EQ_ALERT_EVENTS = {"eqh_alert", "eql_alert"}

ZONE_TYPES = {"premium", "equilibrium", "discount"}

REQUIRED_META_FIELDS = [
    "indicator",
    "indicator_version",
    "tradingview_timezone",
    "instrument",
    "exchange",
    "timeframe",
    "window_start_utc",
    "window_end_utc",
    "ohlcv_csv_sha256",
    "extracted_by",
    "structured_by",
    "produced_at_utc",
    "scope_included",
    "scope_excluded",
    "match_tolerance_candles",
]

REQUIRED_EVENT_FIELDS = ["event_type", "timestamp_utc", "candle_idx", "screenshot_id"]
REQUIRED_ZONE_FIELDS = ["zone_type", "screenshot_id", "valid_from_utc", "valid_until_utc"]
REQUIRED_SHOT_FIELDS = ["screenshot_id", "candle_range_start_utc", "candle_range_end_utc"]

CSV_REQUIRED_COLUMNS = ["timestamp_utc", "open", "high", "low", "close", "volume"]

SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
ISO8601_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})$"
)


def _parse_iso(value: str) -> datetime | None:
    if not isinstance(value, str):
        return None
    if not ISO8601_RE.match(value):
        return None
    try:
        normalized = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _check_meta_block(meta: dict) -> tuple[list[str], datetime | None, datetime | None]:
    errors: list[str] = []
    if not isinstance(meta, dict):
        return ["meta: bloco ausente ou nao e objeto."], None, None

    for field in REQUIRED_META_FIELDS:
        if field not in meta:
            errors.append(f"meta.{field}: campo obrigatorio ausente.")

    tz_value = meta.get("tradingview_timezone")
    if tz_value is not None and tz_value != "UTC":
        errors.append(f"meta.tradingview_timezone: esperado 'UTC', recebido {tz_value!r}.")

    tf_value = meta.get("timeframe")
    if tf_value is not None and tf_value != "4h":
        errors.append(f"meta.timeframe: esperado '4h', recebido {tf_value!r}.")

    sha = meta.get("ohlcv_csv_sha256")
    if isinstance(sha, str) and not SHA256_RE.match(sha):
        errors.append(
            "meta.ohlcv_csv_sha256: nao e SHA-256 hex valido "
            "(64 chars [a-f0-9]). Verifique se o placeholder foi substituido."
        )

    window_start = _parse_iso(meta.get("window_start_utc")) if isinstance(meta.get("window_start_utc"), str) else None
    window_end = _parse_iso(meta.get("window_end_utc")) if isinstance(meta.get("window_end_utc"), str) else None
    if meta.get("window_start_utc") is not None and window_start is None:
        errors.append("meta.window_start_utc: timestamp ISO 8601 UTC invalido.")
    if meta.get("window_end_utc") is not None and window_end is None:
        errors.append("meta.window_end_utc: timestamp ISO 8601 UTC invalido.")
    if window_start and window_end and window_start >= window_end:
        errors.append("meta.window_start_utc deve ser estritamente menor que window_end_utc.")

    if "produced_at_utc" in meta:
        if not isinstance(meta["produced_at_utc"], str) or _parse_iso(meta["produced_at_utc"]) is None:
            errors.append("meta.produced_at_utc: timestamp ISO 8601 UTC invalido.")

    if "match_tolerance_candles" in meta:
        tol = meta["match_tolerance_candles"]
        if not isinstance(tol, int) or isinstance(tol, bool) or tol < 1:
            errors.append("meta.match_tolerance_candles: deve ser inteiro >= 1.")

    for arr_field in ("scope_included", "scope_excluded"):
        if arr_field in meta:
            value = meta[arr_field]
            if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
                errors.append(f"meta.{arr_field}: deve ser lista de strings.")

    for str_field in ("indicator", "indicator_version", "instrument", "exchange",
                      "extracted_by", "structured_by"):
        if str_field in meta and not isinstance(meta[str_field], str):
            errors.append(f"meta.{str_field}: deve ser string.")

    raw = meta.get("indicator_version")
    if isinstance(raw, str) and "PLACEHOLDER" in raw.upper():
        errors.append("meta.indicator_version: contem PLACEHOLDER nao resolvido.")
    raw = meta.get("ohlcv_csv_sha256")
    if isinstance(raw, str) and "PLACEHOLDER" in raw.upper():
        errors.append("meta.ohlcv_csv_sha256: contem PLACEHOLDER nao resolvido.")
    for f in ("window_start_utc", "window_end_utc", "produced_at_utc"):
        v = meta.get(f)
        if isinstance(v, str) and "PLACEHOLDER" in v.upper():
            errors.append(f"meta.{f}: contem PLACEHOLDER nao resolvido.")

    return errors, window_start, window_end


def _check_csv_hash(csv_path: Path, expected_sha: str | None) -> str | None:
    if expected_sha is None:
        return "meta.ohlcv_csv_sha256 ausente; nao foi possivel checar integridade do CSV."
    if not csv_path.exists():
        return f"CSV nao encontrado em {csv_path}."
    digest = hashlib.sha256(csv_path.read_bytes()).hexdigest()
    if digest != expected_sha:
        return (
            f"CSV hash nao bate com meta.ohlcv_csv_sha256: "
            f"esperado={expected_sha} obtido={digest}."
        )
    return None


def _load_csv(csv_path: Path) -> tuple[pd.DataFrame | None, list[str]]:
    errors: list[str] = []
    if not csv_path.exists():
        return None, [f"CSV nao encontrado em {csv_path}."]
    try:
        df = pd.read_csv(csv_path)
    except Exception as exc:
        return None, [f"CSV nao parseavel: {exc}."]
    if list(df.columns) != CSV_REQUIRED_COLUMNS:
        errors.append(
            f"CSV columns inesperadas: esperado {CSV_REQUIRED_COLUMNS}, "
            f"recebido {list(df.columns)}."
        )
    return df, errors


def _build_csv_index(df: pd.DataFrame) -> dict[str, int]:
    index: dict[str, int] = {}
    for idx, ts in enumerate(df["timestamp_utc"].astype(str).tolist()):
        index[ts] = idx
    return index


def _check_events_block(
    events: list,
    csv_df: pd.DataFrame | None,
    window_start: datetime | None,
    window_end: datetime | None,
    known_screenshot_ids: set[str],
) -> list[str]:
    errors: list[str] = []
    if not isinstance(events, list):
        return ["events: deve ser uma lista."]

    csv_ts_index: dict[str, int] = {}
    if csv_df is not None and list(csv_df.columns) == CSV_REQUIRED_COLUMNS:
        csv_ts_index = _build_csv_index(csv_df)

    for i, event in enumerate(events):
        prefix = f"events[{i}]"
        if not isinstance(event, dict):
            errors.append(f"{prefix}: deve ser objeto.")
            continue

        for field in REQUIRED_EVENT_FIELDS:
            if field not in event:
                errors.append(f"{prefix}.{field}: campo obrigatorio ausente.")

        evt_type = event.get("event_type")
        if evt_type is not None and evt_type not in EVENT_TYPES:
            errors.append(f"{prefix}.event_type: valor desconhecido {evt_type!r}.")

        ts_str = event.get("timestamp_utc")
        ts_dt = _parse_iso(ts_str) if isinstance(ts_str, str) else None
        if ts_str is not None and ts_dt is None:
            errors.append(f"{prefix}.timestamp_utc: ISO 8601 UTC invalido ({ts_str!r}).")

        if ts_dt is not None and window_start is not None and window_end is not None:
            if ts_dt < window_start or ts_dt > window_end:
                errors.append(
                    f"{prefix}.timestamp_utc: fora da janela "
                    f"[{window_start.isoformat()}, {window_end.isoformat()}]."
                )

        candle_idx = event.get("candle_idx")
        if candle_idx is not None:
            if not isinstance(candle_idx, int) or isinstance(candle_idx, bool) or candle_idx < 0:
                errors.append(f"{prefix}.candle_idx: deve ser inteiro >= 0.")
            elif csv_ts_index and ts_str is not None:
                expected_idx = csv_ts_index.get(str(ts_str))
                if expected_idx is None:
                    errors.append(
                        f"{prefix}.timestamp_utc: nao encontrado em coluna "
                        f"timestamp_utc do CSV."
                    )
                elif expected_idx != candle_idx:
                    errors.append(
                        f"{prefix}.candle_idx: incoerente com CSV. "
                        f"esperado={expected_idx} recebido={candle_idx}."
                    )

        shot_id = event.get("screenshot_id")
        if shot_id is not None:
            if not isinstance(shot_id, str):
                errors.append(f"{prefix}.screenshot_id: deve ser string.")
            elif known_screenshot_ids and shot_id not in known_screenshot_ids:
                errors.append(
                    f"{prefix}.screenshot_id: {shot_id!r} nao referenciado "
                    f"na lista screenshots."
                )

        if evt_type in OB_FORMED_EVENTS:
            top = event.get("ob_top")
            bottom = event.get("ob_bottom")
            if top is None or bottom is None:
                errors.append(f"{prefix}: ob_top e ob_bottom obrigatorios em eventos OB formed.")
            elif not isinstance(top, (int, float)) or not isinstance(bottom, (int, float)):
                errors.append(f"{prefix}: ob_top e ob_bottom devem ser numericos.")
            elif top <= bottom:
                errors.append(f"{prefix}: ob_top ({top}) deve ser > ob_bottom ({bottom}).")

        if evt_type in FVG_FORMED_EVENTS:
            top = event.get("fvg_top")
            bottom = event.get("fvg_bottom")
            if top is None or bottom is None:
                errors.append(f"{prefix}: fvg_top e fvg_bottom obrigatorios em eventos FVG formed.")
            elif not isinstance(top, (int, float)) or not isinstance(bottom, (int, float)):
                errors.append(f"{prefix}: fvg_top e fvg_bottom devem ser numericos.")
            elif top <= bottom:
                errors.append(f"{prefix}: fvg_top ({top}) deve ser > fvg_bottom ({bottom}).")

        if evt_type in EQ_ALERT_EVENTS:
            level = event.get("level")
            if level is None:
                errors.append(f"{prefix}: level obrigatorio em alertas EQH/EQL.")
            elif not isinstance(level, (int, float)):
                errors.append(f"{prefix}: level deve ser numerico.")

    return errors


def _check_zones_block(
    zones: list,
    window_start: datetime | None,
    window_end: datetime | None,
    known_screenshot_ids: set[str],
) -> list[str]:
    errors: list[str] = []
    if not isinstance(zones, list):
        return ["zones: deve ser uma lista."]

    for i, zone in enumerate(zones):
        prefix = f"zones[{i}]"
        if not isinstance(zone, dict):
            errors.append(f"{prefix}: deve ser objeto.")
            continue
        for field in REQUIRED_ZONE_FIELDS:
            if field not in zone:
                errors.append(f"{prefix}.{field}: campo obrigatorio ausente.")

        zt = zone.get("zone_type")
        if zt is not None and zt not in ZONE_TYPES:
            errors.append(f"{prefix}.zone_type: valor desconhecido {zt!r}.")

        vf = _parse_iso(zone.get("valid_from_utc")) if isinstance(zone.get("valid_from_utc"), str) else None
        vu = _parse_iso(zone.get("valid_until_utc")) if isinstance(zone.get("valid_until_utc"), str) else None
        if zone.get("valid_from_utc") is not None and vf is None:
            errors.append(f"{prefix}.valid_from_utc: ISO 8601 UTC invalido.")
        if zone.get("valid_until_utc") is not None and vu is None:
            errors.append(f"{prefix}.valid_until_utc: ISO 8601 UTC invalido.")
        if vf and vu and vf > vu:
            errors.append(f"{prefix}: valid_from_utc deve ser <= valid_until_utc.")
        if window_start and window_end:
            if vf and (vf < window_start or vf > window_end):
                errors.append(f"{prefix}.valid_from_utc: fora da janela.")
            if vu and (vu < window_start or vu > window_end):
                errors.append(f"{prefix}.valid_until_utc: fora da janela.")

        upper = zone.get("upper_bound")
        lower = zone.get("lower_bound")
        if upper is not None and lower is not None:
            if not isinstance(upper, (int, float)) or not isinstance(lower, (int, float)):
                errors.append(f"{prefix}: upper_bound e lower_bound devem ser numericos.")
            elif upper <= lower:
                errors.append(f"{prefix}: upper_bound ({upper}) deve ser > lower_bound ({lower}).")

        sid = zone.get("screenshot_id")
        if isinstance(sid, str) and known_screenshot_ids and sid not in known_screenshot_ids:
            errors.append(
                f"{prefix}.screenshot_id: {sid!r} nao referenciado na lista screenshots."
            )

    return errors


def _check_screenshots_block(
    shots: list,
    window_start: datetime | None,
    window_end: datetime | None,
) -> tuple[list[str], set[str], list[tuple[datetime, datetime]]]:
    errors: list[str] = []
    seen_ids: set[str] = set()
    intervals: list[tuple[datetime, datetime]] = []
    if not isinstance(shots, list):
        return ["screenshots: deve ser uma lista."], seen_ids, intervals

    for i, shot in enumerate(shots):
        prefix = f"screenshots[{i}]"
        if not isinstance(shot, dict):
            errors.append(f"{prefix}: deve ser objeto.")
            continue
        for field in REQUIRED_SHOT_FIELDS:
            if field not in shot:
                errors.append(f"{prefix}.{field}: campo obrigatorio ausente.")

        sid = shot.get("screenshot_id")
        if isinstance(sid, str):
            if sid in seen_ids:
                errors.append(f"{prefix}.screenshot_id: id duplicado {sid!r}.")
            seen_ids.add(sid)

        start = _parse_iso(shot.get("candle_range_start_utc")) if isinstance(shot.get("candle_range_start_utc"), str) else None
        end = _parse_iso(shot.get("candle_range_end_utc")) if isinstance(shot.get("candle_range_end_utc"), str) else None
        if shot.get("candle_range_start_utc") is not None and start is None:
            errors.append(f"{prefix}.candle_range_start_utc: ISO 8601 UTC invalido.")
        if shot.get("candle_range_end_utc") is not None and end is None:
            errors.append(f"{prefix}.candle_range_end_utc: ISO 8601 UTC invalido.")
        if start and end:
            if start > end:
                errors.append(f"{prefix}: candle_range_start_utc deve ser <= candle_range_end_utc.")
            if window_start and window_end:
                if start < window_start or end > window_end:
                    errors.append(f"{prefix}: range fora da janela do golden.")
            intervals.append((start, end))

        cc = shot.get("candle_count")
        if cc is not None and (not isinstance(cc, int) or isinstance(cc, bool) or cc < 1):
            errors.append(f"{prefix}.candle_count: deve ser inteiro >= 1.")

    sorted_intervals = sorted(intervals, key=lambda x: x[0])
    for prev, nxt in zip(sorted_intervals, sorted_intervals[1:]):
        if nxt[0] < prev[1]:
            errors.append(
                f"screenshots: sobreposicao temporal detectada entre "
                f"intervalos {prev[0].isoformat()}..{prev[1].isoformat()} e "
                f"{nxt[0].isoformat()}..{nxt[1].isoformat()}."
            )

    if window_start and window_end and sorted_intervals:
        total_window_seconds = (window_end - window_start).total_seconds()
        coverage_seconds = sum((b - a).total_seconds() for a, b in sorted_intervals)
        if total_window_seconds > 0:
            ratio = coverage_seconds / total_window_seconds
            if ratio < 0.9:
                errors.append(
                    f"screenshots: cobertura {ratio:.1%} < 90% da janela total. "
                    f"Adicione mais screenshots ou estenda os intervalos."
                )

    return errors, seen_ids, intervals


def validate(golden_path: Path, csv_path: Path) -> ValidationResult:
    golden_path = Path(golden_path)
    csv_path = Path(csv_path)
    errors: list[str] = []

    if not golden_path.exists():
        return ValidationResult(False, [f"Golden nao encontrado em {golden_path}."])

    try:
        golden = json.loads(golden_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return ValidationResult(False, [f"JSON invalido: {exc}."])

    if not isinstance(golden, dict):
        return ValidationResult(False, ["Golden raiz deve ser objeto JSON."])

    for top in ("meta", "events", "zones"):
        if top not in golden:
            errors.append(f"Campo raiz obrigatorio ausente: {top}.")

    meta = golden.get("meta", {})
    meta_errors, window_start, window_end = _check_meta_block(meta if isinstance(meta, dict) else {})
    errors.extend(meta_errors)

    csv_df, csv_errors = _load_csv(csv_path)
    errors.extend(csv_errors)

    expected_sha = meta.get("ohlcv_csv_sha256") if isinstance(meta, dict) else None
    if isinstance(expected_sha, str) and SHA256_RE.match(expected_sha):
        hash_err = _check_csv_hash(csv_path, expected_sha)
        if hash_err:
            errors.append(hash_err)

    shots = golden.get("screenshots", [])
    shot_errors, known_ids, _ = _check_screenshots_block(shots, window_start, window_end)
    errors.extend(shot_errors)

    events = golden.get("events", [])
    errors.extend(
        _check_events_block(events, csv_df, window_start, window_end, known_ids)
    )

    zones = golden.get("zones", [])
    errors.extend(_check_zones_block(zones, window_start, window_end, known_ids))

    return ValidationResult(len(errors) == 0, errors)


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Valida golden dataset SMC.")
    parser.add_argument("--golden", required=True, help="Caminho do JSON do golden.")
    parser.add_argument("--csv", required=True, help="Caminho do CSV de OHLCV.")
    args = parser.parse_args(argv)

    result = validate(Path(args.golden), Path(args.csv))
    if result.is_valid:
        print("OK: golden valido.")
        return 0
    print("FAIL: golden invalido. Erros:")
    for err in result.errors:
        print(f"  - {err}")
    return 1


if __name__ == "__main__":
    sys.exit(_main())
