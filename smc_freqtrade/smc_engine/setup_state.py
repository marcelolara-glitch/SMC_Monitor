"""Máquina de estados de setup SMC multi-modo + matcher declarativo (9.5b).

OBJETIVO
    Estende a FSM de setup da 9.5a com três entregas aditivas (Wave 9.5b):

    1. **Motor multi-modo:** `SetupConfig.entry_mode ∈
       {confirmation, risk, hybrid}`. `confirmation` é o comportamento
       da 9.5a (inalterado, caso de regressão). `risk` confirma direto na
       interseção da zona (sem PENDING). `hybrid` é stub (NotImplementedError).
    2. **Matcher declarativo:** a A3 hard-coded da 9.5a foi extraída para
       uma representação declarativa (`Signature`), sobre a qual a FSM
       itera. A A3 vira a 1ª instância declarativa — semântica preservada,
       saída byte-idêntica em `confirmation`.
    3. **4 arquétipos:** A3 (continuação, OB+FVG+sweep), A2 (continuação,
       OB+sweep), A4a (reversão, IFVG), A5 (tap, OB+volume, modo risk).

    Stateless (df in, df out). Modela **um** setup ativo por vez (FSM
    sequencial, um vencedor por candle), re-armável após terminal.

FONTE DE DADOS
    Colunas consumidas (sufixo conforme TF após merge `@informative`):
    - 4H: `swing_trend_bias_{ts}` (∈ {1, −1}; +1 ⇒ LONG, −1 ⇒ SHORT) —
      exigida só pelas assinaturas trend-gated (A3/A2/A5).
    - Zona (promovida por zone_projection.py):
      `active_{bull,bear}_swing_ob_{top,bottom,id,volume_pct}_{zs}`,
      `active_{bull,bear}_fvg_{top,bottom,id}_{zs}`,
      `active_{bull,bear}_ifvg_{top,bottom,id}_{zs}`,
      `active_{bull,bear}_breaker_{top,bottom,id}_{zs}`,
      `active_{bull,bear}_ote_{top,bottom,id}_{zs}` (9.5e — Fib 62–79%,
      tratada como zona; bull = banda discount/long, bear = premium/short).
    - Base (15m, sem sufixo): `sweep_{bullish,bearish}_{wick,retest}`,
      `choch_internal_{bullish,bearish}`, `open/high/low/close`,
      `in_kz_silver_bullet_{am,late,pm}` (9.5e — killzones da A7, exigidas
      só por assinaturas com `required_base`).

PREDICADO DE VELA DE REJEIÇÃO (inline — sem módulo)
    Idêntico à 9.5a: com `rng = high - low` (guarda `rng > 0`):
    - Rejeição bullish: `(min(open,close) - low)/rng >= rejection_wick_frac`
      E `close >= low + rejection_close_frac * rng`.
    - Rejeição bearish: simétrico.

LIMITAÇÕES CONHECIDAS
    - **RESOLVED fica FORA da coluna** (stateless, sem lookahead). A coluna
      realiza 4 valores: ARMED, PENDING_CONFIRMATION, CONFIRMED, INVALIDATED.
    - `entry_mode='hybrid'` é stub que levanta `NotImplementedError` (D1):
      o fallback do hybrid depende de SL atingido (= RESOLVED), incomputável
      numa FSM stateless sem lookahead. Reaberto na Wave 9.5f/10 quando
      houver realimentação de outcome. Falhar alto; nunca rotear
      silenciosamente para comportamento diferente.
    - `entry_mode='risk'` (D2): ARMED → CONFIRMED direto na interseção da
      zona, sem PENDING. `zone_crossed` é estruturalmente impossível (tocar
      a zona *é* a entrada). Reusa o conjunto de invalidação do ARMED
      (escaped, timeout, trend_changed, mitigated); nenhuma razão nova.
    - A engine não expõe trend "neutro"; assinaturas trend-gated têm
      direção sempre +1/−1. A4a (reversão) é contra-tendência: **sem** gate
      de trend (logo, sem invalidação `trend_changed`).
    - N setups simultâneos → 9.5f/Wave 10 (MVP = um vencedor por candle).
      Mitigação parcial no Bloco 1: `compute_setup_state_multi` roda a FSM
      independentemente por assinatura (G9), mas a FSM interna segue
      um-setup-por-vez dentro de cada assinatura.

BLOCO 1 (Briefing 2, 2026-07-04) — mecanismos config-gated
    Correções estruturais da FSM ratificadas sobre os achados da Fase A
    Parte 2 (`docs/RELATORIO_FASE_A_PARTE2_FIDELIDADE.md` §1/§4 e
    `docs/ADENDO_FASE_A_PARTE2_MEDICAO_2Y.md`). Todos os mecanismos são
    desligados por default — com `SetupConfig()` puro o output é
    byte-idêntico ao pré-Bloco 1 (gate de regressão T1):

    - **G1** `arming_proximity_pct` (default None = desligado): gate de
      proximidade na armação. Evidência: armação sem limite de distância
      + escape absoluto 2% ⇒ 97–99% das invalidações são `escaped`, vida
      mediana de setup = 1 candle (relatório §1).
    - **G2** `confirmation_trigger` (default 'legacy'): re-desenho do
      gatilho de confirmação. `legacy` = ChoCH ∧ rejeição no mesmo candle
      (co-ocorrência medida: 10,4/10k BTC, 5,7/10k ETH; 7–8 CONFIRMED em
      2 anos somando as 9 assinaturas — adendo §1). `choch` = MSS puro
      (canônico §2.11 [v2.0]); `choch_or_rej` = MSS ∨ rejeição. A2/A3/A7
      (premissa de sweep) mantêm o ∧ sweep_recent.
    - **G3** `anchor_invalidation` (default 'promoted_id'): em
      `frozen_band` a vigília de âncora do ARMED é removida —
      `REASON_MITIGATED` deixa de ser emitida. Evidência: a vigília de id
      mede troca da zona promovida por proximidade, não mitigação (15/15
      espúrios no golden; lower-bound 65–100% em 2 anos). LIMITAÇÃO
      declarada: decadência de premissa (ex.: FVG de confluência da A3/A6
      sumir durante ARMED) fica sem monitor neste modo.
    - **G5** `a9_variant` (default 'legacy_ob'): em `sweep_band` a zona
      da A9 vira a banda do próprio sweep (bull `[low_evt, level]`, bear
      `[level, high_evt]`), eliminando o gate de OB sem proveniência
      conceitual (relatório G5).
    - **G9** `compute_setup_state_multi`: FSM independente por assinatura,
      colunas sufixadas `__{sid}` (starvation medida do slot único:
      A10 24.564→1 em 2 anos — adendo G9). Função nova; a antiga fica
      intocada.

NÃO FAZER
    - Não usar `shift(-N)` (lookahead proibido).
    - Não importar `freqtrade` (engine é Python puro).
    - Não inchar `SMCConfig` — `SetupConfig` é dedicado.
    - Não mutar o df do caller (opera sobre cópia, só anexa colunas).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from typing import Callable

import numpy as np
import pandas as pd

from .sessions import SESSION_COLUMNS

# === Valores de estado realizados na coluna ===
STATE_ARMED = 'ARMED'
STATE_PENDING = 'PENDING_CONFIRMATION'
STATE_CONFIRMED = 'CONFIRMED'
STATE_INVALIDATED = 'INVALIDATED'
SETUP_STATES = (STATE_ARMED, STATE_PENDING, STATE_CONFIRMED, STATE_INVALIDATED)

# === Direções (minúscula) ===
DIRECTION_LONG = 'long'
DIRECTION_SHORT = 'short'

# === Modos de entrada (Wave 9.5b, D1) ===
ENTRY_MODE_CONFIRMATION = 'confirmation'
ENTRY_MODE_RISK = 'risk'
ENTRY_MODE_HYBRID = 'hybrid'
ENTRY_MODES = (ENTRY_MODE_CONFIRMATION, ENTRY_MODE_RISK, ENTRY_MODE_HYBRID)

# === Razões de invalidação (enum string) ===
REASON_ESCAPED = 'escaped'
REASON_TIMEOUT = 'timeout'
REASON_TREND_CHANGED = 'trend_changed'
REASON_ZONE_CROSSED = 'zone_crossed'
REASON_MITIGATED = 'mitigated'
INVALIDATION_REASONS = (
    REASON_ESCAPED, REASON_TIMEOUT, REASON_TREND_CHANGED,
    REASON_ZONE_CROSSED, REASON_MITIGATED,
)

# === Gatilhos de confirmação (Bloco 1, G2) ===
CONFIRMATION_TRIGGER_LEGACY = 'legacy'
CONFIRMATION_TRIGGER_CHOCH = 'choch'
CONFIRMATION_TRIGGER_CHOCH_OR_REJ = 'choch_or_rej'
CONFIRMATION_TRIGGERS = (
    CONFIRMATION_TRIGGER_LEGACY,
    CONFIRMATION_TRIGGER_CHOCH,
    CONFIRMATION_TRIGGER_CHOCH_OR_REJ,
)

# === Modos de invalidação por âncora (Bloco 1, G3) ===
ANCHOR_INVALIDATION_PROMOTED_ID = 'promoted_id'
ANCHOR_INVALIDATION_FROZEN_BAND = 'frozen_band'
ANCHOR_INVALIDATIONS = (
    ANCHOR_INVALIDATION_PROMOTED_ID,
    ANCHOR_INVALIDATION_FROZEN_BAND,
)

# === Variantes de zona da A9 (Bloco 1, G5) ===
A9_VARIANT_LEGACY_OB = 'legacy_ob'
A9_VARIANT_SWEEP_BAND = 'sweep_band'
A9_VARIANTS = (A9_VARIANT_LEGACY_OB, A9_VARIANT_SWEEP_BAND)

# === Ids de assinatura válidos (D3, ordem de prioridade) ===
# A3 > A2 > A4a > A5 > A1 > A9 > A6 > A7 > A10 (qualidade de evidência).
# Decide só o empate "duas armam no mesmo candle"; é revisável (o backtest
# da Wave 10 isola por assinatura — §3.5/§6). A 9.5e APENDA A7 (prioridade
# 7) e A10 (8) — prioridades 0–6 das existentes ficam intactas (D4).
_VALID_SIGNATURE_IDS = ('A3', 'A2', 'A4a', 'A5', 'A1', 'A9', 'A6', 'A7', 'A10')

# === Colunas de output ===
COL_SETUP_ID = 'setup_id'
COL_SETUP_SIGNATURE = 'setup_signature'
COL_SETUP_STATE = 'setup_state'
COL_SETUP_DIRECTION = 'setup_direction'
COL_SETUP_ZONE_LOW = 'setup_zone_low'
COL_SETUP_ZONE_HIGH = 'setup_zone_high'
COL_SETUP_INVALIDATION_REASON = 'setup_invalidation_reason'
SETUP_OUTPUT_COLUMNS = (
    COL_SETUP_ID,
    COL_SETUP_SIGNATURE,
    COL_SETUP_STATE,
    COL_SETUP_DIRECTION,
    COL_SETUP_ZONE_LOW,
    COL_SETUP_ZONE_HIGH,
    COL_SETUP_INVALIDATION_REASON,
)


@dataclass(frozen=True)
class SetupConfig:
    """Configuração dedicada da máquina de estados de setup.

    Não incha `SMCConfig`. Defaults ancorados em SMC_PRINCIPIOS §2.5 onde
    a fonte numera, e em decisão de engenharia onde não numera.

    NOTA G4 (`volume_pct_min`, adendo §1): tetos empíricos de 2 anos do
    `active_*_swing_ob_volume_pct_1h` — BTC bull 0,110 / bear 0,199; ETH
    bull 0,231 / bear 0,128. O default 0,2 fica **acima do teto em 3 dos
    4 lados-ativo** (A5-BTC = 0 setups em 2 anos). O valor pertence ao
    espaço de hyperopt sob gate treino/OOS; o default NÃO muda no Bloco 1.

    Campos do Bloco 1 (Briefing 2) — ver docstring do módulo. Com os
    defaults abaixo o comportamento é byte-idêntico ao pré-Bloco 1.
    """
    # Invalidação ARMED (SMC_PRINCIPIOS §2.5)
    armed_escape_pct: float = 0.02        # >2% além da zona sem entrar
    armed_timeout_candles: int = 24       # 6h em 15m, sem atividade
    # Invalidação PENDING
    pending_timeout_candles: int = 16     # N — decisão de engenharia
    # Catalisador / confirmação
    sweep_recency_candles: int = 16       # sweep válido nos últimos K candles
    fvg_ob_adjacency_pct: float = 0.003   # OB↔FVG adjacentes (decisão de projeto)
    rejection_wick_frac: float = 0.5      # pavio direcional >= 50% do range
    rejection_close_frac: float = 0.667   # close no terço favorável
    # Wave 9.5b
    entry_mode: str = ENTRY_MODE_CONFIRMATION   # confirmation | risk | hybrid (D1)
    volume_pct_min: float = 0.2           # limiar de volume da A5 (D5)
    # `signature` aceita um id (str) ou uma sequência de ids. Default 'A3'
    # → caso de regressão byte-idêntico. Múltiplas → FSM itera por
    # prioridade D3 (um vencedor por candle).
    signature: object = 'A3'
    # Sufixos de TF após o merge @informative
    trend_suffix: str = '4h'
    zone_suffix: str = '1h'
    # --- Bloco 1 (Briefing 2): mecanismos config-gated; defaults preservam o legado ---
    arming_proximity_pct: float | None = None   # G1: None = desativado
    confirmation_trigger: str = 'legacy'        # G2: legacy | choch | choch_or_rej
    anchor_invalidation: str = 'promoted_id'    # G3: promoted_id | frozen_band
    a9_variant: str = 'legacy_ob'               # G5: legacy_ob | sweep_band

    def __post_init__(self) -> None:
        if self.armed_timeout_candles < 1:
            raise ValueError(
                f'armed_timeout_candles deve ser >= 1, '
                f'recebeu {self.armed_timeout_candles}'
            )
        if self.pending_timeout_candles < 1:
            raise ValueError(
                f'pending_timeout_candles deve ser >= 1, '
                f'recebeu {self.pending_timeout_candles}'
            )
        if self.sweep_recency_candles < 1:
            raise ValueError(
                f'sweep_recency_candles deve ser >= 1, '
                f'recebeu {self.sweep_recency_candles}'
            )
        if not 0.0 <= self.rejection_wick_frac <= 1.0:
            raise ValueError(
                f'rejection_wick_frac deve estar em [0, 1], '
                f'recebeu {self.rejection_wick_frac}'
            )
        if not 0.0 <= self.rejection_close_frac <= 1.0:
            raise ValueError(
                f'rejection_close_frac deve estar em [0, 1], '
                f'recebeu {self.rejection_close_frac}'
            )
        if self.entry_mode not in ENTRY_MODES:
            raise ValueError(
                f'entry_mode deve estar em {ENTRY_MODES}, '
                f'recebeu {self.entry_mode!r}'
            )
        if not 0.0 <= self.volume_pct_min <= 1.0:
            raise ValueError(
                f'volume_pct_min deve estar em [0, 1], '
                f'recebeu {self.volume_pct_min}'
            )
        if self.arming_proximity_pct is not None \
                and not 0.0 < self.arming_proximity_pct <= 1.0:
            raise ValueError(
                f'arming_proximity_pct deve ser None ou estar em (0, 1], '
                f'recebeu {self.arming_proximity_pct}'
            )
        if self.confirmation_trigger not in CONFIRMATION_TRIGGERS:
            raise ValueError(
                f'confirmation_trigger deve estar em {CONFIRMATION_TRIGGERS}, '
                f'recebeu {self.confirmation_trigger!r}'
            )
        if self.anchor_invalidation not in ANCHOR_INVALIDATIONS:
            raise ValueError(
                f'anchor_invalidation deve estar em {ANCHOR_INVALIDATIONS}, '
                f'recebeu {self.anchor_invalidation!r}'
            )
        if self.a9_variant not in A9_VARIANTS:
            raise ValueError(
                f'a9_variant deve estar em {A9_VARIANTS}, '
                f'recebeu {self.a9_variant!r}'
            )
        ids = [self.signature] if isinstance(self.signature, str) \
            else list(self.signature)
        if not ids:
            raise ValueError('signature não pode ser vazia')
        for sid in ids:
            if sid not in _VALID_SIGNATURE_IDS:
                raise ValueError(
                    f'signature {sid!r} inválida; válidas: '
                    f'{_VALID_SIGNATURE_IDS}'
                )


# ============================================================
# setup_id determinístico
# ============================================================

def _make_setup_id_anchors(
    signature: str, direction: str, anchors, t_armed,
) -> str:
    """Hash determinístico de (signature, direction, *anchors, t_armed).

    Generaliza o id da 9.5a para um número arbitrário de âncoras
    preservando a forma canônica da A3: com `anchors=(ob_id, fvg_id)` a
    f-string resultante é **idêntica** à da 9.5a (gate de regressão).
    """
    parts = [signature, direction]
    for a in anchors:
        if a is None or (isinstance(a, float) and np.isnan(a)):
            parts.append('')
        else:
            parts.append(str(int(a)))
    parts.append(f'{t_armed}')
    canonical = '|'.join(parts)
    return hashlib.sha1(canonical.encode('utf-8')).hexdigest()[:16]


def _make_setup_id(
    signature: str, direction: str, ob_id, fvg_id, t_armed,
) -> str:
    """Compat 9.5a: id de A3 a partir de (ob_id, fvg_id). Delega ao
    construtor por âncoras (saída byte-idêntica)."""
    return _make_setup_id_anchors(signature, direction, (ob_id, fvg_id), t_armed)


# ============================================================
# Helpers de coluna / arrays
# ============================================================

def _require_columns(df: pd.DataFrame, columns: list[str]) -> None:
    missing = [c for c in columns if c not in df.columns]
    if missing:
        raise ValueError(
            f'compute_setup_state() exige colunas mergeadas ausentes: '
            f'{missing}. O df deve estar mergeado com as colunas '
            f'_4h/_1h (ver align_informative / @informative).'
        )


def _float_col(df: pd.DataFrame, col: str) -> np.ndarray:
    """Extrai coluna como float64 (Int64/null → NaN), robusto a dtype."""
    return pd.to_numeric(df[col], errors='coerce').to_numpy(dtype='float64')


def _opt_float_col(df: pd.DataFrame, col: str, n: int) -> np.ndarray:
    """Como `_float_col`, mas devolve array de NaN se a coluna faltar.

    Permite que assinaturas não-selecionadas (cujas colunas podem não
    existir no df) não derrubem o builder; `_require_columns` garante a
    presença das colunas das assinaturas **selecionadas**.
    """
    if col in df.columns:
        return _float_col(df, col)
    return np.full(n, np.nan, dtype='float64')


def _opt_bool_col(df: pd.DataFrame, col: str, n: int) -> np.ndarray:
    """Coluna booleana densa; devolve array all-False se a coluna faltar.

    Análogo a `_opt_float_col` para gates booleanos de base (ex.: killzones
    `in_kz_silver_bullet_*`). Coluna ausente ⇒ gate inativo (all-False),
    não erro — só as colunas das assinaturas **selecionadas** são exigidas
    por `_require_columns` (via `required_base`).
    """
    if col in df.columns:
        return df[col].fillna(False).to_numpy(dtype='bool')
    return np.zeros(n, dtype='bool')


def _rolling_any(flag: np.ndarray, window: int) -> np.ndarray:
    """True em T se houver algum True na janela [T-window+1, T] (lookahead-safe)."""
    s = pd.Series(flag.astype('float64'))
    return (s.rolling(window, min_periods=1).max() > 0).to_numpy()


def _recency_age(flag: np.ndarray) -> np.ndarray:
    """Idade (em candles) do último True em [0, T], `inf` se nenhum.

    Lookahead-safe: só olha passado/presente. Usado para desempatar a
    direção da A9 (sweep mais recente vence)."""
    n = len(flag)
    age = np.full(n, np.inf, dtype='float64')
    last = -1
    for i in range(n):
        if flag[i]:
            last = i
        if last >= 0:
            age[i] = i - last
    return age


def _sweep_band_ffill(
    flag: np.ndarray, low_evt: np.ndarray, high_evt: np.ndarray,
):
    """Banda do sweep forward-filled desde o último candle-evento (G5).

    Nos candles-evento `e` (flag True) captura a banda
    `[low_evt[e], high_evt[e]]` e a propaga para frente até o próximo
    evento; `id` = índice do candle-evento (float, análogo aos ids de
    zona promovida). Lookahead-safe (só passado/presente). NaN antes do
    primeiro evento.
    """
    n = len(flag)
    lo = np.full(n, np.nan, dtype='float64')
    hi = np.full(n, np.nan, dtype='float64')
    bid = np.full(n, np.nan, dtype='float64')
    cur_lo = cur_hi = cur_id = np.nan
    for i in range(n):
        if flag[i]:
            cur_lo = low_evt[i]
            cur_hi = high_evt[i]
            cur_id = float(i)
        lo[i] = cur_lo
        hi[i] = cur_hi
        bid[i] = cur_id
    return lo, hi, bid


def _zone_arrays(A: dict, kind: str, direction: str):
    """(top, bottom, id) da zona `kind` ∈ {ob, fvg, ifvg} na `direction`."""
    pre = 'bull' if direction == DIRECTION_LONG else 'bear'
    return (
        A[f'{pre}_{kind}_top'],
        A[f'{pre}_{kind}_bottom'],
        A[f'{pre}_{kind}_id'],
    )


# ============================================================
# Assinatura declarativa (matcher)
# ============================================================

@dataclass(frozen=True)
class Signature:
    """Representação declarativa de uma assinatura de setup.

    A FSM itera as assinaturas selecionadas por `priority` e, num candle
    sem setup ativo, arma a primeira cuja direção candidata é não-nula e
    cujo `arm_fn` é True.

    Callables operam sobre o dict de arrays `A` (saída de `_build_arrays`):
    - `direction_fn(A) -> ndarray[object]` de {'long','short',None} por candle.
    - `zone_fn(A, direction) -> (zlow[], zhigh[], anchors[n,k])`: zona e
      âncoras (ids cuja persistência define a validade) da `direction`.
    - `arm_fn(A, direction) -> ndarray[bool]`.
    - `confirm_fn(A, direction) -> ndarray[bool]` (só consultado em
      `confirmation`).
    """
    id: str
    tipo: str                          # 'continuacao' | 'reversao' | 'tap'
    entry_mode_preferido: str          # documental; o efetivo vem do SetupConfig
    priority: int                      # menor = maior prioridade (D3)
    trend_gated: bool                  # consome trend 4H (e invalida por trend_changed)
    required_kinds: tuple              # kinds de zona exigidos no df
    direction_fn: Callable
    zone_fn: Callable
    arm_fn: Callable
    confirm_fn: Callable
    # Colunas de **base** (sem sufixo de TF) exigidas além dos kinds de
    # zona — ex.: killzones da A7 (`SESSION_COLUMNS`). Campo trailing com
    # default (9.5e, D6.1): as instâncias posicionais anteriores ficam
    # válidas sem alteração.
    required_base: tuple = ()


# ---- Direção candidata ----

def _direction_from_trend(A: dict) -> np.ndarray:
    """Direção de assinaturas de continuação: +1 → long, −1 → short."""
    trend = A['trend']
    out = np.empty(len(trend), dtype=object)
    out[:] = None
    out[trend == 1.0] = DIRECTION_LONG
    out[trend == -1.0] = DIRECTION_SHORT
    return out


def _direction_from_zone(A: dict, kind: str) -> np.ndarray:
    """Direção *negociável* da zona `kind` presente (reversão).

    `active_bull_{kind}_*` presente → long; `active_bear_{kind}_*` → short.
    **Sem** gate de trend 4H. Empate (ambas presentes) → a de menor
    distância ao close; empate exato → long.
    """
    n = A['n']
    c = A['c']
    bull_top, bull_bot, bull_id = _zone_arrays(A, kind, DIRECTION_LONG)
    bear_top, bear_bot, bear_id = _zone_arrays(A, kind, DIRECTION_SHORT)
    out = np.empty(n, dtype=object)
    out[:] = None
    has_bull = ~np.isnan(bull_id)
    has_bear = ~np.isnan(bear_id)
    with np.errstate(invalid='ignore'):
        d_bull = np.where(
            c < bull_bot, bull_bot - c,
            np.where(c > bull_top, c - bull_top, 0.0),
        )
        d_bear = np.where(
            c < bear_bot, bear_bot - c,
            np.where(c > bear_top, c - bear_top, 0.0),
        )
    only_bull = has_bull & ~has_bear
    only_bear = has_bear & ~has_bull
    both = has_bull & has_bear
    out[only_bull] = DIRECTION_LONG
    out[only_bear] = DIRECTION_SHORT
    with np.errstate(invalid='ignore'):
        both_long = both & (d_bull <= d_bear)
        both_short = both & (d_bull > d_bear)
    out[both_long] = DIRECTION_LONG
    out[both_short] = DIRECTION_SHORT
    return out


def _direction_from_ifvg(A: dict) -> np.ndarray:
    """Direção da A4a (reversão): direção negociável da IFVG presente."""
    return _direction_from_zone(A, 'ifvg')


def _direction_from_breaker(A: dict) -> np.ndarray:
    """Direção da A6 (reversão): direção negociável da zona breaker presente.

    `active_bull_breaker_*` → long; `active_bear_breaker_*` → short.
    Desempate por menor distância ao close (espelha IFVG).
    """
    return _direction_from_zone(A, 'breaker')


def _direction_from_sweep(A: dict) -> np.ndarray:
    """Direção da A9 (reversão): vinda do sweep recente.

    `bull_sweep_recent` → long; `bear_sweep_recent` → short. Empate (ambos
    recentes) → o de sweep **mais recente** (menor idade); empate exato →
    long (espelha a convenção de desempate de `_direction_from_zone`).
    **Sem** gate de trend 4H.
    """
    n = A['n']
    bull_recent = A['bull_sweep_recent']
    bear_recent = A['bear_sweep_recent']
    bull_age = A['bull_sweep_age']
    bear_age = A['bear_sweep_age']
    out = np.empty(n, dtype=object)
    out[:] = None
    only_bull = bull_recent & ~bear_recent
    only_bear = bear_recent & ~bull_recent
    both = bull_recent & bear_recent
    out[only_bull] = DIRECTION_LONG
    out[only_bear] = DIRECTION_SHORT
    out[both & (bull_age <= bear_age)] = DIRECTION_LONG
    out[both & (bull_age > bear_age)] = DIRECTION_SHORT
    return out


# ---- Zona + âncoras ----

def _zone_ob(A: dict, direction: str, with_fvg: bool):
    """Zona = banda do OB swing; âncoras = (ob_id[, fvg_id])."""
    ob_top, ob_bot, ob_id = _zone_arrays(A, 'ob', direction)
    if with_fvg:
        _, _, fvg_id = _zone_arrays(A, 'fvg', direction)
        anchors = np.column_stack([ob_id, fvg_id])
    else:
        anchors = ob_id.reshape(-1, 1)
    return ob_bot, ob_top, anchors


def _zone_A3(A: dict, direction: str):
    return _zone_ob(A, direction, with_fvg=True)


def _zone_ob_only(A: dict, direction: str):
    return _zone_ob(A, direction, with_fvg=False)


def _zone_A4a(A: dict, direction: str):
    """Zona = banda da IFVG; âncora = (ifvg_id,)."""
    it, ib, iid = _zone_arrays(A, 'ifvg', direction)
    return ib, it, iid.reshape(-1, 1)


def _zone_A6(A: dict, direction: str):
    """Zona = banda do breaker; âncora = (breaker_id, fvg_id).

    O `fvg_id` participa da âncora (junto do `breaker_id`) para que a
    invalidação por âncora na FSM também derrube o setup se o FVG sumir
    (briefing §3.4)."""
    bt, bb, bid = _zone_arrays(A, 'breaker', direction)
    _, _, fvg_id = _zone_arrays(A, 'fvg', direction)
    anchors = np.column_stack([bid, fvg_id])
    return bb, bt, anchors


# ---- Armação ----

def _outside(A: dict, direction: str, zlow: np.ndarray, zhigh: np.ndarray) -> np.ndarray:
    """Preço ainda não entrou na zona: long → low > zhigh; short → high < zlow."""
    with np.errstate(invalid='ignore'):
        if direction == DIRECTION_LONG:
            return A['low'] > zhigh
        return A['h'] < zlow


def _arm_zone_with_fvg(A: dict, direction: str, kind: str) -> np.ndarray:
    """Zona `kind` + FVG (mesma direção) + adjacência zona↔FVG + preço fora.

    Núcleo compartilhado por A3 (`kind='ob'`) e A6 (`kind='breaker'`): a
    banda da zona base e a banda do FVG devem sobrepor ou ser adjacentes
    (gap <= `fvg_ob_adjacency_pct` da banda), com ambas as âncoras
    presentes e o preço ainda fora da zona base.
    """
    cfg = A['cfg']
    z_top, z_bot, z_id = _zone_arrays(A, kind, direction)
    fv_top, fv_bot, fv_id = _zone_arrays(A, 'fvg', direction)
    with np.errstate(invalid='ignore'):
        z_mid = (z_top + z_bot) / 2.0
        overlap = (z_bot <= fv_top) & (fv_bot <= z_top)
        gap = np.maximum(np.maximum(fv_bot - z_top, z_bot - fv_top), 0.0)
        adjacent = overlap | (gap <= cfg.fvg_ob_adjacency_pct * z_mid)
    has = (~np.isnan(z_id)) & (~np.isnan(fv_id))
    return has & adjacent & _outside(A, direction, z_bot, z_top)


def _arm_A3(A: dict, direction: str) -> np.ndarray:
    """OB swing + FVG (mesma direção) + adjacência OB↔FVG + preço fora."""
    return _arm_zone_with_fvg(A, direction, 'ob')


def _arm_A1(A: dict, direction: str) -> np.ndarray:
    """OB swing presente + preço fora. Sem sweep (vs A2), sem FVG (vs A3)."""
    ob_top, ob_bot, ob_id = _zone_arrays(A, 'ob', direction)
    has = ~np.isnan(ob_id)
    return has & _outside(A, direction, ob_bot, ob_top)


def _arm_A6(A: dict, direction: str) -> np.ndarray:
    """Breaker + FVG (mesma direção negociável) + adjacência + preço fora."""
    return _arm_zone_with_fvg(A, direction, 'breaker')


def _arm_A2(A: dict, direction: str) -> np.ndarray:
    """OB swing + sweep recente (mesma direção) + preço fora. Sem FVG."""
    ob_top, ob_bot, ob_id = _zone_arrays(A, 'ob', direction)
    has = ~np.isnan(ob_id)
    sweep = A['bull_sweep_recent'] if direction == DIRECTION_LONG \
        else A['bear_sweep_recent']
    return has & sweep & _outside(A, direction, ob_bot, ob_top)


def _arm_A5(A: dict, direction: str) -> np.ndarray:
    """OB swing com volume_pct > volume_pct_min + preço fora."""
    cfg = A['cfg']
    ob_top, ob_bot, ob_id = _zone_arrays(A, 'ob', direction)
    pre = 'bull' if direction == DIRECTION_LONG else 'bear'
    volpct = A[f'{pre}_ob_volpct']
    has = ~np.isnan(ob_id)
    with np.errstate(invalid='ignore'):
        vol_ok = volpct > cfg.volume_pct_min
    return has & vol_ok & _outside(A, direction, ob_bot, ob_top)


def _arm_A4a(A: dict, direction: str) -> np.ndarray:
    """IFVG (direção negociável) presente + preço fora da banda IFVG."""
    it, ib, iid = _zone_arrays(A, 'ifvg', direction)
    has = ~np.isnan(iid)
    return has & _outside(A, direction, ib, it)


def _zone_A7(A: dict, direction: str):
    """A7 (Silver Bullet): zona = banda do FVG da direção; âncora = (fvg_id,).

    OBJETIVO
        Fornecer a banda (zlow, zhigh) e a âncora de invalidação da A7 a
        partir do FVG ativo da `direction` (long → `bull_fvg_*`, short →
        `bear_fvg_*`).
    FONTE DE DADOS
        `_zone_arrays(A, 'fvg', direction)` → (top, bottom, id). As colunas
        FVG são consumidas com sufixo de zona `_{zs}` (default `_1h`).
    LIMITAÇÕES
        Espelha `_zone_A4a`; só fornece a forma declarativa, não decide
        armação (ver `_arm_A7`).
    NÃO FAZER
        Não suffixar killzone aqui (killzone é gate de base, em `_arm_A7`);
        não inverter direção (FVG bull → long).
    """
    ft, fb, fid = _zone_arrays(A, 'fvg', direction)
    return fb, ft, fid.reshape(-1, 1)


def _arm_A7(A: dict, direction: str) -> np.ndarray:
    """A7: FVG(dir) + sweep recente(dir) + killzone ativa + preço fora.

    OBJETIVO
        Armar a continuação Silver Bullet: FVG da direção presente, sweep
        recente da mesma direção, candle dentro de alguma killzone Silver
        Bullet (`in_kz_any`) e preço ainda fora da banda do FVG.
    FONTE DE DADOS
        `_zone_arrays(A, 'fvg', direction)`; `A['{bull,bear}_sweep_recent']`
        (base 15m, janela `sweep_recency_candles`); `A['in_kz_any']` (OR das
        3 colunas `in_kz_silver_bullet_*`, base/sem sufixo); `_outside`.
    LIMITAÇÕES
        Gate de killzone só na armação (D2): o setup origina-se na janela e
        pode confirmar depois. Quais killzones / recência de sweep / janela
        de confirmação são varredura da Wave 10, não definitivo aqui.
    NÃO FAZER
        Não pré-podar para AM (§6/§7); não suffixar as colunas de killzone.
    """
    ft, fb, fid = _zone_arrays(A, 'fvg', direction)
    has = ~np.isnan(fid)
    sweep = A['bull_sweep_recent'] if direction == DIRECTION_LONG \
        else A['bear_sweep_recent']
    return has & sweep & A['in_kz_any'] & _outside(A, direction, fb, ft)


def _zone_A10(A: dict, direction: str):
    """A10 (OTE): zona = banda OTE da direção; âncora = (ote_id,).

    OBJETIVO
        Fornecer a banda (zlow, zhigh) e a âncora da A10 a partir da zona
        OTE ativa da `direction` (long → `bull_ote_*` = banda discount,
        short → `bear_ote_*` = banda premium).
    FONTE DE DADOS
        `_zone_arrays(A, 'ote', direction)` → (top, bottom, id). As colunas
        OTE são tratadas como zona, consumidas com sufixo `_{zs}` (default
        `_1h`), igual a OB/FVG/IFVG/breaker.
    LIMITAÇÕES
        Espelha `_zone_A4a`; não decide armação (ver `_arm_A10`).
    NÃO FAZER
        Não inverter direção (D3): o hook já mapeia bull→discount/long e
        bear→premium/short; `_direction_from_trend` concorda por construção.
    """
    ot, ob, oid = _zone_arrays(A, 'ote', direction)
    return ob, ot, oid.reshape(-1, 1)


def _arm_A10(A: dict, direction: str) -> np.ndarray:
    """A10: OTE(dir) presente + preço fora da banda OTE.

    OBJETIVO
        Armar a continuação OTE: zona OTE da direção presente e preço ainda
        fora da banda (Fib 62–79%). Sem premissa de sweep (vs A7).
    FONTE DE DADOS
        `_zone_arrays(A, 'ote', direction)`; `_outside`.
    LIMITAÇÕES
        OTE é zona persistente (medido: bear ativa em 572/720 no 4h golden)
        → contagem alta de armações é esperada e não justifica pré-poda
        nesta wave (§6).
    NÃO FAZER
        Não inverter direção (D3 — qualquer inversão aqui é bug, oposto do
        trap do IFVG).
    """
    ot, ob, oid = _zone_arrays(A, 'ote', direction)
    has = ~np.isnan(oid)
    return has & _outside(A, direction, ob, ot)


def _zone_A9_sweep_band(A: dict, direction: str):
    """A9 variante `sweep_band` (G5): zona = banda do próprio sweep.

    OBJETIVO
        Fornecer a banda (zlow, zhigh) e a âncora `(id,)` da A9 a partir
        do último sweep da direção: bull → `[low_evt, level_price]`,
        bear → `[level_price, high_evt]` (arrays de `_build_arrays`).
        Elimina o gate de OB sem proveniência conceitual (relatório
        Fase A Parte 2, achado G5).
    FONTE DE DADOS
        `A['{pre}_sweepband_{low,high,id}']` — construídos de
        `sweep_{pre}_{wick,retest}` + `sweep_{pre}_level_price` (base
        15m, sem sufixo) via `_sweep_band_ffill`.
    LIMITAÇÕES
        `id` é o índice do candle-evento; um novo sweep da mesma direção
        troca a âncora (relevante só em `anchor_invalidation='promoted_id'`).
    NÃO FAZER
        Não consumir colunas de OB aqui; não inverter direção
        (`_direction_from_sweep` permanece a fonte da direção).
    """
    pre = 'bull' if direction == DIRECTION_LONG else 'bear'
    return (
        A[f'{pre}_sweepband_low'],
        A[f'{pre}_sweepband_high'],
        A[f'{pre}_sweepband_id'].reshape(-1, 1),
    )


def _arm_A9_sweep_band(A: dict, direction: str) -> np.ndarray:
    """A9 variante `sweep_band` (G5): banda do sweep recente + preço fora.

    OBJETIVO
        Armar a A9 sem OB: banda do sweep presente, idade do evento
        `<= cfg.sweep_recency_candles` e preço ainda fora da banda.
    FONTE DE DADOS
        `A['{pre}_sweepband_{low,high,age,id}']`; `_outside`.
    LIMITAÇÕES
        A confirmação no mapeamento G2 usa a variante **sem** sweep
        (o sweep já é a armação — briefing Bloco 1 §2.5).
    NÃO FAZER
        Não exigir OB (é exatamente o gate removido pelo G5).
    """
    cfg = A['cfg']
    pre = 'bull' if direction == DIRECTION_LONG else 'bear'
    lo = A[f'{pre}_sweepband_low']
    hi = A[f'{pre}_sweepband_high']
    bid = A[f'{pre}_sweepband_id']
    age = A[f'{pre}_sweepband_age']
    has = (~np.isnan(bid)) & (~np.isnan(lo)) & (~np.isnan(hi))
    with np.errstate(invalid='ignore'):
        recent = age <= cfg.sweep_recency_candles
    return has & recent & _outside(A, direction, lo, hi)


# ---- Confirmação (só consultada em modo confirmation) ----

def _confirm_choch_rej_sweep(A: dict, direction: str) -> np.ndarray:
    """A3/A2: ChoCH + rejeição + sweep recente (mesmo primitivo)."""
    if direction == DIRECTION_LONG:
        return A['choch_bull'] & A['rej_bull'] & A['bull_sweep_recent']
    return A['choch_bear'] & A['rej_bear'] & A['bear_sweep_recent']


def _confirm_choch_rej(A: dict, direction: str) -> np.ndarray:
    """A4a/A5: ChoCH (direção da reversão/setup) + rejeição."""
    if direction == DIRECTION_LONG:
        return A['choch_bull'] & A['rej_bull']
    return A['choch_bear'] & A['rej_bear']


# ---- Gatilhos re-desenhados (Bloco 1, G2) ----
# Racional: canônico §2.11 [v2.0] — o consensual é MSS/CISD como gatilho;
# rejeição é *alternativa*, não conjunção. A conjunção legada
# ChoCH∧rejeição no mesmo candle é evento quase-nulo medido
# (co-ocorrência 10,4/10k BTC, 5,7/10k ETH; 7–8 CONFIRMED em 2 anos
# somando as 9 assinaturas — adendo §1). Selecionados em runtime por
# `SetupConfig.confirmation_trigger`; o registro SIGNATURES não muda.

def _confirm_choch(A: dict, direction: str) -> np.ndarray:
    """G2 `trigger='choch'`: gatilho MSS puro (ChoCH internal da direção)."""
    if direction == DIRECTION_LONG:
        return A['choch_bull']
    return A['choch_bear']


def _confirm_choch_sweep(A: dict, direction: str) -> np.ndarray:
    """G2 `trigger='choch'` p/ assinaturas com premissa de sweep:
    MSS ∧ sweep_recent."""
    if direction == DIRECTION_LONG:
        return A['choch_bull'] & A['bull_sweep_recent']
    return A['choch_bear'] & A['bear_sweep_recent']


def _confirm_choch_or_rej(A: dict, direction: str) -> np.ndarray:
    """G2 `trigger='choch_or_rej'`: (MSS ∨ rejeição)."""
    if direction == DIRECTION_LONG:
        return A['choch_bull'] | A['rej_bull']
    return A['choch_bear'] | A['rej_bear']


def _confirm_choch_or_rej_sweep(A: dict, direction: str) -> np.ndarray:
    """G2 `trigger='choch_or_rej'` p/ assinaturas com premissa de sweep:
    (MSS ∨ rejeição) ∧ sweep_recent."""
    if direction == DIRECTION_LONG:
        return (A['choch_bull'] | A['rej_bull']) & A['bull_sweep_recent']
    return (A['choch_bear'] | A['rej_bear']) & A['bear_sweep_recent']


# Assinaturas com premissa de sweep na armação (mantêm o ∧ sweep_recent
# no mapeamento G2). A9 fica FORA do conjunto mesmo sendo sweep-based:
# na variante `sweep_band` o sweep já é a armação (briefing §2.5).
_SWEEP_PREMISE_SIGNATURE_IDS = ('A3', 'A2', 'A7')

# trigger → (confirm_fn com premissa de sweep, confirm_fn demais).
_CONFIRM_TRIGGER_FNS = {
    CONFIRMATION_TRIGGER_CHOCH: (_confirm_choch_sweep, _confirm_choch),
    CONFIRMATION_TRIGGER_CHOCH_OR_REJ: (
        _confirm_choch_or_rej_sweep, _confirm_choch_or_rej,
    ),
}


# ---- Registro das assinaturas (ordem de prioridade D3) ----
# As 4 da 9.5b ficam **inalteradas** (gate de regressão); a 9.5c apenda
# A1 (prioridade 4), A9 (5) e A6 (6). Prioridade só decide empate "duas
# armam no mesmo candle"; é revisável no backtest da Wave 10 (§3.5/§6).

SIGNATURES: dict[str, Signature] = {
    'A3': Signature(
        'A3', 'continuacao', ENTRY_MODE_CONFIRMATION, 0, True, ('ob', 'fvg'),
        _direction_from_trend, _zone_A3, _arm_A3, _confirm_choch_rej_sweep,
    ),
    'A2': Signature(
        'A2', 'continuacao', ENTRY_MODE_CONFIRMATION, 1, True, ('ob',),
        _direction_from_trend, _zone_ob_only, _arm_A2, _confirm_choch_rej_sweep,
    ),
    'A4a': Signature(
        'A4a', 'reversao', ENTRY_MODE_CONFIRMATION, 2, False, ('ifvg',),
        _direction_from_ifvg, _zone_A4a, _arm_A4a, _confirm_choch_rej,
    ),
    'A5': Signature(
        'A5', 'tap', ENTRY_MODE_RISK, 3, True, ('ob', 'volpct'),
        _direction_from_trend, _zone_ob_only, _arm_A5, _confirm_choch_rej,
    ),
    # --- Wave 9.5c (apêndice) ---
    'A1': Signature(
        'A1', 'continuacao', ENTRY_MODE_CONFIRMATION, 4, True, ('ob',),
        _direction_from_trend, _zone_ob_only, _arm_A1, _confirm_choch_rej,
    ),
    'A9': Signature(
        'A9', 'reversao', ENTRY_MODE_CONFIRMATION, 5, False, ('ob',),
        _direction_from_sweep, _zone_ob_only, _arm_A2, _confirm_choch_rej,
    ),
    'A6': Signature(
        'A6', 'reversao', ENTRY_MODE_CONFIRMATION, 6, False, ('breaker', 'fvg'),
        _direction_from_breaker, _zone_A6, _arm_A6, _confirm_choch_rej,
    ),
    # --- Wave 9.5e (apêndice; D4 — não renumerar 0–6) ---
    # A7 (7): Silver Bullet (Sweep+FVG+killzone), continuação trend-gated,
    # confirmação por ChoCH+rej+sweep (paridade A3/A2). `required_base` =
    # killzones (base, sem sufixo).
    'A7': Signature(
        'A7', 'continuacao', ENTRY_MODE_CONFIRMATION, 7, True, ('fvg',),
        _direction_from_trend, _zone_A7, _arm_A7, _confirm_choch_rej_sweep,
        required_base=SESSION_COLUMNS,
    ),
    # A10 (8): OTE (Fib 62–79%), continuação trend-gated, confirmação por
    # ChoCH+rejeição (A10 não tem premissa de sweep).
    'A10': Signature(
        'A10', 'continuacao', ENTRY_MODE_CONFIRMATION, 8, True, ('ote',),
        _direction_from_trend, _zone_A10, _arm_A10, _confirm_choch_rej,
    ),
}


def _resolve_signatures(config: SetupConfig) -> list[Signature]:
    """Lista de assinaturas selecionadas, ordenada por prioridade (D3)."""
    ids = [config.signature] if isinstance(config.signature, str) \
        else list(config.signature)
    sigs = [SIGNATURES[sid] for sid in ids]
    return sorted(sigs, key=lambda s: s.priority)


_KIND_COLUMNS = {
    'ob': ('active_{pre}_swing_ob_top_{zs}',
           'active_{pre}_swing_ob_bottom_{zs}',
           'active_{pre}_swing_ob_id_{zs}'),
    'fvg': ('active_{pre}_fvg_top_{zs}',
            'active_{pre}_fvg_bottom_{zs}',
            'active_{pre}_fvg_id_{zs}'),
    'ifvg': ('active_{pre}_ifvg_top_{zs}',
             'active_{pre}_ifvg_bottom_{zs}',
             'active_{pre}_ifvg_id_{zs}'),
    'breaker': ('active_{pre}_breaker_top_{zs}',
                'active_{pre}_breaker_bottom_{zs}',
                'active_{pre}_breaker_id_{zs}'),
    'ote': ('active_{pre}_ote_top_{zs}',
            'active_{pre}_ote_bottom_{zs}',
            'active_{pre}_ote_id_{zs}'),
    'volpct': ('active_{pre}_swing_ob_volume_pct_{zs}',),
}


def _required_columns(config: SetupConfig, signatures: list[Signature]) -> list[str]:
    """Colunas exigidas: base + trend (se trend-gated) + kinds das sigs."""
    zs = config.zone_suffix
    ts = config.trend_suffix
    cols = [
        'open', 'high', 'low', 'close', 'date',
        'sweep_bullish_wick', 'sweep_bullish_retest',
        'sweep_bearish_wick', 'sweep_bearish_retest',
        'choch_internal_bullish', 'choch_internal_bearish',
    ]
    if any(sig.trend_gated for sig in signatures):
        cols.append(f'swing_trend_bias_{ts}')
    seen = set(cols)
    for sig in signatures:
        kinds = sig.required_kinds
        # G5: A9 em `sweep_band` dispensa o kind 'ob' (o gate de OB é
        # exatamente o removido) e exige os level_price do sweep (base).
        if sig.id == 'A9' and config.a9_variant == A9_VARIANT_SWEEP_BAND:
            kinds = tuple(k for k in kinds if k != 'ob')
            for name in ('sweep_bullish_level_price',
                         'sweep_bearish_level_price'):
                if name not in seen:
                    seen.add(name)
                    cols.append(name)
        for kind in kinds:
            for tmpl in _KIND_COLUMNS[kind]:
                for pre in ('bull', 'bear'):
                    name = tmpl.format(pre=pre, zs=zs)
                    if name not in seen:
                        seen.add(name)
                        cols.append(name)
    # Colunas de base exigidas além dos kinds (ex.: killzones da A7). Base,
    # sem sufixo de TF (9.5e, D6.4).
    for sig in signatures:
        for name in sig.required_base:
            if name not in seen:
                seen.add(name)
                cols.append(name)
    return cols


def _build_arrays(df: pd.DataFrame, config: SetupConfig) -> dict:
    """Empacota todos os arrays que os predicados das assinaturas consomem."""
    zs = config.zone_suffix
    ts = config.trend_suffix
    n = len(df)
    A: dict = {'cfg': config, 'n': n}
    A['o'] = df['open'].to_numpy(dtype='float64')
    A['h'] = df['high'].to_numpy(dtype='float64')
    A['low'] = df['low'].to_numpy(dtype='float64')
    A['c'] = df['close'].to_numpy(dtype='float64')
    A['dates'] = df['date'].to_numpy()
    A['trend'] = _opt_float_col(df, f'swing_trend_bias_{ts}', n)

    for pre in ('bull', 'bear'):
        A[f'{pre}_ob_top'] = _opt_float_col(df, f'active_{pre}_swing_ob_top_{zs}', n)
        A[f'{pre}_ob_bottom'] = _opt_float_col(df, f'active_{pre}_swing_ob_bottom_{zs}', n)
        A[f'{pre}_ob_id'] = _opt_float_col(df, f'active_{pre}_swing_ob_id_{zs}', n)
        A[f'{pre}_ob_volpct'] = _opt_float_col(df, f'active_{pre}_swing_ob_volume_pct_{zs}', n)
        A[f'{pre}_fvg_top'] = _opt_float_col(df, f'active_{pre}_fvg_top_{zs}', n)
        A[f'{pre}_fvg_bottom'] = _opt_float_col(df, f'active_{pre}_fvg_bottom_{zs}', n)
        A[f'{pre}_fvg_id'] = _opt_float_col(df, f'active_{pre}_fvg_id_{zs}', n)
        A[f'{pre}_ifvg_top'] = _opt_float_col(df, f'active_{pre}_ifvg_top_{zs}', n)
        A[f'{pre}_ifvg_bottom'] = _opt_float_col(df, f'active_{pre}_ifvg_bottom_{zs}', n)
        A[f'{pre}_ifvg_id'] = _opt_float_col(df, f'active_{pre}_ifvg_id_{zs}', n)
        A[f'{pre}_breaker_top'] = _opt_float_col(df, f'active_{pre}_breaker_top_{zs}', n)
        A[f'{pre}_breaker_bottom'] = _opt_float_col(df, f'active_{pre}_breaker_bottom_{zs}', n)
        A[f'{pre}_breaker_id'] = _opt_float_col(df, f'active_{pre}_breaker_id_{zs}', n)
        # OTE (9.5e): tratada como zona — sufixo `_{zs}` (default `_1h`).
        A[f'{pre}_ote_top'] = _opt_float_col(df, f'active_{pre}_ote_top_{zs}', n)
        A[f'{pre}_ote_bottom'] = _opt_float_col(df, f'active_{pre}_ote_bottom_{zs}', n)
        A[f'{pre}_ote_id'] = _opt_float_col(df, f'active_{pre}_ote_id_{zs}', n)

    # Gate de killzone Silver Bullet (A7): OR booleano das 3 colunas
    # `in_kz_silver_bullet_*` (base/sem sufixo, 9.5e D6.3), fallback
    # all-False se ausentes.
    in_kz_any = np.zeros(n, dtype='bool')
    for col in SESSION_COLUMNS:
        in_kz_any = in_kz_any | _opt_bool_col(df, col, n)
    A['in_kz_any'] = in_kz_any

    A['choch_bull'] = df['choch_internal_bullish'].fillna(False).to_numpy(dtype='bool')
    A['choch_bear'] = df['choch_internal_bearish'].fillna(False).to_numpy(dtype='bool')

    sweep_bull = (
        df['sweep_bullish_wick'].fillna(False).to_numpy(dtype='bool')
        | df['sweep_bullish_retest'].fillna(False).to_numpy(dtype='bool')
    )
    sweep_bear = (
        df['sweep_bearish_wick'].fillna(False).to_numpy(dtype='bool')
        | df['sweep_bearish_retest'].fillna(False).to_numpy(dtype='bool')
    )
    A['bull_sweep_recent'] = _rolling_any(sweep_bull, config.sweep_recency_candles)
    A['bear_sweep_recent'] = _rolling_any(sweep_bear, config.sweep_recency_candles)
    # Idade do último sweep (desempate de direção da A9 — sweep mais
    # recente vence; espelha o desempate por distância da reversão de zona).
    A['bull_sweep_age'] = _recency_age(sweep_bull)
    A['bear_sweep_age'] = _recency_age(sweep_bear)

    # Banda do sweep (Bloco 1, G5 — A9 `sweep_band`). Construída
    # incondicionalmente (decisão declarada: arrays baratos, e manter o
    # builder livre de branching por config): bull → [low_evt, level],
    # bear → [level, high_evt], forward-fill do último evento. As colunas
    # `sweep_*_level_price` são opcionais aqui (NaN se ausentes);
    # `_required_columns` as exige quando a variante está selecionada.
    bull_level = _opt_float_col(df, 'sweep_bullish_level_price', n)
    bear_level = _opt_float_col(df, 'sweep_bearish_level_price', n)
    (A['bull_sweepband_low'], A['bull_sweepband_high'],
     A['bull_sweepband_id']) = _sweep_band_ffill(sweep_bull, A['low'], bull_level)
    (A['bear_sweepband_low'], A['bear_sweepband_high'],
     A['bear_sweepband_id']) = _sweep_band_ffill(sweep_bear, bear_level, A['h'])
    # Idade do evento da banda == idade do último sweep (mesmo flag).
    A['bull_sweepband_age'] = A['bull_sweep_age']
    A['bear_sweepband_age'] = A['bear_sweep_age']

    rng = A['h'] - A['low']
    safe = rng > 0
    with np.errstate(invalid='ignore', divide='ignore'):
        upper_body = np.minimum(A['o'], A['c'])
        lower_body = np.maximum(A['o'], A['c'])
        bull_wick_frac = np.where(safe, (upper_body - A['low']) / rng, 0.0)
        bear_wick_frac = np.where(safe, (A['h'] - lower_body) / rng, 0.0)
    A['rej_bull'] = (
        safe
        & (bull_wick_frac >= config.rejection_wick_frac)
        & (A['c'] >= A['low'] + config.rejection_close_frac * rng)
    )
    A['rej_bear'] = (
        safe
        & (bear_wick_frac >= config.rejection_wick_frac)
        & (A['c'] <= A['h'] - config.rejection_close_frac * rng)
    )
    return A


def compute_setup_state(
    df: pd.DataFrame,
    config: SetupConfig | None = None,
) -> pd.DataFrame:
    """Computa a máquina de estados de setup (matcher declarativo, multi-modo).

    Stateless (df in, df out — igual `analyze()`). Recebe o DataFrame base
    (15m) **já mergeado** com as colunas de zona promovidas por
    `zone_projection.promote_active_zones`. Devolve o mesmo df + as 7
    colunas `setup_*` (inclui `setup_signature` — a assinatura A1–A10 do
    setup ativo, ao lado do `setup_id` hash; rastreio por assinatura).

    A FSM itera as assinaturas selecionadas em `config.signature` (default
    A3) por prioridade D3 e, num candle sem setup ativo, arma a primeira
    elegível. Fluxo `confirmation`: ARMED → PENDING_CONFIRMATION →
    CONFIRMED, com caminhos de INVALIDATED. Fluxo `risk` (D2): ARMED →
    CONFIRMED direto na interseção da zona (sem PENDING). Modela um setup
    ativo por vez, re-armável após terminal.

    Bloco 1 (config-gated; defaults = comportamento legado, byte-idêntico):
    - G1 `arming_proximity_pct`: na varredura de armação, exige preço a
      até `prox` da zona (long: `low <= zhigh*(1+prox)`; short:
      `high >= zlow*(1-prox)`); falhou → segue para a próxima assinatura.
      O gate é da FSM, não das `_arm_*` (as assinaturas não mudam).
      Semântica resultante: com `prox <= armed_escape_pct`, nenhum setup
      nasce além da linha de escape — `escaped` volta a medir fuga
      pós-armação, não distância de nascença.
    - G2 `confirmation_trigger`: substitui em memória o `confirm_fn` das
      assinaturas selecionadas (registro SIGNATURES intocado).
    - G3 `anchor_invalidation='frozen_band'`: remove a vigília de âncora
      do ARMED (`mitigated` deixa de ser emitida). LIMITAÇÃO declarada:
      decadência de premissa (ex.: FVG de confluência da A3/A6 sumir
      durante ARMED) fica sem monitor neste modo — escolha do Bloco 1.
    - G5 `a9_variant='sweep_band'`: zona/armação da A9 pela banda do
      próprio sweep (sem OB); `_required_columns` passa a exigir os
      `sweep_*_level_price` e dispensa o kind 'ob' da A9.

    Args:
        df: DataFrame base 15m mergeado (ver FONTE DE DADOS do módulo).
        config: SetupConfig. Se None, usa defaults (A3, confirmation).

    Returns:
        Cópia de `df` + 7 colunas (`SETUP_OUTPUT_COLUMNS`).

    Raises:
        NotImplementedError: se `config.entry_mode == 'hybrid'` (D1 — o
            fallback do hybrid depende de RESOLVED/SL, incomputável numa
            FSM stateless sem lookahead; ver SMC_PRINCIPIOS §3.4 e as
            LIMITAÇÕES deste módulo). Reaberto na Wave 9.5f/10.
    """
    if config is None:
        config = SetupConfig()

    if config.entry_mode == ENTRY_MODE_HYBRID:
        raise NotImplementedError(
            "entry_mode='hybrid' é stub nesta wave (D1): o fallback do "
            "hybrid depende de SL atingido (= RESOLVED), incomputável numa "
            "FSM stateless sem lookahead. Ver SMC_PRINCIPIOS §3.4 e as "
            "LIMITAÇÕES de setup_state.py. Reaberto na Wave 9.5f/10 quando "
            "houver realimentação de outcome."
        )

    signatures = _resolve_signatures(config)
    _require_columns(df, _required_columns(config, signatures))

    n = len(df)
    out = df.copy()
    A = _build_arrays(df, config)
    dates = A['dates']
    low = A['low']
    h = A['h']
    c = A['c']
    trend = A['trend']
    entry_mode = config.entry_mode
    escape_pct = config.armed_escape_pct
    armed_timeout = config.armed_timeout_candles
    pending_timeout = config.pending_timeout_candles
    # Bloco 1: G1 (gate de proximidade na armação; None = desligado) e
    # G3 (vigília de âncora só no modo legado 'promoted_id').
    prox = config.arming_proximity_pct
    check_anchor = config.anchor_invalidation == ANCHOR_INVALIDATION_PROMOTED_ID

    # Precompute, por assinatura e direção, os arrays de zona/arm/confirm.
    # prec: list de (Signature, dir_arr, {direction: (zlow, zhigh, anch, arm, conf)}).
    # Bloco 1: overrides em memória, SEM tocar o registro SIGNATURES —
    # G2 substitui o confirm_fn conforme `confirmation_trigger`; G5
    # substitui zone_fn/arm_fn da A9 conforme `a9_variant`.
    prec = []
    for sig in signatures:
        zone_fn = sig.zone_fn
        arm_fn = sig.arm_fn
        confirm_fn = sig.confirm_fn
        if config.confirmation_trigger != CONFIRMATION_TRIGGER_LEGACY:
            with_sweep, without_sweep = \
                _CONFIRM_TRIGGER_FNS[config.confirmation_trigger]
            confirm_fn = with_sweep \
                if sig.id in _SWEEP_PREMISE_SIGNATURE_IDS else without_sweep
        if sig.id == 'A9' and config.a9_variant == A9_VARIANT_SWEEP_BAND:
            zone_fn = _zone_A9_sweep_band
            arm_fn = _arm_A9_sweep_band
        dir_arr = sig.direction_fn(A)
        per = {}
        for d in (DIRECTION_LONG, DIRECTION_SHORT):
            zlow, zhigh, anch = zone_fn(A, d)
            arm = arm_fn(A, d)
            conf = confirm_fn(A, d)
            per[d] = (zlow, zhigh, anch, arm, conf)
        prec.append((sig, dir_arr, per))

    # --- output buffers ---
    out_id: list[str | None] = [None] * n
    out_sig: list[str | None] = [None] * n
    out_state: list[str | None] = [None] * n
    out_dir: list[str | None] = [None] * n
    out_zlow = np.full(n, np.nan, dtype='float64')
    out_zhigh = np.full(n, np.nan, dtype='float64')
    out_reason: list[str | None] = [None] * n

    # --- estado da FSM (um setup ativo por vez) ---
    state: str | None = None
    s_sig: Signature | None = None
    s_dir = ''
    s_id = ''
    s_zlow = np.nan
    s_zhigh = np.nan
    s_anch_arr = np.empty((0, 0))   # âncoras (n, k) da direção congelada
    s_captured_anch = np.empty(0)   # tupla de âncoras capturada na armação
    s_confirm = np.empty(0, dtype='bool')
    armed_idx = -1
    pending_idx = -1

    def _emit(i: int, st: str, reason: str | None = None) -> None:
        out_state[i] = st
        out_id[i] = s_id
        out_sig[i] = s_sig.id
        out_dir[i] = s_dir
        out_zlow[i] = s_zlow
        out_zhigh[i] = s_zhigh
        out_reason[i] = reason

    for i in range(n):
        if state is None:
            # ---- (vazio) → ARMED: scan por prioridade D3 ----
            for sig, dir_arr, per in prec:
                d = dir_arr[i]
                if d is None:
                    continue
                zlow, zhigh, anch, arm, conf = per[d]
                if arm[i]:
                    # G1: gate de proximidade — setup só nasce a até
                    # `prox` da zona; falhou → próxima assinatura da
                    # varredura (não arma). Espelha a aritmética do
                    # escape: com prox <= armed_escape_pct nenhum setup
                    # nasce além da linha de escape (T3, por construção).
                    if prox is not None:
                        if d == DIRECTION_LONG:
                            near = low[i] <= zhigh[i] * (1.0 + prox)
                        else:
                            near = h[i] >= zlow[i] * (1.0 - prox)
                        if not near:
                            continue
                    s_sig = sig
                    s_dir = d
                    s_zlow = zlow[i]
                    s_zhigh = zhigh[i]
                    s_anch_arr = anch
                    s_confirm = conf
                    s_captured_anch = anch[i]
                    s_id = _make_setup_id_anchors(
                        sig.id, d, tuple(s_captured_anch), dates[i],
                    )
                    armed_idx = i
                    state = STATE_ARMED
                    _emit(i, STATE_ARMED)
                    break
            continue

        is_long = s_dir == DIRECTION_LONG
        trend_ok_val = 1.0 if is_long else -1.0

        if state == STATE_ARMED:
            # 1. trend_changed (só assinaturas trend-gated)
            if s_sig.trend_gated and trend[i] != trend_ok_val:
                _emit(i, STATE_INVALIDATED, REASON_TREND_CHANGED)
                state = None
                continue
            # 2. mitigated (qualquer âncora NaN ou diferente da capturada).
            #    G3: pulado em anchor_invalidation='frozen_band' —
            #    mitigação real exige o preço entrar na zona (se entra
            #    com setup ARMED, o passo 3 dispara PENDING no mesmo
            #    candle; atravessamento vira zone_crossed). A vigília de
            #    id media troca de zona promovida por proximidade, não
            #    mitigação (15/15 espúrios no golden; 65–100% em 2 anos).
            #    `s_captured_anch` permanece só para o hash do setup_id.
            if check_anchor:
                cur = s_anch_arr[i]
                mitigated = False
                for a_now, a_cap in zip(cur, s_captured_anch):
                    if np.isnan(a_now) or a_now != a_cap:
                        mitigated = True
                        break
                if mitigated:
                    _emit(i, STATE_INVALIDATED, REASON_MITIGATED)
                    state = None
                    continue
            # 3. intersecta zona → PENDING (confirmation) ou CONFIRMED (risk)
            if low[i] <= s_zhigh and h[i] >= s_zlow:
                if entry_mode == ENTRY_MODE_RISK:
                    _emit(i, STATE_CONFIRMED)
                    state = None
                    continue
                pending_idx = i
                state = STATE_PENDING
                _emit(i, STATE_PENDING)
                continue
            # 4. escaped
            if is_long:
                escaped = low[i] > s_zhigh * (1.0 + escape_pct)
            else:
                escaped = h[i] < s_zlow * (1.0 - escape_pct)
            if escaped:
                _emit(i, STATE_INVALIDATED, REASON_ESCAPED)
                state = None
                continue
            # 5. timeout
            if i - armed_idx >= armed_timeout:
                _emit(i, STATE_INVALIDATED, REASON_TIMEOUT)
                state = None
                continue
            _emit(i, STATE_ARMED)
            continue

        if state == STATE_PENDING:
            # 1. trend_changed (só assinaturas trend-gated)
            if s_sig.trend_gated and trend[i] != trend_ok_val:
                _emit(i, STATE_INVALIDATED, REASON_TREND_CHANGED)
                state = None
                continue
            # 2. zone_crossed (atravessou a zona inteira)
            if is_long:
                crossed = c[i] < s_zlow
            else:
                crossed = c[i] > s_zhigh
            if crossed:
                _emit(i, STATE_INVALIDATED, REASON_ZONE_CROSSED)
                state = None
                continue
            # 3. confirm
            if s_confirm[i]:
                _emit(i, STATE_CONFIRMED)
                state = None
                continue
            # 4. timeout
            if i - pending_idx >= pending_timeout:
                _emit(i, STATE_INVALIDATED, REASON_TIMEOUT)
                state = None
                continue
            _emit(i, STATE_PENDING)
            continue

    out[COL_SETUP_ID] = pd.array(out_id, dtype='string')
    out[COL_SETUP_SIGNATURE] = pd.array(out_sig, dtype='string')
    out[COL_SETUP_STATE] = pd.array(out_state, dtype='string')
    out[COL_SETUP_DIRECTION] = pd.array(out_dir, dtype='string')
    out[COL_SETUP_ZONE_LOW] = out_zlow
    out[COL_SETUP_ZONE_HIGH] = out_zhigh
    out[COL_SETUP_INVALIDATION_REASON] = pd.array(out_reason, dtype='string')
    return out


def compute_setup_state_multi(
    df: pd.DataFrame,
    config: SetupConfig | None = None,
) -> pd.DataFrame:
    """FSM independente por assinatura selecionada (Bloco 1, G9).

    OBJETIVO
        Eliminar a starvation do slot único global: na FSM de
        `compute_setup_state` com múltiplas assinaturas, prioridade D3 +
        um-setup-ativo-por-vez + churn do G1 mascaram as assinaturas de
        prioridade >= 5 (medido em 2 anos, slot ocupado em 99% dos
        candles, 63–74% por setups de vida <= 1 candle; multi-9 vs solo:
        A10 24.564→1, A7 2.064→3, A6 678→0 — adendo G9). Aqui cada
        assinatura roda sua própria FSM (reuso: um `compute_setup_state`
        por sid com `signature=sid` e o mesmo restante do config) e as 7
        colunas de saída são anexadas sufixadas `__{sid}` (ex.:
        `setup_state__A3`). Sem arbitragem de prioridade — a decisão D3
        passa a ser do consumidor (camada IStrategy, wave futura).

    FONTE DE DADOS
        As mesmas colunas mergeadas de `compute_setup_state`, exigidas
        assinatura a assinatura (cada execução solo valida as suas).

    LIMITAÇÕES CONHECIDAS
        - N execuções da FSM (custo linear no nº de assinaturas).
        - Dentro de cada assinatura permanece um setup ativo por vez.
        - Sem colunas agregadas `setup_*` (sem sufixo): qualquer
          combinação entre assinaturas é decisão do consumidor.

    NÃO FAZER
        - Não arbitrar prioridade entre assinaturas aqui (D3 é do
          consumidor nesta função).
        - Não alterar `compute_setup_state` (a função antiga permanece
          intocada — princípio de regressão do Bloco 1).

    Args:
        df: DataFrame base 15m mergeado (ver FONTE DE DADOS do módulo).
        config: SetupConfig; `signature` (str ou sequência) define as
            assinaturas executadas. Se None, defaults (A3, confirmation).

    Returns:
        Cópia de `df` + 7 colunas por assinatura selecionada
        (`{col}__{sid}` para col em `SETUP_OUTPUT_COLUMNS`), na ordem de
        prioridade D3 (estável para layout de colunas, sem semântica).
    """
    if config is None:
        config = SetupConfig()
    out = df.copy()
    for sig in _resolve_signatures(config):
        res = compute_setup_state(df, replace(config, signature=sig.id))
        for col in SETUP_OUTPUT_COLUMNS:
            out[f'{col}__{sig.id}'] = res[col]
    return out
