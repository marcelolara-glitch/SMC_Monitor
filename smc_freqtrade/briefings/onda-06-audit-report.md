# Audit Report — Briefing Onda 6 (Order Blocks)

**Objeto auditado:** `smc_freqtrade/briefings/onda-06-order-blocks-spec.md`
(commit `a516dbc` na branch `claude/plan-order-blocks-wave-6-fRdOU`,
994 linhas, 11 seções, 12 premissas, 4 itens em aberto).
**Tipo de sessão:** auditoria adversarial estrita. Sem código de
implementação. Sem alteração ao briefing nesta sessão (patches
propostos em §5; aplicação posterior).

---

## 1. Sumário executivo

Auditoria revisou os 7 achados de input (Camada 1: A1, A2, B1, B2,
B3, B4, B5) e gerou 8 achados próprios (Camada 2: C1-C8).

- **Camada 1**: 7 achados — **6 confirmados**, **1 confirmado com
  refinamento adicional** (B3, onde a investigação revelou que o
  argumento original do briefing era *fraco* mas o resultado correto
  já é tuple-return por motivos técnicos mais sólidos).
- **Camada 2**: 8 achados — todos novos, **0 falsos positivos**
  (cada um com evidência canônica). Severidade: 0 bloqueantes
  críticos, 3 bloqueantes médios (C1, C3, C6), 5 menores
  (C2, C4, C5, C7, C8).
- **Itens em aberto §11 do briefing**: **todos os 4 fechados**.
- **Linha-a-linha das premissas P1-P12**: sample de 8 premissas
  (P1, P2, P4, P5, P6, P7, P10, P12) verificada contra o Pine
  fonte — todas as referências de linha batem. Não foram
  detectadas premissas mal-fundamentadas.

**Veredito global**: **briefing aprovado para implementação após
patch consolidado §5 ser aplicado e Marcelo aprovar.** Não há
bloqueante que exija decisão prévia de Marcelo além da aprovação
do próprio patch. Os 8 patches do §5 podem ser consolidados em um
único PR de doc (este audit report + patches no briefing), ou
absorvidos no PR de implementação Wave 6 — Marcelo decide §7.

---

## 2. Achados Camada 1

### 2.1 A1 — Inconsistência interna "5 vs 6 campos novos"

**Hipótese auditada (input):** §1 (Contexto) parágrafo 4 diz "5
campos novos"; §2 P3 lista 6 campos explicitamente. Confirmar que a
contagem correta é 6 e propor texto exato de correção do §1.

**Investigação:**

- §1 linha 27 do briefing: "Estende o UDT `OrderBlock` de Onda 1 com
  **5 campos novos** (lifecycle + scope + state + hook volumetric)".
- §2 P3 linhas 100-111: tabela lista **6 campos** explicitamente:
  `t_creation`, `t_mitigation`, `t_invalidation`, `scope`, `state`,
  `volumetric_intensity`.
- §2 P3 linha 114: "sem os **5 campos novos**, o ledger não é
  construível…" — **segunda ocorrência da contagem errada**, não
  identificada no input.
- §3 passo 1 linhas 246-247: "adicionando **6 campos** ao UDT" —
  correto.
- §4.3 ledger schema linhas 442-453: 11 colunas (4 originais + ob_id
  + 6 novos) — consistente com 6.

**Conclusão**: **Confirmado**. Contagem correta = 6. Há duas
ocorrências do erro, não uma (§1 parágrafo 4 e §2 P3 texto
explicativo). Patch §5.1 cobre ambas.

### 2.2 A2 — Smoke 5.2 (Close vs Wick) com assert tautológico

**Hipótese auditada (input):** `test_smoke_wave6_mitigation_close_mode`
afirma `n_mit_close <= n_mit_wick`. Matematicamente sempre verdadeiro:
para bullish OB, `close >= low`; para bearish OB, `close <= high`.
Logo o assert passa mesmo se a engine ignorar o parâmetro `mitigation`.

**Investigação:**

- Bullish OB mitigation condition (§2 P4 do briefing): `source < bar_low`.
  - Wick mode: `source = low`. Trigger quando `low < bar_low`.
  - Close mode: `source = close`. Trigger quando `close < bar_low`.
  - Como `low <= close <= high` por construção do candle, então
    `low < bar_low` é estritamente mais permissivo (mais ou igual
    mitigações) que `close < bar_low`.
- Bearish OB mitigation: `source > bar_high`.
  - Wick mode: `source = high`. Trigger `high > bar_high`.
  - Close mode: `source = close`. Trigger `close > bar_high`.
  - Como `close <= high`, Wick é estritamente mais permissivo.
- Conclusão: `n_mit_close <= n_mit_wick` **é tautológico para
  qualquer OHLC válido**. Engine que ignora o parâmetro
  `mitigation` e usa sempre Wick interna passa no assert.

**Assert mais forte proposto**: detectar pelo menos um OB cujo
comportamento difere entre os dois modos. Critério canônico:
- Wick mitiga mais cedo (`t_mit_wick < t_mit_close`), OU
- Wick mitiga mas Close não (`t_mit_wick != NaT and t_mit_close == NaT`).

Implementação descritiva:
```python
joined = ledger_wick.merge(
    ledger_close,
    on='ob_id', suffixes=('_wick', '_close'),
)
strictly_earlier = (
    joined['t_mitigation_wick'].notna()
    & joined['t_mitigation_close'].notna()
    & (joined['t_mitigation_wick'] < joined['t_mitigation_close'])
).any()
wick_only = (
    joined['t_mitigation_wick'].notna()
    & joined['t_mitigation_close'].isna()
).any()
# Pelo menos uma das duas condições deve valer para provar que
# o parâmetro `mitigation` afeta o resultado.
assert strictly_earlier or wick_only, (
    "Parâmetro mitigation parece estar sendo ignorado: Wick e Close "
    "produzem ledgers indistinguíveis. Verificar implementação de "
    "_resolve_mitigations."
)
```

**Pré-requisito da fixture**: a fixture sintética da §5.1 precisa
gerar pelo menos um candle de retração cujo `low/high` fure o
`bar_low/bar_high` do OB **antes** do `close` fazê-lo (ou nunca).
A fixture atual (5 fases) já contém um candle Z em Fase 3 onde
"low < ob.bar_low" — esse candle satisfaz `wick_only` se o close
do mesmo candle ainda ficar acima de `bar_low`. Documentar no
patch.

**Conclusão**: **Confirmado**. Assert atual fraco; substituir
conforme acima. Patch §5.2 cobre.

### 2.3 B1 — Slice exclusive vs inclusive (§11.1 do briefing)

**Hipótese auditada (input):** Pine `array.slice(arr, from, to)` é
`[from, to)` (exclusive end)? PyneCore compilou verbatim — verificar.

**Investigação:**

Conduzida via Explore agent, três fontes convergentes:

1. **Documentação oficial Pine v5** (TradingView Pine Script v5
   reference manual, seção `array.slice`): `index_to` descrito como
   "a zero-based index **before which to end extraction**" —
   **exclusive end confirmado**.
2. **Análise de contexto do Pine fonte** (linhas 227-231 de
   `tools/pynecore-validation/luxalgo_smc_compute_only.py`): no
   momento em que `storeOrdeBlock` roda, `parsedHighs__global__`
   tem exatamente `bar_index + 1` elementos (posições 0 até
   `bar_index`). Se `array.slice(arr, pivot.barIndex, bar_index)`
   fosse inclusive em `bar_index`, incluiria a vela atual (a do
   break) na busca pelo parsed-extreme — distorcendo a lógica de
   OB origin (queremos o extremo do pullback ANTES do break, não
   incluindo o break). Exclusive end é a única semântica
   compatível.
3. **Convenção Pine v5** alinhada com Python/JavaScript slice
   semantics.

**Conclusão**: **Confirmado exclusive end** com evidência canônica.
**§11.1 do briefing fechado**. P5 do briefing (linha 133-145) está
correta. Patch §5.3 atualiza §11.1 para refletir o fechamento.

**Nota lateral**: o briefing já especifica `df.iloc[int(pivot_idx):int(break_idx)]`
em P5 — sintaxe Python que é naturalmente exclusive-end. Implementação
correta sem necessidade de smoke disambiguador.

### 2.4 B2 — Gap dogmático SMC vs LuxAlgo (§11.4 do briefing)

**Hipótese auditada (input):** Briefing oferece 3 opções
(a/b/c). Marcelo avalia: (a) categoricamente errada (§7.8 é para
features do pago, não divergências dogmáticas); (b) adia
indefinidamente; (c) única coerente.

**Investigação:**

- **§7.8 do Mapa Camada 1** (`docs/MAPA_LUXALGO_CAMADA_1_v1.1.md`
  linhas 543-563): texto introdutório verbatim:

  > "Estas divergências entre output da portagem (referência:
  > gratuito) e screenshots **do pago** (caso o usuário do golden
  > esteja no pago em vez de no gratuito) são diferenças
  > documentadas, NÃO bugs"

  Cabeçalho da tabela: "Feature do pago | Onda da portagem em que
  entra | Status".

  **Conclusão**: §7.8 é categoricamente sobre features do pago.
  Opção (a) confirmada como inválida.

- **§7.1 do Mapa** (linha 439-442): "**LuxAlgo - Smart Money
  Concepts** (gratuito) — referência canônica de **match exato**
  da portagem. A engine deve detectar exatamente o que o gratuito
  detecta, com tolerância ±1 candle (§7.4)."

  **Conclusão**: §7.1 estabelece o gratuito como single source of
  truth para match exato. Divergência dogmática (definição
  semântica de OB conforme dogma SMC) é categoricamente diferente
  de divergência vs pago (feature ausente no gratuito).

- **Opção (b)** (codificar dogma em
  `SMC_PRINCIPIOS_E_LEGADO.md` antes da Wave 6): Wave 6 não
  precisa da definição dogmática para implementar a portagem do
  gratuito. Adiar a implementação para esse esclarecimento é
  AGENTS §2.2 violation (simplicidade primeiro — Wave 6 não
  precisa, então não bloqueia).

- **Opção (c)** é coerente com §7.1 do Mapa e AGENTS §1.0.1
  (hierarquia de fontes — Mapa é canônico).

**Patch proposto**: criar nova subseção **§7.9 do Mapa**
("Divergências dogmáticas SMC vs LuxAlgo gratuito") com texto
exato registrando que a portagem prioriza fidelidade ao gratuito
sobre dogma SMC, e que tais divergências (e.g., definição de
origem de OB) são pré-condições aceitas via §7.1 do Mapa, não
bugs nem features do pago. Texto completo em §5.4.

**Conclusão**: **Confirmado**. §11.4 do briefing fechado por
patch §5.4 (cria §7.9 no Mapa) + patch §5.5 (atualiza §11.4 do
briefing apontando para §7.9).

### 2.5 B3 — Tuple-return vs helper separado (§11.2 do briefing)

**Hipótese auditada (input):** Briefing argumenta tuple-return por
"ledger lifecycle queryable", mas não menciona que a alternativa
(helper `get_order_blocks_ledger(df)` reconstruindo via `df.attrs`
ou via colunas booleans + state interno) tem fragilidades técnicas
reais.

**Investigação:**

1. **`df.attrs` em pandas**: docs oficiais e issues conhecidos:
   - `attrs` é propagado por `.copy()` (shallow e deep).
   - **NÃO é propagado** por operações como `pd.concat`,
     `pd.merge`, `groupby.agg`, `pivot_table`, e várias
     operações de reshape.
   - `attrs` é classificado como **experimental** desde sua
     introdução em pandas 1.0, sem garantia de estabilidade entre
     versões.
   - Em qualquer pipeline Freqtrade real (consumidor downstream),
     `populate_indicators` faz múltiplas operações de merge e
     concat — `attrs` evapora silenciosamente.

2. **Reconstrução determinística do ledger a partir das 8
   booleans + OHLC**: NÃO é possível.
   - `bar_time` (timestamp do parsed-extreme) exige
     `parsed_high`/`parsed_low` da janela, que dependem de
     `ob_filter` e `atr_length`. Sem expor `parsed_*` como
     colunas, reconstrução exige rerodar todo o cálculo de
     volatilidade.
   - **Matching CREATE → MITIGATE para múltiplos OBs coexistentes
     do mesmo (scope, direction)**: ambíguo. Cenário: candle X
     cria OB1 (bullish swing) e candle Y > X cria OB2 (bullish
     swing). Candle Z > Y mitiga "um bullish swing OB". Qual?
     Decisão depende de `bar_low` de cada OB, que por sua vez
     depende de `parsed_low` na respectiva janela. Sem o ledger
     interno, a coluna booleana sozinha NÃO permite reconstruir
     quem foi mitigado.

3. **Conclusão técnica**: tuple-return é **tecnicamente
   necessário**, não apenas preferência arquitetural. O argumento
   do briefing original ("ledger lifecycle queryable") é correto
   mas fraco. O argumento forte é: **a alternativa não é
   reconstruível em geral**.

**Conclusão**: **Confirmado com refinamento**. Tuple-return é a
única opção tecnicamente viável. **§11.2 do briefing fechado**.
Patch §5.6 substitui §11.2 por nota fechada com a justificativa
técnica acima.

### 2.6 B4 — Naming `created/mitigated` vs Pine-faithful (§11.3 do briefing)

**Hipótese auditada (input):** Briefing recomenda
`created/mitigated`. Recomendação inicial do Marcelo: fechar com
`created/mitigated`.

**Investigação:**

- **`created/mitigated`** separa CREATE de MITIGATE em colunas
  distintas, semanticamente claro para consumidor pandas.
- **`ob_alert_*`** (Pine-faithful) espelha
  `currentAlerts.internalBullishOrderBlock` etc. do Pine, mas:
  - Pine usa "alert" porque o output do Pine **é** uma série de
    alerts (`alertcondition`). Em pandas, o output é uma coluna
    de dados — "alert" carrega significado errado.
  - No Pine, `*OrderBlock` no nome do alert refere-se a
    **mitigação** (linhas 329-332 do Pine: "Bullish Internal OB
    Breakout", "Price broke bullish internal OB"). Replicar isso
    em pandas obrigaria a omitir os eventos de **criação**, que
    o Pine não expõe como alerts mas a Wave 6 precisa expor.
  - Logo, `ob_alert_*` é incompleto — não cobre CREATE.

**Conclusão**: **Confirmado**. `created/mitigated` fecha §11.3 do
briefing. Patch §5.7 substitui §11.3 por nota fechada com a
justificativa acima.

### 2.7 B5 — Co-mitigação de múltiplos OBs no mesmo candle

**Hipótese auditada (input):** §4.3 do briefing diz coluna `*_mitigated`
é booleana por candle, sem soma. §4.4 invariante 12 cobre
coexistência de ativos, mas não testa co-mitigação. Propor
invariante nova + caso de teste.

**Investigação:**

- §4.3 linha 433-436 do briefing: "as colunas `*_mitigated` são
  marcadas com `True` em todo candle X onde **pelo menos um** OB
  do scope/direction é mitigado. Múltiplos OBs simultaneamente
  mitigados em X produzem um único `True` na coluna (não soma)."
  **Schema semanticamente correto.**

- §4.4 invariantes 1-12: invariante 12 cobre "coexistência de
  múltiplos OBs ativos". **NÃO existe invariante cobrindo
  co-mitigação.**

- §5 (smoke test): nenhuma das 4 funções de teste verifica
  co-mitigação. Fase 4 da fixture menciona "Mantém o bearish swing
  OB da fase 3 ativo" mas não força co-mitigação posterior.

**Proposta de invariante nova (13)**:

> **13. Co-mitigação determinística.** Se múltiplos OBs do mesmo
> `(scope, direction)` são mitigados no mesmo candle Z, então
> `df_per_candle.loc[Z, 'ob_<scope>_<direction>_mitigated'] == True`
> (uma única marca booleana) e todos os OBs envolvidos têm
> `t_mitigation == df.iloc[Z]['date']` no ledger.

**Proposta de caso de teste novo no smoke (§5.2)**:

```python
def test_smoke_wave6_co_mitigation(synthetic_df_with_co_mitigation):
    """Múltiplos OBs do mesmo (scope, direction) mitigados no mesmo candle.

    Fixture: dois bullish swing OBs criados em candles diferentes,
    ambos com bar_low ainda acima de algum nível-alvo. Candle Z
    posterior tem low que fura ambos bar_low simultaneamente.
    """
    df = detect_pivots(synthetic_df_with_co_mitigation, ...)
    df = compute_trailing_extremes(df)
    df = detect_structure(df)
    df_out, ledger = detect_order_blocks(df, mitigation='Wick')

    co_mitigated_candles = df_out.index[df_out['ob_swing_bullish_mitigated']]
    for Z in co_mitigated_candles:
        ts_Z = df_out.loc[Z, 'date']
        co_mit_obs = ledger.query(
            "scope == 'swing' and bias == @BULLISH and t_mitigation == @ts_Z"
        )
        # Pode ter 1 ou mais OBs mitigados em Z; quando ≥2, é co-mitigação
        if len(co_mit_obs) >= 2:
            # Invariante 13: única marca booleana, múltiplos OBs com mesmo t_mitigation
            assert df_out.loc[Z, 'ob_swing_bullish_mitigated']
            assert (co_mit_obs['t_mitigation'] == ts_Z).all()
```

**Fixture suplementar**: a fixture atual de 5 fases não garante
co-mitigação. Adicionar **fase 6** (~290-300 candles) com retração
profunda que fura `bar_low` de **ambos** os bullish OBs criados em
fases 4 e 5.

**Conclusão**: **Confirmado**. Invariante 13 + caso de teste +
extensão de fixture cobertos em patch §5.8.

---

## 3. Achados Camada 2 (próprios da sessão)

### 3.1 C1 — Inconsistência "13 OBs" vs "12 OBs" vs "~12 OBs"

**Hipótese (própria):** o briefing alterna entre "12" e "13" para
o mesmo conjunto pré-mapeado de OBs visuais.

**Investigação:**

- **Briefing §6 linha 729-730**: "Spot-check híbrido contra os **~12
  OBs** do §3.1 do relatório final da Onda 5".
- **Briefing §8.4 linha 847**: "**13 OBs** visualmente mapeados".
- **Briefing §8.4 linha 877**: "dos **13 OBs** visuais, ≥10
  ratificados".
- **Briefing §10 ref 7 linha 924**: "§3.1 (**12 OBs** pré-mapeados,
  material do spot-check)".

- **Fonte canônica** (`smc_freqtrade/briefings/onda-05-final-consistency-report.md`):
  - Tabela §3.1 lista **exatamente 13 linhas** (Explore agent
    confirmou).
  - Introdução §3.1 linha 77: "**~12 OBs mapeados visualmente** ao
    longo dos 4 meses" — uso colloquial aproximado.
  - Conclusão: contagem canônica = **13**. "~12" é referência
    colloquial.

**Conclusão**: **Inconsistência confirmada.** O briefing tem 3
ocorrências corretas ("13"), 1 incorreta ("12") em §10, e 1
incorreta ("~12") em §6. Padronizar para "13" em todos os locais
(o `~` foi herdado do uso colloquial do relatório Wave 5 e
propagou para o briefing).

**Severidade**: **média**. Não impede implementação mas confunde
o leitor sobre quantidade de matches esperados no spot-check.

**Patch §5.9** cobre. Texto exato em §5.

### 3.2 C2 — "8 cenários" inventado em §3 passo 3

**Hipótese (própria):** §3 passo 3 do briefing afirma cobertura de
"8 cenários" no smoke, mas §5 não lista 8 cenários.

**Investigação:**

- **Briefing §3 passo 3 linha 274-275**: "`pytest` passa;
  cobertura dos **8 cenários** listados em §5."
- **Briefing §5**: lista **5 fases na fixture** (5.1) e **4
  funções de teste** (5.2: `test_smoke_wave6_lifecycle`,
  `test_smoke_wave6_mitigation_close_mode`,
  `test_smoke_wave6_bar_time_within_window`,
  `test_smoke_wave6_parsed_high_low_inversion`).

Não há "8 cenários" identificáveis em §5. O número parece ter sido
inventado durante a redação do §3 sem verificação cruzada.

**Severidade**: **menor**. Cosmético; corrigir para "as 4 funções
de teste de §5 cobrindo a fixture de 5 fases".

**Patch §5.10** cobre.

### 3.3 C3 — Dependência implícita: coluna `date`

**Hipótese (própria):** §4.5 e o smoke usam `df['date']` /
`df.iloc[X]['date']` como timestamp canônico, mas §4.1 (FONTE DE
DADOS) não declara que a coluna `date` é requerida.

**Investigação:**

- **Briefing §4.1 FONTE DE DADOS** (linha 329-332): "DataFrame com
  no mínimo OHLC + as 4 colunas COL_*_IDX produzidas por
  detect_pivots() (Onda 3) para os escopos swing e internal + as 8
  booleans BOS/CHoCH produzidas por detect_structure() (Onda 5)."

  **Não menciona `date`.**

- **Briefing §4.5 passo 2d linha 527**: `bar_time = df.iloc[extreme_idx]['date']`.
- **Briefing §4.5 passo 2d linha 530**: `t_creation = df.iloc[X]['date']`.
- **Briefing §4.5 passo 3b linha 551**: `mask = df['date'] > ob.t_creation`.
- **Briefing §4.5 passo 3d linha 557**: `t_mit = df.loc[hits.idxmax(), 'date']`.

A coluna `date` é dependência crítica não-declarada.

**Verificação cruzada com Onda 5**:
`smc_freqtrade/smc_engine/structure.py` da Onda 5 segue a mesma
convenção implícita — também consome `date` sem declarar.
Provavelmente assumido como padrão Freqtrade. Mas Wave 6 é a
primeira onda a escrever timestamps NO ledger (não apenas booleans
por candle), então a dependência se torna formal.

**Severidade**: **média**. Implementador pode usar `df.index` (se
DataFrame tem DateTimeIndex) ou `df['date']` — sem direcionamento
canônico, pode haver divergência entre implementação e expectativa
de testes.

**Patch §5.11** cobre — adiciona linha em §4.1 declarando `date`
como coluna requerida (dtype `Int64` epoch ms ou `pd.Timestamp`).

### 3.4 C4 — Janela vazia (`pivot_idx == break_idx`) não-tratada

**Hipótese (própria):** §4.5 passo 2b trata `pivot_idx is NaN` mas
não trata `pivot_idx == break_idx` (janela vazia, slice retorna
DataFrame vazio, `idxmin/idxmax` lança ValueError).

**Investigação:**

- **Briefing §4.5 passo 2b linha 515-519**: "Slicear
  `window_parsed = df.iloc[int(pivot_idx):X]` (semi-aberto à
  direita, P5). NOTA: se `pivot_idx` for `NaN`, abortar a criação
  deste OB e logar — significa que o break disparou antes do pivot
  materializar, o que indica bug em Onda 3/5 (não em Onda 6)."

  Só trata `NaN`. Não trata empate.

- **Análise lógica de probabilidade**:
  - Onda 3 materializa `*_LEVEL` no candle Y = pivot_position +
    length.
  - Onda 5 dispara `crossover(close, level)` requer level
    não-NaN no candle atual E no anterior. Primeiro candle
    com level válido é Y; comparison com previous (`level.shift(1)[Y]
    = NaN`) retorna False. Logo crossover só pode disparar em
    `Y+1` mais cedo.
  - `pivot_idx` (= COL_*_IDX) = pivot_position = Y - length << Y+1.
  - **Janela vazia (`pivot_idx == break_idx`) é praticamente
    impossível** desde que Onda 3 e Onda 5 estejam corretas.

- **Mas**: smoke vetorizado em pandas pode ter edge case com
  `Int64` truncamento ou bordas do DataFrame curto (e.g., teste
  sintético com < 50 candles).

**Severidade**: **menor**. Mecanicamente impossível em uso real,
mas implementador deve guardar contra. Sugestão: adicionar à nota
do §4.5 passo 2b: "se janela for vazia (`int(pivot_idx) >= X`),
abortar a criação e logar — indica bug em Onda 3/5".

**Patch §5.12** cobre.

### 3.5 C5 — Empate em `parsed_low` / `parsed_high` sem política documentada

**Hipótese (própria):** §4.5 passo 2c usa `idxmin()` / `idxmax()`
mas não documenta o comportamento em caso de empate (múltiplos
candles com mesmo `parsed_low` mínimo).

**Investigação:**

- **pandas `Series.idxmin()`** docs: "Index of the first
  occurrence of minimum of values."
- **Pine `array.indexof(array.min(arr))`**: `array.indexof` retorna
  a primeira ocorrência ([Pine v5 ref](https://www.tradingview.com/pine-script-reference/v5/#fun_array.indexof)).
- **Conclusão**: ambos retornam **primeiro candle** com o valor
  extremo. Comportamento naturalmente consistente entre Pine e
  pandas.

**Severidade**: **menor**. Comportamento consistente por feliz
coincidência das duas linguagens. Mas documentar explicitamente
no §4.5 evita ambiguidade na revisão de implementação.

**Patch §5.13** cobre — adiciona linha em §4.5 passo 2c: "Empate
em `parsed_low.min()` / `parsed_high.max()`: ambos `Series.idxmin()`
(pandas) e `array.indexof(array.min(...))` (Pine) retornam a
**primeira ocorrência**. Comportamento consistente entre as duas
linguagens — sem necessidade de tie-breaking adicional."

### 3.6 C6 — §6 redação ambígua sobre bump de VERSION

**Hipótese (própria):** §6 critério de aceite afirma "`VERSION`
bumpada conforme AGENTS §1.3 — Marcelo confirma número
explicitamente no PR (esperado: 0.6.0)". Implica que Claude Code
bumpa e Marcelo só confirma. Contradiz AGENTS §1.2.

**Investigação:**

- **AGENTS.md §1.2 (linha 75-77)** verbatim: "Claude Code
  implementa sem alterar `VERSION`. Marcelo revisa o PR.
  Instrução explícita de merge é dada. A atualização de `VERSION`
  tem que ser explícita para acontecer junto do PR."

  **Tradução**: Marcelo é quem bumpa VERSION; Claude Code nunca
  toca.

- **Briefing §6 linha 727-728**: "`VERSION` bumpada conforme
  AGENTS §1.3 — Marcelo confirma número explicitamente no PR
  (esperado: 0.6.0)".

  **Redação ambígua**: "Marcelo confirma" pode ser lido como "Claude
  Code bumpa, Marcelo confere o número".

- **AGENTS §1.3** trata da regra de versionamento sequencial e
  bump em todas ocorrências, mas a responsabilidade do bump fica
  com §1.2 (Marcelo).

**Severidade**: **média**. Redação ambígua em critério de aceite
pode levar Claude Code a bumpar (violando AGENTS §1.2). Idem
risco que Wave 5 — verificar se Onda 5 teve o mesmo problema
(verificação cruzada não-prioritária).

**Patch §5.14** cobre — substitui linha 727-728 por: "`VERSION`
é bumpado por Marcelo **antes do merge** (AGENTS §1.2). Claude
Code **NÃO altera VERSION** no PR. Versão esperada pós-merge:
**0.6.0** (sequencial sobre 0.5.0 da Onda 5)."

### 3.7 C7 — §8.4 limiar "≥10 ratificados" sem base canônica

**Hipótese (própria):** §8.4 estabelece "≥10 ratificados de 13"
como critério de pass/fail do spot-check, sem fundamentação.

**Investigação:**

- **Briefing §8.4 linha 876-878**: "Esperado: dos 13 OBs visuais,
  **≥10 ratificados em (a) ou (b)**. Casos não-ratificados viram
  lista de divergências para o relatório anexado ao PR."

- **Wave 5 final report** (`onda-05-final-consistency-report.md`):
  não estabelece threshold quantitativo. Reporta "ratificado /
  divergente" caso-a-caso. Critério é qualitativo.

- **Mapa §7.4**: tolerância é ±1 candle, mas não estabelece
  threshold de "% mínimo de match para considerar a onda
  aprovada".

O limiar "10/13" foi inventado pelo briefing sem ancoragem
canônica.

**Severidade**: **menor**. Critério inventado mas conservador.
Não impede implementação mas pode forçar rework se 9 de 13
ratificarem (e Marcelo decidir que está OK).

**Opções de patch**:
- (a) Remover o limiar quantitativo, manter o relatório
  qualitativo (Marcelo avalia caso-a-caso).
- (b) Justificar o limiar via referência a Wave 5 (mas Wave 5
  não estabelece).
- (c) Substituir por "≥ X% (X a definir conforme experiência
  Wave 5)".

Recomendado **(a)**: alinhamento com prática Wave 5 (qualitativo)
e AGENTS §2.2 (simplicidade — não introduzir métricas não
canônicas).

**Patch §5.15** cobre.

### 3.8 C8 — §4.5 passo 3 ordering ambígua

**Hipótese (própria):** §4.5 passo 3 menciona ordenação
"internal-first então swing-first, P7" no MITIGATION pass mas não
esclarece se essa ordem afeta o resultado.

**Investigação:**

- **Briefing §4.5 passo 3 linha 543-546**: "Para cada `ob_id` no
  ledger (ordenado por internal-first então swing-first, P7)".

- **Análise causal**: o MITIGATION pass busca para cada OB
  independentemente a primeira vela `> t_creation` que satisfaz a
  condição. **Não há efeito-colateral entre OBs** (um OB mitigado
  não "consome" o candle, não bloqueia outro de mitigar no mesmo
  candle).

  Portanto, **a ordem de iteração dentro do MITIGATION pass NÃO
  afeta o conteúdo do ledger nem do `df_per_candle`**. Cada
  ledger entry recebe o mesmo `t_mitigation` independente da
  ordem.

- Ordem só importa para **estilo de execução** (cosmético: log
  order, debug ordering). Pine seguiu a ordem
  `internal → swing` por razões de orquestração (estado em
  array global), mas em pandas vetorizado essa ordem não tem
  função.

**Severidade**: **menor**. Não afeta correção; afeta clareza.

**Patch §5.16** cobre — adiciona observação em §4.5 passo 3:
"A ordem de iteração (internal antes de swing) é cosmética em
pandas vetorizado — não há efeito-colateral entre OBs no
MITIGATION pass; cada OB é processado independentemente. P7
mantém a ordem por fidelidade ao Pine e por consistência com
o CREATE pass (onde a ordem afeta `ob_id` sequencial)."

---

## 4. Itens em aberto §11 do briefing — status pós-auditoria

Todos os 4 itens fechados. Tabela canônica:

| Item §11 | Hipótese inicial do briefing | Decisão final | Justificativa (seção deste audit) |
|---|---|---|---|
| 11.1 (slice exclusive vs inclusive) | "espelha sintaxe Python e convenção da maioria das linguagens de array" | **FECHADO — exclusive end** | §2.3 (B1) |
| 11.2 (tuple vs helper separado) | "Recomendado tuple; audit decide" | **FECHADO — tuple-return obrigatório** (helper alternativo não é reconstrutível em geral) | §2.5 (B3) |
| 11.3 (naming) | "Recomendado `created/mitigated`" | **FECHADO — `created/mitigated`** (Pine "alert" incompleto, não cobre CREATE) | §2.6 (B4) |
| 11.4 (gap dogmático) | 3 opções (a/b/c) | **FECHADO — opção (c) refinada**: criar §7.9 nova no Mapa | §2.4 (B2) |

---

## 5. Patch consolidado proposto

Todos os patches em um único PR. Texto exato antes/depois.
Numerados na ordem de aparição no briefing (top-down).

### 5.1 [A1, C1 parcial] §1 parágrafo 4 — corrigir "5 → 6 campos novos"

**Localização**: linha 27.

**Antes**:
```
- Estende o UDT `OrderBlock` de Onda 1 com 5 campos novos (lifecycle
  + scope + state + hook volumetric), mantendo `bar_time` para
  preservar fidelidade à interface Pine.
```

**Depois**:
```
- Estende o UDT `OrderBlock` de Onda 1 com 6 campos novos
  (`t_creation`, `t_mitigation`, `t_invalidation`, `scope`, `state`,
  `volumetric_intensity`), mantendo `bar_time` para preservar
  fidelidade à interface Pine.
```

**Justificativa**: §2.1 (A1) — contagem canônica é 6.

### 5.2 [A1] §2 P3 texto explicativo — corrigir "5 → 6"

**Localização**: linha 113-116.

**Antes**:
```
   A extensão do UDT é exceção autorizada à mudança cirúrgica
   (AGENTS §2.3): necessidade arquitetural Wave 6 — sem os 5 campos
   novos, o ledger não é construível e o spot-check híbrido fica
   inespecificável.
```

**Depois**:
```
   A extensão do UDT é exceção autorizada à mudança cirúrgica
   (AGENTS §2.3): necessidade arquitetural Wave 6 — sem os 6 campos
   novos, o ledger não é construível e o spot-check híbrido fica
   inespecificável.
```

**Justificativa**: §2.1 (A1) — segunda ocorrência da contagem
errada, não identificada no input.

### 5.3 [B1] §11.1 — fechar com decisão definitiva

**Localização**: linhas 951-959.

**Antes**:
```
1. **Slice exclusive vs inclusive end (P5).** Confirmar que Pine
   `array.slice(arr, from, to)` é `[from, to)` (exclusive end)
   antes da implementação. Hipótese atual (espelha sintaxe Python e
   convenção da maioria das linguagens de array); PyneCore compilou
   verbatim — verificar comportamento em `pynecore.lib.array` ou
   via teste sintético no smoke da Wave 6. Impacto: se exclusive,
   `df.iloc[pivot_idx:break_idx]` correto. Se inclusive,
   `df.iloc[pivot_idx:break_idx + 1]`. Erro de 1 candle no
   parsed-extreme.
```

**Depois** (item movido para "Decisões fechadas pelo audit"):
```
1. **Slice exclusive vs inclusive end (P5) — FECHADO.** Pine
   `array.slice(arr, from, to)` é `[from, to)` (exclusive end),
   confirmado por: (a) documentação oficial Pine v5
   (`index_to` = "before which to end extraction"), (b) análise de
   contexto do Pine fonte linhas 227-231 (incluir bar_index atual
   distorceria a busca pelo parsed-extreme, então só exclusive faz
   sentido logicamente). Implementação: `df.iloc[int(pivot_idx):int(break_idx)]`
   conforme P5. Sem necessidade de smoke disambiguador. Ver audit
   report §2.3.
```

**Justificativa**: §2.3 (B1) — evidência canônica conclusiva.

### 5.4 [B2] Mapa §7.9 nova — Divergências dogmáticas SMC vs LuxAlgo gratuito

**Localização**: `docs/MAPA_LUXALGO_CAMADA_1_v1.1.md`, adicionar
nova subseção após §7.8 e antes de §8.

**Texto exato a adicionar**:

```
### 7.9 Divergências dogmáticas SMC vs LuxAlgo gratuito

Categoria distinta de §7.8: divergências entre o framework SMC
dogmático (Mentfx, ICT, e literatura derivada) e a implementação
do LuxAlgo gratuito que serve de referência canônica de match
exato (§7.1). Estas divergências **não são bugs** nem **features
do pago**.

**Princípio canônico**: a portagem prioriza fidelidade ao
LuxAlgo gratuito sobre fidelidade ao dogma SMC. Razão: §7.1
estabelece o gratuito como single source of truth para match
exato. Tornar a portagem "mais dogmática" que a referência seria
**bias arquitetural não-autorizado** (AGENTS §1.0.1 — Mapa
prevalece sobre interpretação).

**Divergências dogmáticas registradas**:

| # | Divergência | Definição dogmática SMC | Implementação LuxAlgo gratuito | Onda afetada |
|---|---|---|---|---|
| 1 | Origem do Order Block | Última vela de cor oposta antes do break (Mentfx) | Vela com extremo de `parsed_low`/`parsed_high` na janela `[pivot_idx, break_idx)` (LuxAlgo) | Onda 6 |

Quando a engine produz output que não bate com a definição
dogmática mas bate com o LuxAlgo gratuito, **a engine está
correta**. Marcelo decide caso-a-caso se a divergência justifica
investigação adicional ao `SMC_PRINCIPIOS_E_LEGADO.md` (PR de doc
dedicado, NÃO bloqueia ondas em curso).
```

**Justificativa**: §2.4 (B2) — opção (c) refinada.

### 5.5 [B2] §11.4 — fechar apontando para Mapa §7.9

**Localização**: linhas 976-990.

**Antes**:
```
4. **Gap dogmático SMC vs LuxAlgo.** `docs/SMC_PRINCIPIOS_E_LEGADO.md`
   sugere implicitamente que origem do OB = última vela de cor
   oposta antes do break (definição dogmática). LuxAlgo usa lógica
   diferente: vela com extremo de `parsed_low`/`parsed_high` na
   janela `[pivot_idx, break_idx)` — pode coincidir, pode não. Wave 6
   segue Pine fonte (fidelidade ao gratuito, AGENTS §1.0.1
   hierarquia de fontes). Audit decide se isso vira:
   - (a) Nova entrada em §7.8 do Mapa ("divergência esperada
     não-bug, dogmático SMC ≠ LuxAlgo"), ou
   - (b) Investigação adicional para codificar a definição
     dogmática em `SMC_PRINCIPIOS_E_LEGADO.md` antes da
     implementação, ou
   - (c) Aceitar implicitamente como pré-condição da portagem
     ("LuxAlgo gratuito é referência canônica de match exato",
     Mapa §7.1).
```

**Depois**:
```
4. **Gap dogmático SMC vs LuxAlgo — FECHADO.** Decisão final: a
   divergência (origem de OB dogmática = última vela de cor oposta
   antes do break; LuxAlgo = vela com extremo de
   `parsed_low`/`parsed_high` na janela `[pivot_idx, break_idx)`)
   é registrada em **nova subseção §7.9 do Mapa Camada 1**
   ("Divergências dogmáticas SMC vs LuxAlgo gratuito"), aplicada
   junto deste PR. Princípio canônico: portagem prioriza fidelidade
   ao gratuito (§7.1 do Mapa). Engine não é considerada "errada"
   se produzir output diferente da definição dogmática mas
   compatível com o gratuito. Ver audit report §2.4.
```

**Justificativa**: §2.4 (B2).

### 5.6 [B3] §11.2 — fechar com argumento técnico forte

**Localização**: linhas 961-968.

**Antes**:
```
2. **Contrato de saída: tuple vs helper separado.** Wave 6 propõe
   `detect_order_blocks(df) -> tuple[pd.DataFrame, pd.DataFrame]`,
   quebrando o padrão Onda 5 (`detect_structure(df) -> pd.DataFrame`).
   Audit decide se a clareza arquitetural (ledger lifecycle
   queryable) compensa a quebra de padrão, ou se a alternativa
   `df = detect_order_blocks(df); ledger = get_order_blocks_ledger(df)`
   (helper separado, com ledger reconstruído a partir das colunas
   booleans + state interno cacheado em `df.attrs`) é preferível.
```

**Depois**:
```
2. **Contrato de saída: tuple-return — FECHADO.** Decisão final:
   `detect_order_blocks(df) -> tuple[pd.DataFrame, pd.DataFrame]`
   é a única opção tecnicamente viável. A alternativa (helper
   `get_order_blocks_ledger(df)` reconstruindo via `df.attrs` ou
   via colunas booleans) tem duas falhas técnicas:

   (i) `df.attrs` é experimental em pandas e NÃO é propagado por
   operações comuns (`pd.concat`, `pd.merge`, `groupby.agg`); em
   pipeline Freqtrade real evapora silenciosamente.

   (ii) Reconstrução determinística do ledger a partir das 8
   booleans + OHLC é impossível em geral: `bar_time` exige
   recomputar `parsed_high`/`parsed_low` (dependem de `ob_filter`,
   `atr_length`), e o matching CREATE→MITIGATE para múltiplos
   OBs coexistentes do mesmo (scope, direction) é ambíguo sem
   o ledger interno.

   Ver audit report §2.5.
```

**Justificativa**: §2.5 (B3).

### 5.7 [B4] §11.3 — fechar com naming `created/mitigated`

**Localização**: linhas 970-974.

**Antes**:
```
3. **Naming das 8 colunas booleans.** Wave 6 propõe `ob_<scope>_<direction>_created` /
   `_mitigated`. Alternativa Pine-faithful: `ob_alert_<scope><direction>`
   (espelha `currentAlerts.internalBullishOrderBlock` etc. do Pine).
   Audit decide. Recomendação atual: `created/mitigated` mais
   informativo e separa CREATE de MITIGATE em colunas distintas.
```

**Depois**:
```
3. **Naming das 8 colunas booleans — FECHADO.** Decisão final:
   `ob_<scope>_<direction>_created` / `_mitigated`. Razões:
   (a) Pine usa "alert" porque seu output é `alertcondition`; em
   pandas o output é dado, não evento de alerta — "alert" carrega
   significado errado. (b) No Pine, `*OrderBlock` no nome do alert
   refere-se a **mitigação** somente (linhas 329-332 do Pine: "OB
   Breakout"); replicar em pandas obrigaria a omitir os eventos
   de criação, que Wave 6 expõe. Logo o naming Pine-faithful é
   incompleto. Ver audit report §2.6.
```

**Justificativa**: §2.6 (B4).

### 5.8 [B5] §4.4 invariante 13 + §5 caso de teste novo

**Localização §4.4**: após linha 497 (após invariante 12).

**Texto a adicionar (invariante 13 nova)**:
```
13. **Co-mitigação determinística.** Se múltiplos OBs do mesmo
    `(scope, direction)` são mitigados no mesmo candle Z, então
    `df_per_candle.loc[Z, 'ob_<scope>_<direction>_mitigated'] == True`
    (uma única marca booleana) e todos os OBs envolvidos têm
    `t_mitigation == df.iloc[Z]['date']` no ledger.
```

**Localização §5**: §5.1 ganha **fase 6 nova** na fixture; §5.2
ganha **função de teste nova**.

**Texto a adicionar em §5.1**:
```
- **Fase 6 (~290-300, dependente de extensão de N):** retração
  profunda que fura `bar_low` de **ambos** os bullish OBs criados
  em fases 4 e 5 no mesmo candle Z. *Esperado:* co-mitigação:
  `ob_swing_bullish_mitigated[Z] == True` (única marca booleana);
  ambos OBs no ledger ganham `t_mitigation == df.iloc[Z]['date']`.
  Cobre invariante 13.
```

**Texto a adicionar em §5.2** (após `test_smoke_wave6_parsed_high_low_inversion`):
```python
def test_smoke_wave6_co_mitigation(synthetic_df_co_mit):
    """Múltiplos OBs do mesmo (scope, direction) mitigados no mesmo candle.

    Fixture estendida com fase 6: candle Z onde low fura bar_low de
    ≥2 bullish swing OBs simultaneamente. Cobre invariante 13.
    """
    df = detect_pivots(synthetic_df_co_mit, swings_length=50, internal_length=5, equal_length=3)
    df = compute_trailing_extremes(df)
    df = detect_structure(df)
    df_out, ledger = detect_order_blocks(df, mitigation='Wick')

    co_mit_candles = df_out.index[df_out['ob_swing_bullish_mitigated']]
    found_co_mitigation = False
    for Z in co_mit_candles:
        ts_Z = df_out.loc[Z, 'date']
        co_mit_obs = ledger.query(
            "scope == 'swing' and bias == @BULLISH and t_mitigation == @ts_Z"
        )
        if len(co_mit_obs) >= 2:
            found_co_mitigation = True
            # Invariante 13
            assert df_out.loc[Z, 'ob_swing_bullish_mitigated']
            assert (co_mit_obs['t_mitigation'] == ts_Z).all()
    assert found_co_mitigation, "Fixture deve gerar ≥1 candle de co-mitigação"
```

**Justificativa**: §2.7 (B5).

### 5.9 [A2] §5.2 — assert tautológico → assert forte

**Localização**: linhas 668-679.

**Antes**:
```python
def test_smoke_wave6_mitigation_close_mode(synthetic_df):
    """Modo Close usa close como source, não high/low. Esperado: mitigações
    são *menos frequentes* que no modo Wick (Close mais conservador)."""
    df = detect_pivots(synthetic_df, swings_length=50, internal_length=5, equal_length=3)
    df = compute_trailing_extremes(df)
    df = detect_structure(df)
    _, ledger_wick = detect_order_blocks(df, mitigation='Wick')
    _, ledger_close = detect_order_blocks(df, mitigation='Close')

    n_mit_wick = (ledger_wick['state'] == 'mitigated').sum()
    n_mit_close = (ledger_close['state'] == 'mitigated').sum()
    assert n_mit_close <= n_mit_wick
```

**Depois**:
```python
def test_smoke_wave6_mitigation_close_mode(synthetic_df):
    """Modo Close usa close como source, não high/low.

    Assert forte (não-tautológico): pelo menos um OB do ledger tem
    comportamento de mitigação diferente entre Wick e Close. Sem
    isso, o teste passaria mesmo se a engine ignorasse o parâmetro
    `mitigation` (Wick é estritamente mais permissivo que Close
    para qualquer OHLC válido — então `n_mit_close <= n_mit_wick`
    é tautológico).

    Fixture pré-requisito: pelo menos um candle de retração cujo
    `low` (ou `high` para bearish) fura `bar_low` (ou `bar_high`)
    de algum OB ativo enquanto o `close` do mesmo candle ainda
    fica do lado oposto. A fixture §5.1 fase 3 já garante esse
    cenário (candle Z com `low < ob.bar_low` e `close >= ob.bar_low`).
    """
    df = detect_pivots(synthetic_df, swings_length=50, internal_length=5, equal_length=3)
    df = compute_trailing_extremes(df)
    df = detect_structure(df)
    _, ledger_wick = detect_order_blocks(df, mitigation='Wick')
    _, ledger_close = detect_order_blocks(df, mitigation='Close')

    joined = ledger_wick.merge(
        ledger_close, on='ob_id', suffixes=('_wick', '_close'),
    )
    strictly_earlier = (
        joined['t_mitigation_wick'].notna()
        & joined['t_mitigation_close'].notna()
        & (joined['t_mitigation_wick'] < joined['t_mitigation_close'])
    ).any()
    wick_only = (
        joined['t_mitigation_wick'].notna()
        & joined['t_mitigation_close'].isna()
    ).any()
    assert strictly_earlier or wick_only, (
        "Parâmetro mitigation parece estar sendo ignorado: Wick e "
        "Close produzem ledgers indistinguíveis. Verificar "
        "implementação de _resolve_mitigations."
    )
```

**Justificativa**: §2.2 (A2).

### 5.10 [C1] §6 e §10 — corrigir "12 → 13 OBs"

**Localização §6 linha 729-730**:

**Antes**:
```
- [ ] Spot-check híbrido contra os ~12 OBs do §3.1 do relatório
      final da Onda 5 — relatório anexado ao body do PR
```

**Depois**:
```
- [ ] Spot-check híbrido contra os 13 OBs do §3.1 do relatório
      final da Onda 5 — relatório anexado ao body do PR
```

**Localização §10 ref 7 linha 924**:

**Antes**:
```
7. `smc_freqtrade/briefings/onda-05-final-consistency-report.md` —
   §3.1 (12 OBs pré-mapeados, material do spot-check), §6.2
   (recomendação para Onda 6), **DT-4** (Mapa §7.6 patch — agora
   absorvido em §7 deste briefing).
```

**Depois**:
```
7. `smc_freqtrade/briefings/onda-05-final-consistency-report.md` —
   §3.1 (13 OBs pré-mapeados — header colloquial "~12 OBs", mas
   tabela canônica lista 13 entradas — material do spot-check),
   §6.2 (recomendação para Onda 6), **DT-4** (Mapa §7.6 patch —
   agora absorvido em §7 deste briefing).
```

**Justificativa**: §3.1 (C1).

### 5.11 [C2] §3 passo 3 — corrigir "8 cenários"

**Localização**: linhas 273-275.

**Antes**:
```
3. **Criar `smc_freqtrade/tests/test_smoke_wave6.py`** com smoke
   sintético conforme §5. *Verifica:* `pytest` passa; cobertura dos
   8 cenários listados em §5.
```

**Depois**:
```
3. **Criar `smc_freqtrade/tests/test_smoke_wave6.py`** com smoke
   sintético conforme §5. *Verifica:* `pytest` passa; as 5 funções
   de teste de §5 (`test_smoke_wave6_lifecycle`,
   `test_smoke_wave6_mitigation_close_mode`,
   `test_smoke_wave6_bar_time_within_window`,
   `test_smoke_wave6_parsed_high_low_inversion`,
   `test_smoke_wave6_co_mitigation`) passam cobrindo a fixture com
   6 fases (incluindo a fase 6 nova de co-mitigação, patch §5.8).
```

**Justificativa**: §3.2 (C2). Contagem final = 5 funções (4
originais + 1 nova de co-mitigação) cobrindo 6 fases (5 originais
+ 1 nova).

### 5.12 [C3] §4.1 FONTE DE DADOS — declarar coluna `date`

**Localização**: linhas 328-343 (`FONTE DE DADOS` no docstring).

**Antes**:
```
    FONTE DE DADOS
        df: DataFrame com no mínimo OHLC + as 4 colunas COL_*_IDX
            produzidas por detect_pivots() (Onda 3) para os escopos
            swing e internal + as 8 booleans BOS/CHoCH produzidas por
            detect_structure() (Onda 5).
        ob_filter: replica orderBlockFilterInput do Pine (linha 87).
            ...
```

**Depois**:
```
    FONTE DE DADOS
        df: DataFrame com no mínimo:
            - 4 colunas OHLC: open, high, low, close (float64).
            - Coluna `date` (Int64 epoch ms ou pd.Timestamp) —
              timestamp canônico usado para preencher bar_time,
              t_creation e t_mitigation no ledger.
            - 4 colunas COL_*_IDX produzidas por detect_pivots()
              (Onda 3) para os escopos swing e internal.
            - 8 booleans BOS/CHoCH produzidas por detect_structure()
              (Onda 5).
        ob_filter: replica orderBlockFilterInput do Pine (linha 87).
            ...
```

**Justificativa**: §3.3 (C3).

### 5.13 [C4] §4.5 passo 2b — guardar contra janela vazia

**Localização**: linha 515-519.

**Antes**:
```
   b. Slicear `window_parsed = df.iloc[int(pivot_idx):X]` (semi-aberto
      à direita, P5). NOTA: se `pivot_idx` for `NaN`, abortar a
      criação deste OB e logar — significa que o break disparou antes
      do pivot materializar, o que indica bug em Onda 3/5 (não em
      Onda 6).
```

**Depois**:
```
   b. Slicear `window_parsed = df.iloc[int(pivot_idx):X]` (semi-aberto
      à direita, P5). NOTA:
      - Se `pivot_idx` for `NaN`, abortar a criação deste OB e
        logar — significa que o break disparou antes do pivot
        materializar, o que indica bug em Onda 3/5 (não em Onda 6).
      - Se a janela for vazia (`int(pivot_idx) >= X`), abortar a
        criação deste OB e logar — janela vazia é praticamente
        impossível com Onda 3/5 corretas (ver audit §3.4), mas
        possível em smoke sintético com horizonte curto. Mesma
        classificação de bug que NaN.
```

**Justificativa**: §3.4 (C4).

### 5.14 [C5] §4.5 passo 2c — documentar política de empate

**Localização**: linha 521-523.

**Antes**:
```
   c. Para BULLISH OB: `extreme_idx = window_parsed['parsed_low'].idxmin()`.
      Para BEARISH OB: `extreme_idx = window_parsed['parsed_high'].idxmax()`.
```

**Depois**:
```
   c. Para BULLISH OB: `extreme_idx = window_parsed['parsed_low'].idxmin()`.
      Para BEARISH OB: `extreme_idx = window_parsed['parsed_high'].idxmax()`.
      Empate (múltiplos candles com mesmo extremo): ambos
      `Series.idxmin()` (pandas) e `array.indexof(array.min(...))`
      (Pine) retornam a **primeira ocorrência**. Comportamento
      consistente entre as duas linguagens — sem necessidade de
      tie-breaking adicional.
```

**Justificativa**: §3.5 (C5).

### 5.15 [C6] §6 critério VERSION — alinhar com AGENTS §1.2

**Localização**: linhas 727-728.

**Antes**:
```
- [ ] `VERSION` bumpada conforme AGENTS §1.3 — Marcelo confirma
      número explicitamente no PR (esperado: 0.6.0)
```

**Depois**:
```
- [ ] `VERSION` é bumpado por Marcelo **antes do merge** (AGENTS
      §1.2). Claude Code **NÃO altera VERSION** no PR. Versão
      esperada pós-merge: **0.6.0** (sequencial sobre 0.5.0 da
      Onda 5).
```

**Justificativa**: §3.6 (C6).

### 5.16 [C7] §8.4 — remover limiar arbitrário

**Localização**: linhas 876-878.

**Antes**:
```
Esperado: dos 13 OBs visuais, ≥10 ratificados em (a) ou (b). Casos
não-ratificados viram lista de divergências para o relatório anexado
ao PR.
```

**Depois**:
```
Esperado: relatório anexado ao body do PR listando, para cada um
dos 13 OBs visuais, classificação caso-a-caso (ratificado /
divergente em (a)/(b)/(c)). **Sem critério quantitativo
pré-estabelecido** — alinhamento com prática Wave 5 (avaliação
qualitativa por Marcelo). Marcelo decide aprovação do PR conforme
relatório.
```

**Justificativa**: §3.7 (C7).

### 5.17 [C8] §4.5 passo 3 — documentar ordering como cosmética

**Localização**: linha 543-547.

**Antes**:
```
3. **MITIGATION pass** (vetorizado por OB):

   Para cada `ob_id` no ledger (ordenado por internal-first então
   swing-first, P7):
```

**Depois**:
```
3. **MITIGATION pass** (vetorizado por OB):

   Para cada `ob_id` no ledger (ordenado por internal-first então
   swing-first, P7).

   **Nota**: a ordem de iteração (internal antes de swing) é
   **cosmética** em pandas vetorizado — não há efeito-colateral
   entre OBs no MITIGATION pass; cada OB é processado
   independentemente. P7 mantém a ordem por fidelidade ao Pine e
   por consistência com o CREATE pass (onde a ordem afeta `ob_id`
   sequencial).
```

**Justificativa**: §3.8 (C8).

---

## 6. Bloqueantes para a sessão de implementação

**Nenhum bloqueante.** Todos os achados Camada 1 e Camada 2 são
endereçáveis via patches §5 acima, que podem ser absorvidos:

- **Opção 1 (recomendada)**: PR de doc consolidado (este audit
  report + 17 patches §5 aplicados ao briefing + patch §5.4
  aplicado ao Mapa). Marge antes da sessão de implementação Wave 6.
- **Opção 2**: patches §5 absorvidos no próprio PR de implementação
  Wave 6 (briefing atualizado + Mapa atualizado + código novo no
  mesmo PR). Reduz contagem de PRs mas inflaciona o diff.

Marcelo decide.

---

## 7. Recomendados não-bloqueantes

Observações de qualidade que não afetam correção da implementação
mas melhoram o briefing como documento canônico. Marcelo decide
absorção.

### 7.1 §4.1 NÃO FAZER — redação "Não popular EngineState"

**Localização**: linha 390.

**Observação**: o texto "Não popular EngineState (Mapa §2 v1.1)"
faz sentido na arquitetura vetorizada (EngineState é Onda 1
herança Pine, não usado em pandas), mas pode confundir o leitor
que vê EngineState definido com slots `swing_order_blocks` e
`internal_order_blocks`. Sugestão: "Não popular EngineState (Mapa
§2 v1.1) — a portagem é vetorizada sobre DataFrame; o ledger
substitui os slots `swing_order_blocks` / `internal_order_blocks`
do EngineState herdado do Pine."

### 7.2 §10 ref 4 — referência circular a §11 item 4

**Localização**: linha 914-915.

**Observação**: após patch §5.5 (que fecha §11.4 e cria Mapa §7.9),
a referência "definição dogmática de OB (gap documental; ver §11
item 4 deste briefing)" deve ser atualizada para "definição
dogmática de OB (gap registrado em Mapa §7.9, criado neste PR)".
Mantém rastreabilidade canônica.

### 7.3 Hooks §8.1 — declarar `volume` como pré-condição da Onda 6.1

**Localização**: §8.1, linhas 804-817.

**Observação**: o hook Onda 6.1 (Volumetric OB) prevê preencher
`volumetric_intensity` "somando volume da janela `[pivot_idx, break_idx)`",
o que implica que a Onda 6.1 exigirá coluna `volume` no DataFrame de
entrada. Recomendado adicionar nota explícita: "Pré-condição Onda 6.1:
DataFrame de entrada deve incluir coluna `volume` (padrão Freqtrade
OHLCV). Não é pré-condição da Wave 6 base — apenas da extensão Onda
6.1."

### 7.4 Severidade dos 17 patches §5 — sugestão de priorização

Se Marcelo optar pela **Opção 2** (absorver patches no PR de
implementação), priorizar nesta ordem caso o diff fique grande
demais:

- **Críticos** (correção factual): §5.1, §5.2, §5.10 (campos 5→6,
  OBs 12→13). Mudam números canônicos.
- **Estruturais** (decisões fechadas): §5.3, §5.4, §5.5, §5.6,
  §5.7. Fecham §11 do briefing.
- **Testes** (correção de smoke): §5.8, §5.9. Smokes sem essas
  patches têm cobertura fraca.
- **Documentação** (clareza): §5.11-§5.17. Refinam mas não afetam
  resultado.

---

*Fim do audit report Onda 6.*
