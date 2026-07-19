"""ka_data — OHLCV sintético determinístico + colunas de setup injetadas (Wave 10.2).

OBJETIVO
    Fonte única, **sem aleatoriedade**, dos cenários known-answer (GE-0). Cada
    cenário é um dicionário-dado (`SCENARIOS`) que descreve:
      (1) o OHLCV 15m sintético (preços escolhidos à mão para que entrada, SL
          ancorado e alvo R:R caiam em valores exatos);
      (2) os "eventos" de setup por assinatura (`sid`) — em qual vela o estado
          fica `CONFIRMED`, direção, zona (`zone_low`/`zone_high`), `setup_id` e,
          opcionalmente, a vela em que o setup passa a `INVALIDATED`;
      (3) as expectativas derivadas à mão (`expect`) que o teste compara com o
          resultado do loop de backtest **real** do Freqtrade.

    A partir desse dado, `build_ohlcv` monta o DataFrame OHLCV e
    `build_setup_columns` injeta as 7 `SETUP_OUTPUT_COLUMNS` sufixadas
    (`{col}__{sid}`) para os 9 sids da candidata — é o material que
    `KnownAnswerStrategy.populate_indicators` devolve no lugar de `analyze()`.

REGRAS DE FILL/SAÍDA DO FREQTRADE (versão instalada, confirmadas no código)
    - **Entrada = open da vela seguinte ao sinal.** `Backtesting._get_ohlcv_as_lists`
      aplica `.shift(1)` nas colunas de sinal (`optimize/backtesting.py`), e o
      preenchimento usa `row[OPEN_IDX]` — logo o sinal emitido na vela N preenche
      no open da vela N+1.
    - **Saída por `custom_exit` (R:R ou invalidação) = open da vela em que o
      callback dispara.** `should_exit` chama `custom_exit` com
      `current_rate = row[OPEN_IDX]` (`strategy/interface.py`) e `_get_close_rate`
      devolve `row[OPEN_IDX]` para saídas do tipo sinal/custom.
    - **Saída por SL ancorado = preço exato do stop** (`_get_close_rate_for_stoploss`
      devolve `trade.stop_loss` quando o stop está dentro do range da vela; só cai
      no open se o stop ficou além do range — gap).
    - **Fee por perna:** `Backtesting.set_fee` lê `config["fee"]` e `_enter_trade`
      grava `fee_open = fee_close = self.fee` — o custo incide nas DUAS pernas.

DERIVAÇÃO DO P&L (long; short é espelho), leverage 1, `contractSize=1`:
    amount   = stake / entry
    valor_abertura = amount * entry * (1 + fee)
    valor_fecho    = amount * exit  * (1 - fee)
    profit_abs = valor_fecho - valor_abertura
               = stake * [ (exit/entry) * (1 - fee) - (1 + fee) ]
    (short: profit_abs = stake * [ (1 - fee) - (exit/entry) * (1 + fee) ])
    R (risco) = |entry - sl_anchor|;  sl_anchor(long) = zone_low * (1 - buffer),
    sl_anchor(short) = zone_high * (1 + buffer), com buffer = sl_zone_buffer_pct.

NÃO FAZER
    - Não importar freqtrade aqui (o módulo é dado puro; o guard de import fica
      no test_*).
    - Não fabricar OHLCV que dispare a FSM real — a injeção é deliberada (§1 do
      briefing 10.2): o golden já valida a engine; aqui validamos a execução.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

_SUBPROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_SUBPROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_SUBPROJECT_ROOT))

from smc_engine.setup_state import (  # noqa: E402
    STATE_CONFIRMED,
    STATE_PENDING,
    STATE_INVALIDATED,
    DIRECTION_LONG,
    DIRECTION_SHORT,
    SETUP_OUTPUT_COLUMNS,
)

# Todos os sids da candidata (Grupo C + Grupo R), na ordem de layout.
SIDS_GRUPO_C = ('A3', 'A2', 'A4a', 'A1', 'A9', 'A6', 'A10')
SIDS_GRUPO_R = ('A5', 'A7')
ALL_SIDS = SIDS_GRUPO_C + SIDS_GRUPO_R

PAIR = "SYNTH/USDT:USDT"
TIMEFRAME = "15m"
STAKE = 100.0
FEE = 0.0005                 # espelha config_backtest.json["fee"]
BUFFER = 0.001               # espelha SMCStrategy.sl_zone_buffer_pct
RR = 2.0                     # espelha SMCStrategy.rr_target
START = "2026-01-01 00:00:00"


# ------------------------------------------------------------------
# Definição dos cenários (dado puro — a fonte da verdade do GE-0)
# ------------------------------------------------------------------
# Campos por cenário:
#   n        : nº de velas
#   base     : preço "plano" default (open=high-.. etc. em torno dele)
#   ohlcv    : dict {idx: (open, high, low, close)} — overrides por vela
#   sids     : dict {sid: {...}} — eventos de setup por assinatura:
#                signal_idx, direction, zone_low, zone_high, setup_id,
#                invalidate_idx (opcional)
#   note     : descrição curta
#
# `expect` é preenchido/derivado no teste (não aqui) para manter este módulo
# como dado bruto; o helper `derive` abaixo calcula os valores à mão.

def _flat(n: int, base: float) -> dict:
    return {}


SCENARIOS: dict = {
    # K1 — long → alvo R:R (custom_exit / smc_rr_target).
    "K1": {
        "n": 8, "base": 1000.0,
        "sids": {"A3": {"signal_idx": 1, "direction": DIRECTION_LONG,
                        "zone_low": 990.0, "zone_high": 1010.0, "setup_id": "kaK1"}},
        # entrada = open[2] = 1000. anchor = 990*0.999 = 989.01 ; R = 10.99 ;
        # alvo = 1000 + 2*10.99 = 1021.98. Primeiro open >= alvo é a vela 4 (=1022).
        "ohlcv": {3: (1005.0, 1006.0, 1004.0, 1005.0),
                  4: (1022.0, 1023.0, 1021.0, 1022.0),
                  5: (1022.0, 1023.0, 1021.0, 1022.0),
                  6: (1022.0, 1023.0, 1021.0, 1022.0),
                  7: (1022.0, 1023.0, 1021.0, 1022.0)},
        "note": "long TP via R:R; exit no open da vela 4 = 1022.",
    },
    # K2 — long → SL ancorado (custom_stoploss / stoploss).
    "K2": {
        "n": 8, "base": 1000.0,
        "sids": {"A3": {"signal_idx": 1, "direction": DIRECTION_LONG,
                        "zone_low": 990.0, "zone_high": 1010.0, "setup_id": "kaK2"}},
        # entrada = open[2] = 1000. anchor = 989.01. Vela 4 varre o anchor:
        # high>=989.01>=low -> saída EXATA no anchor 989.01.
        "ohlcv": {3: (998.0, 999.0, 997.0, 998.0),
                  4: (995.0, 996.0, 985.0, 986.0),
                  5: (986.0, 987.0, 985.0, 986.0),
                  6: (986.0, 987.0, 985.0, 986.0),
                  7: (986.0, 987.0, 985.0, 986.0)},
        "note": "long SL ancorado; exit no anchor 989.01 (~ -1R).",
    },
    # K3 — short → alvo R:R (espelho de K1).
    "K3": {
        "n": 8, "base": 1000.0,
        "sids": {"A5": {"signal_idx": 1, "direction": DIRECTION_SHORT,
                        "zone_low": 990.0, "zone_high": 1010.0, "setup_id": "kaK3"}},
        # entrada = open[2] = 1000. anchor(short) = 1010*1.001 = 1011.01 ;
        # R = 11.01 ; alvo(short) = 1000 - 2*11.01 = 977.98. 1o open <= alvo: vela 4 (=977).
        "ohlcv": {3: (995.0, 996.0, 994.0, 995.0),
                  4: (977.0, 978.0, 976.0, 977.0),
                  5: (977.0, 978.0, 976.0, 977.0),
                  6: (977.0, 978.0, 976.0, 977.0),
                  7: (977.0, 978.0, 976.0, 977.0)},
        "note": "short TP via R:R; exit no open da vela 4 = 977.",
    },
    # K4 — short → SL ancorado (espelho de K2).
    "K4": {
        "n": 8, "base": 1000.0,
        "sids": {"A5": {"signal_idx": 1, "direction": DIRECTION_SHORT,
                        "zone_low": 990.0, "zone_high": 1010.0, "setup_id": "kaK4"}},
        # entrada = open[2] = 1000. anchor(short) = 1011.01. Vela 4 varre:
        # low<=1011.01<=high -> saída EXATA no anchor 1011.01.
        "ohlcv": {3: (1002.0, 1003.0, 1001.0, 1002.0),
                  4: (1005.0, 1015.0, 1004.0, 1014.0),
                  5: (1014.0, 1015.0, 1013.0, 1014.0),
                  6: (1014.0, 1015.0, 1013.0, 1014.0),
                  7: (1014.0, 1015.0, 1013.0, 1014.0)},
        "note": "short SL ancorado; exit no anchor 1011.01 (~ -1R).",
    },
    # K5 — sids em direções opostas na mesma vela -> conflito, 0 trades.
    "K5": {
        "n": 6, "base": 1000.0,
        "sids": {
            "A3": {"signal_idx": 1, "direction": DIRECTION_LONG,
                   "zone_low": 990.0, "zone_high": 1010.0, "setup_id": "kaK5L"},
            "A5": {"signal_idx": 1, "direction": DIRECTION_SHORT,
                   "zone_low": 990.0, "zone_high": 1010.0, "setup_id": "kaK5S"},
        },
        "ohlcv": {},
        "note": "direcoes conflitantes -> 0 trades, setup_conflict_dirs=1 na vela 1.",
    },
    # K6 — 2 sids CONFIRMED mesma direção -> vence maior prioridade D3.
    "K6": {
        "n": 8, "base": 1000.0,
        "sids": {
            # A3 tem prioridade D3 mais alta que A6 (índice menor no registry).
            "A3": {"signal_idx": 1, "direction": DIRECTION_LONG,
                   "zone_low": 990.0, "zone_high": 1010.0, "setup_id": "kaK6a3"},
            "A6": {"signal_idx": 1, "direction": DIRECTION_LONG,
                   "zone_low": 985.0, "zone_high": 1010.0, "setup_id": "kaK6a6"},
        },
        # entrada via A3 (vencedor). anchor A3 = 989.01 ; alvo = 1021.98 -> vela 4.
        "ohlcv": {3: (1005.0, 1006.0, 1004.0, 1005.0),
                  4: (1022.0, 1023.0, 1021.0, 1022.0),
                  5: (1022.0, 1023.0, 1021.0, 1022.0),
                  6: (1022.0, 1023.0, 1021.0, 1022.0),
                  7: (1022.0, 1023.0, 1021.0, 1022.0)},
        "note": "2 sids mesma direcao -> enter_tag do sid de maior prioridade (A3).",
    },
    # K7 — contabilidade de fee (numeros redondos; falha se fee=0).
    "K7": {
        "n": 8, "base": 1000.0,
        "sids": {"A3": {"signal_idx": 1, "direction": DIRECTION_LONG,
                        "zone_low": 900.0, "zone_high": 1010.0, "setup_id": "kaK7"}},
        # entrada = open[2] = 1000 ; anchor = 900*0.999 = 899.1 ; R = 100.9 ;
        # alvo = 1000 + 2*100.9 = 1201.8. 1o open >= alvo: vela 4 (=1210, redondo).
        "ohlcv": {3: (1005.0, 1006.0, 1004.0, 1005.0),
                  4: (1210.0, 1211.0, 1209.0, 1210.0),
                  5: (1210.0, 1211.0, 1209.0, 1210.0),
                  6: (1210.0, 1211.0, 1209.0, 1210.0),
                  7: (1210.0, 1211.0, 1209.0, 1210.0)},
        "note": "fee: profit_abs = 100*[(1210/1000)*(1-fee) - (1+fee)]; fee=0 mudaria.",
    },
    # K8 — anti-armadilha de stoploss: -15% intracandle NAO fecha; saida estrutural.
    "K8": {
        "n": 9, "base": 1000.0,
        "sids": {"A3": {"signal_idx": 1, "direction": DIRECTION_LONG,
                        "zone_low": 500.0, "zone_high": 1010.0, "setup_id": "kaK8",
                        "invalidate_idx": 6}},
        # entrada = open[2] = 1000. anchor = 500*0.999 = 499.5 (~ -50%): longe do dip.
        # vela 4: queda adversa de -15% intracandle (low=850). Com config -0.99 e
        # anchor em 499.5, NAO fecha. vela 6: setup INVALIDATED -> custom_exit
        # (smc_structural_invalidation) no open[6].
        "ohlcv": {3: (1000.0, 1001.0, 999.0, 1000.0),
                  4: (1000.0, 1001.0, 850.0, 900.0),   # -15% intracandle
                  5: (900.0, 901.0, 899.0, 900.0),
                  6: (900.0, 901.0, 899.0, 900.0),     # open[6] = preco de saida
                  7: (900.0, 901.0, 899.0, 900.0),
                  8: (900.0, 901.0, 899.0, 900.0)},
        "note": "-15% dip nao fecha (config -0.99); saida estrutural no open[6]=900.",
    },
}


# ------------------------------------------------------------------
# Builders
# ------------------------------------------------------------------

def build_ohlcv(name: str) -> pd.DataFrame:
    """OHLCV 15m sintético determinístico do cenário `name`.

    Velas "planas" no `base` (high=base+1, low=base-1), com overrides explícitos
    de `ohlcv[idx] = (open, high, low, close)`. `date` é tz-aware UTC (o backtest
    do Freqtrade opera em UTC).
    """
    sc = SCENARIOS[name]
    n, base = sc["n"], sc["base"]
    dates = pd.date_range(START, periods=n, freq="15min", tz="UTC")
    o = np.full(n, base, dtype="float64")
    h = o + 1.0
    low = o - 1.0
    c = o.copy()
    v = np.full(n, 100.0, dtype="float64")
    df = pd.DataFrame({"date": dates, "open": o, "high": h, "low": low,
                       "close": c, "volume": v})
    for idx, (oo, hh, ll, cc) in sc.get("ohlcv", {}).items():
        df.loc[idx, ["open", "high", "low", "close"]] = [oo, hh, ll, cc]
    return df


def _string_col(value, n: int) -> pd.array:
    """Coluna StringDtype de `n` linhas — espelha o dtype REAL da engine.

    A engine emite `setup_id/signature/state/direction/invalidation_reason` como
    pandas StringDtype (`pd.array(..., dtype='string')`, `setup_state.py:1977-1983`),
    cujo sentinela de ausência é `pd.NA` — NÃO `None`/object. Os fixtures antigos
    injetavam essas colunas como object/`None`, obtendo paridade de VALOR sem
    paridade de DTYPE: o crash do P3 (`boolean value of NA is ambiguous`) só surge
    com `pd.NA`, então os testes nunca o pegavam (§1 do briefing 10.7). Este helper
    fecha o gap. `value` escalar é broadcast; lista é usada verbatim.
    """
    values = value if isinstance(value, list) else [value] * n
    return pd.array(values, dtype="string")


def build_setup_columns(name: str, dataframe: pd.DataFrame) -> pd.DataFrame:
    """Injeta as 7 `SETUP_OUTPUT_COLUMNS` sufixadas (`{col}__{sid}`) dos 9 sids.

    Para cada sid: colunas de identidade/zona (`setup_id`, `setup_signature`,
    `setup_zone_low`, `setup_zone_high`) constantes em TODAS as velas (para que a
    leitura causal dos callbacks sempre encontre a linha), e `setup_state`
    variável: `CONFIRMED` só na vela de sinal (dispara a entrada), `INVALIDATED`
    a partir de `invalidate_idx` (se houver), `PENDING_CONFIRMATION` nas demais.
    Sids sem evento ficam inteiramente inativos (estado/valores nulos) — mas
    presentes, satisfazendo `require_candidate_columns`.

    DTYPE (Wave 10.7): as colunas de string (`id/signature/state/direction/
    invalidation_reason`) são injetadas como pandas StringDtype (sentinela
    `pd.NA`) via `_string_col`, espelhando a saída real de
    `compute_setup_state_multi`; as zonas são float64 (sentinela `NaN`). Assim o
    harness exercita o MESMO material de dtype que a produção alimenta a
    `populate_entry_trend`.
    """
    sc = SCENARIOS[name]
    n = len(dataframe)
    df = dataframe.copy()

    # Default: todos os sids inativos (colunas presentes, valores nulos) — string
    # cols como StringDtype/`pd.NA`, zonas como float64/`NaN` (paridade de dtype).
    for sid in ALL_SIDS:
        df[f"setup_id__{sid}"] = _string_col(None, n)
        df[f"setup_signature__{sid}"] = _string_col(None, n)
        df[f"setup_state__{sid}"] = _string_col(None, n)
        df[f"setup_direction__{sid}"] = _string_col(None, n)
        df[f"setup_zone_low__{sid}"] = np.nan
        df[f"setup_zone_high__{sid}"] = np.nan
        df[f"setup_invalidation_reason__{sid}"] = _string_col(None, n)

    for sid, ev in sc["sids"].items():
        sig_idx = ev["signal_idx"]
        inval_idx = ev.get("invalidate_idx")
        state = [STATE_PENDING] * n
        state[sig_idx] = STATE_CONFIRMED
        if inval_idx is not None:
            for i in range(inval_idx, n):
                state[i] = STATE_INVALIDATED
        df[f"setup_id__{sid}"] = _string_col(ev["setup_id"], n)
        df[f"setup_signature__{sid}"] = _string_col(sid, n)
        df[f"setup_state__{sid}"] = _string_col(state, n)
        df[f"setup_direction__{sid}"] = _string_col(ev["direction"], n)
        df[f"setup_zone_low__{sid}"] = ev["zone_low"]
        df[f"setup_zone_high__{sid}"] = ev["zone_high"]
    return df


# ------------------------------------------------------------------
# Derivação à mão das expectativas (mesma aritmética do comentário do módulo)
# ------------------------------------------------------------------

def sl_anchor(direction: str, zone_low: float, zone_high: float,
              buffer: float = BUFFER) -> float:
    """Preço da âncora do SL (idêntico a `SMCStrategy._compute_sl_anchor`)."""
    if direction == DIRECTION_SHORT:
        return zone_high * (1.0 + buffer)
    return zone_low * (1.0 - buffer)


def rr_target_price(direction: str, entry: float, anchor: float,
                    rr: float = RR) -> float:
    """Preço-alvo por R:R (idêntico a `SMCStrategy._rr_target_reached`)."""
    risk = abs(entry - anchor)
    if direction == DIRECTION_SHORT:
        return entry - rr * risk
    return entry + rr * risk


def profit_abs(direction: str, entry: float, exit_: float,
               stake: float = STAKE, fee: float = FEE) -> float:
    """P&L absoluto à mão (leverage 1, contractSize 1) — ver docstring do módulo."""
    if direction == DIRECTION_SHORT:
        return stake * ((1.0 - fee) - (exit_ / entry) * (1.0 + fee))
    return stake * ((exit_ / entry) * (1.0 - fee) - (1.0 + fee))
