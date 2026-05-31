"""Sanity no golden (Wave 9.5b §6/P7): cada assinatura × modo sem crash.

OBJETIVO
    P7: rodar `analyze()` (4h/1h/15m) + merge + `compute_setup_state` por
    assinatura × modo no golden real (3 TFs); reportar a contagem
    ARMED/CONFIRMED por assinatura e modo. **Sanity, não PnL** — o
    veredito de resultado é da Wave 10 (backtest por assinatura isolada).

    Também valida o invariante aditivo do §7: ledgers inalterados
    (OB 15 / FVG 11 / BPR 7) após a promoção das 8 colunas novas.

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


# (signature, entry_mode) — A5 no seu modo pretendido (risk) e os demais
# em confirmation; A5 também em confirmation para permanecer testável.
_CASES = [
    ('A3', 'confirmation'),
    ('A2', 'confirmation'),
    ('A4a', 'confirmation'),
    ('A5', 'confirmation'),
    ('A5', 'risk'),
    ('A3', 'risk'),
]


def test_each_signature_mode_runs_without_crash() -> None:
    """Cada assinatura × modo roda sem crash; estados/razões válidos;
    contagem ARMED/CONFIRMED reportada (sanity)."""
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
        report.append(f'{sig:>3}/{mode:<12} ARMED={n_armed:<4} '
                      f'PENDING={n_pend:<4} CONFIRMED={n_conf}')
    print('\n[P7 sanity — contagem por assinatura × modo]')
    print('\n'.join(report))


def test_ledgers_unchanged_after_9_5b_promotion() -> None:
    """§7: ledgers intactos (OB 15 / FVG 11 / BPR 7) apesar das 8 colunas
    novas de zona."""
    result = analyze(_load_ohlcv('btc_usdt_swap_4h_window.csv'))
    assert len(result.ledger_ob.columns) == 15
    assert len(result.ledger_fvg.columns) == 11
    assert len(result.ledger_bpr.columns) == 7
