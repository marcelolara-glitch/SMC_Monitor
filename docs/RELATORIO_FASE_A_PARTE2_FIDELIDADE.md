# RELATÓRIO — FASE A / PARTE 2 — Auditoria de Fidelidade (conceito ↔ código ↔ comportamento)

> **Escopo:** confronto entre o canônico ratificado v2.0 e a implementação, dos primitivos às
> 9 assinaturas, conforme `BRIEFING_FABLE5_FASE_A_DIAGNOSTICO.md §5`. Diagnóstico apenas —
> **nenhuma proposta de correção** (pertencem ao Briefing 2). Nenhuma métrica de P&L foi
> computada ou consultada.
>
> **Fontes:** canônico `docs/SMC_PRINCIPIOS_E_LEGADO.md` v2.0 lido do repositório em
> `main @ 88cae16` (2026-07-03); código `smc_freqtrade/smc_engine/` lido verbatim no mesmo
> commit; comportamento medido sobre o **golden 3-TF** (15m/1h/4h, BTC-USDT-SWAP,
> 2026-01-01→04-30; 11.520/2.880/720 candles), com o pipeline MTF replicado via
> `tools/mtf_align.align_informative` (algoritmo do `merge_informative_pair`, concordância
> 1.0000 validada em fase anterior) + `sessions.tag_sessions`.
>
> **Limitação declarada:** os parquets de 2 anos (`user_data/diag_df*.parquet`) não estão no
> repositório (vivem na VM). O nível "comportamento" desta sessão cobre o golden de 4 meses;
> §7 lista as medições a replicar na VM. Os achados centrais são **mecanísticos** (aritmética
> das condições), não amostrais — replicam em qualquer janela.
>
> **Classificação de cada divergência:** `[BUG-FID]` = viola requisito pré-existente (candidato
> a explicar o histórico); `[LACUNA-v2.0]` = requisito introduzido na revisão v2.0 (esperada);
> `[DOC-INT]` = tensão interna do próprio canônico exposta pelo código; `[AMOSTRAL]` =
> característica da janela golden, não do código.

---

## 1. Sumário executivo — a cadeia causal candidata do zero-trades

Dois gargalos medidos, em série, tornam a emissão de sinal **quase impossível por
construção**, independentemente de edge:

**G1 — [BUG-FID → DOC-INT] Armação sem proximidade + escape absoluto = FSM-moedor.**
A armação exige apenas "preço fora da zona" (`_outside`, setup_state.py:480-485), sem limite
de distância — fiel à letra do gatilho §3.2 do canônico ("OB+FVG detectados... preço fora").
A invalidação por escape compara nível absoluto: long invalida se `low > zhigh·1.02`
(setup_state.py:1007-1010) — fiel à letra do §2.5 (">2% além da zona"). A combinação literal
das duas regras produz: setups que já nascem a mais de 2% da zona morrem no candle seguinte.
**Medido no golden (15m, 4 meses):** A1 arma com distância mediana zona↔preço de **7,24%**
(p90 33,4%); A10 6,34%; A3 3,95%. Resultado: `escaped` responde por **97–99% de todas as
invalidações** (A1: 4.162/4.190; A2: 3.082/3.113; A10: 3.101/3.178), **99% dos escaped morrem
com idade ≤ 1 candle**, e a vida mediana de um setup é **1 candle (15 minutos)** em todas as
assinaturas medidas. A FSM vira um moedor arm→die→rearm (A1: 4.191 setups em 4 meses). O §2.5
pressupõe implicitamente que ARMED nasce perto ("escapou **sem voltar**" — espírito do §2.2:
zona é armadilha que se *observa*); o §3.2 não exige proximidade; o código expõe a contradição.
Severidade: **estrutural, sistema-inteiro**. Efeito colateral não-medido: com "um setup ativo
por vez" (setup_state.py:929-940), o churn de setups distantes ocupa o slot global (medição
pendente em execução multi-assinatura, §7).

**G2 — [BUG-FID] A conjunção de confirmação é um evento quase-nulo — o análogo-A3 do
checklist §5.2-4, um nível acima.** A confirmação exige ChoCH internal e vela de rejeição **no
mesmo candle** (`_confirm_choch_rej*`, setup_state.py:643-654). Base medida no golden 15m:
`choch_bull`=169, `rej_bull`=1.135, **co-ocorrência no mesmo candle: 8** (bear: 2) em 11.520
candles — 10 eventos em 4 meses, antes de exigir que ocorram *dentro* de um PENDING da direção
certa em ≤16 candles. Resultado terminal medido: **1 (um) CONFIRMED no universo inteiro**
(9 assinaturas × 4 meses; o único foi da A4a). A mecânica que sufocou a A3 original
(simultaneidade) sobrevive na dupla ChoCH∧rejeição para **todas** as assinaturas em modo
confirmation. O canônico pré-v2.0 prescrevia "ChoCH 15m + vela de rejeição" (§2.2/§3.2) sem
definir a janela; o código leu "+" como mesmo-candle. Fiel à letra; comportamentalmente
quase-nulo. Severidade: **estrutural, sistema-inteiro**. (Nota: o screen de 2 anos rodou em
modo `risk`, que pula a confirmação — G1 permanece; G2 governa o modo confirmation.)

**Demais achados estruturais (detalhe nas tabelas):** invalidação `mitigated` é espúria em
**15/15 casos medidos** (o OB original seguia ativo; a razão real foi a troca da zona
promovida por proximidade — G3); o gate da A5 (`volpct > 0.2`) tem **teto empírico bull =
0,130** na janela (zero candles elegíveis no lado long em 4 meses — G4); a A9 exige OB ativo
que nenhuma versão do conceito pediu (G5); e as lacunas-[v2.0] esperadas confirmadas
(displacement, dealing-range/EQ-cross, OB estratégico, A7-MSS).

**Checklist §5.2 — resposta curta:** (1) direção: **nenhuma inversão encontrada** — semântica
de sweep, IFVG, breaker, OTE e trend conferidas ponta a ponta; (2) viés 4h: sem inversão, NA
neutro correto, atraso = merge padrão já validado; (3) filtros: dois casos de filtro-extra/
inatingível (G4, G5); premium/discount não é gate em nenhuma assinatura (lacuna-[v2.0]);
(4) janelas: G1 e G2 são exatamente os "análogos da A3" que o item manda procurar;
(5) coerência: 4/689 OBs do ledger 15m com `bar_high ≤ bar_low` (contidos — não vazam para as
zonas consumidas pela FSM).

---

## 2. Tabela de fidelidade — PRIMITIVOS

| Primitivo | Conceito (canônico v2.0) | Código (verbatim) | Comportamento (golden) | Divergência / severidade |
|---|---|---|---|---|
| Pivots / estrutura | §2.1 pré-existente: body break confirmado; internal/swing 2 camadas | `structure.py` consome níveis da Onda 3; trend neutro Pine `bias=0` → `pd.NA` (structure.py:196-200) | Eventos em ordem de grandeza plausível por TF (15m: 273 BOS-int, 337 ChoCH-int, 42 ChoCH-swing; 4h: 21 BOS-int, 13 ChoCH-int); bias 4h com 1 flip na janela `[AMOSTRAL]` | Sem divergência. Body-close ✓ |
| Displacement (§2.6 [v2.0]) | MSS de confirmação e OB estratégico só valem com deslocamento | **Inexistente** — nenhuma referência em `structure.py`/`order_blocks.py`/`setup_state.py` (fórmula segue reservada em HOOKS §10.5) | Confirmação usa ChoCH puro (G2 agrava) | `[LACUNA-v2.0]` **estrutural** — afeta confirmação de todas e o OB estratégico |
| OB primitivo | §2.10: LuxAlgo extreme-in-window é a referência de match (política MAPA §7.9 preservada) | `order_blocks.py:152-188` — `parsed_high/low` com flip em barra de alta volatilidade (Pine verbatim :186-187) | Ledgers: 4h 39 OBs, 1h 179, 15m 689; estados coerentes com §12.1 HOOKS. **Incoerência: 4/689 OBs 15m com `bar_high ≤ bar_low`** (todos `internal`; 3 breaker_broken + 1 active); zonas promovidas swing e breaker: **0 candles** com top≤bottom em qualquer TF | `[BUG-FID]` de coerência **contida**: cosmética para a FSM atual (que só consome swing/breaker promovidos), estrutural-latente para consumidores de internal. Causa provável: flip parsed (:186-187); investigação pertence ao Briefing 2 |
| OB estratégico (§2.10 [v2.0]) | Última vela oposta + displacement + liquidez tomada; cada assinatura declara a semântica | **Inexistente** — todas as assinaturas consomem o primitivo LuxAlgo promovido (`active_*_swing_ob_*_1h`) | — | `[LACUNA-v2.0]` estrutural conceitual |
| FVG | 3 velas; mediana 50%; mitigação conforme §7.10-1 MAPA | `fvg.py` (normalização `top>bottom`, gap por displacement `low < high[2]`) | `top>bottom` em **100%** dos 3 ledgers; larguras > 0 (min 0,40 no 1h); contagens plausíveis (15m: 908; 875 mitigadas) | Sem divergência primitiva. Nuance estratégica ("qual FVG" — o do impulso) tratada na A7 |
| IFVG / Breaker | Papel invertido (PAC); breaker = OB falhado, estados §12.1 | Promoção via `zone_projection` (grupos ifvg/breaker) | Zonas promovidas coerentes (0 invertidas); 1h: 139 breaker_broken / 31 active / 9 mitigated | Sem divergência |
| Sweep | §2.3 núcleo: fura e fecha de volta; wick + outbreak&retest (Conflito C) | `liquidity_sweep.py` — tabela direcional do docstring (:20-33): low furado + close acima = **bullish** ✓ | 15m: 476/453 bull wick/retest, 493/468 bear — simetria sã; direção sem inversão | Sem divergência no núcleo. Parâmetros (janela 16 etc.) = §2.11 engenharia declarada ✓ |
| EQH/EQL | Subconjunto declarado (§2.12 [v2.0]) | Wave 8.1/8.2 | 4h: **0 alerts** (warmup ATR200 — divergência esperada já documentada); 1h: 18/19; 15m: 80/63 | Sem divergência (`[AMOSTRAL]` no 4h, documentado) |
| P/D + OTE (§2.7 [v2.0]) | Dealing range do impulso; EQ-cross obrigatório; OTE 62-79 com confluência | `fib_ote.py`: perna = **trailing range no candle do MSS** (docstring :20-27, simplificação declarada com cláusula de parada DTFX); banda bull `high−0.79·span … high−0.62·span` (:140-145) — **sem inversão** ✓; EQ-cross e confluência: inexistentes | OTE quase-permanente: bull ativa em 6.993/11.520 candles (61%), bear 9.793 (85%) — zona-papel-de-parede, coerente com a LIMITAÇÃO do próprio módulo | `[LACUNA-v2.0]` **estrutural** (ancorador + EQ-cross + confluência); fórmula da banda fiel ao hook §10.3 |
| Tempo / killzones (§2.8 [v2.0]) | 3 janelas NY com DST; transversal com sensibilidade por assinatura | `sessions.py` — `zoneinfo("America/New_York")` (DST automático), `[ini,fim)` sobre o próprio timestamp, tz-naive=UTC por contrato (:58-111) | 480 candles por janela no 15m (4/dia × 120 dias) ✓ | Sem divergência no hook. Transversalidade (campo por assinatura): `[LACUNA-v2.0]` — só a A7 consome |

---

## 3. Tabela de fidelidade — ASSINATURAS

Comportamento no golden (modo `confirmation`, uma assinatura por execução): formato
`setups únicos / CONFIRMED / razões dominantes / direções`.

| A# | Conceito (Parte 9 v2.0) | Código | Comportamento (golden 15m, 4 meses) | Divergências específicas |
|---|---|---|---|---|
| **A1** | Fam. I; OB + viés 4H → retest → MSS c/ displacement | `_arm_A1` (:513-517), dir=trend (:353), confirm ChoCH∧rej (:650-654) | 4.191 / **0** / escaped 4.162 (99% idade≤1; dist mediana armação **7,24%**, p90 33%) / 2.454L-1.737S | G1+G2 dominam. Displacement ausente `[LACUNA-v2.0]`. Semântica de OB = primitivo (ponte §2.10 pendente) |
| **A2** | Fam. I+catalisador; sweep → retest OB → confirmação | `_arm_A2` (:525-531), confirm tripla c/ sweep janelado (:643-647) | 3.113 / **0** / escaped 3.082; mitigated 5/5 espúrios / 1.856L-1.257S | G1+G2. Sweep-direção coerente ✓ |
| **A3** | Fam. I A+; OB+FVG adjacentes + sweep → confirmação §2.11 | `_arm_A3` via adjacência (:488-510); confirm tripla (:643-647) — o fix histórico janelou **só** o sweep (rolling 16, :820-821); ChoCH∧rej seguem mesmo-candle | 484 / **0** / escaped 473 (98% idade≤1; dist 3,95%) / 406L-78S | **G2 é o herdeiro direto do bug A3 original**: a simultaneidade migrou da tripla para a dupla. G1 também. Adjacência OB↔FVG ✓ fiel |
| **A4a** | Fam. I; IFVG retest; direção do papel invertido; inversão válida c/ displacement | dir `_direction_from_ifvg` (:400-402, **sem gate 4H, documentado**), `_arm_A4a` (:546-550), confirm dupla | 2.392 / **1** (o único do universo) / escaped 2.164, timeout 150 / 1.341S-1.051L | Direção do papel ✓. Sem gate de viés: `[DOC-INT]` — §2.4 pré-existente universaliza o gate 4H; Parte 9 [v2.0] omite para reversões; código segue a Parte 9. Displacement na inversão `[LACUNA-v2.0]` |
| **A5** | Fam. I tap; **modo Risk Entry**; zona de qualidade (volumetric) | `_arm_A5` c/ `volpct > 0.2` (:534-543); `entry_mode_preferido` é **documental** (:336: "o efetivo vem do SetupConfig") — em execução global `confirmation` a A5 exige ChoCH∧rej, contradizendo o próprio conceito de tap | 118 / **0** / escaped 114 / **118S-0L**. Causa medida: teto empírico `volpct` bull = **0,130** (p90 0,127) vs limiar 0,2; bear max 0,242 → 368 candles elegíveis | **G4 `[BUG-FID]` categoria §5.2-4**: limiar acima do teto de um lado inteiro (na janela). Modo-por-assinatura não aplicado: decisão declarada, mas em multi-assinatura global produz A5 anti-conceito `[DOC-INT]` |
| **A6** | Fronteira I/II; breaker+FVG sobrepostos; direção do breaker | `_arm_A6`/`_zone_A6` (:520-522, :466-475 — âncora dupla breaker+fvg ✓), dir do breaker sem gate 4H (:405-411) | 17 / **0** / timeout 10, escaped 5 / **17S-0L** — assimetria amostral: breaker bull ativo em 24 candles vs bear 440 `[AMOSTRAL]` | Composição fiel. Mesmo `[DOC-INT]` do gate 4H das reversões |
| **A7** | Fam. II; janela → sweep → **MSS c/ displacement** → **primeiro FVG do impulso** → retest; direção reversão-do-sweep alinhada ao viés | `_arm_A7` (:574-596): FVG(dir) **qualquer ativo 1h** + sweep recente(dir) + killzone + fora; dir = **trend** (:353); confirm tripla c/ sweep de novo (paridade A3, :696-699); killzone só na armação (D2 documentado) | 281 / **0** / escaped 189 (79% idade≤1; dist 2,48%), timeout 62 / 165L-116S | Variante minoritária implementada: **sem MSS pós-sweep, sem vínculo FVG↔impulso, FVG do 1h e não do LTF** — tudo `[LACUNA-v2.0]` esperada (formulação antiga do catálogo). Confirmação por §2.11 em vez de retest simples: composição extra não pedida pela Parte 9 `[DOC-INT leve]`. Killzones/fuso ✓ |
| **A9** | Fam. II; sweep EQH/EQL → ChoCH c/ displacement → entrada | dir do sweep (:414-436 ✓ reversão coerente); **arma via `_arm_A2`** (:684-687) → **exige OB swing ativo da direção** | 3.541 / **0** / escaped 3.501; mitigated 6/6 espúrios / 2.020S-1.521L | **G5 `[BUG-FID]`**: gate de OB sem proveniência em nenhuma versão do conceito (checklist §5.2-3, caso inverso — filtro inventado). Além disso o sweep consumido é de pivots internal/equal do módulo, não especificamente EQH/EQL `[DOC-INT leve]`. Displacement `[LACUNA-v2.0]` |
| **A10** | Fam. II; dealing range do impulso; EQ-cross; 62-79 c/ confluência OB/FVG + confirmação; SL além do 100% | `_zone_A10`/`_arm_A10` (:599-638): zona = OTE trailing-based do hook; **sem EQ-cross, sem confluência**; dir=trend, sem inversão ✓ (D3 conferido nas fórmulas fib_ote.py:140-145) | 3.179 / **0** / escaped 3.101 (99% idade≤1; dist 6,34%, p90 31%) / 1.700L-1.479S; zona ativa 61-85% dos candles | Ancorador + EQ-cross + confluência: `[LACUNA-v2.0]` estruturais. G1 devastador aqui (zona-papel-de-parede + armação sem proximidade) |

---

## 4. Achados transversais numerados

- **G1 — Escape-como-executor** `[BUG-FID→DOC-INT]` estrutural. Armação sem proximidade
  (§3.2 literal) + escape absoluto 2% (§2.5 literal) ⇒ 97-99% das invalidações, vida mediana
  1 candle, distâncias medianas de armação 2,5-7,2% (p90 até 33%). O par de regras do próprio
  canônico é internamente inconsistente; o código o executa fielmente.
- **G2 — Conjunção ChoCH∧rejeição mesmo-candle** `[BUG-FID]` estrutural. 10 co-ocorrências em
  11.520 candles; 1 CONFIRMED no universo. Herdeiro direto do padrão A3; hoje coberto pela
  reclassificação §2.11 [v2.0] como escolha de engenharia — o achado é que a escolha, medida,
  é quase-nula.
- **G3 — `mitigated` espúrio** `[BUG-FID]` estrutural em mecanismo, pequeno em volume atual.
  15/15 casos medidos (A1 3/3, A2 5/5, A3 1/1, A9 6/6): o OB capturado seguia ativo no ledger
  1h; a âncora trocou porque `_project_group` promove a zona ativa **mais próxima do close**
  (zone_projection.py:130-180) e a FSM lê troca de id como mitigação (setup_state.py:985-994).
  Rótulo de razão errado; invalidação sem causa conceitual. Volume hoje mascarado por G1.
- **G4 — Limiar A5 acima do teto empírico bull** `[BUG-FID §5.2-4]` estrutural (na janela;
  verificar teto em 2 anos — §7). 0 candles bull elegíveis; 368 bear.
- **G5 — Gate de OB na A9 sem proveniência** `[BUG-FID §5.2-3-inverso]` estrutural.
- **G6 — Reversões sem gate 4H** `[DOC-INT]`: §2.4 pré-existente (universal) vs Parte 9 v2.0
  (omite para A4a/A6/A9) vs código (segue a Parte 9, docstrings explícitas :363-421). Resolver
  no doc antes de tratar como bug.
- **G7 — 4/689 OBs invertidos no ledger 15m** `[BUG-FID]` de coerência, contido (não vaza
  para zonas consumidas). Causa provável order_blocks.py:186-187.
- **G8 — Lacunas-[v2.0] confirmadas** (displacement §2.6; dealing-range/EQ-cross/confluência
  §2.7; OB estratégico §2.10; A7-MSS/FVG-do-impulso; tempo transversal §2.8): todas presentes
  como previsto pela convenção [v2.0] — nenhuma é bug histórico.

## 5. Checklist §5.2 — fechamento formal

1. **Direção:** sem inversões (sweep :20-33 ✓; IFVG/breaker espelham papel ✓; OTE D3 conferido
   nas fórmulas ✓; trend ±1 ✓). Assimetrias 100%-short (A5/A6) explicadas por G4 e
   `[AMOSTRAL]`, não por inversão.
2. **Viés MTF 4h:** `swing_trend_bias` semântica correta (NA neutro, structure.py:196-200);
   sem inversão; atraso = comportamento padrão do merge @informative (validado 1.0000);
   1 flip na janela `[AMOSTRAL]` — invalidação por trend quase inerte no golden (1 caso, A2).
3. **Filtros:** P/D não é gate em nenhuma assinatura (`[LACUNA-v2.0]` — pré-v2.0 o PRINCIPIOS
   não o exigia); filtro extra na A9 (G5); limiar inatingível na A5-bull (G4).
4. **Janelas/timeouts:** G1 e G2 são os análogos-A3 procurados. Timeouts numéricos conferem
   com §2.11 (24 ARMED / 16 PENDING / sweep 16), setup_state.py:137-143.
5. **Coerência interna:** FVG 100% `top>bottom` nos 3 TFs; OB 4/689 invertidos (G7); pivots e
   contagens em ordem de grandeza plausível; killzones 480/480/480 ✓.

## 6. O que o golden NÃO cobre (honestidade amostral)

Uma janela de 4 meses, um par, um regime (1 flip de trend 4h; 2.383 candles de warmup NA;
breaker bull raro; EQH/EQL 4h zerados por warmup). Os graus das assimetrias (A5/A6, 100%
short) e o papel do trend-invalidation são amostrais. **G1, G2, G3 e G5 não são**: decorrem
da forma das condições e replicam em qualquer janela.

## 7. Medições pendentes na VM (parquets de 2 anos — sem correção, só contadores)

Replicar sobre `diag_df.parquet` (BTC) e `diag_df_eth.parquet` (ETH), por assinatura:
CONFIRMED únicos; distribuição de `setup_invalidation_reason`; idade em candles por setup;
distância zona↔close na armação (mediana/p90); co-ocorrência `choch_internal_* ∧ rejeição`
por 10k candles; quantis de `active_{bull,bear}_swing_ob_volume_pct_1h` (teto bull em 2 anos
vs 0,2); fração de `mitigated` com OB capturado ainda ativo no ledger; e, em execução
multi-assinatura, quantos candles o slot único está ocupado por setup que morre em ≤1 candle
(efeito-máscara de G1 sobre a prioridade D3).

## 8. Registro de disciplina

Nenhuma correção é proposta neste documento (briefing §5.3/§6). Nenhum valor de P&L,
expectancy, win rate ou retorno foi computado. Todas as afirmações de código citam
`arquivo:linha` em `main @ 88cae16`; todas as medições são estruturais e reproduzíveis
(pipeline descrito no cabeçalho).

**Fim do relatório. Interpretação, priorização e correções pertencem ao Briefing 2, sob gate
out-of-sample.**
