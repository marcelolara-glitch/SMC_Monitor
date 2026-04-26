# SMC Monitor — smc_engine.py
# Versão: 0.1.10

"""
OBJETIVO: Mantém estado SMC completo por token/timeframe.
Recebe candles fechados e atualiza todos os conceitos SMC.
FONTE DE DADOS: Candles entregues pelo ws_feed via on_candle callback.
LIMITAÇÕES CONHECIDAS: Requer CANDLE_BUFFER mínimo antes de calcular.
NÃO FAZER: sem I/O, sem lógica de sinal, sem persistência.
"""

import collections
import logging
import math
from typing import Dict

import pandas as pd
from smartmoneyconcepts import smc

import config
from lib_version_check import get_lib_version

VERSION = "0.1.10"

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
        # True only during bootstrap_from_history(); guards on_candle against
        # concurrent calls while historical data is being loaded.
        self._bootstrapping: bool = False
        ok, msg = _smoke_test_library()
        if not ok:
            raise RuntimeError(f"smartmoneyconcepts smoke test failed: {msg}")

    # ─── Public API ─────────────────────────────────────────────────────────────

    def on_candle(self, token: str, timeframe: str, candle: dict) -> None:
        """
        Recebe candle fechado, atualiza buffer e recalcula estado SMC.
        Chamado pelo ws_feed para cada candle com confirm==1.
        """
        if self._bootstrapping:
            return  # historical warm-up in progress; ignore live candles

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
        self._update_atr(token, timeframe)

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
            "all_bos": list,         # cronologicamente ordenado (oldest → newest)
            "active_obs": list,
            "active_fvgs": list,
            "premium_discount": str, # "premium" | "discount" | "equilibrium"
            "pd_reference_range": dict | None,  # {"top": float, "bottom": float,
                                                 #  "source": "ob" | "swing"}
            "pd_position": float | None,        # clamp em [0.0, 1.0]
            "pd_position_raw": float | None,    # valor antes do clamp (debug)
            "pd_label": str,         # "premium" | "discount" | "equilibrium"
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

    # ─── Bootstrap (Passo 12) ────────────────────────────────────────────────────

    def bootstrap_from_history(self, dfs_by_tf: dict) -> None:
        """
        OBJETIVO:
            Popular o buffer circular do engine com candles históricos
            pré-validados, antes do WebSocket começar a enviar candles
            em tempo real. Recalcular todos os indicadores SMC baseado
            nesse histórico.

        FONTE DE DADOS:
            DataFrames fornecidos pelo historical_loader — já auditados
            e com lacunas preenchidas.

        LIMITAÇÕES CONHECIDAS:
            Assume que os DataFrames estão ordenados por timestamp
            ascendente e têm schema OHLCV (Open, High, Low, Close, Volume).
            Não revalida integridade — confia no historical_loader.
            Usa config.TOKENS[0] como token canônico.

        NÃO FAZER:
            Não emitir sinais durante o bootstrap — apenas popular estado.
            Não persistir candles no SQLite (são candles históricos,
            não devem alimentar candle_buffer persistido).
        """
        self._bootstrapping = True
        try:
            token = config.TOKENS[0]
            for tf, df in dfs_by_tf.items():
                if df.empty:
                    continue
                self._populate_buffer(token, tf, df)

            self._recompute_all_indicators(token)
        finally:
            self._bootstrapping = False

    def _populate_buffer(self, token: str, tf: str, df: pd.DataFrame) -> None:
        """
        OBJETIVO: Popular buffer circular de token/tf a partir de DataFrame histórico.
        FONTE DE DADOS: DataFrame com índice UTC e colunas OHLCV.
        LIMITAÇÕES CONHECIDAS: Trunca df para os últimos maxlen candles (igual ao buffer).
        NÃO FAZER: Não revalidar integridade — confia no historical_loader.
        """
        max_len = config.CANDLE_BUFFER.get(tf, 100)

        if token not in self._buffers:
            self._buffers[token] = {}
            self._states[token] = {}
        if tf not in self._buffers[token]:
            self._buffers[token][tf] = collections.deque(maxlen=max_len)
            self._states[token][tf] = _empty_state()

        buf = self._buffers[token][tf]
        recent = df.iloc[-max_len:]
        for ts, row in recent.iterrows():
            ts_ms = int(ts.timestamp() * 1000)
            buf.append({
                "ts": ts_ms,
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row["volume"]),
            })

    def _recompute_all_indicators(self, token: str) -> None:
        """
        OBJETIVO: Recalcular todos os indicadores SMC para token após popular buffers.
        FONTE DE DADOS: Buffers internos preenchidos por _populate_buffer.
        LIMITAÇÕES CONHECIDAS: Só processa TFs com buffer completo (>= maxlen).
        NÃO FAZER: Não emitir sinais — apenas atualizar estado interno.
        """
        for tf in config.TIMEFRAMES:
            if token not in self._buffers or tf not in self._buffers[token]:
                continue
            buf = self._buffers[token][tf]
            max_len = config.CANDLE_BUFFER.get(tf, 100)
            if len(buf) < max_len:
                continue

            self._cycle_df = None
            self._cycle_shl_df = None

            self._update_swings(token, tf)
            self._update_bos_choch(token, tf)
            self._update_order_blocks(token, tf)
            self._update_fvgs(token, tf)
            self._update_premium_discount(token, tf)
            self._update_sweeps(token, tf)
            self._update_atr(token, tf)

            self._states[token][tf]["ready"] = True
            logger.info("bootstrap: %s/%s ready após %d candles", token, tf, len(buf))

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
                  delegando à smc.bos_choch com close_break=True. Popula a lista
                  cronológica state["all_bos"] e o atalho state["last_bos"].
        FONTE DE DADOS: cycle_df e cycle_shl_df cacheados por _update_swings.
        LIMITAÇÕES CONHECIDAS: se _update_swings falhou, cycle_shl_df é None
                               e este método é abortado sem alterar o estado.
                               state["all_bos"] reflete apenas os BOSes visíveis
                               no buffer atual; BOSes fora da janela somem.
        NÃO FAZER: não derivar BOS/ChoCH de comparação manual de closes,
                   não usar wick para confirmar quebra,
                   não deduplicar aqui (isso é responsabilidade do signals).
        """
        state = self._states[token][timeframe]
        if self._cycle_df is None or self._cycle_shl_df is None:
            return
        try:
            df = self._cycle_df
            shl_df = self._cycle_shl_df
            bos_df = smc.bos_choch(df, shl_df, close_break=True)

            new_bos_list: list[dict] = []
            for i in range(len(bos_df)):
                bos_val = bos_df["BOS"].iloc[i]
                choch_val = bos_df["CHOCH"].iloc[i]
                bos_set = not pd.isna(bos_val)
                choch_set = not pd.isna(choch_val)
                if not (bos_set or choch_set):
                    continue

                level_val = bos_df["Level"].iloc[i]
                if pd.isna(level_val):
                    continue

                ts_ms = int(df.index[i].timestamp() * 1000)
                if bos_set:
                    sig_type = "BOS"
                    direction = "bull" if float(bos_val) == 1 else "bear"
                else:
                    sig_type = "ChoCH"
                    direction = "bull" if float(choch_val) == 1 else "bear"

                new_bos_list.append({
                    "type": sig_type,
                    "direction": direction,
                    "price": float(level_val),
                    "ts": ts_ms,
                })

            state["all_bos"] = new_bos_list
            if new_bos_list:
                last = new_bos_list[-1]
                state["last_bos"] = last
                state["trend"] = "bullish" if last["direction"] == "bull" else "bearish"
                logger.debug(
                    "%s/%s %s direction=%s price=%.4f total=%d",
                    token, timeframe, last["type"], last["direction"], last["price"],
                    len(new_bos_list),
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
                  em relação ao range de referência do timeframe e gravar no state
                  os campos consolidados pd_reference_range, pd_position,
                  pd_position_raw e pd_label. O cálculo é centralizado aqui para
                  que signals.py e bot_handler.py consumam a mesma fonte.
        FONTE DE DADOS:
            1) OB ativo não-mitigado mais recente do timeframe (preferência);
            2) swing_high/swing_low do timeframe (fallback).
            Último close do buffer circular do timeframe.
        LIMITAÇÕES CONHECIDAS:
            - Range dos swings pode capturar microswings curtos;
              por isso preferimos OB quando disponível.
            - Se nenhum range válido existe, pd_position fica None e o label
              cai em equilibrium.
            - pd_position é clampado em [0.0, 1.0]; o valor cru fica em
              pd_position_raw para debug/inspeção.
        NÃO FAZER: não delegar à lib (cálculo trivial);
                   não usar médias móveis ou outros indicadores para o range;
                   não recalcular em signals.py — consumir state consolidado.
        """
        candles = self._candles(token, timeframe)
        state = self._states[token][timeframe]
        last_close = float(candles[-1]["close"])

        range_top = 0.0
        range_bottom = 0.0
        source = None

        # Preferência 1: OB ativo não-mitigado mais recente (qualquer direção)
        active_obs = [
            ob for ob in state.get("active_obs", [])
            if not ob.get("mitigated", False)
        ]
        if active_obs:
            ref_ob = max(active_obs, key=lambda o: o.get("ts", 0))
            ob_top = float(ref_ob.get("top", 0.0))
            ob_bottom = float(ref_ob.get("bottom", 0.0))
            if ob_top > ob_bottom:
                range_top = ob_top
                range_bottom = ob_bottom
                source = "ob"

        # Preferência 2 (fallback): range dos swings
        if source is None:
            sh = float(state.get("swing_high", 0.0))
            sl = float(state.get("swing_low", 0.0))
            if sh > sl > 0.0:
                range_top = sh
                range_bottom = sl
                source = "swing"

        if source is None or range_top <= range_bottom:
            state["pd_reference_range"] = None
            state["pd_position"] = None
            state["pd_position_raw"] = None
            state["pd_label"] = "equilibrium"
            state["premium_discount"] = "equilibrium"
            return

        equilibrium = (range_top + range_bottom) / 2.0
        raw_position = (last_close - range_bottom) / (range_top - range_bottom)
        clamped_position = max(0.0, min(1.0, raw_position))

        if last_close > equilibrium:
            label = "premium"
        elif last_close < equilibrium:
            label = "discount"
        else:
            label = "equilibrium"

        state["pd_reference_range"] = {
            "top": range_top,
            "bottom": range_bottom,
            "source": source,
        }
        state["pd_position"] = clamped_position
        state["pd_position_raw"] = raw_position
        state["pd_label"] = label
        state["premium_discount"] = label

    def _update_atr(self, token: str, timeframe: str) -> None:
        """
        OBJETIVO: calcular ATR_14 sobre o buffer do timeframe.
        FONTE DE DADOS: buffer circular.
        LIMITAÇÕES CONHECIDAS: retorna 0.0 se buffer < 15 candles.
        NÃO FAZER: não usar lib externa (cálculo trivial).
        """
        state = self._states[token][timeframe]
        candles = list(self._buffers[token][timeframe])
        if len(candles) < 15:
            state["atr_14"] = 0.0
            return
        trs = []
        for i in range(1, len(candles)):
            high = candles[i]["high"]
            low = candles[i]["low"]
            prev_close = candles[i - 1]["close"]
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            trs.append(tr)
        recent_trs = trs[-14:]
        state["atr_14"] = sum(recent_trs) / len(recent_trs)

    def _update_sweeps(self, token: str, timeframe: str) -> None:
        """
        OBJETIVO: detectar varreduras de liquidez (liquidity sweeps) delegando
                  à smc.liquidity, filtrando apenas pools realmente varridas,
                  e mapear o sweep mais recente (por timestamp do candle que
                  consumou o sweep) para state["last_sweep"].
        FONTE DE DADOS: cycle_df e cycle_shl_df cacheados por _update_swings.
        LIMITAÇÕES CONHECIDAS:
            - A coluna "Liquidity" retorna TODAS as pools identificadas,
              não apenas as varridas — a distinção real vem de "Swept" não-NaN.
            - "Swept" é o índice da vela onde o sweep foi consumado, não um
              booleano. Pools não-varridas vêm com Swept=NaN.
            - "Level" pode vir NaN quando a lib não resolveu o preço; essas
              entradas são descartadas (evita propagar NaN como swept_price).
            - Se nenhum sweep válido é encontrado no ciclo atual,
              state["last_sweep"] é preservado (sweep antigo continua sendo o
              último sweep conhecido).
        NÃO FAZER:
            - não detectar sweeps por comparação manual de wicks;
            - não usar LIQUIDITY_SWEEP_LOOKBACK para este cálculo;
            - não sobrescrever last_sweep com None se nada novo foi encontrado;
            - não usar o timestamp da detecção da pool; usar o timestamp do
              candle que fechou o sweep (df.index[int(Swept)]).
        """
        state = self._states[token][timeframe]
        if self._cycle_df is None or self._cycle_shl_df is None:
            return
        try:
            df = self._cycle_df
            shl_df = self._cycle_shl_df
            liq_df = smc.liquidity(df, shl_df, range_percent=0.01)

            valid_sweeps: list[dict] = []
            for i in range(len(liq_df)):
                liq_val = liq_df["Liquidity"].iloc[i]
                swept_val = liq_df["Swept"].iloc[i]
                level_val = liq_df["Level"].iloc[i]

                # Require all three non-NaN to consider this a real sweep
                if pd.isna(liq_val) or pd.isna(swept_val) or pd.isna(level_val):
                    continue

                swept_idx = int(swept_val)
                if swept_idx <= 0 or swept_idx >= len(df):
                    continue

                direction = "high" if float(liq_val) == 1 else "low"
                valid_sweeps.append({
                    "ts": int(df.index[swept_idx].timestamp() * 1000),
                    "direction": direction,
                    "swept_price": float(level_val),
                    "close": float(df["close"].iloc[swept_idx]),
                })

            if valid_sweeps:
                latest = max(valid_sweeps, key=lambda s: s["ts"])
                state["last_sweep"] = latest
                logger.debug(
                    "%s/%s Sweep %s swept_price=%.4f total_valid=%d",
                    token, timeframe, latest["direction"], latest["swept_price"],
                    len(valid_sweeps),
                )
            # No-op when empty: preserve previously known last_sweep.
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

    lib_version = get_lib_version() or "unknown"

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
        "all_bos": [],
        "active_obs": [],
        "active_fvgs": [],
        "premium_discount": "equilibrium",
        "pd_reference_range": None,
        "pd_position": None,
        "pd_position_raw": None,
        "pd_label": "equilibrium",
        "last_sweep": None,
        "atr_14": 0.0,
    }
