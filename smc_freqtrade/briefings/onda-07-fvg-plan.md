# Plan — Sessão Code Onda 7 (Fair Value Gaps) — planejamento arquitetural

> **Status:** finalizado para aprovação. Esta sessão **não escreve código de
> implementação**, não altera VERSION e não abre PR. O entregável fora deste
> plan file é o briefing `smc_freqtrade/briefings/onda-07-fvg-spec.md`,
> escrito na sessão Code subsequente após `ExitPlanMode` + aprovação.

---

## Contexto

Subprojeto `smc_freqtrade/` em `marcelolara-glitch/SMC_Monitor`. Porta verbatim
o indicador LuxAlgo SMC (Pine compute-only) para Python puro sobre DataFrame,
cadência por ondas. Ondas 1-6 mergeadas, VERSION 0.6.0. Wave 6 (Order Blocks)
validada por spot-check híbrido (PR #46 mergeado). Esta sessão **planeja** a
**Onda 7 (Fair Value Gaps)** com:

- Detecção FVG bullish/bearish (padrão de 3 candles do Pine).
- Mitigação fiel ao Pine compute-only (1 modo: full fill).
- Filtro de volatilidade fiel ao Pine (bool `auto_threshold`, default True).
- UDT estendido com timestamps de lifecycle + hooks para Onda 7.1, 7.2, 7.3.

## Estado do repo verificado

| Item | Estado |
|---|---|
| Branch | `claude/plan-fvg-wave-7-QykmY` (pré-criada) |
| VERSION | `0.6.0` (não mexer) |
| `smc_engine/` | `__init__.py`, `operators.py`, `order_blocks.py`, `pivots.py`, `state.py`, `structure.py`, `trailing.py`, `types.py` |
| Briefings | Wave 5 (spec+audit+consistency), Wave 6 (spec+audit) presentes |
| Spot-check | `docs/spot_checks/wave-06-order-blocks-relatorio.md` presente |

---

## Achados-chave da pesquisa (Phase 1)

### Pine fonte (`tools/pynecore-validation/luxalgo_smc_compute_only.py`)

| Item | Linha | Verbatim / nota |
|---|---|---|
| UDT `fairValueGap` | 47-50 | 3 campos: `top`, `bottom`, `bias`. SEM `barTime`. |
| Input `fairValueGapsThresholdInput` | 91 | `bool` default `True`. Único input FVG-volatilidade. |
| Input `fairValueGapsTimeframeInput` | 92 | Timeframe MTF — string vazia = mesmo TF do chart. |
| Threshold computado | 287 | `cum(|barDeltaPercent|)/bar_index*2` se input True else 0 |
| Bullish create | 288 | `currentLow > last2High AND lastClose > last2High AND barDeltaPercent > threshold` |
| Bearish create | 289 | `currentHigh < last2Low AND lastClose < last2Low AND -barDeltaPercent > threshold` |
| Bullish mitigate | 278 | `low < eachFairValueGap.bottom AND bias == BULLISH` |
| Bearish mitigate | 278 | `high > eachFairValueGap.top AND bias == BEARISH` |
| Ordem callsite | 306-319 | `deleteFairValueGaps` (307) ANTES de `drawFairValueGaps` (319) |
| Mode count | — | **1 modo apenas**. Sem Close/Wick/Average/None no compute-only. |
| Inverse / Double / BPR | — | NÃO presentes. Features do LuxAlgo pago. |

**Padrão de 3 candles (notação Pine backward-index):** terceiro candle = `t` (atual), segundo = `t-1` (`lastOpen`/`lastClose`), primeiro = `t-2` (`last2High`/`last2Low`).

### UDT Python atual (`smc_engine/types.py:203-216`)

```python
@dataclass
class FairValueGap:
    top: Optional[float] = None
    bottom: Optional[float] = None
    bias: Optional[int] = None
```

**Sem** `bar_time`, sem timestamps, sem `state`. Docstring raso (Wave 1, pré-arquitetura de lifecycle). Precisa ser estendido análogo ao `OrderBlock` (Wave 6).

### Template Wave 6 (`smc_engine/order_blocks.py`)

- Constantes `COL_OB_*` exportadas (`order_blocks.py:79-86`) — 8 booleans.
- Assinatura `(df, *, ob_filter, mitigation, atr_length) -> tuple[pd.DataFrame, pd.DataFrame]`.
- Helpers privados sequenciais: `_compute_parsed_high_low`, `_emit_create_record`, `_emit_create_events`, `_resolve_mitigations`, `_build_ledger`.
- Ledger schema: `ob_id`, `scope`, `bias`, `bar_high`, `bar_low`, `bar_time`, `t_creation`, `t_mitigation`, `t_invalidation`, `state`, `volumetric_intensity` (11 colunas).
- `EngineState.fair_value_gaps` slot existe (`state.py:105`) — **NÃO popular**.
- `bar_time ≡ t_origin` preservado (P12 Wave 6).
- 13 invariantes no smoke; co-mitigação determinística (invariante 13).

### Mapa Camada 1 v1.1 (`docs/MAPA_LUXALGO_CAMADA_1_v1.1.md`)

| Seção | Achado |
|---|---|
| §6 (322-344) | Prescreve assinatura `(df_base, df_fvg_tf=None, state=None) -> pd.DataFrame`. **Conflita com prompt §2.2.** Conflito resolvido (Q4): seguir prompt, hook MTF para Wave 7.3, patch Mapa. |
| §7.1 (438-449) | LuxAlgo gratuito = referência canônica, match exato com ±1 candle. |
| §7.4 (486-490) | Tolerância ±1 candle. |
| §7.6.1 (530-546) | **Timestamp visual canônico FVG = terceiro candle do padrão (quando gap fica conhecido)**. |
| §7.8 (606-629) | `FVG mitigation Close/Wick/Average/None` → **Onda 6.1** (decidido). `Inverse FVG` → Onda 7.x pendente. `Double FVG / BPR` → Onda 7.x pendente. `Volume Imbalance / Opening Gap` → **excluído** (perpetual swap). |
| §7.9 (633-659) | Nenhuma divergência FVG registrada ainda. |

### Validação visual (`docs/REFERENCIA_VALIDACAO_VISUAL_LUXALGO.md`)

FVGs ratificados disponíveis para spot-check:
- **V4** (91.200–92.000, 2026-01-20) — bearish
- **V5** (85.700–87.400, 2026-01-29) — bearish
- 8 FVGs bullish identificados nos shots 4, 5, 7, 8 (fev-mai 2026)

### Avaliação LuxAlgo pago (`docs/AVALIACAO_LUXALGO_PRICE_ACTION_CONCEPTS_v1.0.md`)

- §2.5/§4.5: 4 mitigation modes + Volatility Threshold multiplier = **LuxAlgo pago**, Categoria B.
- §6.2: Inverse FVG e Double FVG / BPR descritos.
- §4.5/§6.2: Volume Imbalance e Opening Gap excluídos para perpetual swap 24/7.

### Dogma SMC (`docs/SMC_PRINCIPIOS_E_LEGADO.md`)

**Não define FVG dogmaticamente.** Sem base para nova entrada em §7.9. Item em aberto §11 para registro caso spot-check revele divergência.

---

## Decisões fechadas

| # | Tópico | Decisão | Origem |
|---|---|---|---|
| D1 | UDT field names | Manter `top`/`bottom`/`bias`, estender com timestamps e hooks | Q1 user + Pine 47-50 + Wave 1 |
| D2 | Mitigation modes | 1 modo fiel ao Pine (`low<bottom` / `high>top`). SEM param `mitigation` | Q2 user + Pine 278 + Mapa §7.8 |
| D3 | Volatility filter | `auto_threshold: bool = True`. Replica Pine cumulativo `cum(|delta%|)/bar_index*2`. | Q3 → Claude por canônico: AGENTS §1.0.1 + Pine 287 |
| D4 | API signature | `(df, *, auto_threshold=True) -> tuple[df_per_candle, fvg_ledger]`. Sem MTF agora. | Q4 user. Patch ao Mapa §6 v1.1 documentando assinatura final |
| D5 | `bar_time` em FVG | Timestamp do **primeiro candle do padrão de 3** (= âncora estrutural, define o nível do gap). **`bar_time ≠ t_creation` por construção em FVG** — diferente da Wave 6 onde coincidem por convenção P12. `t_creation` permanece como **terceiro candle** (momento em que o gap fica conhecido, alinhado com Mapa §7.6.1). Ambos preservados no ledger; spot-check pode comparar contra qualquer convenção visual sem refactor | Analogia Wave 6 P12 + Mapa §7.6.1. Item A1 resolvido por esta decisão (D5 deixa de ser risco aberto) |
| D6 | `scope` | **Ausente** em FVG (LuxAlgo gratuito não distingue internal/swing) | Pine 47-50 |
| D7 | Co-mitigação simultânea | Múltiplos FVGs mitigados no mesmo candle Z → cada um recebe `t_mitigation = ts(Z)`. Booleano per-direction agregado | Analogia Wave 6 invariante 13 |
| D8 | CREATE+MITIGATE no mesmo candle | **Impossível por construção** — Pine roda `delete` antes de `draw`. Invariante: `t_mitigation > t_creation` estrita | Pine 306-319 |
| D9 | Ordem dentro do candle | Bullish create antes de bearish create (replicar Pine 290-296) | Pine 290-296 |
| D10 | Hooks reservados | 4 hooks documentados: `is_inverse` (7.1), `is_double` (7.2), `df_fvg_tf` MTF (7.3), `volatility_threshold` float multiplier do pago (7.x) | Q1+Q2+Q4 + Avaliação §2.5/§6.2 |

---

## Estrutura do briefing final (`smc_freqtrade/briefings/onda-07-fvg-spec.md`)

A escrever na sessão Code subsequente. 11 seções herdadas Wave 6:

### §1 Contexto
- Pine fonte: `tools/pynecore-validation/luxalgo_smc_compute_only.py` linhas 46-50 (UDT), 91-92 (inputs), 274-297 (lógica), 306-319 (callsite).
- Roadmap: Onda 7 entre OB (6) e Liquidity Sweep (8).
- Ondas consumidas: zero (FVG é primitiva sobre OHLC, sem dependência BOS/CHoCH).
- Recorte: B (LuxAlgo gratuito completo + hooks pagos).

### §2 Premissas técnicas (P1-P10)
- **P1** — Gatilho via OHLC direto, sem consumir Onda 5.
- **P2** — 1 modo de mitigação Pine-fiel. SEM param `mitigation` na assinatura. Hook estrutural via campo `state` (string).
- **P3** — UDT estendido com timestamps lifecycle + hooks (`is_inverse`, `is_double`).
- **P4** — `auto_threshold: bool = True` — replica Pine `fairValueGapsThresholdInput`. Cálculo cumulativo: `cum(|delta%|)/bar_index*2`.
- **P5** — `t_mitigation > t_creation` estrito (Pine garante por ordem de execução; redundante mas defensivo).
- **P6** — `bar_time = t_creation - 2_candles` (primeiro candle do padrão).
- **P7** — Inverse FVG (Onda 7.1), Double FVG / BPR (Onda 7.2), MTF (Onda 7.3), volatility_threshold multiplier do pago (Onda 7.x). Hooks reservados.
- **P8** — Lookahead-safe (sem `lookahead_on`; Mapa §6 conflito B).
- **P9** — Equivalência `bar_time ≡ t_origin` (analogia P12 Wave 6, redocumentada para FVG).
- **P10** — Ordem dentro candle: bullish create antes de bearish create (Pine 290-296).

### §3 Plano de execução numerado
1. Estender `FairValueGap` em `smc_engine/types.py` (manter top/bottom/bias + adicionar 6 campos: `bar_time`, `t_creation`, `t_mitigation`, `t_invalidation`, `state`, `is_inverse`, `is_double`).
2. Criar `smc_engine/fvg.py` (constantes `COL_FVG_*`, helpers privados, `detect_fair_value_gaps`).
3. Criar `tests/test_smoke_wave7.py` (≥7 fases sintéticas + 12 invariantes + validação isolada do threshold).
4. Atualizar `smc_engine/__init__.py` (exportar `detect_fair_value_gaps` + 4 constantes COL_FVG_*).
5. Spot-check híbrido sobre golden CSV com V4 e V5 como ratificação inicial.

### §4 Spec funcional

#### §4.1 Assinatura pública

```python
def detect_fair_value_gaps(
    df: pd.DataFrame,
    *,
    auto_threshold: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame]:
```

Docstring AGENTS §1.4 (4 blocos OBJETIVO / FONTE DE DADOS / LIMITAÇÕES / NÃO FAZER):
- Declarar `date` esperado (réplica patch §5.12 Wave 6).
- NÃO popular `EngineState.fair_value_gaps`.
- Declarar 4 hooks reservados.
- LIMITAÇÕES: divergência `lookahead_on` documentada (Mapa §6 conflito B).

#### §4.2 Constantes `COL_FVG_*`

```
COL_FVG_BULLISH_CREATED
COL_FVG_BEARISH_CREATED
COL_FVG_BULLISH_MITIGATED
COL_FVG_BEARISH_MITIGATED
```

4 colunas (sem internal/swing → metade da Wave 6).

#### §4.3 Schema do output

- `df_per_candle` (cópia do `df` + 4 booleans).
- `fvg_ledger` DataFrame com schema:
  `fvg_id` (int), `bias` (int ±1), `top` (float), `bottom` (float), `bar_time` (int/timestamp), `t_creation` (int/timestamp), `t_mitigation` (int/timestamp ou NaT), `t_invalidation` (sempre NaT), `state` ('active'|'mitigated'), `is_inverse` (False), `is_double` (False) — **11 colunas**.

#### §4.4 Invariantes do smoke (mínimo 12)
1. `top > bottom` para todo registro (gap não-degenerado).
2. `bias ∈ {BULLISH=+1, BEARISH=-1}`.
3. `state ∈ {'active', 'mitigated'}`.
4. `state='active' ⟺ t_mitigation is pd.NaT`.
5. `t_invalidation is pd.NaT` para todos (Wave 7).
6. `is_inverse == False` para todos.
7. `is_double == False` para todos.
8. `t_creation = bar_time + 2_candles` (deslocamento estrito do padrão de 3).
9. `t_mitigation > t_creation` quando preenchido (estrito; Pine garante por callsite).
10. Mutual exclusion CREATE×MITIGATE no mesmo candle no mesmo FVG (corolário de #9).
11. **11a — Determinismo do ledger em co-mitigação:** múltiplos FVGs ativos mitigados no mesmo candle Z compartilham exatamente `t_mitigation = ts(Z)` (não há tie-breaking por ordem de criação, índice ou bias).
12. **11b — Semântica do boolean per-candle:** `COL_FVG_BULLISH_MITIGATED[Z]` é True ⟺ ≥1 FVG bullish foi mitigado no candle Z (OR agregado sobre todos os FVGs bullish ativos imediatamente antes de Z). Idem para `COL_FVG_BEARISH_MITIGATED`. As duas flags podem coexistir como True no mesmo candle quando direções opostas mitigam simultaneamente (item A4 validado pelo smoke).

#### §4.5 Algoritmo em prosa
- **CREATE pass vetorizado**: identificar índices `t` onde `low[t] > high[t-2]` (bullish) ou `high[t] < low[t-2]` (bearish), filtrar por threshold (se `auto_threshold=True`, computar cumulativo Pine), emitir record com `bar_time=ts(t-2)`, `t_creation=ts(t)`, `top`/`bottom` conforme Pine.
- **Threshold cumulativo**: `barDeltaPercent[i] = (close[i-1] - open[i-1]) / (open[i-1] * 100)`; `threshold[i] = cum(|barDeltaPercent|)[i] / (i+1) * 2`. Vetorizar com `np.cumsum(np.abs(...))`.
- **MITIGATION pass**: iterar records `active`, buscar primeira vela com `date > t_creation` que satisfaz `low < bottom` (bullish) ou `high > top` (bearish), preencher `t_mitigation` + `state='mitigated'`. Vetorização análoga ao `_resolve_mitigations` Wave 6 (linhas 295-356).
- **Ordem dentro candle (P10)**: ao construir o ledger, bullish records antes de bearish do mesmo `t_creation`.

**Validação isolada do threshold (pré-requisito das 7 fases):** antes de testar detecção FVG, validar a função interna que computa o threshold cumulativo contra fixture mínima de 4-5 candles com `barDeltaPercent` pré-computado manualmente. Cobrir o edge case `bar_index=0` (primeira vela: threshold deve ser tratado como 0 ou ausente, replicando comportamento Pine em vela inicial — Pine `bar_index` é 0 no primeiro candle e a divisão produziria `inf`/`NaN`; replicar o guard com clamp `bar_index = max(bar_index, 1)` ou condicional explícita). Item A2 fica validado por este teste, que vive em `tests/test_smoke_wave7.py` como bloco separado das 7 fases de FVG.

### §5 Smoke test sintético

Fixture ≥250 candles. 7 fases planejadas:
1. **Fase setup** — sem gap (estabelecer baseline).
2. **Bullish FVG criado** — padrão 3-candle com gap; verifica `state='active'`.
3. **Bullish FVG mitigado** — `low` posterior penetra `bottom`; verifica `t_mitigation > t_creation`.
4. **Bearish FVG criado e ativo** — sem mitigação até fim da janela.
5. **Fase 5 — `auto_threshold=False` (threshold = 0):** mesma fixture das Fases 2-4, mas chamando `detect_fair_value_gaps(df, auto_threshold=False)`. Invariante de **diferenciação**: a contagem de FVGs detectados com `auto_threshold=False` deve ser **estritamente maior** que com `auto_threshold=True` (gaps geométricos pequenos que o threshold cumulativo filtraria agora passam). Verificar que pelo menos 1 FVG aparece exclusivamente no modo False.
6. **Mid-candle gap não-detectado** — `low[t] > high[t-2]` falso por wick intermediário; verifica não-emissão.
7. **Co-mitigação** — múltiplos FVGs bullish ativos, queda forte mitiga ≥2 num candle.

### §6 Critério de aceite global
Checkbox padrão Wave 6 adaptado:
- [ ] Tipos estendidos em `types.py` (campos novos com defaults seguros).
- [ ] `fvg.py` criado, docstring AGENTS §1.4 completo.
- [ ] `__init__.py` exportando função + 4 COL_FVG_*.
- [ ] `tests/test_smoke_wave7.py` cobrindo 12 invariantes + 7 fases + validação isolada do threshold.
- [ ] `pytest smc_freqtrade/tests/test_smoke_wave7.py -v` passa.
- [ ] `ruff check smc_freqtrade/smc_engine/fvg.py` sem erros.
- [ ] Spot-check híbrido contra V4 (91.200–92.000) e V5 (85.700–87.400) — ratificação inicial.
- [ ] Spot-check de ao menos 3 FVGs bullish dos shots 4/5/7/8.

**Critério de tolerância no spot-check híbrido:**
- Tolerância de **±1 candle** aplica-se a `t_creation` e `t_mitigation` (Mapa §7.4).
- Mitigação requer penetração **estrita**: `low < bottom` (bullish) ou `high > top` (bearish). Tangenciamento exato (`low == bottom`) **não** mitiga, fiel ao Pine compute-only linha 278.
- FVG visualmente "preenchido parcialmente" no TradingView (wick que entra mas não atravessa) deve permanecer `active` no ledger — não é divergência.

- [ ] VERSION bump (0.6.0 → 0.7.0) — **Marcelo faz manualmente**.

### §7 Atualização do Mapa (patches pós-merge)
- **§6** — atualizar assinatura `detect_fair_value_gaps` para `(df, *, auto_threshold=True) -> tuple[pd, pd]`. Documentar hook MTF para Wave 7.3.
- **§7.6** — criar §7.6.3 análogo a §7.6.1/§7.6.2: regra visual canônica para FVG (caixa pequena tipo gap; comparar com terceiro candle do padrão).
- **§7.8** — atualizar status:
  - `Inverse FVG` → **Decidido — hook `is_inverse` em `fvg.py` (Onda 7.1)**.
  - `Double FVG / BPR` → **Decidido — hook `is_double` em `fvg.py` (Onda 7.2)**.
  - `FVG MTF (timeframe input)` → **Decidido — hook `df_fvg_tf` parâmetro futuro (Onda 7.3)**.
  - `Volatility Threshold multiplier (pago)` → **Decidido — hook nome `volatility_threshold` reservado (Onda 7.x)**.

### §8 Hooks de absorção do LuxAlgo pago
- **Onda 7.1** Inverse FVG — campo `is_inverse: bool = False`.
- **Onda 7.2** Double FVG / BPR — campo `is_double: bool = False`.
- **Onda 7.3** MTF — parâmetro `df_fvg_tf: pd.DataFrame | None = None` (Mapa §6 v1.1 prescrição original).
- **Onda 7.x** Volatility multiplier — parâmetro `volatility_threshold: float | None = None` (do pago, Avaliação §2.5).

### §9 Cláusula de conflito briefing vs realidade
Texto padrão Wave 6 — quando o spot-check revelar divergência, abrir audit ao invés de "forçar" decisão.

### §10 Referências canônicas
Lista de leituras na ordem da §3 do prompt do usuário (Pine, Mapa, Validação Visual, Avaliação, Dogma SMC, AGENTS, módulos Wave 1-6, briefings Wave 6, spot-check Wave 6).

### §11 Itens em aberto para audit
- **A3**: Dogma SMC vs LuxAlgo para FVG — `SMC_PRINCIPIOS_E_LEGADO.md` não define FVG. Pendente: se Marcelo decidir registrar definição dogmática, criar entrada em §7.9 do Mapa (precedente Wave 6 OB).

(A1, A2 e A4 foram resolvidos durante o review: A1 → D5 refinada; A2 → validação isolada do threshold em §4.5 + smoke; A4 → invariante 11b explicita coexistência de flags.)

---

## Arquivos críticos a modificar (na sessão Code subsequente)

| Path | Ação |
|---|---|
| `smc_freqtrade/smc_engine/types.py` | Estender dataclass `FairValueGap` (linhas 203-216) com 7 novos campos |
| `smc_freqtrade/smc_engine/fvg.py` | **Novo módulo** — análogo estrutural a `order_blocks.py` |
| `smc_freqtrade/smc_engine/__init__.py` | Adicionar imports + atualizar `__all__` |
| `smc_freqtrade/tests/test_smoke_wave7.py` | **Novo smoke** — 7 fases + 12 invariantes + validação isolada do threshold |
| `smc_freqtrade/briefings/onda-07-fvg-spec.md` | **Novo briefing** — entregável desta sessão |

### Reuso de utilitários existentes
- `smc_engine/operators.py` — possivelmente NENHUM (FVG é OHLC puro, sem ATR). Verificar `cum_sum` para o threshold cumulativo.
- `smc_engine/types.py:9-11` — constantes `BULLISH=1`, `BEARISH=-1` (já existem).
- Padrão `df.copy()` + tuple-return — replicar `order_blocks.py:507`, `:525`.
- Padrão de helpers privados — replicar template `_emit_create_events` + `_resolve_mitigations`.

---

## Verificação end-to-end (na sessão Code subsequente)

```bash
cd ~/SMC_Monitor
pytest smc_freqtrade/tests/test_smoke_wave7.py -v
ruff check smc_freqtrade/smc_engine/fvg.py
```

Spot-check híbrido manual (analogia Wave 6):
- Rodar `detect_fair_value_gaps` sobre `data/btc_usdt_swap_4h_window.csv` (mesma fixture Wave 6).
- Comparar ledger contra:
  - V4 bearish (91.200–92.000, 2026-01-20).
  - V5 bearish (85.700–87.400, 2026-01-29).
  - ≥3 FVGs bullish dos shots 4/5/7/8.
- Tolerância ±1 candle (Mapa §7.4).

---

## Fluxo da sessão Code subsequente

1. Implementação seguindo §3 do briefing (5 passos).
2. Commit:
   ```
   docs(briefing): planejamento da Onda 7 (Fair Value Gaps)
   ```
   (apenas o briefing — implementação vem em PR separado, padrão Wave 6).
3. Push: `git push -u origin claude/plan-fvg-wave-7-QykmY`.
4. **Não abrir PR.** Marcelo abre PR consolidado depois (briefing + audit report).
5. Reportar branch name explicitamente: `claude/plan-fvg-wave-7-QykmY`.

---

## §12 — Anexo: blocos de código em texto puro (para revisão Claude.ai)

Conteúdo literal copiável. Cada bloco é o que a sessão de implementação
escreverá verbatim no módulo correspondente.

### §12.1 — Assinatura completa de `detect_fair_value_gaps`

```python
def detect_fair_value_gaps(
    df: pd.DataFrame,
    *,
    auto_threshold: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame]:
```

Retorno: `(df_per_candle, fvg_ledger)`.
- `df_per_candle`: cópia de `df` acrescida das 4 colunas booleans `COL_FVG_*`.
- `fvg_ledger`: DataFrame com 11 colunas conforme §12.4.

### §12.2 — Docstring AGENTS §1.4 (4 blocos)

```python
"""Detecta Fair Value Gaps bullish e bearish via padrão de 3 candles, com
mitigação fiel ao Pine compute-only.

OBJETIVO
    Portagem fiel de `drawFairValueGaps` (Pine linhas 283-297) e
    `deleteFairValueGaps` (linhas 274-281) do indicador LuxAlgo SMC
    compute-only em `tools/pynecore-validation/luxalgo_smc_compute_only.py`.
    Emite ledger DataFrame com lifecycle de 4 timestamps (`bar_time`,
    `t_creation`, `t_mitigation`, `t_invalidation`) e `state ∈ {'active',
    'mitigated'}`, mais 4 colunas booleans per-candle agregadas
    (BULLISH/BEARISH × CREATED/MITIGATED).

FONTE DE DADOS
    df: DataFrame OHLC com coluna `date` (datetime64[ns, UTC] ou int64 ns)
        e colunas obrigatórias `open`, `high`, `low`, `close`. Demais
        colunas são preservadas em `df_per_candle`. Index é preservado.
    Pine fonte:
        UDT `fairValueGap` — linhas 46-50 (`top`, `bottom`, `bias`).
        Inputs — linhas 91-92 (`fairValueGapsThresholdInput` bool,
            `fairValueGapsTimeframeInput` timeframe).
        Lógica — linhas 274-297.
        Callsite — linhas 306-319 (`deleteFairValueGaps` antes de
            `drawFairValueGaps`).
    Convenções temporais:
        `bar_time` = timestamp do **primeiro** candle do padrão de 3
            (âncora estrutural; define o nível do gap).
        `t_creation` = timestamp do **terceiro** candle (momento em
            que o gap fica conhecido; alinhado com Mapa §7.6.1).
        Em FVG, `bar_time ≠ t_creation` por construção (diferente de
            Wave 6 P12 onde coincidem).

LIMITAÇÕES CONHECIDAS
    1 modo de mitigação Pine-fiel: bullish quando `low < bottom`,
        bearish quando `high > top` (penetração estrita, linha 278).
        Os 4 modos do LuxAlgo pago (Close/Wick/Average/None) são hook
        Onda 6.1 / 7.x.
    `auto_threshold=True` replica `fairValueGapsThresholdInput`
        cumulativo `cum(|barDeltaPercent|)/bar_index*2` (Pine
        linha 287). Edge case `bar_index=0` clamped para evitar
        divisão por zero.
    Inverse FVG → hook Onda 7.1 (campo `is_inverse`, sempre False
        em Wave 7).
    Double FVG / Balanced Price Range → hook Onda 7.2 (campo
        `is_double`, sempre False em Wave 7).
    MTF (`fairValueGapsTimeframeInput`) → hook Onda 7.3 (parâmetro
        `df_fvg_tf` reservado, Mapa §6 v1.1 prescrição inicial).
    Volatility threshold multiplicativo do pago → hook Onda 7.x
        (parâmetro `volatility_threshold` reservado).
    Divergência intencional do Pine: NÃO replicamos
        `lookahead=barmerge.lookahead_on` (Mapa §6 conflito B).
        Confiar em merge_informative_pair prévio do Freqtrade quando
        MTF for habilitado (Wave 7.3).

NÃO FAZER
    Não popular `EngineState.fair_value_gaps`. A portagem é vetorizada
        sobre DataFrame; o ledger substitui o slot.
    Não adicionar param `mitigation` em Wave 7 — Onda 6.1 / 7.x cobrirão.
    Não renomear campos do UDT (`top`, `bottom`, `bias`) — fiel ao Pine
        linhas 46-50 e à Wave 1.
    Não computar `t_invalidation` em Wave 7 — sempre `pd.NaT`.
    Não inferir `bar_time = t_creation` por analogia com Wave 6 P12 —
        em FVG são distintos por construção (D5).
    Não usar lookahead — toda detecção é causal sobre o DataFrame
        passado.
"""
```

### §12.3 — Constantes `COL_FVG_*`

```python
COL_FVG_BULLISH_CREATED: str = "fvg_bullish_created"
COL_FVG_BEARISH_CREATED: str = "fvg_bearish_created"
COL_FVG_BULLISH_MITIGATED: str = "fvg_bullish_mitigated"
COL_FVG_BEARISH_MITIGATED: str = "fvg_bearish_mitigated"
```

### §12.4 — Schema do ledger (11 colunas, dtypes pandas)

```python
LEDGER_SCHEMA: dict[str, str] = {
    "fvg_id":         "int64",                 # 1-indexed, ordem de criação
    "bias":           "int64",                 # +1 BULLISH | -1 BEARISH
    "top":            "float64",               # limite superior do gap
    "bottom":         "float64",               # limite inferior do gap
    "bar_time":       "datetime64[ns, UTC]",   # primeiro candle do padrão (D5)
    "t_creation":     "datetime64[ns, UTC]",   # terceiro candle, gap conhecido
    "t_mitigation":   "datetime64[ns, UTC]",   # nullable; pd.NaT se state='active'
    "t_invalidation": "datetime64[ns, UTC]",   # sempre pd.NaT em Wave 7
    "state":          "object",                # 'active' | 'mitigated'
    "is_inverse":     "bool",                  # sempre False em Wave 7 (hook 7.1)
    "is_double":      "bool",                  # sempre False em Wave 7 (hook 7.2)
}
```

Notas:
- `t_mitigation` e `t_invalidation` usam `datetime64[ns, UTC]` com `pd.NaT`
  como sentinel (pandas suporta NaT nativamente em colunas datetime tz-aware).
- `state` permanece como `object` (string) em Wave 7; futuro categorical
  (`pd.CategoricalDtype(['active','mitigated','breaker'])`) fica como
  refactor opcional pós-Onda 6.2.

### §12.5 — Atualização do `__init__.py`

Imports adicionados (após bloco da Wave 6):

```python
from .fvg import (
    detect_fair_value_gaps,
    COL_FVG_BULLISH_CREATED,
    COL_FVG_BEARISH_CREATED,
    COL_FVG_BULLISH_MITIGATED,
    COL_FVG_BEARISH_MITIGATED,
)
```

`__all__` — entradas adicionadas no final da lista existente (sem reordenar
o que já está lá; padrão Wave 6):

```python
__all__ = [
    # ... entradas existentes Wave 1-6 preservadas verbatim ...
    "detect_fair_value_gaps",
    "COL_FVG_BULLISH_CREATED",
    "COL_FVG_BEARISH_CREATED",
    "COL_FVG_BULLISH_MITIGATED",
    "COL_FVG_BEARISH_MITIGATED",
]
```

### §12.6 — Comando shell de spot-check sobre o golden CSV

```bash
cd ~/SMC_Monitor && python - <<'EOF'
import pandas as pd
from smc_freqtrade.smc_engine.fvg import detect_fair_value_gaps

df = pd.read_csv("data/btc_usdt_swap_4h_window.csv", parse_dates=["date"])
df_out, ledger = detect_fair_value_gaps(df, auto_threshold=True)
ledger.to_csv("docs/spot_checks/wave-07-fvg-ledger.csv", index=False)
print(f"FVGs detectados: {len(ledger)}")
print(f"  BULLISH active:    {((ledger.bias == 1) & (ledger.state == 'active')).sum()}")
print(f"  BULLISH mitigated: {((ledger.bias == 1) & (ledger.state == 'mitigated')).sum()}")
print(f"  BEARISH active:    {((ledger.bias == -1) & (ledger.state == 'active')).sum()}")
print(f"  BEARISH mitigated: {((ledger.bias == -1) & (ledger.state == 'mitigated')).sum()}")
print()
print("Candidatos ratificados (Mapa §5 + anotações pós-Wave-6):")
print("  V4 bearish: top=92000, bottom=91200, bar_time≈2026-01-18, t_creation≈2026-01-20 (±1 candle)")
print("  V5 bearish: top=87400, bottom=85700, bar_time≈2026-01-27, t_creation≈2026-01-29 (±1 candle)")
EOF
```

Após gerar o ledger, comparar V4 e V5 com tolerância ±1 candle (Mapa §7.4)
e penetração estrita (Pine linha 278); cruzar resultado contra screenshots
do LuxAlgo gratuito no TradingView (UTC).
