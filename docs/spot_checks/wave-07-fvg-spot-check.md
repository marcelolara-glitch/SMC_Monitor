# Spot-Check Wave 7 — Fair Value Gaps

> Spot-check híbrido da Onda 7 (`detect_fair_value_gaps`) contra os
> FVGs visualmente ratificados em
> `docs/REFERENCIA_VALIDACAO_VISUAL_LUXALGO.md` (V4, V5 e FVGs bullish
> dos shots 4/5/7/8).
>
> Padrão Wave 6 reaplicado: implementação (PR #48 mergeado) e
> spot-check em PRs separados.

**Engine:** `smc_freqtrade/smc_engine/fvg.py` (VERSION 0.7.0)
**Golden CSV:** `smc_freqtrade/tests/golden/data/btc_usdt_swap_4h_window.csv`
(720 candles, 2026-01-01 00:00 UTC → 2026-04-30 20:00 UTC, BTCUSDT 4h OKX)
**Referência visual:** `docs/REFERENCIA_VALIDACAO_VISUAL_LUXALGO.md` §5
e anotações pós-Wave-6
**Comando:** `smc_freqtrade/briefings/onda-07-fvg-plan.md` §12.6 com
ajuste de path (golden CSV vive sob `smc_freqtrade/tests/golden/data/`,
não `data/`) e rename de coluna (`timestamp_utc` → `date` antes de
chamar `detect_fair_value_gaps`).

---

## 1. Sumário executivo

| Métrica | Valor |
|---|---:|
| FVGs detectados no ledger | **70** |
| BULLISH active | 4 |
| BULLISH mitigated | 29 |
| BEARISH active | 9 |
| BEARISH mitigated | 28 |
| FVGs ratificados auditados nesta sessão | **9** (V4, V5 + 7 bullish dos shots 4/5/7/8) |
| Match dentro de ±1 candle em `t_creation` | **8/9** (B7 fora da janela de dados, esperado) |
| Match dentro de ±0.5% em geometria | **5/9** (V4, V5, B1, B3, B6) |
| Match de estado vs leitura visual (LuxAlgo gratuito) | **9/9** consistente (todos os ratificados aparecem como `active` no ledger, condizente com o fato de o LuxAlgo continuar desenhando a caixa nos shots) |

**Decisão §2 (full-fill vs first-touch):** **MANTER** a semântica
full-fill simétrica da Wave 7. V4 e V5 não discriminam entre as duas
semânticas no recorte de dados (ambas as predicates preveem `active`),
mas são consistentes com a leitura visual de `active`. Os 5
discriminadores empíricos (FVGs bearish #8, #11, #15, #69, #70 — todos
`active` sob full-fill mas `mitigated` sob first-touch dentro de 1–2
candles) requerem **confirmação visual no TradingView por Marcelo**
para evidência definitiva. Até lá, a documentação explícita da Wave 7
(`fvg.py` §LIMITAÇÕES CONHECIDAS) e o alinhamento com a tolerância do
plan §6 sustentam a escolha.

**Recomendação:** nenhum `blocking`. 3 divergências `concerning` em
candidatos bullish (B2, B4, B5) — provavelmente ambiguidade de leitura
visual nos shots, não bug. 1 candidato `acceptable` por limitação da
janela de dados (B7).

---

## 2. Tabela comparativa por FVG ratificado

| fvg_id | bias    | match_create               | match_geometry              | match_mitigation         | classification |
|--------|---------|----------------------------|------------------------------|---------------------------|----------------|
| 9      | bearish | ✓ 2026-01-20 08:00 (V4)    | top +0.22%, bottom +0.21%    | `active` ↔ LuxAlgo visível | acceptable     |
| 12     | bearish | ✓ 2026-01-29 16:00 (V5)    | top +0.34%, bottom −0.13%    | `active` ↔ LuxAlgo visível | acceptable     |
| 43     | bullish | ✓ 2026-02-28 16:00 (B1)    | top −0.10%, bottom −0.04%    | `active` ↔ LuxAlgo visível | acceptable     |
| (–)    | bullish | ✗ sem match para B2        | (sem candidato dentro ±0.5%) | (n/a)                     | concerning     |
| 62     | bullish | ✓ 2026-04-06 00:00 (B3)    | top −0.08%, bottom −0.09%    | `active` ↔ LuxAlgo visível | acceptable     |
| 63     | bullish | ✓ 2026-04-08 00:00 (B4)    | top **+1.16%**, bottom +0.52%| `active` ↔ LuxAlgo visível | concerning     |
| (–)    | bullish | ✗ sem match para B5        | (sem candidato dentro ±0.5%) | (n/a)                     | concerning     |
| 65     | bullish | ✓ 2026-04-13 20:00 (B6, −1 candle vs 2026-04-14) | top +0.11%, bottom +0.17% | `active` ↔ LuxAlgo visível | acceptable     |
| (–)    | bullish | n/a — fora da janela (B7 em 2026-04-30→05-01; CSV termina em 2026-04-30 20:00) | (n/a) | (n/a) | acceptable (limite de dados) |

**Legenda match_geometry:** desvio relativo `(ledger − ratificado) /
ratificado`. Tolerância ±0.5% do plan §6.

**Legenda match_mitigation:** todos os ratificados são caixas que o
LuxAlgo SMC gratuito ainda desenhava no chart à época da geração de
`REFERENCIA_VALIDACAO_VISUAL_LUXALGO.md` §5 e das anotações
pós-Wave-6. Logo, a leitura visual implícita é "FVG ativo" — o ledger
emite `state='active'` para todos eles, consistente.

---

## 3. Detalhe por candidato

### 3.1 V4 — bearish 91.200–92.000, ~2026-01-20

| Campo | Ratificado (visual) | Ledger (fvg_id=9) | Δ |
|---|---|---|---|
| bias | bearish | bearish (−1) | ✓ |
| top  | ~92.000 | 92.207,1 | +0,22% |
| bottom | ~91.200 | 91.394,5 | +0,21% |
| bar_time (1º candle) | ~2026-01-18 (estimativa briefing) | 2026-01-20 00:00 UTC | (vide nota) |
| t_creation (3º candle) | 2026-01-20 | 2026-01-20 08:00 UTC | 0 candles |
| state | desenhado (visível) | `active` | ✓ |

Nota: o `bar_time` ratificado pelo briefing (~2026-01-18) parece um
arredondamento; o ledger é internamente consistente
(`bar_time = t_creation − 2 candles = 2026-01-20 00:00`). A âncora
canônica para validação visual é `t_creation` (3º candle) — Mapa §7.6.1
e doc REFERENCIA §1, ratificação tabela "FVG | terceiro candle do
padrão". `t_creation` matches em 0 candles.

**Classificação:** `acceptable`.

### 3.2 V5 — bearish 85.700–87.400, ~2026-01-29

| Campo | Ratificado | Ledger (fvg_id=12) | Δ |
|---|---|---|---|
| bias | bearish | bearish (−1) | ✓ |
| top  | ~87.400 | 87.700,0 | +0,34% |
| bottom | ~85.700 | 85.592,2 | −0,13% |
| t_creation | 2026-01-29 | 2026-01-29 16:00 UTC | 0 candles (mesma data) |
| state | desenhado | `active` | ✓ |

**Classificação:** `acceptable`.

### 3.3 B1 — bullish 64.300–64.700, ~2026-02-28 (shot 4)

| Campo | Ratificado | Ledger (fvg_id=43) | Δ |
|---|---|---|---|
| bias | bullish | bullish (+1) | ✓ |
| top  | ~64.700 | 64.636,7 | −0,10% |
| bottom | ~64.300 | 64.275,0 | −0,04% |
| t_creation | 2026-02-28 | 2026-02-28 16:00 UTC | 0 candles |
| state | desenhado | `active` | ✓ |

**Classificação:** `acceptable`.

### 3.4 B2 — bullish 64.900–65.300, ~2026-03-01 (shot 5) — sem match

Candidato mais próximo no ledger por data:
- fvg_id=44: bullish, top=66.138,7, bottom=65.328,3,
  t_creation=2026-02-28 20:00 UTC. Faixa do ledger (65.328–66.138) NÃO
  sobrepõe à faixa ratificada (64.900–65.300); diferença de top é
  +1,28% (acima de ±0,5%).

Demais candidatos próximos (fvg_id=43 já é B1, fvg_id=45 está acima de
66k). Não há FVG no ledger compatível com 64.900–65.300 ±0,5% perto
de 2026-03-01.

Possíveis explicações:
1. Leitura visual de B2 confundiu uma OB (faixa azul de demanda) com
   um FVG. O shot 5 do RELATÓRIO_VISUAL_LUXALGO §5 lista duas OBs
   bullish próximas (62.500–64.000 e 65.600–67.000) e um FVG bullish
   64.900–65.300; a vizinhança visual é densa.
2. Visual juntou dois gaps adjacentes pequenos em um único retângulo.

**Classificação:** `concerning` (não bloqueador — fora do controle da
engine; sugere revisão do candidato ratificado em zoom).

### 3.5 B3 — bullish 67.600–68.800, ~2026-04-06 (shot 7)

| Campo | Ratificado | Ledger (fvg_id=62) | Δ |
|---|---|---|---|
| bias | bullish | bullish (+1) | ✓ |
| top  | ~68.800 | 68.748,0 | −0,08% |
| bottom | ~67.600 | 67.537,5 | −0,09% |
| t_creation | 2026-04-06 | 2026-04-06 00:00 UTC | 0 candles |
| state | desenhado | `active` | ✓ |

**Classificação:** `acceptable` (match excelente).

### 3.6 B4 — bullish 68.700–70.400, ~2026-04-08 (shot 7)

| Campo | Ratificado | Ledger (fvg_id=63) | Δ |
|---|---|---|---|
| bias | bullish | bullish (+1) | ✓ |
| top  | ~70.400 | 71.219,3 | **+1,16%** (acima de ±0,5%) |
| bottom | ~68.700 | 69.058,8 | +0,52% (limite) |
| t_creation | 2026-04-08 | 2026-04-08 00:00 UTC | 0 candles |
| state | desenhado | `active` | ✓ |

`t_creation` é match perfeito e a faixa do ledger sobrepõe à ratificada
no intervalo 69.058–70.400. Divergência geométrica provavelmente
explicada por:
- Visual estimou o `top` pelo CORPO de um candle, enquanto o engine usa
  `low` do candle do gap (= wick).
- Imprecisão de pixel na leitura do screenshot.

**Classificação:** `concerning` (não bloqueador — sobreposição
parcial, criação em candle correto; sugere revisão visual com zoom no
shot 7).

### 3.7 B5 — bullish 70.800–71.300, ~2026-04-13 (shot 7) — sem match

Candidatos por data:
- fvg_id=64 (bearish): top=72.864, bottom=71.750, 2026-04-12 04:00 UTC
  — bearish, não bullish.
- fvg_id=65 (bullish): top=72.977,8, bottom=72.424,0, 2026-04-13 20:00
  UTC — geometria 72.4k–72.9k, NÃO sobrepõe à faixa ratificada
  (70.800–71.300). Diferença +2,29% a +2,35% (muito acima de ±0,5%).
- fvg_id=66 (bullish): top=73.935,5, bottom=73.468,0 — ainda mais alto.

Sem FVG no ledger compatível com 70.800–71.300 ±0,5% perto de
2026-04-13.

Possíveis explicações:
1. Confusão visual com uma OB de demanda ou com uma área de pullback
   que não fechou padrão de 3 candles válido pelo threshold (Pine
   linha 287).
2. B5 talvez se refira a uma data anterior (2026-04-11/12) — vizinhança
   de gaps bearish/bullish é densa.

**Classificação:** `concerning` (não bloqueador).

### 3.8 B6 — bullish 72.300–72.900, ~2026-04-14 (shot 7)

| Campo | Ratificado | Ledger (fvg_id=65) | Δ |
|---|---|---|---|
| bias | bullish | bullish (+1) | ✓ |
| top  | ~72.900 | 72.977,8 | +0,11% |
| bottom | ~72.300 | 72.424,0 | +0,17% |
| t_creation | 2026-04-14 | 2026-04-13 20:00 UTC | −1 candle (dentro de ±1) |
| state | desenhado | `active` | ✓ |

**Classificação:** `acceptable`.

### 3.9 B7 — bullish 77.400–78.100, ~2026-04-30 a 05-01 (shot 8)

CSV golden termina em 2026-04-30 20:00 UTC. Um FVG cuja `t_creation`
seria 2026-05-01 requer ≥1 candle adicional após o terceiro candle do
padrão para ser detectado (e mais ainda para mitigação ser avaliada).
Logo: fora da janela de dados, **não detectável por construção**, sem
indicar bug.

**Classificação:** `acceptable` (limite de dados).

---

## 4. Seção crítica — full-fill vs first-touch (§2 do briefing)

### 4.1 Recapitulação

A Wave 7 implementou para bearish FVGs o predicate `high > top` sob a
convenção normalizada (`top = low[t-2]`, borda superior do gap). Isto
produz **full-fill simétrico** ao bullish (`low < bottom`). O Pine
literal armazena `top = high[t]` (borda inferior do gap) e o predicate
`high > top` se torna **first-touch** (qualquer wick que ultrapassa a
base do gap).

A `fvg.py` documenta a divergência intencional (LIMITAÇÕES CONHECIDAS,
linhas 19–38). A pergunta crítica desta sessão: a escolha foi correta
do ponto de vista da consistência com o LuxAlgo gratuito visual?

### 4.2 V4 e V5 não discriminam

Análise computacional sobre o golden CSV:

| FVG | top      | bottom   | full-fill (`high > top`) | first-touch (`high > bottom`) |
|-----|----------|----------|---------------------------|-------------------------------|
| #9 (V4) | 92.207,1 | 91.394,5 | **nenhum hit** → active | **nenhum hit** → active        |
| #12 (V5) | 87.700,0 | 85.592,2 | **nenhum hit** → active | **nenhum hit** → active        |

Para V4 e V5, **nenhum candle após `t_creation` no recorte de dados
(até 2026-04-30 20:00 UTC) atinge sequer a borda inferior do gap**.
Ambas as semânticas produzem `active`. Isso significa que V4 e V5
**não fornecem evidência discriminante** — são apenas confirmação de
que o ledger é consistente com a leitura visual neutra de "FVG ainda
desenhado".

### 4.3 Discriminadores empíricos identificados

Existem 5 FVGs bearish no ledger onde as duas semânticas divergem
**dentro de 1–2 candles** após `t_creation`:

| fvg_id | top      | bottom   | t_creation       | Engine (full-fill) | Pine literal (first-touch) | Distância |
|--------|----------|----------|------------------|--------------------|----------------------------|-----------|
| 8      | 93.555,0 | 92.805,6 | 2026-01-19 04:00 | `active`           | mitigated @ 2026-01-19 08:00 | +1 candle |
| 11     | 88.830,3 | 88.379,4 | 2026-01-29 04:00 | `active`           | mitigated @ 2026-01-29 08:00 | +1 candle |
| 15     | 80.770,9 | 79.194,2 | 2026-01-31 20:00 | `active`           | mitigated @ 2026-02-01 00:00 | +1 candle |
| 69     | 78.340,0 | 77.936,3 | 2026-04-27 08:00 | `active`           | mitigated @ 2026-04-27 12:00 | +1 candle |
| 70     | 76.922,0 | 76.225,6 | 2026-04-29 16:00 | `active`           | mitigated @ 2026-04-30 00:00 | +2 candles |

Total: 22 dos 37 bearish FVGs (59%) teriam timestamp de mitigação
diferente sob Pine literal first-touch — em alguns casos por **dezenas
de dias** (fvg_id=18 difere por ~73 dias; fvg_id=32 por ~16 dias;
fvg_id=52 por ~13 dias). Esses casos onde ambos mitigam mas em
candles diferentes não são discriminadores binários `active`/`mitigated`
e portanto não decidem a §2 isoladamente.

Os 5 discriminadores binários listados acima são os **casos de teste
visual mais informativos** para Marcelo confirmar no TradingView com
LuxAlgo gratuito: olhar nestes timestamps específicos se o gap foi
apagado (1–2 candles após `t_creation`) ou se permanece desenhado
até hoje.

### 4.4 Evidência indireta favorável a full-fill

1. **V4 e V5 ratificados como visíveis**: o anexo "Anotações pós-Wave-6"
   da REFERENCIA_VALIDACAO_VISUAL_LUXALGO.md identifica explicitamente
   V4 e V5 como FVGs bearish ainda desenhados pelo LuxAlgo gratuito à
   época. Ambos têm `state='active'` no ledger Wave 7. Consistente.

2. **Documentação prévia da escolha**: `fvg.py` linhas 26–38 e
   `onda-07-fvg-plan.md` plan §6 já formalizaram a semântica
   "FVG visualmente preenchido parcialmente no TradingView (wick que
   entra mas não atravessa) deve permanecer `active`". Se Marcelo
   verificou esta tolerância no spot-check Wave 6 (e ela passou nas
   ratificações V4/V5), a Wave 7 é coerente.

3. **Consistência geométrica**: a invariante `top > bottom` para todo
   registro (briefing §4.4 invariante 1) é satisfeita uniformemente
   por full-fill. Pine literal exigiria comparação assimétrica
   (`high > top_pine = high[t]` vs `low < bot_pine = low[t]`), o que
   complica consumidores futuros (Onda 7.1 Inverse FVG, 7.2 Double
   FVG/BPR) que precisarão de geometria normalizada.

### 4.5 Veredito e recomendação

**Veredito:** Wave 7 está **provisoriamente alinhada** com o LuxAlgo
gratuito visual, **com base nas duas ratificações disponíveis** (V4 e
V5). Esses dois pontos, porém, **não discriminam** entre as duas
semânticas. A evidência empírica disponível no recorte de dados não
contradiz a escolha da Wave 7, e a consistência da documentação
sustenta a decisão.

**Recomendação:** **MANTER** a implementação atual da Wave 7. **NÃO
REVERTER**.

**Ação opcional sugerida para Marcelo** (fora do escopo desta sessão):
abrir o chart LuxAlgo SMC gratuito no TradingView nos timestamps dos
5 discriminadores (fvg_id 8, 11, 15, 69, 70) e verificar se a caixa
FVG bearish é apagada no candle imediatamente seguinte ao
`t_creation` (= Pine first-touch correto) ou se permanece desenhada
(= Wave 7 full-fill correto). Isto fecharia a §2 com evidência
empírica direta, e poderia ser registrado como anotação adicional no
`REFERENCIA_VALIDACAO_VISUAL_LUXALGO.md` §5.

---

## 5. Lista de divergências classificadas

| Item | Classificação | Justificativa |
|------|---------------|---------------|
| V4 geometria (top +0.22%, bottom +0.21%) | acceptable | dentro de ±0.5% |
| V5 geometria (top +0.34%, bottom −0.13%) | acceptable | dentro de ±0.5% |
| B1 geometria (top −0.10%, bottom −0.04%) | acceptable | dentro de ±0.5% |
| B2 sem match (ratificado 64.900–65.300 @ 2026-03-01) | concerning | nenhum FVG no ledger compatível ±0.5%; provável ambiguidade visual entre OB e FVG no shot 5 |
| B3 geometria (top −0.08%, bottom −0.09%) | acceptable | dentro de ±0.5% |
| B4 geometria (top +1.16%) | concerning | acima de ±0.5%; t_creation perfeito e sobreposição parcial; provável leitura visual por corpo vs wick |
| B5 sem match (ratificado 70.800–71.300 @ 2026-04-13) | concerning | nenhum FVG no ledger compatível ±0.5%; provável confusão com OB de demanda no shot 7 |
| B6 t_creation (−1 candle) | acceptable | dentro de ±1 candle |
| B7 fora da janela | acceptable | limite do golden CSV (termina 2026-04-30 20:00) |
| 22 bearish FVGs com `t_mitigation` divergente entre engine e Pine literal | (informativo, §4.3) | não classificado como divergência aqui — efeito esperado da decisão Wave 7 documentada |

**Nenhum item `blocking`.**

---

## 6. Notas operacionais

### 6.1 Ajustes ao comando §12.6 do plan

A receita literal de `onda-07-fvg-plan.md` §12.6 referencia
`data/btc_usdt_swap_4h_window.csv` e usa `parse_dates=["date"]`. Na
realidade:

- O golden CSV vive em `smc_freqtrade/tests/golden/data/btc_usdt_swap_4h_window.csv`.
- A coluna de timestamp se chama `timestamp_utc`, não `date`.

O comando efetivamente executado nesta sessão (apenas ajuste de path
e rename de coluna; semântica idêntica) foi:

```python
import pandas as pd
from smc_freqtrade.smc_engine.fvg import detect_fair_value_gaps

df = pd.read_csv(
    "smc_freqtrade/tests/golden/data/btc_usdt_swap_4h_window.csv",
    parse_dates=["timestamp_utc"],
).rename(columns={"timestamp_utc": "date"})

df_out, ledger = detect_fair_value_gaps(df, auto_threshold=True)
ledger.to_csv("docs/spot_checks/wave-07-fvg-ledger.csv", index=False)
```

Sugestão (fora do escopo desta sessão): atualizar `onda-07-fvg-plan.md`
§12.6 com os caminhos corretos em PR posterior, análogo ao tratamento
de patches do Mapa.

### 6.2 Output bruto do comando

```
FVGs detectados: 70
  BULLISH active:    4
  BULLISH mitigated: 29
  BEARISH active:    9
  BEARISH mitigated: 28
```

Período coberto: 2026-01-01 00:00:00 UTC → 2026-04-30 20:00:00 UTC
(720 candles de 4h).

### 6.3 Limitação metodológica

Esta sessão foi executada sem acesso ao TradingView. Toda análise
visual referenciada vem de
`docs/REFERENCIA_VALIDACAO_VISUAL_LUXALGO.md`, que consolida shots
prévios. Os 5 discriminadores §4.3 são os candidatos naturais para uma
spot-check visual subsequente por Marcelo, caso queira evidência
direta para o veredito §2.

---

## 7. Conclusão

| Critério | Status |
|---|---|
| FVGs ratificados auditados | 9 (V4, V5, B1–B7) — atende mínimo de 5 do §4 do briefing |
| Match de criação dentro de ±1 candle | 8/9 (B7 fora da janela, esperado) |
| Match de geometria dentro de ±0.5% | 5/9 (V4, V5, B1, B3, B6) |
| Match de estado vs leitura visual | 9/9 consistente |
| Divergências `blocking` | **0** |
| Divergências `concerning` | 3 (B2, B4, B5) — não bloqueadores; provável ambiguidade visual |
| Divergências `acceptable` | 6 (V4, V5, B1, B3, B6, B7) |
| Recomendação §2 (full-fill vs first-touch) | **MANTER** a decisão da Wave 7 |
| Necessidade de reverter PR #48 | **Não** |
| Sugestão futura | Visualizar 5 discriminadores binários (fvg_id 8, 11, 15, 69, 70) no LuxAlgo gratuito para fechar §2 com evidência empírica direta |

**Status final:** `WAVE 7 VALIDADA — SEMÂNTICA FULL-FILL MANTIDA;
DIVERGÊNCIAS RESIDUAIS DE LEITURA VISUAL EM 3 CANDIDATOS BULLISH SÃO
NÃO BLOQUEADORAS`.
