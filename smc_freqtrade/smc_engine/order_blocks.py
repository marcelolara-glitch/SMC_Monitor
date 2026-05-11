"""
OBJETIVO
    Portagem vetorizada de storeOrdeBlock() + deleteOrderBlocks() do
    LuxAlgo SMC (Pine linhas 200-236), integrada via re-leitura das 8
    booleans BOS/CHoCH da Onda 5. Detecta criação e mitigação de
    Order Blocks em duas escalas (internal e swing) e duas direções
    (bullish e bearish).

    Primeira onda do projeto cuja unidade de saída tem ciclo de vida
    multi-candle (criação → ativo → mitigado). Wave 6 emite apenas
    `state ∈ {'active', 'mitigated'}` (`'breaker'` é hook Onda 6.2).

FONTE DE DADOS
    DataFrame com 4 colunas OHLC ('open', 'high', 'low', 'close'),
    coluna 'date' (Int64 epoch ms ou pd.Timestamp), 4 colunas
    COL_*_IDX produzidas por detect_pivots (Onda 3) e 8 booleans
    BOS/CHoCH produzidas por detect_structure (Onda 5).

LIMITAÇÕES CONHECIDAS
    Lookahead-safe por construção: consome apenas colunas já
    materializadas pelas Ondas 3 e 5 (todas lookahead-safe). Nenhum
    `shift(-N)` interno.

    Política de mitigação `date > t_creation` estritamente posterior
    (briefing §2 P11) diverge sutilmente do Pine, que executa
    `deleteOrderBlocks` no mesmo candle do create. Decisão fechada:
    "OB não pode morrer ao nascer". Cenário praticamente irrelevante.

    Volumetric OB / Breaker Blocks / OB Mitigation Average NÃO são
    detectados — hooks reservados (Onda 6.1/6.2).

    Cap de 100 OBs do Pine (linhas 234-235) NÃO portado — bound de
    implementação Pine, não regra semântica (briefing §2 P10).

NÃO FAZER
    Não usar shift(-N) em ponto algum.
    Não recomputar BOS/CHoCH — consumir as 8 booleans da Onda 5.
    Não estender smc_engine/trailing.py — parsed_* ficam locais.
    Não emitir efeitos colaterais sobre o DataFrame de entrada.
    Não popular EngineState (Mapa §2 v1.1).
    Não detectar Volumetric OB — Onda 6.1.
    Não detectar Breaker Blocks — Onda 6.2.
    Não implementar mitigation='Average' — Onda 6.1.
    Não portar o cap de 100 OBs do Pine.
    Não renomear OrderBlock.bar_time → t_origin (briefing §2 P12).
"""
from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd

from .operators import atr_wilder, cum_sum, true_range
from .pivots import (
    COL_INTERNAL_HIGH_IDX,
    COL_INTERNAL_LOW_IDX,
    COL_SWING_HIGH_IDX,
    COL_SWING_LOW_IDX,
)
from .structure import (
    COL_BOS_INTERNAL_BEARISH,
    COL_BOS_INTERNAL_BULLISH,
    COL_BOS_SWING_BEARISH,
    COL_BOS_SWING_BULLISH,
    COL_CHOCH_INTERNAL_BEARISH,
    COL_CHOCH_INTERNAL_BULLISH,
    COL_CHOCH_SWING_BEARISH,
    COL_CHOCH_SWING_BULLISH,
)
from .types import BEARISH, BULLISH


# ============================================================
# Nomes canônicos das 8 colunas booleans produzidas por
# detect_order_blocks. Consumidores referenciam estas constantes —
# não inline-ar as strings (briefing §4.2).
# ============================================================
COL_OB_INTERNAL_BULLISH_CREATED = 'ob_internal_bullish_created'
COL_OB_INTERNAL_BEARISH_CREATED = 'ob_internal_bearish_created'
COL_OB_SWING_BULLISH_CREATED = 'ob_swing_bullish_created'
COL_OB_SWING_BEARISH_CREATED = 'ob_swing_bearish_created'
COL_OB_INTERNAL_BULLISH_MITIGATED = 'ob_internal_bullish_mitigated'
COL_OB_INTERNAL_BEARISH_MITIGATED = 'ob_internal_bearish_mitigated'
COL_OB_SWING_BULLISH_MITIGATED = 'ob_swing_bullish_mitigated'
COL_OB_SWING_BEARISH_MITIGATED = 'ob_swing_bearish_mitigated'


# Ordem canônica de processamento por candle (briefing §2 P7):
# internal-bullish → internal-bearish → swing-bullish → swing-bearish.
# Tuplas (scope, bias_constant, choch_col, bos_col, idx_col,
# created_col, mitigated_col).
_CREATE_PASS_ORDER: tuple[
    tuple[str, int, str, str, str, str, str], ...
] = (
    (
        'internal', BULLISH,
        COL_CHOCH_INTERNAL_BULLISH, COL_BOS_INTERNAL_BULLISH,
        COL_INTERNAL_HIGH_IDX,
        COL_OB_INTERNAL_BULLISH_CREATED, COL_OB_INTERNAL_BULLISH_MITIGATED,
    ),
    (
        'internal', BEARISH,
        COL_CHOCH_INTERNAL_BEARISH, COL_BOS_INTERNAL_BEARISH,
        COL_INTERNAL_LOW_IDX,
        COL_OB_INTERNAL_BEARISH_CREATED, COL_OB_INTERNAL_BEARISH_MITIGATED,
    ),
    (
        'swing', BULLISH,
        COL_CHOCH_SWING_BULLISH, COL_BOS_SWING_BULLISH,
        COL_SWING_HIGH_IDX,
        COL_OB_SWING_BULLISH_CREATED, COL_OB_SWING_BULLISH_MITIGATED,
    ),
    (
        'swing', BEARISH,
        COL_CHOCH_SWING_BEARISH, COL_BOS_SWING_BEARISH,
        COL_SWING_LOW_IDX,
        COL_OB_SWING_BEARISH_CREATED, COL_OB_SWING_BEARISH_MITIGATED,
    ),
)


def _compute_parsed_high_low(
    df: pd.DataFrame,
    ob_filter: str,
    atr_length: int,
) -> tuple[pd.Series, pd.Series]:
    """Pine linhas 124-128 vetorizado.

    Para velas high-volatility (`high - low >= 2 * volatility`),
    inverte high/low na construção do parsed-extreme. Para demais
    velas, parsed_high = high e parsed_low = low.
    """
    high = df['high']
    low = df['low']
    close = df['close']

    atr_measure = atr_wilder(high, low, close, length=atr_length)
    if ob_filter == 'Atr':
        volatility = atr_measure
    else:
        # Pine: `ta.cum(ta.tr) / bar_index`; bar_index é 0-based no
        # primeiro candle, mas `cum_sum(true_range)` no candle 0 é
        # NaN (close[-1] indisponível), então o divisor seguro é
        # `np.arange(1, n+1)` — `bar_index + 1` no contexto Pine,
        # equivalente a cumulativeMean naïve.
        tr = true_range(high, low, close)
        positions = pd.Series(
            np.arange(1, len(df) + 1, dtype='float64'),
            index=df.index,
        )
        volatility = cum_sum(tr) / positions

    high_vol_bar = (high - low) >= (2.0 * volatility)
    high_vol_bar = high_vol_bar.fillna(False)

    parsed_high = high.where(~high_vol_bar, low)
    parsed_low = low.where(~high_vol_bar, high)
    return parsed_high, parsed_low


def _emit_create_record(
    *,
    df: pd.DataFrame,
    parsed_high: pd.Series,
    parsed_low: pd.Series,
    break_pos: int,
    pivot_idx_raw: float,
    scope: str,
    bias: int,
) -> dict | None:
    """Constrói 1 OB record a partir do candle do break (`break_pos`,
    posicional) lendo `pivot_idx` da coluna COL_*_IDX no mesmo candle.

    Retorna `None` se a janela for inválida (pivot_idx NaN ou
    `int(pivot_idx) >= break_pos`) — briefing §4.5 passo 2b.
    """
    if pivot_idx_raw is None or pd.isna(pivot_idx_raw):
        return None
    pivot_pos = int(pivot_idx_raw)
    if pivot_pos < 0 or pivot_pos >= break_pos:
        # Janela vazia ou negativa — bug em Onda 3/5 (briefing §3.4
        # do audit; impossível em uso real, possível em smoke
        # sintético com horizonte curto).
        return None

    window_high = parsed_high.iloc[pivot_pos:break_pos]
    window_low = parsed_low.iloc[pivot_pos:break_pos]
    if window_high.empty:
        return None

    if bias == BULLISH:
        # Empate em parsed_low.min(): idxmin retorna primeira
        # ocorrência — consistente com Pine
        # array.indexof(array.min(...)). Briefing §4.5 passo 2c.
        extreme_label = window_low.idxmin()
    else:
        extreme_label = window_high.idxmax()

    bar_high = float(parsed_high.loc[extreme_label])
    bar_low = float(parsed_low.loc[extreme_label])
    bar_time = df['date'].loc[extreme_label]
    t_creation = df['date'].iloc[break_pos]

    return {
        'scope': scope,
        'bias': bias,
        'bar_high': bar_high,
        'bar_low': bar_low,
        'bar_time': bar_time,
        't_creation': t_creation,
        't_mitigation': pd.NaT,
        't_invalidation': pd.NaT,
        'state': 'active',
        'volumetric_intensity': pd.NA,
    }


def _emit_create_events(
    df: pd.DataFrame,
    parsed_high: pd.Series,
    parsed_low: pd.Series,
) -> tuple[dict[str, pd.Series], list[dict]]:
    """CREATE pass. Para cada candle X com algum dos 8 booleans True,
    emite 1 OB record por combinação (scope, bias) ativa.

    Ordem dentro de X (briefing §2 P7): internal-bullish →
    internal-bearish → swing-bullish → swing-bearish. Reflete em
    `ob_id` sequencial.
    """
    n = len(df)
    create_cols: dict[str, pd.Series] = {}
    records: list[dict] = []

    # Coletor por combinação: lista de (break_pos, OB record).
    pending_records: list[tuple[int, dict, str]] = []

    for combo in _CREATE_PASS_ORDER:
        (
            scope, bias_const, choch_col, bos_col, idx_col,
            created_col, _,
        ) = combo

        trigger_raw = df[choch_col].fillna(False).astype(bool) | (
            df[bos_col].fillna(False).astype(bool)
        )
        created_mask = pd.Series(False, index=df.index, dtype=bool)
        # Pine `p_ivot.barIndex` é Persistent (último valor materializado);
        # em pandas isso equivale a ffill do idx_col, espelhando a
        # semântica que a Onda 5 já usa em `level_col.ffill()`.
        idx_series = df[idx_col].ffill()

        # Iteração por candle de trigger (tipicamente O(dezenas) por
        # combinação sobre 720 candles 4H — aceitável). Cada record
        # é independente; agrupamos por ordem global (break_pos,
        # ordem da combinação) para enumerar ob_id no final.
        positions = np.flatnonzero(trigger_raw.to_numpy())
        for break_pos in positions:
            pivot_idx_raw = idx_series.iloc[int(break_pos)]
            record = _emit_create_record(
                df=df,
                parsed_high=parsed_high,
                parsed_low=parsed_low,
                break_pos=int(break_pos),
                pivot_idx_raw=pivot_idx_raw,
                scope=scope,
                bias=bias_const,
            )
            if record is None:
                continue
            label = df.index[int(break_pos)]
            created_mask.loc[label] = True
            pending_records.append((int(break_pos), record, created_col))

        create_cols[created_col] = created_mask

    # Ordenação por ordem canônica do briefing §2 P7:
    # primeiro break_pos (candle), depois ordem da combinação dentro
    # do candle. _CREATE_PASS_ORDER já é a ordem desejada — `stable`
    # preserva inserção por combinação.
    combo_priority = {
        c[5]: i for i, c in enumerate(_CREATE_PASS_ORDER)
    }
    pending_records.sort(
        key=lambda item: (item[0], combo_priority[item[2]]),
    )

    for ob_id, (_break_pos, record, _created_col) in enumerate(pending_records):
        record_with_id = {'ob_id': ob_id, **record}
        records.append(record_with_id)

    return create_cols, records


def _resolve_mitigations(
    df: pd.DataFrame,
    records: list[dict],
    mitigation: str,
) -> tuple[dict[str, pd.Series], list[dict]]:
    """MITIGATION pass. Para cada OB, busca primeira vela
    `date > t_creation` que satisfaz a condição de mitigação.

    Pine linhas 200-221 +
        bearish_source = close if mitigation == 'Close' else high
        bullish_source = close if mitigation == 'Close' else low
    (Pine linhas 122-123). Política `date > t_creation` estrita
    (briefing §2 P11) — exclui o próprio candle do CREATE.
    """
    n = len(df)
    mitigated_cols: dict[str, pd.Series] = {
        combo[6]: pd.Series(False, index=df.index, dtype=bool)
        for combo in _CREATE_PASS_ORDER
    }

    # Indexação por scope/bias → coluna mitigated correspondente.
    mitigated_col_lookup: dict[tuple[str, int], str] = {
        (combo[0], combo[1]): combo[6] for combo in _CREATE_PASS_ORDER
    }

    if mitigation == 'Close':
        bearish_source = df['close']
        bullish_source = df['close']
    else:
        # 'Wick' = HIGHLOW no Pine.
        bearish_source = df['high']
        bullish_source = df['low']

    dates = df['date']
    out_records: list[dict] = []
    for record in records:
        scope = record['scope']
        bias = record['bias']
        t_creation = record['t_creation']
        bar_high = record['bar_high']
        bar_low = record['bar_low']

        # Filtro `date > t_creation` (estritamente posterior, P11).
        after_create = dates > t_creation
        if bias == BEARISH:
            hits = after_create & (bearish_source > bar_high)
        else:
            hits = after_create & (bullish_source < bar_low)

        new_record = dict(record)
        if hits.any():
            hit_label = df.index[hits.to_numpy().argmax()]
            t_mit = dates.loc[hit_label]
            new_record['t_mitigation'] = t_mit
            new_record['state'] = 'mitigated'

            mit_col = mitigated_col_lookup[(scope, bias)]
            mitigated_cols[mit_col].loc[hit_label] = True

        out_records.append(new_record)

    return mitigated_cols, out_records


def _build_ledger(records: list[dict]) -> pd.DataFrame:
    """Constrói DataFrame ledger com schema canônico (briefing §4.3).

    11 colunas: ob_id, scope, bias, bar_high, bar_low, bar_time,
    t_creation, t_mitigation, t_invalidation, state,
    volumetric_intensity.
    """
    columns = [
        'ob_id', 'scope', 'bias', 'bar_high', 'bar_low', 'bar_time',
        't_creation', 't_mitigation', 't_invalidation', 'state',
        'volumetric_intensity',
    ]
    if not records:
        # Ledger vazio com schema correto.
        return pd.DataFrame({c: pd.Series(dtype='object') for c in columns})

    ledger = pd.DataFrame(records, columns=columns)
    ledger['ob_id'] = ledger['ob_id'].astype('Int64')
    ledger['scope'] = ledger['scope'].astype('string')
    ledger['bias'] = ledger['bias'].astype('Int8')
    ledger['bar_high'] = ledger['bar_high'].astype('float64')
    ledger['bar_low'] = ledger['bar_low'].astype('float64')
    ledger['state'] = ledger['state'].astype('string')
    # volumetric_intensity: Wave 6 sempre pd.NA — dtype float64 nullable.
    ledger['volumetric_intensity'] = ledger['volumetric_intensity'].astype(
        'Float64',
    )
    return ledger


def detect_order_blocks(
    df: pd.DataFrame,
    *,
    ob_filter: Literal['Atr', 'Range'] = 'Atr',
    mitigation: Literal['Close', 'Wick'] = 'Wick',
    atr_length: int = 200,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    OBJETIVO
        Portagem vetorizada de storeOrdeBlock() + deleteOrderBlocks()
        do LuxAlgo SMC (Pine linhas 200-236), integrada via re-leitura
        das 8 booleans BOS/CHoCH da Onda 5. Detecta criação e
        mitigação de Order Blocks em duas escalas (internal e swing)
        e duas direções (bullish e bearish), produzindo (a) um
        DataFrame com 8 eventos booleans por candle e (b) um ledger
        com uma linha por OB de ciclo de vida completo.

    FONTE DE DADOS
        df: DataFrame com no mínimo:
            - 4 colunas OHLC: open, high, low, close (float64).
            - Coluna `date` (Int64 epoch ms ou pd.Timestamp) —
              timestamp canônico usado para preencher bar_time,
              t_creation e t_mitigation no ledger.
            - 4 colunas COL_*_IDX produzidas por detect_pivots()
              (Onda 3) para os escopos swing e internal.
            - 8 booleans BOS/CHoCH produzidas por detect_structure()
              (Onda 5).
        ob_filter: replica orderBlockFilterInput do Pine (linha 87).
            'Atr' usa ta.atr(atr_length); 'Range' usa
            ta.cum(ta.tr) / bar_index. Determina volatilityMeasure
            para detecção de high-volatility bars na inversão de
            parsedHigh/parsedLow.
        mitigation: replica orderBlockMitigationInput do Pine
            (linha 88). 'Wick' (default, = HIGHLOW no Pine) usa
            high/low como fonte de mitigação; 'Close' usa close.
            Aceita apenas 'Close' e 'Wick' em Wave 6 — valor 'Average'
            (midpoint da caixa, `(bar_high + bar_low) / 2`) é hook
            reservado para Onda 6.1 (LuxAlgo Price Action Concepts
            pago).
        atr_length: replica o length de ta.atr() no Pine (linha 124,
            hardcoded em 200). Exposto como parâmetro para facilitar
            testes sintéticos com horizonte curto.

    LIMITAÇÕES CONHECIDAS
        Lookahead-safe por construção: consome apenas COL_*_IDX e
            8 booleans já materializados pelas ondas 3 e 5 (todos
            lookahead-safe). Nenhum shift(-N) interno.

        Política de mitigação `date > t_creation` (estritamente
            posterior) diverge sutilmente do Pine (que executa
            deleteOrderBlocks no MESMO candle do create). Decisão
            fechada no briefing da Onda 6 §2 P11 — "OB não pode
            morrer ao nascer". Cenário praticamente irrelevante
            (close cruza pivot mas wicks raramente furam lado oposto
            da janela no mesmo candle).

        Volumetric Order Blocks (LuxAlgo pago) NÃO são detectados
            nesta onda. Hook reservado: campo
            OrderBlock.volumetric_intensity default None. Decisão
            arquitetural fechada no briefing da Onda 6: feature do
            LuxAlgo Price Action Concepts pago, adiada para
            Onda 6.1 com hook explícito. Ver
            docs/AVALIACAO_LUXALGO_PRICE_ACTION_CONCEPTS_v1.0.md
            §4.2 (spec conceitual) e §6.2 (classificação Categoria B
            — extensão sem mudança arquitetural; preenche
            volumetric_intensity durante o CREATE pass somando
            volume da janela [pivot_idx, break_idx)).

            Pré-condição Onda 6.1: DataFrame de entrada deve incluir
            coluna `volume` (padrão Freqtrade OHLCV). Não é
            pré-condição da Wave 6 base — apenas da extensão Onda
            6.1.

        Breaker Blocks (LuxAlgo pago) NÃO são detectados nesta onda.
            Hook reservado: campo OrderBlock.state aceita futuro
            valor 'breaker' (Wave 6 só emite 'active' e 'mitigated').
            Decisão arquitetural fechada no briefing da Onda 6:
            adiada para Onda 6.2 (refatora _resolve_mitigations para
            state-aware: 'active' → 'breaker' em vez de remoção;
            segunda mitigação remove definitivamente).

        OB Mitigation Method = Average (LuxAlgo pago) NÃO é
            implementada nesta onda. Hook reservado: parâmetro
            mitigation aceita futuro valor 'Average'. Adiada para
            Onda 6.1.

        Cap de 100 OBs do Pine (linhas 234-235) NÃO é portado —
            bound de implementação Pine, não regra semântica.

    NÃO FAZER
        Não usar shift(-N) em ponto algum.
        Não recomputar BOS/CHoCH — consumir as 8 booleans da Onda 5.
        Não estender smc_engine/trailing.py (Onda 4) — parsed_*
            ficam locais ao módulo order_blocks.py.
        Não emitir efeitos colaterais sobre o DataFrame de entrada
            (operar sobre df.copy()).
        Não inline-ar nomes de coluna — usar as constantes COL_OB_*
            definidas no topo do módulo.
        Não popular EngineState (Mapa §2 v1.1) — a portagem é
            vetorizada sobre DataFrame; o ledger substitui os slots
            `swing_order_blocks` / `internal_order_blocks` do
            EngineState herdado do Pine.
        Não detectar Volumetric OB — Onda 6.1.
        Não detectar Breaker Blocks — Onda 6.2.
        Não implementar mitigation='Average' — Onda 6.1.
        Não portar o cap de 100 OBs do Pine.
        Não renomear OrderBlock.bar_time → t_origin (P12).
    """
    if ob_filter not in ('Atr', 'Range'):
        raise ValueError(
            f"ob_filter must be 'Atr' or 'Range', got {ob_filter!r}",
        )
    if mitigation not in ('Close', 'Wick'):
        raise ValueError(
            f"mitigation must be 'Close' or 'Wick' in Wave 6, got "
            f"{mitigation!r}. 'Average' é hook Onda 6.1.",
        )

    df_per_candle = df.copy()
    parsed_high, parsed_low = _compute_parsed_high_low(
        df, ob_filter=ob_filter, atr_length=atr_length,
    )

    create_cols, records = _emit_create_events(
        df, parsed_high=parsed_high, parsed_low=parsed_low,
    )
    mitigated_cols, records = _resolve_mitigations(
        df, records=records, mitigation=mitigation,
    )

    for col, series in create_cols.items():
        df_per_candle[col] = series.astype(bool)
    for col, series in mitigated_cols.items():
        df_per_candle[col] = series.astype(bool)

    ledger = _build_ledger(records)
    return df_per_candle, ledger
