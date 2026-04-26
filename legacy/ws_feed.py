# SMC Monitor — ws_feed.py
# Versão: 0.1.0

"""
OBJETIVO: Conexão WebSocket OKX, recebimento de candles, heartbeat e reconexão automática.
FONTE DE DADOS: OKX WebSocket público — wss://ws.okx.com:8443/ws/v5/business
LIMITAÇÕES CONHECIDAS: Apenas candles fechados (confirm == "1") são entregues ao callback.
NÃO FAZER: Nenhum cálculo SMC, nenhuma lógica de sinal, não manter estado de candles.
"""

VERSION = "0.1.6"

import asyncio
import json
import logging
import threading
import time

import websockets

import config

logger = logging.getLogger(__name__)


def _build_subscriptions() -> list:
    """Monta lista de subscrições a partir de config.TOKENS e config.TIMEFRAMES."""
    args = []
    for token in config.TOKENS:
        for tf in config.TIMEFRAMES:
            args.append({"channel": f"candle{tf}", "instId": token})
    return args


def _parse_message(raw: str):
    """
    Parseia mensagem recebida.
    Retorna (token, timeframe, candle) para candle fechado, ou None caso contrário.

    Formato esperado:
        {
            "arg":  {"channel": "candle15m", "instId": "BTC-USDT-SWAP"},
            "data": [["ts", "open", "high", "low", "close", "vol", ..., "confirm"]]
        }
    Campos do array: [ts, open, high, low, close, vol, volCcy, volCcyQuote, confirm]
    confirm == "1" → candle fechado.
    """
    try:
        msg = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None

    # ignora pong e mensagens sem estrutura de candle
    if "arg" not in msg or "data" not in msg:
        return None

    channel = msg["arg"].get("channel", "")
    inst_id = msg["arg"].get("instId", "")

    if not channel.startswith("candle"):
        return None

    timeframe = channel[len("candle"):]  # "candle15m" → "15m"

    for row in msg["data"]:
        if len(row) < 9:
            continue
        if row[8] != "1":
            continue  # candle ainda aberto

        candle = {
            "ts":     int(row[0]),
            "open":   float(row[1]),
            "high":   float(row[2]),
            "low":    float(row[3]),
            "close":  float(row[4]),
            "volume": float(row[5]),
        }
        return inst_id, timeframe, candle

    return None


async def _ws_loop(on_candle) -> None:
    """Loop principal WebSocket — nunca retorna."""
    subscriptions = _build_subscriptions()
    subscribe_msg = json.dumps({"op": "subscribe", "args": subscriptions})

    while True:
        try:
            logger.info("Conectando a %s", config.OKX_WS_URL)
            async with websockets.connect(config.OKX_WS_URL) as ws:
                logger.info(
                    "Conexão estabelecida. Subscrevendo %d canais.", len(subscriptions)
                )
                await ws.send(subscribe_msg)

                last_ping = time.monotonic()

                while True:
                    now = time.monotonic()

                    # heartbeat — OKX espera ping em texto simples, responde pong
                    if now - last_ping >= config.OKX_WS_PING_INTERVAL:
                        await ws.send("ping")
                        last_ping = now
                        logger.debug("Ping enviado.")

                    try:
                        raw = await asyncio.wait_for(
                            ws.recv(),
                            timeout=config.OKX_WS_PING_INTERVAL,
                        )
                    except asyncio.TimeoutError:
                        continue

                    if raw == "pong":
                        logger.debug("Pong recebido.")
                        continue

                    result = _parse_message(raw)
                    if result is None:
                        continue

                    token, timeframe, candle = result
                    try:
                        on_candle(token, timeframe, candle)
                    except Exception:
                        logger.exception("Erro no callback on_candle.")

        except websockets.exceptions.ConnectionClosed as exc:
            logger.warning(
                "Conexão encerrada: %s. Reconectando em %ds.",
                exc,
                config.OKX_WS_RECONNECT_DELAY,
            )
        except Exception:
            logger.exception(
                "Erro inesperado no WebSocket. Reconectando em %ds.",
                config.OKX_WS_RECONNECT_DELAY,
            )

        await asyncio.sleep(config.OKX_WS_RECONNECT_DELAY)


def start(on_candle) -> None:
    """
    Inicia o loop WebSocket em thread dedicada.
    on_candle é chamado apenas para candles fechados (confirm == "1").
    Nunca retorna — roda até o processo ser encerrado.

    Assinatura do callback:
        on_candle(token: str, timeframe: str, candle: dict) -> None

    candle dict:
        {
            "ts":     int,    # timestamp de abertura em ms
            "open":   float,
            "high":   float,
            "low":    float,
            "close":  float,
            "volume": float,
        }
    """
    def _run():
        asyncio.run(_ws_loop(on_candle))

    thread = threading.Thread(target=_run, name="ws-feed", daemon=True)
    thread.start()
    thread.join()  # bloqueia até o processo ser encerrado
