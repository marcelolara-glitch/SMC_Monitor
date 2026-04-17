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
        ok, msg = _smoke_test_library()
        if not ok:
            raise RuntimeError(f"smartmoneyconcepts smoke test failed: {msg}")

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

        # Per-cycle DataFrame cache: set by _update_swings, consumed by siblings.
        self._cycle_df = None
        self._cycle_shl_df = None

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
        """
        OBJETIVO: detectar swing highs/lows delegando o cálculo à
                  smartmoneyconcepts via smc.swing_highs_lows.
        FONTE DE DADOS: buffer circular convertido em DataFrame.
        LIMITAÇÕES CONHECIDAS: swing_length mínimo exige buffer suficiente;
                               a lib retorna NaN nas bordas do DataFrame.
        NÃO FAZER: não calcular swings manualmente, não usar wick sem
                   confirmação de SWING_LOOKBACK velas em cada lado.
        """
        state = self._states[token][timeframe]
        try:
            df = self._buffer_to_dataframe(self._buffers[token][timeframe])
            shl_df = smc.swing_highs_lows(df, swing_length=config.SWING_LOOKBACK)

            highs = shl_df[shl_df["HighLow"] == 1]["Level"].dropna()
            lows = shl_df[shl_df["HighLow"] == -1]["Level"].dropna()

            if not highs.empty:
                state["swing_high"] = float(highs.iloc[-1])
            if not lows.empty:
                state["swing_low"] = float(lows.iloc[-1])

            # cache for reuse in subsequent _update_* calls this cycle
            self._cycle_df = df
            self._cycle_shl_df = shl_df
        except Exception as exc:
            logger.warning(
                "%s/%s _update_swings failed: %s", token, timeframe, exc
            )

    def _update_bos_choch(self, token: str, timeframe: str) -> None:
        """
        OBJETIVO: detectar Break of Structure (BOS) e Change of Character (ChoCH)
                  delegando à smc.bos_choch com close_break=True.
        FONTE DE DADOS: cycle_df e cycle_shl_df cacheados por _update_swings.
        LIMITAÇÕES CONHECIDAS: se _update_swings falhou, cycle_shl_df é None
                               e este método é abortado sem alterar o estado.
        NÃO FAZER: não derivar BOS/ChoCH de comparação manual de closes,
                   não usar wick para confirmar quebra.
        """
        state = self._states[token][timeframe]
        if self._cycle_df is None or self._cycle_shl_df is None:
            return
        try:
            df = self._cycle_df
            shl_df = self._cycle_shl_df
            bos_df = smc.bos_choch(df, shl_df, close_break=True)

            # Find last row with BOS or CHOCH signal
            new_bos = None
            for i in range(len(bos_df) - 1, -1, -1):
                bos_val = bos_df["BOS"].iloc[i]
                choch_val = bos_df["CHOCH"].iloc[i]
                import math
                bos_set = not (isinstance(bos_val, float) and math.isnan(bos_val))
                choch_set = not (isinstance(choch_val, float) and math.isnan(choch_val))
                if bos_set or choch_set:
                    level = float(bos_df["Level"].iloc[i])
                    ts_ms = int(df.index[i].timestamp() * 1000)
                    if bos_set:
                        sig_type = "BOS"
                        direction = "bull" if float(bos_val) == 1 else "bear"
                    else:
                        sig_type = "ChoCH"
                        direction = "bull" if float(choch_val) == 1 else "bear"
                    new_bos = {
                        "type": sig_type,
                        "direction": direction,
                        "price": level,
                        "ts": ts_ms,
                    }
                    break

            if new_bos:
                state["last_bos"] = new_bos
                state["trend"] = "bullish" if new_bos["direction"] == "bull" else "bearish"
                logger.debug(
                    "%s/%s %s direction=%s price=%.4f",
                    token, timeframe, new_bos["type"], new_bos["direction"], new_bos["price"],
                )
        except Exception as exc:
            logger.warning(
                "%s/%s _update_bos_choch failed: %s", token, timeframe, exc
            )

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

def _smoke_test_library() -> tuple:
    """
    OBJETIVO: validar que a smartmoneyconcepts instalada retorna as colunas
              esperadas pelo engine. Se a API da lib mudou entre versões,
              detectar imediatamente e abortar o boot.
    FONTE DE DADOS: DataFrame sintético com 60 candles gerados com seed fixa
                    (42) para reprodutibilidade.
    LIMITAÇÕES CONHECIDAS: não valida correção semântica dos cálculos,
                           apenas a estrutura de retorno.
    NÃO FAZER: não usar dados reais (depende de rede), não depender de
               config.py (pode não estar carregado).

    Retorna (success: bool, message: str).
    """
    import numpy as np
    import importlib.metadata

    try:
        lib_version = importlib.metadata.version("smartmoneyconcepts")
    except Exception:
        lib_version = "unknown"

    try:
        rng = np.random.default_rng(42)
        n = 60
        base = 30000.0
        closes = base + np.cumsum(rng.normal(0, 100, n))
        opens = np.roll(closes, 1)
        opens[0] = base
        highs = np.maximum(opens, closes) + rng.uniform(10, 80, n)
        lows = np.minimum(opens, closes) - rng.uniform(10, 80, n)
        volumes = rng.uniform(100, 1000, n)

        idx = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
        df = pd.DataFrame({
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
        }, index=idx)

        expected = {
            "swing_highs_lows": ["HighLow", "Level"],
            "bos_choch": ["BOS", "CHOCH", "Level", "BrokenIndex"],
            "ob": ["OB", "Top", "Bottom", "OBVolume", "MitigatedIndex", "Percentage"],
            "fvg": ["FVG", "Top", "Bottom", "MitigatedIndex"],
            "liquidity": ["Liquidity", "Level", "End", "Swept"],
        }

        shl_df = smc.swing_highs_lows(df, swing_length=5)
        results = {
            "swing_highs_lows": shl_df,
            "bos_choch": smc.bos_choch(df, shl_df, close_break=True),
            "ob": smc.ob(df, shl_df, close_mitigation=False),
            "fvg": smc.fvg(df, join_consecutive=False),
            "liquidity": smc.liquidity(df, shl_df, range_percent=0.01),
        }

        for func_name, cols in expected.items():
            result_df = results[func_name]
            for col in cols:
                if col not in result_df.columns:
                    return (
                        False,
                        f"coluna '{col}' ausente em '{func_name}' na versão {lib_version} da lib",
                    )

        return (True, "ok")

    except Exception as exc:
        return (False, f"exceção durante smoke test (versão {lib_version}): {exc}")


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
