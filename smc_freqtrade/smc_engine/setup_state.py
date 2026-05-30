"""Máquina de estados de setup SMC + assinatura A3 (Triple Confirmation).

OBJETIVO
    Implementar a máquina de estados de setup SMC (5 estados
    conceituais, 4 realizados em coluna) e a assinatura **A3 — Triple
    Confirmation (OB + FVG + Sweep)**, do tipo Continuação, consumindo
    contexto multi-timeframe (4H trend / 1H zona / 15m confirmação) já
    mergeado no DataFrame base.

    Primeira wave cujo output (`setup_state == 'CONFIRMED'`) é consumido
    por sinal de entrada de trade (Wave 10). Stateless: recebe o df
    (15m base + colunas `_4h`/`_1h`) e devolve o mesmo df + 6 colunas
    `setup_*`.

FONTE DE DADOS
    Colunas consumidas (sufixo conforme TF após merge `@informative`):
    - 4H: `swing_trend_bias_4h` (∈ {1, −1}; +1 ⇒ LONG, −1 ⇒ SHORT).
    - 1H (zona, promovida por zone_projection.py §S1):
      `active_{bull,bear}_swing_ob_{top,bottom,id}_1h`,
      `active_{bull,bear}_fvg_{top,bottom,id}_1h`.
    - 15m (base, sem sufixo): `sweep_{bullish,bearish}_{wick,retest}`,
      `choch_internal_{bullish,bearish}`, `open/high/low/close`.

    Predicados A3 conforme SMC_PRINCIPIOS_E_LEGADO.md §2-§3 e o briefing
    da Wave 9.5a §S4. Filtro de mitigação via `t_mitigation.notna()`
    (HOOKS §12.1) — codificado já na promoção de zona (§S1).

PREDICADO DE VELA DE REJEIÇÃO (§S3, inline — sem módulo)
    Não há detector formal de "vela de rejeição" no projeto. A fonte
    (§2.2) é qualitativa ("pavio direcional longo + close forte");
    operacionaliza-se aqui como quantitativo (divergência documentada):
    com `rng = high - low` (guarda `rng > 0`):
    - Rejeição bullish (LONG):
      `(min(open,close) - low)/rng >= rejection_wick_frac`  E
      `close >= low + rejection_close_frac * rng`.
    - Rejeição bearish (SHORT): simétrico
      `(high - max(open,close))/rng >= rejection_wick_frac`  E
      `close <= high - rejection_close_frac * rng`.

LIMITAÇÕES CONHECIDAS
    - `pending_timeout_candles = 16` é **decisão de engenharia**, não
      derivada de fonte (SMC_PRINCIPIOS §2.5 não numera "N candles
      15m"). Rationale: 16 × 15m = 4h = 1 candle macro 4H = 4 candles
      da zona 1H; acima da latência de formação do ChoCH 15m (~8-12
      candles, dado `pivot_internal_length=5`); abaixo da janela ARMED
      (24/6h). A tunar por backtest na Wave 9.5c.
    - `fvg_ob_adjacency_pct` é decisão de projeto (a fonte não numera
      adjacência OB↔FVG).
    - Predicado de rejeição: divergência qualitativo→quantitativo
      (acima).
    - A engine não expõe trend "neutro"; sem gate de neutro — direção é
      sempre +1 ou −1.
    - **RESOLVED fica FORA da coluna.** A engine é stateless por candle
      e não pode computar SL/TP hit sem lookahead (proibido —
      VERIFICACAO §3.2, SMC_PRINCIPIOS §5.3). RESOLVED é conceitual /
      ciclo de trade do Freqtrade. A coluna realiza 4 valores: ARMED,
      PENDING_CONFIRMATION, CONFIRMED, INVALIDATED.
    - Escopo do OB da zona = `swing` (D4). Apenas Confirmation Entry
      (D6); Risk Entry fora de escopo.
    - Modela **um** setup ativo por vez (FSM sequencial), re-armável
      após terminal (CONFIRMED/INVALIDATED). Breaker/IFVG, Premium/
      Discount e matcher declarativo ficam para a Wave 9.5b.

NÃO FAZER
    - Não usar `shift(-N)` (lookahead proibido).
    - Não importar `freqtrade` (engine é Python puro).
    - Não inchar `SMCConfig` — `SetupConfig` é dedicado.
    - Não mutar o df do caller (opera sobre cópia, só anexa colunas).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

import numpy as np
import pandas as pd

# === Valores de estado realizados na coluna (D2) ===
STATE_ARMED = 'ARMED'
STATE_PENDING = 'PENDING_CONFIRMATION'
STATE_CONFIRMED = 'CONFIRMED'
STATE_INVALIDATED = 'INVALIDATED'
SETUP_STATES = (STATE_ARMED, STATE_PENDING, STATE_CONFIRMED, STATE_INVALIDATED)

# === Direções (D2, minúscula) ===
DIRECTION_LONG = 'long'
DIRECTION_SHORT = 'short'

# === Razões de invalidação (D8, enum string) ===
REASON_ESCAPED = 'escaped'
REASON_TIMEOUT = 'timeout'
REASON_TREND_CHANGED = 'trend_changed'
REASON_ZONE_CROSSED = 'zone_crossed'
REASON_MITIGATED = 'mitigated'
INVALIDATION_REASONS = (
    REASON_ESCAPED, REASON_TIMEOUT, REASON_TREND_CHANGED,
    REASON_ZONE_CROSSED, REASON_MITIGATED,
)

# === Colunas de output (S5) ===
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
    """Configuração dedicada da máquina de estados de setup (Wave 9.5a).

    Não incha `SMCConfig` (D3). Defaults ancorados em SMC_PRINCIPIOS
    §2.5 onde a fonte numera, e em decisão de engenharia onde não numera
    (ver LIMITAÇÕES CONHECIDAS do módulo).
    """
    # Invalidação ARMED (SMC_PRINCIPIOS §2.5)
    armed_escape_pct: float = 0.02        # >2% além da zona sem entrar
    armed_timeout_candles: int = 24       # 6h em 15m, sem atividade
    # Invalidação PENDING
    pending_timeout_candles: int = 16     # N — decisão de engenharia
    # Catalisador / confirmação A3
    sweep_recency_candles: int = 16       # sweep válido nos últimos K candles
    fvg_ob_adjacency_pct: float = 0.003   # OB↔FVG adjacentes (decisão de projeto)
    rejection_wick_frac: float = 0.5      # pavio direcional >= 50% do range
    rejection_close_frac: float = 0.667   # close no terço favorável
    signature: str = 'A3'                 # hard-coded nesta wave
    # Sufixos de TF após o merge @informative (S1/D7)
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


def _make_setup_id(
    signature: str, direction: str, ob_id, fvg_id, t_armed,
) -> str:
    """Hash determinístico de (signature, direction, ob_id, fvg_id, t_armed).

    D5: string estável; permite que a 9.5b adicione assinaturas no mesmo
    OB sem colisão. sha1 truncado de uma f-string canônica.
    """
    ob_part = '' if ob_id is None else str(int(ob_id))
    fvg_part = '' if fvg_id is None else str(int(fvg_id))
    canonical = f'{signature}|{direction}|{ob_part}|{fvg_part}|{t_armed}'
    return hashlib.sha1(canonical.encode('utf-8')).hexdigest()[:16]


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


def _rolling_any(flag: np.ndarray, window: int) -> np.ndarray:
    """True em T se houver algum True na janela [T-window+1, T] (lookahead-safe)."""
    s = pd.Series(flag.astype('float64'))
    return (s.rolling(window, min_periods=1).max() > 0).to_numpy()


def compute_setup_state(
    df: pd.DataFrame,
    config: SetupConfig | None = None,
) -> pd.DataFrame:
    """Computa a máquina de estados A3 (Triple Confirmation) com MTF.

    Stateless (df in, df out — igual `analyze()`). Recebe o DataFrame
    base (15m) **já mergeado** com colunas `_4h` e `_1h` (incluindo as
    12 colunas de zona promovidas por `zone_projection.promote_active_zones`).
    Devolve o mesmo df + as 6 colunas `setup_*` (S5).

    A3 é Continuação: trend macro 4H + pullback à zona OB+FVG 1H + sweep
    catalisador recente + ChoCH 15m + vela de rejeição, na direção do
    trend. Fluxo: (vazio) → ARMED → PENDING_CONFIRMATION → CONFIRMED, com
    caminhos de INVALIDATED. Modela um setup ativo por vez, re-armável
    após terminal.

    Args:
        df: DataFrame base 15m mergeado (ver FONTE DE DADOS do módulo).
        config: SetupConfig. Se None, usa defaults.

    Returns:
        Cópia de `df` + 6 colunas (`SETUP_OUTPUT_COLUMNS`). `setup_state`
        ∈ {ARMED, PENDING_CONFIRMATION, CONFIRMED, INVALIDATED} ou <NA>;
        `setup_invalidation_reason` ∈ INVALIDATION_REASONS ou <NA>.
    """
    if config is None:
        config = SetupConfig()

    zs = config.zone_suffix
    ts = config.trend_suffix
    trend_col = f'swing_trend_bias_{ts}'
    # Colunas de zona 1H (promovidas em §S1).
    c_bull_ob_top = f'active_bull_swing_ob_top_{zs}'
    c_bull_ob_bot = f'active_bull_swing_ob_bottom_{zs}'
    c_bull_ob_id = f'active_bull_swing_ob_id_{zs}'
    c_bear_ob_top = f'active_bear_swing_ob_top_{zs}'
    c_bear_ob_bot = f'active_bear_swing_ob_bottom_{zs}'
    c_bear_ob_id = f'active_bear_swing_ob_id_{zs}'
    c_bull_fvg_top = f'active_bull_fvg_top_{zs}'
    c_bull_fvg_bot = f'active_bull_fvg_bottom_{zs}'
    c_bull_fvg_id = f'active_bull_fvg_id_{zs}'
    c_bear_fvg_top = f'active_bear_fvg_top_{zs}'
    c_bear_fvg_bot = f'active_bear_fvg_bottom_{zs}'
    c_bear_fvg_id = f'active_bear_fvg_id_{zs}'

    base_cols = [
        'open', 'high', 'low', 'close', 'date',
        'sweep_bullish_wick', 'sweep_bullish_retest',
        'sweep_bearish_wick', 'sweep_bearish_retest',
        'choch_internal_bullish', 'choch_internal_bearish',
    ]
    mtf_cols = [
        trend_col,
        c_bull_ob_top, c_bull_ob_bot, c_bull_ob_id,
        c_bear_ob_top, c_bear_ob_bot, c_bear_ob_id,
        c_bull_fvg_top, c_bull_fvg_bot, c_bull_fvg_id,
        c_bear_fvg_top, c_bear_fvg_bot, c_bear_fvg_id,
    ]
    _require_columns(df, base_cols + mtf_cols)

    n = len(df)
    out = df.copy()

    # --- arrays base ---
    o = df['open'].to_numpy(dtype='float64')
    h = df['high'].to_numpy(dtype='float64')
    low = df['low'].to_numpy(dtype='float64')
    c = df['close'].to_numpy(dtype='float64')
    dates = df['date'].to_numpy()
    trend = _float_col(df, trend_col)

    # zonas 1H (NaN quando não há zona ativa)
    bull_ob_top = _float_col(df, c_bull_ob_top)
    bull_ob_bot = _float_col(df, c_bull_ob_bot)
    bull_ob_id = _float_col(df, c_bull_ob_id)
    bear_ob_top = _float_col(df, c_bear_ob_top)
    bear_ob_bot = _float_col(df, c_bear_ob_bot)
    bear_ob_id = _float_col(df, c_bear_ob_id)
    bull_fvg_top = _float_col(df, c_bull_fvg_top)
    bull_fvg_bot = _float_col(df, c_bull_fvg_bot)
    bull_fvg_id = _float_col(df, c_bull_fvg_id)
    bear_fvg_top = _float_col(df, c_bear_fvg_top)
    bear_fvg_bot = _float_col(df, c_bear_fvg_bot)
    bear_fvg_id = _float_col(df, c_bear_fvg_id)

    choch_bull = df['choch_internal_bullish'].fillna(False).to_numpy(dtype='bool')
    choch_bear = df['choch_internal_bearish'].fillna(False).to_numpy(dtype='bool')

    # --- precompute sweep recency (rolling-any, lookahead-safe) ---
    sweep_bull = (
        df['sweep_bullish_wick'].fillna(False).to_numpy(dtype='bool')
        | df['sweep_bullish_retest'].fillna(False).to_numpy(dtype='bool')
    )
    sweep_bear = (
        df['sweep_bearish_wick'].fillna(False).to_numpy(dtype='bool')
        | df['sweep_bearish_retest'].fillna(False).to_numpy(dtype='bool')
    )
    bull_sweep_recent = _rolling_any(sweep_bull, config.sweep_recency_candles)
    bear_sweep_recent = _rolling_any(sweep_bear, config.sweep_recency_candles)

    # --- precompute rejeição (S3) ---
    rng = h - low
    safe = rng > 0
    with np.errstate(invalid='ignore', divide='ignore'):
        upper_body = np.minimum(o, c)
        lower_body = np.maximum(o, c)
        bull_wick_frac = np.where(safe, (upper_body - low) / rng, 0.0)
        bear_wick_frac = np.where(safe, (h - lower_body) / rng, 0.0)
    rej_bull = (
        safe
        & (bull_wick_frac >= config.rejection_wick_frac)
        & (c >= low + config.rejection_close_frac * rng)
    )
    rej_bear = (
        safe
        & (bear_wick_frac >= config.rejection_wick_frac)
        & (c <= h - config.rejection_close_frac * rng)
    )

    # --- output buffers ---
    out_id: list[str | None] = [None] * n
    out_state: list[str | None] = [None] * n
    out_dir: list[str | None] = [None] * n
    out_zlow = np.full(n, np.nan, dtype='float64')
    out_zhigh = np.full(n, np.nan, dtype='float64')
    out_reason: list[str | None] = [None] * n

    # --- estado da FSM (um setup ativo por vez) ---
    state: str | None = None
    s_dir = ''
    s_id = ''
    s_zlow = np.nan
    s_zhigh = np.nan
    s_ob_id = np.nan
    s_fvg_id = np.nan
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
            # ---- (vazio) → ARMED ----
            armed = False
            if trend[i] == 1.0 and not np.isnan(bull_ob_id[i]) \
                    and not np.isnan(bull_fvg_id[i]):
                ob_t, ob_b = bull_ob_top[i], bull_ob_bot[i]
                fv_t, fv_b = bull_fvg_top[i], bull_fvg_bot[i]
                ob_mid = (ob_t + ob_b) / 2.0
                overlap = (ob_b <= fv_t) and (fv_b <= ob_t)
                gap = max(fv_b - ob_t, ob_b - fv_t, 0.0)
                adjacent = overlap or (gap <= config.fvg_ob_adjacency_pct * ob_mid)
                if adjacent and low[i] > ob_t:
                    s_dir = DIRECTION_LONG
                    s_zlow, s_zhigh = ob_b, ob_t
                    s_ob_id, s_fvg_id = bull_ob_id[i], bull_fvg_id[i]
                    armed = True
            elif trend[i] == -1.0 and not np.isnan(bear_ob_id[i]) \
                    and not np.isnan(bear_fvg_id[i]):
                ob_t, ob_b = bear_ob_top[i], bear_ob_bot[i]
                fv_t, fv_b = bear_fvg_top[i], bear_fvg_bot[i]
                ob_mid = (ob_t + ob_b) / 2.0
                overlap = (ob_b <= fv_t) and (fv_b <= ob_t)
                gap = max(fv_b - ob_t, ob_b - fv_t, 0.0)
                adjacent = overlap or (gap <= config.fvg_ob_adjacency_pct * ob_mid)
                if adjacent and h[i] < ob_b:
                    s_dir = DIRECTION_SHORT
                    s_zlow, s_zhigh = ob_b, ob_t
                    s_ob_id, s_fvg_id = bear_ob_id[i], bear_fvg_id[i]
                    armed = True
            if armed:
                t_armed = dates[i]
                s_id = _make_setup_id(
                    config.signature, s_dir, s_ob_id, s_fvg_id, t_armed,
                )
                armed_idx = i
                state = STATE_ARMED
                _emit(i, STATE_ARMED)
            continue

        is_long = s_dir == DIRECTION_LONG
        trend_ok_val = 1.0 if is_long else -1.0

        if state == STATE_ARMED:
            cur_ob_id = bull_ob_id[i] if is_long else bear_ob_id[i]
            cur_fvg_id = bull_fvg_id[i] if is_long else bear_fvg_id[i]
            # 1. trend_changed
            if trend[i] != trend_ok_val:
                _emit(i, STATE_INVALIDATED, REASON_TREND_CHANGED)
                state = None
                continue
            # 2. mitigated (zona OB/FVG sumiu ou trocou de id)
            mitigated = (
                np.isnan(cur_ob_id) or np.isnan(cur_fvg_id)
                or cur_ob_id != s_ob_id or cur_fvg_id != s_fvg_id
            )
            if mitigated:
                _emit(i, STATE_INVALIDATED, REASON_MITIGATED)
                state = None
                continue
            # 3. intersecta zona → PENDING
            if low[i] <= s_zhigh and h[i] >= s_zlow:
                pending_idx = i
                state = STATE_PENDING
                _emit(i, STATE_PENDING)
                continue
            # 4. escaped
            if is_long:
                escaped = low[i] > s_zhigh * (1.0 + config.armed_escape_pct)
            else:
                escaped = h[i] < s_zlow * (1.0 - config.armed_escape_pct)
            if escaped:
                _emit(i, STATE_INVALIDATED, REASON_ESCAPED)
                state = None
                continue
            # 5. timeout
            if i - armed_idx >= config.armed_timeout_candles:
                _emit(i, STATE_INVALIDATED, REASON_TIMEOUT)
                state = None
                continue
            _emit(i, STATE_ARMED)
            continue

        if state == STATE_PENDING:
            # 1. trend_changed
            if trend[i] != trend_ok_val:
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
            # 3. confirm (Triple Confirmation: ChoCH + rejeição + sweep recente)
            if is_long:
                confirm = choch_bull[i] and rej_bull[i] and bull_sweep_recent[i]
            else:
                confirm = choch_bear[i] and rej_bear[i] and bear_sweep_recent[i]
            if confirm:
                _emit(i, STATE_CONFIRMED)
                state = None
                continue
            # 4. timeout
            if i - pending_idx >= config.pending_timeout_candles:
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
