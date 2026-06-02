"""Projeção causal de zona ativa por candle (Wave 9.5a §S1).

OBJETIVO
    Promover, por candle, a zona OB/FVG ativa mais relevante de cada
    viés (bullish/bearish) para colunas do `df`, de modo que a zona
    atravesse o merge `@informative` do Freqtrade (que só carrega
    colunas do `df`, nunca os ledgers). Genérico e reutilizável — não
    é específico de nenhuma assinatura de setup.

    26 colunas novas no df (12 da 9.5a + 8 da 9.5b + 6 da 9.5c, aditivas
    ao fim):
        active_{bull,bear}_swing_ob_{top,bottom,id}        (9.5a)
        active_{bull,bear}_fvg_{top,bottom,id}             (9.5a)
        active_{bull,bear}_swing_ob_volume_pct             (9.5b, A5/D5)
        active_{bull,bear}_ifvg_{top,bottom,id}            (9.5b, A4a/D4)
        active_{bull,bear}_breaker_{top,bottom,id}         (9.5c, A6/D-C9)

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

# === Wave 9.5b — volume_pct do OB swing vencedor (A5) + zona IFVG (A4a) ===
# volume_pct do MESMO OB que venceu o tie-break (menor distância ao close)
# e define top/bottom/id daquele candle — não um agregado (D5).
COL_ACTIVE_BULL_SWING_OB_VOLUME_PCT = 'active_bull_swing_ob_volume_pct'
COL_ACTIVE_BEAR_SWING_OB_VOLUME_PCT = 'active_bear_swing_ob_volume_pct'
# Zona IFVG (Inverse FVG vivo): o rótulo bull/bear é a **direção
# negociável** (pós-inversão), oposta ao `bias` do ledger FVG (D4/§5.3).
COL_ACTIVE_BULL_IFVG_TOP = 'active_bull_ifvg_top'
COL_ACTIVE_BULL_IFVG_BOTTOM = 'active_bull_ifvg_bottom'
COL_ACTIVE_BULL_IFVG_ID = 'active_bull_ifvg_id'
COL_ACTIVE_BEAR_IFVG_TOP = 'active_bear_ifvg_top'
COL_ACTIVE_BEAR_IFVG_BOTTOM = 'active_bear_ifvg_bottom'
COL_ACTIVE_BEAR_IFVG_ID = 'active_bear_ifvg_id'

# === Wave 9.5c — zona breaker (OB mitigado vivo) com inversão de
# direção (A6/D-C9). O rótulo bull/bear é a **direção negociável**
# (pós-inversão), oposta ao `bias` do OB de origem: OB BEARISH mitigado
# → suporte/long (`active_bull_breaker_*`); OB BULLISH mitigado →
# resistência/short (`active_bear_breaker_*`).
COL_ACTIVE_BULL_BREAKER_TOP = 'active_bull_breaker_top'
COL_ACTIVE_BULL_BREAKER_BOTTOM = 'active_bull_breaker_bottom'
COL_ACTIVE_BULL_BREAKER_ID = 'active_bull_breaker_id'
COL_ACTIVE_BEAR_BREAKER_TOP = 'active_bear_breaker_top'
COL_ACTIVE_BEAR_BREAKER_BOTTOM = 'active_bear_breaker_bottom'
COL_ACTIVE_BEAR_BREAKER_ID = 'active_bear_breaker_id'

# Ordem canônica das 26 colunas anexadas (12 originais + 2 volume_pct +
# 6 IFVG + 6 breaker). As novas são **aditivas ao fim** — o gate real do
# §7 é aditividade, não a contagem.
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
    # --- Wave 9.5b (aditivo ao fim) ---
    COL_ACTIVE_BULL_SWING_OB_VOLUME_PCT,
    COL_ACTIVE_BEAR_SWING_OB_VOLUME_PCT,
    COL_ACTIVE_BULL_IFVG_TOP,
    COL_ACTIVE_BULL_IFVG_BOTTOM,
    COL_ACTIVE_BULL_IFVG_ID,
    COL_ACTIVE_BEAR_IFVG_TOP,
    COL_ACTIVE_BEAR_IFVG_BOTTOM,
    COL_ACTIVE_BEAR_IFVG_ID,
    # --- Wave 9.5c (aditivo ao fim) ---
    COL_ACTIVE_BULL_BREAKER_TOP,
    COL_ACTIVE_BULL_BREAKER_BOTTOM,
    COL_ACTIVE_BULL_BREAKER_ID,
    COL_ACTIVE_BEAR_BREAKER_TOP,
    COL_ACTIVE_BEAR_BREAKER_BOTTOM,
    COL_ACTIVE_BEAR_BREAKER_ID,
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


def _lookup_volume_pct(
    proj_id: np.ndarray, ob_swing: pd.DataFrame, bias: int,
) -> np.ndarray:
    """Resolve o `volume_pct` do OB vencedor (por `ob_id`) candle-a-candle.

    Wave 9.5b (A5/D5): para cada candle, `proj_id` é o `ob_id` que já
    venceu o tie-break (menor distância ao close) na promoção de zona.
    Devolve o `volume_pct` **desse mesmo OB** — não um agregado. NaN onde
    não há OB ativo (`proj_id` NaN).
    """
    n = len(proj_id)
    out = np.full(n, np.nan, dtype='float64')
    sub = ob_swing[ob_swing['bias'] == bias]
    if len(sub) == 0:
        return out
    vmap: dict[int, float] = {}
    for oid, vp in zip(sub['ob_id'].to_numpy(), sub['volume_pct'].to_numpy()):
        vmap[int(oid)] = float(vp) if pd.notna(vp) else np.nan
    for i in range(n):
        oid = proj_id[i]
        if not np.isnan(oid):
            out[i] = vmap.get(int(oid), np.nan)
    return out


def _ifvg_group_arrays(
    ledger_fvg: pd.DataFrame, fvg_bias: int,
) -> tuple[np.ndarray, ...]:
    """Extrai arrays de IFVG vivo para um `bias` do **ledger FVG**.

    IFVG vivo = FVG que mitigou e inverteu polaridade. Inclui tanto
    `state == 'mitigated'` (ainda vivo, `t_invalidation` NaT) quanto
    `state == 'inverse_broken'` (viveu em `[t_mitigation, t_invalidation)`
    e quebrou) — ambos têm `is_inverse == True`. Filtrar só por
    `state == 'mitigated'` (letra do §5.3 item 1) excluiria os quebrados
    e violaria P3 ("ativo só em `(t_mitigation, t_invalidation)`" e
    "vazio após a invalidação"); usamos `is_inverse` (= a união) e
    deixamos o predicado temporal bordar cada um.

    Governo temporal = par `(t_mitigation, t_invalidation)` (§2). `t_inv`
    tem NaT preenchido com `t_mitigation` só para `to_numpy()` comparável;
    a máscara `t_inv_isna` decide o ramo (espelha `_group_arrays`).
    """
    sub = ledger_fvg[
        (ledger_fvg['bias'] == fvg_bias) & (ledger_fvg['is_inverse'])
    ]
    if len(sub) == 0:
        empty = np.empty(0)
        return empty, empty, empty, empty, empty, empty
    tops = sub['top'].to_numpy(dtype='float64')
    bottoms = sub['bottom'].to_numpy(dtype='float64')
    ids = sub['fvg_id'].astype('float64').to_numpy()
    mit = sub['t_mitigation']
    inv = sub['t_invalidation']
    isna = pd.isna(inv)
    inv_filled = inv.where(~isna, other=mit)
    return (
        tops, bottoms, ids,
        mit.to_numpy(), inv_filled.to_numpy(), isna.to_numpy(),
    )


def _project_ifvg_group(
    dates: np.ndarray,
    closes: np.ndarray,
    tops: np.ndarray,
    bottoms: np.ndarray,
    ids: np.ndarray,
    t_mit: np.ndarray,
    t_inv: np.ndarray,
    t_inv_isna: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Projeta a zona IFVG ativa mais próxima do close por candle (D4).

    Projetor **dedicado** (não reusa `_project_group` verbatim, D4): o
    predicado "ativo em T" usa o par `(t_mitigation, t_invalidation)` em
    vez de `(t_creation, t_mitigation)`:
        `t_mitigation <= T AND (t_invalidation is NaT OR t_invalidation > T)`.
    Geometria (`top`/`bottom`) e tie-break (menor distância ao close,
    empate → primeira por ordem do ledger) idênticos. NaN onde não há
    IFVG ativo.
    """
    n = len(dates)
    out_top = np.full(n, np.nan, dtype='float64')
    out_bottom = np.full(n, np.nan, dtype='float64')
    out_id = np.full(n, np.nan, dtype='float64')
    if len(tops) == 0:
        return out_top, out_bottom, out_id

    for i in range(n):
        t = dates[i]
        active = (t_mit <= t) & (t_inv_isna | (t_inv > t))
        if not active.any():
            continue
        idx = np.flatnonzero(active)
        c = closes[i]
        sub_top = tops[idx]
        sub_bottom = bottoms[idx]
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


def _breaker_group_arrays(
    ledger_ob: pd.DataFrame, ob_bias: int, breaker_scope: str,
) -> tuple[np.ndarray, ...]:
    """Extrai arrays de breaker vivo para um `bias` do **ledger OB** (D-C9).

    Espelha `_ifvg_group_arrays` adaptado ao ledger OB. Breaker nasce na
    mitigação do OB (`order_blocks.py`, Onda 6.2): por isso o filtro de
    origem é `t_mitigation.notna()` — **NUNCA** `state == 'mitigated'`
    (HOOKS §12.1: filtrar por `state` perderia ~95% dos breakers já
    quebrados, que vivem em `[t_mitigation, t_invalidation)`). Restrito por
    `breaker_scope ∈ {'swing','internal','both'}` (default 'swing',
    consistente com a zona OB da D4).

    Governo temporal = par `(t_mitigation, t_invalidation)` (idêntico ao
    IFVG): breaker vivo em T sse `t_mitigation <= T AND (t_invalidation is
    NaT OR t_invalidation > T)`. Geometria = `bar_high`/`bar_low` do OB;
    id = `ob_id`. `t_inv` tem NaT preenchido com `t_mitigation` só para
    `to_numpy()` comparável; a máscara `t_inv_isna` decide o ramo.
    """
    sub = ledger_ob[ledger_ob['t_mitigation'].notna()]
    if breaker_scope != 'both':
        sub = sub[sub['scope'] == breaker_scope]
    sub = sub[sub['bias'] == ob_bias]
    if len(sub) == 0:
        empty = np.empty(0)
        return empty, empty, empty, empty, empty, empty
    tops = sub['bar_high'].to_numpy(dtype='float64')
    bottoms = sub['bar_low'].to_numpy(dtype='float64')
    ids = sub['ob_id'].astype('float64').to_numpy()
    mit = sub['t_mitigation']
    inv = sub['t_invalidation']
    isna = pd.isna(inv)
    inv_filled = inv.where(~isna, other=mit)
    return (
        tops, bottoms, ids,
        mit.to_numpy(), inv_filled.to_numpy(), isna.to_numpy(),
    )


def promote_active_zones(
    df: pd.DataFrame,
    ledger_ob: pd.DataFrame,
    ledger_fvg: pd.DataFrame,
    breaker_scope: str = 'swing',
) -> pd.DataFrame:
    """Anexa as 26 colunas de zona ativa por candle ao `df`.

    Pós-passo causal de `analyze()`. Lê os ledgers já construídos e
    projeta, por candle, a zona swing OB / FVG / IFVG / breaker ativa mais
    próxima do close, para cada viés, mais o `volume_pct` do OB vencedor.
    Preserva o `df` de entrada intocado (opera sobre cópia; só anexa
    colunas).

    Args:
        df: DataFrame base (saída dos detectores), com coluna `date`.
        ledger_ob: ledger de Order Blocks (15 colunas). A zona OB swing
            usa apenas `scope == 'swing'`; a zona breaker usa o escopo de
            `breaker_scope`.
        ledger_fvg: ledger de Fair Value Gaps (11 colunas).
        breaker_scope: escopo dos OBs de origem da zona breaker (D-C9):
            `'swing'` (default, consistente com a zona OB), `'internal'`
            ou `'both'`. Os outros valores apenas alimentam o backtest da
            Wave 10 (varredura por escopo).

    Returns:
        Cópia de `df` + 26 colunas (`ACTIVE_ZONE_COLUMNS`). `*_top` /
        `*_bottom` são float64 (NaN sem zona); `*_id` é Int64 nullable
        (<NA> sem zona).
    """
    if breaker_scope not in ('swing', 'internal', 'both'):
        raise ValueError(
            f"breaker_scope deve ser 'swing', 'internal' ou 'both', "
            f"recebeu {breaker_scope!r}",
        )
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

    # --- Wave 9.5b: volume_pct do OB swing vencedor (A5/D5) ---
    out[COL_ACTIVE_BULL_SWING_OB_VOLUME_PCT] = _lookup_volume_pct(
        out[COL_ACTIVE_BULL_SWING_OB_ID].to_numpy(dtype='float64'),
        ob_swing, BULLISH,
    )
    out[COL_ACTIVE_BEAR_SWING_OB_VOLUME_PCT] = _lookup_volume_pct(
        out[COL_ACTIVE_BEAR_SWING_OB_ID].to_numpy(dtype='float64'),
        ob_swing, BEARISH,
    )

    # --- Wave 9.5b: zona IFVG com inversão de direção (A4a/D4) ---
    # active_bull_ifvg_* ← FVG BEARISH mitigado (vira suporte/long).
    # active_bear_ifvg_* ← FVG BULLISH mitigado (vira resistência/short).
    ifvg_specs = (
        (BEARISH,
         COL_ACTIVE_BULL_IFVG_TOP,
         COL_ACTIVE_BULL_IFVG_BOTTOM,
         COL_ACTIVE_BULL_IFVG_ID),
        (BULLISH,
         COL_ACTIVE_BEAR_IFVG_TOP,
         COL_ACTIVE_BEAR_IFVG_BOTTOM,
         COL_ACTIVE_BEAR_IFVG_ID),
    )
    for fvg_bias, col_top, col_bottom, col_id in ifvg_specs:
        tops, bottoms, ids, t_mit, t_inv, t_inv_isna = _ifvg_group_arrays(
            ledger_fvg, fvg_bias,
        )
        proj_top, proj_bottom, proj_id = _project_ifvg_group(
            dates, closes, tops, bottoms, ids, t_mit, t_inv, t_inv_isna,
        )
        out[col_top] = proj_top
        out[col_bottom] = proj_bottom
        out[col_id] = pd.array(proj_id, dtype='Int64')

    # --- Wave 9.5c: zona breaker com inversão de direção (A6/D-C9) ---
    # active_bull_breaker_* ← OB BEARISH mitigado (vira suporte/long).
    # active_bear_breaker_* ← OB BULLISH mitigado (vira resistência/short).
    # Predicado temporal idêntico ao IFVG → reusa `_project_ifvg_group`.
    breaker_specs = (
        (BEARISH,
         COL_ACTIVE_BULL_BREAKER_TOP,
         COL_ACTIVE_BULL_BREAKER_BOTTOM,
         COL_ACTIVE_BULL_BREAKER_ID),
        (BULLISH,
         COL_ACTIVE_BEAR_BREAKER_TOP,
         COL_ACTIVE_BEAR_BREAKER_BOTTOM,
         COL_ACTIVE_BEAR_BREAKER_ID),
    )
    for ob_bias, col_top, col_bottom, col_id in breaker_specs:
        tops, bottoms, ids, t_mit, t_inv, t_inv_isna = _breaker_group_arrays(
            ledger_ob, ob_bias, breaker_scope,
        )
        proj_top, proj_bottom, proj_id = _project_ifvg_group(
            dates, closes, tops, bottoms, ids, t_mit, t_inv, t_inv_isna,
        )
        out[col_top] = proj_top
        out[col_bottom] = proj_bottom
        out[col_id] = pd.array(proj_id, dtype='Int64')

    return out
