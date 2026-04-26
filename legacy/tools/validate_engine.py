#!/usr/bin/env python3
# SMC Monitor — tools/validate_engine.py
# Versão: 0.1.0

"""
OBJETIVO: Validar consistência conceitual entre smc_engine.py (implementação
          própria, streaming incremental) e biblioteca smartmoneyconcepts
          (referência batch) alimentadas com os mesmos dados históricos reais
          do BTC-USDT-SWAP da OKX.

FONTE DE DADOS: OKX REST API endpoint /api/v5/market/history-candles para
                timeframes 15m, 1H e 4H (últimos ~500 candles por TF).

LIMITAÇÕES CONHECIDAS:
  - Tool de desenvolvimento — não é código de produção.
  - smartmoneyconcepts é dependência APENAS deste script.
  - Divergências esperadas entre as duas implementações (ver análise
    comparativa no relatório). Objetivo é quantificar, não garantir match.
  - OKX history-candles limita 100 candles por request — script pagina com
    parâmetro `after` para buscar 500 candles.
  - Tolerância temporal de ±2 candles para localização de OBs/FVGs entre
    as duas implementações (já que index absoluto difere por buffer).

NÃO FAZER:
  - Não alterar módulos de produção.
  - Não escrever em banco SQLite de produção.
  - Não enviar notificações Telegram.
  - Não ir para requirements.txt de produção.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

# Garantir que o script encontra smc_engine.py e config.py do projeto
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    import numpy as np
    import pandas as pd
    import requests
except ImportError as e:
    print(f"[FATAL] Dependência faltando: {e}", file=sys.stderr)
    print("        Instalar com: pip install numpy pandas requests --break-system-packages",
          file=sys.stderr)
    sys.exit(1)

try:
    from smartmoneyconcepts import smc as lib_smc  # type: ignore
except ImportError:
    print("[FATAL] Biblioteca smartmoneyconcepts não encontrada.", file=sys.stderr)
    print("        Instalar com: pip install smartmoneyconcepts --break-system-packages",
          file=sys.stderr)
    sys.exit(1)

try:
    import config  # projeto
    from smc_engine import SMCEngine  # projeto
except ImportError as e:
    print(f"[FATAL] Não foi possível importar módulos do projeto: {e}", file=sys.stderr)
    print(f"        Esperado PROJECT_ROOT={PROJECT_ROOT}", file=sys.stderr)
    sys.exit(1)


# ─── Parâmetros da validação ──────────────────────────────────────────────────

OKX_BASE_URL = "https://www.okx.com"
INSTRUMENT = "BTC-USDT-SWAP"
TIMEFRAMES = ["15m", "1H", "4H"]
TARGET_CANDLES = 500
OKX_BATCH_LIMIT = 100

# Tolerância temporal para considerar dois OBs/FVGs "equivalentes"
OB_FVG_TIME_TOLERANCE_CANDLES = 2


# ─── Coleta de dados da OKX ────────────────────────────────────────────────────

def fetch_okx_history(inst_id: str, bar: str, target: int) -> List[dict]:
    """
    Busca `target` candles históricos via endpoint REST history-candles.
    Pagina usando parâmetro `after` (timestamp do candle mais antigo recebido).
    Retorna lista oldest → newest com dicts {ts, open, high, low, close, volume}.
    """
    collected: List[list] = []
    after_ts: str | None = None

    while len(collected) < target:
        remaining = target - len(collected)
        limit = min(OKX_BATCH_LIMIT, remaining)

        params: Dict[str, Any] = {
            "instId": inst_id,
            "bar": bar,
            "limit": str(limit),
        }
        if after_ts is not None:
            params["after"] = after_ts

        url = f"{OKX_BASE_URL}/api/v5/market/history-candles"
        try:
            resp = requests.get(url, params=params, timeout=15)
            resp.raise_for_status()
            payload = resp.json()
        except (requests.RequestException, ValueError) as exc:
            print(f"  [ERROR] Falha ao buscar {bar}: {exc}", file=sys.stderr)
            break

        if payload.get("code") != "0":
            print(f"  [ERROR] OKX retornou code={payload.get('code')} msg={payload.get('msg')}",
                  file=sys.stderr)
            break

        batch = payload.get("data", [])
        if not batch:
            break

        # OKX retorna newest → oldest; append como veio, vamos ordenar no final
        collected.extend(batch)
        # próximo `after` = timestamp do candle mais antigo deste batch
        after_ts = batch[-1][0]

        # cortesia com o rate limit
        time.sleep(0.25)

    # Ordenar oldest → newest e normalizar para dicts
    # Formato: [ts, open, high, low, close, vol, volCcy, volCcyQuote, confirm]
    collected.sort(key=lambda row: int(row[0]))

    candles: List[dict] = []
    for row in collected[:target]:
        try:
            candles.append({
                "ts": int(row[0]),
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5]),
            })
        except (ValueError, IndexError, TypeError):
            continue

    return candles


# ─── Conversões ────────────────────────────────────────────────────────────────

def candles_to_dataframe(candles: List[dict]) -> pd.DataFrame:
    """Converte lista de candles em DataFrame no formato esperado pela lib."""
    df = pd.DataFrame(candles)
    df["datetime"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    df = df.set_index("datetime")
    return df[["open", "high", "low", "close", "volume"]]


# ─── Execução do smc_engine sobre candles (simula streaming) ──────────────────

def run_project_engine(
    candles: List[dict],
    timeframe: str,
    token: str = INSTRUMENT,
) -> Dict[str, Any]:
    """
    Alimenta o SMCEngine candle-a-candle simulando o WebSocket feed,
    capturando o estado a cada candle e consolidando os artefatos gerados.
    """
    engine = SMCEngine()

    # Coletas acumulativas (capturamos snapshots ao longo do stream)
    all_obs_seen: Dict[Tuple[int, str], dict] = {}
    all_fvgs_seen: Dict[Tuple[int, str], dict] = {}
    bos_events: List[dict] = []
    last_seen_bos_ts: int | None = None

    for candle in candles:
        engine.on_candle(token, timeframe, candle)

    # Após o stream, também capturamos "tudo que já foi visto" percorrendo o
    # buffer final mais uma vez — mas o engine só guarda estado current.
    # Então reprocessamos em passes para coletar tudo que apareceu:
    engine2 = SMCEngine()
    for candle in candles:
        engine2.on_candle(token, timeframe, candle)
        state = engine2.get_state(token, timeframe)
        if not state.get("ready"):
            continue

        # Capturar todos os OBs já detectados (ativos ou que já existiram)
        for ob in state.get("active_obs", []):
            key = (ob["ts"], ob["type"])
            if key not in all_obs_seen:
                all_obs_seen[key] = dict(ob)

        for fvg in state.get("active_fvgs", []):
            key = (fvg["ts"], fvg["type"])
            if key not in all_fvgs_seen:
                all_fvgs_seen[key] = dict(fvg)

        last_bos = state.get("last_bos")
        if last_bos is not None and last_bos["ts"] != last_seen_bos_ts:
            bos_events.append(dict(last_bos))
            last_seen_bos_ts = last_bos["ts"]

    # Swing points: o engine só guarda os mais recentes; recalcular sobre o
    # buffer final para obter todos os swings detectáveis com a mesma lógica
    buffer = list(candles)  # já está oldest → newest
    swing_highs, swing_lows = _recompute_project_swings(buffer)

    final_state = engine2.get_state(token, timeframe)

    return {
        "swing_highs": swing_highs,
        "swing_lows": swing_lows,
        "obs": list(all_obs_seen.values()),
        "fvgs": list(all_fvgs_seen.values()),
        "bos_events": bos_events,
        "final_state": {
            "trend": final_state.get("trend"),
            "premium_discount": final_state.get("premium_discount"),
            "swing_high": final_state.get("swing_high"),
            "swing_low": final_state.get("swing_low"),
        },
    }


def _recompute_project_swings(candles: List[dict]) -> Tuple[List[dict], List[dict]]:
    """Replica exatamente a lógica de SMCEngine._swing_points sobre o buffer completo."""
    lb = config.SWING_LOOKBACK
    swing_highs: List[dict] = []
    swing_lows: List[dict] = []

    for i in range(lb, len(candles) - lb):
        high_i = candles[i]["high"]
        low_i = candles[i]["low"]

        if all(
            candles[i + d]["high"] < high_i and candles[i - d]["high"] < high_i
            for d in range(1, lb + 1)
        ):
            swing_highs.append({"price": high_i, "idx": i, "ts": candles[i]["ts"]})

        if all(
            candles[i + d]["low"] > low_i and candles[i - d]["low"] > low_i
            for d in range(1, lb + 1)
        ):
            swing_lows.append({"price": low_i, "idx": i, "ts": candles[i]["ts"]})

    return swing_highs, swing_lows


# ─── Execução da biblioteca smartmoneyconcepts ────────────────────────────────

def run_library(df: pd.DataFrame, swing_length: int) -> Dict[str, Any]:
    """
    Roda as funções correspondentes da biblioteca sobre o DataFrame completo.
    Retorna dicionário com artefatos comparáveis.
    """
    shl_df = lib_smc.swing_highs_lows(df, swing_length=swing_length)
    bos_df = lib_smc.bos_choch(df, shl_df, close_break=True)
    ob_df = lib_smc.ob(df, shl_df, close_mitigation=False)
    fvg_df = lib_smc.fvg(df, join_consecutive=False)

    # Extrair swing highs/lows
    lib_swing_highs: List[dict] = []
    lib_swing_lows: List[dict] = []
    for i in range(len(df)):
        hl = shl_df["HighLow"].iloc[i]
        if pd.isna(hl):
            continue
        ts = int(df.index[i].timestamp() * 1000)
        level = float(shl_df["Level"].iloc[i])
        if hl == 1:
            lib_swing_highs.append({"price": level, "idx": i, "ts": ts})
        elif hl == -1:
            lib_swing_lows.append({"price": level, "idx": i, "ts": ts})

    # Extrair BOS/ChoCH
    lib_bos_events: List[dict] = []
    for i in range(len(df)):
        bos = bos_df["BOS"].iloc[i]
        choch = bos_df["CHOCH"].iloc[i]
        ts = int(df.index[i].timestamp() * 1000)
        if not pd.isna(bos):
            lib_bos_events.append({
                "ts": ts,
                "idx": i,
                "type": "BOS",
                "direction": "bull" if bos == 1 else "bear",
                "price": float(bos_df["Level"].iloc[i]),
            })
        if not pd.isna(choch):
            lib_bos_events.append({
                "ts": ts,
                "idx": i,
                "type": "ChoCH",
                "direction": "bull" if choch == 1 else "bear",
                "price": float(bos_df["Level"].iloc[i]),
            })

    # Extrair OBs
    lib_obs: List[dict] = []
    for i in range(len(df)):
        ob_val = ob_df["OB"].iloc[i]
        if pd.isna(ob_val):
            continue
        ts = int(df.index[i].timestamp() * 1000)
        lib_obs.append({
            "ts": ts,
            "idx": i,
            "type": "bull" if ob_val == 1 else "bear",
            "top": float(ob_df["Top"].iloc[i]),
            "bottom": float(ob_df["Bottom"].iloc[i]),
        })

    # Extrair FVGs
    lib_fvgs: List[dict] = []
    for i in range(len(df)):
        fvg_val = fvg_df["FVG"].iloc[i]
        if pd.isna(fvg_val):
            continue
        ts = int(df.index[i].timestamp() * 1000)
        lib_fvgs.append({
            "ts": ts,
            "idx": i,
            "type": "bull" if fvg_val == 1 else "bear",
            "top": float(fvg_df["Top"].iloc[i]),
            "bottom": float(fvg_df["Bottom"].iloc[i]),
        })

    return {
        "swing_highs": lib_swing_highs,
        "swing_lows": lib_swing_lows,
        "bos_events": lib_bos_events,
        "obs": lib_obs,
        "fvgs": lib_fvgs,
    }


# ─── Comparação ────────────────────────────────────────────────────────────────

def compare_lists_by_ts(
    list_a: List[dict],
    list_b: List[dict],
    tolerance: int = 0,
    timeframe_ms: int = 0,
) -> Dict[str, Any]:
    """
    Compara duas listas com campo `ts`. Tolerância em número de candles do TF.
    Retorna métricas de match, não-match, e percentual de concordância.
    """
    ts_a = {item["ts"] for item in list_a}
    ts_b = {item["ts"] for item in list_b}

    if tolerance == 0 or timeframe_ms == 0:
        matched = ts_a & ts_b
        only_a = ts_a - ts_b
        only_b = ts_b - ts_a
    else:
        # Match aproximado por janela de ±tolerance candles
        tolerance_ms = tolerance * timeframe_ms
        matched_a = set()
        matched_b = set()
        for ta in ts_a:
            for tb in ts_b:
                if abs(ta - tb) <= tolerance_ms:
                    matched_a.add(ta)
                    matched_b.add(tb)
                    break
        matched = matched_a  # aproximação
        only_a = ts_a - matched_a
        only_b = ts_b - matched_b

    total_union = len(ts_a | ts_b) if (ts_a | ts_b) else 1
    agreement_pct = (len(matched) / total_union) * 100.0 if total_union else 0.0

    return {
        "count_project": len(list_a),
        "count_library": len(list_b),
        "matched": len(matched),
        "only_project": len(only_a),
        "only_library": len(only_b),
        "agreement_pct": round(agreement_pct, 2),
    }


TF_TO_MS = {"15m": 15 * 60 * 1000, "1H": 60 * 60 * 1000, "4H": 4 * 60 * 60 * 1000}


# ─── Relatório ────────────────────────────────────────────────────────────────

def print_tf_report(tf: str, project: Dict[str, Any], library: Dict[str, Any]) -> None:
    tf_ms = TF_TO_MS[tf]
    sep = "─" * 78

    print()
    print(sep)
    print(f" RELATÓRIO DE VALIDAÇÃO — {INSTRUMENT} @ {tf}")
    print(sep)

    # Counts brutos
    print()
    print(" [Counts brutos por indicador]")
    print(f"   Swing Highs   | projeto={len(project['swing_highs']):>4} | "
          f"lib={len(library['swing_highs']):>4}")
    print(f"   Swing Lows    | projeto={len(project['swing_lows']):>4} | "
          f"lib={len(library['swing_lows']):>4}")
    print(f"   BOS/ChoCH     | projeto={len(project['bos_events']):>4} | "
          f"lib={len(library['bos_events']):>4}")
    print(f"   Order Blocks  | projeto={len(project['obs']):>4} | "
          f"lib={len(library['obs']):>4}")
    print(f"   FVGs          | projeto={len(project['fvgs']):>4} | "
          f"lib={len(library['fvgs']):>4}")

    # Concordância por indicador
    print()
    print(" [Concordância (match por timestamp, tolerância ±2 candles para OB/FVG)]")

    sh_cmp = compare_lists_by_ts(project["swing_highs"], library["swing_highs"])
    sl_cmp = compare_lists_by_ts(project["swing_lows"], library["swing_lows"])
    bos_cmp = compare_lists_by_ts(project["bos_events"], library["bos_events"])
    ob_cmp = compare_lists_by_ts(
        project["obs"], library["obs"],
        tolerance=OB_FVG_TIME_TOLERANCE_CANDLES, timeframe_ms=tf_ms,
    )
    fvg_cmp = compare_lists_by_ts(
        project["fvgs"], library["fvgs"],
        tolerance=OB_FVG_TIME_TOLERANCE_CANDLES, timeframe_ms=tf_ms,
    )

    print(f"   Swing Highs   | match={sh_cmp['matched']:>3} | "
          f"só-projeto={sh_cmp['only_project']:>3} | só-lib={sh_cmp['only_library']:>3} | "
          f"concordância={sh_cmp['agreement_pct']:>5.1f}%")
    print(f"   Swing Lows    | match={sl_cmp['matched']:>3} | "
          f"só-projeto={sl_cmp['only_project']:>3} | só-lib={sl_cmp['only_library']:>3} | "
          f"concordância={sl_cmp['agreement_pct']:>5.1f}%")
    print(f"   BOS/ChoCH     | match={bos_cmp['matched']:>3} | "
          f"só-projeto={bos_cmp['only_project']:>3} | só-lib={bos_cmp['only_library']:>3} | "
          f"concordância={bos_cmp['agreement_pct']:>5.1f}%")
    print(f"   Order Blocks  | match={ob_cmp['matched']:>3} | "
          f"só-projeto={ob_cmp['only_project']:>3} | só-lib={ob_cmp['only_library']:>3} | "
          f"concordância={ob_cmp['agreement_pct']:>5.1f}% (±{OB_FVG_TIME_TOLERANCE_CANDLES}c)")
    print(f"   FVGs          | match={fvg_cmp['matched']:>3} | "
          f"só-projeto={fvg_cmp['only_project']:>3} | só-lib={fvg_cmp['only_library']:>3} | "
          f"concordância={fvg_cmp['agreement_pct']:>5.1f}% (±{OB_FVG_TIME_TOLERANCE_CANDLES}c)")

    # Estado final do engine (só projeto tem)
    fs = project.get("final_state", {})
    print()
    print(" [Estado final do smc_engine (projeto)]")
    print(f"   trend             = {fs.get('trend')}")
    print(f"   premium_discount  = {fs.get('premium_discount')}")
    print(f"   swing_high atual  = {fs.get('swing_high')}")
    print(f"   swing_low atual   = {fs.get('swing_low')}")


# ─── Entry point ───────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Valida smc_engine contra smartmoneyconcepts com dados reais OKX."
    )
    parser.add_argument(
        "--candles", type=int, default=TARGET_CANDLES,
        help=f"Número de candles por TF (default: {TARGET_CANDLES})",
    )
    parser.add_argument(
        "--swing-length", type=int, default=None,
        help="swing_length para a lib (default: config.SWING_LOOKBACK)",
    )
    args = parser.parse_args()

    target = args.candles
    swing_length = args.swing_length if args.swing_length else config.SWING_LOOKBACK

    print("=" * 78)
    print(" SMC Monitor — Validação comparativa do smc_engine.py")
    print("=" * 78)
    print(f" Instrumento         : {INSTRUMENT}")
    print(f" Timeframes          : {', '.join(TIMEFRAMES)}")
    print(f" Candles por TF      : {target}")
    print(f" SWING_LOOKBACK (proj): {config.SWING_LOOKBACK}")
    print(f" swing_length (lib)   : {swing_length}")
    print(f" CANDLE_BUFFER (proj) : {config.CANDLE_BUFFER}")

    overall_ok = True

    for tf in TIMEFRAMES:
        print()
        print(f"[{tf}] Buscando {target} candles históricos da OKX…")
        candles = fetch_okx_history(INSTRUMENT, tf, target)
        if len(candles) < 50:
            print(f"  [SKIP] Apenas {len(candles)} candles obtidos para {tf}, pulando.",
                  file=sys.stderr)
            overall_ok = False
            continue

        print(f"  [OK] {len(candles)} candles recebidos "
              f"(de {candles[0]['ts']} a {candles[-1]['ts']})")

        print(f"[{tf}] Rodando smc_engine do projeto (streaming incremental)…")
        project_result = run_project_engine(candles, tf)
        print(f"  [OK] Streaming completo")

        print(f"[{tf}] Rodando smartmoneyconcepts (batch)…")
        df = candles_to_dataframe(candles)
        try:
            library_result = run_library(df, swing_length=swing_length)
            print(f"  [OK] Batch completo")
        except Exception as exc:  # noqa: BLE001
            print(f"  [ERROR] Lib falhou: {exc}", file=sys.stderr)
            overall_ok = False
            continue

        print_tf_report(tf, project_result, library_result)

    print()
    print("=" * 78)
    print(" NOTAS INTERPRETATIVAS")
    print("=" * 78)
    print("""
  Divergências são ESPERADAS e não indicam bug. As duas implementações
  usam definições diferentes para os mesmos conceitos SMC:

  1. Swings: o projeto aceita swings consecutivos do mesmo tipo; a lib
     força alternância HIGH→LOW→HIGH→LOW. Concordância típica 60-80%.

  2. BOS/ChoCH: o projeto marca a cada rompimento de close sobre último
     swing; a lib exige padrão formal de 4 swings alternados. Projeto
     vai produzir MUITO mais sinais. Concordância típica 20-40%.

  3. Order Blocks: definições estruturalmente diferentes — "candle oposto
     antes de impulso" (projeto) vs "candle extremo antes de rompimento
     estrutural" (lib). Concordância baixa esperada.

  4. FVGs: mesma base de 3 candles, mas lib adiciona filtro de direção
     do candle do meio. Projeto mais permissivo. Concordância 70-90%.

  O que realmente importa na validação:
   - Swing points devem ter OVERLAP SIGNIFICATIVO (> 50%). Divergência
     total sugere bug no detector do projeto.
   - FVGs do projeto devem ser SUPERSET dos FVGs da lib. Se a lib
     detectou FVG que o projeto não detectou, investigar.
   - Trend final e Premium/Discount fazem sentido intuitivamente?
""")

    return 0 if overall_ok else 1


if __name__ == "__main__":
    sys.exit(main())






