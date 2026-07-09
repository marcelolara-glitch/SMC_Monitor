# CONGELAMENTO — Configuração-candidata v2 + Gates de Edge + Protocolo anti-derivação

> **Status:** ratificado por Marcelo em 2026-07-09 (D-E1–D-E4, conversa de abertura da
> Fase de Edge). Este documento é **imutável** após o merge no repositório: qualquer
> alteração exige novo ciclo de pré-registro (ver §4-P5). Referência de código:
> `main @ 24c659e` (pós-merge do PR #88).
>
> **Regra de precedência:** nenhum número de P&L existia quando este documento foi
> escrito. O harness da Wave 10 atual é **incapaz** de executar esta candidata
> (`SMCStrategy.py:241` hardcoda `SetupConfig()` default) — condição verificada que
> garante o congelamento pré-código-P&L-capaz.

---

## §1. Configuração-candidata congelada

A candidata são **duas** instâncias de `SetupConfig`, executadas em duas chamadas de
`compute_setup_state_multi` (a função aceita um config por chamada e itera
`replace(config, signature=sid)` — `setup_state.py:1987-2040 @ 24c659e`). Colunas de
saída sufixadas `{col}__{sid}` não colidem entre os grupos (sids disjuntos).

### §1.1 Grupo C — habitat confirmation (7 assinaturas)

Assinaturas: `('A3', 'A2', 'A4a', 'A1', 'A9', 'A6', 'A10')`.

| Campo | Valor congelado | Base |
|---|---|---|
| `signature` | `('A3','A2','A4a','A1','A9','A6','A10')` | — |
| `entry_mode` | `'confirmation'` | [Certo] habitat medido (golden + 2y) |
| `armed_escape_pct` | `0.02` | legado (hyperopt futuro) |
| `armed_timeout_candles` | `24` | legado |
| `pending_timeout_candles` | `16` | legado |
| `sweep_recency_candles` | `16` | legado |
| `fvg_ob_adjacency_pct` | `0.003` | legado |
| `rejection_wick_frac` | `0.5` | legado |
| `rejection_close_frac` | `0.667` | legado |
| `volume_pct_min` | `0.2` | legado (A5 ausente deste grupo; valor é espaço de hyperopt) |
| `trend_suffix` / `zone_suffix` | `'4h'` / `'1h'` | scaffold Wave 10a |
| `arming_proximity_pct` | `0.02` | [Certo] Bloco1-ON medido (G1) |
| `confirmation_trigger` | `'choch'` | [Certo] Bloco1-ON medido (G2) |
| `anchor_invalidation` | `'frozen_band'` | [Certo] Bloco1-ON medido (G3) |
| `a9_variant` | `'sweep_band'` | [Certo] Bloco1-ON medido (G5) |
| `displacement_gate` | `'confirm'` | [Certo] medido (Onda 1: 86→40 CONFIRMED) |
| `displacement_body_len` | `10` | Pine §10.5 |
| `displacement_wick_frac` | `0.36` | Pine §10.5 |
| `ote_lifecycle` | `'v2'` | [Certo] medido (Onda 2) |
| `ote_require_eq_cross` | `True` | [Certo] medido (113/3→34/1) |
| `ote_require_confluence` | `True` | [Certo] medido (→16/1) |
| `a7_variant` | `'legacy'` (inerte — A7 ausente) | default |
| `a7_fvg_window` | `2` (inerte) | default |
| `killzone_qualifier` | `()` | espaço de hyperopt, não medido por assinatura |
| `ob_semantics` | `'strategic'` | [Provável] razão de existir do §2.10; `primitive` vira ablação |

### §1.2 Grupo R — habitat risk/tap (2 assinaturas)

Assinaturas: `('A5', 'A7')`. Justificativa: A7 `chain_v2` mediu **0 CONFIRMED** em
confirmation (PR #87 — habitat declarado risk/tap); A5 é nativamente
`ENTRY_MODE_RISK` no registry (`setup_state.py:1298-1301 @ 24c659e`, arquétipo `tap`).
Congelar ambas em confirmation seria descarte sem processo (regra permanente do
Marcelo).

| Campo | Valor congelado | Base |
|---|---|---|
| `signature` | `('A5', 'A7')` | — |
| `entry_mode` | `'risk'` | [Certo] registry A5; [Provável] habitat A7 (medição PR #87) |
| `arming_proximity_pct` | `0.02` | [Suposição] coerência Bloco 1; conjunção risk∧prox **não medida** — gates adjudicam |
| `anchor_invalidation` | `'frozen_band'` | [Suposição] idem |
| `confirmation_trigger` | `'legacy'` | inerte em risk (ARMED→CONFIRMED direto, sem etapa de confirmação) |
| `a9_variant` | `'legacy_ob'` (inerte — A9 ausente) | default |
| `displacement_gate` | `'off'` | [Certo] displacement foi medido apenas como gate de **confirmação**; conjunção risk∧displacement não medida — regra "medir antes de embarcar" |
| `ote_lifecycle` / `ote_require_*` | `'legacy'` / `False` (inertes — A10 ausente) | guardas satisfeitas |
| `a7_variant` | `'chain_v2'` | [Certo] medido (10 cadeias 5/5 → 7 setups) |
| `a7_fvg_window` | `2` | valor da medição |
| `killzone_qualifier` | `()` | killzone é intrínseca à cadeia da A7 |
| `ob_semantics` | `'primitive'` (inerte — A1 ausente) | default |
| Demais campos | idênticos ao Grupo C | legado |

**Expectativa pré-registrada:** A5 com `volume_pct_min=0.2` está acima do teto
empírico em 3 dos 4 lados-ativo (adendo 2y, G4) — resultado esperado é
**PARKED por amostra insuficiente**, não descarte. `volume_pct_min` pertence à fase
de hyperopt (§4-P6), decisão já documentada na docstring do `SetupConfig`.

### §1.3 Arbitragem D3 no consumidor (pré-registrada)

`compute_setup_state_multi` não arbitra (decisão de design, G9). Regras da camada
IStrategy, congeladas aqui:

1. **Mesma vela, múltiplos sids CONFIRMED, mesma direção** → vence o de maior
   prioridade D3 (ordem do registry: A3 > A2 > A4a > A5 > A1 > A9 > A6 > A7 > A10);
   `enter_tag = f"{sid_vencedor}_{direção}"`.
2. **Mesma vela, direções conflitantes** → **nenhuma entrada** (evidência
   contraditória); a ocorrência é contada em coluna diagnóstica
   (`setup_conflict_dirs`) para o relatório.
3. Um trade por par por vez (comportamento default do Freqtrade — não alterar
   `max_open_trades` por par nesta fase).

### §1.4 Cláusula de exequibilidade

Ajustes **de exequibilidade** (a config congelada não roda por razão estrutural
descoberta na Wave 10.1/10.2 — ex.: guarda de validação, coluna ausente) são
permitidos com registro em emenda datada neste documento, desde que **nenhum valor
numérico de parâmetro** mude. Mudança de parâmetro ⇒ novo ciclo (§4-P5).

---

## §2. Universo de dados congelado

| Item | Valor |
|---|---|
| Treino | `BTC/USDT:USDT` (OKX, futures/isolated), 15m+1h+4h, **2024-07-01 00:00 UTC → 2026-06-30 00:00 UTC** |
| OOS | `ETH/USDT:USDT`, mesma janela, mesmos TFs |
| [Suposição] | A janela do adendo 2y pode diferir; a janela que governa é a deste documento |

**Custos (regra pré-registrada):** `config_backtest.json @ 24c659e` tem `fee: None`
— **custo zero, inaceitável para veredito de edge**. Antes da primeira execução
(§4-P3), o fee **taker** da OKX para USDT-perp deve ser fixado no config com fonte
citada (página oficial de fees da OKX, data de consulta no relatório da execução),
aplicado nas duas pernas. Slippage não é modelado nesta fase — limitação documentada,
que **enviesa a favor** da candidata; vereditos PASS carregam esse asterisco.

---

## §3. Gates de edge (pré-registrados, por assinatura)

Unidade de avaliação: assinatura isolada (via `enter_tag`, agrupamento nativo do
relatório de backtest). R de um trade = `|entry − sl_anchor|`.

| Gate | Critério | Veredito se falha |
|---|---|---|
| **GE-0** (harness) | Suíte known-answer (Wave 10.2) 100% verde antes de qualquer backtest real | bloqueia tudo |
| **GE-1** (amostra treino) | `n_trades ≥ 30` no treino BTC 2y | **PARKED** (amostra insuficiente — estacionar, nunca descartar) |
| **GE-2** (expectância treino) | expectância média por trade `> 0R` **líquida de fee** | **FAIL-treino** |
| **GE-3** (OOS) | ETH: `n_oos ≥ 10` **e** expectância de mesmo sinal (positiva) | `n_oos < 10` ⇒ **PARKED-OOS**; sinal negativo ⇒ **FAIL-OOS** |

Vereditos possíveis por assinatura: `PASS` (GE-1∧GE-2∧GE-3), `FAIL-treino`,
`FAIL-OOS`, `PARKED`, `PARKED-OOS`. `FAIL` alimenta a fase de hyperopt como hipótese
a re-testar sob novo pré-registro — **não** é exclusão permanente (regra do Marcelo).
Nenhum gate usa magnitude de OOS (só sinal): OOS pequeno demais para calibrar
magnitude sem overfit.

---

## §4. Protocolo anti-derivação (ordem de operações)

- **P1.** Este documento entra no repositório no PR da Wave 10.1 — antes de o
  harness ser validado e antes de qualquer execução.
- **P2.** Wave 10.2: suíte known-answer (trades sintéticos com desfecho conhecido
  atravessando a camada IStrategy; asserts de contagem, preços de entrada/saída e
  P&L contra valores calculados à mão). Verde ⇒ GE-0 satisfeito.
- **P3.** Execução 1: treino BTC. Tabela de vereditos GE-1/GE-2 **escrita e
  commitada** antes de qualquer execução OOS.
- **P4.** Execução 2: OOS ETH. Vereditos GE-3. Relatório final referencia o hash do
  commit deste documento.
- **P5.** Qualquer mudança de config após P3 ⇒ novo ciclo de pré-registro. Mudança
  após P4 ⇒ ETH está **queimado** como OOS; plano B é walk-forward em janelas
  não usadas.
- **P6.** Fase de hyperopt (acervo de calibração do handoff §5.4): opera
  **exclusivamente** sobre o treino BTC; qualquer promoção a candidata exige novo
  documento de congelamento + OOS virgem ou walk-forward.
- **P7.** Quem vê P&L: os números de P&L só existem a partir de P3 e são reportados
  integralmente no chat (Marcelo + analista) — não há execução exploratória fora de
  P3/P4.

---

*Documento escrito em 2026-07-09, main @ 24c659e, VERSION 0.10.1. Imutável salvo
§1.4 (emendas de exequibilidade) e §4-P5 (novo ciclo).*
