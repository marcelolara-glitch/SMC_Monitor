# SMC Monitor — config.py
# Versão: 0.1.5

"""
OBJETIVO: Centraliza todos os parâmetros de configuração do SMC Monitor.
Tokens, credenciais e parâmetros SMC ficam aqui.
Credenciais sensíveis (Telegram, OKX) são carregadas de variáveis de ambiente.
NÃO FAZER: nunca hardcodar credenciais neste arquivo.
"""

import os

# ─── Versão ───────────────────────────────────────────────────────────────────
VERSION = "0.1.5"

# ─── Tokens monitorados ───────────────────────────────────────────────────────
TOKENS = [
    "BTC-USDT-SWAP",
]

# ─── Timeframes monitorados ───────────────────────────────────────────────────
TIMEFRAMES = ["15m", "1H", "4H"]

# ─── OKX WebSocket ────────────────────────────────────────────────────────────
OKX_WS_URL = "wss://ws.okx.com:8443/ws/v5/business"
OKX_WS_PING_INTERVAL = 30        # segundos entre pings
OKX_WS_RECONNECT_DELAY = 5       # segundos antes de reconectar após queda

# ─── Buffer de candles por timeframe ─────────────────────────────────────────
# Quantidade mínima de candles para cálculo SMC ser válido
CANDLE_BUFFER = {
    "15m": 100,
    "1H":  100,
    "4H":  100,
}

# ─── Parâmetros SMC ───────────────────────────────────────────────────────────
SWING_LOOKBACK = 5               # velas para cada lado na detecção de swing
OB_MIN_DISPLACEMENT = 0.003      # deslocamento mínimo (0.3%) para OB válido
LIQUIDITY_SWEEP_LOOKBACK = 10    # velas para trás na detecção de sweep

# ─── Heartbeat ────────────────────────────────────────────────────────────────
HEARTBEAT_INTERVAL_SECONDS = 1800  # 30 minutos

# ─── Score de confluência ─────────────────────────────────────────────────────
SIGNAL_THRESHOLD = 4             # pontuação mínima para emitir sinal (max=6)

# ─── Tracker ─────────────────────────────────────────────────────────────────
SIGNAL_TIMEOUT_SECONDS = 86400   # 24 horas; timeout individual por sinal

# ─── Telegram ────────────────────────────────────────────────────────────────
# Carregado de variável de ambiente — nunca hardcodar
TELEGRAM_TOKEN = os.environ.get("SMC_TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("SMC_TELEGRAM_CHAT_ID", "")

# ── Bot Telegram (Passo 11) ───────────────────────────────────────────────────
TELEGRAM_AUTHORIZED_CHAT_IDS: list[int] = [
    int(cid) for cid in os.environ.get("SMC_TELEGRAM_CHAT_ID", "0").split(",")
    if cid.strip().isdigit() and int(cid.strip()) != 0
]
BOT_POLL_TIMEOUT: int = 60  # segundos

# ─── OKX API (Fase 2) ────────────────────────────────────────────────────────
OKX_API_KEY    = os.environ.get("SMC_OKX_API_KEY", "")
OKX_API_SECRET = os.environ.get("SMC_OKX_API_SECRET", "")
OKX_PASSPHRASE = os.environ.get("SMC_OKX_PASSPHRASE", "")

# ─── Paths ───────────────────────────────────────────────────────────────────
BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
DATA_DIR  = os.path.join(BASE_DIR, "data")
DB_PATH   = os.path.join(DATA_DIR, "smc_state.db")
LOG_PATH  = os.path.join(BASE_DIR, "smc_monitor.log")
