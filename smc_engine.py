# SMC Monitor — smc_engine.py
# Versão: 0.1.1

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
        OBJETIVO: detectar Order Blocks delegando à smc.ob e mapear o resultado
                  para o formato interno, preservando apenas OBs não-mitigados.
        FONTE DE DADOS: cycle_df e cycle_shl_df cacheados por _update_swings.
        LIMITAÇÕES CONHECIDAS: se _update_swings falhou, cycle_shl_df é None
                               e este método é abortado sem alterar o estado.
        NÃO FAZER: não re-implementar lógica de detecção de OB manualmente,
                   não incluir OBs já mitigados na lista active_obs.
        """
        state = self._states[token][timeframe]
        if self._cycle_df is None or self._cycle_shl_df is None:
            return
        try:
            import math
            df = self._cycle_df
            shl_df = self._cycle_shl_df
            ob_df = smc.ob(df, shl_df, close_mitigation=False)

            new_obs = []
            for i in range(len(ob_df)):
                ob_val = ob_df["OB"].iloc[i]
                if isinstance(ob_val, float) and math.isnan(ob_val):
                    continue
                mitigated_idx = ob_df["MitigatedIndex"].iloc[i]
                mitigated = not (isinstance(mitigated_idx, float) and math.isnan(mitigated_idx)) and float(mitigated_idx) > 0
                if mitigated:
                    continue
                ob_type = "bull" if float(ob_val) == 1 else "bear"
                pct = ob_df["Percentage"].iloc[i]
                displacement = float(pct) / 100.0 if not (isinstance(pct, float) and math.isnan(pct)) else 0.0
                ob_entry = {
                    "ts": int(df.index[i].timestamp() * 1000),
                    "type": ob_type,
                    "top": float(ob_df["Top"].iloc[i]),
                    "bottom": float(ob_df["Bottom"].iloc[i]),
                    "volume": float(ob_df["OBVolume"].iloc[i]),
                    "displacement": displacement,
                    "mitigated": False,
                }
                new_obs.append(ob_entry)
                logger.debug(
                    "%s/%s OB %s %.4f-%.4f disp=%.4f",
                    token, timeframe, ob_type, ob_entry["bottom"], ob_entry["top"], displacement,
                )

            state["active_obs"] = new_obs
        except Exception as exc:
            logger.warning(
                "%s/%s _update_order_blocks failed: %s", token, timeframe, exc
            )

    def _update_fvgs(self, token: str, timeframe: str) -> None:
        """
        OBJETIVO: detectar Fair Value Gaps delegando à smc.fvg e mapear o
                  resultado para o formato interno, com status derivado de
                  MitigatedIndex e posição relativa ao midpoint.
        FONTE DE DADOS: cycle_df cacheado por _update_swings.
        LIMITAÇÕES CONHECIDAS: se _update_swings falhou, cycle_df é None
                               e este método é abortado sem alterar o estado.
        NÃO FAZER: não re-implementar padrão de 3 velas, não aplicar filtro
                   FVG_MIN_SIZE (a lib não usa threshold — alinhamento intencional).
        """
        state = self._states[token][timeframe]
        if self._cycle_df is None:
            return
        try:
            import math
            df = self._cycle_df
            fvg_df = smc.fvg(df, join_consecutive=False)
            last_close = float(df["close"].iloc[-1])

            new_fvgs = []
            for i in range(len(fvg_df)):
                fvg_val = fvg_df["FVG"].iloc[i]
                if isinstance(fvg_val, float) and math.isnan(fvg_val):
                    continue
                top = float(fvg_df["Top"].iloc[i])
                bottom = float(fvg_df["Bottom"].iloc[i])
                midpoint = (top + bottom) / 2
                fvg_type = "bull" if float(fvg_val) == 1 else "bear"

                mitigated_idx = fvg_df["MitigatedIndex"].iloc[i]
                has_mitigation = not (isinstance(mitigated_idx, float) and math.isnan(mitigated_idx)) and float(mitigated_idx) > 0

                if has_mitigation:
                    # Determine partial vs fully mitigated from current price position
                    if fvg_type == "bull":
                        if last_close <= bottom:
                            status = "mitigated"
                        elif last_close <= midpoint:
                            status = "partial"
                        else:
                            status = "active"
                    else:
                        if last_close >= top:
                            status = "mitigated"
                        elif last_close >= midpoint:
                            status = "partial"
                        else:
                            status = "active"
                else:
                    status = "active"

                if status == "mitigated":
                    continue

                fvg_entry = {
                    "ts": int(df.index[i].timestamp() * 1000),
                    "type": fvg_type,
                    "top": top,
                    "bottom": bottom,
                    "midpoint": midpoint,
                    "status": status,
                }
                new_fvgs.append(fvg_entry)
                logger.debug(
                    "%s/%s FVG %s %.4f-%.4f status=%s",
                    token, timeframe, fvg_type, bottom, top, status,
                )

            state["active_fvgs"] = new_fvgs
        except Exception as exc:
            logger.warning(
                "%s/%s _update_fvgs failed: %s", token, timeframe, exc
            )

    def _update_premium_discount(self, token: str, timeframe: str) -> None:
        """
        OBJETIVO: classificar o preço atual como premium, discount ou equilibrium
                  em relação ao midpoint do range swing_high/swing_low.
        FONTE DE DADOS: swing_high e swing_low já atualizados neste ciclo por
                        _update_swings; último close do buffer circular.
        LIMITAÇÕES CONHECIDAS: requer swing_high > swing_low para ser significativo;
                               retorna equilibrium se swings ainda não estiverem
                               disponíveis (estado inicial).
        NÃO FAZER: não delegar à lib — cálculo trivial e próprio do projeto;
                   não usar médias móveis ou outros indicadores para o range.
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
        OBJETIVO: detectar varreduras de liquidez (liquidity sweeps) delegando
                  à smc.liquidity e mapeando o último pool varrido para last_sweep.
        FONTE DE DADOS: cycle_df e cycle_shl_df cacheados por _update_swings.
        LIMITAÇÕES CONHECIDAS: se _update_swings falhou, cycle_shl_df é None
                               e este método é abortado sem alterar o estado.
        NÃO FAZER: não detectar sweeps por comparação manual de wicks,
                   não usar LIQUIDITY_SWEEP_LOOKBACK para este cálculo.
        """
        state = self._states[token][timeframe]
        if self._cycle_df is None or self._cycle_shl_df is None:
            return
        try:
            import math
            df = self._cycle_df
            shl_df = self._cycle_shl_df
            liq_df = smc.liquidity(df, shl_df, range_percent=0.01)

            last_sweep = None
            for i in range(len(liq_df) - 1, -1, -1):
                liq_val = liq_df["Liquidity"].iloc[i]
                swept_val = liq_df["Swept"].iloc[i]
                if isinstance(liq_val, float) and math.isnan(liq_val):
                    continue
                if isinstance(swept_val, float) and math.isnan(swept_val):
                    continue
                if float(swept_val) <= 0:
                    continue
                level = float(liq_df["Level"].iloc[i])
                direction = "high" if float(liq_val) == 1 else "low"
                last_sweep = {
                    "ts": int(df.index[i].timestamp() * 1000),
                    "direction": direction,
                    "swept_price": level,
                    "close": float(df["close"].iloc[-1]),
                }
                logger.debug(
                    "%s/%s Sweep %s swept_price=%.4f",
                    token, timeframe, direction, level,
                )
                break

            if last_sweep is not None:
                state["last_sweep"] = last_sweep
        except Exception as exc:
            logger.warning(
                "%s/%s _update_sweeps failed: %s", token, timeframe, exc
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
