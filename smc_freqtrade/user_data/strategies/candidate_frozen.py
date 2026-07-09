"""candidate_frozen — configs congeladas (v2) + arbitragem D3 pura (Wave 10.1).

OBJETIVO
    Materializar, em código puro (SEM import de freqtrade), a
    configuração-candidata congelada em
    `docs/CONGELAMENTO_CANDIDATA_V2_E_GATES_EDGE.md` (a **fonte única** dos
    valores) e a arbitragem D3 do consumidor (§1.3 do doc). São duas
    instâncias de `SetupConfig` — Grupo C (habitat confirmation, 7
    assinaturas) e Grupo R (habitat risk/tap, 2 assinaturas) — mais a função
    pura `arbitrate_d3`, que decide o vencedor por vela a partir dos sids
    CONFIRMED. Consumido por `SMCStrategyCandidate` e pinado campo-a-campo
    pelo teste `tests/test_smoke_wave10_1.py` (o teste É o pin do
    congelamento).

FONTE DE DADOS
    - Valores dos campos: `docs/CONGELAMENTO_CANDIDATA_V2_E_GATES_EDGE.md`
      §1.1 (Grupo C) e §1.2 (Grupo R), verbatim. Nenhum valor é derivado ou
      "esperto" aqui — cada campo é explícito.
    - `SetupConfig` e o registry `SIGNATURES` vêm de `smc_engine.setup_state`
      (a engine vive na raiz do subprojeto, fora de `user_data/`).
    - Ordem de prioridade D3 (`D3_PRIORITY`): derivada por enumeração da
      ordem do registry `SIGNATURES` (NÃO hardcodada) — §1.3 do doc.

LIMITAÇÕES CONHECIDAS
    - Módulo puro: não roda a FSM nem toca pandas/freqtrade. A execução das
      configs é da camada IStrategy (`SMCStrategyCandidate`); a arbitragem
      D3 vetorizada/por-vela também.
    - `arbitrate_d3` recebe apenas os CONFIRMED da vela (o filtro de estado é
      do consumidor) e devolve o vencedor + motivo; não conhece preço, zona
      nem P&L.

NÃO FAZER
    - Não importar freqtrade (o módulo deve coletar no sandbox sem exchange).
    - Não editar valores de parâmetro sem novo ciclo de pré-registro (§4-P5
      do doc); ajustes de exequibilidade (§1.4) não mudam nenhum número.
    - Não hardcodar as prioridades D3 (derivar do registry).
"""
from __future__ import annotations

import sys
from pathlib import Path

# A engine SMC vive na raiz do subprojeto (`smc_freqtrade/smc_engine`), fora
# de `user_data/`. Espelha o mecanismo `_SUBPROJECT_ROOT` da SMCStrategy para
# permitir importar `smc_engine` mesmo quando o módulo é carregado só pelo
# resolver de estratégias (que adiciona apenas o diretório da estratégia).
_SUBPROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_SUBPROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_SUBPROJECT_ROOT))

from smc_engine.setup_state import SetupConfig, SIGNATURES  # noqa: E402

# === Assinaturas por grupo (doc §1.1 / §1.2) ===
# Grupo C — habitat confirmation (7 assinaturas).
SIDS_GRUPO_C: tuple = ('A3', 'A2', 'A4a', 'A1', 'A9', 'A6', 'A10')
# Grupo R — habitat risk/tap (2 assinaturas).
SIDS_GRUPO_R: tuple = ('A5', 'A7')

# === Prioridade D3 (doc §1.3) ===
# Ordem do registry `SIGNATURES` (insertion order == prioridade): menor valor
# = maior prioridade. Derivada por enumeração — NÃO hardcodar os números.
# Resulta em: A3=0 > A2=1 > A4a=2 > A5=3 > A1=4 > A9=5 > A6=6 > A7=7 > A10=8.
D3_PRIORITY: dict[str, int] = {sid: i for i, sid in enumerate(SIGNATURES)}


def build_cfg_c() -> SetupConfig:
    """Grupo C — habitat confirmation congelado (doc §1.1).

    Todos os campos explícitos (sem dependência de default). Guarda da
    combinação impossível (`__post_init__`) passa porque
    `confirmation_trigger='choch'` (não 'legacy'); a guarda dos gates OTE
    passa porque `ote_lifecycle='v2'` acompanha `ote_require_*=True`.
    """
    return SetupConfig(
        signature=SIDS_GRUPO_C,
        entry_mode='confirmation',
        armed_escape_pct=0.02,
        armed_timeout_candles=24,
        pending_timeout_candles=16,
        sweep_recency_candles=16,
        fvg_ob_adjacency_pct=0.003,
        rejection_wick_frac=0.5,
        rejection_close_frac=0.667,
        volume_pct_min=0.2,
        trend_suffix='4h',
        zone_suffix='1h',
        arming_proximity_pct=0.02,
        confirmation_trigger='choch',
        anchor_invalidation='frozen_band',
        a9_variant='sweep_band',
        displacement_gate='confirm',
        displacement_body_len=10,
        displacement_wick_frac=0.36,
        ote_lifecycle='v2',
        ote_require_eq_cross=True,
        ote_require_confluence=True,
        a7_variant='legacy',
        a7_fvg_window=2,
        killzone_qualifier=(),
        ob_semantics='strategic',
    )


def build_cfg_r() -> SetupConfig:
    """Grupo R — habitat risk/tap congelado (doc §1.2).

    Todos os campos explícitos. `displacement_gate='off'` desativa a guarda da
    combinação impossível; `ote_lifecycle='legacy'` com `ote_require_*=False`
    satisfaz a guarda dos gates OTE. "Demais campos idênticos ao Grupo C"
    (doc §1.2, última linha) — reproduzidos aqui explicitamente.
    """
    return SetupConfig(
        signature=SIDS_GRUPO_R,
        entry_mode='risk',
        armed_escape_pct=0.02,
        armed_timeout_candles=24,
        pending_timeout_candles=16,
        sweep_recency_candles=16,
        fvg_ob_adjacency_pct=0.003,
        rejection_wick_frac=0.5,
        rejection_close_frac=0.667,
        volume_pct_min=0.2,
        trend_suffix='4h',
        zone_suffix='1h',
        arming_proximity_pct=0.02,
        confirmation_trigger='legacy',
        anchor_invalidation='frozen_band',
        a9_variant='legacy_ob',
        displacement_gate='off',
        displacement_body_len=10,
        displacement_wick_frac=0.36,
        ote_lifecycle='legacy',
        ote_require_eq_cross=False,
        ote_require_confluence=False,
        a7_variant='chain_v2',
        a7_fvg_window=2,
        killzone_qualifier=(),
        ob_semantics='primitive',
    )


def arbitrate_d3(
    candidates: list[tuple[str, str]],
) -> tuple[str | None, str | None, str]:
    """Arbitragem D3 do consumidor (doc §1.3), pura — sem pandas.

    OBJETIVO
        Dada a lista de `(sid, direction)` CONFIRMED numa vela, devolver
        `(sid_vencedor, direção, motivo)`:
          - `[]`                       → `(None, None, 'empty')`.
          - 1 candidato               → `(sid, dir, 'single')`.
          - >=2 mesma direção         → vence o de MAIOR prioridade D3 (menor
                                        `D3_PRIORITY`): `(sid, dir,
                                        'priority_tiebreak')` (§1.3-1).
          - direções conflitantes    → `(None, None, 'conflict_dirs')`
                                        (§1.3-2, evidência contraditória).

    Args:
        candidates: lista de `(sid, direction)` CONFIRMED na vela. `sid` deve
            estar em `D3_PRIORITY`; `direction` em {'long','short'}.

    Returns:
        `(sid_vencedor | None, direção | None, motivo)` com
        `motivo ∈ {'single','priority_tiebreak','conflict_dirs','empty'}`.
    """
    if not candidates:
        return (None, None, 'empty')
    directions = {d for _, d in candidates}
    if len(directions) > 1:
        # Direções opostas na mesma vela → evidência contraditória, sem entrada.
        return (None, None, 'conflict_dirs')
    direction = next(iter(directions))
    # Mesma direção: vence a maior prioridade D3 (menor índice no registry).
    winner_sid = min(candidates, key=lambda c: D3_PRIORITY[c[0]])[0]
    reason = 'single' if len(candidates) == 1 else 'priority_tiebreak'
    return (winner_sid, direction, reason)
