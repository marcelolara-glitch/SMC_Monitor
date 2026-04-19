# SMC Monitor — telegram.py
# Versão: 0.1.4

"""
OBJETIVO: Enviar notificações via Telegram Bot API.
FONTE DE DADOS: Recebe string pronta de signals.py ou main.py.
LIMITAÇÕES CONHECIDAS: Falhas de envio são silenciosas (warning no log).
NÃO FAZER: nenhum cálculo SMC, nenhuma lógica de sinal, não formatar mensagens.
"""

import datetime
import json
import logging
import time
import urllib.error
import urllib.request

import config

VERSION = "0.1.4"

logger = logging.getLogger(__name__)

_API_BASE = "https://api.telegram.org/bot{token}/sendMessage"
_TIMEOUT = 10
_RETRY_COUNT = 3
_RETRY_INTERVAL = 2


def _post(message: str) -> None:
    """Send a single HTTP POST to the Telegram sendMessage endpoint. Raises on failure."""
    if not config.TELEGRAM_TOKEN or not config.TELEGRAM_CHAT_ID:
        logger.warning("Telegram credentials not configured — message not sent")
        return

    url = _API_BASE.format(token=config.TELEGRAM_TOKEN)
    payload = json.dumps({
        "chat_id": config.TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
    }).encode()

    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        if resp.status != 200:
            raise urllib.error.HTTPError(url, resp.status, "Non-200 response", {}, None)


def send_signal(message: str) -> None:
    """Send a signal message with up to 3 retries (2 s apart). Silent on final failure."""
    for attempt in range(1, _RETRY_COUNT + 1):
        try:
            _post(message)
            return
        except Exception as exc:
            if attempt < _RETRY_COUNT:
                logger.warning("Telegram send_signal attempt %d failed: %s — retrying", attempt, exc)
                time.sleep(_RETRY_INTERVAL)
            else:
                logger.warning("Telegram send_signal failed after %d attempts: %s", _RETRY_COUNT, exc)


def send_heartbeat(message: str) -> None:
    """
    OBJETIVO: enviar heartbeat periódico. Retry leve (2 tentativas, backoff 2s)
              para sobreviver a blips momentâneos sem bloquear o loop principal.
    NÃO FAZER: não subir para 3+ retries; não levantar exceção — retornar/logar apenas.
    """
    for attempt in range(1, 3):
        try:
            _post(message)
            return
        except Exception as exc:
            if attempt < 2:
                logger.warning(
                    "Telegram send_heartbeat attempt %d failed: %s — retrying", attempt, exc
                )
                time.sleep(2)
            else:
                logger.warning("Telegram send_heartbeat failed after 2 attempts: %s", exc)


def _format_duration(seconds: int) -> str:
    if seconds < 3600:
        m = max(1, seconds // 60)
        return f"{m}min"
    elif seconds < 86400:
        h = seconds // 3600
        m = (seconds % 3600) // 60
        return f"{h}h{m:02d}min" if m else f"{h}h"
    else:
        d = seconds // 86400
        h = (seconds % 86400) // 3600
        return f"{d}d {h}h" if h else f"{d}d"


def send_signal_closed(
    signal_id: int,
    token: str,
    direction: str,
    outcome: str,
    resolved_price: float,
    entry_mid: float,
    sl_price: float,
    tp1_price: float,
    r_multiple: float,
    duration_seconds: int,
    candle_ts: int,
) -> bool:
    """
    OBJETIVO: Notificar via Telegram o fechamento de um sinal rastreado
              (sl_hit, tp1_hit ou timed_out).
    FONTE DE DADOS: dict de transição retornado por tracker.observe_candle_15m().
    LIMITAÇÕES CONHECIDAS: 3 tentativas com intervalo de 2s; falha silenciosa
                           após esgotamento — warning no log, retorna False.
    NÃO FAZER: não chamar tracker, não calcular R aqui.

    Retorna True em sucesso, False após esgotar tentativas.
    """
    candle_time = datetime.datetime.utcfromtimestamp(candle_ts / 1000).strftime("%H:%M")
    duration_str = _format_duration(duration_seconds)

    if outcome == "sl_hit":
        touch_label = "low" if direction == "LONG" else "high"
        msg = (
            f"🔴 *SL atingido — {token} {direction} #{signal_id}*\n"
            f"Candle 15m {candle_time} — {touch_label}: `{resolved_price:.4f}`\n"
            f"Entry mid: `{entry_mid:.4f}` · SL: `{sl_price:.4f}`\n"
            f"Aberto há {duration_str} · Resultado: *{r_multiple:+.1f}R*"
        )
    elif outcome == "tp1_hit":
        touch_label = "high" if direction == "LONG" else "low"
        msg = (
            f"🟢 *TP1 atingido — {token} {direction} #{signal_id}*\n"
            f"Candle 15m {candle_time} — {touch_label}: `{resolved_price:.4f}`\n"
            f"Entry mid: `{entry_mid:.4f}` · TP1: `{tp1_price:.4f}`\n"
            f"Aberto há {duration_str} · Resultado: *{r_multiple:+.1f}R*"
        )
    else:  # timed_out
        sl_dist = (
            abs(resolved_price - sl_price) / resolved_price * 100
            if resolved_price > 0 else 0.0
        )
        if tp1_price and tp1_price > 0 and resolved_price > 0:
            tp1_dist_str = f"{abs(resolved_price - tp1_price) / resolved_price * 100:.2f}%"
        else:
            tp1_dist_str = "—"
        msg = (
            f"⚪ *Timeout — {token} {direction} #{signal_id}*\n"
            f"Sem toque de SL ou TP1 em {duration_str}\n"
            f"Preço atual: `{resolved_price:.4f}`\n"
            f"Distância do SL: {sl_dist:.2f}% · Distância do TP1: {tp1_dist_str}"
        )

    for attempt in range(1, _RETRY_COUNT + 1):
        try:
            _post(msg)
            return True
        except Exception as exc:
            if attempt < _RETRY_COUNT:
                logger.warning(
                    "Telegram send_signal_closed attempt %d failed: %s — retrying",
                    attempt, exc,
                )
                time.sleep(_RETRY_INTERVAL)
            else:
                logger.warning(
                    "Telegram send_signal_closed failed after %d attempts: %s",
                    _RETRY_COUNT, exc,
                )
    return False


def send_critical_alert(message: str) -> bool:
    """
    OBJETIVO: enviar mensagem crítica ao chat Telegram configurado.
              Usado para alertas que exigem ação imediata do operador
              (boot abortado, engine quebrada, etc.).
    FONTE DE DADOS: variável `message` e credenciais Telegram do config.
    LIMITAÇÕES CONHECIDAS: depende do Telegram estar online. Timeout
                           reduzido (5s) porque é crítico — se falhar,
                           segue em frente sem bloquear.
    NÃO FAZER: não formatar com Markdown (pode falhar parse), não enviar
               em loop (chamada única).

    Retorna True se enviou com sucesso, False caso contrário.
    """
    if not config.TELEGRAM_TOKEN or not config.TELEGRAM_CHAT_ID:
        logger.warning("Telegram credentials not configured — critical alert not sent")
        return False

    url = _API_BASE.format(token=config.TELEGRAM_TOKEN)
    payload = json.dumps({
        "chat_id": config.TELEGRAM_CHAT_ID,
        "text": message,
    }).encode()

    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    for attempt in range(1, 4):  # 3 tentativas total: a primeira e 2 retries
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    return True
                logger.warning(
                    "Telegram send_critical_alert HTTP %d (attempt %d)",
                    resp.status, attempt,
                )
        except Exception as exc:
            logger.warning(
                "Telegram send_critical_alert attempt %d failed: %s",
                attempt, exc,
            )
        if attempt < 3:
            time.sleep(2)
    return False
