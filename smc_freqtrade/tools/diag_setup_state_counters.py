"""Contadores estruturais da FSM de setup, por assinatura × modo (Bloco 1).

OBJETIVO
    Consolidar o instrumental de medição da Fase A Parte 2 num script
    reutilizável: rodar `compute_setup_state` por assinatura (solo) e nas
    composições (slot único e `compute_setup_state_multi`), imprimindo
    contadores **estruturais** — setups, CONFIRMED, idade mediana,
    escaped com vida <= 1 candle, distância de armação (med/p90),
    armações além de `prox`, distribuição de razões e o bloco multi vs
    solo (starvation G9). Serve de leitura informativa dos 4 mecanismos
    do Bloco 1 (G1/G2/G3/G5) — os gates duros são os testes T1–T8 — e,
    do Bloco 2 / Onda 1, do gate de displacement (§2.6-i): totais de
    `disp_bull/bear`, taxa choch∧disp/choch por lado e CONFIRMED por
    assinatura com o gate off vs confirm (gates duros: T-D1–T-D5).
    Do Bloco 2 / Onda 2 (§2.7), leitura do ciclo de vida v2 do OTE:
    persistência por lado legacy vs v2 e zonas v2 criadas + razões de
    kill (golden 1h), e A10 solo em 4 configurações
    (legacy | v2 | v2+eq | v2+eq+conf) sobre a base Bloco-1-ON +
    `displacement_gate='confirm'` (gates duros: T-O1–T-O7).

FONTE DE DADOS
    Uma de duas entradas:
    - `--golden-dir DIR`: os 3 CSVs golden (`btc_usdt_swap_{tf}_window.csv`,
      tf ∈ {4h, 1h, 15m}); o pipeline da Fase A é replicado (analyze ×3 +
      `sessions.tag_sessions` no 15m + `tools.mtf_align.align_informative`).
    - `--parquet PATH`: DataFrame 15m já mergeado (ex.: os
      `user_data/diag_df*.parquet` de 2 anos da VM).

LIMITAÇÕES CONHECIDAS
    - Distância de armação na convenção do gate G1 (normalizada pela
      borda da zona): long `(low - zhigh)/zhigh`, short `(zlow - high)/zlow`.
    - Idade do setup = candles entre a armação e o último candle emitido
      (setup de 1 emissão → idade 0; arm→die no candle seguinte → 1).
    - O bloco multi vs solo roda o conjunto completo de assinaturas
      selecionadas; com `compute_setup_state_multi`, multi == solo por
      construção (G9) — a coluna existe para evidenciar o contraste com
      o slot único legado.

NÃO FAZER
    - Não computar P&L / expectancy / win rate (disciplina da Fase A;
      o harness de P&L segue não-validado).
    - Não usar como gate de CI — os gates são os testes T1–T8.

USO
    python -m tools.diag_setup_state_counters --golden-dir tests/golden/data \
        --prox 0.02 --trigger choch --anchor frozen_band --a9 sweep_band \
        --displacement confirm --ote v2 --ote-eq --ote-conf
"""
from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

from smc_engine import analyze, compute_setup_state, SetupConfig
from smc_engine.fib_ote import project_ote_zones_v2
from smc_engine.fvg import COL_FVG_BEARISH_CREATED, COL_FVG_BULLISH_CREATED
from smc_engine.sessions import SESSION_COLUMNS, tag_sessions
from smc_engine.setup_state import (
    _VALID_SIGNATURE_IDS,
    STATE_CONFIRMED,
    _a7_chain_ffill,
    _displacement_flags,
    compute_setup_state_multi,
)
from tools.mtf_align import align_informative

REPORT_PROX_DEFAULT = 0.02   # limiar de *report* (arm>prox) quando o gate G1 está off


def _load_ohlcv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df['date'] = pd.to_datetime(df['timestamp_utc'], utc=True)
    return df[['date', 'open', 'high', 'low', 'close', 'volume']]


def build_merged_from_golden(golden_dir: Path) -> pd.DataFrame:
    """Pipeline da Fase A: analyze ×3 + tag_sessions(15m) + merges 1h/4h."""
    r4 = analyze(_load_ohlcv(golden_dir / 'btc_usdt_swap_4h_window.csv'))
    r1 = analyze(_load_ohlcv(golden_dir / 'btc_usdt_swap_1h_window.csv'))
    r15 = analyze(_load_ohlcv(golden_dir / 'btc_usdt_swap_15m_window.csv'))
    base15 = tag_sessions(r15.df)
    merged = align_informative(base15, r1.df, '15m', '1h', suffix='1h')
    merged = align_informative(merged, r4.df, '15m', '4h', suffix='4h')
    return merged


def _in_kz_any(merged: pd.DataFrame) -> np.ndarray:
    """OR booleano das 3 colunas de killzone Silver Bullet (base, sem sufixo)."""
    n = len(merged)
    out = np.zeros(n, dtype='bool')
    for col in SESSION_COLUMNS:
        if col in merged.columns:
            out = out | merged[col].fillna(False).to_numpy(dtype='bool')
    return out


def _chain_ids(merged: pd.DataFrame, in_kz: np.ndarray, side: str,
               recency: int, window: int) -> np.ndarray:
    """Ids por candle da cadeia A7 (Bloco 2 / Onda 3a) — reuso de
    `_a7_chain_ffill` sobre o merged (MSS-d = ChoCH cru ∧ displacement)."""
    n = len(merged)
    o = merged['open'].to_numpy(dtype='float64')
    h = merged['high'].to_numpy(dtype='float64')
    low = merged['low'].to_numpy(dtype='float64')
    c = merged['close'].to_numpy(dtype='float64')
    disp_bull, disp_bear = _displacement_flags(o, h, low, c, 10, 0.36)
    if side == 'bull':
        choch = merged['choch_internal_bullish'].fillna(False).to_numpy(dtype='bool')
        mss = choch & disp_bull
        sweep = (merged['sweep_bullish_wick'].fillna(False)
                 | merged['sweep_bullish_retest'].fillna(False)).to_numpy(dtype='bool')
        fvg = merged[COL_FVG_BULLISH_CREATED].fillna(False).to_numpy(dtype='bool')
    else:
        choch = merged['choch_internal_bearish'].fillna(False).to_numpy(dtype='bool')
        mss = choch & disp_bear
        sweep = (merged['sweep_bearish_wick'].fillna(False)
                 | merged['sweep_bearish_retest'].fillna(False)).to_numpy(dtype='bool')
        fvg = merged[COL_FVG_BEARISH_CREATED].fillna(False).to_numpy(dtype='bool')
    _, _, zid = _a7_chain_ffill(mss, sweep, fvg, in_kz, h, low, c, side,
                                window, recency)
    return zid


def _chain_births_kills(zid: np.ndarray) -> tuple[int, int, int]:
    """(nascimentos, mortes por close-through, substituições) a partir do id."""
    births = kills_close = replaces = 0
    prev = np.nan
    for v in zid:
        if not np.isnan(v):
            if np.isnan(prev):
                births += 1
            elif v != prev:
                births += 1
                replaces += 1
        elif not np.isnan(prev):
            kills_close += 1
        prev = v
    return births, kills_close, replaces


def _per_setup_frame(res: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por setup: direção, zona congelada, idade, razão final."""
    active = res.dropna(subset=['setup_id'])
    if active.empty:
        return pd.DataFrame(columns=[
            'direction', 'zone_low', 'zone_high', 'arm_low', 'arm_high',
            'age', 'reason', 'confirmed',
        ])
    g = active.groupby('setup_id', sort=False)
    first = g.head(1)
    rows = pd.DataFrame({
        'direction': first['setup_direction'].to_numpy(),
        'zone_low': first['setup_zone_low'].to_numpy(),
        'zone_high': first['setup_zone_high'].to_numpy(),
        'arm_low': first['low'].to_numpy(),
        'arm_high': first['high'].to_numpy(),
        'age': (g.size() - 1).to_numpy(),
        'reason': g['setup_invalidation_reason'].last().to_numpy(),
        'confirmed': (g['setup_state'].last() == STATE_CONFIRMED).to_numpy(),
    }, index=first['setup_id'].to_numpy())
    return rows


def _arming_distance(per_setup: pd.DataFrame) -> np.ndarray:
    """Distância de armação na convenção do gate G1 (borda da zona)."""
    is_long = (per_setup['direction'] == 'long').to_numpy()
    d_long = per_setup['arm_low'].to_numpy() / per_setup['zone_high'].to_numpy() - 1.0
    d_short = 1.0 - per_setup['arm_high'].to_numpy() / per_setup['zone_low'].to_numpy()
    return np.where(is_long, d_long, d_short)


def report_signature(res: pd.DataFrame, label: str, prox_report: float) -> None:
    ps = _per_setup_frame(res)
    n = len(ps)
    n_conf = int(ps['confirmed'].sum())
    print(f'--- {label} ---')
    if n == 0:
        print('  setups=0')
        return
    dist = _arming_distance(ps)
    esc = ps[ps['reason'] == 'escaped']
    esc_le1 = int((esc['age'] <= 1).sum())
    n_beyond = int((dist > prox_report).sum())
    print(f'  setups={n}  CONFIRMED={n_conf}  '
          f'idade_mediana={float(ps["age"].median()):.1f}')
    print(f'  escaped={len(esc)}  esc<=1={esc_le1} '
          f'({esc_le1 / len(esc) * 100:.0f}% dos escaped)' if len(esc)
          else '  escaped=0')
    print(f'  dist_armacao med={float(np.median(dist)) * 100:.2f}%  '
          f'p90={float(np.percentile(dist, 90)) * 100:.2f}%  '
          f'arm>{prox_report:.0%}: {n_beyond} ({n_beyond / n * 100:.0f}%)')
    reasons = ps['reason'].dropna().value_counts()
    txt = ', '.join(f'{k}={v}' for k, v in reasons.items()) or '—'
    print(f'  razoes: {txt}')


def main() -> None:
    ap = argparse.ArgumentParser(
        description='Contadores estruturais da FSM (sem P&L).')
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument('--golden-dir', type=Path,
                     help='diretório dos 3 CSVs golden (4h/1h/15m)')
    src.add_argument('--parquet', type=Path,
                     help='parquet 15m já mergeado (ex.: diag_df.parquet)')
    ap.add_argument('--signatures', default=','.join(_VALID_SIGNATURE_IDS),
                    help='lista separada por vírgula (default: as 9)')
    ap.add_argument('--modes', default='confirmation',
                    help='confirmation,risk (default: confirmation)')
    # Os 4 mecanismos do Bloco 1 (defaults = legado, desligados):
    ap.add_argument('--prox', type=float, default=None,
                    help='G1 arming_proximity_pct (default: off)')
    ap.add_argument('--trigger', default='legacy',
                    help='G2 confirmation_trigger (legacy|choch|choch_or_rej)')
    ap.add_argument('--anchor', default='promoted_id',
                    help='G3 anchor_invalidation (promoted_id|frozen_band)')
    ap.add_argument('--a9', default='legacy_ob',
                    help='G5 a9_variant (legacy_ob|sweep_band)')
    # Bloco 2 / Onda 1 (default = legado, desligado):
    ap.add_argument('--displacement', default='off',
                    choices=('off', 'confirm'),
                    help='Bloco 2 displacement_gate (off|confirm)')
    # Bloco 2 / Onda 2 (default = legado, desligado):
    ap.add_argument('--ote', default='legacy',
                    choices=('legacy', 'v2'),
                    help='Bloco 2 / Onda 2 ote_lifecycle (legacy|v2)')
    ap.add_argument('--ote-eq', action='store_true',
                    help='ote_require_eq_cross (exige --ote v2)')
    ap.add_argument('--ote-conf', action='store_true',
                    help='ote_require_confluence (exige --ote v2)')
    # Bloco 2 / Onda 3a (default = legado, desligado):
    ap.add_argument('--a7', default='legacy',
                    choices=('legacy', 'chain_v2'),
                    help='Bloco 2 / Onda 3a a7_variant (legacy|chain_v2)')
    ap.add_argument('--kzq', default='',
                    help='killzone_qualifier: ids separados por vírgula '
                         '(default: vazio)')
    ap.add_argument('--no-multi', action='store_true',
                    help='pular o bloco multi vs solo')
    args = ap.parse_args()

    sids = tuple(s.strip() for s in args.signatures.split(',') if s.strip())
    modes = tuple(m.strip() for m in args.modes.split(',') if m.strip())
    kzq = tuple(s.strip() for s in args.kzq.split(',') if s.strip())
    prox_report = args.prox if args.prox is not None else REPORT_PROX_DEFAULT

    if args.parquet:
        merged = pd.read_parquet(args.parquet)
        print(f'input: {args.parquet} ({len(merged)} candles)')
    else:
        merged = build_merged_from_golden(args.golden_dir)
        print(f'input: golden {args.golden_dir} ({len(merged)} candles)')
    print(f'mecanismos: prox={args.prox}  trigger={args.trigger}  '
          f'anchor={args.anchor}  a9={args.a9}  '
          f'displacement={args.displacement}  ote={args.ote}  '
          f'ote_eq={args.ote_eq}  ote_conf={args.ote_conf}  '
          f'a7={args.a7}  kzq={",".join(kzq) or "-"}')
    print(f'assinaturas={",".join(sids)}  modos={",".join(modes)}\n')

    def cfg(signature, mode, displacement=None):
        return SetupConfig(
            signature=signature, entry_mode=mode,
            arming_proximity_pct=args.prox,
            confirmation_trigger=args.trigger,
            anchor_invalidation=args.anchor,
            a9_variant=args.a9,
            displacement_gate=(
                args.displacement if displacement is None else displacement
            ),
            ote_lifecycle=args.ote,
            ote_require_eq_cross=args.ote_eq,
            ote_require_confluence=args.ote_conf,
            a7_variant=args.a7,
            killzone_qualifier=kzq,
        )

    solo_counts: dict[tuple[str, str], int] = {}
    for mode in modes:
        for sid in sids:
            res = compute_setup_state(merged, cfg(sid, mode))
            solo_counts[(sid, mode)] = int(res['setup_id'].dropna().nunique())
            report_signature(res, f'{sid} / {mode} (solo)', prox_report)
        print()

    # Bloco 2 / Onda 1: contadores de displacement (§2.6-i) — totais das
    # flags, taxa choch∧disp/choch por lado e CONFIRMED solo por
    # assinatura com o gate off vs confirm (demais mecanismos = args).
    print('=== displacement (Bloco 2 / Onda 1) ===')
    dcfg = cfg(sids[0], modes[0])
    disp_bull, disp_bear = _displacement_flags(
        merged['open'].to_numpy(dtype='float64'),
        merged['high'].to_numpy(dtype='float64'),
        merged['low'].to_numpy(dtype='float64'),
        merged['close'].to_numpy(dtype='float64'),
        dcfg.displacement_body_len, dcfg.displacement_wick_frac,
    )
    ch_bull = merged['choch_internal_bullish'] \
        .fillna(False).to_numpy(dtype='bool')
    ch_bear = merged['choch_internal_bearish'] \
        .fillna(False).to_numpy(dtype='bool')
    n_cand = len(merged)
    nb, ns = int(disp_bull.sum()), int(disp_bear.sum())
    print(f'  disp_bull={nb} ({nb / n_cand * 100:.1f}%)  '
          f'disp_bear={ns} ({ns / n_cand * 100:.1f}%)  '
          f'de {n_cand} candles')
    for lado, ch, disp in (('bull', ch_bull, disp_bull),
                           ('bear', ch_bear, disp_bear)):
        n_ch = int(ch.sum())
        n_both = int((ch & disp).sum())
        rate = n_both / n_ch * 100 if n_ch else 0.0
        print(f'  choch∧disp/choch [{lado}]: {n_both}/{n_ch} ({rate:.0f}%)')
    for mode in modes:
        print(f'  [{mode}] CONFIRMED por assinatura (gate off | confirm):')
        for sid in sids:
            n_off = int((
                compute_setup_state(merged, cfg(sid, mode, 'off'))
                ['setup_state'] == STATE_CONFIRMED
            ).sum())
            n_on = int((
                compute_setup_state(merged, cfg(sid, mode, 'confirm'))
                ['setup_state'] == STATE_CONFIRMED
            ).sum())
            print(f'    {sid:>4}: {n_off:>5} | {n_on:>5}')
    print()

    # Bloco 2 / Onda 2: leitura do ciclo de vida v2 do OTE (§2.7) —
    # persistência por lado legacy vs v2 + zonas criadas e razões de
    # kill (recomputados no golden 1h; indisponível em --parquet) e A10
    # solo nas 4 configurações sobre a base Bloco-1-ON fixa do briefing
    # + displacement_gate='confirm' (independente dos args).
    print('=== OTE v2 (Bloco 2 / Onda 2) ===')
    if args.golden_dir:
        r1 = analyze(_load_ohlcv(args.golden_dir / 'btc_usdt_swap_1h_window.csv'))
        _, ote_stats = project_ote_zones_v2(r1.df, with_stats=True)
        for pre in ('bull', 'bear'):
            legacy_p = float(r1.df[f'active_{pre}_ote_id'].notna().mean())
            v2_p = float(r1.df[f'{pre}_ote_v2_id'].notna().mean())
            st = ote_stats[pre]
            kills = ', '.join(f'{k}={v}' for k, v in st['kills'].items())
            print(f'  [{pre}] persistencia (1h): legacy={legacy_p:.1%}  '
                  f'v2={v2_p:.1%}')
            print(f'  [{pre}] zonas_v2_criadas={st["created"]}  '
                  f'kills: {kills}')
    else:
        print('  persistencia/kills por lado: só em --golden-dir '
              '(parquet não recomputa o 1h) — bloco pulado')
    if 'bull_ote_v2_id_1h' in merged.columns:
        print("  A10 solo (Bloco-1-ON + displacement='confirm'):")
        ote_variants = (
            ('legacy', {}),
            ('v2', dict(ote_lifecycle='v2')),
            ('v2+eq', dict(ote_lifecycle='v2', ote_require_eq_cross=True)),
            ('v2+eq+conf', dict(ote_lifecycle='v2', ote_require_eq_cross=True,
                                ote_require_confluence=True)),
        )
        for label, kw in ote_variants:
            res = compute_setup_state(merged, SetupConfig(
                signature='A10', entry_mode='confirmation',
                arming_proximity_pct=0.02,
                confirmation_trigger='choch',
                anchor_invalidation='frozen_band',
                a9_variant='sweep_band',
                displacement_gate='confirm',
                **kw,
            ))
            report_signature(res, f'A10 / {label}', prox_report)
    else:
        print('  A10 solo 4-config: colunas *_ote_v2_*_1h ausentes no '
              'input — bloco pulado')
    print()

    # Bloco 2 / Onda 3a (§0/§4): cadeia da A7 + tempo transversal.
    # Matriz da §0 (cadeias por L∈{4,8,16} × kz, F=2), zonas criadas/kills
    # por lado (L=16), A7 solo legacy vs chain_v2 sobre Bloco-1-ON +
    # displacement='confirm', e efeito do qualifier por assinatura listada.
    print('=== A7 chain_v2 + tempo transversal (Bloco 2 / Onda 3a) ===')
    in_kz = _in_kz_any(merged)
    all_true = np.ones(len(merged), dtype='bool')
    print('  matriz §0 (F=2) — cadeias bull/bear por L × kz:')
    for L in (4, 8, 16):
        for use_kz, tag in ((all_true, 'sem kz'), (in_kz, 'com kz')):
            bull = _chain_ids(merged, use_kz, 'bull', L, 2)
            bear = _chain_ids(merged, use_kz, 'bear', L, 2)
            nb = int(pd.Series(bull).dropna().nunique())
            ns = int(pd.Series(bear).dropna().nunique())
            print(f'    L={L:>2}  {tag}: bull={nb:>3}  bear={ns:>3}')
    print('  (variante estrita cadeia-inteira-na-janela: calibração, §8 — '
          'fora deste bloco)')
    print('  zonas criadas / kills por lado (L=16, F=2, com kz):')
    for side in ('bull', 'bear'):
        zid = _chain_ids(merged, in_kz, side, 16, 2)
        births, kills_close, replaces = _chain_births_kills(zid)
        print(f'    [{side}] criadas={births}  '
              f'kills(close-through)={kills_close}  substituicoes={replaces}')
    print("  A7 solo (Bloco-1-ON + displacement='confirm'): legacy | chain_v2")
    for a7v in ('legacy', 'chain_v2'):
        res = compute_setup_state(merged, SetupConfig(
            signature='A7', entry_mode='confirmation',
            arming_proximity_pct=0.02, confirmation_trigger='choch',
            anchor_invalidation='frozen_band', a9_variant='sweep_band',
            displacement_gate='confirm', a7_variant=a7v,
        ))
        report_signature(res, f'A7 / {a7v}', prox_report)
    if kzq:
        print(f'  efeito do qualifier (kzq={",".join(kzq)}) — armações '
              f'dentro/fora de kz:')
        for sid in kzq:
            base = compute_setup_state(
                merged, replace(cfg(sid, modes[0]), killzone_qualifier=()))
            qual = compute_setup_state(
                merged, replace(cfg(sid, modes[0]), killzone_qualifier=(sid,)))
            for label, res in (('sem qual', base), ('com qual', qual)):
                act = res.dropna(subset=['setup_id'])
                idx = act.groupby('setup_id', sort=False).head(1).index.to_numpy()
                inside = int(in_kz[idx].sum()) if len(idx) else 0
                outside = int((~in_kz[idx]).sum()) if len(idx) else 0
                print(f'    {sid:>4} {label}: dentro={inside:>5}  '
                      f'fora={outside:>5}')
    else:
        print('  qualifier: use --kzq <ids> para o efeito por assinatura')
    print()

    if args.no_multi or len(sids) < 2:
        return

    print('=== multi vs solo (G9) ===')
    for mode in modes:
        legacy = compute_setup_state(merged, cfg(sids, mode))
        slot = legacy.dropna(subset=['setup_id']) \
            .groupby('setup_signature')['setup_id'].nunique()
        multi = compute_setup_state_multi(merged, cfg(sids, mode))
        print(f'[{mode}]  assinatura: solo | slot_unico | multi_fsm')
        for sid in sids:
            n_multi = int(multi[f'setup_id__{sid}'].dropna().nunique())
            print(f'  {sid:>4}: {solo_counts[(sid, mode)]:>6} | '
                  f'{int(slot.get(sid, 0)):>6} | {n_multi:>6}')


if __name__ == '__main__':
    main()
