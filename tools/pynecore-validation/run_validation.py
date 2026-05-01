"""
OBJETIVO
--------
Rodar o LuxAlgo SMC compute-only (traduzido via PyneCore) sobre candles
históricos do BTC/USDT-PERP 4h, capturar os 16 alertcondition por candle,
e exportar 2 CSVs para validação cruzada com o LuxAlgo no TradingView.

FONTE DE DADOS
--------------
- Candles: ~/SMC_Monitor/user_data/data/binance/futures/BTC_USDT_USDT-4h-futures.feather
- Lógica SMC: luxalgo_smc_compute_only.py (PyneCore script no mesmo diretório)

LIMITAÇÕES CONHECIDAS
---------------------
- Janela hardcoded em 30 dias para limitar carga de validação visual
- Comparação contra TradingView é manual (screenshot vs CSV)
- A API exata do PyneCore precisa ser confirmada na documentação oficial
  (https://pynecore.org/docs) durante implementação. O esqueleto fornecido
  é a abordagem mais provável; ajustar conforme docs atual.

NÃO FAZER
---------
- NÃO modificar o luxalgo_smc_compute_only.py — é output do compilador
  e qualquer mudança invalida a comparação
- NÃO ampliar janela sem alinhar (gera dataset grande demais para revisão visual)
- NÃO inferir "fidelidade" só por contagens agregadas — precisa
  validação visual ponto a ponto contra o TradingView
"""

from __future__ import annotations
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone

import pandas as pd

# ---------------------------------------------------------------------------
# Configurações fixas do experimento
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path.home() / "SMC_Monitor"
CANDLES_PATH = PROJECT_ROOT / "user_data/data/binance/futures/BTC_USDT_USDT-4h-futures.feather"
SCRIPT_DIR = Path(__file__).parent
OUTPUT_DIR = SCRIPT_DIR / "output"
PYNESCRIPT_PATH = SCRIPT_DIR / "luxalgo_smc_compute_only.py"

# Janela: últimos 30 dias terminando no final dos dados disponíveis
WINDOW_DAYS = 30
PAIR = "BTC/USDT:USDT"
TIMEFRAME = "4h"

# Os 16 alertcondition que o script Pyne expõe
ALERT_NAMES = [
    "internalBullishBOS",
    "internalBearishBOS",
    "internalBullishCHoCH",
    "internalBearishCHoCH",
    "swingBullishBOS",
    "swingBearishBOS",
    "swingBullishCHoCH",
    "swingBearishCHoCH",
    "internalBullishOrderBlock",
    "internalBearishOrderBlock",
    "swingBullishOrderBlock",
    "swingBearishOrderBlock",
    "equalHighs",
    "equalLows",
    "bullishFairValueGap",
    "bearishFairValueGap",
]


# ---------------------------------------------------------------------------
# Carga e preparação dos candles
# ---------------------------------------------------------------------------

def load_candles() -> pd.DataFrame:
    """Carrega candles do .feather do Freqtrade e filtra janela."""
    if not CANDLES_PATH.exists():
        raise FileNotFoundError(
            f"Candles não encontrados em {CANDLES_PATH}.\n"
            "Rodar primeiro 'freqtrade download-data' para baixar BTC/USDT 4h."
        )

    df = pd.read_feather(CANDLES_PATH)

    # Freqtrade usa coluna 'date' como timestamp
    if "date" not in df.columns:
        raise ValueError(f"Esperava coluna 'date' no .feather, achei: {df.columns.tolist()}")

    df = df.sort_values("date").reset_index(drop=True)

    # Garante timezone-aware UTC
    if df["date"].dt.tz is None:
        df["date"] = df["date"].dt.tz_localize("UTC")

    # Filtra janela
    end_dt = df["date"].max()
    start_dt = end_dt - timedelta(days=WINDOW_DAYS)
    df = df[df["date"] >= start_dt].reset_index(drop=True)

    print(f"[load_candles] Janela: {df['date'].min()} a {df['date'].max()}")
    print(f"[load_candles] Total de candles: {len(df)}")
    print(f"[load_candles] Colunas: {df.columns.tolist()}")

    return df


# ---------------------------------------------------------------------------
# Execução PyneCore
# ---------------------------------------------------------------------------

def run_pynecore_validation(df: pd.DataFrame) -> pd.DataFrame:
    """
    Roda o luxalgo_smc_compute_only.py via PyneCore e captura os
    16 alertcondition por candle.

    Retorna: DataFrame com colunas [date, open, high, low, close, volume,
                                     <16 alertcondition booleanos>]
    """
    # IMPORTAÇÃO TARDIA — só dentro desta função, para o CLI principal
    # poder dar mensagens de erro claras se PyneCore não estiver instalado
    try:
        from pynecore.core.script_runner import ScriptRunner
    except ImportError as e:
        raise ImportError(
            "PyneCore não está instalado neste venv.\n"
            "Rodar: pip install -r requirements.txt"
        ) from e

    # ATENÇÃO: a API exata do PyneCore precisa ser confirmada na documentação
    # oficial https://pynecore.org/docs. Esta implementação é um esqueleto;
    # Claude Code deve ajustar baseado na docs atual.
    #
    # Estrutura provável da chamada PyneCore:
    #   runner = ScriptRunner(script_path=PYNESCRIPT_PATH)
    #   results = runner.run(df)
    #
    # `results` deve ser um DataFrame com as séries dos 16 alertcondition
    # alinhadas aos candles. Estrutura exata depende da API do PyneCore.

    runner = ScriptRunner(script_path=str(PYNESCRIPT_PATH))
    results = runner.run(df)

    # Sanity check
    expected_alerts_in_results = set(ALERT_NAMES)
    available_columns = set(results.columns)
    missing = expected_alerts_in_results - available_columns
    if missing:
        print(f"[WARN] Alertcondition esperados mas não encontrados: {missing}")
        print(f"[WARN] Colunas disponíveis: {available_columns}")

    return results


# ---------------------------------------------------------------------------
# Geração dos CSVs
# ---------------------------------------------------------------------------

def export_full_csv(df: pd.DataFrame, output_path: Path) -> None:
    """Exporta CSV com 1 linha por candle e todas as 16 colunas booleanas."""
    columns_order = ["date", "open", "high", "low", "close", "volume"] + ALERT_NAMES
    columns_present = [c for c in columns_order if c in df.columns]
    df[columns_present].to_csv(output_path, index=False)
    print(f"[export_full_csv] Escritas {len(df)} linhas em {output_path}")


def export_summary_csv(df: pd.DataFrame, output_path: Path) -> None:
    """Exporta CSV resumido — só linhas onde algum alertcondition foi True."""
    rows = []
    for _, row in df.iterrows():
        for alert_name in ALERT_NAMES:
            if alert_name in row and bool(row[alert_name]):
                rows.append({
                    "timestamp": row["date"],
                    "event_type": alert_name,
                    "candle_close": row.get("close"),
                    "candle_high": row.get("high"),
                    "candle_low": row.get("low"),
                })

    summary_df = pd.DataFrame(rows)
    summary_df.to_csv(output_path, index=False)
    print(f"[export_summary_csv] {len(summary_df)} eventos exportados para {output_path}")

    # Distribuição de eventos por tipo
    if len(summary_df) > 0:
        print("\n[summary] Distribuição de eventos por tipo:")
        print(summary_df["event_type"].value_counts().to_string())


# ---------------------------------------------------------------------------
# Validações automáticas (sanity checks)
# ---------------------------------------------------------------------------

def sanity_checks(df: pd.DataFrame) -> None:
    """Validações grosseiras antes de prosseguir para análise visual."""
    print("\n=== SANITY CHECKS ===")

    # 1. Total de candles
    print(f"  [1] Total de candles processados: {len(df)}")

    # 2. Continuidade temporal (sem gaps grandes)
    if len(df) > 1 and "date" in df.columns:
        deltas = df["date"].diff().dropna()
        expected = pd.Timedelta(hours=4)
        gaps = deltas[deltas != expected]
        if len(gaps) > 0:
            print(f"  [2] WARN: {len(gaps)} gaps temporais detectados:")
            print(gaps.value_counts().head().to_string())
        else:
            print(f"  [2] OK: continuidade temporal perfeita ({expected} entre candles)")

    # 3. Eventos por tipo (zero pode indicar bug)
    print("  [3] Contagem de eventos por tipo:")
    for alert in ALERT_NAMES:
        if alert in df.columns:
            count = int(df[alert].sum())
            flag = " <-- ZERO!" if count == 0 else ""
            print(f"        {alert}: {count}{flag}")
        else:
            print(f"        {alert}: COLUNA AUSENTE")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    print("=" * 60)
    print("  PyneCore Validation — LuxAlgo SMC compute-only")
    print(f"  Par: {PAIR} | Timeframe: {TIMEFRAME} | Janela: últimos {WINDOW_DAYS} dias")
    print("=" * 60)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Carregar candles
    df = load_candles()

    # 2. Rodar PyneCore
    print("\n[run] Executando PyneCore sobre os candles...")
    results = run_pynecore_validation(df)

    # 3. Sanity checks
    sanity_checks(results)

    # 4. Exportar CSVs
    print("\n[export] Gerando CSVs...")
    export_full_csv(results, OUTPUT_DIR / "events_full.csv")
    export_summary_csv(results, OUTPUT_DIR / "events_summary.csv")

    print("\n=== CONCLUSÃO ===")
    print(f"Outputs em: {OUTPUT_DIR.resolve()}")
    print("Comparar manualmente com screenshot do TradingView (LuxAlgo SMC original).")

    return 0


if __name__ == "__main__":
    sys.exit(main())
