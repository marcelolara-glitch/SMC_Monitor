# Referência Canônica — Validação Visual LuxAlgo SMC vs Engine Python
> **Documento canônico de referência.** Consultado em todo
> spot-check visual da engine `smc_freqtrade/` contra o indicador
> LuxAlgo Smart Money Concepts (versão gratuita) no TradingView,
> **independentemente da onda em análise**.
>
> Origem: análise da Onda 5 (BOS/CHoCH). As regras temporais,
> tolerâncias e procedimentos aqui descritos aplicam-se
> universalmente a qualquer marcador do LuxAlgo SMC — BOS, CHoCH,
> pivots HH/LH/HL/LL, EQH/EQL, FVG, OB, sweeps, etc.
---
**Símbolo:** BTCUSDT Perpetual Swap Contract  
**Exchange:** OKX  
**Timeframe:** 4h  
**Período analisado (origem):** jan/2026 a abr/2026  
**Indicador:** LuxAlgo Smart Money Concepts — versão gratuita  
**Objetivo:** validar a consistência temporal entre a apuração visual no TradingView e a apuração da engine Python.
---
## 1. Correção metodológica aplicada
No relatório anterior, os timestamps dos eventos **BOS** e **CHoCH** foram lidos pela posição visual do texto `BOS` / `CHoCH` no chart.
A análise posterior com zoom mostrou que, no LuxAlgo SMC, a anatomia visual desses eventos é:
```text
início da linha = swing point original rompido
fim da linha = candle de close-cross / candle que confirma o rompimento
posição do label = ponto médio aproximado entre início e fim da linha
```
Portanto, para fins de validação contra a engine, o timestamp correto do evento **não é a posição do label**, mas sim a **extremidade direita da linha**, isto é, o candle em que o rompimento foi confirmado.
### Regra adotada neste relatório
| Tipo de marcador | Regra temporal usada para consistência com engine |
|---|---|
| BOS | Data de detecção = candle do close-cross, extremidade direita da linha |
| CHoCH | Data de detecção = candle do close-cross, extremidade direita da linha |
| HH / LH / HL / LL | Visualmente o label fica no pivot; para engine, a consistência depende se ela reporta `pivot_time` ou `confirmation_time`. Como pivot exige candles futuros para confirmação, a data de detecção operacional é posterior ao candle do pivot. |
| EQH / EQL | Exigem pelo menos dois pivots. Para detecção operacional, considerar o último pivot/sinal necessário, não o ponto médio visual da linha. |
| FVG | Padrão de 3 candles. Data de detecção = terceiro candle do padrão, quando o gap fica conhecido. |
| OB | A caixa é desenhada no candle de origem, mas a detecção operacional costuma ocorrer depois, quando a estrutura é rompida e o OB é validado. Para consistência, comparar com o candle de validação/trigger da engine, não com a origem da caixa. |
---
## 2. Conclusão executiva
A divergência temporal observada nos eventos swing **não indica bug na engine**.
A engine reporta o timestamp do **close-cross**, que corresponde à extremidade direita da linha BOS/CHoCH no LuxAlgo. A leitura visual anterior havia usado a posição do label, que fica aproximadamente no ponto médio da linha.
**Status:** engine validada para os eventos swing analisados.
---
## 3. Eventos swing — comparação direta Engine vs Visual corrigido
| Evento | Tipo | Preço aprox. | Swing point original / início da linha | Label visual no chart | Close-cross visual / fim da linha | Timestamp engine | Diferença engine vs fim visual | Status |
|---:|---|---:|---|---|---|---|---:|---|
| 1 | BOS bearish | 86,300 | jan/2026, pivot estrutural prévio | n/d no relatório anterior | **2026-01-25 16:00** | **2026-01-25 16:00** | 0 candle | Consistente; swing não havia sido lido como visível no relatório anterior |
| 2 | BOS bearish | 65,100 | 2026-02-12 12:00 a 2026-02-13 00:00 | 2026-02-18 00:00 aprox. | **2026-02-23 00:00** | **2026-02-23 00:00** | 0 candle | Consistente |
| 3 | CHoCH bullish | 70,800 | 2026-02-15 16:00 aprox. | 2026-02-24 00:00 aprox. | **2026-03-04 08:00** | **2026-03-04 08:00** | 0 candle | Consistente |
| 4 | BOS bullish | 73,800 | 2026-03-04 08:00 aprox. | 2026-03-10 12:00 aprox. | **2026-03-16 20:00** | **2026-03-16 20:00** | 0 candle | Consistente |
| 5 | BOS bullish | 76,000 | 2026-03-16 20:00 aprox. | 2026-04-01 20:00 aprox. | **2026-04-17 12:00** | **2026-04-17 12:00** | 0 candle | Consistente |
---
## 4. Eventos BOS/CHoCH — tabela visual revisada para consistência
Esta tabela mantém os eventos identificados visualmente, mas separa:
- **Label visual:** posição aproximada do texto `BOS` / `CHoCH` no TradingView.
- **Data de detecção visual corrigida:** extremidade direita da linha, ou seja, o candle de close-cross.
- **Uso recomendado:** comparar a engine contra a data de detecção corrigida, não contra a posição do label.
> Observação: para eventos internos, a data de detecção corrigida foi estimada visualmente pela extremidade direita das linhas tracejadas. A precisão é menor do que nos eventos swing validados com zoom.
| Shot | Tipo | Scope | Preço aprox. | Label visual aprox. | Data de detecção visual corrigida | Confiança | Observação de consistência |
|---:|---|---|---:|---|---|---|---|
| 1 | CHoCH bullish | internal | 89,300 | 2026-01-01 12:00 | 2026-01-02 00:00 aprox. | média | label fica no meio da linha curta |
| 1 | BOS bullish | internal | 90,600 | 2026-01-03 08:00 | 2026-01-04 04:00 aprox. | média | fim da linha no rompimento à direita |
| 1 | CHoCH bearish | indeter | 86,300 | 2026-01-11 08:00 | indeterminado | baixa | label cortado no rodapé; não usar para validação automática |
| 1 | BOS bullish | internal | 92,500 | 2026-01-12 16:00 | 2026-01-13 08:00 aprox. | média | linha tracejada curta |
| 2 | CHoCH bearish | internal | 94,400 | 2026-01-17 12:00 | 2026-01-19 00:00 aprox. | média | rompimento após consolidação do topo |
| 2 | BOS bearish | internal | 88,100 | 2026-01-24 20:00 | 2026-01-25 16:00 aprox. | alta | coincide com evento swing #1 em nível estrutural próximo |
| 2 | BOS bearish | internal | 85,900 | 2026-01-27 16:00 | 2026-01-29 00:00 aprox. | média | linha até candle forte de queda |
| 3 | BOS bearish | internal | 74,300 | 2026-02-03 00:00 | 2026-02-04 00:00 aprox. | média | linha tracejada termina no rompimento à direita |
| 3 | BOS bearish | internal | 67,700 | 2026-02-10 08:00 | 2026-02-10 20:00 aprox. | média | linha curta |
| 3 | BOS bearish | internal | 65,900 | 2026-02-12 12:00 | 2026-02-13 00:00 aprox. | média | próximo ao início do swing BOS #2 |
| 3 | CHoCH bullish | internal | 68,000 | 2026-02-13 04:00 | 2026-02-13 16:00 aprox. | média | reversão interna |
| 4 | CHoCH bearish | internal | 66,400 | 2026-02-17 16:00 | 2026-02-18 08:00 aprox. | média | linha curta |
| 4 | BOS bearish | swing | 65,100 | 2026-02-18 00:00 | **2026-02-23 00:00** | alta | evento swing #2; engine consistente |
| 4 | CHoCH bullish | internal | 68,000 | 2026-02-20 16:00 | 2026-02-21 08:00 aprox. | média | linha curta |
| 4 | CHoCH bearish | internal | 66,500 | 2026-02-21 16:00 | 2026-02-22 12:00 aprox. | média | linha curta |
| 4 | CHoCH bullish | internal | 68,600 | 2026-02-23 12:00 | 2026-02-24 08:00 aprox. | média | linha tracejada verde |
| 4 | CHoCH bullish | swing | 70,800 | 2026-02-24 00:00 | **2026-03-04 08:00** | alta | evento swing #3; engine consistente |
| 4 | BOS bullish | internal | 68,100 | 2026-03-01 12:00 | 2026-03-02 00:00 aprox. | média | overlap com shot 5 |
| 4 | BOS bullish | internal | 70,000 | 2026-03-02 12:00 | 2026-03-03 12:00 aprox. | média | overlap com shot 5 |
| 5 | BOS bullish | internal | 68,100 | 2026-03-01 12:00 | 2026-03-02 00:00 aprox. | média | aparece também no shot 4 |
| 5 | BOS bullish | internal | 70,000 | 2026-03-03 12:00 | 2026-03-04 08:00 aprox. | média | próximo ao close-cross do CHoCH swing #3 |
| 5 | CHoCH bearish | internal | 65,900 | 2026-03-06 12:00 | 2026-03-08 12:00 aprox. | média | label em ponto médio da linha tracejada |
| 5 | BOS bullish | swing | 73,800 | 2026-03-10 12:00 | **2026-03-16 20:00** | alta | evento swing #4; engine consistente |
| 5 | CHoCH bullish | internal | 71,300 | 2026-03-12 08:00 | 2026-03-13 08:00 aprox. | média | linha curta |
| 5 | BOS bullish | internal | 73,700 | 2026-03-14 12:00 | 2026-03-16 20:00 aprox. | alta | termina próximo ao rompimento estrutural |
| 5 | CHoCH bearish | internal | 70,200 | 2026-03-15 12:00 | 2026-03-17 00:00 aprox. | média | aparece também no shot 6 |
| 6 | BOS bullish | internal | 73,700 | 2026-03-15 12:00 | 2026-03-16 20:00 aprox. | média | label parcialmente cortado; fim próximo ao evento swing #4 |
| 6 | CHoCH bearish | internal | 70,200 | 2026-03-17 00:00 | 2026-03-18 12:00 aprox. | média | linha tracejada vermelha |
| 6 | BOS bearish | internal | 69,200 | 2026-03-21 08:00 | 2026-03-22 12:00 aprox. | média | linha tracejada |
| 6 | CHoCH bullish | internal | 71,000 | 2026-03-22 12:00 | 2026-03-23 08:00 aprox. | média | linha tracejada |
| 6 | CHoCH bearish | internal | 68,700 | 2026-03-25 00:00 | 2026-03-26 12:00 aprox. | média | linha tracejada |
| 6 | CHoCH bullish | internal | 67,300 | 2026-03-29 08:00 | 2026-03-30 08:00 aprox. | média | linha sobre faixa azul de demanda |
| 7 | BOS bullish | swing | 76,000 | 2026-04-01 20:00 | **2026-04-17 12:00** | alta | evento swing #5; engine consistente |
| 7 | BOS bullish | internal | 67,400 | 2026-04-05 08:00 | 2026-04-06 04:00 aprox. | média | linha curta |
| 7 | BOS bullish | internal | 70,400 | 2026-04-07 04:00 | 2026-04-08 00:00 aprox. | média | linha curta |
| 7 | BOS bullish | internal | 72,800 | 2026-04-10 00:00 | 2026-04-10 20:00 aprox. | média | linha tracejada |
| 7 | BOS bullish | internal | 73,800 | 2026-04-12 12:00 | 2026-04-14 08:00 aprox. | média | próximo à zona cinza |
| 7 | BOS bullish | internal | 75,300 | 2026-04-16 12:00 | 2026-04-17 12:00 aprox. | alta | label parcialmente encoberto; fim coincide com swing #5 |
| 8 | BOS bullish | internal | 75,300 | 2026-04-16 08:00 | 2026-04-17 12:00 aprox. | alta | aparece também no shot 7 |
| 8 | BOS bullish | internal | 78,300 | 2026-04-19 20:00 | 2026-04-22 00:00 aprox. | média | linha tracejada |
| 8 | BOS bullish | internal | 78,600 | 2026-04-25 00:00 | 2026-04-27 00:00 aprox. | média | linha tracejada |
| 8 | CHoCH bearish | internal | 77,000 | 2026-04-26 16:00 | 2026-04-28 00:00 aprox. | média | linha tracejada vermelha |
| 8 | BOS bearish | internal | 75,600 | 2026-04-29 12:00 | 2026-04-30 00:00 aprox. | média | linha tracejada vermelha |
| 8 | CHoCH bullish | internal | 77,900 | 2026-04-30 12:00 | 2026-05-01 00:00 aprox. | média | evento no fim do shot; validar em zoom se necessário |
---
## 5. Tabela auxiliar — outros marcadores com regra temporal recomendada
A tabela auxiliar abaixo reaproveita os marcadores complementares do relatório anterior, mas agora adiciona a interpretação temporal recomendada para validação contra a engine.
| Shot | Marcador | Referência visual | Preço / faixa aprox. | Data visual anterior | Data recomendada para consistência com engine | Observação |
|---:|---|---|---:|---|---|---|
| 1 | HH | pivot | 97,800 | 2026-01-14 16:00 | usar `pivot_time` se a engine reporta pivots; usar `confirmation_time` se reporta detecção operacional | HH/LH/HL/LL são pivots, não breaks |
| 1 | EQL | linha entre fundos próximos | 94,400 | 2026-01-14 a 2026-01-15 | último fundo/pivot necessário para formar o EQL | indicador depende de dois pontos |
| 1 | OB bearish | caixa de origem | 96,600–97,800 | 2026-01-14 a 2026-01-15 | candle de validação/trigger do OB, se houver na engine | caixa fica no candle de origem, mas validação ocorre depois |
| 2 | HH | pivot | 97,600 | 2026-01-14 16:00 | pivot ou confirmação, conforme convenção da engine | topo herdado do shot 1 |
| 2 | EQL | linha entre fundos próximos | 94,400 | 2026-01-15 | último pivot necessário | não comparar com centro do label |
| 2 | EQH | linha entre topos próximos | 95,500 | 2026-01-16 a 2026-01-17 | último topo/pivot necessário | exige dois pontos |
| 2 | OB bearish | caixa de origem | 96,800–97,800 | 2026-01-15 a 2026-01-30 | candle de trigger/validação | caixa desenhada no passado |
| 2 | FVG / OB bearish | gap/caixa | 92,600–93,600 | 2026-01-19 | terceiro candle do FVG ou trigger do OB | depende do tipo implementado na engine |
| 2 | FVG / OB bearish | gap/caixa | 91,200–92,000 | 2026-01-20 | terceiro candle do FVG ou trigger do OB | depende do tipo implementado na engine |
| 2 | FVG / OB bearish | gap/caixa | 85,700–87,400 | 2026-01-29 | terceiro candle do FVG ou trigger do OB | queda forte |
| 3 | EQH | linha entre topos próximos | 79,000 | 2026-02-01 a 2026-02-02 | último topo/pivot necessário | exige dois pontos |
| 3 | EQL | linha entre fundos próximos | 74,300 | 2026-02-02 a 2026-02-03 | último fundo/pivot necessário | próximo a BOS bearish |
| 3 | LL | pivot | 59,400 | 2026-02-06 | pivot ou confirmação, conforme convenção da engine | fundo estrutural |
| 3 | LH | pivot | 71,000 | 2026-02-08 16:00 | pivot ou confirmação, conforme convenção da engine | topo de repique |
| 3 | HL | pivot | 64,900 | 2026-02-12 20:00 | pivot ou confirmação, conforme convenção da engine | pivot antes de CHoCH bullish |
| 3 | LH | pivot | 70,800 | 2026-02-15 08:00 | pivot ou confirmação, conforme convenção da engine | topo direito |
| 4 | LL | pivot | 62,600 | 2026-02-24 | pivot ou confirmação, conforme convenção da engine | leitura visual pouco nítida |
| 4 | EQH | linha entre topos próximos | 68,300 | 2026-02-27 | último topo/pivot necessário | exige dois pontos |
| 4 | OB bullish | caixa de origem/demanda | 62,000–64,000 | 2026-02-24 a 2026-03-03 | candle de trigger/validação | grande faixa azul |
| 4 | FVG bullish | gap | 64,300–64,700 | 2026-02-28 | terceiro candle do padrão FVG | gap de 3 candles |
| 5 | HH | pivot | 73,800 | 2026-03-04 12:00 | pivot ou confirmação, conforme convenção da engine | topo local |
| 5 | HL | pivot | 65,300 | 2026-03-08 a 2026-03-09 | pivot ou confirmação, conforme convenção da engine | fundo antes da alta |
| 5 | OB bullish | demanda | 65,600–67,000 | 2026-03-08 a 2026-03-16 | candle de trigger/validação | faixa azul à direita |
| 5 | OB bullish | demanda | 62,500–64,000 | 2026-03-01 a 2026-03-16 | candle de trigger/validação | faixa azul inferior |
| 5 | FVG bullish | gap | 64,900–65,300 | 2026-03-01 | terceiro candle do padrão FVG | pequena caixa verde |
| 6 | HH | pivot | 75,800 | 2026-03-16 | pivot ou confirmação, conforme convenção da engine | topo local |
| 6 | OB bearish | supply | 73,300–74,200 | 2026-03-29 a 2026-03-31 | candle de trigger/validação | caixa cinza |
| 6 | OB bullish | demanda | 65,600–67,400 | 2026-03-15 a 2026-03-31 | candle de trigger/validação | grande faixa azul |
| 6 | LL | pivot | 65,000 | 2026-03-30 | pivot ou confirmação, conforme convenção da engine | fundo de 30 mar |
| 6 | OB bullish | demanda | 64,900–65,800 | 2026-03-30 a 2026-03-31 | candle de trigger/validação | caixa no fundo |
| 7 | EQH | linha entre topos próximos | 67,200 | 2026-04-03 | último topo/pivot necessário | exige dois pontos |
| 7 | OB bullish | demanda | 66,000–67,400 | 2026-04-03 a 2026-04-16 | candle de trigger/validação | grande faixa azul |
| 7 | FVG bullish | gap | 67,600–68,800 | 2026-04-06 | terceiro candle do padrão FVG | gap de alta |
| 7 | FVG bullish | gap | 68,700–70,400 | 2026-04-08 | terceiro candle do padrão FVG | gap de alta |
| 7 | FVG bullish | gap | 70,800–71,300 | 2026-04-13 | terceiro candle do padrão FVG | gap de alta |
| 7 | FVG bullish | gap | 72,300–72,900 | 2026-04-14 | terceiro candle do padrão FVG | gap de alta |
| 7 | OB bearish | supply | 73,300–74,200 | 2026-04-13 a 2026-04-16 | candle de trigger/validação | caixa cinza |
| 8 | OB / zona cinza | supply/demanda visual | 73,600–74,400 | 2026-04-15 a 2026-04-18 | candle de trigger/validação | zona cinza no início do shot |
| 8 | OB bullish | demanda | 73,600–75,000 | 2026-04-17 a 2026-05-01 | candle de trigger/validação | faixa azul inferior |
| 8 | OB bullish | demanda | 74,900–76,300 | 2026-04-29 a 2026-05-01 | candle de trigger/validação | caixa azul menor |
| 8 | FVG bullish | gap | 77,400–78,100 | 2026-04-30 a 2026-05-01 | terceiro candle do padrão FVG | gap na última impulsão |

> **Anotações pós-Wave-6 (2026-05-11):** Duas entradas marcadas
> originalmente como "FVG / OB bearish" foram confirmadas como
> **FVG bearish (não OB)** via spot-check visual da Onda 6 contra
> LuxAlgo gratuito no TradingView:
>
> - Shot 2, faixa 91.200–92.000, 2026-01-20: FVG bearish.
> - Shot 2, faixa 85.700–87.400, 2026-01-29: FVG bearish.
>
> Esses dois pontos servem como ratificação inicial canônica para
> o spot-check da Onda 7 (FVG), análogo ao papel que os 5 swing
> BOS/CHoCH cumpriram para a ratificação da Onda 5.

---
## 6. Sumário de consistência dos eventos swing
| Categoria | Total analisado | Consistentes com engine | Divergentes após correção | Observação |
|---|---:|---:|---:|---|
| BOS bearish swing | 2 | 2 | 0 | inclui evento de jan não lido como swing no relatório anterior |
| CHoCH bullish swing | 1 | 1 | 0 | evento de 04 mar validado pelo fim da linha |
| BOS bullish swing | 2 | 2 | 0 | eventos de 16 mar e 17 abr validados |
| **Total** | **5** | **5** | **0** | engine consistente com o close-cross |
---
## 7. Incertezas remanescentes
| Item | Incerteza | Impacto |
|---|---|---|
| Eventos internos | As datas corrigidas foram estimadas visualmente pela extremidade direita das linhas tracejadas, sem zoom individual de cada evento | Usar como spot-check qualitativo; para validação candle-a-candle, gerar zooms adicionais ou comparar diretamente com output tabular da engine |
| HH/LH/HL/LL | Visualmente aparecem no pivot, mas a detecção de pivot exige candles futuros | Definir se a engine reporta `pivot_time` ou `confirmation_time` antes de comparar |
| EQH/EQL | A linha pode ter label em posição visual intermediária | Comparar pela data do último pivot/sinal necessário |
| OB | Caixa é desenhada no candle de origem, mas validação pode ocorrer depois | Comparar com a regra exata usada na engine: origem, criação, mitigação ou invalidação |
| FVG | Caixa aparece quando o padrão de 3 candles se completa | Comparar com o terceiro candle do padrão, não com o primeiro candle da caixa |
---
## 8. Recomendação para validação automatizada
Para evitar falso positivo de divergência temporal:
1. **BOS/CHoCH**
   - Não usar a posição X do label.
   - Usar a extremidade direita da linha.
   - Comparar com o candle de close-cross da engine.
2. **Pivots HH/LH/HL/LL**
   - Separar dois campos na engine:
     - `pivot_time`: candle onde o pivot ocorreu;
     - `confirmation_time`: candle em que o pivot pôde ser confirmado.
   - Comparar o visual do TradingView com `pivot_time`, mas comparar alertas/detecção operacional com `confirmation_time`.
3. **EQH/EQL**
   - Usar a data do último pivot que completa a condição de igualdade.
   - Evitar usar centro visual da linha.
4. **FVG**
   - Usar o terceiro candle do padrão de 3 candles.
5. **OB**
   - Documentar claramente qual evento a engine chama de `timestamp`:
     - candle de origem do OB;
     - candle de criação/validação;
     - candle de mitigação;
     - candle de invalidação.
   - Para check visual, manter esses eventos separados.
---
## 9. Conclusão final
A revisão corrige a interpretação temporal dos marcadores BOS/CHoCH do LuxAlgo.
A posição do texto `BOS` / `CHoCH` é apenas uma referência visual, posicionada aproximadamente no meio da linha. O evento detectável ocorre na extremidade direita da linha, quando o candle fecha rompendo o nível do swing point original.
**Conclusão:** a engine Python está consistente com o LuxAlgo SMC nos eventos swing analisados.
**Status final:** `ENGINE VALIDADA — DIVERGÊNCIAS TEMPORAIS ANTERIORES ERAM ESPERADAS POR LEITURA DO LABEL, NÃO DO CLOSE-CROSS`.

---

## 10. Backlog de auditorias visuais pendentes (registrado, não-bloqueante)

1. **FVG base (Onda 7):** 5 fvg_ids discriminadores (8, 11, 15, 69, 70) vs.
   TradingView (LuxAlgo gratuito) — confirma bearish full-fill vs. first-touch
   (§7.10 #1 do Mapa Camada 1).
2. **BPR (Onda 7.2):** spot-check de **formação** das 2 BPRs do golden contra
   `ICT Concepts [LuxAlgo]` (`i_BPR=true`). Divergência de membros é esperada
   (§7.10 #3 do Mapa); conferir geometria das coincidentes, não a contagem.

---

## 11. Nota de poder estatístico — CHoCH+ swing no golden 4h

O poder discriminante do **CHoCH+ swing** no golden 4h é **n=1** (único swing
CHoCH na janela, que virou "+"; nenhum contra-exemplo swing). Validação
substantiva do escopo swing depende do smoke sintético (Caso A/C do
`test_smoke_wave5_5.py`) + leitura de código, não do golden. O escopo
**internal** tem n=5 (4 ratificados + 1 divergência #699), validação adequada.
