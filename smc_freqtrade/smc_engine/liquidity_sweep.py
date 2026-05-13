"""
OBJETIVO
    Portagem vetorizada do indicador Pine `Liquidity Sweeps [LuxAlgo]`
    (indicador gratuito, separado do SMC principal). Detecta duas
    classes de evento sobre pivots previamente identificados pela
    Onda 3:

        1. WICK SWEEP — wick fura o pivot e o close volta para o lado
           original (sem rompimento de close prévio). Pivot permanece
           em estado pré-break.

        2. OUTBREAK & RETEST — primeiro um close rompe o pivot
           (estado pré-break → pós-break), depois uma mecha volta a
           furar o nível pelo lado de dentro com close de volta
           (false breakout). Pivot tem `brk=True`.

    Cada classe é one-shot por pivot (`wic` para wick, `tak` para
    retest). A direção do evento depende do lado do pivot e do estado
    (vide tabela abaixo):

        Pool          | Estado     | Predicate                         | Coluna emit
        --------------|------------|-----------------------------------|----------------------
        high (máx)    | pré-break  | h > level & c < level             | sweep_bearish_wick
        low  (mín)    | pré-break  | l < level & c > level             | sweep_bullish_wick
        high (máx)    | pós-break  | l < level & c > level             | sweep_bullish_retest
        low  (mín)    | pós-break  | h > level & c < level             | sweep_bearish_retest

    Para cada sweep emitido, a "sweep area" fica viva por até
    `sweep_max_extension_bars` candles. Mitigação acontece quando o
    close retorna ao lado oposto:

        sweep bearish (dir +1) → mitigada quando close > level
        sweep bullish (dir -1) → mitigada quando close < level

FONTE DE DADOS
    Pine source: `Liquidity Sweeps [LuxAlgo]` (anexo do pre-planning
    da Onda 8).
    Insumos df: 'high', 'low', 'close' + colunas da Onda 3
    (`equal_*_level/idx/alert`, `internal_*_level/idx`,
    opcionalmente `swing_*_level/idx`).
    Insumo opcional: coluna `pd_zone` da Onda 4 (quando
    `qualify_with_pd_zone=True`).

LIMITAÇÕES CONHECIDAS
    Detector usa modo 'Wicks + Outbreaks & Retest' do Pine (cobertura
        completa). Outros modos não expostos como flag — saída separa
        as classes via colunas `_wick` vs `_retest`, caller filtra
        conforme desejado.

    Forward-fill interno de `*_level` é IMPLÍCITO via pool de pivots
        — não há ffill no df de entrada. A inscrição no pool no candle
        de confirmação captura o `price` do pivot, e o pool mantém esse
        valor disponível em todos os candles subsequentes até mitigação
        ou idade máxima. Preserva o df de entrada intocado.

    Pool de pivots é mantido como dicts em memória durante a execução
        (estado local). Função permanece pura (sem side effects no df
        nem variáveis globais).

    Quando `pivot_sources` inclui `'swing'`, pode haver duplicação com
        eventos BOS swing (Onda 5). Decisão deliberada de manter
        `'swing'` como hook (não default).

    Identidade de pivots adjacentes: cada candle com `*_level != NaN`
        cria um novo entry no pool, mesmo que o valor numérico coincida
        com pivot anterior (Pine fonte cria entry distinto em `aPivH`
        para cada `ta.pivothigh(len, len)` confirmado).

    Last-write-wins: quando múltiplos pivots disparam o MESMO tipo de
        evento no MESMO candle (caso degenerado raro — vide Cenário J
        do smoke test), as colunas `*_level_idx` / `*_level_price`
        registram o pivot mais recente processado. A coluna booleana
        permanece True (idempotente).

    Cleanup remove pivots quando `tak` ou `mit` (death post-break) ou
        idade > `sweep_max_pivot_age_bars`. Sweep area pendente em
        pivot `tak=True` é abandonada — mas como o retest fire requer
        close > level (high_pool) ou close < level (low_pool), e a
        mitigação requer o oposto, mitigação na MESMA candle é
        impossível por construção.

NÃO FAZER
    Não consumir BOS/CHoCH (Onda 5) — confirmação pós-sweep é
        responsabilidade da state machine (Onda 9.5).
    Não modificar colunas existentes do df — apenas adicionar.
    Não emitir sinais duplicados sobre o mesmo pivot — o flag `wic`
        (uma vez disparado wick sweep) e a transição para `brk=true`
        (outbreak iniciado) garantem one-shot por classe.
    Não usar `equal_*_alert` como insumo de detecção — apenas como
        sinalização de "novo pivot formou-se". Detecção usa `*_level`
        e `*_idx`.
    Não aplicar `df[level_col].ffill()` no df de entrada — o pool
        substitui o ffill.
    Não inline-ar nomes de coluna — usar as constantes COL_SWEEP_*
        definidas no topo do módulo.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .pivots import (
    COL_EQUAL_HIGH_LEVEL, COL_EQUAL_HIGH_IDX, COL_EQUAL_HIGH_ALERT,
    COL_EQUAL_LOW_LEVEL, COL_EQUAL_LOW_IDX, COL_EQUAL_LOW_ALERT,
    COL_INTERNAL_HIGH_LEVEL, COL_INTERNAL_HIGH_IDX,
    COL_INTERNAL_LOW_LEVEL, COL_INTERNAL_LOW_IDX,
    COL_SWING_HIGH_LEVEL, COL_SWING_HIGH_IDX,
    COL_SWING_LOW_LEVEL, COL_SWING_LOW_IDX,
)
from .trailing import COL_PD_ZONE


# ============================================================
# Nomes canônicos das colunas produzidas por
# detect_liquidity_sweeps. Consumidores referenciam estas
# constantes — não inline-ar as strings.
# ============================================================

# Eventos primários — 4 colunas booleanas
COL_SWEEP_BULLISH_WICK = 'sweep_bullish_wick'
COL_SWEEP_BEARISH_WICK = 'sweep_bearish_wick'
COL_SWEEP_BULLISH_RETEST = 'sweep_bullish_retest'
COL_SWEEP_BEARISH_RETEST = 'sweep_bearish_retest'

# Referência ao pivot varrido
COL_SWEEP_BULLISH_LEVEL_IDX = 'sweep_bullish_level_idx'
COL_SWEEP_BEARISH_LEVEL_IDX = 'sweep_bearish_level_idx'
COL_SWEEP_BULLISH_LEVEL_PRICE = 'sweep_bullish_level_price'
COL_SWEEP_BEARISH_LEVEL_PRICE = 'sweep_bearish_level_price'

# Mitigação da sweep area
COL_SWEEP_BULLISH_MITIGATED = 'sweep_bullish_mitigated'
COL_SWEEP_BEARISH_MITIGATED = 'sweep_bearish_mitigated'

# Opcional (qualify_with_pd_zone=True)
COL_SWEEP_BULLISH_PD_ZONE = 'sweep_bullish_pd_zone'
COL_SWEEP_BEARISH_PD_ZONE = 'sweep_bearish_pd_zone'


# Mapa de source → (level_col_high, idx_col_high, level_col_low, idx_col_low).
_SOURCE_COLS: dict[str, tuple[str, str, str, str]] = {
    'equal': (
        COL_EQUAL_HIGH_LEVEL, COL_EQUAL_HIGH_IDX,
        COL_EQUAL_LOW_LEVEL, COL_EQUAL_LOW_IDX,
    ),
    'internal': (
        COL_INTERNAL_HIGH_LEVEL, COL_INTERNAL_HIGH_IDX,
        COL_INTERNAL_LOW_LEVEL, COL_INTERNAL_LOW_IDX,
    ),
    'swing': (
        COL_SWING_HIGH_LEVEL, COL_SWING_HIGH_IDX,
        COL_SWING_LOW_LEVEL, COL_SWING_LOW_IDX,
    ),
}

_ALLOWED_SOURCES: frozenset[str] = frozenset(_SOURCE_COLS.keys())


def _validate_inputs(
    df: pd.DataFrame,
    pivot_sources: tuple[str, ...],
    sweep_max_extension_bars: int,
    sweep_max_pivot_age_bars: int,
    qualify_with_pd_zone: bool,
) -> None:
    """Validações de §3.6 do briefing. Falhas → ValueError com mensagem
    explicativa. Validações são realizadas no início do detector,
    antes de qualquer alocação."""
    if not pivot_sources:
        raise ValueError(
            "pivot_sources não pode ser tupla vazia; aceita "
            f"subset de {sorted(_ALLOWED_SOURCES)!r}"
        )
    for source in pivot_sources:
        if source not in _ALLOWED_SOURCES:
            raise ValueError(
                f"pivot_sources contém valor inválido {source!r}; "
                f"aceita apenas {sorted(_ALLOWED_SOURCES)!r}"
            )
    if sweep_max_extension_bars < 1:
        raise ValueError(
            f"sweep_max_extension_bars deve ser >= 1; recebeu "
            f"{sweep_max_extension_bars}"
        )
    if sweep_max_pivot_age_bars < sweep_max_extension_bars:
        raise ValueError(
            "sweep_max_pivot_age_bars deve ser >= "
            "sweep_max_extension_bars; recebeu "
            f"{sweep_max_pivot_age_bars} < {sweep_max_extension_bars}"
        )
    if qualify_with_pd_zone and COL_PD_ZONE not in df.columns:
        raise ValueError(
            "qualify_with_pd_zone=True requer Onda 4 "
            "(compute_trailing_extremes) aplicada antes — coluna "
            f"{COL_PD_ZONE!r} ausente no df"
        )
    for source in pivot_sources:
        for col in _SOURCE_COLS[source]:
            if col not in df.columns:
                raise ValueError(
                    f"pivot_sources inclui {source!r} mas coluna "
                    f"{col!r} ausente no df — rodar detect_pivots "
                    "(Onda 3) antes"
                )


def detect_liquidity_sweeps(
    df: pd.DataFrame,
    *,
    pivot_sources: tuple[str, ...] = ('equal', 'internal'),
    sweep_max_extension_bars: int = 300,
    sweep_max_pivot_age_bars: int = 2000,
    qualify_with_pd_zone: bool = False,
) -> pd.DataFrame:
    """
    OBJETIVO
        Detectar Liquidity Sweeps (varridas de liquidez) sobre pivots
        previamente identificados pela Onda 3. Portado verbatim do Pine
        `Liquidity Sweeps [LuxAlgo]` (indicador gratuito, separado do
        SMC principal).

        Captura duas classes de sweep:
        1. WICK SWEEP — wick fura o pivot e o close volta para o lado
           original (sem rompimento de close prévio).
        2. OUTBREAK & RETEST — primeiro um close rompe o pivot,
           depois a mecha volta a furar o nível pelo lado de dentro
           com close de volta (false breakout).

    FONTE DE DADOS
        Pine source: `Liquidity Sweeps [LuxAlgo]` (anexo do pre-planning
        da Onda 8).
        Insumos df: 'high', 'low', 'close' + colunas da Onda 3
        (`equal_*_level/idx/alert`, `internal_*_level/idx`,
        opcionalmente `swing_*_level/idx`).
        Insumo opcional: coluna `pd_zone` da Onda 4 (se
        `qualify_with_pd_zone=True`).

    PARÂMETROS
        df: DataFrame com OHLC + colunas da Onda 3 já aplicadas.
        pivot_sources: tupla de strings — quais pivots entram como
            "liquidez". Aceita 'equal', 'internal', 'swing'.
            Default `('equal', 'internal')`.
        sweep_max_extension_bars: paridade com `maxB=300` do Pine.
            Quantos candles após o sweep a "sweep area" continua
            ativa para fins de mitigação.
        sweep_max_pivot_age_bars: paridade com hardcoded `2000` do
            Pine. Pivots mais antigos que isso são purgados do pool
            independentemente de mitigação.
        qualify_with_pd_zone: se True, anota cada sweep com a zona
            PD vigente (requer Onda 4 já aplicada ao df).

    LIMITAÇÕES CONHECIDAS
        Detector usa modo 'Wicks + Outbreaks & Retest' do Pine
            (cobertura completa). Outros modos não expostos como flag
            — saída separa as classes via colunas `_wick` vs `_retest`,
            caller filtra conforme desejado.
        Forward-fill interno de `*_level` é estritamente para
            rastreamento de pivots — não altera o df de entrada.
        Pool de pivots é mantido como dicts em memória durante a
            execução. Função permanece pura (sem side effects no df).
        Quando `pivot_sources` inclui `'swing'`, pode haver duplicação
            com eventos BOS swing (Onda 5). Decisão deliberada de
            manter `'swing'` como hook (não default).

    NÃO FAZER
        Não consumir BOS/CHoCH (Onda 5) — confirmação pós-sweep é
            responsabilidade da state machine (Onda 9.5).
        Não modificar colunas existentes do df — apenas adicionar.
        Não emitir sinais duplicados sobre o mesmo pivot — o flag
            `wic` (uma vez disparado wick sweep) e a transição para
            `brk=true` (outbreak iniciado) garantem one-shot por
            classe.
        Não usar `equal_*_alert` como insumo de detecção — apenas
            como sinalização de "novo pivot formou-se". Detecção usa
            `*_level` e `*_idx`.

    RETORNO
        Cópia do df de entrada com colunas anexadas (ver constantes
        COL_SWEEP_* exportadas no módulo).
    """
    _validate_inputs(
        df, pivot_sources,
        sweep_max_extension_bars, sweep_max_pivot_age_bars,
        qualify_with_pd_zone,
    )

    result = df.copy()
    n = len(df)

    # Buffers de saída — booleans em numpy, level_idx via lista
    # convertida a Int64 nullable no final, level_price em float64
    # com NaN. Equal_*_alert NÃO é insumo (NÃO FAZER do briefing).
    bullish_wick = np.zeros(n, dtype=bool)
    bearish_wick = np.zeros(n, dtype=bool)
    bullish_retest = np.zeros(n, dtype=bool)
    bearish_retest = np.zeros(n, dtype=bool)
    bullish_mitigated = np.zeros(n, dtype=bool)
    bearish_mitigated = np.zeros(n, dtype=bool)

    bullish_level_idx: list = [pd.NA] * n
    bearish_level_idx: list = [pd.NA] * n
    bullish_level_price = np.full(n, np.nan, dtype='float64')
    bearish_level_price = np.full(n, np.nan, dtype='float64')

    if qualify_with_pd_zone:
        bullish_pd_zone: list = [pd.NA] * n
        bearish_pd_zone: list = [pd.NA] * n
        pd_zone_series = df[COL_PD_ZONE]

    # Pré-extrai arrays OHLC para o loop principal.
    high_arr = df['high'].to_numpy(dtype='float64')
    low_arr = df['low'].to_numpy(dtype='float64')
    close_arr = df['close'].to_numpy(dtype='float64')

    # Pré-extrai arrays de cada source (level + idx, high e low).
    source_arrays: list[tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]] = []
    for source in pivot_sources:
        hl_col, hi_col, ll_col, li_col = _SOURCE_COLS[source]
        source_arrays.append((
            df[hl_col].to_numpy(dtype='float64'),
            df[hi_col].to_numpy(dtype='float64'),
            df[ll_col].to_numpy(dtype='float64'),
            df[li_col].to_numpy(dtype='float64'),
        ))

    # Pools — chave é pivot_id auto-incremento (vide §7 do briefing:
    # cada candle com level != NaN cria entry distinto, mesmo se
    # preço coincidir com pivot anterior).
    high_pool: dict[int, dict] = {}
    low_pool: dict[int, dict] = {}
    next_id = 0

    for t in range(n):
        h = high_arr[t]
        l = low_arr[t]
        c = close_arr[t]

        # === 1. Inscrição de novos pivots ===
        # Cada source pode contribuir 1 pivot high e/ou 1 pivot low.
        # Equal_*_alert NÃO é consultado — apenas *_level e *_idx
        # (NÃO FAZER do briefing).
        for hl_arr, hi_arr, ll_arr, li_arr in source_arrays:
            if not np.isnan(hl_arr[t]):
                high_pool[next_id] = {
                    'price': float(hl_arr[t]),
                    'idx': int(hi_arr[t]),
                    'confirmed_at': t,
                    'brk': False,
                    'wic': False,
                    'tak': False,
                    'mit': False,
                    'sweep_idx': None,
                    'sweep_direction': None,
                    'swept_mit': False,
                }
                next_id += 1
            if not np.isnan(ll_arr[t]):
                low_pool[next_id] = {
                    'price': float(ll_arr[t]),
                    'idx': int(li_arr[t]),
                    'confirmed_at': t,
                    'brk': False,
                    'wic': False,
                    'tak': False,
                    'mit': False,
                    'sweep_idx': None,
                    'sweep_direction': None,
                    'swept_mit': False,
                }
                next_id += 1

        # === 2. Atualização de pivots de máxima (high_pool) ===
        for p in high_pool.values():
            if p['mit']:
                continue
            price = p['price']
            if not p['brk']:
                # Pré-break — detecta close-break (transita p/ pós-break)
                # ou wick sweep bearish (one-shot).
                if c > price:
                    p['brk'] = True
                if not p['wic'] and h > price and c < price:
                    # WICK SWEEP BEARISH (varredura de stops de compradores).
                    bearish_wick[t] = True
                    bearish_level_idx[t] = p['idx']
                    bearish_level_price[t] = price
                    if qualify_with_pd_zone:
                        bearish_pd_zone[t] = pd_zone_series.iloc[t]
                    p['wic'] = True
                    p['sweep_idx'] = t
                    p['sweep_direction'] = +1
                    p['swept_mit'] = False
            else:
                # Pós-break — detecta morte do break (close volta abaixo)
                # ou outbreak & retest bullish (one-shot).
                if c < price:
                    p['mit'] = True
                if not p['tak'] and l < price and c > price:
                    # OUTBREAK & RETEST BULLISH (false-breakdown invertido:
                    # preço quebrou pra cima, mecha desce, close fecha
                    # de volta acima → breakout válido).
                    bullish_retest[t] = True
                    bullish_level_idx[t] = p['idx']
                    bullish_level_price[t] = price
                    if qualify_with_pd_zone:
                        bullish_pd_zone[t] = pd_zone_series.iloc[t]
                    p['tak'] = True
                    p['sweep_idx'] = t
                    p['sweep_direction'] = -1
                    p['swept_mit'] = False

        # === 3. Atualização de pivots de mínima (low_pool) — simétrico ===
        for p in low_pool.values():
            if p['mit']:
                continue
            price = p['price']
            if not p['brk']:
                if c < price:
                    p['brk'] = True
                if not p['wic'] and l < price and c > price:
                    # WICK SWEEP BULLISH (varredura de stops de vendedores).
                    bullish_wick[t] = True
                    bullish_level_idx[t] = p['idx']
                    bullish_level_price[t] = price
                    if qualify_with_pd_zone:
                        bullish_pd_zone[t] = pd_zone_series.iloc[t]
                    p['wic'] = True
                    p['sweep_idx'] = t
                    p['sweep_direction'] = -1
                    p['swept_mit'] = False
            else:
                if c > price:
                    p['mit'] = True
                if not p['tak'] and h > price and c < price:
                    # OUTBREAK & RETEST BEARISH.
                    bearish_retest[t] = True
                    bearish_level_idx[t] = p['idx']
                    bearish_level_price[t] = price
                    if qualify_with_pd_zone:
                        bearish_pd_zone[t] = pd_zone_series.iloc[t]
                    p['tak'] = True
                    p['sweep_idx'] = t
                    p['sweep_direction'] = +1
                    p['swept_mit'] = False

        # === 4. Mitigação de sweep areas ===
        # Para cada pivot com sweep_idx setado e área ainda não
        # mitigada, verifica retorno do close ao lado oposto dentro
        # da janela de extensão. Mitigação no MESMO candle do sweep é
        # impossível por construção (predicados mutuamente exclusivos).
        for pool in (high_pool, low_pool):
            for p in pool.values():
                if p['sweep_idx'] is None or p['swept_mit']:
                    continue
                if t - p['sweep_idx'] > sweep_max_extension_bars:
                    continue
                price = p['price']
                if p['sweep_direction'] == -1 and c < price:
                    bullish_mitigated[t] = True
                    p['swept_mit'] = True
                elif p['sweep_direction'] == +1 and c > price:
                    bearish_mitigated[t] = True
                    p['swept_mit'] = True

        # === 5. Cleanup ===
        # Remove pivots cuja vida acabou: post-break morto (mit), retest
        # já tirado (tak), ou idade excedida.
        for pool in (high_pool, low_pool):
            dead = [
                pid for pid, p in pool.items()
                if (p['mit'] or p['tak'])
                or (t - p['confirmed_at'] > sweep_max_pivot_age_bars)
            ]
            for pid in dead:
                del pool[pid]

    # Montagem das colunas de saída.
    result[COL_SWEEP_BULLISH_WICK] = bullish_wick
    result[COL_SWEEP_BEARISH_WICK] = bearish_wick
    result[COL_SWEEP_BULLISH_RETEST] = bullish_retest
    result[COL_SWEEP_BEARISH_RETEST] = bearish_retest
    result[COL_SWEEP_BULLISH_LEVEL_IDX] = pd.array(
        bullish_level_idx, dtype='Int64',
    )
    result[COL_SWEEP_BEARISH_LEVEL_IDX] = pd.array(
        bearish_level_idx, dtype='Int64',
    )
    result[COL_SWEEP_BULLISH_LEVEL_PRICE] = bullish_level_price
    result[COL_SWEEP_BEARISH_LEVEL_PRICE] = bearish_level_price
    result[COL_SWEEP_BULLISH_MITIGATED] = bullish_mitigated
    result[COL_SWEEP_BEARISH_MITIGATED] = bearish_mitigated
    if qualify_with_pd_zone:
        result[COL_SWEEP_BULLISH_PD_ZONE] = pd.array(
            bullish_pd_zone, dtype='string',
        )
        result[COL_SWEEP_BEARISH_PD_ZONE] = pd.array(
            bearish_pd_zone, dtype='string',
        )

    return result
