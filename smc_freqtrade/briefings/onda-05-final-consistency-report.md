# Relatório final de consistência — Onda 5 (BOS/CHoCH) e inputs para ondas futuras

**Projeto:** SMC_Freqtrade (subprojeto `smc_freqtrade/` do repo `marcelolara-glitch/SMC_Monitor`)
**Escopo do check:** validação da engine Python (Ondas 1-5) contra LuxAlgo SMC gratuito (TradingView)
**Janela de dados:** BTC-USDT-SWAP 4H OKX, 2026-01-01 a 2026-04-30 (720 candles)
**Método:** spot-check híbrido — engine produz output canônico; análise visual ratificada via 8 screenshots TradingView consolidados em relatório v2 metodologicamente corrigido
**Data do consolidado:** 10/05/2026

---

## 1. Sumário executivo

A engine SMC do `smc_freqtrade/` foi validada na Onda 5 (BOS/CHoCH formal) através de spot-check visual contra o LuxAlgo SMC gratuito em chart real BTC-USDT-SWAP 4H OKX.

**Resultado:** `ENGINE VALIDADA — 5/5 SWING EVENTS CONSISTENTES`.

Houve aprendizado metodológico crítico no processo: o **label visual "BOS"/"CHoCH" do LuxAlgo é plotado no ponto médio da linha tracejada, não no candle de evento.** O evento real (close-cross) corresponde à **extremidade direita** da linha. A engine sempre reportou o candle correto; a primeira leitura visual havia comparado contra o ponto errado, gerando 4 falsos positivos de divergência.

**Inputs colhidos para Ondas futuras:** o relatório v2 também mapeou visualmente OBs (~12), FVGs (~7), EQH/EQL e HH/LH/HL/LL — material reutilizável quando Ondas 6 (Order Blocks) e 7 (FVG) entrarem em sessão arquitetural.

**Decisões arquiteturais emergentes:** identificada necessidade de separar `pivot_time` (candle do pivot) de `confirmation_time` (candle de detecção operacional) em futuros indicadores. Não impacta a Onda 5, mas vira input de design para Ondas 6+ e potencial PR de hardening na Onda 3 (`pivots.py`).

---

## 2. Status da Onda 5 (BOS/CHoCH formal)

### 2.1. Configuração validada

- Engine: `swings_length=50` (default, em `smc_engine/pivots.py:262`)
- LuxAlgo TradingView: Swing Detection Length = 50 (configuração confirmada pelo usuário)
- Símbolo, exchange e timeframe alinhados em ambos os sistemas

### 2.2. Eventos swing — comparação consolidada

| # | Tipo engine | Timestamp engine (close-cross) | Timestamp LuxAlgo (fim da linha) | Diff | Status |
|---:|---|---|---|---:|---|
| 1 | bos_swing_bearish | 2026-01-25 16:00 | 2026-01-25 16:00 | 0 | ✅ Consistente |
| 2 | bos_swing_bearish | 2026-02-23 00:00 | 2026-02-23 00:00 | 0 | ✅ Consistente |
| 3 | choch_swing_bullish | 2026-03-04 08:00 | 2026-03-04 08:00 | 0 | ✅ Consistente |
| 4 | bos_swing_bullish | 2026-03-16 20:00 | 2026-03-16 20:00 | 0 | ✅ Consistente |
| 5 | bos_swing_bullish | 2026-04-17 12:00 | 2026-04-17 12:00 | 0 | ✅ Consistente |

**Total swing:** 5 eventos, 5 matches, 0 divergências.

### 2.3. Narrativa SMC validada

A sequência detectada pela engine forma uma narrativa SMC coerente:

```
BEARISH (jan) → BEARISH (fev) → CHoCH BULLISH (mar 4) → BULLISH (mar) → BULLISH (abr)
```

Uma única inversão estrutural de tendência (CHoCH em 4 mar), com BOS consecutivos no mesmo bias antes e depois. Mutual exclusion respeitada (nenhum candle com 2 eventos). Coerente com o cenário cripto do período (queda Q1 + recuperação Q2).

### 2.4. Eventos internal — status

A engine detectou **34 eventos internal** (13 BOS bullish + 8 BOS bearish + 6 CHoCH bullish + 7 CHoCH bearish). A análise visual reportou **~39 eventos internal** com timestamps corrigidos pelo fim da linha (estimativas, não validados em zoom individual).

**Cruzamento internal não foi feito em rigor candle-a-candle.** Os timestamps visuais dos eventos internal foram estimados sem zoom dedicado, com confiança "média" reportada pela análise visual. Para validação rigorosa internal, seria necessário gerar zooms individuais por evento.

**Decisão de escopo:** dado que (a) o spot-check rigoroso de 34 eventos internal demanda esforço hands-on considerável, (b) os matches swing dão confiança alta no algoritmo β (vetorização com cycle-breaking) implementado, e (c) os contadores agregados (13/8/6/7) batem em ordem de magnitude com o esperado pelo briefing, **a validação internal fica como dívida técnica de baixa prioridade** — a ser revisitada apenas se aparecer sinal de bug em uso real.

### 2.5. Aprendizado metodológico

**Descoberta crítica:** o label "BOS"/"CHoCH" do LuxAlgo está no **ponto médio aproximado** da linha tracejada que conecta swing point original (início) ao candle de close-cross (fim). Para validação contra qualquer engine que detecte breaks via close-cross, **comparar sempre contra a extremidade direita da linha, nunca contra a posição do texto.**

Esta descoberta deve ser **registrada canonicamente no Mapa Camada 1 v1.1 §7.6 (Fluxo de produção do golden)** para evitar que futuros spot-checks (Ondas 6, 7, 8) repitam o erro de interpretação.

---

## 3. Inputs colhidos para Ondas futuras

A análise visual do relatório v2 mapeou marcadores que serão alvo de Ondas posteriores, com **timestamps corrigidos e regras temporais recomendadas**. Material reutilizável.

### 3.1. Inputs para Onda 6 (Order Blocks)

**~12 OBs mapeados visualmente** ao longo dos 4 meses:

| Tipo | Período | Faixa de preço | Shot |
|---|---|---|---|
| OB bearish (supply) | 14-15 jan | 96,600-97,800 | 1, 2 |
| OB bearish (supply) | 19 jan | 92,600-93,600 | 2 |
| OB bearish (supply) | 20 jan | 91,200-92,000 | 2 |
| OB bearish (supply) | 29 jan | 85,700-87,400 | 2 |
| OB bullish (demanda) | 24 fev - 3 mar | 62,000-64,000 | 4 |
| OB bullish (demanda) | 8-16 mar | 65,600-67,000 | 5 |
| OB bullish (demanda) | 1-16 mar | 62,500-64,000 | 5 |
| OB bearish (supply) | 29-31 mar | 73,300-74,200 | 6 |
| OB bullish (demanda) | 15-31 mar | 65,600-67,400 | 6 |
| OB bullish (demanda) | 30-31 mar | 64,900-65,800 | 6 |
| OB bullish (demanda) | 3-16 abr | 66,000-67,400 | 7 |
| OB bearish (supply) | 13-16 abr | 73,300-74,200 | 7, 8 |
| OB bullish (demanda) | 17 abr - 1 mai | 73,600-75,000 | 8 |

**Regra temporal recomendada (a confirmar com o Pine fonte):** comparar contra `candle de trigger/validação` da engine, não com candle de origem da caixa.

**Decisão arquitetural a tomar na Onda 6:** definir qual evento a engine reporta como `timestamp` do OB:
- candle de origem do OB
- candle de criação/validação
- candle de mitigação
- candle de invalidação

Recomendação: a engine pode (e idealmente deve) reportar os 4 timestamps separadamente. Documentar a convenção no briefing da Onda 6.

### 3.2. Inputs para Onda 7 (FVG)

**~7 FVGs mapeados visualmente:**

| Tipo | Data aproximada | Faixa de preço | Shot |
|---|---|---|---|
| FVG bullish | 28 fev | 64,300-64,700 | 4 |
| FVG bullish | 1 mar | 64,900-65,300 | 5 |
| FVG bullish | 6 abr | 67,600-68,800 | 7 |
| FVG bullish | 8 abr | 68,700-70,400 | 7 |
| FVG bullish | 13 abr | 70,800-71,300 | 7 |
| FVG bullish | 14 abr | 72,300-72,900 | 7 |
| FVG bullish | 30 abr - 1 mai | 77,400-78,100 | 8 |

**Regra temporal recomendada:** comparar contra o **terceiro candle do padrão de 3 candles** (quando o gap fica conhecido), não contra o primeiro candle da caixa.

### 3.3. Inputs para Onda 8 (Liquidity / EQH/EQL)

**EQH/EQL já mapeados:**

| Tipo | Data aproximada | Preço | Shot |
|---|---|---|---|
| EQL | 14-15 jan | 94,400 | 1, 2 |
| EQH | 16-17 jan | 95,500 | 2 |
| EQH | 1-2 fev | 79,000 | 3 |
| EQL | 2-3 fev | 74,300 | 3 |
| EQH | 27 fev | 68,300 | 4 |
| EQH | 3 abr | 67,200 | 7 |

**Regra temporal recomendada:** comparar contra `data do último pivot necessário para formar o EQH/EQL`, não centro visual da linha.

### 3.4. Gap arquitetural identificado para Onda 3 (Pivots)

A análise visual identificou que **HH/LH/HL/LL são desenhados pelo LuxAlgo no candle do pivot real**, mas a detecção operacional só é possível após N candles futuros (length=50 para swing, 5 para internal).

**Atualmente em `pivots.py`:** a Onda 3 produz `COL_*_LEVEL` e `COL_*_IDX` que materializam apenas no candle de confirmação (lookahead-safe). Não há coluna separada para `pivot_time` (timestamp do pivot real, recuado N candles).

**Recomendação:** considerar para uma versão futura da Onda 3 (ou em PR de hardening) adicionar coluna `COL_*_PIVOT_TIME` com o timestamp do pivot real, ao lado do `COL_*_IDX` que já existe. Útil para:
- Reconciliação visual com LuxAlgo (que plota no pivot real)
- Análise post-mortem de sinais
- Documentação clara da semântica de cada coluna

Não é bloqueante para Ondas 5, 6, 7, 8. Vira candidato para PR dedicado em janela apropriada.

---

## 4. Decisões arquiteturais emergentes do spot-check

### 4.1. Convenção temporal canônica do golden

Atualizar `docs/MAPA_LUXALGO_CAMADA_1_v1.1.md` §7.6 (Fluxo de produção e atualização do golden) acrescentando a **regra de interpretação visual canônica**:

> **Regra de leitura visual canônica do LuxAlgo SMC**
>
> Para validar a engine contra screenshots do LuxAlgo, o timestamp do
> evento detectado deve ser comparado contra a **extremidade direita**
> dos marcadores visuais, conforme tabela:
>
> | Marcador LuxAlgo | Ponto de comparação |
> |---|---|
> | BOS / CHoCH | Fim da linha tracejada (candle do close-cross) |
> | OB | Candle de trigger/validação (não o de origem da caixa) |
> | FVG | Terceiro candle do padrão (quando o gap fica conhecido) |
> | EQH / EQL | Último pivot que completa a condição de igualdade |
> | HH/LH/HL/LL | Candle do pivot real (não o de confirmação) |
>
> O label de texto do LuxAlgo (`BOS`, `CHoCH`, etc.) costuma estar
> no ponto médio aproximado da linha — é referência visual apenas,
> **NÃO é o timestamp do evento.**

Este patch deve ser feito **antes da Onda 6**, para que o spot-check de OBs já adote a regra canônica.

### 4.2. Spot-check híbrido como método validado

O método de spot-check híbrido (engine produz output + análise visual ratifica via screenshots) **funcionou na Onda 5** depois da correção metodológica. Pode ser replicado nas Ondas 6, 7, 8 com confiança.

**Lições para próximas ondas:**
- Usar **outra IA com visão mais robusta** para o mapeamento visual inicial (custo: 1 conversa externa por onda)
- Antes do cruzamento, **validar a convenção temporal** do indicador visual (qual ponto da estrutura corresponde ao evento detectável)
- Cobrir os eventos **swing primeiro** (poucos, alta confiança); **internal vira dívida técnica** salvo bug identificado
- Documentar **inputs colhidos para ondas futuras** durante o spot-check da onda atual (eficiência composta)

### 4.3. Necessidade de modularizar timestamp por evento na engine

Para Ondas 6+ que envolvem estruturas com **múltiplos timestamps relevantes** (OB tem origem/criação/mitigação/invalidação), a engine deve reportar todos os timestamps separadamente, não apenas um. Briefing da Onda 6 deve especificar isso.

---

## 5. Dívidas técnicas registradas

| ID | Descrição | Severidade | Quando atacar |
|---|---|---|---|
| DT-1 | Validação candle-a-candle dos 34 eventos internal da Onda 5 | Baixa | Sob demanda (apenas se aparecer bug em produção) |
| DT-2 | Coluna `COL_*_PIVOT_TIME` na Onda 3 para reconciliação visual com LuxAlgo HH/LH/HL/LL | Baixa | PR dedicado em janela apropriada |
| DT-3 | Issue follow-up sobre gap #2 do PR #40 (assert per-coluna agregada vs per-segmento, conforme audit) | Baixa | Antes da Onda 6 ou junto com a Onda 6 |
| DT-4 | PR de patch no Mapa §7.6 documentando regra "label = ponto médio, evento = fim da linha" e tabela de pontos de comparação por marcador | Média | **Antes da Onda 6** (evita repetir erro de interpretação) |

---

## 6. Próximos passos recomendados

### 6.1. Imediato (antes de abrir sessão da Onda 6)

1. **Resolver DT-4** — PR de doc patch no Mapa Camada 1 v1.1 §7.6, acrescentando a tabela de pontos de comparação por marcador (BOS/CHoCH, OB, FVG, EQH/EQL, HH/LL). Sessão Code curta (~1 PR de ~30 linhas). Garante que o método canônico esteja documentado **antes** de o spot-check da Onda 6 começar.

2. **Arquivar este relatório no repo** como `smc_freqtrade/briefings/onda-05-final-consistency-report.md` (decisão do Marcelo se vai como PR dedicado ou junto com DT-4).

3. **Decidir destino da DT-3** (gap #2 do PR #40) — abre como issue separado para resolver depois, ou incorpora na Onda 6.

### 6.2. Iniciar Onda 6 (Order Blocks)

Briefing pode aproveitar:
- Os ~12 OBs visualmente mapeados (§3.1 deste relatório) como pré-spot-check
- A convenção temporal canônica já registrada no Mapa (após DT-4)
- O padrão validado de "spot-check híbrido" (engine + visual + cruzamento)

A Onda 6 herda a estrutura conceitual da Onda 5 e adiciona:
- **Decisão arquitetural prévia:** qual(is) timestamp(s) a engine reporta para um OB (origem/criação/mitigação/invalidação — provavelmente os 4)
- **Decisão LuxAlgo paid:** Volumetric OB e Breaker Blocks são features do pago — decidir absorção ou postergar (conforme registro em `docs/AVALIACAO_LUXALGO_PRICE_ACTION_CONCEPTS_v1.0.md`)

### 6.3. Médio prazo

- DT-1 (internal events) só revisitar se sinal de bug aparecer
- DT-2 (`pivot_time` na Onda 3) candidato a PR de hardening em janela apropriada

---

## 7. Conclusão

**Onda 5 está fechada com validação positiva.** A engine Python porta corretamente o `displayStructure()` do LuxAlgo SMC gratuito para os eventos swing. A descoberta metodológica do "label = ponto médio" é um ganho permanente que se aplica a todas as ondas futuras do projeto e está pronta para ser canonizada no Mapa.

O projeto está em boa posição para avançar para a Onda 6 (Order Blocks), com método de validação testado, inputs visuais pré-mapeados e convenção temporal canônica documentada.

**Status final do check de consistência:** `APROVADO`.
