"""Zona OTE (banda Fib 0.62-0.79) ancorada no MSS (Wave 9.5d, HOOKS §10.3).

OBJETIVO
    Projetar, por candle, a zona OTE (Optimal Trade Entry) ativa de cada
    viés, ancorada no último Market Structure Shift (MSS) swing. OTE =
    retração na banda Fibonacci 0.62-0.79 da perna do MSS. Insumo puro
    (hook) da assinatura A10 da Wave 9.5e — esta wave NÃO emite sinal,
    só materializa a zona em colunas do `df`.

    6 colunas novas (aditivas ao fim), espelhando o tipo das colunas de
    `zone_projection`:
        active_bull_ote_{top,bottom,id}   (long / banda discount)
        active_bear_ote_{top,bottom,id}   (short / banda premium)

FONTE DE DADOS
    - Evento de disparo (MSS swing): união de BOS swing + CHoCH swing
      (`bos_swing_{bullish,bearish}` ∪ `choch_swing_{bullish,bearish}`
      de `structure.py`). `mss_scope='swing'` é o default desta wave
      (D-D3); `'internal'`/`'both'` ficam reservados para a Wave 10.
    - Perna do MSS = **swing range ativo no candle do MSS**:
      `low = trailing_bottom[T_mss]`, `high = trailing_top[T_mss]`
      (colunas densas de `trailing.py`, Onda 4). É exatamente a faixa
      que o engine já usa para Premium/Discount — reuso de conceito
      existente, **OTE simplificada sobre o swing range ativo no MSS**
      (simplificação de DTFX, ver HOOKS §10.3; o Pine `DTFX Algo Zones`
      não está no repo). Se a fonte DTFX for fornecida e divergir desta
      perna → PARAR e reportar (§0 do briefing).
    - Predicado "ativa em T" reusa `zone_projection._project_group`:
      `t_creation <= T AND (t_invalidation is NaT OR t_invalidation > T)`.
      Lookahead-safe (só lê passado/presente; sem `shift(-N)`).

LIMITAÇÕES CONHECIDAS
    - Apenas a banda OTE 0.62-0.79; demais níveis Fib / varredura de
      janelas ficam na Wave 10. A mediana 0.705 não vira coluna (só
      teste unitário).
    - Tie-break quando há mais de uma zona ativa: menor distância ao
      `close` (herdado de `_project_group`).
    - O "ledger" OTE (1 linha por zona MSS) é intermediário interno —
      **NÃO** é exposto em `AnalyzeResult` (D-D6).

NÃO FAZER
    - Não usar `shift(-N)` (lookahead proibido).
    - Não mutar o `df` do caller — opera sobre cópia e só anexa colunas.
    - Não expor o ledger OTE em `AnalyzeResult` nem tocar nos 4 ledgers.
    - Não importar `freqtrade`.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .structure import (
    COL_BOS_SWING_BEARISH,
    COL_BOS_SWING_BULLISH,
    COL_CHOCH_SWING_BEARISH,
    COL_CHOCH_SWING_BULLISH,
)
from .trailing import COL_TRAILING_BOTTOM, COL_TRAILING_TOP
from .types import BEARISH, BULLISH
from .zone_projection import _project_group

# === Constantes de coluna (HOOKS §10.3) ===
COL_ACTIVE_BULL_OTE_TOP = 'active_bull_ote_top'        # long / discount
COL_ACTIVE_BULL_OTE_BOTTOM = 'active_bull_ote_bottom'
COL_ACTIVE_BULL_OTE_ID = 'active_bull_ote_id'
COL_ACTIVE_BEAR_OTE_TOP = 'active_bear_ote_top'        # short / premium
COL_ACTIVE_BEAR_OTE_BOTTOM = 'active_bear_ote_bottom'
COL_ACTIVE_BEAR_OTE_ID = 'active_bear_ote_id'

OTE_COLUMNS = (
    COL_ACTIVE_BULL_OTE_TOP,
    COL_ACTIVE_BULL_OTE_BOTTOM,
    COL_ACTIVE_BULL_OTE_ID,
    COL_ACTIVE_BEAR_OTE_TOP,
    COL_ACTIVE_BEAR_OTE_BOTTOM,
    COL_ACTIVE_BEAR_OTE_ID,
)

# Banda OTE canônica (D-D4). Mediana 0.705 só no teste unitário.
OTE_RETRACE_LOW, OTE_RETRACE_HIGH = 0.62, 0.79


def _build_ote_ledger(df: pd.DataFrame) -> pd.DataFrame:
    """Constrói o ledger OTE: 1 linha por MSS swing (D-D3/D-D4).

    Percorre causalmente (sem `shift(-N)`). Para cada candle `T` de MSS
    swing lê a perna `(trailing_bottom[T], trailing_top[T])`, calcula a
    banda OTE direction-aware (D-D4) e resolve `t_invalidation` por
    varredura para a frente (candles ≥ `T`) do close vs a origem 0.0:
        - bull: origem 0.0 = `low` → invalida quando `close < low`;
        - bear: origem 0.0 = `high` → invalida quando `close > high`.
    `t_invalidation` fica NaT enquanto não invalidado.

    Bandas (D-D4; 0.0 = origem do impulso, 1.0 = fim):
        - bull (long): banda **discount** —
          `bottom = high - 0.79·span`, `top = high - 0.62·span`;
        - bear (short): banda **premium** —
          `bottom = low + 0.62·span`, `top = low + 0.79·span`.

    Returns:
        DataFrame com colunas `ote_id` (int), `bias` (+1/-1),
        `t_creation`, `top`, `bottom`, `t_invalidation`. `t_creation` /
        `t_invalidation` herdam o dtype de `df['date']`.
    """
    dates = df['date'].to_numpy()
    closes = df['close'].to_numpy(dtype='float64')
    ttop = df[COL_TRAILING_TOP].to_numpy(dtype='float64')
    tbot = df[COL_TRAILING_BOTTOM].to_numpy(dtype='float64')
    bull_mss = (
        df[COL_BOS_SWING_BULLISH].to_numpy()
        | df[COL_CHOCH_SWING_BULLISH].to_numpy()
    )
    bear_mss = (
        df[COL_BOS_SWING_BEARISH].to_numpy()
        | df[COL_CHOCH_SWING_BEARISH].to_numpy()
    )
    n = len(df)

    ids: list[int] = []
    biases: list[int] = []
    creations: list = []
    tops: list[float] = []
    bottoms: list[float] = []
    invalidations: list = []
    next_id = 0

    for t in range(n):
        for is_bull in (True, False):
            if is_bull and not bull_mss[t]:
                continue
            if (not is_bull) and not bear_mss[t]:
                continue
            low = tbot[t]
            high = ttop[t]
            if not (np.isfinite(low) and np.isfinite(high)) or high <= low:
                continue
            span = high - low
            if is_bull:
                bias = BULLISH
                ote_bottom = high - OTE_RETRACE_HIGH * span
                ote_top = high - OTE_RETRACE_LOW * span
            else:
                bias = BEARISH
                ote_bottom = low + OTE_RETRACE_LOW * span
                ote_top = low + OTE_RETRACE_HIGH * span

            t_inv = None
            for j in range(t, n):
                if is_bull:
                    if closes[j] < low:
                        t_inv = dates[j]
                        break
                else:
                    if closes[j] > high:
                        t_inv = dates[j]
                        break

            ids.append(next_id)
            biases.append(bias)
            creations.append(dates[t])
            tops.append(ote_top)
            bottoms.append(ote_bottom)
            invalidations.append(t_inv)
            next_id += 1

    return pd.DataFrame({
        'ote_id': pd.array(ids, dtype='int64'),
        'bias': pd.array(biases, dtype='int64'),
        't_creation': pd.Series(creations, dtype=df['date'].dtype),
        'top': pd.array(tops, dtype='float64'),
        'bottom': pd.array(bottoms, dtype='float64'),
        't_invalidation': pd.Series(invalidations),
    })


def project_ote_zones(df: pd.DataFrame) -> pd.DataFrame:
    """Anexa as 6 colunas de zona OTE ativa por candle ao `df`.

    Constrói o ledger interno (`_build_ote_ledger`), separa por `bias` e
    projeta via `zone_projection._project_group` (predicado
    `t_creation <= T AND (t_invalidation is NaT OR t_invalidation > T)`,
    tie-break por menor distância ao close). Preserva o `df` de entrada
    intocado (opera sobre cópia; só anexa colunas).

    Mapeamento: bull → `active_bull_ote_*` (banda discount), bear →
    `active_bear_ote_*` (banda premium).

    Args:
        df: DataFrame com colunas `date`, `close`, `trailing_top`,
            `trailing_bottom` e as 4 colunas `*_swing_*` de structure.

    Returns:
        Cópia de `df` + 6 colunas (`OTE_COLUMNS`). `*_top`/`*_bottom`
        são float64 (NaN sem zona); `*_id` é Int64 nullable (<NA> sem
        zona).
    """
    out = df.copy()
    dates = df['date'].to_numpy()
    closes = df['close'].to_numpy(dtype='float64')
    ledger = _build_ote_ledger(df)

    specs = (
        (BULLISH,
         COL_ACTIVE_BULL_OTE_TOP,
         COL_ACTIVE_BULL_OTE_BOTTOM,
         COL_ACTIVE_BULL_OTE_ID),
        (BEARISH,
         COL_ACTIVE_BEAR_OTE_TOP,
         COL_ACTIVE_BEAR_OTE_BOTTOM,
         COL_ACTIVE_BEAR_OTE_ID),
    )

    for bias, col_top, col_bottom, col_id in specs:
        sub = ledger[ledger['bias'] == bias]
        tops = sub['top'].to_numpy(dtype='float64')
        bottoms = sub['bottom'].to_numpy(dtype='float64')
        ids = sub['ote_id'].astype('float64').to_numpy()
        creation = sub['t_creation']
        inv = sub['t_invalidation']
        isna = pd.isna(inv)
        inv_filled = inv.where(~isna, other=creation)
        proj_top, proj_bottom, proj_id = _project_group(
            dates, closes, tops, bottoms, ids,
            creation.to_numpy(), inv_filled.to_numpy(), isna.to_numpy(),
        )
        out[col_top] = proj_top
        out[col_bottom] = proj_bottom
        out[col_id] = pd.array(proj_id, dtype='Int64')

    return out
