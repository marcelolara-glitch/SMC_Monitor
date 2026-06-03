"""Smoke sintético Wave 9.5d — hooks Sessions (§10.6) + Fib/OTE (§10.3).

OBJETIVO
    Cobrir, de forma determinística e aditiva, os dois hooks puros da
    Wave 9.5d:
        1. `tag_sessions`: 3 killzones Silver Bullet (NY-time) idênticas
           sob os 3 tipos de `date` (tz-aware UTC, tz-naive, int64
           epoch-ms), incluindo a fronteira DST EST→EDT (2026-03-08).
        2. `project_ote_zones`: banda OTE 0.62-0.79 direction-aware sobre
           o swing range ativo no MSS (trap de direção + lifecycle).
        3. Anti-lookahead: nenhum `shift(-N)` nos 2 módulos novos.

FONTE DE DADOS
    DataFrames sintéticos com timestamps/colunas conhecidos. O teste de
    OTE injeta diretamente `trailing_*` e as colunas `*_swing_*` (não
    depende de `detect_structure` — testa o hook em isolamento).

NÃO FAZER
    Não comparar contra TradingView (sem ground truth visual).
    Não validar A7/A10 (Wave 9.5e) — aqui só infra de hook.
"""
from __future__ import annotations

import ast
import io
import tokenize
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from smc_engine import (
    BEARISH,
    BULLISH,
    OTE_COLUMNS,
    SESSION_COLUMNS,
    project_ote_zones,
    tag_sessions,
)
from smc_engine.fib_ote import (
    COL_ACTIVE_BEAR_OTE_BOTTOM,
    COL_ACTIVE_BEAR_OTE_ID,
    COL_ACTIVE_BEAR_OTE_TOP,
    COL_ACTIVE_BULL_OTE_BOTTOM,
    COL_ACTIVE_BULL_OTE_ID,
    COL_ACTIVE_BULL_OTE_TOP,
    OTE_RETRACE_HIGH,
    OTE_RETRACE_LOW,
    _build_ote_ledger,
)
from smc_engine.sessions import (
    COL_IN_KZ_SILVER_BULLET_AM,
    COL_IN_KZ_SILVER_BULLET_LATE,
    COL_IN_KZ_SILVER_BULLET_PM,
)
from smc_engine.structure import (
    COL_BOS_SWING_BEARISH,
    COL_BOS_SWING_BULLISH,
    COL_CHOCH_SWING_BEARISH,
    COL_CHOCH_SWING_BULLISH,
)
from smc_engine.trailing import COL_TRAILING_BOTTOM, COL_TRAILING_TOP

_EPOCH = pd.Timestamp('1970-01-01', tz='UTC')


# ---------------------------------------------------------------------------
# 1. Sessions — Timestamp, tz-naive e epoch-ms, com DST EST→EDT.
# ---------------------------------------------------------------------------

# (timestamp UTC, AM esperado, LATE esperado, PM esperado).
# Pré-DST 2026-03-01 (EST, UTC-5): 03:00 NY = 08:00 UTC, etc.
# Pós-DST 2026-03-15 (EDT, UTC-4): 03:00 NY = 07:00 UTC, etc.
_SESSION_CASES = [
    # --- Pré-DST (EST, UTC-5) ---
    ('2026-03-01T08:00:00Z', True, False, False),   # 03:00 NY → AM
    ('2026-03-01T09:00:00Z', False, False, False),  # 04:00 NY → nada
    ('2026-03-01T15:00:00Z', False, True, False),   # 10:00 NY → LATE
    ('2026-03-01T19:00:00Z', False, False, True),   # 14:00 NY → PM
    ('2026-03-01T00:00:00Z', False, False, False),  # 19:00 NY (dia ant.)
    # --- Pós-DST (EDT, UTC-4) ---
    ('2026-03-15T07:00:00Z', True, False, False),   # 03:00 NY → AM
    ('2026-03-15T08:00:00Z', False, False, False),  # 04:00 NY → nada (trap DST)
    ('2026-03-15T14:00:00Z', False, True, False),   # 10:00 NY → LATE
    ('2026-03-15T18:00:00Z', False, False, True),   # 14:00 NY → PM
]


def _session_df() -> pd.DataFrame:
    dates = pd.to_datetime([c[0] for c in _SESSION_CASES], utc=True)
    return pd.DataFrame({
        'date': dates,
        'open': 1.0, 'high': 2.0, 'low': 0.5, 'close': 1.5,
    })


def test_sessions_membership_and_dst():
    """Pertencimento por candle correto e dtype bool (incl. trap DST)."""
    out = tag_sessions(_session_df())
    for col in SESSION_COLUMNS:
        assert out[col].dtype == bool
    am = out[COL_IN_KZ_SILVER_BULLET_AM].to_numpy()
    late = out[COL_IN_KZ_SILVER_BULLET_LATE].to_numpy()
    pm = out[COL_IN_KZ_SILVER_BULLET_PM].to_numpy()
    exp_am = np.array([c[1] for c in _SESSION_CASES])
    exp_late = np.array([c[2] for c in _SESSION_CASES])
    exp_pm = np.array([c[3] for c in _SESSION_CASES])
    assert (am == exp_am).all()
    assert (late == exp_late).all()
    assert (pm == exp_pm).all()
    # Trap DST explícito: 08:00 UTC é AM pré-DST mas NÃO pós-DST.
    assert am[0] and not am[6]


def test_sessions_equivalence_across_date_types():
    """As 3 variantes de `date` produzem colunas idênticas (D-D2)."""
    base = _session_df()
    df_aware = base
    df_naive = base.copy()
    df_naive['date'] = base['date'].dt.tz_localize(None)
    df_int = base.copy()
    df_int['date'] = (
        (base['date'] - _EPOCH) // pd.Timedelta('1ms')
    ).astype('int64')

    out_aware = tag_sessions(df_aware)
    out_naive = tag_sessions(df_naive)
    out_int = tag_sessions(df_int)
    for col in SESSION_COLUMNS:
        ref = out_aware[col].to_numpy()
        assert (out_naive[col].to_numpy() == ref).all()
        assert (out_int[col].to_numpy() == ref).all()


# ---------------------------------------------------------------------------
# 2. Fib/OTE — perna sintética com extremos conhecidos.
# ---------------------------------------------------------------------------

# Bull MSS @idx 2: range [100, 200], invalida em idx 7 (close < 100).
# Bear MSS @idx 10: range [300, 400], invalida em idx 16 (close > 400).
_BULL_T, _BULL_LOW, _BULL_HIGH = 2, 100.0, 200.0
_BULL_INV = 7
_BEAR_T, _BEAR_LOW, _BEAR_HIGH = 10, 300.0, 400.0
_BEAR_INV = 16
_N_OTE = 20


def _ote_df() -> pd.DataFrame:
    closes = np.full(_N_OTE, 150.0)
    closes[_BULL_INV:_BEAR_T] = 90.0          # invalida bull (< 100)
    closes[_BEAR_T:_BEAR_INV] = 350.0         # dentro do range bear
    closes[_BEAR_INV:] = 410.0                # invalida bear (> 400)

    ttop = np.full(_N_OTE, np.nan)
    tbot = np.full(_N_OTE, np.nan)
    ttop[_BULL_T], tbot[_BULL_T] = _BULL_HIGH, _BULL_LOW
    ttop[_BEAR_T], tbot[_BEAR_T] = _BEAR_HIGH, _BEAR_LOW

    bos_bull = np.zeros(_N_OTE, dtype=bool)
    bos_bear = np.zeros(_N_OTE, dtype=bool)
    choch_bull = np.zeros(_N_OTE, dtype=bool)
    choch_bear = np.zeros(_N_OTE, dtype=bool)
    bos_bull[_BULL_T] = True          # MSS bull = BOS swing
    choch_bear[_BEAR_T] = True        # MSS bear = CHoCH swing

    return pd.DataFrame({
        'date': pd.date_range('2026-01-01', periods=_N_OTE, freq='1h'),
        'open': closes, 'high': closes + 1.0, 'low': closes - 1.0,
        'close': closes,
        COL_TRAILING_TOP: ttop,
        COL_TRAILING_BOTTOM: tbot,
        COL_BOS_SWING_BULLISH: bos_bull,
        COL_BOS_SWING_BEARISH: bos_bear,
        COL_CHOCH_SWING_BULLISH: choch_bull,
        COL_CHOCH_SWING_BEARISH: choch_bear,
    })


def test_ote_ledger_levels_and_direction():
    """Níveis Fib 0.62/0.705/0.79 e trap de direção (discount vs premium)."""
    ledger = _build_ote_ledger(_ote_df())
    assert len(ledger) == 2

    bull = ledger[ledger['bias'] == BULLISH].iloc[0]
    bear = ledger[ledger['bias'] == BEARISH].iloc[0]

    bull_span = _BULL_HIGH - _BULL_LOW
    # Bull (discount): bottom = high - 0.79*span, top = high - 0.62*span.
    assert bull['bottom'] == pytest.approx(_BULL_HIGH - OTE_RETRACE_HIGH * bull_span)
    assert bull['top'] == pytest.approx(_BULL_HIGH - OTE_RETRACE_LOW * bull_span)
    # Mediana 0.705 dentro da banda.
    bull_median = _BULL_HIGH - 0.705 * bull_span
    assert bull['bottom'] <= bull_median <= bull['top']
    # Trap de direção: banda bull na metade BAIXA do range.
    assert bull['top'] < (_BULL_LOW + _BULL_HIGH) / 2

    bear_span = _BEAR_HIGH - _BEAR_LOW
    # Bear (premium): bottom = low + 0.62*span, top = low + 0.79*span.
    assert bear['bottom'] == pytest.approx(_BEAR_LOW + OTE_RETRACE_LOW * bear_span)
    assert bear['top'] == pytest.approx(_BEAR_LOW + OTE_RETRACE_HIGH * bear_span)
    bear_median = _BEAR_LOW + 0.705 * bear_span
    assert bear['bottom'] <= bear_median <= bear['top']
    # Trap de direção: banda bear na metade ALTA do range.
    assert bear['bottom'] > (_BEAR_LOW + _BEAR_HIGH) / 2


def test_ote_projection_lifecycle():
    """Zona ativa entre criação e invalidação; vazia antes e depois."""
    out = project_ote_zones(_ote_df())
    for col in OTE_COLUMNS:
        assert col in out.columns
    assert out[COL_ACTIVE_BULL_OTE_TOP].dtype == 'float64'
    assert str(out[COL_ACTIVE_BULL_OTE_ID].dtype) == 'Int64'

    bull_top = out[COL_ACTIVE_BULL_OTE_TOP]
    # Antes da criação (idx < 2): vazio.
    assert bull_top.iloc[:_BULL_T].isna().all()
    # Ativa em [criação, invalidação): idx 2..6 preenchido.
    assert bull_top.iloc[_BULL_T:_BULL_INV].notna().all()
    # Após cruzar a origem 0.0 (idx >= 7): vazio.
    assert bull_top.iloc[_BULL_INV:].isna().all()
    # Valor projetado == nível do ledger.
    exp_top = _BULL_HIGH - OTE_RETRACE_LOW * (_BULL_HIGH - _BULL_LOW)
    assert bull_top.iloc[_BULL_T] == pytest.approx(exp_top)

    bear_top = out[COL_ACTIVE_BEAR_OTE_TOP]
    assert bear_top.iloc[:_BEAR_T].isna().all()
    assert bear_top.iloc[_BEAR_T:_BEAR_INV].notna().all()
    assert bear_top.iloc[_BEAR_INV:].isna().all()

    # Bandas em metades opostas do range (trap de direção, projetado).
    assert out[COL_ACTIVE_BULL_OTE_BOTTOM].iloc[_BULL_T] < (_BULL_LOW + _BULL_HIGH) / 2
    assert out[COL_ACTIVE_BEAR_OTE_BOTTOM].iloc[_BEAR_T] > (_BEAR_LOW + _BEAR_HIGH) / 2


# ---------------------------------------------------------------------------
# 3. Anti-lookahead — nenhum `shift(-N)` nos módulos novos.
# ---------------------------------------------------------------------------

def _module_path(name: str) -> Path:
    return Path(__file__).resolve().parent.parent / 'smc_engine' / name


@pytest.mark.parametrize('module', ['sessions.py', 'fib_ote.py'])
def test_no_lookahead_shift(module: str):
    """Falha se algum `.shift(<negativo>)` aparecer (lookahead proibido)."""
    source = _module_path(module).read_text(encoding='utf-8')
    # Grep textual sobre o CÓDIGO (sem comentários nem docstrings — estas
    # mencionam "shift(-N)" na seção NÃO FAZER, prosa não é lookahead).
    code_only = ''.join(
        tok.string
        for tok in tokenize.generate_tokens(io.StringIO(source).readline)
        if tok.type not in (tokenize.COMMENT, tokenize.STRING)
    )
    assert 'shift(-' not in code_only.replace(' ', '')
    # AST: qualquer chamada .shift(arg) com arg negativo.
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == 'shift'
            and node.args
        ):
            arg = node.args[0]
            is_neg = (
                isinstance(arg, ast.UnaryOp)
                and isinstance(arg.op, ast.USub)
            )
            assert not is_neg, f"shift negativo (lookahead) em {module}"
