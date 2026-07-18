"""
OBJETIVO
    Cobrir o branch de *head-fill* de `tools.mtf_align.align_informative`
    (linhas ~170-188): as primeiras linhas da base que antecedem o 1º candle
    informativo fechado são preenchidas com o último candle informativo
    estritamente anterior à janela (`prior.iloc[-1]`).

    Esse branch nunca foi exercitado pelos goldens (janelas alinhadas — código
    morto em teste até a Wave 10.6). A produção (P3, 3ª tentativa) o executou
    pela primeira vez com base iniciando no MEIO de um candle informativo e
    crashou: `.fillna(prior.iloc[-1])` carregava `None` nas colunas object
    `equal_{high,low}_pivot_indices`, e o `fillna` dict-like rejeita valor
    `None` por coluna com `ValueError: Must specify a fill 'value' or 'method'`.

    A correção constrói o mapa de fill EXCLUINDO as entradas `None`
    (`{k: v for k, v in prior.iloc[-1].items() if v is not None}`): preencher
    NaN com `None` é no-op por definição — pular a entrada é idêntico ao
    pretendido, e colunas object sem pivot equal acumulado permanecem vazias no
    head (estado correto). Cada `Tn` mapeia 1:1 ao critério `§3.n` do briefing
    da Wave 10.6.

FONTE DE DADOS
    T1/T2: DataFrames sintéticos pequenos (≤ 40 linhas) via `pd.date_range`.
        Determinísticos, sem freqtrade.
    T3: goldens MTF reais `tests/golden/data/btc_usdt_swap_{15m,1h,4h}_window.csv`,
        com a base 15m FATIADA para iniciar no meio de um candle 4h — o cenário
        exato do P3 — rodando o pipeline da Candidate (padrão do
        `test_smoke_wave10_5.py`) até `require_candidate_columns`.

NÃO FAZER
    - Não importar `freqtrade.*` (a suíte sandbox deve coletar sem freqtrade).
    - Não tocar engine, estratégias, config ou o comportamento do caminho
      alinhado.
"""
from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path

import pandas as pd

_SUBPROJECT_ROOT = Path(__file__).resolve().parents[1]
_STRATEGIES_DIR = _SUBPROJECT_ROOT / "user_data" / "strategies"
_GOLDEN_DIR = _SUBPROJECT_ROOT / "tests" / "golden" / "data"

for _p in (str(_SUBPROJECT_ROOT), str(_STRATEGIES_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from tools.mtf_align import align_informative  # noqa: E402


def _mk_base_15m(start: str, periods: int) -> pd.DataFrame:
    return pd.DataFrame({
        "date": pd.date_range(start, periods=periods, freq="15min", tz="UTC"),
        "close": list(range(periods)),
    })


# ============================================================
# T1 / §3.1 — branch antes morto, agora coberto:
#   base 15m iniciando no MEIO de um candle 4h, informativo com uma coluna
#   object `None` na linha de preenchimento e uma coluna numérica com valor.
# ============================================================

def test_t1_head_fill_skips_none_object_columns():
    """Base 15m começa 09:15 (meio do candle 4h 08:00-12:00). O informativo 4h
    tem candles em 00:00/04:00/08:00/12:00; o candle 04:00 (`date_merge`=07:45,
    estritamente anterior a 09:15) é a `prior.iloc[-1]` que preenche o head.

    Esse candle carrega `None` em `equal_high_pivot_indices` (coluna object,
    sem pivot equal acumulado) e `100.0` em `close`. Asserts:
      (i)   não levanta (o bug do P3 era `ValueError` aqui);
      (ii)  o head da coluna NUMÉRICA é preenchido com o valor prévio (100.0);
      (iii) o head da coluna object-`None` permanece NaN/None (no-op correto).
    """
    # 09:15 = 37 candles de 15m após 00:00 — dentro do candle 4h 08:00-12:00.
    base = _mk_base_15m("2026-01-01 09:15", 16)
    inf = pd.DataFrame({
        "date": pd.date_range("2026-01-01 04:00", periods=4, freq="4h", tz="UTC"),
        "close": [100.0, 101.0, 102.0, 103.0],
        # object com `None` na 1ª linha (o candle 04:00 que preenche o head).
        "equal_high_pivot_indices": pd.Series(
            [None, [1, 2], None, [3]], dtype=object
        ),
    })

    # (i) não levanta.
    out = align_informative(base, inf, "15m", "4h")

    # O 1º `date_merge` coincidente é 11:45 (candle 08:00); as 10 primeiras
    # linhas (09:15..11:30) são o head preenchido pelo candle 04:00 — cujas
    # colunas NÃO-None (date, close) carregam o valor prévio.
    assert (
        out["date_4h"].iloc[:10] == pd.Timestamp("2026-01-01 04:00", tz="UTC")
    ).all(), (
        "head deve carregar a `date` do candle informativo anterior (04:00)"
    )
    # (ii) coluna numérica preenchida com o valor prévio (candle 04:00).
    assert (out["close_4h"].iloc[:10] == 100.0).all(), (
        "head numérico deve carregar o close do candle informativo anterior"
    )
    # (iii) coluna object-`None` permanece vazia no head (no-op, estado correto).
    assert out["equal_high_pivot_indices_4h"].iloc[:10].isna().all(), (
        "head da coluna object cujo valor prévio é None permanece NaN/None"
    )
    # A partir da 1ª coincidência (11:45), o merge assume o candle 08:00.
    assert out["close_4h"].iloc[10] == 101.0
    assert out["equal_high_pivot_indices_4h"].iloc[10] == [1, 2]


# ============================================================
# T2 / §3.2 — regressão byte-idêntica no caminho alinhado:
#   dados alinhados (padrão golden) ⇒ o branch de head-fill NÃO executa e a
#   saída é idêntica a um merge_ordered+ffill sem o bloco de head-fill.
# ============================================================

def test_t2_aligned_path_byte_identical_no_head_fill():
    """Base 15m e informativo 4h ambos iniciando 00:00 (padrão dos goldens).

    Não há candle informativo ANTERIOR à janela → `prior` é vazio e o bloco de
    head-fill é pulado (a mudança da Wave 10.6 é inerte). A saída deve ser
    `df.equals` a uma reconstrução direta via `merge_ordered(fill_method=ffill)`
    SEM o bloco de head-fill — prova local de que o caminho alinhado não mudou
    (os pins golden existentes são a prova sistêmica).
    """
    base = _mk_base_15m("2026-01-01 00:00", 40)
    inf = pd.DataFrame({
        "date": pd.date_range("2026-01-01 00:00", periods=3, freq="4h", tz="UTC"),
        "close": [100.0, 101.0, 102.0],
        "equal_low_pivot_indices": pd.Series([None, [1, 2], None], dtype=object),
    })

    out = align_informative(base, inf, "15m", "4h")

    # Reconstrução do caminho alinhado sem o head-fill (espelha a função).
    ref_inf = inf.copy()
    ref_inf["date_merge"] = (
        ref_inf["date"]
        + pd.to_timedelta(240, "m")
        - pd.to_timedelta(15, "m")
    )
    ref_inf.columns = [f"{c}_4h" for c in ref_inf.columns]
    ref = pd.merge_ordered(
        base, ref_inf,
        fill_method="ffill",
        left_on="date", right_on="date_merge_4h", how="left",
    ).drop("date_merge_4h", axis=1)

    # Sem candle anterior à janela, o head permanece NaN (branch inerte).
    assert out["date_4h"].iloc[:15].isna().all()
    assert out.equals(ref), (
        "caminho alinhado divergiu de merge_ordered+ffill sem head-fill"
    )


# ============================================================
# T3 / §3.3 — fumaça do pipeline de produção com base DESALINHADA
#   (o cenário exato do P3), até `require_candidate_columns` OK.
# ============================================================

def _load_ohlcv(name: str) -> pd.DataFrame:
    df = pd.read_csv(_GOLDEN_DIR / name)
    df["date"] = pd.to_datetime(df["timestamp_utc"], utc=True)
    return df[["date", "open", "high", "low", "close", "volume"]]


@lru_cache(maxsize=1)
def _misaligned_candidate_pipeline() -> pd.DataFrame:
    """Replica o pipeline de `SMCStrategyCandidate.populate_indicators`
    (padrão `test_smoke_wave10_5.py`) com a base 15m FATIADA para iniciar no
    meio de um candle 4h — o cenário exato do P3 que exercita o head-fill.

    Importado tardiamente para não pagar `analyze`/`candidate_frozen` na coleta
    quando o teste é deselecionado.
    """
    from smc_engine import analyze, tag_sessions
    from smc_engine.setup_state import compute_setup_state_multi
    from candidate_frozen import build_cfg_c, build_cfg_r

    raw_15m = _load_ohlcv("btc_usdt_swap_15m_window.csv")
    # 37 candles de 15m = 9h15 → base começa 09:15, MEIO do candle 4h 08:00.
    sliced = raw_15m.iloc[37:].reset_index(drop=True)
    assert sliced["date"].iloc[0] == pd.Timestamp("2026-01-01 09:15", tz="UTC")

    base = analyze(sliced).df
    res_1h = analyze(_load_ohlcv("btc_usdt_swap_1h_window.csv")).df
    res_4h = analyze(_load_ohlcv("btc_usdt_swap_4h_window.csv")).df

    merged = align_informative(base, res_1h, "15m", "1h", suffix="1h")
    merged = align_informative(merged, res_4h, "15m", "4h", suffix="4h")
    merged = tag_sessions(merged)
    merged = compute_setup_state_multi(merged, build_cfg_c())
    merged = compute_setup_state_multi(merged, build_cfg_r())
    return merged


def test_t3_p3_misaligned_pipeline_runs_and_columns_present():
    """O pipeline da Candidate com base desalinhada (P3) roda sem levantar e
    produz as colunas exigidas pela entrada — antes da correção, os dois
    `align_informative` (`_1h` e `_4h`) crashavam no head-fill com
    `ValueError: Must specify a fill 'value' or 'method'`.
    """
    from candidate_frozen import require_candidate_columns

    df = _misaligned_candidate_pipeline()
    # Sanidade: a base foi encurtada mas segue longa (head-fill exercitado).
    assert len(df) > 11000
    # Não deve levantar (todas as colunas setup_state/direction__{sid} presentes).
    require_candidate_columns(df.columns)
