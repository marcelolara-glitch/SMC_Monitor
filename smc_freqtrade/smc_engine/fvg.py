"""
OBJETIVO
    Portagem vetorizada de drawFairValueGaps() + deleteFairValueGaps() do
    LuxAlgo SMC (Pine linhas 274-297) sobre DataFrame OHLC, sem consumir
    a Onda 5. Detecta criação e mitigação de Fair Value Gaps em duas
    direções (bullish e bearish) num padrão de 3 candles, filtrando por
    volatilidade cumulativa fiel ao Pine (`auto_threshold`).

    Wave 7 emite `state ∈ {'active', 'mitigated'}` e detecta mitigação.
    Wave 7.1 estende com Inverse FVG: um FVG mitigado passa a atuar na
    direção oposta (zona de polaridade invertida) e pode ser invalidado,
    emitindo `state = 'inverse_broken'` + `t_invalidation` e 2 booleans
    per-candle (`fvg_bullish_inverse_broken`, `fvg_bearish_inverse_broken`).
    O campo `is_double` é hook para Onda 7.2 (Double FVG / BPR), sempre
    False nesta onda.

FONTE DE DADOS
    DataFrame com 4 colunas OHLC ('open', 'high', 'low', 'close') e
    coluna 'date' (Int64 epoch ms ou pd.Timestamp). Wave 7 NÃO depende
    das Ondas 3-6 — opera diretamente sobre OHLC.

LIMITAÇÕES CONHECIDAS
    Lookahead-safe por construção: o padrão de 3 candles só fica
        determinado quando o terceiro candle fecha, e a mitigação só
        examina candles estritamente posteriores a `t_creation`.
        Divergência intencional do Pine: NÃO replicamos
        `lookahead=barmerge.lookahead_on` (Mapa §6 conflito B).

    Convenção de armazenamento NORMALIZADA (briefing §4.4 invariante 1):
        `top > bottom` para todo registro do ledger. Para bearish FVG
        isso significa trocar a ordem em relação ao Pine literal
        (Pine linha 296: `fairValueGap(currentHigh, last2Low, BEARISH)`
        armazena top=high[t] < bottom=low[t-2]; aqui top=low[t-2],
        bottom=high[t]). A predicate `high > top` (briefing §6) sob
        a convenção normalizada produz semântica de **full fill** para
        bearish (price atravessa a borda superior do gap), simétrica
        com `low < bottom` para bullish. Pine literal teria sido
        first-touch para bearish; adotamos full-fill simétrico por
        consistência geométrica e por alinhamento com a tolerância do
        spot-check do briefing §6 (FVG visualmente preenchido
        parcialmente permanece `active`).

    Penetração ESTRITA (Pine linha 278): `low < bottom` (bullish) e
        `high > top` (bearish). Tangenciamento exato (`low == bottom`)
        NÃO mitiga.

    Política `date > t_creation` estritamente posterior (briefing §2
        P5 + análogo Wave 6 §2 P11): exclui o próprio candle do
        CREATE. Pine garante a mesma invariante pelo callsite
        (`deleteFairValueGaps` é chamado ANTES de `drawFairValueGaps`,
        Pine linhas 307 e 319), então `t_mitigation > t_creation`
        estrita por construção.

    Inverse FVG (Wave 7.1): predicado de invalidação da zona invertida
        usa penetração wick-estrita simétrica (idioma FVG), não
        close/body. Divergência intencional vs breaker block da Onda
        6.2 (`order_blocks.py`), que usa close ou high/low conforme
        parâmetro `mitigation`. Forma do lifecycle/estado espelha a
        6.2; base do predicado fica no idioma do FVG.

    "IFVG" no projeto = Inverse FVG (zona mitigada que inverte
        polaridade, paralela ao breaker da 6.2). NÃO confundir com
        "Implied Fair Value Gap" do indicador `ICT Concepts [LuxAlgo]`
        (formação de gap implícito por displacement, `low < high[2]`)
        — conceito distinto, avaliado e descartado do roadmap por ser
        ferramenta de breadth, sem ganho para os setups de alta
        convicção do Monitor.

    Volumetric FVG (LuxAlgo pago) NÃO é detectado. Double FVG / BPR
        detectado via `compose_balanced_price_ranges` (Onda 7.2);
        `is_double` populado para FVGs-membros de um BPR.

    MTF (`fairValueGapsTimeframeInput` do Pine, linha 92) NÃO é
        consumido — assinatura é single-TF. Hook reservado para
        Onda 7.3 (parâmetro `df_fvg_tf`).

    Volatility threshold multiplicativo (Wave 7.x): opt-in via
        `volatility_threshold` kwarg em `detect_fair_value_gaps`. Fator
        aplicado sobre o threshold cumulativo: `threshold_eff =
        (volatility_threshold or 1.0) * threshold`. Default `None` →
        fator 1.0 → idêntico ao 7.1.

    Balanced Price Range (Wave 7.2): composto a partir do ledger de
        FVGs via `compose_balanced_price_ranges`. Referência de overlap
        portada do indicador `ICT Concepts [LuxAlgo]` (free, CC
        BY-NC-SA), bloco "Balance Price Range". Sem lifecycle (sem
        state, sem t_invalidation, sem break tracking) — formação
        apenas. Hook futuro aditivo para Wave 9.5.

    Threshold edge case `bar_index=0`: clamp para 1 (evita divisão
        por zero). Pine `bar_index` é 0 na primeira vela mas a
        expressão `cum(...)/bar_index*2` produz `inf`/`NaN` na vela
        0; clamp produz threshold=0 (consistente com a ausência de
        FVG no primeiro candle).

NÃO FAZER
    Não usar shift(-N) nem lookahead em ponto algum.
    Não consumir COL_BOS_* / COL_CHOCH_* da Onda 5 — FVG é primitiva
        sobre OHLC (briefing §2 P1).
    Não popular EngineState.fair_value_gaps — a portagem é vetorizada
        sobre DataFrame; o ledger substitui o slot.
    Não adicionar param `mitigation` em Wave 7 — Onda 6.1 / 7.x cobrirão
        os 4 modos do LuxAlgo pago.
    Não renomear `top`, `bottom`, `bias` no UDT — fiel ao Pine 46-50.
    Não repurposiar `'mitigated'` — pós-7.1, `state == 'mitigated'` é
        exatamente o inverse FVG vivo.
    Não criar boolean per-candle para a inversão — o momento da inversão
        já está capturado pelos booleans `*_mitigated` existentes.
    Não inferir `bar_time = t_creation` por analogia com Wave 6 P12 —
        em FVG são distintos por construção (D5; bar_time = t_creation
        - 2 candles).
    Não inline-ar nomes de coluna — usar as constantes COL_FVG_*
        definidas no topo do módulo.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .types import BEARISH, BULLISH


# ============================================================
# Nomes canônicos das 6 colunas booleans produzidas por
# detect_fair_value_gaps. Consumidores referenciam estas constantes —
# não inline-ar as strings (briefing §4.2).
# ============================================================
COL_FVG_BULLISH_CREATED: str = "fvg_bullish_created"
COL_FVG_BEARISH_CREATED: str = "fvg_bearish_created"
COL_FVG_BULLISH_MITIGATED: str = "fvg_bullish_mitigated"
COL_FVG_BEARISH_MITIGATED: str = "fvg_bearish_mitigated"
COL_FVG_BULLISH_INVERSE_BROKEN: str = "fvg_bullish_inverse_broken"
COL_FVG_BEARISH_INVERSE_BROKEN: str = "fvg_bearish_inverse_broken"


def _compute_threshold(
    open_: pd.Series,
    close: pd.Series,
    *,
    auto_threshold: bool,
) -> np.ndarray:
    """Replica Pine linha 287:
        threshold = ta.cum(|barDeltaPercent|) / bar_index * 2
    quando `auto_threshold=True`, senão `threshold = 0`.

    barDeltaPercent[i] = (close[i-1] - open[i-1]) / (open[i-1] * 100)

    Edge cases:
        i=0: close[-1]/open[-1] inexistente → barDeltaPercent[0] = NaN,
            substituído por 0 antes do cumsum (Pine `ta.cum` em séries
            com NaN inicial faz comportamento análogo). bar_index=0
            clamped para 1, threshold[0] = 0.
        i=1: bar_index=1, threshold = 2 * |barDeltaPercent[1]| —
            simétrico: nenhum delta consegue ser maior que 2 vezes seu
            próprio módulo, então FVG na vela 1 nunca passa o filtro
            (consistente com necessidade de t >= 2 para padrão de 3
            candles).
    """
    n = len(open_)
    if not auto_threshold:
        return np.zeros(n, dtype='float64')

    last_close = close.shift(1).to_numpy()
    last_open = open_.shift(1).to_numpy()
    with np.errstate(divide='ignore', invalid='ignore'):
        delta = (last_close - last_open) / (last_open * 100.0)
    abs_delta = np.where(np.isnan(delta), 0.0, np.abs(delta))
    cum_abs = np.cumsum(abs_delta)
    bar_index = np.arange(n, dtype='float64')
    bar_index_clamped = np.maximum(bar_index, 1.0)
    threshold = cum_abs / bar_index_clamped * 2.0
    return threshold


def _emit_create_events(
    df: pd.DataFrame,
    *,
    threshold: np.ndarray,
    volatility_factor: float = 1.0,
) -> tuple[pd.Series, pd.Series, list[dict]]:
    """CREATE pass vetorizado. Para cada candle t >= 2 verifica
    condições bullish e bearish (Pine linhas 288-289), respeitando
    ordem determinística P10 (bullish antes de bearish no mesmo t).

    Storage normalizado (briefing §4.4 invariante 1):
        bullish: top = low[t],    bottom = high[t-2]
        bearish: top = low[t-2],  bottom = high[t]
    Em ambos: top > bottom, com bias indicando direção.
    """
    n = len(df)
    open_arr = df['open'].to_numpy(dtype='float64')
    high_arr = df['high'].to_numpy(dtype='float64')
    low_arr = df['low'].to_numpy(dtype='float64')
    close_arr = df['close'].to_numpy(dtype='float64')

    last_close = np.concatenate(([np.nan], close_arr[:-1]))
    last_open = np.concatenate(([np.nan], open_arr[:-1]))
    with np.errstate(divide='ignore', invalid='ignore'):
        delta = (last_close - last_open) / (last_open * 100.0)

    last2_high = np.concatenate(([np.nan, np.nan], high_arr[:-2]))
    last2_low = np.concatenate(([np.nan, np.nan], low_arr[:-2]))

    effective_threshold = threshold * volatility_factor

    bullish_mask = (
        (low_arr > last2_high)
        & (last_close > last2_high)
        & (delta > effective_threshold)
    )
    bearish_mask = (
        (high_arr < last2_low)
        & (last_close < last2_low)
        & (-delta > effective_threshold)
    )

    bullish_created = pd.Series(bullish_mask, index=df.index, dtype=bool)
    bearish_created = pd.Series(bearish_mask, index=df.index, dtype=bool)

    dates = df['date']
    records: list[dict] = []
    # Iteração ordenada por candle; dentro do mesmo candle, bullish
    # antes de bearish (P10, Pine linhas 290-296). Acontece naturalmente
    # ao processar bullish_mask[t] antes de bearish_mask[t].
    for t in range(2, n):
        if bullish_mask[t]:
            records.append({
                'bias': BULLISH,
                'top': float(low_arr[t]),
                'bottom': float(last2_high[t]),
                'bar_time': dates.iloc[t - 2],
                't_creation': dates.iloc[t],
                't_mitigation': pd.NaT,
                't_invalidation': pd.NaT,
                'state': 'active',
                'is_inverse': False,
                'is_double': False,
            })
        if bearish_mask[t]:
            records.append({
                'bias': BEARISH,
                'top': float(last2_low[t]),
                'bottom': float(high_arr[t]),
                'bar_time': dates.iloc[t - 2],
                't_creation': dates.iloc[t],
                't_mitigation': pd.NaT,
                't_invalidation': pd.NaT,
                'state': 'active',
                'is_inverse': False,
                'is_double': False,
            })

    return bullish_created, bearish_created, records


def _resolve_mitigations(
    df: pd.DataFrame,
    records: list[dict],
) -> tuple[pd.Series, pd.Series, list[dict]]:
    """MITIGATION pass. Para cada FVG ativo, busca primeira vela
    `date > t_creation` que satisfaz penetração estrita.

    Predicados (Pine linha 278, com storage normalizado):
        bullish: low[Z] < bottom
        bearish: high[Z] > top
    Tangenciamento exato (`low == bottom`) NÃO mitiga — fiel ao Pine.
    """
    dates = df['date']
    low = df['low']
    high = df['high']

    bullish_mit = pd.Series(False, index=df.index, dtype=bool)
    bearish_mit = pd.Series(False, index=df.index, dtype=bool)

    out_records: list[dict] = []
    for record in records:
        bias = record['bias']
        t_creation = record['t_creation']
        top = record['top']
        bottom = record['bottom']

        after_create = dates > t_creation
        if bias == BULLISH:
            hits = after_create & (low < bottom)
        else:
            hits = after_create & (high > top)

        new_record = dict(record)
        if hits.any():
            hit_pos = int(hits.to_numpy().argmax())
            new_record['t_mitigation'] = dates.iloc[hit_pos]
            new_record['state'] = 'mitigated'
            if bias == BULLISH:
                bullish_mit.iloc[hit_pos] = True
            else:
                bearish_mit.iloc[hit_pos] = True

        out_records.append(new_record)

    return bullish_mit, bearish_mit, out_records


def _resolve_inverse_invalidations(
    df: pd.DataFrame,
    records: list[dict],
) -> tuple[pd.Series, pd.Series, list[dict]]:
    """INVERSE INVALIDATION pass (Wave 7.1). Para cada FVG mitigado
    (= inverse FVG vivo), busca primeira vela `date > t_mitigation`
    que penetra a borda OPOSTA à da mitigação, wick estrito.

    Predicados (simétricos à mitigação, bias oposto):
        bullish original (mitigado por low < bottom): invalida quando
            high[W] > top
        bearish original (mitigado por high > top): invalida quando
            low[W] < bottom

    D1: todo mitigado recebe is_inverse = True.
    D4: invalidação por penetração da borda oposta, wick estrito.
    D5: busca estritamente posterior a t_mitigation.
    D6: is_inverse True para mitigated e inverse_broken.
    """
    dates = df['date']
    low = df['low']
    high = df['high']

    bullish_inv_broken = pd.Series(False, index=df.index, dtype=bool)
    bearish_inv_broken = pd.Series(False, index=df.index, dtype=bool)

    out_records: list[dict] = []
    for record in records:
        new_record = dict(record)

        if new_record['state'] != 'mitigated':
            out_records.append(new_record)
            continue

        new_record['is_inverse'] = True
        bias = new_record['bias']
        t_mitigation = new_record['t_mitigation']
        top = new_record['top']
        bottom = new_record['bottom']

        after_mit = dates > t_mitigation
        if bias == BULLISH:
            hits = after_mit & (high > top)
        else:
            hits = after_mit & (low < bottom)

        if hits.any():
            hit_pos = int(hits.to_numpy().argmax())
            new_record['t_invalidation'] = dates.iloc[hit_pos]
            new_record['state'] = 'inverse_broken'
            if bias == BULLISH:
                bullish_inv_broken.iloc[hit_pos] = True
            else:
                bearish_inv_broken.iloc[hit_pos] = True

        out_records.append(new_record)

    return bullish_inv_broken, bearish_inv_broken, out_records


def _build_ledger(records: list[dict]) -> pd.DataFrame:
    """Constrói DataFrame ledger com schema canônico (briefing §12.4):
    11 colunas em ordem fixa, fvg_id 1-indexed por ordem de criação.
    """
    columns = [
        'fvg_id', 'bias', 'top', 'bottom', 'bar_time', 't_creation',
        't_mitigation', 't_invalidation', 'state',
        'is_inverse', 'is_double',
    ]
    if not records:
        return pd.DataFrame({c: pd.Series(dtype='object') for c in columns})

    records_with_id = [{'fvg_id': i + 1, **r} for i, r in enumerate(records)]
    ledger = pd.DataFrame(records_with_id, columns=columns)
    ledger['fvg_id'] = ledger['fvg_id'].astype('int64')
    ledger['bias'] = ledger['bias'].astype('int64')
    ledger['top'] = ledger['top'].astype('float64')
    ledger['bottom'] = ledger['bottom'].astype('float64')
    ledger['state'] = ledger['state'].astype('object')
    ledger['is_inverse'] = ledger['is_inverse'].astype('bool')
    ledger['is_double'] = ledger['is_double'].astype('bool')
    return ledger


def detect_fair_value_gaps(
    df: pd.DataFrame,
    *,
    auto_threshold: bool = True,
    volatility_threshold: float | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Detecta Fair Value Gaps bullish e bearish via padrão de 3 candles, com
    mitigação fiel ao Pine compute-only e invalidação de zona invertida
    (Inverse FVG, Wave 7.1).

    OBJETIVO
        Portagem fiel de `drawFairValueGaps` (Pine linhas 283-297) e
        `deleteFairValueGaps` (linhas 274-281) do indicador LuxAlgo SMC
        compute-only em `tools/pynecore-validation/luxalgo_smc_compute_only.py`.
        Emite ledger DataFrame com lifecycle de 4 timestamps (`bar_time`,
        `t_creation`, `t_mitigation`, `t_invalidation`) e `state ∈ {'active',
        'mitigated', 'inverse_broken'}`, mais 6 colunas booleans per-candle
        agregadas (BULLISH/BEARISH × CREATED/MITIGATED/INVERSE_BROKEN).

    FONTE DE DADOS
        df: DataFrame OHLC com coluna `date` (datetime64[ns, UTC] ou int64 ns)
            e colunas obrigatórias `open`, `high`, `low`, `close`. Demais
            colunas são preservadas em `df_per_candle`. Index é preservado.
        Pine fonte:
            UDT `fairValueGap` — linhas 46-50 (`top`, `bottom`, `bias`).
            Inputs — linhas 91-92 (`fairValueGapsThresholdInput` bool,
                `fairValueGapsTimeframeInput` timeframe).
            Lógica — linhas 274-297.
            Callsite — linhas 306-319 (`deleteFairValueGaps` antes de
                `drawFairValueGaps`).
        Convenções temporais:
            `bar_time` = timestamp do **primeiro** candle do padrão de 3
                (âncora estrutural; define o nível do gap).
            `t_creation` = timestamp do **terceiro** candle (momento em
                que o gap fica conhecido; alinhado com Mapa §7.6.1).
            Em FVG, `bar_time ≠ t_creation` por construção (diferente de
                Wave 6 P12 onde coincidem).

    LIMITAÇÕES CONHECIDAS
        1 modo de mitigação Pine-fiel: bullish quando `low < bottom`,
            bearish quando `high > top` (penetração estrita, linha 278).
            Os 4 modos do LuxAlgo pago (Close/Wick/Average/None) são hook
            Onda 6.1 / 7.x.
        `auto_threshold=True` replica `fairValueGapsThresholdInput`
            cumulativo `cum(|barDeltaPercent|)/bar_index*2` (Pine
            linha 287). Edge case `bar_index=0` clamped para evitar
            divisão por zero.
        Inverse FVG (Wave 7.1): predicado de invalidação wick-estrito,
            penetração da borda oposta à da mitigação. `is_inverse`
            populado para todo FVG mitigado.
        Double FVG / Balanced Price Range → `compose_balanced_price_ranges`
            (Onda 7.2). `is_double` populado para FVGs-membros de BPR.
        MTF (`fairValueGapsTimeframeInput`) → hook Onda 7.3 (parâmetro
            `df_fvg_tf` reservado, Mapa §6 v1.1 prescrição inicial).
        Volatility threshold (Onda 7.x): `volatility_threshold` multiplica
            o threshold cumulativo. `None` (default) → fator 1.0; `> 1.0`
            → mais estrito. Com `auto_threshold=False` (threshold=0) o
            filtro é no-op (0 × fator = 0).
        Divergência intencional do Pine: NÃO replicamos
            `lookahead=barmerge.lookahead_on` (Mapa §6 conflito B).
            Confiar em merge_informative_pair prévio do Freqtrade quando
            MTF for habilitado (Wave 7.3).

    NÃO FAZER
        Não popular `EngineState.fair_value_gaps`. A portagem é vetorizada
            sobre DataFrame; o ledger substitui o slot.
        Não adicionar param `mitigation` em Wave 7 — Onda 6.1 / 7.x cobrirão.
        Não renomear campos do UDT (`top`, `bottom`, `bias`) — fiel ao Pine
            linhas 46-50 e à Wave 1.
        Não repurposiar `'mitigated'` — pós-7.1, `state == 'mitigated'` é
            exatamente o inverse FVG vivo.
        Não criar boolean per-candle para a inversão.
        Não inferir `bar_time = t_creation` por analogia com Wave 6 P12 —
            em FVG são distintos por construção (D5).
        Não usar lookahead — toda detecção é causal sobre o DataFrame
            passado.
    """
    df_per_candle = df.copy()

    threshold = _compute_threshold(
        df['open'], df['close'], auto_threshold=auto_threshold,
    )

    vol_factor = volatility_threshold if volatility_threshold is not None else 1.0

    bullish_created, bearish_created, records = _emit_create_events(
        df, threshold=threshold, volatility_factor=vol_factor,
    )
    bullish_mit, bearish_mit, records = _resolve_mitigations(df, records)
    bullish_inv, bearish_inv, records = _resolve_inverse_invalidations(
        df, records,
    )

    df_per_candle[COL_FVG_BULLISH_CREATED] = bullish_created.astype(bool)
    df_per_candle[COL_FVG_BEARISH_CREATED] = bearish_created.astype(bool)
    df_per_candle[COL_FVG_BULLISH_MITIGATED] = bullish_mit.astype(bool)
    df_per_candle[COL_FVG_BEARISH_MITIGATED] = bearish_mit.astype(bool)
    df_per_candle[COL_FVG_BULLISH_INVERSE_BROKEN] = bullish_inv.astype(bool)
    df_per_candle[COL_FVG_BEARISH_INVERSE_BROKEN] = bearish_inv.astype(bool)

    ledger = _build_ledger(records)
    return df_per_candle, ledger


def compose_balanced_price_ranges(
    ledger_fvg: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Compõe Balanced Price Ranges (BPR) a partir do ledger de FVGs.

    OBJETIVO
        BPR é a zona de sobreposição entre um FVG bullish e um FVG
        bearish (equilíbrio). Algoritmo de overlap portado do indicador
        `ICT Concepts [LuxAlgo]` (free, CC BY-NC-SA), bloco "Balance
        Price Range (overlap of 2 latest FVG bull/bear)".

    FONTE DE DADOS
        ledger_fvg produzido por `detect_fair_value_gaps`. Formação é
        puramente derivada do ledger (zona, membros, timestamps) — não
        recebe OHLC.

    LIMITAÇÕES CONHECIDAS
        Sem lifecycle: sem `state`, sem `t_invalidation`, sem break
        tracking. BPR é só formação neste PR. Consumidor (setup
        machine, Wave 9.5) ainda não existe; lifecycle é hook futuro
        aditivo (§1.2).

        BPR portado do `ICT Concepts`, não do SMC. O ICT constrói BPR
        sobre FVGs displacement-based (`body > meanBody`); nós compomos
        sobre FVGs SMC-portados (`auto_threshold` cumulativo). Portamos
        o algoritmo de overlap, não os inputs — os BPRs-membros
        divergem dos do ICT.

        Pareamento event-driven ("FVG oposto ativo mais recente na
        criação") vs "último par a cada barra" do ICT —
        funcionalmente alinhados.

    NÃO FAZER
        Não adicionar lifecycle/state ao BPR neste PR.
        Não emitir booleans per-candle de BPR.

    Args:
        ledger_fvg: ledger de FVGs (11 colunas, de detect_fair_value_gaps).

    Returns:
        (ledger_bpr, ledger_fvg_marcado):
            ledger_bpr: DataFrame com 7 colunas
                [bpr_id, bias, top, bottom, t_creation,
                 fvg_id_bull, fvg_id_bear].
                bias: BULLISH (BPR_UP) ou BEARISH (BPR_DN).
            ledger_fvg_marcado: cópia do ledger_fvg com is_double=True
                para FVGs que são membros de algum BPR.
    """
    bpr_columns = [
        'bpr_id', 'bias', 'top', 'bottom', 't_creation',
        'fvg_id_bull', 'fvg_id_bear',
    ]
    ledger_out = ledger_fvg.copy()

    if len(ledger_fvg) == 0:
        empty_bpr = pd.DataFrame({
            'bpr_id': pd.Series(dtype='int64'),
            'bias': pd.Series(dtype='int64'),
            'top': pd.Series(dtype='float64'),
            'bottom': pd.Series(dtype='float64'),
            't_creation': pd.Series(dtype=ledger_fvg['t_creation'].dtype
                                    if 't_creation' in ledger_fvg.columns
                                    else 'object'),
            'fvg_id_bull': pd.Series(dtype='int64'),
            'fvg_id_bear': pd.Series(dtype='int64'),
        })
        return empty_bpr, ledger_out

    sorted_fvg = ledger_fvg.sort_values('t_creation').reset_index(drop=True)

    bpr_records: list[dict] = []
    member_ids: set[int] = set()

    for i in range(len(sorted_fvg)):
        f = sorted_fvg.iloc[i]
        f_bias = f['bias']
        f_t = f['t_creation']

        candidate = None
        for j in range(i - 1, -1, -1):
            g = sorted_fvg.iloc[j]
            if g['bias'] == f_bias:
                continue
            if g['t_creation'] >= f_t:
                continue
            g_mit = g['t_mitigation']
            if not pd.isna(g_mit) and g_mit <= f_t:
                continue
            candidate = g
            break

        if candidate is None:
            continue

        if f_bias == BULLISH:
            bull, bear = f, candidate
        else:
            bull, bear = candidate, f

        bull_top = bull['top']
        bull_bottom = bull['bottom']
        bear_top = bear['top']
        bear_bottom = bear['bottom']

        if bull_bottom < bear_top and bear_bottom < bull_bottom:
            bpr_records.append({
                'bias': BULLISH,
                'top': float(bear_top),
                'bottom': float(bull_bottom),
                't_creation': f_t,
                'fvg_id_bull': int(bull['fvg_id']),
                'fvg_id_bear': int(bear['fvg_id']),
            })
            member_ids.add(int(bull['fvg_id']))
            member_ids.add(int(bear['fvg_id']))
        elif bear_bottom < bull_top and bull_bottom < bear_bottom:
            bpr_records.append({
                'bias': BEARISH,
                'top': float(bull_top),
                'bottom': float(bear_bottom),
                't_creation': f_t,
                'fvg_id_bull': int(bull['fvg_id']),
                'fvg_id_bear': int(bear['fvg_id']),
            })
            member_ids.add(int(bull['fvg_id']))
            member_ids.add(int(bear['fvg_id']))

    if not bpr_records:
        empty_bpr = pd.DataFrame({c: pd.Series(dtype='int64' if c != 'top' and c != 'bottom' and c != 't_creation'
                                                else ('float64' if c in ('top', 'bottom')
                                                      else ledger_fvg['t_creation'].dtype))
                                  for c in bpr_columns})
        return empty_bpr, ledger_out

    for idx, rec in enumerate(bpr_records):
        rec['bpr_id'] = idx + 1

    ledger_bpr = pd.DataFrame(bpr_records, columns=bpr_columns)
    ledger_bpr['bpr_id'] = ledger_bpr['bpr_id'].astype('int64')
    ledger_bpr['bias'] = ledger_bpr['bias'].astype('int64')
    ledger_bpr['top'] = ledger_bpr['top'].astype('float64')
    ledger_bpr['bottom'] = ledger_bpr['bottom'].astype('float64')
    ledger_bpr['fvg_id_bull'] = ledger_bpr['fvg_id_bull'].astype('int64')
    ledger_bpr['fvg_id_bear'] = ledger_bpr['fvg_id_bear'].astype('int64')

    ledger_out.loc[ledger_out['fvg_id'].isin(member_ids), 'is_double'] = True

    return ledger_bpr, ledger_out
