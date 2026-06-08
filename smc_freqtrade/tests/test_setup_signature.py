"""Smoke da coluna `setup_signature` (instrumentação por assinatura — 10c).

OBJETIVO
    Provar que o matcher (`compute_setup_state`) emite a assinatura legível
    (A1–A10) numa coluna própria (`setup_signature`), paralela ao `setup_id`
    (hash não-reversível), em todas as linhas com setup ativo — e NA nas linhas
    sem setup. Cobre o smoke de engine do §7:
      - df sintético que arma/confirma um A3 long conhecido → `setup_signature`
        == 'A3' nas linhas ARMED→PENDING→CONFIRMED, casando a direção;
      - linha sem setup ativo → `setup_signature` NA;
      - a constante e a coluna estão na lista de output (`SETUP_OUTPUT_COLUMNS`).

FONTE DE DADOS
    DataFrame mergeado scriptado à mão (esperado independente da engine), no
    mesmo molde dos demais testes de trajetória (`test_setup_state_9_5b.py`).

LIMITAÇÕES CONHECIDAS
    Mudança aditiva de instrumentação: não revalida a FSM (estados/âncora) —
    isso é coberto pelos testes de trajetória existentes. Aqui só a coluna nova.

NÃO FAZER
    Não gerar a fixture esperada com o próprio `compute_setup_state`; não tocar
    `analyze()` nem golden.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from smc_engine import (
    compute_setup_state,
    SetupConfig,
    SETUP_OUTPUT_COLUMNS,
    COL_SETUP_SIGNATURE,
    STATE_ARMED,
    STATE_PENDING,
    STATE_CONFIRMED,
    DIRECTION_LONG,
)

# Banda OB long [100, 102]; FVG long adjacente [102, 103] (âncoras da A3).
OB_TOP, OB_BOT, OB_ID = 102.0, 100.0, 5
FVG_TOP, FVG_BOT, FVG_ID = 103.0, 102.0, 7

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
    'active_bull_fvg_top_1h': np.nan,
    'active_bull_fvg_bottom_1h': np.nan,
    'active_bull_fvg_id_1h': np.nan,
    'active_bear_fvg_top_1h': np.nan,
    'active_bear_fvg_bottom_1h': np.nan,
    'active_bear_fvg_id_1h': np.nan,
    'sweep_bullish_wick': False,
    'sweep_bullish_retest': False,
    'sweep_bearish_wick': False,
    'sweep_bearish_retest': False,
    'choch_internal_bullish': False,
    'choch_internal_bearish': False,
}

_ALL_COLS = ['open', 'high', 'low', 'close'] + list(_DEFAULTS)

_OB_FVG_LONG = {
    'active_bull_swing_ob_top_1h': OB_TOP,
    'active_bull_swing_ob_bottom_1h': OB_BOT,
    'active_bull_swing_ob_id_1h': float(OB_ID),
    'active_bull_fvg_top_1h': FVG_TOP,
    'active_bull_fvg_bottom_1h': FVG_BOT,
    'active_bull_fvg_id_1h': float(FVG_ID),
}


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


def test_setup_signature_in_output_columns() -> None:
    """A coluna `setup_signature` integra o bloco de output do matcher."""
    assert COL_SETUP_SIGNATURE == 'setup_signature'
    assert COL_SETUP_SIGNATURE in SETUP_OUTPUT_COLUMNS


def test_setup_signature_a3_long_trajectory() -> None:
    """A3 long: `setup_signature` == 'A3' em ARMED→PENDING→CONFIRMED, casando a
    direção; linha sem setup ativo → NA; dtype 'string'."""
    rows = [
        # 0: neutro — sem zona/sweep → nada arma (sem setup ativo).
        _cdl(106, 108, 107),
        # 1: ARM A3 — OB+FVG adjacentes, preço acima da zona + sweep bullish.
        {**_cdl(105, 107, 106, sweep_bullish_wick=True), **_OB_FVG_LONG},
        # 2: intersecta a zona → PENDING.
        {**_cdl(99, 103, 101), **_OB_FVG_LONG},
        # 3: CONFIRM — choch + rejeição bullish + sweep ainda recente.
        {**_cdl(98, 102, 101.8, open_=101, choch_internal_bullish=True),
         **_OB_FVG_LONG},
    ]
    res = compute_setup_state(_build(rows), SetupConfig(signature='A3'))

    sig = res[COL_SETUP_SIGNATURE]
    # Linha 0 (sem setup ativo) → NA na assinatura e no estado.
    assert pd.isna(sig.iloc[0])
    assert pd.isna(res['setup_state'].iloc[0])
    # Linhas 1–3 (ARMED→PENDING→CONFIRMED) carregam a assinatura legível 'A3'.
    assert res['setup_state'].tolist()[1:] == [
        STATE_ARMED, STATE_PENDING, STATE_CONFIRMED,
    ]
    assert sig.tolist()[1:] == ['A3', 'A3', 'A3']
    # Direção casada (long) nas linhas do setup.
    assert (res['setup_direction'].iloc[1:] == DIRECTION_LONG).all()
    # dtype nullable string + setup_id (hash) segue ao lado, não-nulo no setup.
    assert sig.dtype == 'string'
    assert res['setup_id'].iloc[1:].notna().all()


def test_setup_signature_distinct_from_setup_id() -> None:
    """A assinatura é a string legível ('A3'), não o hash do `setup_id`."""
    rows = [
        {**_cdl(105, 107, 106, sweep_bullish_wick=True), **_OB_FVG_LONG},
    ]
    res = compute_setup_state(_build(rows), SetupConfig(signature='A3'))
    assert res[COL_SETUP_SIGNATURE].iloc[0] == 'A3'
    # O setup_id é um hash de 16 hex chars — distinto da assinatura legível.
    sid = res['setup_id'].iloc[0]
    assert sid != 'A3' and len(sid) == 16
