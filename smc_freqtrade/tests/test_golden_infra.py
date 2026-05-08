"""
OBJETIVO
    Smoke test da infra do golden dataset:
    1. README existe e tem cabecalho esperado.
    2. Schema JSON e parseavel.
    3. Validador roda contra esqueleto do golden e detecta os PLACEHOLDERs
       como erros (sanity -- validador funciona).
    4. Validador roda contra um golden artificial valido (criado em fixture)
       e retorna sucesso.
    5. ohlcv_fetcher.py e importavel sem efeitos colaterais.

FONTE DE DADOS
    - Arquivos do PR (tests/golden/**)
    - Fixture interna criada no proprio teste

LIMITACOES CONHECIDAS
    - NAO faz fetch real de OHLCV (sem rede no CI).
    - NAO valida correcao semantica de eventos (escopo das ondas 5+).

NAO FAZER
    - Nao chamar OKX API.
    - Nao rodar a engine SMC.
    - Nao escrever em diretorios fora do tmp_path do pytest.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
GOLDEN_DIR = REPO_ROOT / "tests" / "golden"
TOOLS_DIR = GOLDEN_DIR / "tools"
SCHEMA_PATH = GOLDEN_DIR / "schema" / "golden_schema.json"
README_PATH = GOLDEN_DIR / "README.md"
SKELETON_PATH = GOLDEN_DIR / "golden" / "btc_usdt_swap_4h_luxalgo_smc.json"
SKELETON_CSV_PATH = GOLDEN_DIR / "data" / "btc_usdt_swap_4h_window.csv"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def validator_module():
    return _load_module("_golden_validator", TOOLS_DIR / "golden_validator.py")


def _make_csv(path: Path, n_candles: int = 10, start_iso: str = "2026-01-08T00:00:00Z") -> str:
    start_dt = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
    rows = ["timestamp_utc,open,high,low,close,volume"]
    for i in range(n_candles):
        ts = (start_dt + timedelta(hours=4 * i)).strftime("%Y-%m-%dT%H:%M:%SZ")
        base = 100.0 + i
        rows.append(f"{ts},{base},{base + 1},{base - 1},{base + 0.5},10")
    body = "\n".join(rows) + "\n"
    path.write_text(body, encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _minimal_meta(window_start: str, window_end: str, sha: str) -> dict:
    return {
        "indicator": "LuxAlgo - Smart Money Concepts",
        "indicator_version": "free-2024-09-01",
        "tradingview_timezone": "UTC",
        "instrument": "BTC-USDT-SWAP",
        "exchange": "OKX",
        "timeframe": "4h",
        "window_start_utc": window_start,
        "window_end_utc": window_end,
        "ohlcv_csv_sha256": sha,
        "extracted_by": "Marcelo (fixture)",
        "structured_by": "Claude Code (fixture)",
        "produced_at_utc": "2026-05-08T10:00:00Z",
        "scope_included": ["BOS"],
        "scope_excluded": ["pivots por candle"],
        "match_tolerance_candles": 1,
    }


def _build_valid_golden(tmp_path: Path) -> tuple[Path, Path]:
    csv_path = tmp_path / "ohlcv.csv"
    sha = _make_csv(csv_path, n_candles=10, start_iso="2026-01-08T00:00:00Z")
    window_start = "2026-01-08T00:00:00Z"
    window_end = "2026-01-09T12:00:00Z"
    golden = {
        "meta": _minimal_meta(window_start, window_end, sha),
        "screenshots": [
            {
                "screenshot_id": "shot_01",
                "candle_range_start_utc": window_start,
                "candle_range_end_utc": window_end,
                "candle_count": 10,
            }
        ],
        "events": [
            {
                "event_type": "bos_bullish_swing",
                "timestamp_utc": "2026-01-08T20:00:00Z",
                "candle_idx": 5,
                "screenshot_id": "shot_01",
                "level": 105.0,
            }
        ],
        "zones": [
            {
                "zone_type": "premium",
                "screenshot_id": "shot_01",
                "valid_from_utc": window_start,
                "valid_until_utc": window_end,
                "upper_bound": 110.0,
                "lower_bound": 105.0,
            }
        ],
    }
    golden_path = tmp_path / "golden.json"
    golden_path.write_text(json.dumps(golden), encoding="utf-8")
    return golden_path, csv_path


def test_readme_exists_and_has_header():
    assert README_PATH.exists(), "README.md ausente em tests/golden/."
    body = README_PATH.read_text(encoding="utf-8")
    for needle in ("LuxAlgo SMC gratuito", "UTC", "720", "tolerance"):
        assert needle.lower() in body.lower(), f"README sem termo obrigatorio: {needle!r}."


def test_schema_is_parseable():
    assert SCHEMA_PATH.exists()
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert schema["title"].startswith("SMC Golden Dataset Schema")
    assert "meta" in schema["properties"]
    assert "events" in schema["properties"]
    assert "zones" in schema["properties"]


def test_validator_rejects_skeleton(validator_module):
    result = validator_module.validate(SKELETON_PATH, SKELETON_CSV_PATH)
    assert result.is_valid is False
    joined = "\n".join(result.errors).upper()
    assert "PLACEHOLDER" in joined, (
        f"Validador deveria reportar PLACEHOLDER no esqueleto. "
        f"Erros recebidos: {result.errors}"
    )


def test_validator_accepts_minimal_valid_golden(tmp_path, validator_module):
    golden_path, csv_path = _build_valid_golden(tmp_path)
    result = validator_module.validate(golden_path, csv_path)
    assert result.is_valid, f"Esperado golden valido, erros: {result.errors}"


def test_validator_detects_event_outside_window(tmp_path, validator_module):
    golden_path, csv_path = _build_valid_golden(tmp_path)
    data = json.loads(golden_path.read_text(encoding="utf-8"))
    data["events"][0]["timestamp_utc"] = "2027-01-01T00:00:00Z"
    data["events"][0]["candle_idx"] = 0
    golden_path.write_text(json.dumps(data), encoding="utf-8")
    result = validator_module.validate(golden_path, csv_path)
    assert result.is_valid is False
    assert any("fora da janela" in e for e in result.errors), result.errors


def test_validator_detects_csv_hash_mismatch(tmp_path, validator_module):
    golden_path, csv_path = _build_valid_golden(tmp_path)
    data = json.loads(golden_path.read_text(encoding="utf-8"))
    data["meta"]["ohlcv_csv_sha256"] = "0" * 64
    golden_path.write_text(json.dumps(data), encoding="utf-8")
    result = validator_module.validate(golden_path, csv_path)
    assert result.is_valid is False
    assert any("hash nao bate" in e.lower() or "hash não bate" in e.lower() for e in result.errors), result.errors


def test_validator_detects_inverted_ob_bounds(tmp_path, validator_module):
    golden_path, csv_path = _build_valid_golden(tmp_path)
    data = json.loads(golden_path.read_text(encoding="utf-8"))
    data["events"].append(
        {
            "event_type": "ob_bullish_swing_formed",
            "timestamp_utc": "2026-01-08T16:00:00Z",
            "candle_idx": 4,
            "screenshot_id": "shot_01",
            "ob_top": 100.0,
            "ob_bottom": 105.0,
        }
    )
    golden_path.write_text(json.dumps(data), encoding="utf-8")
    result = validator_module.validate(golden_path, csv_path)
    assert result.is_valid is False
    assert any("ob_top" in e and "ob_bottom" in e for e in result.errors), result.errors


def test_ohlcv_fetcher_importable(monkeypatch):
    calls: list[str] = []

    def fake_get(*args, **kwargs):
        calls.append(args[0] if args else kwargs.get("url", "?"))
        raise AssertionError("ohlcv_fetcher chamou requests.get em import-time.")

    try:
        import requests  # noqa: F401
        monkeypatch.setattr("requests.get", fake_get, raising=False)
    except ImportError:
        pass

    module = _load_module("_ohlcv_fetcher", TOOLS_DIR / "ohlcv_fetcher.py")
    assert hasattr(module, "fetch_window")
    assert hasattr(module, "write_csv")
    assert calls == [], f"Import causou chamadas HTTP: {calls}"
