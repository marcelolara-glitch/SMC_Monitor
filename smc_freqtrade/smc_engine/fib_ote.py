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
      existente. **Proveniência (v2.1, D1 da Onda 2): esta perna É o
      dealing range do PRINCIPIOS §2.7 no tier swing** — o trailing
      reseta apenas em pivô swing (trailing.py, Pine 156-161/174-179),
      logo (trailing_bottom, trailing_top) no candle do MSS equivale por
      construção à perna pivô-oposto→extremo (identidade 19/19 no golden
      1h). A antiga cláusula de parada DTFX está revogada: não há mais
      proxy; há definição canônica.
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

# === Ciclo de vida v2 (Bloco 2 / Onda 2, PRINCIPIOS §2.7) ===
# 12 colunas aditivas, {pre}_ote_v2_{campo} para pre ∈ {bull, bear}.
OTE_V2_FIELDS = ('top', 'bottom', 'id', 'eq_level', 'origin', 'eq_crossed')
OTE_V2_COLUMNS = tuple(
    f'{pre}_ote_v2_{field}'
    for pre in ('bull', 'bear')
    for field in OTE_V2_FIELDS
)

# EQ = 0.5 da perna (equilibrium do dealing range, §2.7).
OTE_EQ_RETRACE = 0.5

# Razões de kill do ciclo de vida v2 (contadas por lado; diag §6).
OTE_V2_KILL_REPLACED = 'replaced'          # novo MSS da mesma direção
OTE_V2_KILL_OPPOSITE_MSS = 'opposite_mss'  # MSS da direção oposta
OTE_V2_KILL_ORIGIN_BREAK = 'origin_break'  # close além da origem 0.0
OTE_V2_KILL_REASONS = (
    OTE_V2_KILL_REPLACED,
    OTE_V2_KILL_OPPOSITE_MSS,
    OTE_V2_KILL_ORIGIN_BREAK,
)


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


def project_ote_zones_v2(
    df: pd.DataFrame,
    *,
    with_stats: bool = False,
):
    """Anexa as 12 colunas do ciclo de vida v2 do dealing range ao `df`.

    OBJETIVO
        Implementar o ciclo de vida da zona OTE do PRINCIPIOS §2.7
        (Bloco 2 / Onda 2, decisões D1-D5): passo único O(n), causal,
        estado por lado com **no máximo UMA zona ativa** — substituição
        em novo MSS da mesma direção (`replaced`), morte em MSS oposto
        (`opposite_mss`), morte por close além da origem 0.0
        (`origin_break`, herdada do legado) e EQ tracking sticky por
        zona. Função paralela ao `project_ote_zones` legado (interface
        preservation — o legado fica intocado); o consumo pela A10 é
        config-gated em `SetupConfig.ote_lifecycle` (default 'legacy').

        Correção ao relatório da Fase A Parte 2: a invalidação por close
        além da origem **já existe** no builder legado
        (`_build_ote_ledger`, :147-156, com projeção causal — zona
        inativa a partir do próprio candle da invalidação). A
        persistência papel-de-parede do legado (61-95%) vem do que
        falta lá: substituição em novo MSS da mesma direção, morte em
        MSS oposto e a multiplicidade de zonas coexistindo (o tie-break
        por proximidade mascara um acervo de pernas antigas vivas). A
        v2 implementa exatamente isso e **herda** a regra existente.

        Ordem no mesmo candle `t` (kills antes de criação):
            1. zona ativa + MSS oposto em `t` → `opposite_mss`;
            2. zona ativa + close além da origem → `origin_break`
               (bull `close < origin`, bear `close > origin`; zona
               inativa a partir do próprio candle, convenção do legado);
            3. MSS da mesma direção em `t`: zona ativa → `replaced`;
               zona nova nasce em `t` e emite a partir de `t` (sujeita
               ao `origin_break` no próprio candle, como no legado j=t).

    FONTE DE DADOS
        Eventos e perna idênticos ao legado: MSS swing = BOS∪CHoCH swing
        (`structure.py`), perna `(trailing_bottom[t], trailing_top[t])`
        (`trailing.py`), guardas idênticas (finitos, `high > low`),
        bandas direction-aware idênticas (0.62-0.79). Proveniência da
        perna (D1): ver docstring do módulo — a perna É o dealing range
        do §2.7 no tier swing (identidade 19/19 no golden 1h; taxas da
        sondagem de 2026-07-05: EQ-cross ~53%, toque na banda ~42%,
        n=19). Além do legado, consome `high`/`low` (EQ por toque de
        pavio). `eq_level` = 0.5 da perna (bull `high − 0.5·span`, bear
        `low + 0.5·span`); `origin` = 0.0 da perna (bull `low`, bear
        `high`); `eq_crossed` sticky: bull vira True no primeiro candle
        com `low <= eq_level`, bear com `high >= eq_level`; reseta em
        zona nova.

    LIMITAÇÕES CONHECIDAS
        - `mss_scope` segue swing (D2); internal/both reservados
          (calibração futura).
        - EQ por toque de pavio; a variante por close é espaço de
          calibração registrado, NÃO implementado (D-decisão da onda).
        - Contador de criações/kills por lado é retorno auxiliar
          (`with_stats=True`) para o diag §6 — **não** vira ledger em
          `AnalyzeResult` (D-D6 preservada).

    NÃO FAZER
        - Não usar `shift(-N)` (lookahead proibido).
        - Não mutar o `df` do caller — opera sobre cópia.
        - Não tocar `project_ote_zones`/`_build_ote_ledger` legados.
        - Não expor stats/ledger em `AnalyzeResult` (D-D6).

    Args:
        df: DataFrame com colunas `date`, `high`, `low`, `close`,
            `trailing_top`, `trailing_bottom` e as 4 colunas
            `*_swing_*` de structure.
        with_stats: se True, retorna `(out, stats)` com
            `stats[pre] = {'created': int, 'kills': {razão: int}}`.

    Returns:
        Cópia de `df` + 12 colunas (`OTE_V2_COLUMNS`). `*_top`,
        `*_bottom`, `*_eq_level`, `*_origin` float64 (NaN sem zona);
        `*_id` Int64 nullable (<NA> sem zona; valor = índice de barra
        da criação); `*_eq_crossed` bool (False sem zona).
    """
    out = df.copy()
    closes = df['close'].to_numpy(dtype='float64')
    highs = df['high'].to_numpy(dtype='float64')
    lows = df['low'].to_numpy(dtype='float64')
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

    arrs = {
        pre: {
            'top': np.full(n, np.nan, dtype='float64'),
            'bottom': np.full(n, np.nan, dtype='float64'),
            'id': np.full(n, np.nan, dtype='float64'),
            'eq_level': np.full(n, np.nan, dtype='float64'),
            'origin': np.full(n, np.nan, dtype='float64'),
            'eq_crossed': np.zeros(n, dtype='bool'),
        }
        for pre in ('bull', 'bear')
    }
    stats = {
        pre: {'created': 0, 'kills': dict.fromkeys(OTE_V2_KILL_REASONS, 0)}
        for pre in ('bull', 'bear')
    }
    # Estado por lado: None = sem zona; dict = zona ativa.
    zone: dict[str, dict | None] = {'bull': None, 'bear': None}

    def _kill(pre: str, reason: str) -> None:
        stats[pre]['kills'][reason] += 1
        zone[pre] = None

    for t in range(n):
        leg_low = tbot[t]
        leg_high = ttop[t]
        leg_ok = (
            np.isfinite(leg_low) and np.isfinite(leg_high)
            and leg_high > leg_low
        )
        bull_evt = bool(bull_mss[t]) and leg_ok
        bear_evt = bool(bear_mss[t]) and leg_ok

        # 1. MSS oposto mata a zona ativa do outro lado.
        if zone['bull'] is not None and bear_evt:
            _kill('bull', OTE_V2_KILL_OPPOSITE_MSS)
        if zone['bear'] is not None and bull_evt:
            _kill('bear', OTE_V2_KILL_OPPOSITE_MSS)

        # 2. close além da origem (regra herdada de _build_ote_ledger
        #    :147-156; inativa a partir do próprio candle).
        if zone['bull'] is not None and closes[t] < zone['bull']['origin']:
            _kill('bull', OTE_V2_KILL_ORIGIN_BREAK)
        if zone['bear'] is not None and closes[t] > zone['bear']['origin']:
            _kill('bear', OTE_V2_KILL_ORIGIN_BREAK)

        # 3. MSS da mesma direção: substitui (kill antes de criar) e a
        #    zona nova emite a partir de t — sujeita ao origin_break no
        #    próprio candle de criação (legado varre j desde t).
        if bull_evt:
            if zone['bull'] is not None:
                _kill('bull', OTE_V2_KILL_REPLACED)
            span = leg_high - leg_low
            zone['bull'] = {
                'top': leg_high - OTE_RETRACE_LOW * span,
                'bottom': leg_high - OTE_RETRACE_HIGH * span,
                'eq_level': leg_high - OTE_EQ_RETRACE * span,
                'origin': leg_low,
                'id': float(t),
                'eq_crossed': False,
            }
            stats['bull']['created'] += 1
            if closes[t] < leg_low:
                _kill('bull', OTE_V2_KILL_ORIGIN_BREAK)
        if bear_evt:
            if zone['bear'] is not None:
                _kill('bear', OTE_V2_KILL_REPLACED)
            span = leg_high - leg_low
            zone['bear'] = {
                'top': leg_low + OTE_RETRACE_HIGH * span,
                'bottom': leg_low + OTE_RETRACE_LOW * span,
                'eq_level': leg_low + OTE_EQ_RETRACE * span,
                'origin': leg_high,
                'id': float(t),
                'eq_crossed': False,
            }
            stats['bear']['created'] += 1
            if closes[t] > leg_high:
                _kill('bear', OTE_V2_KILL_ORIGIN_BREAK)

        # 4. EQ sticky (toque de pavio) + emissão do candle t.
        zb = zone['bull']
        if zb is not None:
            if lows[t] <= zb['eq_level']:
                zb['eq_crossed'] = True
            a = arrs['bull']
            a['top'][t] = zb['top']
            a['bottom'][t] = zb['bottom']
            a['id'][t] = zb['id']
            a['eq_level'][t] = zb['eq_level']
            a['origin'][t] = zb['origin']
            a['eq_crossed'][t] = zb['eq_crossed']
        zr = zone['bear']
        if zr is not None:
            if highs[t] >= zr['eq_level']:
                zr['eq_crossed'] = True
            a = arrs['bear']
            a['top'][t] = zr['top']
            a['bottom'][t] = zr['bottom']
            a['id'][t] = zr['id']
            a['eq_level'][t] = zr['eq_level']
            a['origin'][t] = zr['origin']
            a['eq_crossed'][t] = zr['eq_crossed']

    for pre in ('bull', 'bear'):
        a = arrs[pre]
        out[f'{pre}_ote_v2_top'] = a['top']
        out[f'{pre}_ote_v2_bottom'] = a['bottom']
        out[f'{pre}_ote_v2_id'] = pd.array(a['id'], dtype='Int64')
        out[f'{pre}_ote_v2_eq_level'] = a['eq_level']
        out[f'{pre}_ote_v2_origin'] = a['origin']
        out[f'{pre}_ote_v2_eq_crossed'] = a['eq_crossed']

    if with_stats:
        return out, stats
    return out
