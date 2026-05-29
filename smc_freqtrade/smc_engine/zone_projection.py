"""Projeção causal de zona ativa por candle (Wave 9.5a §S1).

OBJETIVO
    Promover, por candle, a zona OB/FVG ativa mais relevante de cada
    viés (bullish/bearish) para colunas do `df`, de modo que a zona
    atravesse o merge `@informative` do Freqtrade (que só carrega
    colunas do `df`, nunca os ledgers). Genérico e reutilizável — não
    é específico de nenhuma assinatura de setup.

    12 colunas novas no df:
        active_{bull,bear}_swing_ob_{top,bottom,id}
        active_{bull,bear}_fvg_{top,bottom,id}

FONTE DE DADOS
    - `df['date']` (Int64 epoch ms OU pd.Timestamp) — o instante T de
      cada candle.
    - `ledger_ob` (15 colunas, scope ∈ {internal, swing}) e
      `ledger_fvg` (11 colunas), já construídos pela mesma chamada de
      `analyze()`. NÃO reconstrói detecção.

    Predicado "ativo em T" reutilizado verbatim de
    `order_blocks.py` (~linha 479):
        `t_creation <= T AND (t_mitigation is NaT OR t_mitigation > T)`.
    Lookahead-safe por construção (só lê passado/presente; sem
    `shift(-N)`).

LIMITAÇÕES CONHECIDAS
    - Escopo do OB promovido é apenas `swing` (decisão D4 da Wave
      9.5a). Internal OB fica como variante futura.
    - Tie-break quando há mais de uma zona ativa: a de menor distância
      ao `close` do candle (distância 0 se `close` dentro da zona;
      senão distância à borda mais próxima). Empate de distância →
      primeira por ordem de criação no ledger (estável).
    - `*_id` em float interno → convertido para `Int64` nullable
      (preserva `ob_id == 0`); `<NA>`/`NaN` quando não há zona ativa.

NÃO FAZER
    - Não usar `shift(-N)` (lookahead proibido).
    - Não mutar `df`, `ledger_ob` ou `ledger_fvg` do caller — apenas
      anexar colunas a uma cópia.
    - Não reconstruir detecção de OB/FVG — consumir os ledgers prontos.
    - Não importar `freqtrade`.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .types import BEARISH, BULLISH

# === Constantes de coluna (S1) ===
COL_ACTIVE_BULL_SWING_OB_TOP = 'active_bull_swing_ob_top'
COL_ACTIVE_BULL_SWING_OB_BOTTOM = 'active_bull_swing_ob_bottom'
COL_ACTIVE_BULL_SWING_OB_ID = 'active_bull_swing_ob_id'
COL_ACTIVE_BEAR_SWING_OB_TOP = 'active_bear_swing_ob_top'
COL_ACTIVE_BEAR_SWING_OB_BOTTOM = 'active_bear_swing_ob_bottom'
COL_ACTIVE_BEAR_SWING_OB_ID = 'active_bear_swing_ob_id'
COL_ACTIVE_BULL_FVG_TOP = 'active_bull_fvg_top'
COL_ACTIVE_BULL_FVG_BOTTOM = 'active_bull_fvg_bottom'
COL_ACTIVE_BULL_FVG_ID = 'active_bull_fvg_id'
COL_ACTIVE_BEAR_FVG_TOP = 'active_bear_fvg_top'
COL_ACTIVE_BEAR_FVG_BOTTOM = 'active_bear_fvg_bottom'
COL_ACTIVE_BEAR_FVG_ID = 'active_bear_fvg_id'

# Ordem canônica das 12 colunas anexadas.
ACTIVE_ZONE_COLUMNS = (
    COL_ACTIVE_BULL_SWING_OB_TOP,
    COL_ACTIVE_BULL_SWING_OB_BOTTOM,
    COL_ACTIVE_BULL_SWING_OB_ID,
    COL_ACTIVE_BEAR_SWING_OB_TOP,
    COL_ACTIVE_BEAR_SWING_OB_BOTTOM,
    COL_ACTIVE_BEAR_SWING_OB_ID,
    COL_ACTIVE_BULL_FVG_TOP,
    COL_ACTIVE_BULL_FVG_BOTTOM,
    COL_ACTIVE_BULL_FVG_ID,
    COL_ACTIVE_BEAR_FVG_TOP,
    COL_ACTIVE_BEAR_FVG_BOTTOM,
    COL_ACTIVE_BEAR_FVG_ID,
)


def _project_group(
    dates: np.ndarray,
    closes: np.ndarray,
    tops: np.ndarray,
    bottoms: np.ndarray,
    ids: np.ndarray,
    t_creation: np.ndarray,
    t_mit: np.ndarray,
    t_mit_isna: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Projeta a zona ativa mais próxima do close para cada candle.

    Para cada candle T: zonas ativas pelo predicado de `order_blocks.py`
    (~linha 479): `t_creation <= T AND (t_mitigation is NaT OR
    t_mitigation > T)`. O ramo NaT é tratado pela máscara `t_mit_isna`
    (evita comparar NaT, e independe de tz/dtype). Tie-break = menor
    distância ao close (0 se close dentro da zona). Empate → primeira
    por ordem do ledger (np.argmin é estável e retorna o primeiro mínimo).

    Retorna (top, bottom, id) como arrays float length n; NaN onde não
    há zona ativa.
    """
    n = len(dates)
    out_top = np.full(n, np.nan, dtype='float64')
    out_bottom = np.full(n, np.nan, dtype='float64')
    out_id = np.full(n, np.nan, dtype='float64')
    if len(tops) == 0:
        return out_top, out_bottom, out_id

    for i in range(n):
        t = dates[i]
        active = (t_creation <= t) & (t_mit_isna | (t_mit > t))
        if not active.any():
            continue
        idx = np.flatnonzero(active)
        c = closes[i]
        sub_top = tops[idx]
        sub_bottom = bottoms[idx]
        # distância ao close: 0 se dentro; senão à borda mais próxima.
        dist = np.where(
            c < sub_bottom,
            sub_bottom - c,
            np.where(c > sub_top, c - sub_top, 0.0),
        )
        best = idx[int(np.argmin(dist))]
        out_top[i] = tops[best]
        out_bottom[i] = bottoms[best]
        out_id[i] = ids[best]
    return out_top, out_bottom, out_id


def _group_arrays(
    ledger: pd.DataFrame, bias: int,
) -> tuple[np.ndarray, ...]:
    """Extrai arrays (top, bottom, id, t_creation, t_mit, t_mit_isna).

    `t_mit` tem os NaT preenchidos com `t_creation` (mesmo dtype/tz,
    valor irrelevante porque mascarado por `t_mit_isna`) só para
    permitir `to_numpy()` comparável; o predicado de atividade usa a
    máscara explícita.
    """
    sub = ledger[ledger['bias'] == bias]
    if len(sub) == 0:
        empty = np.empty(0)
        return empty, empty, empty, empty, empty, empty
    top_col = 'bar_high' if 'bar_high' in ledger.columns else 'top'
    bottom_col = 'bar_low' if 'bar_low' in ledger.columns else 'bottom'
    id_col = 'ob_id' if 'ob_id' in ledger.columns else 'fvg_id'
    tops = sub[top_col].to_numpy(dtype='float64')
    bottoms = sub[bottom_col].to_numpy(dtype='float64')
    ids = sub[id_col].astype('float64').to_numpy()
    creation = sub['t_creation']
    mit = sub['t_mitigation']
    isna = pd.isna(mit)
    mit_filled = mit.where(~isna, other=creation)
    return (
        tops, bottoms, ids,
        creation.to_numpy(), mit_filled.to_numpy(), isna.to_numpy(),
    )


def promote_active_zones(
    df: pd.DataFrame,
    ledger_ob: pd.DataFrame,
    ledger_fvg: pd.DataFrame,
) -> pd.DataFrame:
    """Anexa as 12 colunas de zona ativa por candle ao `df`.

    Pós-passo causal de `analyze()`. Lê os ledgers já construídos e
    projeta, por candle, a zona swing OB / FVG ativa mais próxima do
    close, para cada viés. Preserva o `df` de entrada intocado (opera
    sobre cópia; só anexa colunas).

    Args:
        df: DataFrame base (saída dos detectores), com coluna `date`.
        ledger_ob: ledger de Order Blocks (15 colunas). Apenas linhas
            `scope == 'swing'` são consideradas.
        ledger_fvg: ledger de Fair Value Gaps (11 colunas).

    Returns:
        Cópia de `df` + 12 colunas (`ACTIVE_ZONE_COLUMNS`). `*_top` /
        `*_bottom` são float64 (NaN sem zona); `*_id` é Int64 nullable
        (<NA> sem zona).
    """
    out = df.copy()
    dates = df['date'].to_numpy()
    closes = df['close'].to_numpy(dtype='float64')

    ob_swing = ledger_ob[ledger_ob['scope'] == 'swing']

    specs = (
        (ob_swing, BULLISH,
         COL_ACTIVE_BULL_SWING_OB_TOP,
         COL_ACTIVE_BULL_SWING_OB_BOTTOM,
         COL_ACTIVE_BULL_SWING_OB_ID),
        (ob_swing, BEARISH,
         COL_ACTIVE_BEAR_SWING_OB_TOP,
         COL_ACTIVE_BEAR_SWING_OB_BOTTOM,
         COL_ACTIVE_BEAR_SWING_OB_ID),
        (ledger_fvg, BULLISH,
         COL_ACTIVE_BULL_FVG_TOP,
         COL_ACTIVE_BULL_FVG_BOTTOM,
         COL_ACTIVE_BULL_FVG_ID),
        (ledger_fvg, BEARISH,
         COL_ACTIVE_BEAR_FVG_TOP,
         COL_ACTIVE_BEAR_FVG_BOTTOM,
         COL_ACTIVE_BEAR_FVG_ID),
    )

    for ledger, bias, col_top, col_bottom, col_id in specs:
        tops, bottoms, ids, t_creation, t_mit, t_mit_isna = _group_arrays(
            ledger, bias,
        )
        proj_top, proj_bottom, proj_id = _project_group(
            dates, closes, tops, bottoms, ids,
            t_creation, t_mit, t_mit_isna,
        )
        out[col_top] = proj_top
        out[col_bottom] = proj_bottom
        out[col_id] = pd.array(proj_id, dtype='Int64')

    return out
