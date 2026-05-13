"""
OBJETIVO
    Rodar pipeline Onda 3 (pivots) → Onda 8 (liquidity sweeps) sobre o
    golden CSV (BTC-USDT-SWAP 4H, 2026-01-01 → 2026-04-30) e
    serializar todos os eventos em JSON ratificável.

    Output destinado a spot-check visual contra screenshots do Pine
    `Liquidity Sweeps [LuxAlgo]` no TradingView.

FONTE DE DADOS
    smc_freqtrade/tests/golden/data/btc_usdt_swap_4h_window.csv
    Hash esperado: 1a3f746cfe6095ad544c46c66e1500306627ea5224cdc3708ef994af2b3ef3fa

LIMITAÇÕES CONHECIDAS
    - Pipeline executa apenas Onda 3 e Onda 8 — Ondas 4-7 não rodam,
      logo `qualify_with_pd_zone=False` (default).
    - Output não é o golden JSON canônico (golden cobre apenas Ondas
      1-7 conforme Mapa Camada 1 §7). É arquivo de trabalho.
    - Cleanup do detector remove pivots `tak=True` no mesmo candle
      → eventos `*_retest` aparecem mas SEM mitigação registrada
      (comportamento idêntico ao Pine).

NÃO FAZER
    - Não modificar o golden CSV.
    - Não importar de smc_freqtrade.* (raiz é smc_engine).
    - Não rodar pytest aqui — é script standalone.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import pandas as pd

# Adicionar smc_freqtrade ao path para imports relativos
sys.path.insert(0, str(Path(__file__).parent.parent))

from smc_engine import (
    detect_pivots,
    detect_liquidity_sweeps,
    COL_SWEEP_BULLISH_WICK,
    COL_SWEEP_BEARISH_WICK,
    COL_SWEEP_BULLISH_RETEST,
    COL_SWEEP_BEARISH_RETEST,
    COL_SWEEP_BULLISH_LEVEL_IDX,
    COL_SWEEP_BEARISH_LEVEL_IDX,
    COL_SWEEP_BULLISH_LEVEL_PRICE,
    COL_SWEEP_BEARISH_LEVEL_PRICE,
    COL_SWEEP_BULLISH_MITIGATED,
    COL_SWEEP_BEARISH_MITIGATED,
)


EXPECTED_HASH = "1a3f746cfe6095ad544c46c66e1500306627ea5224cdc3708ef994af2b3ef3fa"


def verify_hash(csv_path: Path) -> str:
    """Compute sha256 of CSV; return hash. Não falha se diferente —
    apenas reporta no JSON de saída."""
    h = hashlib.sha256()
    with csv_path.open('rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()


def load_csv(csv_path: Path) -> pd.DataFrame:
    """Carrega CSV e normaliza columns para OHLCV minúsculos.
    Detecta automaticamente timestamp column (date/timestamp/time)."""
    df = pd.read_csv(csv_path)
    # Normaliza columns
    df.columns = [c.lower() for c in df.columns]
    # Detecta timestamp
    ts_col = next(
        (
            c
            for c in (
                'date',
                'timestamp',
                'timestamp_utc',
                'time',
                'datetime',
            )
            if c in df.columns
        ),
        None,
    )
    if ts_col is None:
        raise ValueError(
            f"CSV sem coluna de timestamp; columns={list(df.columns)}"
        )
    df['timestamp'] = pd.to_datetime(df[ts_col], utc=True)
    return df


def collect_events(df: pd.DataFrame) -> list[dict]:
    """Itera o df com colunas Onda 8 aplicadas e coleta cada evento
    de sweep em uma lista de dicts. Ordem: bullish_wick,
    bearish_wick, bullish_retest, bearish_retest, e respectivas
    mitigações."""
    events: list[dict] = []

    def _ts(t: int) -> str:
        return df['timestamp'].iloc[t].isoformat()

    for t in range(len(df)):
        # Sweep events
        if bool(df[COL_SWEEP_BULLISH_WICK].iloc[t]):
            events.append({
                "type": "sweep_bullish_wick",
                "sweep_idx": int(t),
                "sweep_timestamp": _ts(t),
                "level_price": float(df[COL_SWEEP_BULLISH_LEVEL_PRICE].iloc[t]),
                "level_idx": int(df[COL_SWEEP_BULLISH_LEVEL_IDX].iloc[t]),
                "level_timestamp": _ts(int(df[COL_SWEEP_BULLISH_LEVEL_IDX].iloc[t])),
                "candle_high": float(df['high'].iloc[t]),
                "candle_low": float(df['low'].iloc[t]),
                "candle_close": float(df['close'].iloc[t]),
            })
        if bool(df[COL_SWEEP_BEARISH_WICK].iloc[t]):
            events.append({
                "type": "sweep_bearish_wick",
                "sweep_idx": int(t),
                "sweep_timestamp": _ts(t),
                "level_price": float(df[COL_SWEEP_BEARISH_LEVEL_PRICE].iloc[t]),
                "level_idx": int(df[COL_SWEEP_BEARISH_LEVEL_IDX].iloc[t]),
                "level_timestamp": _ts(int(df[COL_SWEEP_BEARISH_LEVEL_IDX].iloc[t])),
                "candle_high": float(df['high'].iloc[t]),
                "candle_low": float(df['low'].iloc[t]),
                "candle_close": float(df['close'].iloc[t]),
            })
        if bool(df[COL_SWEEP_BULLISH_RETEST].iloc[t]):
            events.append({
                "type": "sweep_bullish_retest",
                "sweep_idx": int(t),
                "sweep_timestamp": _ts(t),
                "level_price": float(df[COL_SWEEP_BULLISH_LEVEL_PRICE].iloc[t]),
                "level_idx": int(df[COL_SWEEP_BULLISH_LEVEL_IDX].iloc[t]),
                "level_timestamp": _ts(int(df[COL_SWEEP_BULLISH_LEVEL_IDX].iloc[t])),
                "candle_high": float(df['high'].iloc[t]),
                "candle_low": float(df['low'].iloc[t]),
                "candle_close": float(df['close'].iloc[t]),
            })
        if bool(df[COL_SWEEP_BEARISH_RETEST].iloc[t]):
            events.append({
                "type": "sweep_bearish_retest",
                "sweep_idx": int(t),
                "sweep_timestamp": _ts(t),
                "level_price": float(df[COL_SWEEP_BEARISH_LEVEL_PRICE].iloc[t]),
                "level_idx": int(df[COL_SWEEP_BEARISH_LEVEL_IDX].iloc[t]),
                "level_timestamp": _ts(int(df[COL_SWEEP_BEARISH_LEVEL_IDX].iloc[t])),
                "candle_high": float(df['high'].iloc[t]),
                "candle_low": float(df['low'].iloc[t]),
                "candle_close": float(df['close'].iloc[t]),
            })
        # Mitigation events (apenas wicks geram mitigação — vide cleanup)
        if bool(df[COL_SWEEP_BULLISH_MITIGATED].iloc[t]):
            events.append({
                "type": "mitigation_bullish_sweep_area",
                "mitigation_idx": int(t),
                "mitigation_timestamp": _ts(t),
                "candle_close": float(df['close'].iloc[t]),
            })
        if bool(df[COL_SWEEP_BEARISH_MITIGATED].iloc[t]):
            events.append({
                "type": "mitigation_bearish_sweep_area",
                "mitigation_idx": int(t),
                "mitigation_timestamp": _ts(t),
                "candle_close": float(df['close'].iloc[t]),
            })

    return events


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--csv', required=True,
        help='Path absoluto ou relativo ao golden CSV',
    )
    parser.add_argument(
        '--output',
        default='smc_freqtrade/tests/golden/sweeps_engine_output.json',
        help='Path do JSON de saída',
    )
    args = parser.parse_args()

    csv_path = Path(args.csv).resolve()
    output_path = Path(args.output).resolve()

    if not csv_path.exists():
        print(f"ERROR: CSV não encontrado em {csv_path}", file=sys.stderr)
        return 1

    actual_hash = verify_hash(csv_path)
    hash_match = (actual_hash == EXPECTED_HASH)

    print(f"CSV path: {csv_path}")
    print(f"CSV hash: {actual_hash}")
    print(f"Expected: {EXPECTED_HASH}")
    print(f"Match: {hash_match}")

    df = load_csv(csv_path)
    print(f"Candles loaded: {len(df)}")
    print(f"Range: {df['timestamp'].iloc[0]} → {df['timestamp'].iloc[-1]}")

    # Pipeline: Onda 3 → Onda 8
    df = detect_pivots(df)
    df = detect_liquidity_sweeps(df)

    events = collect_events(df)

    # Stats
    type_counts: dict[str, int] = {}
    for ev in events:
        type_counts[ev['type']] = type_counts.get(ev['type'], 0) + 1

    output = {
        "meta": {
            "source_csv": str(csv_path),
            "csv_hash": actual_hash,
            "hash_match_expected": hash_match,
            "candle_count": int(len(df)),
            "first_candle": df['timestamp'].iloc[0].isoformat(),
            "last_candle": df['timestamp'].iloc[-1].isoformat(),
            "engine_version": "smc_freqtrade VERSION 0.7.0 (Onda 8 mergeada, bump pendente)",
            "detector_params": {
                "pivot_sources": ["equal", "internal"],
                "sweep_max_extension_bars": 300,
                "sweep_max_pivot_age_bars": 2000,
                "qualify_with_pd_zone": False,
            },
            "event_counts": type_counts,
            "total_events": len(events),
        },
        "events": events,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open('w') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\nOutput written to: {output_path}")
    print(f"Total events: {len(events)}")
    print(f"Breakdown:")
    for k, v in sorted(type_counts.items()):
        print(f"  {k}: {v}")

    return 0


if __name__ == '__main__':
    sys.exit(main())
