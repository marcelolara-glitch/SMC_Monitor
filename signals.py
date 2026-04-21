# SMC Monitor — signals.py
# Versão: 0.1.9

"""
OBJETIVO: Calcular score de confluência SMC, decidir emissão de sinal e
          detectar eventos relevantes (BOS/ChoCH, sweep, trend change 4H).
FONTE DE DADOS: estados SMC entregues pelo SMCEngine via get_state().
LIMITAÇÕES CONHECIDAS: requer todos os timeframes prontos (ready=True) para avaliar.
NÃO FAZER: sem cálculo SMC, sem conexão WebSocket, sem envio de mensagens Telegram.
"""

import datetime
import logging
import time

import config
import state as _state
from smc_engine import SMCEngine

VERSION = "0.1.9"

logger = logging.getLogger(__name__)

# Candle duration in milliseconds per timeframe
_TF_DURATION_MS: dict[str, int] = {
    "15m": 15 * 60 * 1_000,
    "1H":  60 * 60 * 1_000,
    "4H":  4  * 60 * 60 * 1_000,
}

# Minimum R:R ratio required for signal emission (final gate)
_MIN_RR = 1.5

# SL buffer: max(0.3% of swing base, 1.5 * ATR_14 15m)
_SL_BUFFER_PCT = 0.003
_SL_BUFFER_ATR_MULT = 1.5

# Human-readable labels for each scorable criterion (insertion-ordered).
# Premium/Discount e Tendência 4H são GATES (bloqueiam emissão), não pontuáveis.
_CRITERIA_LABELS: dict[str, str] = {
    "ob_active":        "OB ativo no 1H",
    "fvg_adjacent":     "FVG adjacente ao OB (1H)",
    "sweep_recent":     "Liquidity Sweep recente",
    "bos_choch_15m":    "BOS/ChoCH confirmado no 15m",
    "trend_1h_aligned": "Tendência 1H alinhada",
}

# (token, timeframe, event_type) → {"ts": int, "value": str | None}
_event_tracking: dict[tuple[str, str, str], dict] = {}


def _ts_to_str(ts_ms: int) -> str:
    if not ts_ms:
        return "—"
    return datetime.datetime.utcfromtimestamp(ts_ms / 1000.0).strftime("%Y-%m-%d %H:%M UTC")


def evaluate(token: str, engine: SMCEngine) -> dict | None:
    """
    Recebe o token e a instância do SMCEngine, consulta os estados dos três
    timeframes via engine.get_state(), calcula o score de confluência e retorna
    o sinal estruturado se score >= config.SIGNAL_THRESHOLD.
    Retorna None se o threshold não for atingido ou se a tendência 4H for neutra.
    """
    state_4h  = engine.get_state(token, "4H")
    state_1h  = engine.get_state(token, "1H")
    state_15m = engine.get_state(token, "15m")

    # All three timeframes must have a full candle buffer
    if not (state_4h.get("ready") and state_1h.get("ready") and state_15m.get("ready")):
        logger.debug("%s: not all timeframes ready — skipping evaluation", token)
        return None

    # ── Gate 2: Tendência 4H (viés macro) ────────────────────────────────────
    # Executa primeiro por necessidade — direction DERIVA de trend_4h e o
    # Gate 1 (P/D) precisa de direction para decidir. 4H neutral bloqueia.
    # (Numeração segue briefing: Gate 1 = P/D, Gate 2 = 4H.)
    trend_4h = state_4h.get("trend", "neutral")
    if trend_4h == "neutral":
        logger.debug("%s: gate 4H bloqueou — trend_4h=neutral", token)
        return None

    direction = "LONG"  if trend_4h == "bullish" else "SHORT"
    ob_type   = "bull"  if direction == "LONG"   else "bear"

    # ── Gate 1: Premium/Discount direcional ──────────────────────────────────
    # LONG só em Discount claro (<0.45); SHORT só em Premium claro (>0.55);
    # Equilibrium (0.45–0.55) passa, mas não pontua no score.
    pd_position = state_1h.get("pd_position")
    if pd_position is None:
        pd_position = 0.5
    if direction == "LONG" and pd_position > 0.55:
        logger.debug(
            "%s: gate P/D bloqueou LONG — pd_position=%.2f > 0.55 (Premium)",
            token, pd_position,
        )
        return None
    if direction == "SHORT" and pd_position < 0.45:
        logger.debug(
            "%s: gate P/D bloqueou SHORT — pd_position=%.2f < 0.45 (Discount)",
            token, pd_position,
        )
        return None

    now_ms = int(time.time() * 1_000)

    # Current price from 15m buffer
    try:
        current_price = float(list(engine._buffers[token]["15m"])[-1]["close"])
    except (KeyError, IndexError):
        current_price = 0.0

    # ── Criterion 1: Active OB in 1H in the correct direction ────────────────
    active_obs_1h = [
        ob for ob in state_1h.get("active_obs", [])
        if ob["type"] == ob_type and not ob.get("mitigated", False)
    ]
    ob_active = len(active_obs_1h) > 0

    # Reference OB: most recent un-mitigated OB in the correct direction
    ref_ob = active_obs_1h[-1] if active_obs_1h else None

    # ── Criterion 2: FVG adjacent / overlapping the OB in 1H ─────────────────
    active_fvgs_1h = [
        fvg for fvg in state_1h.get("active_fvgs", [])
        if fvg["type"] == ob_type and fvg.get("status") != "mitigated"
    ]

    fvg_adjacent = False
    matched_fvg = None
    if ref_ob and active_fvgs_1h:
        ob_top    = ref_ob["top"]
        ob_bottom = ref_ob["bottom"]
        for fvg in active_fvgs_1h:
            # Zones overlap when neither is entirely above/below the other
            if fvg["bottom"] <= ob_top and fvg["top"] >= ob_bottom:
                fvg_adjacent = True
                matched_fvg = fvg
                break

    # ── Criterion 3: Recent liquidity sweep in 1H or 15m ─────────────────────
    sweep_recent = False
    ref_sweep = None
    ref_sweep_tf = None
    for tf in ("1H", "15m"):
        sweep = engine.get_state(token, tf).get("last_sweep")
        if sweep:
            window_ms = 10 * _TF_DURATION_MS[tf]
            if (now_ms - sweep["ts"]) <= window_ms:
                sweep_recent = True
                ref_sweep = sweep
                ref_sweep_tf = tf
                break

    # ── Criterion 4: BOS or ChoCH confirmed in 15m in trade direction ─────────
    bos_15m      = state_15m.get("last_bos")
    bos_choch_15m = (
        bos_15m is not None and bos_15m.get("direction") == ob_type
    )

    # ── Criterion 5: 1H trend aligned with trade direction ───────────────────
    # PR B3 estenderá para aceitar 1H desalinhado quando houver confluência de
    # esgotamento (sweep + BOS 15m + Discount). Neste PR, apenas alinhamento direto.
    trend_1h = state_1h.get("trend", "neutral")
    trend_1h_aligned = (
        (direction == "LONG"  and trend_1h == "bullish") or
        (direction == "SHORT" and trend_1h == "bearish")
    )

    # ── Score (sobre 5 critérios; P/D e 4H são gates, já validados acima) ─────
    criteria: dict[str, bool] = {
        "ob_active":        ob_active,
        "fvg_adjacent":     fvg_adjacent,
        "sweep_recent":     sweep_recent,
        "bos_choch_15m":    bos_choch_15m,
        "trend_1h_aligned": trend_1h_aligned,
    }
    score = sum(criteria.values())

    logger.info(
        "%s direction=%s score=%d/5 criteria=%s",
        token, direction, score, criteria,
    )

    if score < config.SIGNAL_THRESHOLD:
        return None

    # ── Entry sugerido (cascata: FVG mid → borda interna do OB → preço atual) ─
    if matched_fvg:
        entry = matched_fvg["midpoint"]
        entry_source = "fvg"
    elif ref_ob:
        entry = ref_ob["top"] if direction == "LONG" else ref_ob["bottom"]
        entry_source = "ob_edge"
    else:
        entry = current_price
        entry_source = "current_price"

    entry_zone_valid = (
        {"top": ref_ob["top"], "bottom": ref_ob["bottom"]} if ref_ob else None
    )

    # ── SL structural: swing low/high + buffer max(0.3%, 1.5×ATR_14 15m) ─────
    atr_14 = state_15m.get("atr_14", 0.0)
    if direction == "LONG":
        sl_base = state_1h.get("swing_low", 0.0)
        if sl_base <= 0.0:
            logger.debug("%s: bloqueado — swing_low indisponível para SL", token)
            return None
        buffer = max(_SL_BUFFER_PCT * sl_base, _SL_BUFFER_ATR_MULT * atr_14)
        sl_price = sl_base - buffer
    else:
        sl_base = state_1h.get("swing_high", 0.0)
        if sl_base <= 0.0:
            logger.debug("%s: bloqueado — swing_high indisponível para SL", token)
            return None
        buffer = max(_SL_BUFFER_PCT * sl_base, _SL_BUFFER_ATR_MULT * atr_14)
        sl_price = sl_base + buffer

    risk = abs(entry - sl_price)
    if risk <= 0.0:
        logger.debug("%s: bloqueado — risk=0 (entry == sl)", token)
        return None

    # ── TP1: próximo target estrutural à frente do entry, com piso R:R ≥ 1.5 ─
    tp_candidates: list[float] = []

    for fvg in active_fvgs_1h:
        if fvg.get("type") != ob_type:
            continue
        mp = fvg.get("midpoint", 0.0)
        if direction == "LONG" and mp > entry:
            tp_candidates.append(mp)
        elif direction == "SHORT" and mp < entry:
            tp_candidates.append(mp)

    swing_target = (
        state_1h.get("swing_high") if direction == "LONG"
        else state_1h.get("swing_low")
    )
    if swing_target:
        if (direction == "LONG" and swing_target > entry) or \
           (direction == "SHORT" and swing_target < entry):
            tp_candidates.append(swing_target)

    tp_candidates.sort(key=lambda c: abs(c - entry))

    tp1 = None
    tp1_source = None
    for cand in tp_candidates:
        rr = abs(cand - entry) / risk
        if rr >= _MIN_RR:
            tp1 = cand
            tp1_source = "structural"
            break

    if tp1 is None:
        if direction == "LONG":
            tp1 = entry + _MIN_RR * risk
        else:
            tp1 = entry - _MIN_RR * risk
        tp1_source = "math"

    # ── Gate R:R final ───────────────────────────────────────────────────────
    rr_final = abs(tp1 - entry) / risk
    if rr_final < _MIN_RR:
        logger.debug(
            "%s: bloqueado por R:R final=%.2f < %.2f", token, rr_final, _MIN_RR
        )
        return None

    # ── Premium/Discount details (do state consolidado — PR A) ───────────────
    pd_ref_range = state_1h.get("pd_reference_range")
    if pd_ref_range:
        pd_swing_high  = float(pd_ref_range.get("top", 0.0))
        pd_swing_low   = float(pd_ref_range.get("bottom", 0.0))
        pd_equilibrium = (pd_swing_high + pd_swing_low) / 2.0
    else:
        pd_swing_high  = float(state_1h.get("swing_high", 0.0))
        pd_swing_low   = float(state_1h.get("swing_low", 0.0))
        pd_equilibrium = (
            (pd_swing_high + pd_swing_low) / 2.0
            if pd_swing_high > pd_swing_low and pd_swing_high > 0.0
            else 0.0
        )

    pd_details = {
        "label":       state_1h.get("pd_label", "equilibrium"),
        "position":    pd_position,
        "swing_high":  pd_swing_high,
        "swing_low":   pd_swing_low,
        "equilibrium": pd_equilibrium,
    }

    # ── Trend states per TF ───────────────────────────────────────────────────
    trend_states = {
        tf: {
            "trend":    st.get("trend", "neutral"),
            "last_bos": st.get("last_bos"),
        }
        for tf, st in (("4H", state_4h), ("1H", state_1h), ("15m", state_15m))
    }

    return {
        "token":        token,
        "direction":    direction,
        "score":        score,
        "criteria":     criteria,
        "entry":             entry,
        "entry_source":      entry_source,
        "entry_zone_valid":  entry_zone_valid,
        "sl_price":     sl_price,
        "tp1":          tp1,
        "tp1_source":   tp1_source,
        "rr":           rr_final,
        "timestamp":    now_ms,
        "ref_ob":       ref_ob,
        "ref_fvg":      matched_fvg,
        "ref_sweep":    ref_sweep,
        "ref_sweep_tf": ref_sweep_tf,
        "trend_states": trend_states,
        "pd_details":   pd_details,
        "current_price": current_price,
    }


def format_signal(signal: dict) -> str:
    """
    Recebe o dict de sinal retornado por evaluate() e retorna string formatada
    pronta para envio via Telegram (Markdown Mode).
    """
    direction     = signal["direction"]
    emoji         = "🟢" if direction == "LONG" else "🔴"
    token         = signal["token"]
    score         = signal["score"]
    entry         = signal["entry"]
    entry_source  = signal.get("entry_source", "")
    entry_zone_valid = signal.get("entry_zone_valid")
    sl            = signal["sl_price"]
    tp1           = signal["tp1"]
    tp1_source    = signal.get("tp1_source", "")
    rr            = signal.get("rr", 0.0)
    criteria      = signal["criteria"]
    current_price = signal.get("current_price", 0.0)
    trend_states  = signal.get("trend_states", {})
    ref_ob        = signal.get("ref_ob")
    ref_fvg       = signal.get("ref_fvg")
    ref_sweep     = signal.get("ref_sweep")
    ref_sweep_tf  = signal.get("ref_sweep_tf")
    pd_details    = signal.get("pd_details", {})
    now_ms        = signal.get("timestamp", int(time.time() * 1_000))

    lines = []

    # ── Header ────────────────────────────────────────────────────────────────
    lines.append(f"{emoji} *{direction} — {token}*")
    cp_str = f"`{current_price:.4f}`" if current_price else "—"
    lines.append(f"Score: *{score}/5*  | Preço atual: {cp_str}")
    lines.append("")

    # ── Gates aprovados (informativo — sinal só é emitido se ambos ok) ───────
    pd_gate_label = pd_details.get("label", "equilibrium") if pd_details else "equilibrium"
    pd_gate_pos   = pd_details.get("position", 0.5) if pd_details else 0.5
    trend_4h_val  = trend_states.get("4H", {}).get("trend", "neutral")
    lines.append("━━ Gates aprovados ━━")
    lines.append(f"  ✅ Premium/Discount ({pd_gate_label}, {pd_gate_pos:.2f})")
    lines.append(f"  ✅ Tendência 4H ({trend_4h_val})")
    lines.append("")

    # ── Trend Multi-Timeframe ─────────────────────────────────────────────────
    lines.append("━━ Trend Multi-Timeframe ━━")
    for tf in ("4H", "1H", "15m"):
        ts_data  = trend_states.get(tf, {})
        trend    = ts_data.get("trend", "neutral")
        last_bos = ts_data.get("last_bos")
        if last_bos:
            bos_type  = last_bos.get("type", "BOS")
            bos_dir   = last_bos.get("direction", "")
            bos_price = last_bos.get("price", 0.0)
            bos_ts    = _ts_to_str(last_bos.get("ts", 0))
            bos_info  = f"(última {bos_type}: {bos_dir} @ {bos_price:.4f} em {bos_ts})"
        else:
            bos_info = "(—)"
        lines.append(f"{tf}: {trend}  {bos_info}")
    lines.append("")

    # ── Zona de Entrada ───────────────────────────────────────────────────────
    entry_src_label = {
        "fvg":           "via FVG midpoint",
        "ob_edge":       "via borda interna do OB",
        "current_price": "via preço atual (fallback)",
    }.get(entry_source, entry_source)
    tp1_src_label = {
        "structural": "via target estrutural",
        "math":       f"via R:R 1:{_MIN_RR}",
    }.get(tp1_source, tp1_source)

    lines.append("━━ Zona de Entrada ━━")
    lines.append(f"Entrada sugerida: `{entry:.4f}` ({entry_src_label})")
    if entry_zone_valid:
        lines.append(
            f"Zona válida: `{entry_zone_valid['bottom']:.4f}` – "
            f"`{entry_zone_valid['top']:.4f}`"
        )
    lines.append(f"SL: `{sl:.4f}` (swing estrutural + buffer)")
    lines.append(f"TP1: `{tp1:.4f}` ({tp1_src_label})")
    lines.append(f"R:R: {rr:.2f}")
    lines.append("")

    # ── Indicadores 1H Detalhados ─────────────────────────────────────────────
    lines.append("━━ Indicadores 1H Detalhados ━━")

    if ref_ob:
        ob_type_label = ref_ob.get("type", "")
        disp_pct      = ref_ob.get("displacement", 0.0) * 100
        lines.append(f"OB referência ({ob_type_label}):")
        lines.append(f"  range: `{ref_ob['bottom']:.4f}` – `{ref_ob['top']:.4f}`")
        lines.append(f"  volume: `{ref_ob.get('volume', 0.0):.4f}`")
        lines.append(f"  displacement: `{disp_pct:.2f}%`")
    else:
        lines.append("OB referência: —")

    if ref_fvg:
        fvg_type_label = ref_fvg.get("type", "")
        lines.append(f"FVG adjacente ({fvg_type_label}):")
        lines.append(f"  range: `{ref_fvg['bottom']:.4f}` – `{ref_fvg['top']:.4f}`")
        lines.append(f"  midpoint: `{ref_fvg.get('midpoint', 0.0):.4f}`")
        lines.append(f"  status: {ref_fvg.get('status', 'active')}")
    else:
        lines.append("FVG adjacente: —")

    if ref_sweep and ref_sweep_tf:
        sweep_age = (now_ms - ref_sweep.get("ts", now_ms)) // _TF_DURATION_MS.get(ref_sweep_tf, 1)
        lines.append(f"Sweep recente ({ref_sweep_tf}):")
        lines.append(f"  direção: {ref_sweep.get('direction', '')}")
        lines.append(f"  preço varrido: `{ref_sweep.get('swept_price', 0.0):.4f}`")
        lines.append(f"  idade: {sweep_age} candles")
    else:
        lines.append("Sweep recente: —")

    if pd_details:
        pd_label = pd_details.get("label", "equilibrium")
        pd_pos   = pd_details.get("position", 0.5)
        pd_sh    = pd_details.get("swing_high", 0.0)
        pd_sl    = pd_details.get("swing_low", 0.0)
        pd_eq    = pd_details.get("equilibrium", 0.0)
        lines.append("Premium/Discount (1H):")
        lines.append(f"  posição: {pd_pos:.2f} ({pd_label})")
        lines.append(f"  swing_high: `{pd_sh:.4f}`")
        lines.append(f"  swing_low: `{pd_sl:.4f}`")
        lines.append(f"  equilibrium: `{pd_eq:.4f}`")
    lines.append("")

    # ── Critérios atingidos ───────────────────────────────────────────────────
    lines.append("━━ Critérios atingidos ━━")
    for key, label in _CRITERIA_LABELS.items():
        icon = "✅" if criteria.get(key) else "❌"
        lines.append(f"  {icon} {label}")

    return "\n".join(lines)


def evaluate_events(token: str, engine: SMCEngine) -> list[dict]:
    """
    OBJETIVO: detectar eventos novos (BOS/ChoCH, sweep, trend change 4H)
              comparando estado atual do engine contra cache _event_tracking.
    FONTE DE DADOS: engine.get_state() para cada TF; _event_tracking para
                    último ts e valor notificado por chave.
    LIMITAÇÕES CONHECIDAS:
      - trend_change só considera transições causadas por BOS/ChoCH confirmado
        (bootstrap neutral→bullish sem BOS ignorado);
      - dedup é por event_ts, não por hash do dict;
      - na primeira chamada por chave (cache None), priming silencioso:
        inicializa cache sem notificação.
    NÃO FAZER: não enviar Telegram aqui (responsabilidade do main.py);
               não persistir cache aqui (main decide quando save).

    Retorna lista de dicts de evento. Cada dict tem:
      {"event_type": "bos_choch"|"sweep"|"trend_change",
       "timeframe": "4H"|"1H"|"15m",
       "data": {...}}
    """
    events: list[dict] = []

    for tf in ("4H", "1H", "15m"):
        st = engine.get_state(token, tf)
        if not st.get("ready"):
            continue

        last_bos   = st.get("last_bos")
        last_sweep = st.get("last_sweep")

        # ── bos_choch ──────────────────────────────────────────────────────────
        if last_bos is not None:
            key    = (token, tf, "bos_choch")
            cached = _event_tracking.get(key)
            if cached is None:
                _event_tracking[key] = {"ts": last_bos["ts"], "value": None}
            elif last_bos["ts"] != cached["ts"]:
                events.append({
                    "event_type": "bos_choch",
                    "timeframe":  tf,
                    "data": {
                        "type":      last_bos.get("type", "BOS"),
                        "direction": last_bos.get("direction", ""),
                        "price":     last_bos.get("price", 0.0),
                        "ts":        last_bos["ts"],
                    },
                })
                _event_tracking[key] = {"ts": last_bos["ts"], "value": None}

        # ── sweep ──────────────────────────────────────────────────────────────
        if last_sweep is not None:
            key    = (token, tf, "sweep")
            cached = _event_tracking.get(key)
            if cached is None:
                _event_tracking[key] = {"ts": last_sweep["ts"], "value": None}
            elif last_sweep["ts"] != cached["ts"]:
                events.append({
                    "event_type": "sweep",
                    "timeframe":  tf,
                    "data": {
                        "direction":   last_sweep.get("direction", ""),
                        "swept_price": last_sweep.get("swept_price", 0.0),
                        "close":       last_sweep.get("close", 0.0),
                        "ts":          last_sweep["ts"],
                    },
                })
                _event_tracking[key] = {"ts": last_sweep["ts"], "value": None}

        # ── trend_change (4H only) ─────────────────────────────────────────────
        if tf == "4H" and last_bos is not None:
            current_trend = st.get("trend", "neutral")
            key    = (token, "4H", "trend_change")
            cached = _event_tracking.get(key)
            if cached is None:
                _event_tracking[key] = {"ts": last_bos["ts"], "value": current_trend}
            elif last_bos["ts"] != cached["ts"]:
                if current_trend != cached["value"]:
                    events.append({
                        "event_type": "trend_change",
                        "timeframe":  "4H",
                        "data": {
                            "from_trend":    cached["value"],
                            "to_trend":      current_trend,
                            "bos_type":      last_bos.get("type", "BOS"),
                            "bos_direction": last_bos.get("direction", ""),
                            "bos_price":     last_bos.get("price", 0.0),
                            "ts":            last_bos["ts"],
                        },
                    })
                # Always sync ts when a new BOS arrives, regardless of direction change
                _event_tracking[key] = {"ts": last_bos["ts"], "value": current_trend}

    return events


def format_event(event: dict, token: str) -> str:
    """Formata dict de evento para mensagem Markdown pronta para Telegram."""
    et   = event["event_type"]
    tf   = event["timeframe"]
    data = event["data"]

    if et == "bos_choch":
        ts_str = _ts_to_str(data["ts"])
        return (
            f"🔔 {data['type']} {tf} — {token}\n"
            f"Direção: {data['direction']}\n"
            f"Preço rompido: {data['price']:.4f}\n"
            f"Timestamp: {ts_str}"
        )

    if et == "sweep":
        ts_str = _ts_to_str(data["ts"])
        return (
            f"💧 Sweep {tf} — {token}\n"
            f"Direção: {data['direction']}\n"
            f"Preço varrido: {data['swept_price']:.4f}\n"
            f"Close do candle: {data['close']:.4f}\n"
            f"Timestamp: {ts_str}"
        )

    if et == "trend_change":
        ts_str = _ts_to_str(data["ts"])
        return (
            f"🔄 Trend 4H mudou — {token}\n"
            f"{data['from_trend']} → {data['to_trend']}\n"
            f"Causado por: {data['bos_type']} {data['bos_direction']} @ {data['bos_price']:.4f}\n"
            f"Timestamp: {ts_str}"
        )

    return f"[evento desconhecido: {et}]"


def load_event_tracking() -> None:
    """Popula _event_tracking a partir de state.load_event_tracking()."""
    global _event_tracking
    loaded = _state.load_event_tracking()
    _event_tracking.update(loaded)
    logger.info("event_tracking restaurado: %d entradas", len(loaded))


def persist_event_tracking() -> None:
    """Persiste _event_tracking via state.save_event_tracking()."""
    _state.save_event_tracking(_event_tracking)
