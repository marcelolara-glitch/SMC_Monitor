# SMC Monitor — signals.py
# Versão: 0.1.0

"""
OBJETIVO: Calcular score de confluência SMC e decidir emissão de sinal.
FONTE DE DADOS: estados SMC entregues pelo SMCEngine via get_state().
LIMITAÇÕES CONHECIDAS: requer todos os timeframes prontos (ready=True) para avaliar.
NÃO FAZER: sem cálculo SMC, sem conexão WebSocket, sem envio de mensagens Telegram.
"""

import logging
import time

import config
from smc_engine import SMCEngine

logger = logging.getLogger(__name__)

# Candle duration in milliseconds per timeframe
_TF_DURATION_MS: dict[str, int] = {
    "15m": 15 * 60 * 1_000,
    "1H":  60 * 60 * 1_000,
    "4H":  4  * 60 * 60 * 1_000,
}

# SL margin: 0.1% beyond the OB edge
_SL_MARGIN = 0.001

# Human-readable labels for each criterion (insertion-ordered)
_CRITERIA_LABELS: dict[str, str] = {
    "ob_active":           "OB ativo no 1H",
    "fvg_adjacent":        "FVG adjacente ao OB (1H)",
    "sweep_recent":        "Liquidity Sweep recente",
    "premium_discount_ok": "Zona Premium/Discount correta",
    "bos_choch_15m":       "BOS/ChoCH confirmado no 15m",
    "trend_4h_aligned":    "Tendência 4H alinhada",
}


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

    # Direction is determined exclusively by the 4H trend
    trend_4h = state_4h.get("trend", "neutral")
    if trend_4h == "neutral":
        logger.debug("%s: 4H trend neutral — no signal evaluated", token)
        return None

    direction = "LONG"  if trend_4h == "bullish" else "SHORT"
    ob_type   = "bull"  if direction == "LONG"   else "bear"

    now_ms = int(time.time() * 1_000)

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
    if ref_ob and active_fvgs_1h:
        ob_top    = ref_ob["top"]
        ob_bottom = ref_ob["bottom"]
        for fvg in active_fvgs_1h:
            # Zones overlap when neither is entirely above/below the other
            if fvg["bottom"] <= ob_top and fvg["top"] >= ob_bottom:
                fvg_adjacent = True
                break

    # ── Criterion 3: Recent liquidity sweep in 1H or 15m ─────────────────────
    sweep_recent = False
    for tf in ("1H", "15m"):
        sweep = engine.get_state(token, tf).get("last_sweep")
        if sweep:
            window_ms = 10 * _TF_DURATION_MS[tf]
            if (now_ms - sweep["ts"]) <= window_ms:
                sweep_recent = True
                break

    # ── Criterion 4: Price in Premium/Discount zone in 1H ────────────────────
    pd_1h = state_1h.get("premium_discount", "equilibrium")
    if direction == "LONG":
        premium_discount_ok = pd_1h == "discount"
    else:
        premium_discount_ok = pd_1h == "premium"

    # ── Criterion 5: BOS or ChoCH confirmed in 15m in trade direction ─────────
    bos_15m      = state_15m.get("last_bos")
    bos_choch_15m = (
        bos_15m is not None and bos_15m.get("direction") == ob_type
    )

    # ── Criterion 6: 4H trend aligned with trade direction ───────────────────
    trend_4h_aligned = (
        (direction == "LONG"  and trend_4h == "bullish") or
        (direction == "SHORT" and trend_4h == "bearish")
    )

    # ── Score ─────────────────────────────────────────────────────────────────
    criteria: dict[str, bool] = {
        "ob_active":           ob_active,
        "fvg_adjacent":        fvg_adjacent,
        "sweep_recent":        sweep_recent,
        "premium_discount_ok": premium_discount_ok,
        "bos_choch_15m":       bos_choch_15m,
        "trend_4h_aligned":    trend_4h_aligned,
    }
    score = sum(criteria.values())

    logger.info(
        "%s direction=%s score=%d/6 criteria=%s",
        token, direction, score, criteria,
    )

    if score < config.SIGNAL_THRESHOLD:
        return None

    # ── Entry zone ────────────────────────────────────────────────────────────
    if ref_ob:
        entry_zone = {"top": ref_ob["top"], "bottom": ref_ob["bottom"]}
    else:
        # Fallback when no OB found in the correct direction
        if direction == "LONG":
            ref_price  = state_1h.get("swing_low", 0.0)
        else:
            ref_price  = state_1h.get("swing_high", 0.0)
        entry_zone = {"top": ref_price, "bottom": ref_price}

    # ── Stop-loss price ───────────────────────────────────────────────────────
    if direction == "LONG":
        sl_price = entry_zone["bottom"] * (1.0 - _SL_MARGIN)
    else:
        sl_price = entry_zone["top"]    * (1.0 + _SL_MARGIN)

    # ── TP1: nearest FVG midpoint beyond the entry zone ───────────────────────
    if direction == "LONG":
        # Bull FVGs whose bottom sits above the entry zone top
        candidates = [
            fvg for fvg in active_fvgs_1h
            if fvg["bottom"] > entry_zone["top"]
        ]
        tp1 = min(candidates, key=lambda f: f["bottom"])["midpoint"] if candidates else None
    else:
        # Bear FVGs whose top sits below the entry zone bottom
        candidates = [
            fvg for fvg in active_fvgs_1h
            if fvg["top"] < entry_zone["bottom"]
        ]
        tp1 = max(candidates, key=lambda f: f["top"])["midpoint"] if candidates else None

    return {
        "token":      token,
        "direction":  direction,
        "score":      score,
        "criteria":   criteria,
        "entry_zone": entry_zone,
        "sl_price":   sl_price,
        "tp1":        tp1,
        "timestamp":  now_ms,
    }


def format_signal(signal: dict) -> str:
    """
    Recebe o dict de sinal retornado por evaluate() e retorna string formatada
    pronta para envio via Telegram (Markdown Mode).
    """
    direction = signal["direction"]
    emoji     = "🟢" if direction == "LONG" else "🔴"
    token     = signal["token"]
    score     = signal["score"]
    ez        = signal["entry_zone"]
    sl        = signal["sl_price"]
    tp1       = signal["tp1"]
    criteria  = signal["criteria"]

    met_labels = [
        label for key, label in _CRITERIA_LABELS.items()
        if criteria.get(key)
    ]

    lines = [
        f"{emoji} *{direction} — {token}*",
        f"Score: *{score}/6*",
        "",
        f"Entrada: `{ez['bottom']:.4f}` – `{ez['top']:.4f}`",
        f"SL: `{sl:.4f}`",
        f"TP1: `{tp1:.4f}`" if tp1 is not None else "TP1: —",
        "",
        "*Critérios atingidos:*",
    ]
    for label in met_labels:
        lines.append(f"  ✅ {label}")

    return "\n".join(lines)
