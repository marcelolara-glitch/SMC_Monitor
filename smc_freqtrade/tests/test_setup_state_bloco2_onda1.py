"""Bloco 2 / Onda 1 — displacement como gate de confirmação (§2.6-i).

OBJETIVO
    T-D1–T-D5 do briefing: regressão byte-idêntica com defaults (T-D1,
    padrão do T1 do Bloco 1), fórmula Pine §10.5 em sintéticos
    determinísticos (T-D2), composição do gate na FSM (T-D3) e dois
    asserts por construção sobre o golden 3-TF: todo CONFIRMED com o
    gate on é displaced na direção do setup (T-D4) e o modo risk é
    inerte ao gate (T-D5).

FONTE DE DADOS
    Sintéticos scriptados à mão (esperado anotado independente da
    engine) reusando os helpers de test_setup_state_bloco1 + goldens
    reais em tests/golden/data com o pipeline da Fase A (fixture
    `merged_golden` importada do módulo do Bloco 1).

LIMITAÇÕES CONHECIDAS
    Os contadores absolutos de T-D4 (86 → 40 CONFIRMED, disp 1.135
    bull / 1.167 bear em 11.520 candles) foram medidos no golden 15m
    com a configuração Bloco-1-ON do briefing (prox=0.02, trigger
    'choch', frozen_band, sweep_band, G9 multi) e reproduzem os números
    do Briefing Bloco 2 / Onda 1 §0.

NÃO FAZER
    Não gerar a fixture esperada dos sintéticos com o próprio
    `compute_setup_state`; não testar aqui a regra ii do §2.6 (OB
    estratégico — Onda 3).
"""
from __future__ import annotations

import hashlib

import numpy as np
import pandas as pd
import pytest

from smc_engine import (
    compute_setup_state,
    SetupConfig,
    STATE_ARMED,
    STATE_PENDING,
    STATE_CONFIRMED,
)
from smc_engine.setup_state import (
    DIRECTION_LONG,
    DIRECTION_SHORT,
    ENTRY_MODE_RISK,
    SETUP_OUTPUT_COLUMNS,
    _displacement_flags,
    compute_setup_state_multi,
)

# Reuso deliberado do módulo do Bloco 1: baseline de regressão, ordem
# D3 completa, helpers sintéticos e a fixture golden (importar uma
# função decorada com @pytest.fixture a registra neste módulo).
from .test_setup_state_bloco1 import (
    ALL_SIGS,
    _BASELINE_DEFAULT_DIGEST,
    _OB_LONG,
    _build,
    _cdl,
    _states,
    merged_golden,  # noqa: F401 (fixture)
)

# Configuração Bloco-1-ON do briefing (§0): os 4 mecanismos ligados.
_BLOCO1_ON = dict(
    arming_proximity_pct=0.02,
    confirmation_trigger='choch',
    anchor_invalidation='frozen_band',
    a9_variant='sweep_band',
)

# Baselines medidos no golden 15m (11.520 candles) — Briefing §0.
_GOLDEN_DISP_BULL = 1135
_GOLDEN_DISP_BEAR = 1167
_GOLDEN_CONFIRMED_GATE_OFF = 86
_GOLDEN_CONFIRMED_GATE_ON = 40


# ============================================================
# T-D1 — regressão: defaults ⇒ digest idêntico ao baseline do Bloco 1
# ============================================================

def test_td1_default_regression_digest(merged_golden) -> None:
    """Config default (gate off) no golden: digest das 7 colunas ==
    baseline pré-Bloco 1 (o MESMO hash do T1 do Bloco 1)."""
    res = compute_setup_state(merged_golden)
    payload = res[list(SETUP_OUTPUT_COLUMNS)].to_csv(
        index=False, float_format='%.10g',
    )
    digest = hashlib.sha256(payload.encode('utf-8')).hexdigest()
    assert digest == _BASELINE_DEFAULT_DIGEST


def test_td1_explicit_off_equals_default() -> None:
    """Gate 'off' explícito (com os demais campos novos explícitos) ==
    default (frame-equal)."""
    rows = [
        {**_cdl(103.0, 104.0, 103.5), **_OB_LONG},
        {**_cdl(101.5, 103.0, 102.5), **_OB_LONG},
    ]
    df = _build(rows)
    default = compute_setup_state(df, SetupConfig(signature='A1'))
    explicit = compute_setup_state(df, SetupConfig(
        signature='A1',
        displacement_gate='off',
        displacement_body_len=10,
        displacement_wick_frac=0.36,
    ))
    pd.testing.assert_frame_equal(default, explicit)


# ============================================================
# T-D2 — fórmula (Pine §10.5) em sintéticos determinísticos
# ============================================================

def _flags(o, h, low, c, body_len=10, wick_frac=0.36):
    return _displacement_flags(
        np.asarray(o, dtype='float64'), np.asarray(h, dtype='float64'),
        np.asarray(low, dtype='float64'), np.asarray(c, dtype='float64'),
        body_len, wick_frac,
    )


def _base_bull(n=10):
    """n candles bull de corpo 1.0 e wicks ~0 (aquecem a SMA)."""
    return ([100.0] * n, [101.05] * n, [99.99] * n, [101.0] * n)


def test_td2_bull_displacement_and_strict_mean() -> None:
    o, h, low, c = _base_bull()
    # Candle 10: corpo 5 > SMA (1,4), wicks 0,5/0,1 < 0,36*5=1,8; c>o.
    o += [100.0]; c += [105.0]; h += [105.5]; low += [99.9]
    db, ds = _flags(o, h, low, c)
    assert db[10] and not ds[10]
    # Candle 9: corpo 1,0 == SMA 1,0 → comparação estrita ⇒ False.
    assert not db[9]
    # Aquecimento (SMA indefinida) ⇒ False em 0..8.
    assert not db[:9].any() and not ds.any()


def test_td2_upper_wick_40pct_fails() -> None:
    o, h, low, c = _base_bull()
    # Corpo 5, wick superior 2,0 = 40% do corpo (>= 36%) ⇒ False.
    o += [100.0]; c += [105.0]; h += [107.0]; low += [99.9]
    db, ds = _flags(o, h, low, c)
    assert not db[10] and not ds[10]


def test_td2_body_below_mean_fails() -> None:
    o, h, low, c = _base_bull()
    # Corpo 0,5 < SMA 0,95, wicks pequenos ⇒ False.
    o += [100.0]; c += [100.5]; h += [100.51]; low += [99.99]
    db, ds = _flags(o, h, low, c)
    assert not db[10] and not ds[10]


def test_td2_doji_fails() -> None:
    o, h, low, c = _base_bull()
    # body == 0 ⇒ não-displacement (wicks < 0*frac é impossível; c>o falha).
    o += [100.0]; c += [100.0]; h += [100.5]; low += [99.5]
    db, ds = _flags(o, h, low, c)
    assert not db[10] and not ds[10]


def test_td2_sma_undefined_ninth_candle_fails() -> None:
    # Candle 9 (índice 8): SMA(10) indefinida ⇒ False mesmo com forma
    # de displacement perfeita.
    o, h, low, c = _base_bull(8)
    o += [100.0]; c += [110.0]; h += [110.1]; low += [99.9]
    db, ds = _flags(o, h, low, c)
    assert not db.any() and not ds.any()
    # O MESMO candle no índice 9 (primeira janela cheia) ⇒ True — a
    # negativa acima vem da SMA indefinida, não da forma.
    o2, h2, low2, c2 = _base_bull(9)
    o2 += [100.0]; c2 += [110.0]; h2 += [110.1]; low2 += [99.9]
    db2, _ = _flags(o2, h2, low2, c2)
    assert db2[9]


def test_td2_bearish_symmetry() -> None:
    # Espelho do caso bull: candles base bear + displacement bear.
    n = 10
    o = [101.0] * n; c = [100.0] * n; h = [101.01] * n; low = [99.95] * n
    o += [105.0]; c += [100.0]; h += [105.1]; low += [99.9]
    db, ds = _flags(o, h, low, c)
    assert ds[10] and not db[10]
    assert not ds[:10].any()


# ============================================================
# T-D3 — composição: gate na FSM (PENDING sintético)
# ============================================================

# Candle de ChoCH bull SEM displacement (corpo 0,1; wick superior 1,6).
_CHOCH_NOT_DISPLACED = _cdl(
    100.0, 102.6, 101.0, open_=100.9, choch_internal_bullish=True,
)
# Candle de ChoCH bull displaced (corpo 1,0; wicks 0,1 < 0,36).
_CHOCH_DISPLACED = _cdl(
    100.9, 102.1, 102.0, open_=101.0, choch_internal_bullish=True,
)


def _pending_rows(final_row: dict) -> pd.DataFrame:
    rows = [
        {**_cdl(103.0, 104.0, 103.5), **_OB_LONG},   # ARMED
        {**_cdl(101.5, 103.0, 102.5), **_OB_LONG},   # → PENDING
        {**final_row, **_OB_LONG},                   # candidato a confirmar
    ]
    return _build(rows)


def test_td3_choch_trigger_gated_by_displacement() -> None:
    df = _pending_rows(_CHOCH_NOT_DISPLACED)
    # Gate off: MSS puro confirma.
    res = compute_setup_state(df, SetupConfig(
        signature='A1', confirmation_trigger='choch',
    ))
    assert _states(res) == [STATE_ARMED, STATE_PENDING, STATE_CONFIRMED]
    # Gate on: ChoCH não-displaced NÃO confirma.
    res = compute_setup_state(df, SetupConfig(
        signature='A1', confirmation_trigger='choch',
        displacement_gate='confirm', displacement_body_len=2,
    ))
    assert _states(res) == [STATE_ARMED, STATE_PENDING, STATE_PENDING]


def test_td3_choch_trigger_confirms_displaced() -> None:
    df = _pending_rows(_CHOCH_DISPLACED)
    res = compute_setup_state(df, SetupConfig(
        signature='A1', confirmation_trigger='choch',
        displacement_gate='confirm', displacement_body_len=2,
    ))
    assert _states(res) == [STATE_ARMED, STATE_PENDING, STATE_CONFIRMED]


def test_td3_legacy_trigger_requires_choch_rej_disp() -> None:
    """`legacy` + gate on ⇒ ChoCH ∧ rejeição ∧ displacement."""
    # Hammer: rejeição bull válida (wick inferior 87% do range, close no
    # topo) + ChoCH, mas corpo 0,2 com wick 2,8 ⇒ NÃO displaced.
    hammer = _cdl(99.0, 102.2, 102.0, open_=101.8,
                  choch_internal_bullish=True)
    df = _pending_rows(hammer)
    res = compute_setup_state(df, SetupConfig(signature='A1'))
    assert _states(res) == [STATE_ARMED, STATE_PENDING, STATE_CONFIRMED]
    res = compute_setup_state(df, SetupConfig(
        signature='A1',
        displacement_gate='confirm', displacement_body_len=2,
    ))
    assert _states(res) == [STATE_ARMED, STATE_PENDING, STATE_PENDING]


def test_td3_legacy_trigger_confirms_choch_rej_disp() -> None:
    """Tripla conjunção satisfeita ⇒ confirma (rejeição com
    `rejection_wick_frac` reduzido — com o default 0,5 a co-ocorrência
    rejeição∧displacement é impossível por aritmética: wick inferior
    >= 50% do range >= 50% do corpo > 36% do corpo)."""
    # Corpo 1,0; wick inferior 0,3 (22% do range, < 36% do corpo);
    # wick superior 0,05; close no topo ⇒ rejeição (frac 0,2) ∧ ChoCH
    # ∧ displacement.
    candle = _cdl(100.7, 102.05, 102.0, open_=101.0,
                  choch_internal_bullish=True)
    df = _pending_rows(candle)
    res = compute_setup_state(df, SetupConfig(
        signature='A1', rejection_wick_frac=0.2,
        displacement_gate='confirm', displacement_body_len=2,
    ))
    assert _states(res) == [STATE_ARMED, STATE_PENDING, STATE_CONFIRMED]


# ============================================================
# T-D4 — por construção (golden): todo CONFIRMED com gate on é displaced
# ============================================================

def test_td4_golden_all_confirmed_are_displaced(merged_golden) -> None:
    """Bloco-1-ON + gate on, 9 assinaturas (G9 multi) em confirmation:
    todo candle de CONFIRMED satisfaz disp(direção) — violações == 0.
    Contadores absolutos ancorados na medição do briefing (§0)."""
    disp_bull, disp_bear = _displacement_flags(
        merged_golden['open'].to_numpy(dtype='float64'),
        merged_golden['high'].to_numpy(dtype='float64'),
        merged_golden['low'].to_numpy(dtype='float64'),
        merged_golden['close'].to_numpy(dtype='float64'),
        10, 0.36,
    )
    assert int(disp_bull.sum()) == _GOLDEN_DISP_BULL
    assert int(disp_bear.sum()) == _GOLDEN_DISP_BEAR

    totals = {}
    results = {}
    for gate in ('off', 'confirm'):
        res = compute_setup_state_multi(merged_golden, SetupConfig(
            signature=ALL_SIGS, displacement_gate=gate, **_BLOCO1_ON,
        ))
        results[gate] = res
        totals[gate] = sum(
            int((res[f'setup_state__{sid}'] == STATE_CONFIRMED).sum())
            for sid in ALL_SIGS
        )
    assert totals['off'] == _GOLDEN_CONFIRMED_GATE_OFF
    assert totals['confirm'] == _GOLDEN_CONFIRMED_GATE_ON

    violations = 0
    for sid in ALL_SIGS:
        confirmed = (
            results['confirm'][f'setup_state__{sid}'] == STATE_CONFIRMED
        ).fillna(False).to_numpy(dtype='bool')
        direction = results['confirm'][f'setup_direction__{sid}']
        is_long = (direction == DIRECTION_LONG) \
            .fillna(False).to_numpy(dtype='bool')
        is_short = (direction == DIRECTION_SHORT) \
            .fillna(False).to_numpy(dtype='bool')
        violations += int((confirmed & is_long & ~disp_bull).sum())
        violations += int((confirmed & is_short & ~disp_bear).sum())
    assert violations == 0


# ============================================================
# T-D5 — modo risk: gate inerte por construção (golden)
# ============================================================

def test_td5_risk_mode_gate_inert(merged_golden) -> None:
    base = dict(
        signature=ALL_SIGS, entry_mode=ENTRY_MODE_RISK, **_BLOCO1_ON,
    )
    off = compute_setup_state(
        merged_golden, SetupConfig(displacement_gate='off', **base),
    )
    on = compute_setup_state(
        merged_golden, SetupConfig(displacement_gate='confirm', **base),
    )
    pd.testing.assert_frame_equal(off, on)
    assert int((off['setup_state'] == STATE_CONFIRMED).sum()) > 0


# ============================================================
# Validação dos campos novos do SetupConfig
# ============================================================

def test_bloco2_config_fields_validated() -> None:
    with pytest.raises(ValueError, match='displacement_gate'):
        SetupConfig(displacement_gate='nope')
    with pytest.raises(ValueError, match='displacement_body_len'):
        SetupConfig(displacement_body_len=1)
    with pytest.raises(ValueError, match='displacement_body_len'):
        SetupConfig(displacement_body_len=10.0)
    with pytest.raises(ValueError, match='displacement_wick_frac'):
        SetupConfig(displacement_wick_frac=0.0)
    with pytest.raises(ValueError, match='displacement_wick_frac'):
        SetupConfig(displacement_wick_frac=1.5)
