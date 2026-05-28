"""
OBJETIVO
    Smoke + integração do helper `tools.mtf_align.align_informative`,
    cobrindo critérios C1-C10 do briefing Wave 9.4 §5.

    Cada teste `Tn` mapeia 1:1 ao critério `Cn` do briefing.

FONTE DE DADOS
    T1-T8: DataFrames sintéticos pequenos (≤ 32 rows) com séries de datas
        construídas via `pd.date_range`. Critérios determinísticos.
    T9-T10: goldens MTF reais capturados em
        `tests/golden/data/btc_usdt_swap_{4h,1h,15m}_window.csv`
        (jan-abr/2026, BTC-USDT-SWAP/OKX, registrados em README §8).

LIMITAÇÕES CONHECIDAS
    T9 e T10 exercitam a direção upstream-supported (base mais fina que
    inf). O briefing §3 P3 e §5 C9/C10 usam o rótulo "4H base + 1H inf"
    para descrever o mesmo cenário; a matemática (shift +180min / +225min)
    casa apenas com `base=1H/inf=4H` e `base=15m/inf=4H` no algoritmo
    upstream (a direção oposta dispara `ValueError`, vide T6/C6). Os
    rótulos do briefing foram interpretados pela matemática.

NÃO FAZER
    - Não importar `freqtrade.*` (o helper sob teste é livre de Freqtrade).
    - Não pular T9/T10 se os CSVs existirem — eles fazem parte do contrato
      do PR.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from tools.mtf_align import align_informative


GOLDEN_DIR = Path(__file__).resolve().parent / 'golden' / 'data'


def _load_ohlcv_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df['date'] = pd.to_datetime(df['timestamp_utc'], utc=True)
    return df[['date', 'open', 'high', 'low', 'close', 'volume']]


def _mk_series(start: str, periods: int, freq: str) -> pd.DataFrame:
    return pd.DataFrame({
        'date': pd.date_range(start, periods=periods, freq=freq, tz='UTC'),
        'close': list(range(periods)),
    })


# ============================================================
# T1 / C1 — output_len == len(df_base)
# ============================================================

def test_t1_output_length_equals_base():
    """C1: output tem sempre `len(df_base)` linhas, qualquer cenário."""
    base = _mk_series('2026-01-01', 12, '1h')   # 12 linhas
    inf = _mk_series('2026-01-01', 3, '4h')     # 3 linhas
    out = align_informative(base, inf, '1h', '4h')
    assert len(out) == len(base) == 12


# ============================================================
# T2 / C2 — todas as colunas do informative aparecem renomeadas
# ============================================================

def test_t2_all_inf_columns_renamed_with_suffix():
    """C2: para toda col em df_inf.columns, existe `f'{col}_{tf_inf}'`
    no output. Inclui date/open/high/low/close."""
    base = _mk_series('2026-01-01', 12, '1h')
    inf = pd.DataFrame({
        'date': pd.date_range('2026-01-01', periods=3, freq='4h', tz='UTC'),
        'open': [1.0, 2.0, 3.0],
        'high': [1.5, 2.5, 3.5],
        'low': [0.5, 1.5, 2.5],
        'close': [1.2, 2.2, 3.2],
    })
    out = align_informative(base, inf, '1h', '4h')
    for col in inf.columns:
        assert f'{col}_4h' in out.columns, f'Coluna {col}_4h ausente.'


# ============================================================
# T3 / C3 — Lookahead-safety verbatim
# ============================================================

def test_t3_lookahead_safety_arithmetic():
    """C3: para toda linha, `date_inf_merged + minutes_inf ≤ date_base +
    minutes_base`."""
    base = _mk_series('2026-01-01', 48, '15min')  # 48 × 15min = 12h
    inf = _mk_series('2026-01-01', 12, '1h')      # 12 × 1h = 12h
    out = align_informative(base, inf, '15m', '1h')
    minutes_base = 15
    minutes_inf = 60
    mask = out['date_1h'].notna()
    lhs = out.loc[mask, 'date_1h'] + pd.Timedelta(minutes=minutes_inf)
    rhs = out.loc[mask, 'date'] + pd.Timedelta(minutes=minutes_base)
    assert (lhs <= rhs).all(), 'Violação de lookahead-safety detectada.'


# ============================================================
# T4 / C4 — Recência (maior date_inf que satisfaz lookahead)
# ============================================================

def test_t4_recency_picks_latest_valid_inf():
    """C4: para toda linha, date_inf_merged é o **maior** timestamp em
    df_inf['date'] tal que date_inf_merged + minutes_inf ≤ date_base +
    minutes_base."""
    base = _mk_series('2026-01-01', 48, '15min')
    inf = _mk_series('2026-01-01', 12, '1h')
    out = align_informative(base, inf, '15m', '1h')

    minutes_base = pd.Timedelta(minutes=15)
    minutes_inf = pd.Timedelta(minutes=60)

    inf_dates = inf['date'].sort_values()
    for _, row in out.iterrows():
        if pd.isna(row['date_1h']):
            continue
        deadline = row['date'] + minutes_base - minutes_inf
        eligible = inf_dates[inf_dates <= deadline]
        expected = eligible.iloc[-1]
        assert row['date_1h'] == expected, (
            f"Linha date={row['date']}: esperado {expected}, "
            f"obtido {row['date_1h']}."
        )


# ============================================================
# T5 / C5 — tf_base == tf_inf → sem shift
# ============================================================

def test_t5_same_timeframe_no_shift():
    """C5: tf_base == tf_inf → output[f'date_{tf_inf}'][i] == output['date'][i]."""
    base = _mk_series('2026-01-01', 10, '1h')
    inf = _mk_series('2026-01-01', 10, '1h')
    inf['close'] = [v * 10 for v in range(10)]
    out = align_informative(base, inf, '1h', '1h')
    assert (out['date'] == out['date_1h']).all()
    # close_1h corresponde 1:1 (sem shift, sem ffill diferente).
    assert list(out['close_1h']) == list(inf['close'])


# ============================================================
# T6 / C6 — tf_inf mais rápido → ValueError
# ============================================================

def test_t6_faster_inf_raises_value_error():
    """C6: tf_inf < tf_base → raise ValueError com mensagem upstream."""
    base = _mk_series('2026-01-01', 3, '4h')
    inf = _mk_series('2026-01-01', 12, '1h')
    with pytest.raises(ValueError, match='faster timeframe to a slower timeframe'):
        align_informative(base, inf, '4h', '1h')


# ============================================================
# T7 / C7 — Borda inicial
# ============================================================

def test_t7_initial_border_ffill_from_prior_inf():
    """C7: df_inf começa N candles depois de df_base. Com ffill=True e
    candle anterior disponível, primeira linha preenchida; sem candle
    anterior, NaN."""
    # Cenário A: inf começa DEPOIS de base; SEM candle anterior →
    # primeiras linhas do output ficam NaN.
    base = _mk_series('2026-01-01 00:00', 8, '15min')   # 00:00..01:45
    inf = _mk_series('2026-01-01 02:00', 3, '1h')       # 02:00..04:00
    out = align_informative(base, inf, '15m', '1h')
    assert out['date_1h'].isna().all(), (
        'Sem inf anterior à janela base, todas as linhas devem ser NaN.'
    )

    # Cenário B: base começa DEPOIS de inf; ffill deve preencher a
    # primeira linha com o inf anterior.
    base = _mk_series('2026-01-01 04:00', 4, '15min')   # 04:00..04:45
    inf = _mk_series('2026-01-01 00:00', 5, '1h')       # 00:00..04:00
    out = align_informative(base, inf, '15m', '1h')
    # Primeira linha base (04:00) deve ter inf anterior preenchido
    # (lookahead-safe: 03:00 inf fecha em 04:00).
    assert out['date_1h'].iloc[0] is not pd.NaT
    assert pd.notna(out['date_1h'].iloc[0])


# ============================================================
# T8 / C8 — Idempotência de cópia
# ============================================================

def test_t8_inputs_not_mutated():
    """C8: id(df_base_in) != id(df_base_out). df_base.equals(orig) após."""
    base = _mk_series('2026-01-01', 12, '1h')
    inf = _mk_series('2026-01-01', 3, '4h')
    base_orig = base.copy()
    inf_orig = inf.copy()
    out = align_informative(base, inf, '1h', '4h')
    assert id(out) != id(base)
    assert base.equals(base_orig), 'df_base foi mutado.'
    assert inf.equals(inf_orig), 'df_inf foi mutado.'


# ============================================================
# T9 / C9 — Cenário real 4H + 1H goldens
# ============================================================

def test_t9_real_goldens_4h_1h():
    """C9: goldens reais (briefing §2.2). Direção upstream-supported:
    base=1H (2880 candles), inf=4H (720 candles). Shift fresco = +180min
    (1H que fecha junto com 4H). 3 linhas iniciais ficam NaN antes do
    primeiro fechamento de 4H — comportamento esperado, não bug.
    """
    base_1h = _load_ohlcv_csv(GOLDEN_DIR / 'btc_usdt_swap_1h_window.csv')
    inf_4h = _load_ohlcv_csv(GOLDEN_DIR / 'btc_usdt_swap_4h_window.csv')

    assert len(base_1h) == 2880
    assert len(inf_4h) == 720

    out = align_informative(base_1h, inf_4h, '1h', '4h')

    assert len(out) == len(base_1h) == 2880

    # As 3 primeiras linhas (00:00, 01:00, 02:00) ocorrem antes do
    # primeiro fechamento de 4H (04:00). Apenas a partir da 4ª (03:00)
    # o date_4h fica preenchido.
    assert out['date_4h'].iloc[:3].isna().all()
    assert out['date_4h'].iloc[3:].notna().all()

    # Para linhas "fresh" (logo após um fechamento de 4H), shift é
    # exatamente 180min. Há ~720 dessas linhas (uma por candle 4H).
    shift_min = (out['date'] - out['date_4h']).dt.total_seconds() / 60
    fresh = shift_min == 180
    assert fresh.sum() == 720


# ============================================================
# T10 / C10 — Cenário real 4H + 15m goldens
# ============================================================

def test_t10_real_goldens_4h_15m():
    """C10: goldens reais. Direção upstream-supported: base=15m (11520
    candles), inf=4H (720 candles). Shift fresco = +225min (15m que fecha
    junto com 4H). 15 linhas iniciais ficam NaN antes do primeiro
    fechamento de 4H.
    """
    base_15m = _load_ohlcv_csv(GOLDEN_DIR / 'btc_usdt_swap_15m_window.csv')
    inf_4h = _load_ohlcv_csv(GOLDEN_DIR / 'btc_usdt_swap_4h_window.csv')

    assert len(base_15m) == 11520
    assert len(inf_4h) == 720

    out = align_informative(base_15m, inf_4h, '15m', '4h')

    assert len(out) == len(base_15m) == 11520

    # As 15 primeiras linhas (00:00..03:45) ocorrem antes do primeiro
    # fechamento de 4H (04:00).
    assert out['date_4h'].iloc[:15].isna().all()
    assert out['date_4h'].iloc[15:].notna().all()

    shift_min = (out['date'] - out['date_4h']).dt.total_seconds() / 60
    fresh = shift_min == 225
    assert fresh.sum() == 720
