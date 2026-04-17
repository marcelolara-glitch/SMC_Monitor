# SMC Monitor — smc_engine.py
# Versão: 0.1.0

"""
OBJETIVO: Mantém estado SMC completo por token/timeframe.
Recebe candles fechados e atualiza todos os conceitos SMC.
FONTE DE DADOS: Candles entregues pelo ws_feed via on_candle callback.
LIMITAÇÕES CONHECIDAS: Requer CANDLE_BUFFER mínimo antes de calcular.
NÃO FAZER: sem I/O, sem lógica de sinal, sem persistência.
"""

import collections
import logging
from typing import Dict

import pandas as pd
from smartmoneyconcepts import smc

import config

logger = logging.getLogger(__name__)


class SMCEngine:
    """
    OBJETIVO: Mantém estado SMC completo por token/timeframe.
    Recebe candles fechados e atualiza todos os conceitos SMC.
    FONTE DE DADOS: Candles entregues pelo ws_feed via on_candle callback.
    LIMITAÇÕES CONHECIDAS: Requer CANDLE_BUFFER mínimo antes de calcular.
    NÃO FAZER: sem I/O, sem lógica de sinal, sem persistência.
    """

    def __init__(self) -> None:
        # _buffers[token][timeframe] -> deque of candle dicts (oldest → newest)
        self._buffers: Dict[str, Dict[str, collections.deque]] = {}
        # _states[token][timeframe] -> SMC state dict
        self._states: Dict[str, Dict[str, dict]] = {}

    # ─── Public API ─────────────────────────────────────────────────────────────

    def on_candle(self, token: str, timeframe: str, candle: dict) -> None:
        """
        Recebe candle fechado, atualiza buffer e recalcula estado SMC.
        Chamado pelo ws_feed para cada candle com confirm==1.
        """
        if token not in self._buffers:
            self._buffers[token] = {}
            self._states[token] = {}

        max_len = config.CANDLE_BUFFER.get(timeframe, 100)

        if timeframe not in self._buffers[token]:
            self._buffers[token][timeframe] = collections.deque(maxlen=max_len)
            self._states[token][timeframe] = _empty_state()

        self._buffers[token][timeframe].append(candle)

        if len(self._buffers[token][timeframe]) < max_len:
            return  # buffer not yet full — not enough history to calculate

        self._update_swings(token, timeframe)
        self._update_bos_choch(token, timeframe)
        self._update_order_blocks(token, timeframe)
        self._update_fvgs(token, timeframe)
        self._update_premium_discount(token, timeframe)
        self._update_sweeps(token, timeframe)

        self._states[token][timeframe]["ready"] = True

    def get_state(self, token: str, timeframe: str) -> dict:
        """
        Retorna estado SMC atual para o par token/timeframe.
        Retorna dict vazio se buffer insuficiente.

        Retorno:
        {
            "ready": bool,
            "swing_high": float,
            "swing_low": float,
            "trend": str,            # "bullish" | "bearish" | "neutral"
            "last_bos": dict | None, # {"type": "BOS"|"ChoCH", "direction": "bull"|"bear",
                                     #  "price": float, "ts": int}
            "active_obs": list,
            "active_fvgs": list,
            "premium_discount": str, # "premium" | "discount" | "equilibrium"
            "last_sweep": dict | None,
        }
        """
        try:
            return self._states[token][timeframe]
        except KeyError:
            return {}

    def get_all_states(self) -> dict:
        """
        Retorna estados de todos os pares token/timeframe.
        Usado pelo state.py para persistência.
        """
        return {
            token: dict(tf_states)
            for token, tf_states in self._states.items()
        }

    # ─── Private helpers ────────────────────────────────────────────────────────

    def _candles(self, token: str, timeframe: str) -> list:
        """Buffer como lista simples oldest → newest."""
        return list(self._buffers[token][timeframe])

    def _buffer_to_dataframe(self, buffer) -> pd.DataFrame:
        """
        OBJETIVO: converter deque de candles em DataFrame pandas pronto para
                  uso com a smartmoneyconcepts lib.
        FONTE DE DADOS: buffer circular mantido por on_candle.
        LIMITAÇÕES CONHECIDAS: requer que os dicts no buffer tenham as keys
                               ts, open, high, low, close, volume.
        NÃO FAZER: não alterar a ordem dos candles, não filtrar candles.
        """
        rows = list(buffer)
        df = pd.DataFrame(rows)
        df["datetime"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
        df = df.set_index("datetime")
        return df[["open", "high", "low", "close", "volume"]]

    # ─── SMC update methods ─────────────────────────────────────────────────────

    def _update_swings(self, token: str, timeframe: str) -> None:
        """Detecta swing highs/lows usando SWING_LOOKBACK velas para cada lado."""
        candles = self._candles(token, timeframe)
        swing_highs, swing_lows = self._swing_points(candles)

        state = self._states[token][timeframe]

        if swing_highs:
            # most recent confirmed swing high
            state["swing_high"] = swing_highs[-1]["price"]

        if swing_lows:
            state["swing_low"] = swing_lows[-1]["price"]

    def _update_bos_choch(self, token: str, timeframe: str) -> None:
        """
        BOS: preço fecha além do último swing high/low na direção da tendência.
        ChoCH: preço fecha além do swing oposto (reversão).
        Usa fechamento de vela (body break), nunca wick.
        """
        candles = self._candles(token, timeframe)
        state = self._states[token][timeframe]
        swing_highs, swing_lows = self._swing_points(candles)

        if not swing_highs or not swing_lows:
            return

        last_sh = swing_highs[-1]["price"]
        last_sl = swing_lows[-1]["price"]
        last_close = candles[-1]["close"]
        last_ts = candles[-1]["ts"]
        trend = state["trend"]

        # Bootstrap trend from swing index positions when still neutral
        if trend == "neutral":
            if swing_highs[-1]["idx"] > swing_lows[-1]["idx"]:
                trend = "bullish"
            elif swing_lows[-1]["idx"] > swing_highs[-1]["idx"]:
                trend = "bearish"

        new_bos = None

        if last_close > last_sh:
            # break of the most recent swing high
            bos_type = "BOS" if trend == "bullish" else "ChoCH"
            new_bos = {
                "type": bos_type,
                "direction": "bull",
                "price": last_sh,
                "ts": last_ts,
            }
            trend = "bullish"

        elif last_close < last_sl:
            # break of the most recent swing low
            bos_type = "BOS" if trend == "bearish" else "ChoCH"
            new_bos = {
                "type": bos_type,
                "direction": "bear",
                "price": last_sl,
                "ts": last_ts,
            }
            trend = "bearish"

        if new_bos:
            state["last_bos"] = new_bos
            logger.debug(
                "%s/%s %s direction=%s price=%.4f",
                token, timeframe, new_bos["type"], new_bos["direction"], new_bos["price"],
            )

        state["trend"] = trend

    def _update_order_blocks(self, token: str, timeframe: str) -> None:
        """
        OB bullish: última vela de baixa antes de movimento de alta forte.
        OB bearish: última vela de alta antes de movimento de baixa forte.
        Score: volume relativo + magnitude do deslocamento subsequente.
        Invalida OBs cujo range foi completamente mitigado pelo preço.
        """
        candles = self._candles(token, timeframe)
        state = self._states[token][timeframe]
        last_close = candles[-1]["close"]
        min_disp = config.OB_MIN_DISPLACEMENT

        # Invalidate fully mitigated OBs
        for ob in state["active_obs"]:
            if ob["mitigated"]:
                continue
            if ob["type"] == "bull" and last_close < ob["bottom"]:
                ob["mitigated"] = True
            elif ob["type"] == "bear" and last_close > ob["top"]:
                ob["mitigated"] = True

        state["active_obs"] = [ob for ob in state["active_obs"] if not ob["mitigated"]]

        # Build index of already-tracked OBs to avoid duplicates
        tracked: set = {(ob["ts"], ob["type"]) for ob in state["active_obs"]}

        # Detect new OBs: scan pairs (candle[i], candle[i+1])
        for i in range(len(candles) - 1):
            c = candles[i]
            c_next = candles[i + 1]

            # Bullish OB: bearish candle followed by strong bullish impulse
            if c["close"] < c["open"]:
                displacement = (c_next["close"] - c_next["open"]) / c["close"]
                if displacement > min_disp and (c["ts"], "bull") not in tracked:
                    ob = {
                        "ts": c["ts"],
                        "type": "bull",
                        "top": c["open"],
                        "bottom": c["close"],
                        "volume": c["volume"],
                        "displacement": displacement,
                        "mitigated": False,
                    }
                    state["active_obs"].append(ob)
                    tracked.add((c["ts"], "bull"))
                    logger.debug(
                        "%s/%s New bull OB %.4f-%.4f disp=%.4f",
                        token, timeframe, ob["bottom"], ob["top"], displacement,
                    )

            # Bearish OB: bullish candle followed by strong bearish impulse
            elif c["close"] > c["open"]:
                displacement = (c_next["open"] - c_next["close"]) / c["close"]
                if displacement > min_disp and (c["ts"], "bear") not in tracked:
                    ob = {
                        "ts": c["ts"],
                        "type": "bear",
                        "top": c["close"],
                        "bottom": c["open"],
                        "volume": c["volume"],
                        "displacement": displacement,
                        "mitigated": False,
                    }
                    state["active_obs"].append(ob)
                    tracked.add((c["ts"], "bear"))
                    logger.debug(
                        "%s/%s New bear OB %.4f-%.4f disp=%.4f",
                        token, timeframe, ob["bottom"], ob["top"], displacement,
                    )

    def _update_fvgs(self, token: str, timeframe: str) -> None:
        """
        FVG: gap entre low[i] e high[i-2] (bullish) ou high[i] e low[i-2] (bearish).
        Tamanho mínimo: FVG_MIN_SIZE * preço atual.
        Rastreia mitigação pela mediana (50% do FVG).
        Status: "active" | "partial" | "mitigated".
        """
        candles = self._candles(token, timeframe)
        state = self._states[token][timeframe]
        last_close = candles[-1]["close"]
        min_size = config.FVG_MIN_SIZE * last_close

        # Update mitigation status on surviving FVGs
        for fvg in state["active_fvgs"]:
            if fvg["status"] == "mitigated":
                continue
            mid = fvg["midpoint"]
            if fvg["type"] == "bull":
                # Bullish FVG mitigated when price drops below its bottom
                if last_close <= fvg["bottom"]:
                    fvg["status"] = "mitigated"
                elif last_close <= mid:
                    fvg["status"] = "partial"
            else:  # bear
                # Bearish FVG mitigated when price rises above its top
                if last_close >= fvg["top"]:
                    fvg["status"] = "mitigated"
                elif last_close >= mid:
                    fvg["status"] = "partial"

        state["active_fvgs"] = [f for f in state["active_fvgs"] if f["status"] != "mitigated"]

        # Build index to avoid duplicates
        tracked: set = {(f["ts"], f["type"]) for f in state["active_fvgs"]}

        # Detect new FVGs using three-candle pattern: c0, c1, c2
        for i in range(2, len(candles)):
            c0 = candles[i - 2]
            c2 = candles[i]

            # Bullish FVG: low[i] > high[i-2]
            if c2["low"] > c0["high"]:
                gap_bottom = c0["high"]
                gap_top = c2["low"]
                if (gap_top - gap_bottom) >= min_size and (c2["ts"], "bull") not in tracked:
                    fvg = {
                        "ts": c2["ts"],
                        "type": "bull",
                        "top": gap_top,
                        "bottom": gap_bottom,
                        "midpoint": (gap_top + gap_bottom) / 2,
                        "status": "active",
                    }
                    state["active_fvgs"].append(fvg)
                    tracked.add((c2["ts"], "bull"))
                    logger.debug(
                        "%s/%s New bull FVG %.4f-%.4f",
                        token, timeframe, gap_bottom, gap_top,
                    )

            # Bearish FVG: high[i] < low[i-2]
            elif c2["high"] < c0["low"]:
                gap_top = c0["low"]
                gap_bottom = c2["high"]
                if (gap_top - gap_bottom) >= min_size and (c2["ts"], "bear") not in tracked:
                    fvg = {
                        "ts": c2["ts"],
                        "type": "bear",
                        "top": gap_top,
                        "bottom": gap_bottom,
                        "midpoint": (gap_top + gap_bottom) / 2,
                        "status": "active",
                    }
                    state["active_fvgs"].append(fvg)
                    tracked.add((c2["ts"], "bear"))
                    logger.debug(
                        "%s/%s New bear FVG %.4f-%.4f",
                        token, timeframe, gap_bottom, gap_top,
                    )

    def _update_premium_discount(self, token: str, timeframe: str) -> None:
        """
        Range = swing_high - swing_low.
        Equilibrium = 50% do range.
        Premium: preço atual > equilibrium.
        Discount: preço atual < equilibrium.
        """
        candles = self._candles(token, timeframe)
        state = self._states[token][timeframe]
        last_close = candles[-1]["close"]

        sh = state["swing_high"]
        sl = state["swing_low"]

        if sh <= sl or sh == 0.0:
            state["premium_discount"] = "equilibrium"
            return

        equilibrium = (sh + sl) / 2

        if last_close > equilibrium:
            state["premium_discount"] = "premium"
        elif last_close < equilibrium:
            state["premium_discount"] = "discount"
        else:
            state["premium_discount"] = "equilibrium"

    def _update_sweeps(self, token: str, timeframe: str) -> None:
        """
        Sweep: vela ultrapassa swing high/low E fecha de volta dentro do range.
        Indica captura de liquidez — pré-condição de entrada.
        """
        candles = self._candles(token, timeframe)
        state = self._states[token][timeframe]

        lb = config.LIQUIDITY_SWEEP_LOOKBACK
        if len(candles) <= lb:
            return

        last = candles[-1]
        lookback = candles[-(lb + 1):-1]  # lb candles before the last

        ref_high = max(c["high"] for c in lookback)
        ref_low = min(c["low"] for c in lookback)

        # Sweep of highs: wick pierces above ref_high but close falls back inside
        if last["high"] > ref_high and last["close"] < ref_high:
            state["last_sweep"] = {
                "ts": last["ts"],
                "direction": "high",
                "swept_price": ref_high,
                "close": last["close"],
            }
            logger.debug(
                "%s/%s Sweep high ref=%.4f close=%.4f",
                token, timeframe, ref_high, last["close"],
            )

        # Sweep of lows: wick pierces below ref_low but close recovers inside
        elif last["low"] < ref_low and last["close"] > ref_low:
            state["last_sweep"] = {
                "ts": last["ts"],
                "direction": "low",
                "swept_price": ref_low,
                "close": last["close"],
            }
            logger.debug(
                "%s/%s Sweep low ref=%.4f close=%.4f",
                token, timeframe, ref_low, last["close"],
            )


# ─── Module-level helpers ────────────────────────────────────────────────────

def _empty_state() -> dict:
    return {
        "ready": False,
        "swing_high": 0.0,
        "swing_low": 0.0,
        "trend": "neutral",
        "last_bos": None,
        "active_obs": [],
        "active_fvgs": [],
        "premium_discount": "equilibrium",
        "last_sweep": None,
    }
