# SMC Monitor — main.py
# Versão: 0.1.2

"""
OBJETIVO: Entry point e orquestrador do daemon SMC Monitor.
Inicializa módulos na ordem correta, conecta ws_feed ao smc_engine,
avalia sinais após cada candle fechado, persiste estado periodicamente.
FONTE DE DADOS: ws_feed via callback on_candle.
NÃO FAZER: nenhum cálculo SMC, nenhuma lógica de sinal — apenas orquestração.
"""

import collections
import datetime
import logging
import sys
import threading
import time

import config
import lib_version_check
import signals
import smc_engine
from smc_engine import _smoke_test_library
import state
import telegram
import ws_feed

VERSION = "0.1.2"

logger = logging.getLogger(__name__)

_start_time = time.time()
_candle_count = 0


def _setup_logging() -> None:
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s — %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    root.addHandler(sh)

    try:
        fh = logging.FileHandler(config.LOG_PATH)
        fh.setFormatter(fmt)
        root.addHandler(fh)
    except Exception:
        pass


def _restore_engine_state(
    engine: smc_engine.SMCEngine,
    saved_states: dict,
    saved_buffers: dict,
) -> None:
    for token, tf_map in saved_buffers.items():
        engine._buffers.setdefault(token, {})
        engine._states.setdefault(token, {})
        for timeframe, candles in tf_map.items():
            max_len = config.CANDLE_BUFFER.get(timeframe, 100)
            engine._buffers[token][timeframe] = collections.deque(candles, maxlen=max_len)

    for token, tf_map in saved_states.items():
        engine._states.setdefault(token, {})
        for timeframe, st in tf_map.items():
            engine._states[token][timeframe] = st


def _heartbeat_loop() -> None:
    while True:
        time.sleep(config.HEARTBEAT_INTERVAL_SECONDS)
        uptime_s = int(time.time() - _start_time)
        h, remainder = divmod(uptime_s, 3600)
        m, s = divmod(remainder, 60)
        msg = (
            f"SMC Monitor v{VERSION} — heartbeat\n"
            f"Uptime: {h:02d}h{m:02d}m{s:02d}s\n"
            f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}"
        )
        telegram.send_heartbeat(msg)


def _version_check_loop() -> None:
    # Wakes every hour; fires check_for_updates on Monday 09:00–09:59 UTC.
    _last_check_week: int | None = None

    while True:
        time.sleep(3600)
        now = datetime.datetime.now(datetime.timezone.utc)
        # weekday() == 0 is Monday; check window 09:00–09:59 UTC
        if now.weekday() == 0 and now.hour == 9:
            iso_week = now.isocalendar()[1]
            if iso_week != _last_check_week:
                _last_check_week = iso_week
                lib_version_check.check_for_updates()


def main() -> None:
    global _candle_count

    _setup_logging()
    logger.info("SMC Monitor v%s iniciando", VERSION)

    lib_version = smc_engine._get_lib_version()
    logger.info("smartmoneyconcepts version: %s", lib_version)

    ok, msg = _smoke_test_library()
    if not ok:
        alert_text = (
            "🚨 SMC MONITOR — BOOT ABORTADO\n"
            f"Motivo: smoke test da smartmoneyconcepts falhou\n"
            f"Versão instalada: {lib_version}\n"
            f"Exceção: {msg}\n\n"
            "AÇÃO NECESSÁRIA:\n"
            "1. Verificar operações em andamento na OKX manualmente\n"
            # TODO Fase 3: quando executor estiver implementado, adicionar aqui:
            #   open_positions = executor.list_open_positions()
            #   if open_positions:
            #       alert_text += f"\n⚠️ OPERAÇÕES ABERTAS: {len(open_positions)}\n"
            #       for p in open_positions:
            #           alert_text += f"  - {p['instId']} {p['side']} {p['sz']} @ {p['avgPx']}\n"
            #       alert_text += "\nVocê precisa gerenciar estas posições manualmente.\n"
            "2. Daemon não está rodando — não haverá novos sinais\n"
            "3. Investigar compatibilidade da lib antes de reiniciar\n\n"
            "Sistema offline até correção."
        )
        try:
            telegram.send_critical_alert(alert_text)
        except Exception as e:
            logger.error("Failed to send critical alert: %s", e)
        logger.critical("Smoke test failed: %s. Aborting boot.", msg)
        sys.exit(1)

    logger.info("Smoke test passed. Engine ready.")

    state.init_db()
    signals.load_event_tracking()

    engine = smc_engine.SMCEngine()

    saved_states = state.load_state()
    saved_buffers = state.load_candle_buffers()
    _restore_engine_state(engine, saved_states, saved_buffers)
    logger.info(
        "Estado restaurado: %d tokens — buffers restaurados: %d tokens",
        len(saved_states),
        len(saved_buffers),
    )

    hb_thread = threading.Thread(target=_heartbeat_loop, daemon=True, name="heartbeat")
    hb_thread.start()

    vc_thread = threading.Thread(target=_version_check_loop, daemon=True, name="version-check")
    vc_thread.start()

    def on_candle(token: str, timeframe: str, candle: dict) -> None:
        global _candle_count

        engine.on_candle(token, timeframe, candle)

        events = signals.evaluate_events(token, engine)
        for event in events:
            telegram.send_signal(signals.format_event(event, token))

        signal = signals.evaluate(token, engine)
        if signal is not None:
            telegram.send_signal(signals.format_signal(signal))

        _candle_count += 1
        if _candle_count % 100 == 0:
            state.save_state(engine.get_all_states())
            for tok in config.TOKENS:
                for tf in config.TIMEFRAMES:
                    buf = engine._buffers.get(tok, {}).get(tf)
                    if buf is not None:
                        state.save_candle_buffer(tok, tf, list(buf))
            signals.persist_event_tracking()

    ws_feed.start(on_candle)


if __name__ == "__main__":
    main()
