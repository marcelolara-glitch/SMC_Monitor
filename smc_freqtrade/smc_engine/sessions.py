"""Killzones Silver Bullet por candle (Wave 9.5d, HOOKS §10.6).

OBJETIVO
    Anexar, por candle, 3 colunas booleanas que marcam pertencimento às
    3 killzones Silver Bullet do ICT/HOOKS §10.6, em horário de
    Nova York (NY-time, com DST): 03:00-04:00, 10:00-11:00 e
    14:00-15:00. Insumo puro (hook) da assinatura A7 (Silver Bullet) da
    Wave 9.5e — esta wave NÃO emite sinal, só materializa a marca.

FONTE DE DADOS
    - `df['date']` — o instante T de cada candle, em um dos dois tipos
      homogêneos aceitos por `engine._validate_input`:
        * `pd.Timestamp` (datetime64), tz-aware ou tz-naive;
        * `int`/`int64` (contrato do projeto: epoch em milissegundos).
    - Fronteiras das killzones: HOOKS §10.6 verbatim (3-4 AM / 10-11 AM /
      2-3 PM NY). Conversão de fuso via `zoneinfo.ZoneInfo`
      ("America/New_York"), que já resolve EST↔EDT (DST).

    Semântica de cada janela: `[início, fim)` sobre o **próprio**
    timestamp do candle — lookahead-safe trivial (só lê o presente).

LIMITAÇÕES CONHECIDAS
    - Apenas as 3 killzones Silver Bullet do §10.6. Sessões completas
      London/Asian/NY não têm fronteira citável no doc e ficam fora
      desta wave (§0 do briefing: não inferir).
    - Em timeframe 4h, o alinhamento da grade às horas NY faz com que
      **somente a janela AM (03:00-04:00)** materialize candle; as
      janelas 10-11 AM e 2-3 PM ficam sempre `False` no 4h. Isto é
      esperado (A7 é sinal de 15m/1h), não bug.
    - `date` tz-naive é assumido como UTC antes da conversão (contrato
      do projeto / golden).

NÃO FAZER
    - Não usar `shift(-N)` (lookahead proibido).
    - Não mutar o `df` do caller — opera sobre cópia e só anexa colunas.
    - Não criar colunas de sessão London/Asian/NY (sem fronteira
      citável).
    - Não importar `freqtrade`.
"""
from __future__ import annotations

from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

# === Constantes de coluna (HOOKS §10.6) ===
COL_IN_KZ_SILVER_BULLET_AM = 'in_kz_silver_bullet_am'      # 03:00-04:00 NY
COL_IN_KZ_SILVER_BULLET_LATE = 'in_kz_silver_bullet_late'  # 10:00-11:00 NY
COL_IN_KZ_SILVER_BULLET_PM = 'in_kz_silver_bullet_pm'      # 14:00-15:00 NY

SESSION_COLUMNS = (
    COL_IN_KZ_SILVER_BULLET_AM,
    COL_IN_KZ_SILVER_BULLET_LATE,
    COL_IN_KZ_SILVER_BULLET_PM,
)

# Fronteiras `[início, fim)` em hora NY (HOOKS §10.6 verbatim).
_KILLZONE_WINDOWS = (
    (COL_IN_KZ_SILVER_BULLET_AM, 3, 4),
    (COL_IN_KZ_SILVER_BULLET_LATE, 10, 11),
    (COL_IN_KZ_SILVER_BULLET_PM, 14, 15),
)

_NY_TZ = ZoneInfo("America/New_York")


def _ny_hour(date_series: pd.Series) -> np.ndarray:
    """Deriva a hora NY (0-23) de cada candle, cobrindo os 3 tipos de `date`.

    Casos (D-D2 do briefing), todos resolvidos para um índice tz-aware
    em "America/New_York" (DST automático via `zoneinfo`):
        - `int`/`int64` → epoch-ms: `pd.to_datetime(unit='ms', utc=True)`.
        - datetime tz-aware → convertido direto para UTC e então NY.
        - datetime tz-naive → assumido UTC (`tz_localize('UTC')`).

    Retorna `np.ndarray[int]` com a hora local NY de cada linha.
    """
    s = pd.Series(date_series).reset_index(drop=True)
    if pd.api.types.is_integer_dtype(s.dtype):
        ts = pd.to_datetime(s, unit='ms', utc=True)
    else:
        ts = pd.to_datetime(s)
        if ts.dt.tz is None:
            ts = ts.dt.tz_localize('UTC')
        else:
            ts = ts.dt.tz_convert('UTC')
    ny = ts.dt.tz_convert(_NY_TZ)
    return ny.dt.hour.to_numpy()


def tag_sessions(df: pd.DataFrame) -> pd.DataFrame:
    """Anexa as 3 colunas booleanas de killzone Silver Bullet (NY-time).

    Cada coluna `c` é `(hora_ny >= ini) & (hora_ny < fim)` em dtype
    `bool` (nunca `object`/NaN), com `[ini, fim)` do §10.6. Não muta o
    `df` de entrada (opera sobre cópia; só anexa `SESSION_COLUMNS` ao
    fim).

    Args:
        df: DataFrame com coluna `date` (homogênea: `pd.Timestamp` ou
            `int` epoch-ms), conforme `engine._validate_input`.

    Returns:
        Cópia de `df` + 3 colunas booleanas (`SESSION_COLUMNS`).
    """
    out = df.copy()
    hour = _ny_hour(df['date'])
    for col, ini, fim in _KILLZONE_WINDOWS:
        out[col] = (hour >= ini) & (hour < fim)
    return out
