"""Gerador engine-first do golden JSON.

OBJETIVO
    Rodar smc_engine.analyze() sobre o CSV golden, mapear o output
    para os 22 event_types canonicos do schema + 3 zone_types em
    zones[], e emitir JSON com meta.ratified=false conformante ao
    schema golden v1 (tests/golden/schema/golden_schema.json).

FONTE DE DADOS
    CSV golden: tests/golden/data/btc_usdt_swap_4h_window.csv
    (720 candles, colunas timestamp_utc,open,high,low,close,volume).

USO
    python tests/golden/tools/generate_golden_engine_output.py \\
        --csv tests/golden/data/btc_usdt_swap_4h_window.csv \\
        --output tests/golden/golden/btc_usdt_swap_4h_luxalgo_smc.engine_output.json \\
        [--validate]

    --validate (opcional): apos gerar, roda
    golden_validator.validate() contra o JSON produzido e o CSV
    de origem. Exit 0 se OK; exit 1 se invalido (mas JSON e
    sempre gravado independente).

LIMITACOES CONHECIDAS
    - Saida tem ratified=false sempre. Ratificacao e manual
      (PR separado).
    - screenshots[] sempre vazio (preenchido manualmente apos
      spot-check). screenshot_id de events/zones e string vazia.
    - volumetric_intensity dos OBs e omitido (sempre pd.NA na
      Onda 6; campo nao e exigido pelo schema).
    - Event field names seguem o schema canonico
      (bos_bullish_internal etc.), nao os column names do engine
      (bos_internal_bullish): mapper inverte scope<->bias.

NAO FAZER
    - Nao sobrescrever JSON canonico (tests/golden/golden/
      btc_usdt_swap_4h_luxalgo_smc.json) -- usar caminho de saida
      diferente por default.
    - Nao inferir ratified=true por nenhuma heuristica -- sempre
      false na geracao engine-first.
    - Nao chamar este script em testes automaticos -- e manual
      pelo operador humano.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

# Standalone CLI: garantir que smc_engine/ resolva quando rodado
# diretamente de fora do pacote (sem PYTHONPATH).
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from smc_engine import __version__, SMCConfig, analyze  # noqa: E402


BIAS_BULLISH = 1
BIAS_BEARISH = -1


def _read_csv(csv_path: Path) -> tuple[pd.DataFrame, list[str]]:
    """Le CSV golden e devolve (df, iso_strings).

    df tem colunas date (int epoch, unidade derivada do pandas em
    uso), open, high, low, close, volume -- pronto para analyze().
    iso_strings preserva as strings originais timestamp_utc do CSV,
    indexadas por candle_idx. Necessario para emitir timestamps
    bit-identicos ao que aparece no CSV (validador faz match
    exato de string).
    """
    raw = pd.read_csv(csv_path)
    iso_strings = raw['timestamp_utc'].astype(str).tolist()
    date_int = pd.to_datetime(raw['timestamp_utc'], utc=True).astype('int64') // 10**6
    df = pd.DataFrame({
        'date': date_int.astype('int64'),
        'open': raw['open'].astype('float64'),
        'high': raw['high'].astype('float64'),
        'low': raw['low'].astype('float64'),
        'close': raw['close'].astype('float64'),
        'volume': raw['volume'].astype('float64'),
    })
    return df, iso_strings


def _sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def _build_lookup(
    df: pd.DataFrame, iso_strings: list[str]
) -> dict[int, tuple[int, str]]:
    """date int -> (candle_idx, iso_string)."""
    return {
        int(d): (i, iso_strings[i]) for i, d in enumerate(df['date'].tolist())
    }


def _map_bos_choch_events(
    df: pd.DataFrame, lookup: dict[int, tuple[int, str]]
) -> list[dict[str, Any]]:
    """Mapeia as 8 colunas bos_/choch_ para 8 event_types do schema.

    Engine columns: bos_{scope}_{bias} (scope first).
    Schema event_type: bos_{bias}_{scope} (bias first).
    """
    events: list[dict[str, Any]] = []
    pairs = [
        ('bos_internal_bullish', 'bos_bullish_internal'),
        ('bos_internal_bearish', 'bos_bearish_internal'),
        ('bos_swing_bullish', 'bos_bullish_swing'),
        ('bos_swing_bearish', 'bos_bearish_swing'),
        ('choch_internal_bullish', 'choch_bullish_internal'),
        ('choch_internal_bearish', 'choch_bearish_internal'),
        ('choch_swing_bullish', 'choch_bullish_swing'),
        ('choch_swing_bearish', 'choch_bearish_swing'),
    ]
    for col_name, event_type in pairs:
        if col_name not in df.columns:
            continue
        mask = df[col_name].fillna(False).astype(bool)
        for idx in df.index[mask]:
            date_val = int(df['date'].iloc[idx])
            candle_idx, iso = lookup[date_val]
            events.append({
                'event_type': event_type,
                'timestamp_utc': iso,
                'candle_idx': candle_idx,
                'screenshot_id': '',
            })
    return events


def _map_ob_events(
    ledger_ob: pd.DataFrame, lookup: dict[int, tuple[int, str]]
) -> list[dict[str, Any]]:
    """Mapeia ledger_ob -> 8 event_types (formed + mitigated) x (bull/bear) x (internal/swing).

    OB top/bottom: ob_top = bar_high, ob_bottom = bar_low (sempre,
    independente do bias -- top > bottom por construcao).
    """
    events: list[dict[str, Any]] = []
    for _, row in ledger_ob.iterrows():
        scope = str(row['scope'])
        bias_int = int(row['bias'])
        bias_str = 'bullish' if bias_int == BIAS_BULLISH else 'bearish'

        t_creation = int(row['t_creation'])
        c_idx, c_iso = lookup[t_creation]
        events.append({
            'event_type': f'ob_{bias_str}_{scope}_formed',
            'timestamp_utc': c_iso,
            'candle_idx': c_idx,
            'screenshot_id': '',
            'ob_top': float(row['bar_high']),
            'ob_bottom': float(row['bar_low']),
        })

        if str(row['state']) == 'mitigated' and pd.notna(row['t_mitigation']):
            t_mit = int(row['t_mitigation'])
            m_idx, m_iso = lookup[t_mit]
            events.append({
                'event_type': f'ob_{bias_str}_{scope}_mitigated',
                'timestamp_utc': m_iso,
                'candle_idx': m_idx,
                'screenshot_id': '',
            })
    return events


def _map_fvg_events(
    ledger_fvg: pd.DataFrame, lookup: dict[int, tuple[int, str]]
) -> list[dict[str, Any]]:
    """Mapeia ledger_fvg -> 4 event_types (formed + mitigated) x (bull/bear)."""
    events: list[dict[str, Any]] = []
    for _, row in ledger_fvg.iterrows():
        bias_int = int(row['bias'])
        bias_str = 'bullish' if bias_int == BIAS_BULLISH else 'bearish'

        t_creation = int(row['t_creation'])
        c_idx, c_iso = lookup[t_creation]
        events.append({
            'event_type': f'fvg_{bias_str}_formed',
            'timestamp_utc': c_iso,
            'candle_idx': c_idx,
            'screenshot_id': '',
            'fvg_top': float(row['top']),
            'fvg_bottom': float(row['bottom']),
        })

        if str(row['state']) == 'mitigated' and pd.notna(row['t_mitigation']):
            t_mit = int(row['t_mitigation'])
            m_idx, m_iso = lookup[t_mit]
            events.append({
                'event_type': f'fvg_{bias_str}_mitigated',
                'timestamp_utc': m_iso,
                'candle_idx': m_idx,
                'screenshot_id': '',
            })
    return events


def _map_eq_events(
    df: pd.DataFrame, lookup: dict[int, tuple[int, str]]
) -> list[dict[str, Any]]:
    """Mapeia equal_high_alert/equal_low_alert -> eqh_alert/eql_alert."""
    events: list[dict[str, Any]] = []
    pairs = [
        ('equal_high_alert', 'eqh_alert', 'high'),
        ('equal_low_alert', 'eql_alert', 'low'),
    ]
    for col_name, event_type, price_col in pairs:
        if col_name not in df.columns:
            continue
        mask = df[col_name].fillna(False).astype(bool)
        for idx in df.index[mask]:
            date_val = int(df['date'].iloc[idx])
            candle_idx, iso = lookup[date_val]
            events.append({
                'event_type': event_type,
                'timestamp_utc': iso,
                'candle_idx': candle_idx,
                'screenshot_id': '',
                'level': float(df[price_col].iloc[idx]),
            })
    return events


def _map_pd_zones(
    df: pd.DataFrame, lookup: dict[int, tuple[int, str]]
) -> list[dict[str, Any]]:
    """Agrupa pd_zone candle-a-candle em zones[] do schema.

    Sequencias contiguas com mesmo pd_zone viram uma zone:
      valid_from_utc  = primeiro candle do trecho (ISO string CSV)
      valid_until_utc = ultimo candle do trecho   (ISO string CSV)
      upper_bound     = max(trailing_top) no trecho
      lower_bound     = min(trailing_bottom) no trecho
    pd_zone == NA interrompe a sequencia.
    """
    if 'pd_zone' not in df.columns:
        return []

    zones: list[dict[str, Any]] = []
    current_zone: str | None = None
    current_from_idx: int | None = None

    def _close(end_idx: int) -> None:
        assert current_zone is not None and current_from_idx is not None
        seq = df.iloc[current_from_idx:end_idx + 1]
        _, iso_from = lookup[int(df['date'].iloc[current_from_idx])]
        _, iso_until = lookup[int(df['date'].iloc[end_idx])]
        zones.append({
            'zone_type': current_zone,
            'screenshot_id': '',
            'valid_from_utc': iso_from,
            'valid_until_utc': iso_until,
            'upper_bound': float(seq['trailing_top'].max()),
            'lower_bound': float(seq['trailing_bottom'].min()),
        })

    for idx in range(len(df)):
        zone_val = df['pd_zone'].iloc[idx]
        is_na = pd.isna(zone_val)
        if is_na:
            if current_zone is not None:
                _close(idx - 1)
                current_zone = None
                current_from_idx = None
        else:
            zone_str = str(zone_val)
            if current_zone is None:
                current_zone = zone_str
                current_from_idx = idx
            elif zone_str != current_zone:
                _close(idx - 1)
                current_zone = zone_str
                current_from_idx = idx

    if current_zone is not None and current_from_idx is not None:
        _close(len(df) - 1)

    return zones


def build_golden_json(
    df: pd.DataFrame,
    iso_strings: list[str],
    csv_path: Path,
    config: SMCConfig | None = None,
) -> dict[str, Any]:
    """Roda analyze() e monta dict completo conforme schema canonico."""
    if config is None:
        config = SMCConfig()

    result = analyze(df, config=config)
    lookup = _build_lookup(result.df, iso_strings)

    events: list[dict[str, Any]] = []
    events.extend(_map_bos_choch_events(result.df, lookup))
    events.extend(_map_ob_events(result.ledger_ob, lookup))
    events.extend(_map_fvg_events(result.ledger_fvg, lookup))
    events.extend(_map_eq_events(result.df, lookup))
    events.sort(key=lambda e: (e['candle_idx'], e['event_type']))

    zones = _map_pd_zones(result.df, lookup)

    csv_sha = _sha256_of_file(csv_path)
    window_start = iso_strings[0]
    window_end = iso_strings[-1]
    produced = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

    return {
        'meta': {
            'indicator': 'smc_engine (LuxAlgo-aligned, engine-first)',
            'indicator_version': f'engine v{__version__}',
            'tradingview_timezone': 'UTC',
            'instrument': 'BTC-USDT-SWAP',
            'exchange': 'OKX',
            'timeframe': '4h',
            'window_start_utc': window_start,
            'window_end_utc': window_end,
            'ohlcv_csv_sha256': csv_sha,
            'extracted_by': f'smc_engine.analyze() v{__version__}',
            'structured_by': 'smc_engine engine-first; spot-check pendente',
            'ratified': False,
            'ratification_notes': '',
            'produced_at_utc': produced,
            'scope_included': [
                'BOS bullish/bearish (internal e swing)',
                'CHoCH bullish/bearish (internal e swing)',
                'OB formacao e mitigacao (internal e swing)',
                'FVG formacao e mitigacao',
                'EQH/EQL alerts',
                'Premium/Discount/Equilibrium zones',
            ],
            'scope_excluded': [
                'Swing/internal/equal pivots por candle (validados por testes sinteticos na Onda 3)',
                'CHoCH+ (feature do LuxAlgo Price Action Concepts pago, ausente no gratuito)',
                'Volumetric OB metrics (idem)',
                'Breaker Blocks (idem)',
                'Liquidity Grabs (idem; sera abordado na Onda 8 com regra propria)',
                'Liquidity Trendlines (idem)',
                'Chart Patterns (idem)',
                'Inverse FVG e Double FVG (idem)',
                'Volume Imbalance e Opening Gap (irrelevantes para perpetual swap 24/7)',
            ],
            'match_tolerance_candles': 1,
        },
        'screenshots': [],
        'events': events,
        'zones': zones,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Gera golden JSON candidato via smc_engine.analyze().'
    )
    parser.add_argument('--csv', type=Path, required=True,
                        help='Caminho do CSV golden de entrada')
    parser.add_argument('--output', type=Path, required=True,
                        help='Caminho do JSON de saida')
    parser.add_argument('--validate', action='store_true',
                        help='Roda golden_validator.validate() apos gerar')
    args = parser.parse_args()

    if not args.csv.exists():
        print(f"ERROR: CSV nao encontrado: {args.csv}", file=sys.stderr)
        return 1

    print(f"Lendo CSV: {args.csv}", file=sys.stderr)
    df, iso_strings = _read_csv(args.csv)
    print(f"  {len(df)} candles carregados", file=sys.stderr)

    print("Rodando analyze()...", file=sys.stderr)
    golden = build_golden_json(df, iso_strings, args.csv)
    print(
        f"  {len(golden['events'])} events, {len(golden['zones'])} zones gerados",
        file=sys.stderr,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(golden, f, indent=2, ensure_ascii=False)
    print(f"JSON escrito em: {args.output}", file=sys.stderr)

    if args.validate:
        print("Validando contra schema...", file=sys.stderr)
        sys.path.insert(0, str(Path(__file__).parent))
        from golden_validator import validate
        result_v = validate(args.output, args.csv)
        if result_v.is_valid:
            print("OK: golden valido.")
            return 0
        print("FAIL: golden invalido. Erros:")
        for err in result_v.errors:
            print(f"  - {err}")
        return 1

    return 0


if __name__ == '__main__':
    sys.exit(main())
