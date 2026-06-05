"""Smoke tests da Wave 10a — scaffold SMCStrategy (IStrategy) + MTF.

OBJETIVO
    Selar o plumbing determinístico do scaffold sem decidir trade:
    T1 carga/instanciação; T2 pipeline base (analyze + compute_setup_state
    sobre o df mergeado); T3 no-op de entrada/saída; T4 fronteira causal
    (consome `active_*`/`setup_*`, nunca ledgers); T5 paridade
    `align_informative` (espelho) ↔ `merge_informative_pair` (Freqtrade).

FONTE DE DADOS
    Golden CSV `tests/golden/data/btc_usdt_swap_{15m,1h,4h}_window.csv`
    (mesma janela Jan–Abr/2026). Engine `smc_engine.analyze`; matcher
    `smc_engine.compute_setup_state`; merge de teste `tools.mtf_align.
    align_informative` (espelho sancionado de `merge_informative_pair`,
    Wave 9.4). A estratégia é importada de `user_data/strategies/SMCStrategy.py`.

LIMITAÇÕES CONHECIDAS
    Não roda backtest, `recursive-analysis` nem `lookahead-analysis` (10b/10c
    e/ou exigem exchange/dados na VM). T2 usa `align_informative` para montar
    o input multi-TF que a IStrategy receberia em produção via `@informative`
    (paridade selada por T5).

NÃO FAZER
    Não validar contra LuxAlgo TradingView (dados de mecânica, não oráculo
    visual). Não introduzir lógica de sinal.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

_SUBPROJECT_ROOT = Path(__file__).resolve().parents[1]
_STRATEGIES_DIR = _SUBPROJECT_ROOT / "user_data" / "strategies"
_GOLDEN_DIR = _SUBPROJECT_ROOT / "tests" / "golden" / "data"

for _p in (str(_SUBPROJECT_ROOT), str(_STRATEGIES_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from smc_engine import analyze  # noqa: E402
from tools.mtf_align import align_informative  # noqa: E402

from SMCStrategy import SMCStrategy  # noqa: E402


def _load_golden(tf: str) -> pd.DataFrame:
    """Carrega o golden de um TF como OHLCV com `date` datetime naive (UTC)."""
    df = pd.read_csv(_GOLDEN_DIR / f"btc_usdt_swap_{tf}_window.csv")
    df = df.rename(columns={"timestamp_utc": "date"})
    df["date"] = pd.to_datetime(df["date"], utc=True).dt.tz_localize(None)
    return df[["date", "open", "high", "low", "close", "volume"]]


def _merged_base() -> pd.DataFrame:
    """Monta o df base 15m mergeado com `_4h`/`_1h` como a IStrategy receberia.

    Ordem fiel (igual `interface.py::advise_indicators`): roda `analyze()` nos
    informativos, mergeia o resultado (sufixado) sobre a base 15m **crua**.
    `populate_indicators` da estratégia roda o `analyze()` da base depois.
    """
    base = _load_golden("15m")
    inf_4h = analyze(_load_golden("4h")).df
    inf_1h = analyze(_load_golden("1h")).df
    merged = align_informative(base, inf_4h, "15m", "4h", suffix="4h")
    merged = align_informative(merged, inf_1h, "15m", "1h", suffix="1h")
    return merged


@pytest.fixture(scope="module")
def strategy() -> SMCStrategy:
    """Instância mínima da SMCStrategy (config só com `candle_type_def`)."""
    from freqtrade.enums import CandleType

    return SMCStrategy({"candle_type_def": CandleType.FUTURES})


# === T1 — carga ===

def test_t1_import_and_instantiate(strategy):
    """Importar e instanciar não lança; atributos de interface corretos."""
    assert strategy.INTERFACE_VERSION == 3
    assert strategy.timeframe == "15m"
    assert strategy.can_short is True
    assert strategy.process_only_new_candles is True
    assert strategy.startup_candle_count >= 200
    # Dois informativos registrados (1H e 4H).
    tfs = sorted(inf.timeframe for inf, _ in strategy._ft_informative)
    assert tfs == ["1h", "4h"]


# === T2 — pipeline base ===

def test_t2_populate_indicators_pipeline(strategy):
    """`populate_indicators` roda fim-a-fim: colunas base + `_1h`/`_4h` +
    `compute_setup_state` sem `ValueError`; colunas de setup presentes."""
    merged = _merged_base()
    assert "swing_trend_bias_4h" in merged.columns
    assert "active_bull_swing_ob_top_1h" in merged.columns

    out = strategy.populate_indicators(merged, {"pair": "BTC/USDT:USDT"})

    for col in ("setup_id", "setup_state", "setup_direction"):
        assert col in out.columns
    # Colunas base do engine presentes (sem sufixo).
    assert "swing_trend_bias" in out.columns
    # A FSM realizou ao menos um estado na janela golden.
    assert out["setup_state"].notna().sum() > 0


# === T3 — sem sinal quando não há CONFIRMED (atualizado na 10b) ===

def test_t3_no_signal_without_confirmed(strategy):
    """Sem nenhum `CONFIRMED`, `populate_entry/exit_trend` não emitem sinais.

    NOTA 10b: a 10a tinha `populate_entry_trend` como no-op puro; a 10b passou a
    emitir entrada STRICT em `CONFIRMED` (lendo `setup_state`/`setup_direction`/
    `setup_id`, sempre presentes após `populate_indicators`). Este teste preserva
    a garantia 10a-equivalente — nenhuma entrada quando não há `CONFIRMED` — com
    o df já carregando as colunas do matcher (não-CONFIRMED). `populate_exit_trend`
    permanece no-op (a saída determinística da 10b vive em `custom_exit`).
    """
    df = _load_golden("15m").head(50).copy()
    # Colunas do matcher como em produção (após `populate_indicators`), sem
    # nenhum CONFIRMED na janela.
    df["setup_state"] = "ARMED"
    df["setup_direction"] = "long"
    df["setup_id"] = "armed_placeholder"

    entry = strategy.populate_entry_trend(df.copy(), {"pair": "BTC/USDT:USDT"})
    exit_ = strategy.populate_exit_trend(df.copy(), {"pair": "BTC/USDT:USDT"})
    for frame in (entry, exit_):
        for col in ("enter_long", "enter_short", "exit_long", "exit_short"):
            if col in frame.columns:
                assert (frame[col].fillna(0) == 1).sum() == 0


# === T4 — fronteira causal: active_*/setup_*, nunca ledgers ===

def test_t4_no_ledger_columns_in_output(strategy):
    """A saída de `populate_indicators` não carrega colunas de ledger; carrega
    `active_*`/`setup_*` (colunas causais)."""
    out = strategy.populate_indicators(_merged_base(), {"pair": "BTC/USDT:USDT"})
    leaky = [c for c in out.columns if "t_mitigation" in c or "t_invalidation" in c]
    assert leaky == []
    assert any(c.startswith("active_") for c in out.columns)
    assert any(c.startswith("setup_") for c in out.columns)


def test_t4_source_never_reads_ledgers():
    """O código da estratégia não acessa `ledger_*` em `populate_*` (vazamento
    de futuro). Verificação textual sobre o fonte."""
    src = (_STRATEGIES_DIR / "SMCStrategy.py").read_text(encoding="utf-8")
    # `analyze(dataframe).df` é o único campo consumido; nenhum `.ledger_`.
    assert ".ledger_" not in src


# === T5 — paridade sandbox↔produção (sela a equivalência da Wave 9.4) ===

def test_t5_align_informative_matches_merge_informative_pair():
    """`align_informative` (tools) e `merge_informative_pair` (Freqtrade)
    produzem o mesmo alinhamento/sufixos na janela golden."""
    from freqtrade.strategy import merge_informative_pair

    base = _load_golden("15m")
    inf = analyze(_load_golden("4h")).df

    mirror = align_informative(base, inf, "15m", "4h", suffix="4h")
    native = merge_informative_pair(
        base, inf, "15m", "4h", ffill=True, append_timeframe=False, suffix="4h"
    )

    assert list(mirror.columns) == list(native.columns)
    assert len(mirror) == len(native)
    # Colunas-chave consumidas pelo matcher + OHLC informativo: idênticas.
    for col in ("swing_trend_bias_4h", "active_bull_swing_ob_top_4h",
                "close_4h", "date_4h"):
        pd.testing.assert_series_equal(
            mirror[col], native[col], check_names=False
        )
