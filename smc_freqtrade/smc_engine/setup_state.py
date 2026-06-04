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

NÃO FAZER
    - Não usar `shift(-N)` (lookahead proibido).
    - Não importar `freqtrade` (engine é Python puro).
    - Não inchar `SMCConfig` — `SetupConfig` é dedicado.
    - Não mutar o df do caller (opera sobre cópia, só anexa colunas).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
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

# === Ids de assinatura válidos (D3, ordem de prioridade) ===
# A3 > A2 > A4a > A5 > A1 > A9 > A6 > A7 > A10 (qualidade de evidência).
# Decide só o empate "duas armam no mesmo candle"; é revisável (o backtest
# da Wave 10 isola por assinatura — §3.5/§6). A 9.5e APENDA A7 (prioridade
# 7) e A10 (8) — prioridades 0–6 das existentes ficam intactas (D4).
_VALID_SIGNATURE_IDS = ('A3', 'A2', 'A4a', 'A5', 'A1', 'A9', 'A6', 'A7', 'A10')

# === Colunas de output ===
COL_SETUP_ID = 'setup_id'
COL_SETUP_STATE = 'setup_state'
COL_SETUP_DIRECTION = 'setup_direction'
COL_SETUP_ZONE_LOW = 'setup_zone_low'
COL_SETUP_ZONE_HIGH = 'setup_zone_high'
COL_SETUP_INVALIDATION_REASON = 'setup_invalidation_reason'
SETUP_OUTPUT_COLUMNS = (
    COL_SETUP_ID,
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
        for kind in sig.required_kinds:
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
    `zone_projection.promote_active_zones`. Devolve o mesmo df + as 6
    colunas `setup_*`.

    A FSM itera as assinaturas selecionadas em `config.signature` (default
    A3) por prioridade D3 e, num candle sem setup ativo, arma a primeira
    elegível. Fluxo `confirmation`: ARMED → PENDING_CONFIRMATION →
    CONFIRMED, com caminhos de INVALIDATED. Fluxo `risk` (D2): ARMED →
    CONFIRMED direto na interseção da zona (sem PENDING). Modela um setup
    ativo por vez, re-armável após terminal.

    Args:
        df: DataFrame base 15m mergeado (ver FONTE DE DADOS do módulo).
        config: SetupConfig. Se None, usa defaults (A3, confirmation).

    Returns:
        Cópia de `df` + 6 colunas (`SETUP_OUTPUT_COLUMNS`).

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

    # Precompute, por assinatura e direção, os arrays de zona/arm/confirm.
    # prec: list de (Signature, dir_arr, {direction: (zlow, zhigh, anch, arm, conf)}).
    prec = []
    for sig in signatures:
        dir_arr = sig.direction_fn(A)
        per = {}
        for d in (DIRECTION_LONG, DIRECTION_SHORT):
            zlow, zhigh, anch = sig.zone_fn(A, d)
            arm = sig.arm_fn(A, d)
            conf = sig.confirm_fn(A, d)
            per[d] = (zlow, zhigh, anch, arm, conf)
        prec.append((sig, dir_arr, per))

    # --- output buffers ---
    out_id: list[str | None] = [None] * n
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
            # 2. mitigated (qualquer âncora NaN ou diferente da capturada)
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
    out[COL_SETUP_STATE] = pd.array(out_state, dtype='string')
    out[COL_SETUP_DIRECTION] = pd.array(out_dir, dtype='string')
    out[COL_SETUP_ZONE_LOW] = out_zlow
    out[COL_SETUP_ZONE_HIGH] = out_zhigh
    out[COL_SETUP_INVALIDATION_REASON] = pd.array(out_reason, dtype='string')
    return out
