"""Sanity no golden (Wave 9.5c §5.4): A1/A9/A6 × modo sem crash.

OBJETIVO
    §5.4: rodar `analyze()` (4h/1h/15m) + merge + `compute_setup_state`
    pelas 3 assinaturas novas × modo no golden real (3 TFs); reportar a
    contagem ARMED/PENDING/CONFIRMED. **Sanity, não PnL** — o veredito é da
    Wave 10 (backtest por assinatura isolada; §6 — não podar por contagem).

    Também valida o invariante aditivo do §5.6: ledgers inalterados
    (OB 15 / FVG 11 / BPR 7) e zona ativa 20 → 26 após o projetor breaker.

FONTE DE DADOS
    Goldens reais em tests/golden/data/btc_usdt_swap_{4h,1h,15m}_window.csv.

NÃO FAZER
    Não comparar contra TradingView (sem ground truth visual).
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pandas as pd

from smc_engine import (
    analyze,
    compute_setup_state,
    ACTIVE_ZONE_COLUMNS,
    SetupConfig,
    SETUP_STATES,
    INVALIDATION_REASONS,
    STATE_ARMED,
    STATE_CONFIRMED,
    STATE_PENDING,
)
from tools.mtf_align import align_informative

GOLDEN_DIR = Path(__file__).resolve().parent / 'golden' / 'data'


def _load_ohlcv(name: str) -> pd.DataFrame:
    df = pd.read_csv(GOLDEN_DIR / name)
    df['date'] = pd.to_datetime(df['timestamp_utc'], utc=True)
    return df[['date', 'open', 'high', 'low', 'close', 'volume']]


@lru_cache(maxsize=1)
def _merged_golden() -> pd.DataFrame:
    """df 15m mergeado com 1h/4h (zona promovida) — base de todas as sigs."""
    r4 = analyze(_load_ohlcv('btc_usdt_swap_4h_window.csv'))
    r1 = analyze(_load_ohlcv('btc_usdt_swap_1h_window.csv'))
    r15 = analyze(_load_ohlcv('btc_usdt_swap_15m_window.csv'))
    merged = align_informative(r15.df, r1.df, '15m', '1h', suffix='1h')
    merged = align_informative(merged, r4.df, '15m', '4h', suffix='4h')
    return merged


# A1/A9/A6 em confirmation; A1 também em risk (verifica D2: sem PENDING).
# Mais a varredura conjunta das 7 assinaturas (um vencedor por candle).
_CASES = [
    ('A1', 'confirmation'),
    ('A9', 'confirmation'),
    ('A6', 'confirmation'),
    ('A1', 'risk'),
    (('A3', 'A2', 'A4a', 'A5', 'A1', 'A9', 'A6'), 'confirmation'),
]


def test_each_signature_mode_runs_without_crash() -> None:
    """Cada caso roda sem crash; estados/razões válidos; contagem
    ARMED/PENDING/CONFIRMED reportada (sanity, não veredito — §6)."""
    merged = _merged_golden()
    report: list[str] = []
    for sig, mode in _CASES:
        res = compute_setup_state(
            merged, SetupConfig(signature=sig, entry_mode=mode),
        )
        state = res['setup_state']
        states = set(state.dropna().unique())
        assert states.issubset(set(SETUP_STATES)), f'{sig}/{mode}: {states}'
        reasons = set(res['setup_invalidation_reason'].dropna().unique())
        assert reasons.issubset(set(INVALIDATION_REASONS))
        n_armed = int((state == STATE_ARMED).sum())
        n_conf = int((state == STATE_CONFIRMED).sum())
        n_pend = int((state == STATE_PENDING).sum())
        # risk nunca emite PENDING (D2)
        if mode == 'risk':
            assert n_pend == 0, f'{sig}/risk emitiu PENDING'
        report.append(f'{str(sig):>40}/{mode:<12} ARMED={n_armed:<4} '
                      f'PENDING={n_pend:<4} CONFIRMED={n_conf}')
    print('\n[§5.4 sanity — contagem por assinatura × modo]')
    print('\n'.join(report))


def test_zone_active_20_to_26_and_ledgers_unchanged() -> None:
    """§5.6: zona ativa 20 → 26 (6 colunas breaker, aditivas ao fim);
    ledgers intactos (OB 15 / FVG 11 / BPR 7)."""
    result = analyze(_load_ohlcv('btc_usdt_swap_4h_window.csv'))
    assert len(ACTIVE_ZONE_COLUMNS) == 26
    n = len(ACTIVE_ZONE_COLUMNS)
    assert list(result.df.columns[-n:]) == list(ACTIVE_ZONE_COLUMNS)
    assert len(result.ledger_ob.columns) == 15
    assert len(result.ledger_fvg.columns) == 11
    assert len(result.ledger_bpr.columns) == 7
