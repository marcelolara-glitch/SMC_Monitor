"""
OBJETIVO
    Portagem vetorizada de updateTrailingExtremes() do LuxAlgo SMC
    (Pine linhas 271-276) combinada com o reset de trailing.top /
    trailing.bottom que ocorre dentro de getCurrentStructure() apenas
    no modo swing (Pine linhas 156-161 e 174-179).

    Adicionalmente, deriva Premium / Discount / Equilibrium do range
    trailing_top..trailing_bottom em relação ao close — Mapa Camada 1
    v1.1 §6 Onda 4 ("não existe no LuxAlgo, mas é trivial: derivar
    Premium/Discount/Equilibrium do `trailing.top` e `trailing.bottom`").

FONTE DE DADOS
    DataFrame com no mínimo 'high', 'low', 'close', mais as colunas
    COL_SWING_HIGH_LEVEL e COL_SWING_LOW_LEVEL produzidas por
    pivots.detect_pivots(). Internal e equal pivots NÃO resetam
    trailing — fiel ao Pine, que dentro de getCurrentStructure só
    executa o bloco de reset quando `not equalHighLow and not internal`.

LIMITAÇÕES CONHECIDAS
    Antes do primeiro swing pivot, trailing_top é cummax(high) e
    trailing_bottom é cummin(low) — equivalente ao estado Persistent
    inicial do Pine, que parte de NaN e estabiliza no primeiro pivot
    (no Pine, `math.max(high, na)` retorna `high`; em pandas o cummax
    desde o índice 0 produz o mesmo output observável).

    pd_ratio é NaN quando trailing_top == trailing_bottom (range
    degenerado, possível nos primeiros candles antes de qualquer
    expansão). pd_zone usa string nullable (pd.NA) nessa condição.

    Equilibrium é estrito: pd_ratio == 0.5 exato. Em float a
    ocorrência prática é virtualmente zero — mantido para cobertura
    formal dos 3 níveis citados pelo Mapa.

NÃO FAZER
    Não usar shift(-N) em ponto algum.
    Não aplicar reset com base em internal_high_level / internal_low_level.
    Não aplicar reset com base em equal_high_level / equal_low_level.
    Não emitir efeitos colaterais sobre o DataFrame de entrada
        (operar sobre cópia).
    Não popular EngineState — Mapa §2 v1.1 fechou que estado vive
        no DataFrame em Python vetorizado.
    Não inline-ar nomes de coluna — usar as constantes COL_* e
        PD_ZONE_* definidas no topo do módulo.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .pivots import (
    COL_SWING_HIGH_LEVEL,
    COL_SWING_LOW_LEVEL,
)


# ============================================================
# Nomes canônicos das colunas produzidas por
# compute_trailing_extremes. Consumidores referenciam estas
# constantes — não inline-ar as strings.
# ============================================================
COL_TRAILING_TOP = 'trailing_top'
COL_TRAILING_BOTTOM = 'trailing_bottom'
COL_PD_RATIO = 'pd_ratio'
COL_PD_ZONE = 'pd_zone'

# Valores possíveis de pd_zone (constantes para consumidores
# downstream referenciarem em vez de strings literais).
PD_ZONE_PREMIUM = 'premium'
PD_ZONE_DISCOUNT = 'discount'
PD_ZONE_EQUILIBRIUM = 'equilibrium'


# ============================================================
# Helper privado.
# ============================================================

def _segmented_running_extreme(
    series: pd.Series,
    pivot_level: pd.Series,
    mode: str,
) -> pd.Series:
    """Aplica cummax (mode='max') / cummin (mode='min') sobre `series`
    com reset para `pivot_level` em cada candle onde pivot_level é
    não-NaN. Vetorizado via groupby de segmentos."""
    is_pivot = pivot_level.notna()
    segment_id = is_pivot.cumsum()

    # Em cada candle de pivot, semeia o segmento com pivot_level — assim
    # o primeiro candle do segmento começa exatamente no nível do swing
    # real (high[X-size] / low[X-size]) e não no high/low do candle de
    # detecção. Match exato com o Pine: o reset em getCurrentStructure
    # sobrescreve o cummax/cummin que updateTrailingExtremes acabou de
    # aplicar no mesmo candle.
    seed = series.where(~is_pivot, pivot_level)

    if mode == 'max':
        return seed.groupby(segment_id).cummax()
    return seed.groupby(segment_id).cummin()


# ============================================================
# Função pública.
# ============================================================

def compute_trailing_extremes(df: pd.DataFrame) -> pd.DataFrame:
    """
    OBJETIVO
        Portagem vetorizada de updateTrailingExtremes() do LuxAlgo SMC
        (Pine linhas 271-276) combinada com o reset de trailing.top /
        trailing.bottom que ocorre em getCurrentStructure() apenas no
        modo swing (Pine linhas 156-161 e 174-179).

        Adicionalmente, deriva Premium / Discount / Equilibrium do
        range trailing_top..trailing_bottom em relação ao close.
        Mapa Camada 1 v1.1 §6 Onda 4.

    FONTE DE DADOS
        df: DataFrame com no mínimo 'high', 'low', 'close', mais as
            colunas COL_SWING_HIGH_LEVEL e COL_SWING_LOW_LEVEL
            produzidas por pivots.detect_pivots(). Internal e equal
            pivots NÃO resetam trailing — fiel ao Pine.

    LIMITAÇÕES CONHECIDAS
        Antes do primeiro swing pivot, trailing_top é cummax(high) e
        trailing_bottom é cummin(low) — equivalente ao estado
        Persistent inicial do Pine.

        pd_ratio é NaN quando trailing_top == trailing_bottom (range
        degenerado). pd_zone usa string nullable (pd.NA) nessa condição.

        Equilibrium é estrito: pd_ratio == 0.5 exato.

    NÃO FAZER
        Não usar shift(-N) em ponto algum.
        Não aplicar reset com base em internal_* ou equal_*.
        Não emitir efeitos colaterais sobre o DataFrame de entrada
            (operar sobre cópia).
        Não popular EngineState — Mapa §2 v1.1 fechou que estado vive
            no DataFrame em Python vetorizado.
        Não inline-ar nomes de coluna — usar as constantes COL_* e
            PD_ZONE_*.
    """
    result = df.copy()

    trailing_top = _segmented_running_extreme(
        df['high'], df[COL_SWING_HIGH_LEVEL], mode='max',
    )
    trailing_bottom = _segmented_running_extreme(
        df['low'], df[COL_SWING_LOW_LEVEL], mode='min',
    )

    range_size = trailing_top - trailing_bottom
    pd_ratio = np.where(
        range_size > 0,
        (df['close'] - trailing_bottom) / range_size,
        np.nan,
    )
    pd_ratio = pd.Series(pd_ratio, index=df.index, dtype='float64')

    pd_zone = pd.Series(pd.NA, index=df.index, dtype='string')
    pd_zone.loc[pd_ratio > 0.5] = PD_ZONE_PREMIUM
    pd_zone.loc[pd_ratio < 0.5] = PD_ZONE_DISCOUNT
    pd_zone.loc[pd_ratio == 0.5] = PD_ZONE_EQUILIBRIUM

    result[COL_TRAILING_TOP] = trailing_top
    result[COL_TRAILING_BOTTOM] = trailing_bottom
    result[COL_PD_RATIO] = pd_ratio
    result[COL_PD_ZONE] = pd_zone

    return result
