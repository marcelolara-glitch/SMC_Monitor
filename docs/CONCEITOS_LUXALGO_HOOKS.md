# Conceitos LuxAlgo — Referência Canônica dos Hooks Pendentes

> Documento de referência permanente. Todas as definições foram
> extraídas diretamente de `docs.luxalgo.com`, Pines free
> publicados pela LuxAlgo no TradingView, e Pine `Volumized Order
> Blocks` da FluxCharts. **Não há especulação — apenas citações
> verbatim, código verificado, e divergências intencionais
> explicitamente declaradas.**
>
> Versão consolidada após análise de 8 Pines free e doc PAC,
> com decisões arquiteturais aprovadas por Marcelo.
>
> Destino: `docs/CONCEITOS_LUXALGO_HOOKS.md` — absorvido no PR
> da Wave 8.1 (primeira wave do bloco pré-9.5a).
>
> Autor: Claude.ai · Data: 2026-05-18 · Versão: 2.0

---

## 0. Decisões arquiteturais aprovadas

Estas decisões foram tomadas em conversa Claude.ai com Marcelo,
após análise de Pines disponíveis e impossibilidade de acessar
o PAC paid. **São válidas para todo o bloco pré-9.5a.**

| Tópico | Decisão | Razão |
|---|---|---|
| **Breaker Block** | Seguir definição PAC paid (OB mitigado vira Breaker) | Coerência com arquitetura primitivas→assinaturas |
| **IFVG** | Seguir definição PAC paid (FVG mitigada vira IFVG na retest) | Compõe melhor com A4a "IFVG Retest" no catálogo |
| **PAC paid Pine** | Inacessível (invite-only) | Divergências documentadas onde Pine não disponível |
| **Fonte FluxCharts** | Aceita como referência metodológica para Volumetric OB | Única fonte Pine pública para fórmulas volumétricas |
| **Camada IT (Intermediate Term)** | Não implementar agora — hook reservado | Refactor da Wave 3 mergeada não justifica ganho marginal incerto |

---

## 1. CHoCH+ (Wave 5.5)

### Definição oficial LuxAlgo

> *"The 'CHoCH+' label is also demonstrated as it triggers only
> if price has already made a new higher low, or lower high."*

> *"'CHoCH+' being a more confirmed reversal signal."*

Fonte: `luxalgo.com/library/indicator/luxalgo-price-action-concepts`

### Conceito

CHoCH+ é variante mais estrita do CHoCH. Dispara apenas se, **antes
do break**, o preço já fez:

- **CHoCH+ bullish:** um novo **higher low** (HL)
- **CHoCH+ bearish:** um novo **lower high** (LH)

**Regra estrutural pura** — não envolve volume, deslocamento, P/D
ou outras métricas.

### Pine source público (confirmado)

Existem booleans paralelos:
- `s_CHoCH` (CHoCH swing puro) e `s_CHoCHP` (CHoCH+ swing)
- `i_CHoCH` (CHoCH internal puro) e `i_CHoCHP` (CHoCH+ internal)

### Implementação Wave 5.5

Em `structure.py`:
- Booleans paralelos `choch_plus_*` para internal e swing
- Detecção: requer HL/LH formado entre último CHoCH simples e o
  break atual
- Não exige dependência de outros módulos

### Divergência intencional

**O detalhe operacional exato** de "quão recente deve ser o HL/LH
prévio" não está publicado. Recomendação: HL/LH deve estar entre
o último CHoCH simples confirmado e o break atual (sem janela
adicional). Documentar como divergência potencial vs PAC paid.

### Implicação para catálogo

- A1 (OB Retest + CHoCH) — opcional usar `choch_plus`
- A4a (IFVG Retest) — confirmação de reversão estrutural
- A6 (Unicorn) — Market Structure Shift literatura ICT
- A8 — validação de falha
- A9 (EQH/EQL Sweep + CHoCH) — robustez

**5 das 11 assinaturas beneficiam.**

---

## 2. Volumetric Order Block (Wave 6.1)

### Definição oficial LuxAlgo (doc PAC)

**Componentes:**

1. **Internal activity** (verbatim): *"highlights the bullish and
   bearish activity within the interval used to construct the
   order block"*

2. **Metrics** (verbatim): *"accumulated volume within the interval
   used to construct the order block (...) percentage to the right
   indicates how much the volume of an order block account for the
   total accumulated volume of all Volumetric Order Blocks
   displayed on the chart"*

3. **Hide Overlap** (verbatim): *"if two Volumetric Order Blocks
   overlap the most recent one will be conserved"*

4. **Position** (4 opções): `Full`, `Middle`, `Accurate`, `Precise`

5. **Mitigation** (2 opções): `Absolute`, `Middle`

### Código de referência — FluxCharts Volumized Order Blocks

**Atenção:** Este Pine é da **FluxCharts**, não LuxAlgo. Licença MPL
2.0. Adotado por ser **única fonte Pine pública** com fórmulas
volumétricas explícitas. PAC paid não disponível.

**Fórmulas verbatim do Pine FluxCharts:**

| Campo | Cálculo |
|---|---|
| `obVolume` | `volume[t] + volume[t-1] + volume[t-2]` (soma 3 candles) |
| `obHighVolume` (bullish) | `volume[t] + volume[t-1]` (2 candles bullish) |
| `obLowVolume` (bullish) | `volume[t-2]` (1 candle base) |
| `obHighVolume` (bearish) | `volume[t-2]` (1 candle base) |
| `obLowVolume` (bearish) | `volume[t] + volume[t-1]` (2 candles bearish) |
| `bbVolume` | `volume` no momento da mitigação (Breaker volume) |

### Implementação Wave 6.1

Em `OrderBlock` UDT (campos novos):
- `volume_bullish: float` — volume bullish acumulado dentro do range
- `volume_bearish: float` — volume bearish acumulado dentro do range
- `volume_total: float` — soma de ambos (= `obVolume`)
- `volume_pct: float` — percentual do total entre OBs ativos
- `bb_volume: float` — volume capturado no momento da mitigação

**Fórmula de `volume_pct`** (divergência intencional vs PAC paid):

```python
volume_pct[i] = obVolume[i] / sum(obVolume[j] for j in OBs_ativos)
```

Derivada da definição PAC verbatim. Documentar como "fórmula
derivada da definição PAC, sem código de referência disponível".

### Mitigation methods — DOIS sistemas paralelos

**Para Volumetric OB** (Wave 6.1): doc PAC oferece 2 opções —
`Absolute` e `Middle`.

| Método | Definição |
|---|---|
| **Absolute** | Preço atravessa range completo do OB |
| **Middle** | Preço atravessa nível médio do OB |

Atual: Wave 6 implementa apenas Wick (default). Wave 6.1 adiciona
suporte a `Absolute` e `Middle` per PAC paid.

### Hooks NÃO incluídos na Wave 6.1 (decisão Marcelo)

- **OB ATR size filter** (`maxATRMult = 3.5`) — feature FluxCharts,
  não está na PAC. Registrado como hook reservado em §10.
- **OB Combination** — feature FluxCharts. Hook reservado em §10.

### Implicação para catálogo

- **A5 (Direct OB Tap):** critério "alto score" passa a usar
  `volume_pct` (ex.: `volume_pct > 0.2` significa 20%+ do volume
  institucional)
- **A3 (Triple Confirmation):** critério opcional adicional

---

## 3. Breaker Block (Wave 6.2)

### Definição oficial LuxAlgo (doc PAC) — **DECISÃO MARCELO**

> *"Breaker Blocks show previous Volumetric Order Blocks that got
> mitigated (broken by price). These zones can be revisited by the
> price and provide support/resistance areas."*

> *"Bullish breaker blocks disappear once price goes above the
> breaker block upper extremity, while bearish breaker blocks
> disappear once price goes under the breaker block lower
> extremity."*

> *"A breaker block is confirmed when price comes back to mitigate
> an order block."*

Fonte: `docs.luxalgo.com/.../order-blocks`,
`luxalgo.com/blog/breaker-blocks-vs-order-blocks-key-differences-explained`

### Confirmação pelo Pine FluxCharts

O Pine FluxCharts implementa exatamente esta semântica:

```pine
if not currentOB.breaker
    if (low ou close min) < currentOB.bottom
        currentOB.breaker := true
        currentOB.breakTime := time
        currentOB.bbVolume := volume       // GUARDA volume na mitigação
else
    if high > currentOB.top
        bullishOrderBlocksList.remove(i)   // remove se preço sair pelo topo
```

Mecânica:
- OB mitigado vira breaker (estado `breaker := true`)
- Captura `bbVolume` no momento da mitigação
- Remove permanentemente se preço sair pelo lado oposto

### Diferença vs Pine LuxAlgo `Breaker Blocks with Signals`

O Pine LuxAlgo `Breaker Blocks with Signals` (free) usa **definição
diferente** (autônoma, via MSS + A-B-C-D-E search). **NÃO ADOTADA**
— decisão Marcelo: seguir PAC paid (simples, sobre OBs existentes).

### Implementação Wave 6.2

Em `order_blocks.py`:
- Estado `is_breaker: bool` no UDT `OrderBlock` (hook P9 já reservado)
- Campo `breaker_at: int` (timestamp da mitigação)
- Campo `bb_volume: float` (volume na mitigação)
- Lógica:
  - Ao mitigar OB → marcar `is_breaker = True`
  - Tracking de saída completa pelo lado oposto → marcar como morto
- Ingredientes já existem (Wave 6 mitigação ✅, Wave 8 sweeps
  para enriquecer contexto)

### Implicação para catálogo

- **A6 (ICT Unicorn):** Breaker Block + FVG overlap → setup principal

---

## 4. Inverse FVG / IFVG (Wave 7.1)

### Definição oficial LuxAlgo (doc PAC) — **DECISÃO MARCELO**

> *"Inverse fair value gaps are essentially mitigated fair value
> gaps, these can be used to provide retests areas. A mitigated
> bullish FVG will lead to a bearish inverse FVG, where we can
> expect price to retrace upward and retest the area."*

> *"For the sake of efficiency, inverse FVG's are always based on
> the mitigation of the most recent detected FVG, disregarding any
> previous historical FVG that might get mitigated."*

Fonte: `docs.luxalgo.com/.../imbalances`

### Mecânica

```
1. FVG bullish formado em zona X
2. Preço mitiga (atravessa para baixo, fechando além do limite)
3. A zona X agora é IFVG bearish — age como resistência no retest
4. Sinal: candle wick OU close violando a zona original
```

E para o caso espelho (FVG bearish → IFVG bullish).

### Restrição importante

> *"always based on the mitigation of the most recent detected FVG,
> disregarding any previous historical FVG that might get mitigated"*

**Apenas a FVG mais recente** pode gerar IFVG. Simplificação de
eficiência da LuxAlgo. Diverge de literatura ICT pura.

### Diferença vs Pine LuxAlgo `ICT Concepts` free

O Pine `ICT Concepts` implementa IFVG como **primitiva alternativa
de detecção** (toggle exclusivo com FVG). **NÃO ADOTADA** —
decisão Marcelo: seguir PAC paid (transformação no tempo).

### Implementação Wave 7.1

Em `fvg.py`:
- Campo `is_inverse: bool` no UDT `FairValueGap` (hook já existe)
- Campo `inverted_at: int` (timestamp da mitigação que gerou o IFVG)
- Detecção: ao marcar FVG como mitigada, se for a **mais recente**
  do bias correspondente, criar entrada IFVG espelhada
- FVG e IFVG coexistem (mesma zona, momento diferente)

### Implicação para catálogo

- **A4a (IFVG Retest):** baseado neste hook

---

## 5. Double FVG / BPR (Wave 7.2)

### Definição oficial LuxAlgo (doc PAC)

> *"Double Fair Value Gaps, also called balanced price ranges occur
> when the areas of two Fair Value Gaps overlap. The overlapping
> areas highlight a new area of imbalance."*

> *"A bullish Balanced Price Range is determined by a new bullish
> Fair Value Gap area overlapping a previous bearish Fair Value Gap
> area, while a bearish Balanced Price Range is determined by a
> new bearish Fair Value Gap area overlapping a previous bullish
> Fair Value Gap area."*

### Confirmação pelo Pine LuxAlgo `ICT Concepts` (free)

```pine
if i_BPR and bFVG_UP.size() > 0 and bFVG_DN.size() > 0
    bxUP    = bFVG_UP.get(0)   // último FVG bull
    bxDN    = bFVG_DN.get(0)   // último FVG bear

    if bxUPbtm < bxDNtop and bxDNbtm < bxUPbtm
        // BPR bullish: overlap entre as duas zonas
```

**Confirmação:** BPR bullish requer overlap geométrico entre o
**último** FVG bullish e o **último** FVG bearish.

### Implementação Wave 7.2

Em `fvg.py`:
- Campo `is_double: bool` (hook já existe)
- Campo `parent_fvg_ids: tuple[int, int]` (IDs das duas FVGs)
- Detecção: ao formar nova FVG, verificar sobreposição com FVG
  ativa de bias oposto (apenas a mais recente, per LuxAlgo)

### Implicação para catálogo

- **A4b (BPR Retest):** baseado neste hook

---

## 6. Volatility Threshold (Wave 7.x)

### Definição oficial LuxAlgo (doc PAC)

> *"The volatility threshold allows filtering out less significant
> imbalances, with higher values preserving imbalances with a larger
> range."*

> *"The volatility threshold is determined from a volatility
> estimator, the threshold act as a multiplier. Increments of 1
> will return visible results. Floating points can be used."*

### Limitação documental

A LuxAlgo **não publica qual é o `volatility_estimator` exato**
da versão paga. O Pine free relacionado usa "cumulative mean of
FVG heights".

### Implementação Wave 7.x

Em `fvg.py`:
- Parâmetro `volatility_threshold: float = 0.0` (hook já existe)
- Estimador: `cumulative mean of FVG heights` (igual ao free)
- Filtro aplicado **na detecção** — FVG não qualificada nunca
  entra no ledger

### Divergência intencional

Versão paga pode usar variante mais sofisticada (talvez ATR-based).
Documentar como divergência intencional.

### Implicação para catálogo

Não habilita assinatura nova. Melhora qualidade de **todas** as
assinaturas com FVG: A3, A4a, A4b, A6, A7, A11.

---

## 7. Mitigation = Average (Wave 7.x — pacote FVG)

### Definição oficial LuxAlgo (doc PAC)

| Método | Definição verbatim LuxAlgo |
|---|---|
| **Close** | *"Mitigates an imbalance once price close cross above the imbalance upper extremity in the case of a bearish imbalance, and under its lower extremity in case of a bullish imbalance."* |
| **Wick** | *"Mitigates an imbalance once price high cross above the imbalance upper extremity in the case of a bearish imbalance, and when price low cross under its lower extremity in case of a bullish imbalance."* |
| **Average** | *"Mitigates an imbalance once price cross the imbalance area average level."* |
| **None** | *"Will not remove mitigated imbalances."* |

### Implementação Wave 7.x

Em `fvg.py`:
- Adicionar `Average` como opção de mitigação
- Wave 7 já tem Close, Wick, None implementados
- Pacote 7.x adiciona Volatility Threshold + Average mitigation

---

## 8. EQH/EQL fix (Wave 8.1)

### Estado atual

Issue §12.2 do Mapa registra: *"Threshold idêntico (0.1) mas
fórmula efetiva difere"*. Nossa engine produziu 0 alerts; LuxAlgo
mostra alguns visualmente.

### Fórmula obtida do Pine LuxAlgo `ICT Concepts`

```pine
a = 10 / input.float(4, title='margin', step=0.1, minval=2, maxval=7)
atr = ta.atr(10)

// Para cada novo swing high (ph):
count = 0
for i = 0 to math.min(sz, 50) -1
    if aZZ.d.get(i) ==  1                    // só swings highs
        if aZZ.y.get(i) > ph + (atr/a)
            break                              // fora da banda — parar
        else
            if aZZ.y.get(i) > ph - (atr/a) and aZZ.y.get(i) < ph + (atr/a)
                count += 1                     // dentro da banda
                // ... captura level e bar_index

if count > 2                                  // EQH = 3+ swings dentro da banda
    // cria Buyside Liquidity box
```

### Mecânica verbatim

| Componente | Valor/Fórmula |
|---|---|
| ATR | `ta.atr(10)` |
| Margin | input `float(4, minval=2, maxval=7)` (default 4) |
| Banda tolerância | `atr/a` onde `a = 10/margin` (default `a = 2.5`) |
| Lookback | últimos 50 swings (não toda história) |
| Threshold direção | `aZZ.d.get(i) == 1` (só highs para EQH, lows para EQL) |
| Threshold contagem | `count > 2` (3+ swings na banda) |

### Comparação com código atual (Wave 3)

| Aspecto | Wave 3 atual | Pine LuxAlgo |
|---|---|---|
| Threshold | fixo 0.1 (multiplicador estático) | `atr/a` (ATR-adaptivo) |
| Swing mínimo | 2 | 3+ |
| Lookback | toda história | últimos 50 |
| Filtro direção | ambas direções | só same-direction |

### Implementação Wave 8.1

A fórmula resolve o issue §12.2 — não é refinamento de threshold,
é toda a abordagem que diverge.

Detalhe operacional do briefing técnico em documento separado
(`BRIEFING_WAVE_8_1.md`).

---

## 9. Engine MTF (Wave 9.4)

### Escopo

`analyze_multi_tf(df_4h, df_1h, df_15m) → dict[tf, AnalyzeResult]`

Engine roda em N timeframes e retorna dicionário sincronizado.

### Fora do escopo deste documento

Wave 9.4 é puramente arquitetural — não envolve hooks conceituais
LuxAlgo. Briefing técnico em documento separado quando chegar a vez.

---

## 10. Hooks adicionais identificados (FORA DO ESCOPO ATUAL)

Esta seção registra conceitos identificados durante análise dos
Pines mas **não implementados no bloco pré-9.5a**. Servem como
roadmap futuro pós-Onda 10.

### 10.1 OB ATR Size Filter (FluxCharts)

**Conceito:** `if obSize > 3.5 * atr(10): descarta OB`

**Origem:** Pine FluxCharts `Volumized Order Blocks`

**Status:** **Não na PAC paid.** Hook reservado para futuro
refinamento de qualidade de OB. Pode mascarar OBs legítimos em
regimes de alta volatilidade (cripto pós-evento macro).

### 10.2 OB Combination (FluxCharts)

**Conceito:** OBs do mesmo bias que se sobrepõem são mesclados em
OB único combinado com volumes somados.

**Origem:** Pine FluxCharts `Volumized Order Blocks` —
função `combineOBsFunc()`

**Status:** **Não na PAC paid.** Hook reservado. Útil se quisermos
consolidar ledger de OBs muito populoso, mas conceitualmente
contestável (cada OB tem origem temporal própria).

### 10.3 Fibonacci over MSS (DTFX)

**Conceito:** Projeta 5 níveis Fibonacci automaticamente após cada
Market Structure Shift, formando "DTFX zones".

**Origem:** Pine LuxAlgo `DTFX Algo Zones`

**Status:** **Habilita versão simplificada de A10 (OTE)** sem
módulo Fibonacci complexo. Hook reservado para quando A10 for
abordada (pós-9.5c).

### 10.4 Camada IT (Intermediate Term)

**Conceito:** Hierarquia ICT de 3 camadas — ST/IT/LT — em vez das
2 atuais (internal/swing).

**Origem:** Pine LuxAlgo `Pure Price Action Structures` (LuxAlgo
tem indicador separado com 3 camadas, mas PAC paid usa 2).

**Status:** **Não na PAC paid.** Decisão Marcelo: hook reservado.
Wave 3 (mergeada) fica como está. Se em backtest 9.5b surgir caso
claro onde IT melhoraria assinatura, abrir Wave 3.1.

### 10.5 Displacement Filter (ICT Concepts)

**Conceito:** Candle qualificado como "displacement institucional"
exige body > média (10 períodos) E wicks < 36% do body.

**Origem:** Pine LuxAlgo `ICT Concepts`

```pine
L_body = high - mx < body * 0.36 and mn - low < body * 0.36
L_bodyUP = body > meanBody and L_body and close > open
```

**Status:** Hook reservado. Pode substituir parcialmente
`volatility_threshold` em filtro de qualidade FVG ou refinar
detecção de Volumetric OB.

### 10.6 Silver Bullet Sessions / Killzones

**Conceito:** Janelas temporais de atividade institucional (NY,
London Open/Close, Asian, Silver Bullet 3-4 AM / 10-11 AM /
2-3 PM NY).

**Origem:** Pines LuxAlgo `ICT Concepts`, `ICT Silver Bullet`

**Status:** Cripto opera 24/7, mas atividade institucional segue
ondas correlacionadas. Habilita **A7 (Silver Bullet)** quando
abordada. Hook reservado.

---

## 11. Status final dos hooks pendentes — versão 2.0

| Hook | Wave | Fonte canônica | Status |
|---|---|---|---|
| **CHoCH+** | 5.5 | Doc PAC + Pine source público | Definição clara, divergência operacional documentada |
| **Volumetric OB** | 6.1 | Doc PAC + Pine FluxCharts | **Fórmulas obtidas** (declarado FluxCharts como referência) |
| **Mitigation Middle (OB)** | 6.1 | Doc PAC | Definição clara |
| **Breaker Block** | 6.2 | Doc PAC (decisão Marcelo) | Definição clara, confirmada por FluxCharts |
| **IFVG** | 7.1 | Doc PAC (decisão Marcelo) | Definição clara |
| **Double FVG / BPR** | 7.2 | Doc PAC + Pine `ICT Concepts` | Fórmula obtida |
| **Volatility Threshold** | 7.x | Doc PAC | Estimador documentado como divergência |
| **Mitigation Average (FVG)** | 7.x | Doc PAC | Definição clara |
| **EQH/EQL fix** | 8.1 | Pine `ICT Concepts` | **Fórmula obtida** — resolve issue §12.2 |
| **Engine MTF** | 9.4 | Projeto interno | Arquitetural — sem dependência LuxAlgo |

---

## 12. Sequência operacional final

```
Onda 9 ✅ FECHADA (v0.9.0)
  │
  ▼ [6 waves de pré-requisitos]
  ├─ Wave 8.1  — EQH/EQL fix          (1ª, fórmula pronta)
  ├─ Wave 6.2  — Breaker Blocks       (2ª, destrava A6)
  ├─ Wave 7.1+7.2+7.x — pacote FVG    (3ª, IFVG + BPR + Volatility + Avg)
  ├─ Wave 5.5  — CHoCH+               (4ª, multiplicador transversal)
  ├─ Wave 6.1  — Volumetric OB + Mit. Middle  (5ª, fórmulas FluxCharts)
  └─ Wave 9.4  — Engine MTF           (6ª, infra MTF arquitetural)
  │
  ▼
Wave 9.5a — Setup state machine + matcher + A3 com MTF
Wave 9.5b — Catálogo expandido (A1, A4a, A4b, A6, A8, A11)
Wave 9.5c — Persistência + edge cases
Wave 10  — SMCStrategy.py (Freqtrade IStrategy)
```

---

## 13. Catálogo de assinaturas — 11 entradas

| ID | Nome | Tipo | Hook necessário |
|---|---|---|---|
| A1 | OB Retest + CHoCH | Continuação | CHoCH+ opcional como filtro |
| A2 | Sweep + Swing OB Retest | Continuação | 8.1 (EQH/EQL para variante) |
| A3 | Triple Confirmation (OB+FVG+Sweep) | Continuação | — (pronta hoje) |
| A4a | IFVG Retest | Reversão | 7.1 (IFVG) |
| A4b | Double FVG / BPR Retest | Continuação | 7.2 (Double FVG) |
| A5 | Direct OB Tap | Continuação agressiva | Volumetric OB opcional |
| A6 | ICT Unicorn (Breaker + FVG) | Reversão | 6.2 (Breaker) |
| A7 | Silver Bullet (Sweep+FVG window) | Continuação | §10.6 (Sessions — reservado) |
| A9 | EQH/EQL Sweep + CHoCH | Reversão | 8.1 (EQH/EQL fix) |
| A10 | OTE (Fib 62-79%) | Continuação | §10.3 (Fib over MSS — reservado) |
| A12 | Liquidity Run multi-pool | Reversão | 8.1 |

**Total: 11 assinaturas conceituais.** A8 removida (redundante com
A6 — Breaker LuxAlgo).

---

**Fim do documento.**
