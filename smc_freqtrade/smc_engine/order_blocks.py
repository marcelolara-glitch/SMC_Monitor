"""
OBJETIVO
    Portagem vetorizada de storeOrdeBlock() + deleteOrderBlocks() do
    LuxAlgo SMC (Pine linhas 200-236), integrada via re-leitura das 8
    booleans BOS/CHoCH da Onda 5. Detecta criação e mitigação de
    Order Blocks em duas escalas (internal e swing) e duas direções
    (bullish e bearish).

    Onda 6.2 estende o módulo com Breaker Blocks (PAC/FluxCharts): a
    mitigação da Onda 6 já é o nascimento do breaker; a 6.2 detecta a
    MORTE do breaker (preço sai pela extremidade oposta) e captura o
    volume do candle da mitigação em `bb_volume`. Estado vai de
    `'mitigated'` (breaker vivo) para `'breaker_broken'` (breaker
    morto), preenchendo `t_invalidation`.

    Primeira onda do projeto cuja unidade de saída tem ciclo de vida
    multi-candle (criação → ativo → mitigado → breaker_broken).
    Vocabulário de estado: `state ∈ {'active', 'mitigated',
    'breaker_broken'}`.

FONTE DE DADOS
    DataFrame com 4 colunas OHLC ('open', 'high', 'low', 'close'),
    coluna 'date' (Int64 epoch ms ou pd.Timestamp), 4 colunas
    COL_*_IDX produzidas por detect_pivots (Onda 3) e 8 booleans
    BOS/CHoCH produzidas por detect_structure (Onda 5). Coluna
    `volume` é opcional: quando presente, alimenta `bb_volume` no
    candle da mitigação; quando ausente, `bb_volume` permanece
    `pd.NA`. Volume NÃO é pré-condição da Wave 6/6.2.

LIMITAÇÕES CONHECIDAS
    Lookahead-safe por construção: consome apenas colunas já
    materializadas pelas Ondas 3 e 5 (todas lookahead-safe). Nenhum
    `shift(-N)` interno. Scan de morte do breaker é forward com
    `date > t_mitigation` estritamente posterior (espelha P11 — o
    breaker não pode morrer no candle em que nasce).

    Política de mitigação `date > t_creation` estritamente posterior
    (briefing §2 P11) diverge sutilmente do Pine, que executa
    `deleteOrderBlocks` no mesmo candle do create. Decisão fechada:
    "OB não pode morrer ao nascer". Cenário praticamente irrelevante.

    Divergência intencional vs PAC/FluxCharts: o PAC remove o
    breaker morto da lista; aqui preservamos o registro com
    `state = 'breaker_broken'` (histórico imutável). Análogo à
    divergência FVG full-fill registrada no Mapa §7.10.

    Onda 6.1 estende com Volumetric OB (4 campos volumétricos:
    `volume_bullish`, `volume_bearish`, `volume_total`, `volume_pct`)
    e eixo ortogonal `ob_mitigation_level` (`'Absolute'`/`'Middle'`).
    Fórmulas volumétricas derivadas do Pine FluxCharts "Volumized
    Order Blocks" (MPL 2.0); mitigação Middle derivada do LuxAlgo
    PAC pago. `volume_pct` é fórmula derivada da definição PAC
    verbatim, sem código de referência PAC paid disponível;
    denominador computado no instante de criação sobre OBs ativos
    naquele instante (lookahead-safe).

    Cap de 100 OBs do Pine (linhas 234-235) NÃO portado — bound de
    implementação Pine, não regra semântica (briefing §2 P10).

NÃO FAZER
    Não usar shift(-N) em ponto algum.
    Não recomputar BOS/CHoCH — consumir as 8 booleans da Onda 5.
    Não estender smc_engine/trailing.py — parsed_* ficam locais.
    Não emitir efeitos colaterais sobre o DataFrame de entrada.
    Não popular EngineState (Mapa §2 v1.1).
    Não portar o cap de 100 OBs do Pine.
    Não renomear OrderBlock.bar_time → t_origin (briefing §2 P12).
    Não emitir booleans per-candle de morte de breaker — derivável
        do ledger via t_invalidation; per-candle "breaker vivo em X"
        é escopo da Onda 9.4 (engine MTF).
    Não materializar `is_breaker` — derivável: `state == 'mitigated'`
        ⇔ breaker vivo; `state == 'breaker_broken'` ⇔ breaker morto.
    Não implementar OB ATR size filter (FluxCharts) — §10 HOOKS.
    Não implementar OB Combination (FluxCharts) — §10 HOOKS.
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

    # Volumetric fields (Wave 6.1 — FluxCharts formula §2.3/§2.4).
    has_volume = 'volume' in df.columns
    volume_bullish = pd.NA
    volume_bearish = pd.NA
    volume_total = pd.NA

    if has_volume:
        extreme_pos = df.index.get_loc(extreme_label)
        t_pos = extreme_pos + 2
        if t_pos <= break_pos and t_pos < len(df):
            vol_base = df['volume'].iloc[extreme_pos]
            vol_plus_1 = df['volume'].iloc[extreme_pos + 1]
            vol_plus_2 = df['volume'].iloc[extreme_pos + 2]
            if (
                pd.notna(vol_base)
                and pd.notna(vol_plus_1)
                and pd.notna(vol_plus_2)
            ):
                vol_base = float(vol_base)
                vol_plus_1 = float(vol_plus_1)
                vol_plus_2 = float(vol_plus_2)
                if bias == BULLISH:
                    volume_bearish = vol_base
                    volume_bullish = vol_plus_1 + vol_plus_2
                else:
                    volume_bullish = vol_base
                    volume_bearish = vol_plus_1 + vol_plus_2
                volume_total = volume_bullish + volume_bearish

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
        'volume_bullish': volume_bullish,
        'volume_bearish': volume_bearish,
        'volume_total': volume_total,
        'volume_pct': pd.NA,
        'bb_volume': pd.NA,
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
    ob_mitigation_level: str = 'Absolute',
) -> tuple[dict[str, pd.Series], list[dict]]:
    """MITIGATION + BREAKER DEATH pass. Para cada OB, busca primeira
    vela `date > t_creation` que satisfaz a condição de mitigação;
    se houver mitigação (= nascimento do breaker, PAC/FluxCharts),
    continua o scan a partir do candle seguinte buscando a morte do
    breaker pela extremidade OPOSTA da caixa.

    Pine linhas 200-221 +
        bearish_source = close if mitigation == 'Close' else high
        bullish_source = close if mitigation == 'Close' else low
    (Pine linhas 122-123). Política `date > t_creation` estrita
    (briefing §2 P11) — exclui o próprio candle do CREATE. Política
    análoga `date > t_mitigation` estrita para a morte do breaker
    (briefing 6.2 §2 P8) — exclui o próprio candle do nascimento.

    Reescreve o mesmo registro com `t_invalidation` + `state =
    'breaker_broken'` quando a morte é encontrada; senão `state`
    permanece `'mitigated'` e `t_invalidation` permanece NaT
    (breaker vivo até o fim do dataset). Captura `bb_volume` no
    candle da mitigação se a coluna `volume` existir.
    """
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

    has_volume = 'volume' in df.columns
    volume_series = df['volume'] if has_volume else None

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
        if ob_mitigation_level == 'Middle':
            mid = (bar_high + bar_low) / 2
            if bias == BEARISH:
                hits = after_create & (bearish_source > mid)
            else:
                hits = after_create & (bullish_source < mid)
        else:
            if bias == BEARISH:
                hits = after_create & (bearish_source > bar_high)
            else:
                hits = after_create & (bullish_source < bar_low)

        new_record = dict(record)
        if hits.any():
            hit_arr = hits.to_numpy()
            hit_pos = int(hit_arr.argmax())
            hit_label = df.index[hit_pos]
            t_mit = dates.loc[hit_label]
            new_record['t_mitigation'] = t_mit
            new_record['state'] = 'mitigated'

            mit_col = mitigated_col_lookup[(scope, bias)]
            mitigated_cols[mit_col].loc[hit_label] = True

            if has_volume:
                vol_val = volume_series.loc[hit_label]
                new_record['bb_volume'] = (
                    pd.NA if pd.isna(vol_val) else float(vol_val)
                )

            # BREAKER DEATH scan: extremidade oposta, candle estritamente
            # posterior à mitigação (briefing 6.2 §2 P8 / §3).
            # OB BULLISH virou breaker bearish: morre quando fonte_para_cima
            #   (close ou high) > bar_high.
            # OB BEARISH virou breaker bullish: morre quando fonte_para_baixo
            #   (close ou low) < bar_low.
            start = hit_pos + 1
            if start < len(df):
                if bias == BULLISH:
                    death_src = (
                        df['close'] if mitigation == 'Close' else df['high']
                    )
                    death_hits = death_src.iloc[start:] > bar_high
                else:
                    death_src = (
                        df['close'] if mitigation == 'Close' else df['low']
                    )
                    death_hits = death_src.iloc[start:] < bar_low
                if death_hits.any():
                    death_arr = death_hits.to_numpy()
                    death_label = df.index[start + int(death_arr.argmax())]
                    new_record['t_invalidation'] = dates.loc[death_label]
                    new_record['state'] = 'breaker_broken'

        out_records.append(new_record)

    return mitigated_cols, out_records


def _compute_volume_pct(records: list[dict]) -> None:
    """Computa volume_pct in-place, no instante de criação de cada OB.

    Para cada OB X com volume_total definido, volume_pct_X =
    volume_total_X / sum(volume_total_Y for Y ativo em T_X), onde
    "Y ativo em T_X" = t_creation_Y <= T_X AND (t_mitigation_Y is NaT
    OR t_mitigation_Y > T_X). Lookahead-safe por construção.
    """
    for x in records:
        if pd.isna(x.get('volume_total')):
            x['volume_pct'] = pd.NA
            continue
        t_x = x['t_creation']
        denom = 0.0
        for y in records:
            if pd.isna(y.get('volume_total')):
                continue
            if y['t_creation'] > t_x:
                continue
            t_mit_y = y.get('t_mitigation')
            if pd.notna(t_mit_y) and t_mit_y <= t_x:
                continue
            denom += float(y['volume_total'])
        x['volume_pct'] = (
            float(x['volume_total']) / denom if denom > 0 else pd.NA
        )


def _build_ledger(records: list[dict]) -> pd.DataFrame:
    """Constrói DataFrame ledger com schema canônico (15 colunas).

    ob_id, scope, bias, bar_high, bar_low, bar_time,
    t_creation, t_mitigation, t_invalidation, state,
    volume_bullish, volume_bearish, volume_total, volume_pct,
    bb_volume.
    """
    columns = [
        'ob_id', 'scope', 'bias', 'bar_high', 'bar_low', 'bar_time',
        't_creation', 't_mitigation', 't_invalidation', 'state',
        'volume_bullish', 'volume_bearish', 'volume_total', 'volume_pct',
        'bb_volume',
    ]
    if not records:
        return pd.DataFrame({c: pd.Series(dtype='object') for c in columns})

    ledger = pd.DataFrame(records, columns=columns)
    ledger['ob_id'] = ledger['ob_id'].astype('Int64')
    ledger['scope'] = ledger['scope'].astype('string')
    ledger['bias'] = ledger['bias'].astype('Int8')
    ledger['bar_high'] = ledger['bar_high'].astype('float64')
    ledger['bar_low'] = ledger['bar_low'].astype('float64')
    ledger['state'] = ledger['state'].astype('string')
    ledger['volume_bullish'] = ledger['volume_bullish'].astype('Float64')
    ledger['volume_bearish'] = ledger['volume_bearish'].astype('Float64')
    ledger['volume_total'] = ledger['volume_total'].astype('Float64')
    ledger['volume_pct'] = ledger['volume_pct'].astype('Float64')
    ledger['bb_volume'] = ledger['bb_volume'].astype('Float64')
    return ledger


def detect_order_blocks(
    df: pd.DataFrame,
    *,
    ob_filter: Literal['Atr', 'Range'] = 'Atr',
    mitigation: Literal['Close', 'Wick'] = 'Wick',
    ob_mitigation_level: Literal['Absolute', 'Middle'] = 'Absolute',
    atr_length: int = 200,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Detecta Order Blocks com mitigação, breaker death, volumetria e
    mitigation level (Absolute/Middle).

    Produz (a) DataFrame com 8 eventos booleans por candle e (b) ledger
    com 15 colunas por OB de ciclo de vida completo.

    Args:
        df: DataFrame OHLCV com colunas obrigatórias (OHLC + date) +
            COL_*_IDX (Onda 3) + 8 booleans BOS/CHoCH (Onda 5).
            Coluna `volume` é opcional: quando presente, alimenta os
            4 campos volumétricos e `bb_volume`.
        ob_filter: 'Atr' ou 'Range' (Pine linha 87).
        mitigation: 'Close' ou 'Wick' — fonte de mitigação.
        ob_mitigation_level: 'Absolute' (default, byte-idêntico à
            6.2) usa bar_low/bar_high como threshold; 'Middle' usa
            midpoint da caixa `(bar_high + bar_low) / 2`. Afeta
            apenas a mitigação inicial; morte do breaker usa sempre
            bar_high/bar_low.
        atr_length: length de ta.atr() no Pine (default 200).
    """
    if ob_filter not in ('Atr', 'Range'):
        raise ValueError(
            f"ob_filter must be 'Atr' or 'Range', got {ob_filter!r}",
        )
    if mitigation not in ('Close', 'Wick'):
        raise ValueError(
            f"mitigation must be 'Close' or 'Wick', got {mitigation!r}",
        )
    if ob_mitigation_level not in ('Absolute', 'Middle'):
        raise ValueError(
            f"ob_mitigation_level must be 'Absolute' or 'Middle', "
            f"got {ob_mitigation_level!r}",
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
        ob_mitigation_level=ob_mitigation_level,
    )
    _compute_volume_pct(records)

    for col, series in create_cols.items():
        df_per_candle[col] = series.astype(bool)
    for col, series in mitigated_cols.items():
        df_per_candle[col] = series.astype(bool)

    ledger = _build_ledger(records)
    return df_per_candle, ledger
