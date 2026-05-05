"""
OBJETIVO
    Smoke test da Onda 3: prova que `smc_engine.pivots.detect_pivots`
    porta fielmente as 5 funções nested do LuxAlgo SMC
    (leg / startOfNewLeg / startOfBullishLeg / startOfBearishLeg /
    getCurrentStructure), incluindo:
      - propagação de estado via ffill (Persistent[int] do Pine)
      - detecção de swing high/low com delay de `swings_length` candles
      - detecção de internal high/low com delay de `internal_length`
      - alerta de equal high/low quando dentro de `equal_threshold * atr`
      - lookahead-safety por construção (truncation invariance)
      - degeneração esperada para DataFrames mais curtos que swings_length

FONTE DE DADOS
    Sintética: pequenos DataFrames construídos à mão, com pivots
    plantados em posições conhecidas e candles de preenchimento
    constante (high=50, low=49) escolhidos de modo a NÃO disparar
    pivots competidores nas janelas em torno dos eventos plantados.

    Cada teste constrói seu próprio DataFrame; sem fixtures.

LIMITAÇÕES CONHECIDAS
    Não valida contra dataset real do Pine — equivalência golden vai
    para PR próprio entre Onda 3 e Onda 5 (ver §1.4 do briefing Onda 3).
    Casos de empate `>=` vs `>` no detector de leg ficam fora do escopo
    (Pine usa `>` estrito; portagem espelha).

NÃO FAZER
    Não relaxar o teste 7 (truncation invariance): ele é o gate
    anti-lookahead desta onda. Se falhar, é red flag arquitetural.
    Não importar de smc_freqtrade.smc_engine — o pacote raiz é
    `smc_engine` (ver tests/test_smoke_wave2.py).
    Não usar fixtures pytest aqui — cada teste é auto-contido.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from smc_engine.pivots import (
    _leg,
    _start_of_bearish_leg,
    _start_of_bullish_leg,
    _start_of_new_leg,
    detect_pivots,
)


# ============================================================
# Helpers de construção de DataFrames sintéticos.
# ============================================================

def _make_flat_df(n: int, base_high: float = 50.0, base_low: float = 49.0) -> pd.DataFrame:
    """DataFrame de n candles com high/low/close constantes (sem pivots)."""
    return pd.DataFrame({
        'high': np.full(n, base_high, dtype=float),
        'low': np.full(n, base_low, dtype=float),
        'close': np.full(n, (base_high + base_low) / 2.0, dtype=float),
        'date': pd.date_range('2024-01-01', periods=n, freq='15min'),
    })


def _df_with_trough_then_peak(
    n: int,
    trough_idx: int,
    peak_idx: int,
    trough_low: float = 10.0,
    peak_high: float = 100.0,
) -> pd.DataFrame:
    """DataFrame de n candles com um vale em trough_idx (low=trough_low,
    high=base_high=50) e um pico em peak_idx (high=peak_high, low=49).

    Ordem importa: trough_idx < peak_idx, para que a primeira transição
    de leg seja do estado inicial 0 -> BULLISH_LEG=1 (swing low),
    permitindo a detecção subsequente do swing high (1 -> BEARISH_LEG=0).
    Sem essa ordem, o primeiro swing high não dispara `startOfNewLeg`
    porque BEARISH_LEG (=0) coincide com o estado inicial.
    """
    assert trough_idx < peak_idx
    df = _make_flat_df(n)
    df.loc[trough_idx, 'low'] = trough_low
    df.loc[peak_idx, 'high'] = peak_high
    return df


# ============================================================
# 1. _leg state transitions (manual fidelity)
# ============================================================

def test_leg_state_transitions_propagate_via_ffill() -> None:
    """Replica a tabela manual do briefing §3.6:
    8 candles com vale em idx=2, size=3 -> swing low em X=2+3=5.
    `leg` deve ser [0,0,0,0,0,1,1,1] (BULLISH_LEG só a partir de X=5,
    propagado por ffill). E start_of_new_leg / start_of_bullish_leg
    True apenas em X=5; start_of_bearish_leg sempre False.
    """
    high = pd.Series([50.0, 50.0, 10.0, 50.0, 50.0, 50.0, 50.0, 50.0])
    low = pd.Series([49.0, 49.0, 9.0, 49.0, 49.0, 49.0, 49.0, 49.0])

    leg = _leg(high, low, size=3)
    assert leg.tolist() == [0, 0, 0, 0, 0, 1, 1, 1]

    new = _start_of_new_leg(leg)
    bull = _start_of_bullish_leg(leg)
    bear = _start_of_bearish_leg(leg)

    expected_new = [False, False, False, False, False, True, False, False]
    expected_bull = expected_new[:]
    expected_bear = [False] * 8

    assert new.tolist() == expected_new
    assert bull.tolist() == expected_bull
    assert bear.tolist() == expected_bear


# ============================================================
# 2. swing high detection
# ============================================================

def test_swing_high_basic_detection() -> None:
    """Trough em idx=30, peak em idx=80, swings_length=50:
    swing_low_level deve materializar em X=30+50=80 com valor 10,
    e swing_high_level em X=80+50=130 com valor 100. Antes de cada
    candle de detecção, as colunas são NaN.
    """
    df = _df_with_trough_then_peak(n=140, trough_idx=30, peak_idx=80)
    out = detect_pivots(df)

    # Antes do candle de detecção do swing high (X=130), swing_high_level
    # deve ser NaN em todos os candles.
    for i in range(130):
        assert np.isnan(out['swing_high_level'].iloc[i]), (
            f'swing_high_level.iloc[{i}] deveria ser NaN, era {out["swing_high_level"].iloc[i]}'
        )

    # No candle de detecção: nível = high do candle do peak (idx=80) = 100.
    assert np.isclose(out['swing_high_level'].iloc[130], 100.0)
    # E o idx é a posição do peak real = 80.
    assert np.isclose(out['swing_high_idx'].iloc[130], 80.0)


# ============================================================
# 3. swing low detection
# ============================================================

def test_swing_low_basic_detection() -> None:
    """Análogo do teste 2 para swing low. Único trough em idx=20:
    swing_low_level em X=20+50=70 com valor 5; NaN antes."""
    df = _make_flat_df(140)
    df.loc[20, 'low'] = 5.0
    out = detect_pivots(df)

    for i in range(70):
        assert np.isnan(out['swing_low_level'].iloc[i])

    assert np.isclose(out['swing_low_level'].iloc[70], 5.0)
    assert np.isclose(out['swing_low_idx'].iloc[70], 20.0)


# ============================================================
# 4. internal pivots (size=5)
# ============================================================

def test_internal_pivots_detection_with_size_5() -> None:
    """internal_length=5: trough em idx=10 -> internal_low em X=15.
    Pico em idx=20 -> internal_high em X=25 (precedido pelo trough,
    então leg transiciona 0->1->0 corretamente).
    """
    df = _df_with_trough_then_peak(n=40, trough_idx=10, peak_idx=20)
    out = detect_pivots(df, internal_length=5)

    # Internal low em X=15
    assert np.isclose(out['internal_low_level'].iloc[15], 10.0)
    assert np.isclose(out['internal_low_idx'].iloc[15], 10.0)
    # Internal high em X=25
    assert np.isclose(out['internal_high_level'].iloc[25], 100.0)
    assert np.isclose(out['internal_high_idx'].iloc[25], 20.0)


# ============================================================
# 5. equal high alert dentro do threshold
# ============================================================

def test_equal_high_alert_when_within_threshold() -> None:
    """Sequência trough -> peak1 (100) -> trough -> peak2 (100.5).
    equal_length=3, atr fixa=10, threshold=0.1 -> threshold_abs=1.0.
    Distância entre peaks = 0.5 < 1.0 -> alert dispara em X=43.
    """
    n = 60
    df = _make_flat_df(n)
    df.loc[10, 'low'] = 5.0     # trough 1 -> equal_low em X=13
    df.loc[20, 'high'] = 100.0  # peak 1  -> equal_high em X=23
    df.loc[30, 'low'] = 5.0     # trough 2 -> equal_low em X=33
    df.loc[40, 'high'] = 100.5  # peak 2  -> equal_high em X=43 (alert)

    atr = pd.Series(np.full(n, 10.0), index=df.index)
    out = detect_pivots(
        df, equal_length=3, equal_threshold=0.1, atr=atr,
    )

    # Os 2 equal_high se materializam nos candles esperados.
    assert np.isclose(out['equal_high_level'].iloc[23], 100.0)
    assert np.isclose(out['equal_high_level'].iloc[43], 100.5)

    # No primeiro pico não há prev_equal_high_level conhecido -> alert False.
    assert bool(out['equal_high_alert'].iloc[23]) is False
    # No segundo pico, distância 0.5 < 1.0 -> alert True.
    assert bool(out['equal_high_alert'].iloc[43]) is True


# ============================================================
# 6. equal high alert FORA do threshold
# ============================================================

def test_equal_high_alert_NOT_triggered_when_outside_threshold() -> None:
    """Mesma sequência do teste 5 mas peak 2 = 105 (distância 5.0 >
    threshold_abs=1.0). Alert nunca dispara em nenhum candle."""
    n = 60
    df = _make_flat_df(n)
    df.loc[10, 'low'] = 5.0
    df.loc[20, 'high'] = 100.0
    df.loc[30, 'low'] = 5.0
    df.loc[40, 'high'] = 105.0  # distância 5.0 > 1.0

    atr = pd.Series(np.full(n, 10.0), index=df.index)
    out = detect_pivots(
        df, equal_length=3, equal_threshold=0.1, atr=atr,
    )

    # Pico 2 ainda materializa o nível, mas alert não dispara.
    assert np.isclose(out['equal_high_level'].iloc[43], 105.0)
    assert not out['equal_high_alert'].any(), (
        'equal_high_alert deveria ser False em todos os candles'
    )


# ============================================================
# 7. truncation invariance (anti-lookahead)
# ============================================================

def test_no_lookahead_truncation_invariance() -> None:
    """Princípio §5.3 SMC_PRINCIPIOS_E_LEGADO: detect_pivots(df.iloc[:N])
    deve produzir colunas byte-idênticas a detect_pivots(df).iloc[:N]
    no intervalo onde ambos têm dados suficientes (X-50 < N).

    Construímos 200 candles com padrão senoidal grosseira para gerar
    múltiplos pivots; comparamos as 14 colunas no recorte iloc[:100]
    (N-swings_length = 150-50 = 100).

    ATR é fornecida explicitamente em ambas as chamadas, fatiada no
    mesmo recorte, para tornar a comparação determinística (sem
    depender do ramp-up Wilder length=200 sobre dados truncados).
    """
    n = 200
    # Senoidal: amplitude 5 sobre base 100, período 13 (irregular relativo
    # a swings_length=50 -> gera pivots espalhados).
    t = np.arange(n)
    base = 100.0 + 5.0 * np.sin(t * 2.0 * np.pi / 13.0)
    high = base + 0.5
    low = base - 0.5
    close = base
    df = pd.DataFrame({
        'high': high, 'low': low, 'close': close,
        'date': pd.date_range('2024-01-01', periods=n, freq='15min'),
    })

    atr_full = pd.Series(np.full(n, 1.0), index=df.index)

    n_trunc = 150
    df_trunc = df.iloc[:n_trunc].copy()
    atr_trunc = atr_full.iloc[:n_trunc]

    out_full = detect_pivots(df, atr=atr_full)
    out_trunc = detect_pivots(df_trunc, atr=atr_trunc)

    cmp_n = n_trunc - 50  # janela onde swing depende só de [X-50..X]
    cols_to_check = [
        'swing_high_level', 'swing_high_idx',
        'swing_low_level', 'swing_low_idx',
        'internal_high_level', 'internal_high_idx',
        'internal_low_level', 'internal_low_idx',
        'equal_high_level', 'equal_high_idx',
        'equal_low_level', 'equal_low_idx',
        'equal_high_alert', 'equal_low_alert',
    ]
    for col in cols_to_check:
        full_slice = out_full[col].iloc[:cmp_n].reset_index(drop=True)
        trunc_slice = out_trunc[col].iloc[:cmp_n].reset_index(drop=True)
        pd.testing.assert_series_equal(
            full_slice, trunc_slice, check_names=False,
            obj=f'truncation invariance falhou em coluna {col!r}',
        )


# ============================================================
# 8. DataFrame curto demais retorna pivots all-NaN
# ============================================================

def test_short_dataframe_returns_all_nan_pivots() -> None:
    """Com n=30 e swings_length=50, shift(50) é NaN em todos os candles
    (faltam dados). Logo: nenhuma transição de leg, nenhum evento,
    swing_*_level e swing_*_idx all-NaN.
    """
    df = _df_with_trough_then_peak(n=30, trough_idx=10, peak_idx=20)
    out = detect_pivots(df)

    for col in ('swing_high_level', 'swing_high_idx',
                'swing_low_level', 'swing_low_idx'):
        assert out[col].isna().all(), (
            f'{col!r} deveria ser all-NaN em DataFrame curto (n=30 < swings_length+1)'
        )
