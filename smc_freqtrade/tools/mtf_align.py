"""
OBJETIVO
    Helper de validação fora do Freqtrade que alinha duas séries OHLCV
    de timeframes diferentes em um único DataFrame, sem lookahead bias,
    espelhando o algoritmo de `merge_informative_pair` do Freqtrade.

    Permite que testes e sandboxes (notadamente o matcher de setups da
    Wave 9.5a) construam o mesmo input multi-TF que a `IStrategy`
    receberia em produção, sem depender de um run completo do Freqtrade.

FONTE DE DADOS
    Algoritmo replicado de
    `freqtrade/freqtrade@develop:freqtrade/strategy/strategy_helper.py:6-116`
    (`merge_informative_pair`, GPL-3.0). Código próprio — não copia
    verbatim, mas espelha:

    - Shift do `date_merge` quando `minutes_base < minutes_inf`
      (linhas 56-61): `open_inf + minutes_inf - minutes_base`. Essa
      é a chave para evitar lookahead — o candle informative só fica
      visível ao base depois que ambos os fechamentos coincidem.
    - Caso especial `timeframe_inf == "1M"` (linhas 52-55) via
      `pd.offsets.MonthBegin(1)`.
    - Backend `pd.merge_ordered(..., fill_method="ffill")` (linhas
      87-94). Comentário upstream: "2.5x faster than separate ffill()".
    - Edge case da borda inicial (linhas 96-109): quando o informative
      começa depois do base e `dataframe.at[0, date_merge]` é NaN,
      preenche as linhas iniciais com o último candle informative
      anterior à primeira data válida — estritamente passado,
      lookahead-safe.
    - `ValueError` quando `minutes_inf < minutes_base` (linhas 65-68).

LIMITAÇÕES CONHECIDAS
    - Mapping de timeframes (`_timeframe_to_minutes`) cobre apenas o
      conjunto operacional do projeto (1m..1w + 1M). Outros valores
      raise `KeyError`. Não há paridade com `timeframe_to_minutes` do
      ccxt — quando o projeto precisar de TFs fora do mapping, estender
      a tabela.
    - `df_base[date_column]` e `df_inf[date_column]` precisam ser
      datetime64 ordenados estritamente crescentes; a função não
      reordena nem deduplica.

NÃO FAZER
    - Não importar `freqtrade.*`. O propósito do helper é justamente
      reproduzir o algoritmo sem depender da árvore Freqtrade.
    - Não usar este helper em código de produção — a `SMCStrategy`
      (Wave 10) consome multi-TF nativamente via `@informative` do
      Freqtrade. Esta função existe **apenas** para sandbox/teste.
    - Não substituir o backend `merge_ordered + ffill` por `merge` +
      `ffill()` separados — o upstream documenta perda de performance
      (~2.5x) e este helper preserva a equivalência operacional.
"""
from __future__ import annotations

import pandas as pd


_TIMEFRAME_MINUTES: dict[str, int] = {
    '1m': 1, '3m': 3, '5m': 5, '15m': 15, '30m': 30,
    '1h': 60, '1H': 60,
    '2h': 120, '2H': 120,
    '4h': 240, '4H': 240,
    '6h': 360, '6H': 360,
    '12h': 720, '12H': 720,
    '1d': 1440, '1D': 1440,
    '1w': 10080, '1W': 10080,
    '1M': -1,
}


def _timeframe_to_minutes(tf: str) -> int:
    """Converte código de timeframe para minutos.

    `1M` retorna sentinela `-1`; o caller detecta e usa
    `pd.offsets.MonthBegin(1)` em vez de um delta fixo.
    """
    if tf not in _TIMEFRAME_MINUTES:
        raise KeyError(
            f'Timeframe desconhecido: {tf!r}. '
            f'Suportados: {sorted(_TIMEFRAME_MINUTES)}.'
        )
    return _TIMEFRAME_MINUTES[tf]


def align_informative(
    df_base: pd.DataFrame,
    df_inf: pd.DataFrame,
    tf_base: str,
    tf_inf: str,
    *,
    date_column: str = 'date',
    ffill: bool = True,
    suffix: str | None = None,
) -> pd.DataFrame:
    """Alinha `df_inf` (timeframe maior) sobre `df_base` (menor) sem lookahead.

    Cada coluna de `df_inf` aparece no output renomeada como
    `{col}_{tf_inf}` (ou `{col}_{suffix}` se `suffix` fornecido), inclusive
    `date`, `open`, `high`, `low`, `close`. O número de linhas do output é
    sempre `len(df_base)`.

    Para a linha `i` do output, a coluna `date_{tf_inf}` carrega o
    timestamp de abertura do **mais recente** candle informative cujo
    fechamento `≤` ao fechamento do candle base `i` — preservando a
    invariante de lookahead-safety verificável aritmeticamente:

        date_inf_merged + minutes_inf  ≤  date_base + minutes_base

    Parameters
    ----------
    df_base, df_inf:
        DataFrames de OHLCV. Não mutados — função copia internamente.
    tf_base, tf_inf:
        Timeframes (e.g. `'4h'`, `'1H'`, `'15m'`, `'1M'`).
    date_column:
        Nome da coluna de timestamp em ambos os DataFrames (default `date`).
    ffill:
        Se `True` (default), preenche valores faltantes via merge_ordered
        + ffill (algoritmo upstream). Se `False`, faz `pd.merge` simples
        sem forward-fill — pode deixar NaN no output.
    suffix:
        Override do sufixo aplicado às colunas do informative. Default é
        `tf_inf`.

    Raises
    ------
    ValueError
        Se `tf_inf` for mais rápido que `tf_base` (espelha mensagem
        upstream linhas 65-68 do `strategy_helper.py`).
    """
    minutes_base = _timeframe_to_minutes(tf_base)
    minutes_inf = _timeframe_to_minutes(tf_inf)

    base = df_base.copy()
    inf = df_inf.copy()

    if minutes_inf != -1 and minutes_base != -1 and minutes_inf < minutes_base:
        raise ValueError(
            'Tried to merge a faster timeframe to a slower timeframe. '
            'This would create new rows, and can throw off your regular indicators.'
        )

    if minutes_inf == minutes_base:
        inf['date_merge'] = inf[date_column]
    elif inf.empty:
        inf['date_merge'] = inf[date_column]
    elif tf_inf == '1M':
        inf['date_merge'] = (
            inf[date_column] + pd.offsets.MonthBegin(1)
        ) - pd.to_timedelta(minutes_base, 'm')
    else:
        inf['date_merge'] = (
            inf[date_column]
            + pd.to_timedelta(minutes_inf, 'm')
            - pd.to_timedelta(minutes_base, 'm')
        )

    col_suffix = suffix if suffix is not None else tf_inf
    date_merge_col = f'date_merge_{col_suffix}'
    inf.columns = [f'{c}_{col_suffix}' for c in inf.columns]

    if ffill:
        out = pd.merge_ordered(
            base,
            inf,
            fill_method='ffill',
            left_on=date_column,
            right_on=date_merge_col,
            how='left',
        )
        if (
            len(out) > 1
            and len(inf) > 0
            and pd.isnull(out.at[0, date_merge_col])
        ):
            first_valid_idx = out[date_merge_col].first_valid_index()
            if first_valid_idx:
                first_valid_date_merge = out.at[first_valid_idx, date_merge_col]
                prior = inf[inf[date_merge_col] < first_valid_date_merge]
                if not prior.empty:
                    out.loc[: first_valid_idx - 1] = out.loc[
                        : first_valid_idx - 1
                    ].fillna(prior.iloc[-1])
    else:
        out = pd.merge(
            base, inf, left_on=date_column, right_on=date_merge_col, how='left'
        )

    out = out.drop(date_merge_col, axis=1)
    return out
