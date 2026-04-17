# SMC Monitor — telegram.py
# Versão: 0.1.1

"""
OBJETIVO: Enviar notificações via Telegram Bot API.
FONTE DE DADOS: Recebe string pronta de signals.py ou main.py.
LIMITAÇÕES CONHECIDAS: Falhas de envio são silenciosas (warning no log).
NÃO FAZER: nenhum cálculo SMC, nenhuma lógica de sinal, não formatar mensagens.
"""

import json
import logging
import time
import urllib.error
import urllib.request

import config

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
    """Send a heartbeat/status message. No retry — warning on failure."""
    try:
        _post(message)
    except Exception as exc:
        logger.warning("Telegram send_heartbeat failed: %s", exc)


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
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status == 200:
                return True
            logger.warning("Telegram send_critical_alert HTTP %d", resp.status)
            return False
    except Exception as exc:
        logger.warning("Telegram send_critical_alert failed: %s", exc)
        return False
