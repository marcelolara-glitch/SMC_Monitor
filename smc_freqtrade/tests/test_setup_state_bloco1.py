"""Bloco 1 (Briefing 2) — correções estruturais da FSM: G1/G2/G3/G5/G9.

OBJETIVO
    T1–T8 do briefing: regressão byte-idêntica com defaults (T1),
    mecanismos novos exercitados em sintéticos determinísticos (T2, T4,
    T5, T6, T7) e três asserts **por construção** sobre o golden 3-TF
    (T3: 0 armações além de `prox`; T6b: 0 `mitigated` em `frozen_band`;
    T8: multi == solo por assinatura).

FONTE DE DADOS
    Sintéticos scriptados à mão (esperado anotado independente da engine,
    padrão de test_setup_state_9_5b.py) + goldens reais em
    tests/golden/data/btc_usdt_swap_{4h,1h,15m}_window.csv com o pipeline
    da Fase A (analyze ×3 + tag_sessions + align_informative).

LIMITAÇÕES CONHECIDAS
    O baseline de T1 (digest + contadores) foi capturado do código
    pré-Bloco 1 (main @ 88cae16) neste mesmo pipeline; os contadores
    reproduzem exatamente a tabela §3 do
    docs/RELATORIO_FASE_A_PARTE2_FIDELIDADE.md. O digest depende da
    serialização `to_csv(float_format='%.10g')` — estável para o pandas
    pinado; se o pin mudar, regerar com o snippet no docstring de
    `test_t1_default_regression_digest`.

NÃO FAZER
    Não gerar a fixture esperada dos sintéticos com o próprio
    `compute_setup_state`; não medir P&L (fora do escopo da wave).
"""
from __future__ import annotations

import hashlib

import numpy as np
import pandas as pd
import pytest

from smc_engine import (
    analyze,
    compute_setup_state,
    SetupConfig,
    STATE_ARMED,
    STATE_PENDING,
    STATE_CONFIRMED,
    STATE_INVALIDATED,
    REASON_ESCAPED,
    REASON_MITIGATED,
    DIRECTION_LONG,
)
from smc_engine.sessions import tag_sessions
from smc_engine.setup_state import (
    SETUP_OUTPUT_COLUMNS,
    compute_setup_state_multi,
)
from tools.mtf_align import align_informative

from .test_smoke_wave9_5b_golden import GOLDEN_DIR, _load_ohlcv

# Ordem D3 completa (as 9 assinaturas).
ALL_SIGS = ('A3', 'A2', 'A4a', 'A5', 'A1', 'A9', 'A6', 'A7', 'A10')

# ============================================================
# Baseline T1 — capturado do código pré-Bloco 1 (main @ 88cae16) sobre o
# golden 3-TF com o pipeline da Fase A (tag_sessions + align_informative).
# Os contadores por assinatura reproduzem a tabela §3 do
# RELATORIO_FASE_A_PARTE2_FIDELIDADE.md (ex.: A1 4.191 setups / escaped
# 4.162; 1 único CONFIRMED no universo, da A4a).
# ============================================================
_BASELINE_DEFAULT_DIGEST = (
    '525410f282297e60f3ff62ae65eaca2a31f82dc35b395987cad61da437d24349'
)
# sid → (n_setups, n_confirmed, n_mitigated) em solo/confirmation/default.
_BASELINE_SOLO = {
    'A3': (484, 0, 1),
    'A2': (3113, 0, 5),
    'A4a': (2392, 1, 44),
    'A5': (118, 0, 0),
    'A1': (4191, 0, 3),
    'A9': (3541, 0, 6),
    'A6': (17, 0, 2),
    'A7': (281, 0, 18),
    'A10': (3179, 0, 12),
}


# ============================================================
# Fixtures golden (module scope — pipeline caro, computado uma vez)
# ============================================================

@pytest.fixture(scope='module')
def merged_golden() -> pd.DataFrame:
    """Golden 15m mergeado com 1h/4h + killzones (pipeline da Fase A)."""
    r4 = analyze(_load_ohlcv('btc_usdt_swap_4h_window.csv'))
    r1 = analyze(_load_ohlcv('btc_usdt_swap_1h_window.csv'))
    r15 = analyze(_load_ohlcv('btc_usdt_swap_15m_window.csv'))
    base15 = tag_sessions(r15.df)
    merged = align_informative(base15, r1.df, '15m', '1h', suffix='1h')
    merged = align_informative(merged, r4.df, '15m', '4h', suffix='4h')
    return merged


@pytest.fixture(scope='module')
def solo_default_runs(merged_golden) -> dict[str, pd.DataFrame]:
    """Execução solo (config default) por assinatura — base de T1/T8."""
    return {
        sid: compute_setup_state(merged_golden, SetupConfig(signature=sid))
        for sid in ALL_SIGS
    }


def _n_setups(res: pd.DataFrame, col: str = 'setup_id') -> int:
    return int(res[col].dropna().nunique())


# ============================================================
# Helpers sintéticos (padrão test_setup_state_9_5b)
# ============================================================

OB_TOP, OB_BOT, OB_ID = 102.0, 100.0, 5

_DEFAULTS = {
    'swing_trend_bias_4h': 1.0,
    'active_bull_swing_ob_top_1h': np.nan,
    'active_bull_swing_ob_bottom_1h': np.nan,
    'active_bull_swing_ob_id_1h': np.nan,
    'active_bull_swing_ob_volume_pct_1h': np.nan,
    'active_bear_swing_ob_top_1h': np.nan,
    'active_bear_swing_ob_bottom_1h': np.nan,
    'active_bear_swing_ob_id_1h': np.nan,
    'active_bear_swing_ob_volume_pct_1h': np.nan,
    'sweep_bullish_wick': False,
    'sweep_bullish_retest': False,
    'sweep_bearish_wick': False,
    'sweep_bearish_retest': False,
    'sweep_bullish_level_price': np.nan,
    'sweep_bearish_level_price': np.nan,
    'choch_internal_bullish': False,
    'choch_internal_bearish': False,
}

_ALL_COLS = ['open', 'high', 'low', 'close'] + list(_DEFAULTS)


def _build(rows: list[dict]) -> pd.DataFrame:
    n = len(rows)
    data: dict[str, list] = {c: [] for c in _ALL_COLS}
    for row in rows:
        for c in ('open', 'high', 'low', 'close'):
            data[c].append(row[c])
        for c, d in _DEFAULTS.items():
            data[c].append(row.get(c, d))
    df = pd.DataFrame(data)
    df['date'] = pd.date_range('2026-03-01', periods=n, freq='15min', tz='UTC')
    return df


def _cdl(low, high, close, open_=None, **overrides) -> dict:
    row = {
        'open': close if open_ is None else open_,
        'high': high, 'low': low, 'close': close,
    }
    row.update(overrides)
    return row


def _states(res: pd.DataFrame) -> list:
    return [s if pd.notna(s) else None for s in res['setup_state']]


def _reasons(res: pd.DataFrame) -> list:
    return [r if pd.notna(r) else None
            for r in res['setup_invalidation_reason']]


_OB_LONG = {
    'active_bull_swing_ob_top_1h': OB_TOP,
    'active_bull_swing_ob_bottom_1h': OB_BOT,
    'active_bull_swing_ob_id_1h': float(OB_ID),
}


# ============================================================
# T1 — regressão: defaults ⇒ byte-idêntico ao pré-Bloco 1
# ============================================================

def test_t1_default_regression_digest(merged_golden) -> None:
    """Config default no golden: digest das 7 colunas == baseline pré-Bloco 1.

    Regerar (só se o pin de pandas mudar): rodar o pipeline da fixture no
    commit base e `sha256(res[SETUP_OUTPUT_COLUMNS].to_csv(index=False,
    float_format='%.10g'))`.
    """
    res = compute_setup_state(merged_golden)
    payload = res[list(SETUP_OUTPUT_COLUMNS)].to_csv(
        index=False, float_format='%.10g',
    )
    digest = hashlib.sha256(payload.encode('utf-8')).hexdigest()
    assert digest == _BASELINE_DEFAULT_DIGEST


def test_t1_default_regression_solo_counters(solo_default_runs) -> None:
    """Contadores solo por assinatura (default) == baseline pré-Bloco 1
    (== tabela §3 do relatório da Fase A Parte 2)."""
    for sid, (n_setups, n_conf, n_mit) in _BASELINE_SOLO.items():
        res = solo_default_runs[sid]
        assert _n_setups(res) == n_setups, sid
        assert int((res['setup_state'] == STATE_CONFIRMED).sum()) == n_conf, sid
        assert int(
            (res['setup_invalidation_reason'] == REASON_MITIGATED).sum()
        ) == n_mit, sid


# ============================================================
# T2 — G1: zona a 5% com prox=0.02 não arma; a 1% arma
# ============================================================

def test_t2_proximity_gate_blocks_far_arms_near() -> None:
    cfg = SetupConfig(signature='A1', arming_proximity_pct=0.02)
    # 5% além do topo da zona (zhigh=102 → low=107.1) → não arma.
    far = _build([{**_cdl(107.1, 108.0, 107.5), **_OB_LONG}])
    res = compute_setup_state(far, cfg)
    assert _states(res) == [None]
    # 1% (low=103.02 <= 102*1.02=104.04) → arma.
    near = _build([{**_cdl(103.02, 104.0, 103.5), **_OB_LONG}])
    res = compute_setup_state(near, cfg)
    assert _states(res) == [STATE_ARMED]
    # Sem o gate (default None), o mesmo candle distante arma (legado).
    res = compute_setup_state(far, SetupConfig(signature='A1'))
    assert _states(res) == [STATE_ARMED]


# ============================================================
# T3 — G1 por construção: golden, 9 assinaturas, prox=0.02 ⇒
#       distância de armação > prox em 0 setups
# ============================================================

def test_t3_golden_no_arming_beyond_prox(merged_golden) -> None:
    prox = 0.02
    res = compute_setup_state(
        merged_golden,
        SetupConfig(signature=ALL_SIGS, arming_proximity_pct=prox),
    )
    active = res.dropna(subset=['setup_id'])
    assert len(active) > 0
    first = active.groupby('setup_id', sort=False).head(1)
    assert (first['setup_state'] == STATE_ARMED).all()
    is_long = first['setup_direction'] == DIRECTION_LONG
    # Mesma aritmética do gate (normalizada pela borda da zona):
    # long  `low <= zhigh*(1+prox)` ⇔ (low - zhigh)/zhigh <= prox;
    # short `high >= zlow*(1-prox)` ⇔ (zlow - high)/zlow <= prox.
    dist_long = first['low'] / first['setup_zone_high'] - 1.0
    dist_short = 1.0 - first['high'] / first['setup_zone_low']
    dist = np.where(is_long, dist_long, dist_short)
    n_beyond = int((dist > prox + 1e-12).sum())
    assert n_beyond == 0, f'{n_beyond} setups armados além de prox'


# ============================================================
# T4 — G1 + escape: armado a 1%, preço afasta para 3% → escaped
# ============================================================

def test_t4_escape_measures_post_arming_flight() -> None:
    cfg = SetupConfig(signature='A1', arming_proximity_pct=0.02)
    rows = [
        {**_cdl(103.0, 104.0, 103.5), **_OB_LONG},    # ~1% → ARMED
        {**_cdl(105.06, 106.0, 105.5), **_OB_LONG},   # ~3% > 104.04 → escaped
    ]
    res = compute_setup_state(_build(rows), cfg)
    assert _states(res) == [STATE_ARMED, STATE_INVALIDATED]
    assert _reasons(res)[1] == REASON_ESCAPED


# ============================================================
# T5 — G2: ChoCH puro confirma com trigger='choch'; não no legado
# ============================================================

# Candle de ChoCH sem forma de rejeição (corpo cheio, pavio inferior 10%).
_CHOCH_NO_REJ = _cdl(100.0, 102.0, 101.9, open_=100.2,
                     choch_internal_bullish=True)


def test_t5_choch_trigger_confirms_pure_mss() -> None:
    rows = [
        {**_cdl(103.0, 104.0, 103.5), **_OB_LONG},           # ARMED
        {**_cdl(101.5, 103.0, 102.5), **_OB_LONG},           # → PENDING
        {**_CHOCH_NO_REJ, **_OB_LONG},                       # ChoCH puro
    ]
    df = _build(rows)
    # trigger='choch' → CONFIRMED no candle do ChoCH.
    res = compute_setup_state(
        df, SetupConfig(signature='A1', confirmation_trigger='choch'),
    )
    assert _states(res) == [STATE_ARMED, STATE_PENDING, STATE_CONFIRMED]
    # Legado (ChoCH ∧ rejeição no mesmo candle) → segue PENDING.
    res = compute_setup_state(df, SetupConfig(signature='A1'))
    assert _states(res) == [STATE_ARMED, STATE_PENDING, STATE_PENDING]


def test_t5_choch_trigger_keeps_sweep_premise_on_a2() -> None:
    """Mapeamento G2: A2 (premissa de sweep) usa MSS ∧ sweep_recent —
    ChoCH com sweep já fora da janela NÃO confirma."""
    sweep0 = {'sweep_bullish_wick': True,
              'sweep_bullish_level_price': 99.0}
    rows = [
        {**_cdl(103.0, 104.0, 103.5), **sweep0, **_OB_LONG},  # sweep + ARMED
        {**_cdl(101.5, 103.0, 102.5), **_OB_LONG},            # → PENDING
        {**_CHOCH_NO_REJ, **_OB_LONG},                        # sweep velho
    ]
    df = _build(rows)
    cfg = SetupConfig(
        signature='A2', confirmation_trigger='choch',
        sweep_recency_candles=2,
    )
    res = compute_setup_state(df, cfg)
    # No candle 2 a janela de recência (2) já não cobre o sweep do candle
    # 0 → MSS ∧ sweep falha → permanece PENDING.
    assert _states(res) == [STATE_ARMED, STATE_PENDING, STATE_PENDING]


# ============================================================
# T6 — G3: troca do id promovido com zona original viva
# ============================================================

def test_t6_frozen_band_survives_promoted_id_swap() -> None:
    ob_swapped = {**_OB_LONG, 'active_bull_swing_ob_id_1h': 6.0}
    rows = [
        {**_cdl(103.0, 104.0, 103.5), **_OB_LONG},     # ARMED (id=5)
        {**_cdl(103.0, 104.0, 103.5), **ob_swapped},   # id=5→6, banda igual
    ]
    df = _build(rows)
    # Legado ('promoted_id'): troca de id → mitigated (o rótulo espúrio).
    res = compute_setup_state(df, SetupConfig(signature='A1'))
    assert _states(res) == [STATE_ARMED, STATE_INVALIDATED]
    assert _reasons(res)[1] == REASON_MITIGATED
    # 'frozen_band': a banda congelada segue vigiada → setup sobrevive.
    res = compute_setup_state(
        df, SetupConfig(signature='A1', anchor_invalidation='frozen_band'),
    )
    assert _states(res) == [STATE_ARMED, STATE_ARMED]


def test_t6b_golden_frozen_band_zero_mitigated(merged_golden) -> None:
    """T6b por construção: golden, 9 assinaturas, frozen_band ⇒
    contagem de `mitigated` == 0 (as demais razões seguem emitidas)."""
    res = compute_setup_state(
        merged_golden,
        SetupConfig(signature=ALL_SIGS, anchor_invalidation='frozen_band'),
    )
    reasons = res['setup_invalidation_reason'].dropna()
    assert int((reasons == REASON_MITIGATED).sum()) == 0
    assert len(reasons) > 0
    assert _n_setups(res) > 0


# ============================================================
# T7 — G5: banda do sweep e armação sem coluna de OB
# ============================================================

def test_t7_a9_sweep_band_arms_without_ob_columns() -> None:
    evt = {'sweep_bullish_wick': True, 'sweep_bullish_level_price': 100.0}
    rows = [
        {**_cdl(99.0, 101.0, 100.5), **evt},   # evento: banda=[99, 100]
        _cdl(100.5, 101.5, 101.0),             # fora da banda → arma
    ]
    df = _build(rows)
    # SEM qualquer coluna de OB no frame.
    df = df.drop(columns=[c for c in df.columns if 'swing_ob' in c])
    res = compute_setup_state(
        df, SetupConfig(signature='A9', a9_variant='sweep_band'),
    )
    assert _states(res) == [None, STATE_ARMED]
    assert res['setup_direction'].iloc[1] == DIRECTION_LONG
    # Banda == [low_evt, level_price] (bull).
    assert res['setup_zone_low'].iloc[1] == 99.0
    assert res['setup_zone_high'].iloc[1] == 100.0
    # Contraste: a A9 legada exige as colunas de OB neste mesmo frame.
    with pytest.raises(ValueError, match='swing_ob'):
        compute_setup_state(df, SetupConfig(signature='A9'))


# ============================================================
# T8 — G9 por construção: multi == solo por assinatura (golden)
# ============================================================

def test_t8_multi_equals_solo_per_signature(
    merged_golden, solo_default_runs,
) -> None:
    multi = compute_setup_state_multi(
        merged_golden, SetupConfig(signature=ALL_SIGS),
    )
    for sid in ALL_SIGS:
        for col in SETUP_OUTPUT_COLUMNS:
            assert f'{col}__{sid}' in multi.columns, f'{col}__{sid}'
        n_multi = _n_setups(multi, f'setup_id__{sid}')
        n_solo = _n_setups(solo_default_runs[sid])
        assert n_multi == n_solo, f'{sid}: multi {n_multi} != solo {n_solo}'
        # Starvation zero, ancorado no baseline absoluto (não só relativo).
        assert n_multi == _BASELINE_SOLO[sid][0], sid


# ============================================================
# Validação dos campos novos do SetupConfig
# ============================================================

def test_new_config_fields_validated() -> None:
    with pytest.raises(ValueError, match='arming_proximity_pct'):
        SetupConfig(arming_proximity_pct=0.0)
    with pytest.raises(ValueError, match='arming_proximity_pct'):
        SetupConfig(arming_proximity_pct=1.5)
    with pytest.raises(ValueError, match='confirmation_trigger'):
        SetupConfig(confirmation_trigger='nope')
    with pytest.raises(ValueError, match='anchor_invalidation'):
        SetupConfig(anchor_invalidation='nope')
    with pytest.raises(ValueError, match='a9_variant'):
        SetupConfig(a9_variant='nope')


def test_new_defaults_equal_explicit_legacy() -> None:
    """Defaults implícitos == valores legados explícitos (frame-equal)."""
    rows = [
        {**_cdl(103.0, 104.0, 103.5), **_OB_LONG},
        {**_cdl(101.5, 103.0, 102.5), **_OB_LONG},
    ]
    df = _build(rows)
    default = compute_setup_state(df, SetupConfig(signature='A1'))
    explicit = compute_setup_state(df, SetupConfig(
        signature='A1',
        arming_proximity_pct=None,
        confirmation_trigger='legacy',
        anchor_invalidation='promoted_id',
        a9_variant='legacy_ob',
    ))
    pd.testing.assert_frame_equal(default, explicit)
