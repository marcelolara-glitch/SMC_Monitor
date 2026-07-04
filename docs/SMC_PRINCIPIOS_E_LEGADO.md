# SMC Monitor — Legado, Princípios e Aprendizados

> **Status do projeto:** o sistema próprio (`main.py` + `signals.py` + `tracker.py` + 8 módulos de apoio) foi descontinuado em abril de 2026, após Check Up técnico revelar problemas estruturais de modelagem. Este documento preserva o aprendizado e estabelece princípios que devem orientar qualquer futuro sistema SMC, dentro ou fora deste repositório.
>
> **Próxima fase:** subprojeto `smc_freqtrade/` neste mesmo repositório, com freqtrade como base de infraestrutura e lógica SMC implementada como `IStrategy` customizada. O sistema legado é preservado em `legacy/` para referência.
>
> **Última atualização:** 2026-07-03 — **Revisão v2.0** (Fase A Parte 1: proposta P0–P10
> ratificada integralmente pelo Marcelo; evidência e fontes em
> `docs/RELATORIO_FASE_A_PARTE1_CONCEITUAL.md`).
>
> **Convenção [v2.0]:** requisitos marcados com `[v2.0]` foram introduzidos nesta revisão e
> **não descrevem o comportamento histórico do código**. Na auditoria da Fase A Parte 2,
> divergência código↔conceito em item `[v2.0]` classifica-se como *lacuna esperada*;
> divergência em item sem a marca classifica-se como *candidato a bug de fidelidade*.
>
> **Revisão v2.1 (2026-07-04):** resolução da tensão G6 (gate direcional das reversões) e
> incorporação da evidência da Fase A Parte 2 (`docs/RELATORIO_FASE_A_PARTE2_FIDELIDADE.md`,
> `docs/ADENDO_FASE_A_PARTE2_MEDICAO_2Y.md`). Marcas `[v2.1]` seguem a mesma convenção.

---

## Parte 1 — Por que este documento existe

### 1.1 O contexto da virada

O SMC Monitor foi construído ao longo de 13 passos roadmap, desde abril de 2026, como daemon Python rodando 24/7 em VM Oracle Cloud, monitorando BTC-USDT-SWAP via WebSocket OKX, com lógica de confluência SMC sobre 5 critérios pontuáveis e 2 gates direcionais. Versão lógica final em produção: v0.1.11.

O sistema funcionava do ponto de vista de software (uptime de 4+ dias, persistência sem corrupção, comunicação Telegram fluente), mas apresentou desempenho operacional anômalo após o Check Up de abril: 35 dos 36 sinais emitidos em 5 dias terminaram em `timed_out`, com indícios de que o `tracker.py` não realizava forward simulation real, com sinais sendo "resolvidos" no mesmo instante de emissão. Análise mais profunda revelou que isso não era apenas conjunto de bugs corrigíveis — era sintoma de **modelagem conceitualmente equivocada do que é "um sinal SMC"**.

A modelagem original tratava sinal como snapshot de score atingido em candle close. A modelagem correta — confirmada pela literatura SMC e por especialistas operando manualmente — trata sinal como **um setup armado esperando confirmação dentro de uma zona**. A diferença é fundamental e propaga-se por toda a arquitetura.

Em vez de remendar o sistema atual, optamos por:

1. Encerrar o sistema próprio, preservando o código no Git como acervo
2. Adotar **freqtrade** como infraestrutura (chassi e motor)
3. Reescrever apenas a inteligência SMC como `IStrategy` customizada
4. Validar via backtesting de 1-2 anos antes de qualquer dry-run ou live

Esta decisão foi tomada após análise honesta de make vs buy. Construir nosso próprio motor de backtesting, gestão de ordens, persistência de trades, dashboard e Telegram — equivalente ao que freqtrade oferece pronto — exigiria mais 2-3 meses de trabalho que não geram edge competitivo. O edge mora na **lógica de decisão SMC**, não na infraestrutura.

### 1.2 Como usar este documento

Este documento é **referência viva**, não histórico arquivado. Deve ser consultado:

- Antes de qualquer briefing para Claude Code envolvendo lógica SMC
- Quando uma nova conversa com Claude começar e precisar de contexto rápido
- Quando dúvidas sobre modelagem voltarem (e voltam, é da natureza humana e de LLMs)
- Antes de tomar decisões arquiteturais novas

A Parte 8 ("Instruções para Claude") é especialmente importante — destina-se a ancorar conversas futuras com Claude (que não terão memória desta) e prevenir derivas conceituais.

---

## Parte 2 — O modelo conceitual correto de SMC em automação

### 2.1 SMC é narrativa sequencial, não checklist de confluência

**Princípio.** Em SMC, a presença simultânea de OB, FVG, sweep e BOS no estado atual do mercado **não é** sinal. O que importa é a **sequência causal**: smart money cria liquidez (range), faz sweep para acumular contra retail, e depois desloca preço gerando OB+FVG. Se você emite sinal toda vez que esses elementos co-existem sem checar a ordem em que apareceram, está pescando ruído.

**Por que isso importa.** O sistema legado tratava os 5 critérios como pontuação independente: `ob_active + fvg_adjacent + sweep_recent + bos_choch_15m + trend_1h_aligned`. Score 3+ emitia. Resultado: 21 sinais com score 3 (sem sweep, sem BOS) e 15 com score 4 (sem sweep) — ou seja, 100% dos sinais sem o catalisador clássico do SMC. Isso é diagnóstico de modelagem errada, não de threshold mal calibrado.

**Como fazer certo.** A modelagem deve verificar **transições** entre estados, não estados isolados. Sweep precisa ter ocorrido **antes** da formação do OB que se observa agora. BOS no 15m precisa ter ocorrido **depois** que o preço retornou à zona do 1H. Ordem temporal é parte do critério.

### 2.1.1 As duas famílias de setup [v2.0]

A literatura contém duas arquiteturas de entrada distintas, ambas legítimas. O canônico passa
a declará-las, e cada assinatura do catálogo (Parte 9) é etiquetada com a sua:

- **Família I — Retest de POI pré-existente.** Uma zona (OB/FVG) já formada em TF maior espera
  o retorno do preço; o sweep atua como qualificador de qualidade. É a família que a máquina de
  estados da Parte 3 modela: a zona existe antes, o setup ARMED existe antes do gatilho.
- **Família II — Zona-nascente (modelo-2022).** O sweep dispara um MSS com deslocamento, e a
  zona de entrada **nasce desse impulso** (o FVG/OB criado pelo displacement). Não existe setup
  antes do sweep, porque a zona ainda não existe; ARMED só pode surgir pós-sweep. Sequência
  canônica: sweep → MSS com displacement → retração à zona do impulso → entrada.

Fontes: modelo-2022 como sequência nomeada sweep→MSS→FVG (tradingview.com/script/SD8VyvVg,
tradingfinder.com/education/forex/ict-mentorship-2022-model, fxnx.com); retest de POI
(innercircletrader.net/tutorials/ict-order-block). Detalhe e grau de consenso:
`docs/RELATORIO_FASE_A_PARTE1_CONCEITUAL.md` §1-F1, §4-E-1/E-3, §5.

### 2.2 Zona de entrada é armadilha, não preço

**Princípio.** Um operador SMC profissional nunca pensa "entrar em 75720". Pensa "se o preço retornar à zona 75600-75850 (que é meu OB), e nesse retorno o 15m mostrar uma ChoCH bullish + rejeição (vela com pavio inferior longo + close forte), aí entro". A entrada é **um evento condicional dentro de uma zona**, não um número.

**Por que isso importa.** O sistema legado calculava `entry` como ponto único (FVG midpoint ou OB top), gerando sinais onde `entry_low == entry_high` em 36/36 casos. Pior: o entry vinha de evento histórico (FVG formado dias atrás), enquanto o SL vinha do `swing_low` atual do 1H. Os dois valores não conversavam temporalmente. Resultado: sinais LONG com `sl_price > entry_mid` em 35/36 casos — matematicamente sem sentido para a direção.

**Como fazer certo.** Uma zona é um intervalo de preço que delimita um OB ou FVG. Enquanto preço estiver fora da zona, setup está apenas **armado**. Quando preço entra na zona, setup vira **pending confirmation**. A entrada acontece no preço da **vela de confirmação**, não em ponto pré-calculado. SL é ancorado na **estrutura que define a zona** (mínima do OB para LONG), não em swing-lows soltos do timeframe.

### 2.3 Liquidity Sweep é catalisador, não pontuação

**Princípio.** Sweep não é "mais um critério que aumenta confiança". É o **catalisador** que diferencia uma zona "esperando" de uma zona "já caçou stops e está pronta para reverter". Sem sweep, você está entrando contra inércia — possível, mas trade de baixa qualidade que um especialista filtraria.

**Por que isso importa.** No sistema legado, `sweep_recent` apareceu em apenas 1 dos 36 sinais. Os outros 35 foram emitidos sem o catalisador clássico. Isso é estatisticamente impossível de ser correto — o gate deveria ter bloqueado.

**Como fazer certo.** Sweep deve ser tratado como **gate condicional** com diferenciação de qualidade:

- **Setup A+ (premium):** sweep recente na direção contrária + retorno à zona = trade de alta probabilidade
- **Setup B (standard):** sem sweep mas zona forte (OB com volume alto + FVG limpa + trend macro firme) = entrada apenas com confirmação extra no 15m
- **Não-setup:** sem sweep e zona fraca = ignorar, não emitir

**Leitura por família [v2.0].** Na Família II (§2.1.1) o sweep é estágio obrigatório por
definição — sem ele não há setup, de nenhuma qualidade. A diferenciação A+/B acima aplica-se à
Família I, e é uma **síntese declarada** deste projeto (alternativa legítima na literatura, não
consenso): o default do modelo-2022 é sweep-obrigatório, e modelos de retest de POI sem sweep
existem condicionados a viés HTF. Registro do espaço: RELATORIO Fase A Parte 1, §4-E-3.

### 2.4 Multi-timeframe é hierarquia decisória, não AND lógico

**Princípio.** Os timeframes não votam com pesos iguais. Cada um tem **função específica** na decisão:

- **4H define direção.** Trend 4H bullish? Procuro apenas LONG. Bearish? Apenas SHORT. Neutro? Estou de fora. **Não vota no score, só direção.**
- **1H define a zona.** Onde está a próxima zona de demanda/oferta institucional? OB com FVG é a melhor. Sem zona ativa, espero — sem inventar zona em outro TF.
- **15m dispara a entrada.** ChoCH no 15m **dentro da zona do 1H** é a condição de entrada. Sem isso, não há trade. **Não vota no score — decide o "quando".**

**Por que isso importa.** O sistema legado tratava 4H/1H/15m como AND lógico que somava pontos. Resultado: o gate 4H ficou travado em "bullish" mesmo quando a estrutura local mudou, gerando 100% LONG em 5 dias de mercado lateral — estatisticamente impossível.

**Como fazer certo.** Cada TF é uma "camada" do funil decisório, com função única:

```
4H bullish? → SIM → procurar zona LONG no 1H
                   ├─ Sem zona ativa → setup ARMED não existe
                   ├─ Zona ativa, preço fora → setup ARMED, observar
                   └─ Zona ativa, preço dentro → setup PENDING_CONFIRMATION
                                                  ├─ Sem ChoCH 15m → continuar pending
                                                  └─ ChoCH 15m + rejeição → setup CONFIRMED → entrar
```

**Hierarquia com duas saídas [v2.0].** No corpus ICT, o timeframe alto entrega **direção e
alvo**: além do viés, ele define o *draw on liquidity* — o pool de liquidez oposto
não-mitigado para onde o preço tende a ser entregue (ver §2.9). A máquina de estados atual
consome apenas a direção; o alvo-HTF é função declarada da hierarquia ainda não modelada.
Fontes: backtrex.com/en/blog/ict-market-structure-shift-mss-guide;
tradezella.com/learning-items/ict-model-4.

**Escopo do gate direcional [v2.1 — resolução G6].** O gate de viés 4H do funil acima é
obrigatório para as assinaturas de **continuação**. Assinaturas de **reversão** (A4a, A6,
A9) declaram sua relação com o viés na Parte 9; a decisão ratificada é **independência do
viés 4H** — a reversão opera na virada local, e o viés swing-4H flipa ~21 vezes em 2 anos
(adendo §3), tarde demais para gatear a virada. A variante alinhada-ao-viés fica registrada
como espaço de calibração (hyperopt sob gate treino/OOS), não como doutrina.

### 2.5 Invalidação é tão importante quanto entrada

**Princípio.** Setups morrem o tempo todo. Um especialista deleta setups com naturalidade. Se preço passou da zona sem voltar, ou voltou mas sem confirmação, ou confirmou mas o contexto macro mudou — o setup morre. Sistema sem invalidação acumula "zumbis" que parecem ativos mas são lixo.

**Por que isso importa.** O sistema legado mantinha sinais "vivos" por 24h independente do que o mercado fazia. Em alguns clusters, 5 sinais idênticos foram emitidos consecutivamente porque o setup persistia (sem o preço chegar a testá-lo) — todos terminaram em timeout sem nem perto de bater SL ou TP. Era ruído amplificado.

**Como fazer certo.** Critérios de invalidação explícitos para cada estado:

- **ARMED → invalidado** se OB/FVG mitigado, se preço escapou >2% acima/abaixo da zona sem voltar, ou se 6h sem atividade
- **PENDING_CONFIRMATION → invalidado** se preço atravessou a zona inteira sem confirmar, ou se contexto macro 4H mudou direção, ou se N candles 15m sem confirmação (timeout)
- **CONFIRMED → trade ativo**, com SL e TP estruturais. Saída por SL, TP, ou trailing.

---

### 2.6 Displacement é critério de validade, não filtro opcional [v2.0]

**Definição.** Displacement é o movimento impulsivo que evidencia participação institucional:
candle(s) com corpo maior que a média dos últimos N corpos e wicks pequenos relativo ao corpo
(fórmula de referência já registrada em `CONCEITOS_LUXALGO_HOOKS.md §10.5`, do Pine
`ICT Concepts [LuxAlgo]`: `body > meanBody` e wicks `< 0.36 * body`), idealmente deixando FVG.

**Regras.** (i) Um MSS/ChoCH usado como **confirmação de entrada** só é válido se a quebra
ocorre com displacement. (ii) Um **OB estratégico** (§2.10) só é válido se seguido de
displacement. CHoCH estrutural puro sem deslocamento continua existindo como evento de
estrutura — mas não qualifica confirmação de entrada.

Fontes: backtrex.com (o impulso que valida o MSS quase sempre cria imbalance);
thesimpleict.com/ict-displacement-explained-2025 (OB sem displacement não é pegada
institucional); strike.money/technical-analysis/order-block;
tradingstrategyguides.com/day-5-order-blocks-explained; e a operacionalização de terceiros do
Anexo A (`profittown-sniper-smc`: "Impulse from OB caused BOS" como condição dura).

### 2.7 Premium/Discount, Dealing Range e OTE [v2.0]

**Dealing range.** O range de referência do ICT é o swing low↔high do **impulso relevante** —
tipicamente o movimento pós-raid que quebrou estrutura — e não um extremo trailing de longo
prazo. Equilibrium (EQ) = 50% do dealing range. **LONG só em discount (abaixo do EQ), SHORT só
em premium (acima do EQ), relativo ao dealing range.**

**OTE.** Faixa 62%–79% da retração do impulso, ponto central 70,5%. Requisitos de validade:
a retração precisa **cruzar o EQ** (retração até 40% não arma OTE); o nível sozinho não é
trade — exige **confluência** (OB/FVG dentro da faixa) e **confirmação**; invalidação
estrutural = fechamento além do 100% (origem do swing); SL além do 100% com buffer; alvos
preferenciais nas extensões −0.27/−0.62 ou liquidez oposta (§2.9).

**Distinção de implementação.** A engine deriva um P/D de *trailing extremes* (porta LuxAlgo —
`MAPA_LUXALGO_CAMADA_1_v1.1.md §6-Onda 4`). São **âncoras diferentes** que produzem zonas
diferentes. O canônico estratégico adota o dealing range; cada filtro/assinatura declara na
Parte 9 qual âncora consome. A convivência das duas âncoras é decisão documentada, não bug.

Fontes: innercircletrader.net/tutorials/ict-fibonacci-levels e
/ict-optimal-trade-entry-ote-pattern; ictflow.com/blog/ict-optimal-trade-entry-ote;
tradingstrategyguides.com/understanding-ict-optimal-trade-entry-ote; fxnx.com.

### 2.8 Tempo como dimensão do modelo [v2.0]

No corpus ICT, tempo (killzones/sessões) é **filtro transversal de qualidade** — condiciona
todos os modelos, não uma assinatura. Janelas herdadas (horário de NY): London open 3–4h,
NY AM 10–11h, NY PM 14–15h.

**Decisão de adaptação a cripto (explícita):** essas janelas foram calibradas para FX/índices.
Em perpétuos cripto 24/7 seu valor é **hipótese experimental**, não fato — será decidida por
medição (backtest estruturado com/sem gate temporal), nunca por doutrina. Até lá: cada
assinatura declara na Parte 9 sua sensibilidade a tempo — **obrigatória** (A7, por definição) /
**qualificadora** (usável como filtro de qualidade opcional) / **nenhuma**.

Registro honesto do espaço: parte da comunidade trata OTE como retração pura, não time-based
(discussão em innercircletrader.net/tutorials/ict-optimal-trade-entry-ote-pattern). Fontes da
posição majoritária: tradingfinder.com (alinhamento com sessões como marca do 2022);
forexfactory.com/thread/1342719 ("trade exclusivamente na kill zone" para OTE);
grandalgo.com/blog/ict-silver-bullet-strategy (janela não-negociável na SB);
thesimpleict.com (session timing como filtro de qualidade do displacement).

### 2.9 Alvos: draw on liquidity [v2.0]

O alvo primário do corpus é **liquidez oposta não-mitigada** (old/session highs-lows, EQH/EQL)
— o *draw on liquidity* definido no TF alto. Framework alternativo ancorado: extensões de
Fibonacci −0.27/−0.62 sobre o swing do impulso.

**Removido do modelo conceitual:** o antigo TP2 = *retracement* 0.618 (escolha sem âncora no
corpus — ICT usa extensões negativas e pools, não retrações como alvo). Se o código atual o
utiliza, reclassifica-se como escolha de engenharia declarada (§2.11) até decisão do Briefing 2.
Escada de parciais e BE-após-TP1 permanecem como gestão idiossincrática declarada (§2.11).

Fontes: tradezella.com/learning-items/ict-model-4 (alvos em liquidez externa);
fxopen.com/blog/en/what-is-the-ict-silver-bullet-strategy;
innercircletrader.net/tutorials/ict-fibonacci-levels (extensões);
innercircletrader.net/tutorials/ict-breaker-block-trading (TP no próximo pool).

### 2.10 OB primitivo vs OB estratégico [v2.0]

**OB primitivo (LuxAlgo).** Vela de extremo (`parsed_low`/`parsed_high`) na janela
`[pivot_idx, break_idx)`. É e continua sendo a referência de **match do golden dataset** — a
política de fidelidade do `MAPA_LUXALGO_CAMADA_1_v1.1.md §7.9` fica **integralmente
preservada**: quando a engine bate com o LuxAlgo gratuito e diverge do dogma, a engine está
correta *como primitivo*.

**OB estratégico (ICT).** A **última vela oposta antes do displacement** (última de baixa
antes do impulso de alta, e vice-versa), válido apenas com: displacement subsequente (§2.6),
estrutura/liquidez tomada pelo impulso, e alinhamento com o viés HTF.

**Ponte.** São camadas distintas com funções distintas: o primitivo valida a portagem; o
estratégico define zona de entrada. Cada assinatura declara na Parte 9 qual semântica consome.
Divergências engine↔dogma no nível do primitivo continuam regidas pelo MAPA §7.9.

Fontes: innercircletrader.net/tutorials/ict-order-block; strike.money;
blog.trinitytrading.io/order-blocks-ict-trading-guide-2026; Anexo A (`smc_quant`: "last
opposing candle before a major move").

### 2.11 Escolhas de engenharia declaradas (sem âncora externa) [v2.0]

Os itens abaixo **não têm âncora no corpus** — são engenharia deste projeto: calibráveis,
não-dogma. A Fase A Parte 2 audita **presença e coerência de implementação**, nunca "correção"
contra fonte inexistente. Valores finais serão decididos por hyperopt sob gate out-of-sample.

- Escape >2% da zona (invalidação ARMED); timeout 6h (ARMED); N candles 15m (PENDING).
- Parametrização do sweep: X%·ATR de ultrapassagem e janela temporal (núcleo
  wick-beyond-close-back tem âncora; os parâmetros não).
- Gestão: BE após TP1; escada de parciais 20-30/40-50/20-30; R:R mínimo 1:2 (corpus oscila
  entre 1:2 e 1:3).
- **Conjunção de confirmação "ChoCH 15m + vela de rejeição":** o consensual no corpus é
  MSS/CISD como gatilho, com padrão candlestick (rejeição/engolfo) como **alternativa** — a
  conjunção obrigatória dos dois é composição deste projeto (precedente de risco: a modelagem
  original da A3). Mantida como escolha declarada; revisão pertence ao Briefing 2.

### 2.12 Escopo de liquidez [v2.0]

Pools modelados hoje: **EQH/EQL** (threshold ATR) — um **subconjunto** do espaço do corpus.
Pools não-cobertos, registrados para roadmap (não são requisito das assinaturas atuais):
PDH/PDL, highs/lows de sessão, old highs/lows semanais, trendline liquidity.
Fontes: backtrex.com; forexfactory.com/thread/1347627;
innercircletrader.net/tutorials/ict-silver-bullet-strategy.

---

## Parte 3 — A máquina de estados de um setup SMC

### 3.1 Os cinco estados

```
┌────────────────────────────────────────────────────────────────┐
│                        ARMED                                   │
│  Zona detectada (OB+FVG) com contexto macro 4H alinhado.       │
│  Preço está FORA da zona. Sistema observa, não alerta.         │
└────────────────────────────────────────────────────────────────┘
                          │
                          │ preço entra na zona
                          ▼
┌────────────────────────────────────────────────────────────────┐
│                  PENDING_CONFIRMATION                          │
│  Preço dentro da zona. Sistema observa o 15m esperando         │
│  ChoCH bullish (LONG) ou bearish (SHORT) + vela de rejeição.   │
└────────────────────────────────────────────────────────────────┘
                          │
                  ┌───────┴───────┐
                  │               │
        ChoCH +   │               │   N candles
        rejeição  │               │   sem confirmação
                  ▼               ▼
┌──────────────────────┐    ┌──────────────────────────────┐
│      CONFIRMED       │    │       INVALIDATED            │
│  Sinal real emitido. │    │  Setup morto. Não emite.     │
│  Trade ativo com SL  │    │  Razão registrada para       │
│  e TP estruturais.   │    │  análise (escape, timeout,   │
└──────────────────────┘    │  mitigação, etc.)            │
        │                   └──────────────────────────────┘
        │
   ┌────┴────┐
   │         │
   ▼         ▼
┌──────────────┐
│   RESOLVED   │
│  SL hit, TP  │
│  hit, ou     │
│  timeout.    │
└──────────────┘
```

### 3.2 Transições e gatilhos

| De | Para | Gatilho |
|---|---|---|
| (vazio) | ARMED | OB+FVG detectados em zona não mitigada, com contexto 4H alinhado |
| ARMED | PENDING_CONFIRMATION | preço entrou na zona (entre OB top e bottom) |
| ARMED | INVALIDATED | OB/FVG mitigado OU preço escapou >2% sem entrar OU 6h sem atividade |
| PENDING_CONFIRMATION | CONFIRMED | ChoCH 15m + vela de rejeição na direção do trade |
| PENDING_CONFIRMATION | INVALIDATED | preço atravessou a zona inteira OU N candles 15m sem confirmar OU trend 4H mudou |
| CONFIRMED | RESOLVED | SL hit, TP hit, ou timeout configurado |

**Escopo desta máquina [v2.0].** O diagrama e a tabela acima modelam a **Família I** (§2.1.1):
a zona existe antes, ARMED existe antes do gatilho. Para a **Família II**, a máquina tem um
pré-estado implícito — nenhum setup existe antes do sweep; a zona (FVG/OB do impulso) nasce no
MSS pós-sweep e só então o fluxo PENDING → CONFIRMED se aplica por analogia. A formalização de
uma FSM-II é trabalho pós-Fase A; **não implementar por antecipação** (anti-over-engineering).

### 3.3 Por que essa modelagem e não outra

A modelagem alternativa que adotamos no sistema legado — score de confluência sobre estado atual — falha porque:

1. **Trata SMC como conjunto de indicadores estatísticos**, não como narrativa de fluxo institucional
2. **Não diferencia "zona armada" de "trade executável"** — emite alertas para ambos como se fossem a mesma coisa
3. **Não tem mecanismo de invalidação granular** — depende de timeout cego de 24h
4. **Mistura ordem temporal nos cálculos** — entry de evento histórico com SL de evento atual

A modelagem por máquina de estados resolve cada um desses problemas:

1. Cada estado representa uma **fase da narrativa**, com transições explícitas
2. Setup ARMED nunca alerta; só CONFIRMED gera sinal de trade
3. Cada estado tem critérios próprios de invalidação
4. Entry é calculado **no momento da confirmação** com preço atual; SL é ancorado na estrutura que define a zona — temporalmente coerentes

### 3.4 Modelos de entrada: Risk vs Confirmation

A literatura SMC reconhece dois modelos de entrada legítimos, que correspondem a estados diferentes da máquina:

**Risk Entry (entrada antecipada):**
- Trader coloca ordem **limit** quando setup ainda está ARMED
- Ordem dispara automaticamente se preço retornar à zona
- Vantagem: melhor preço de entrada, R:R potencialmente maior
- Desvantagem: pode ser executada sem confirmação real (false setup)
- **Equivale a:** transição direta ARMED → CONFIRMED quando preço entra na zona

**Confirmation Entry (entrada confirmada):**
- Trader espera setup chegar a PENDING_CONFIRMATION
- Só entra quando ChoCH 15m + rejeição materializa-se
- Vantagem: maior probabilidade de trade ganhador
- Desvantagem: preço pior, R:R menor, possibilidade de não confirmar e perder o trade
- **Equivale a:** fluxo completo ARMED → PENDING_CONFIRMATION → CONFIRMED

A estratégia ideal usa **ambos hibridamente**: Risk Entry como ordem primária (limit) e Confirmation Entry como fallback caso o Risk Entry seja stopado. Para uma primeira versão automatizada, recomenda-se começar **apenas com Confirmation Entry**, pois é mais conservador e o backtest é mais confiável.

---

## Parte 4 — Aprendizados do sistema legado (o que NÃO fazer)

### 4.1 Bug 1: scanner disfarçado de monitor

**Sintoma.** Em 5 dias, 36 sinais emitidos. Distribuição: 35 timed_out (97.2%), 1 tp1_hit (2.8%), 0 sl_hit. Volume de sinais incompatível com a tese original ("monitor de poucos tokens com profundidade").

**Causa raiz.** O sistema avaliava confluência **a cada candle close** e emitia se threshold fosse atingido. Como a configuração SMC (OB+FVG+trend) persiste por horas ou dias após formada, o sistema reemitia o mesmo setup repetidamente. Em um cluster, 5 sinais idênticos foram emitidos em 1 hora.

**Lição.** Monitor SMC não emite sinais a cada candle. Emite sinais em **transições de estado**: quando setup vira CONFIRMED, ponto. Estado ARMED pode persistir 6 horas sem gerar uma única notificação. Frequência de emissão alta é red flag, não feature.

### 4.2 Bug 2: cálculo entry vs SL temporalmente incoerente

**Sintoma.** 35 dos 36 sinais LONG tinham `sl_price > entry_mid` — SL acima do entry para uma posição comprada. Matematicamente sem sentido.

**Causa raiz.** `entry` vinha de `matched_fvg["midpoint"]` (FVG potencialmente formado dias antes) e `sl_price` vinha de `state_1h.get("swing_low") - buffer` (swing_low atual do 1H). Os dois valores não conversavam temporalmente. Quando o preço subia muito desde a formação do FVG, o swing_low atual já estava acima do midpoint antigo.

**Lição.** Em uma única decisão de trade, **todos os preços de referência precisam ser temporalmente coerentes**. Entry, SL e TP devem vir do mesmo momento estrutural. Se entry é "zona limit no FVG histórico", SL é "abaixo do swing_low que **delimita** esse FVG", não swing_low solto do mercado atual.

### 4.3 Bug 3: dedup que não acumula

**Sintoma.** A tabela `signal_emission_tracking` tinha 1 linha após 36 emissões. Deveria ter ~6-8 linhas (uma por setup único).

**Causa raiz.** A função `record_emission` em `state.py` parece ter feito DELETE+INSERT em vez de UPSERT, ou o `key_hash` mudava sutilmente a cada candle por imprecisão decimal. Não foi auditado em profundidade porque a decisão de migrar tornou-se prioritária.

**Lição.** Dedup por hash de zona requer normalização rigorosa dos valores (truncamento de casas decimais consistente, ordem fixa de campos). Em sistema novo, prefira dedup por **identidade de setup** (state machine ID único por setup ativo) em vez de hash de range — é mais robusto.

### 4.4 Bug 4: tracker que não simulava forward

**Sintoma.** Em todos os timed_out, `resolved_at_ts` era idêntico ao `emitted_at_ts` (diferença em segundos, não horas), e `resolved_price` era essencialmente o preço do momento da emissão. No único `tp1_hit`, `resolved_at_ts` foi 15 minutos **antes** da emissão — fisicamente impossível.

**Causa raiz.** `tracker.py` (Passo 10) parece ter sido descontinuado ou desabilitado em algum dos refactors do Passo 13 (PRs A/B1/B2/B3/C), e a marcação de status passou a ser feita "no momento da emissão" sem real forward simulation candle-by-candle.

**Lição.** Forward simulation é função crítica que **não pode ser silenciosamente quebrada por refactor**. Em freqtrade, isso é responsabilidade do framework (gerencia trade lifecycle, SL/TP on exchange), eliminando essa classe inteira de bugs.

### 4.5 A causa raiz comum

Todos os 4 bugs acima compartilham uma origem: **a modelagem de "sinal" como snapshot pontual no candle close**, em vez de **fase de um ciclo de vida**.

Snapshot puro implica:
- Recalcular tudo a cada candle (gera reemissão)
- Tratar entry e SL como cálculos independentes (gera incoerência temporal)
- Não persistir identidade de setup (gera dedup frágil)
- Marcar resolução no mesmo instante (não há forward simulation real, porque não há "futuro" no modelo)

A modelagem por máquina de estados (Parte 3) elimina essa classe inteira de bugs por construção, não por correção pontual.

---

## Parte 5 — Princípios operacionais para futuros sistemas SMC

### 5.1 Antes de modelar pipeline, modelar como o especialista pensa

**Erro a evitar.** Começar pelo "como detecto OB e FVG" e depois adicionar regras de combinação. Isso produz scanner com mais critérios, não monitor que opera como especialista.

**Abordagem correta.** Antes de escrever qualquer linha de código, descrever em prosa simples como um trader SMC profissional decide entrar em um trade. Em que ordem ele observa as coisas. Quais são seus critérios de descarte. Como ele decide que um setup morreu. Quanto tempo ele espera. Esse texto vira a especificação da máquina de estados.

**Sinal de alerta:** se a especificação fala em "score" antes de falar em "transições" e "ciclo de vida", está modelando errado.

### 5.2 Backtesting não é opcional — é a primeira prova

**Erro a evitar.** Acreditar que "se a lógica está correta no papel, vai funcionar". O sistema legado tinha modelagem aparentemente coerente (5 critérios + 2 gates), mas só descobrimos que estava errada após 5 dias rodando em produção e analisando 36 sinais em pós-mortem.

**Abordagem correta.** Backtest contra 1-2 anos de dados históricos é a primeira validação. Se a estratégia não sobrevive a backtest com Sharpe > 1.5 e drawdown < 25%, **ela não é colocada em dry-run**. Se não sobrevive a dry-run de 30 dias com performance similar ao backtest, **ela não vai a live**. Cada gate filtra por ordem de magnitude.

**Custo de pular essa etapa:** 5 dias de produção = 36 sinais ruins emitidos no Telegram = nenhuma decisão de trade real possível com aquele dataset.

### 5.3 Lookahead bias: o erro silencioso que destrói estratégias SMC

**Risco específico.** A função `swing_highs_lows` da biblioteca `smartmoneyconcepts` (e equivalentes em outras libs) precisa de candles **antes E depois** do swing para confirmá-lo. Se você usa o resultado naive no backtest, está usando informação que não estaria disponível em produção. Backtest fica espetacular; live é catastrófico.

**Detecção.** Freqtrade tem comando `lookahead-analysis` que detecta esse bug automaticamente. **Toda estratégia SMC implementada em freqtrade DEVE passar por essa análise antes de qualquer dry-run.**

**Mitigação na escrita.** Usar parâmetros como `swing_length=N` com cuidado, sempre testando se o uso do resultado respeita o "tempo presente" do candle em avaliação. Quando em dúvida, atrasar deliberadamente o uso do indicador por N candles equivalente ao lookback.

### 5.4 Custos reais devem estar no cálculo desde o dia 1

**Erro a evitar.** Backtest sem taxas, sem funding fees, sem slippage. Estratégia que dá 5% ao mês com R:R 1.5 vira -2% ao mês quando você desconta:

- **Taxa de exchange:** ~0.05% maker, ~0.1% taker, em cada entrada e saída (= ~0.2% por round-trip)
- **Funding rate** (perpetual swap): ~0.01% a cada 8 horas em condições normais, mas pode chegar a 0.1%+ em volatilidade alta
- **Slippage:** variável, mas em mercado normal de BTC algo como 0.05-0.1% por execução

**Custo combinado:** ~0.3-0.5% por round-trip em condições normais. Estratégias que não têm edge bruto de pelo menos 1.5% por trade médio **não cobrem custos**.

**Implicação prática.** Configurar freqtrade com `fee` realista no backtest (não 0). Verificar que estratégia dá lucro **após** custos, não antes.

---

## Parte 6 — Decisão arquitetural: por que freqtrade

### 6.1 Make vs buy: o que a decisão real envolveu

A pergunta que a discussão revelou não foi "o sistema tem bugs?" — é "qual o objetivo do projeto?".

Se o objetivo fosse **aprender a construir um sistema de trading do zero**, manter o sistema próprio e iterar fazia sentido. Veículo de aprendizado.

Se o objetivo é **operar um sistema que gere edge real em SMC**, construir e manter infraestrutura própria desperdiça tempo em problemas resolvidos. Tempo que deveria estar sendo gasto em **modelagem SMC** e **calibração de estratégia** estava sendo gasto em WebSocket reconnect, SQLite schema, async logging, dedup hashing, Telegram polling.

A decisão de migrar para freqtrade é **alinhamento entre objetivo declarado e meio escolhido**. O sistema próprio era um meio que servia ao objetivo errado.

### 6.2 O que freqtrade resolve por nós

| Componente | Sistema legado | Freqtrade |
|---|---|---|
| Conexão exchange (WebSocket + REST) | `ws_feed.py` (custom) | nativo via CCXT |
| Persistência de candles | `candle_buffer` table | nativo |
| Persistência de trades | `signal_lifecycle` table | nativo (Trade model) |
| Reconexão automática | parcial (não testado) | nativo, robusto |
| Dry-run com dinheiro fictício | inexistente | nativo |
| Backtesting histórico | inexistente | comando dedicado |
| Hyperopt (otimização paramétrica) | inexistente | nativo |
| Lookahead bias detection | inexistente | comando dedicado |
| Multi-pair (BTC, ETH, etc.) | não implementado | configuração |
| Telegram bot | `bot_handler.py` (custom) | nativo |
| Dashboard web (FreqUI) | inexistente | nativo |
| Gestão de SL/TP on-exchange | não implementado | nativo (suporte por exchange) |
| Cálculo de funding rate | não implementado | nativo (com caveats) |
| Cálculo de fees realista | não implementado | nativo |

### 6.3 O que continua sendo trabalho nosso

**A inteligência SMC.** Toda a lógica conceitual da Parte 2 e Parte 3 deste documento precisa ser implementada como `IStrategy` customizada. Especificamente:

- `populate_indicators`: rodar `smartmoneyconcepts` lib (que já usamos) sobre o dataframe e adicionar colunas (`ob_top`, `ob_bottom`, `fvg_top`, `fvg_bottom`, `bos_15m`, `swing_low_1h`, etc.)
- Lógica de máquina de estados em colunas auxiliares: `setup_state` (armed/pending/confirmed/invalidated), `setup_id` (identidade do setup)
- `populate_entry_trend`: dispara entrada quando `setup_state` transita para "confirmed" no candle atual
- `custom_stoploss`: SL estrutural ancorado no OB/swing original do setup
- `populate_exit_trend`: lógica de TP estrutural (próximo swing high para LONG, próximo swing low para SHORT)
- Calibração de parâmetros via `hyperopt`

**Estimativa:** 3-4 semanas de trabalho focado em modelagem SMC, após 1-2 semanas de setup e familiarização com freqtrade.

### 6.4 Caveats conhecidos do freqtrade com OKX

Confirmados via documentação oficial e issues do GitHub (abril 2026):

1. **OKX é suportado oficialmente** para perpetual swap (`BTC/USDT:USDT` em notação CCXT)
2. **Apenas isolated margin** — `cross` para futures não é suportado em freqtrade 2026.3 (validado empiricamente em 2026-04-26 contra OKX, comportamento inverso ao reportado na issue #11478 de março/2025). Para 1 pair, irrelevante na prática.
3. **One-way mode** recomendado (não hedge mode). Configuração feita na conta OKX antes de iniciar bot.
4. **Backtest preciso apenas nos últimos ~3 meses** — antes disso, MARK candles ausentes geram leve imprecisão em funding fees. Workaround: `futures_funding_rate: 0` no config para janelas mais longas, com aproximação aceitável.
5. **Position mode não pode ser trocado mid-trading** — se trocar, o bot trava.

Nenhum desses é bloqueador. Todos são contornáveis.

---

## Parte 7 — Expectativas calibradas

### 7.1 Bot de trade não é renda passiva no curto prazo

Esta seção existe como contrapeso ao otimismo. Vai ser relida em momentos de frustração.

**O que a literatura e comunidade documentam:**

- A **maioria** das pessoas que monta bot de trade em crypto perde dinheiro ou empata com taxas, mesmo com sistemas tecnicamente bem feitos
- Estratégias que funcionam têm **vida útil limitada** (3-12 meses tipicamente) porque o mercado muda regime
- "Rodar e esquecer" não funciona — sistemas que sobrevivem exigem **iteração constante** (semanal a mensal)
- Capital de partida importa: com US$ 500-1000, custos comem boa parte do edge mesmo de estratégias decentes

**Implicação realista:** os primeiros 6 meses são **investimento de aprendizado**, não geração de renda. Quem entra esperando renda imediata desiste no primeiro drawdown.

### 7.2 O ciclo de aprendizado realista

| Fase | Duração | Capital | Objetivo |
|---|---|---|---|
| Fase 1 — Validação | 1-2 semanas | US$ 0 | Setup freqtrade, primeiro backtest com estratégia trivial, validar OKX dry-run |
| Fase 2 — Estratégia SMC própria | 3-4 semanas | US$ 0 | Implementar máquina de estados, primeiro backtest SMC, hyperopt |
| Fase 3 — Dry-run estendido | 1 mês | US$ 0 | 30 dias em paper trading, comparar com backtest |
| Fase 4 — Live com capital de aprendizado | 2-3 meses | US$ 500-1000 | Validar em mercado real com perda tolerável |
| Fase 5 — Escalar ou pivotar | mês 6+ | variável | Decisão informada com dados reais |

**Total até decisão informada: 4-6 meses, custo monetário US$ 0-1000 (tolerável a perda total na Fase 4).**

### 7.3 Métricas de sucesso por fase

**Fase 2 (backtest SMC):**
- ✅ Sharpe ratio > 1.5
- ✅ Max drawdown < 25%
- ✅ Win rate > 40% combinado com R:R médio > 1.5
- ✅ Profit factor > 1.3
- ✅ Sobrevivência a `lookahead-analysis`
- ✅ Lucro positivo **após** custos realistas (fee 0.1%, slippage 0.05%)

**Fase 3 (dry-run):**
- ✅ Performance dry-run em até ±30% da projeção do backtest
- ✅ Trades disparam quando esperado (signals consistentes)
- ✅ Sem crashes, OOM, ou degradação ao longo de 30 dias

**Fase 4 (live):**
- ✅ Perda mensal não excede 10% do capital alocado
- ✅ Padrão de trades operacionais consistente com dry-run
- ✅ Aprendizado documentado (o que diferiu da projeção e por quê)

Métricas mais agressivas que essas no início são red flag de overfit ou de sorte que não se reproduz.

---

## Parte 8 — Instruções para Claude (sessões futuras)

> Esta seção destina-se ao Claude (eu) em sessões futuras sem memória desta. Se você é Claude lendo isto agora em outra conversa, **leia com atenção**. Estes princípios foram destilados de uma conversa cara em tempo, esforço e tokens. Não os ignore.

### 8.1 Princípios que devem ser tratados como dogma

A menos que o Marcelo apresente evidência forte e específica em sentido contrário, trate o seguinte como **assumido e não-negociável**:

1. **A inteligência SMC mora em uma máquina de estados** (ARMED → PENDING_CONFIRMATION → CONFIRMED → RESOLVED, com INVALIDATED transversal). Não proponha modelos de "score de confluência" ou "AND lógico de critérios". Esses já foram testados e falharam.

2. **Liquidity Sweep é gate, não pontuação.** Setup A+ exige sweep recente; Setup B aceita ausência de sweep mas exige confirmação extra; sem zona forte e sem sweep, não-setup. Não trate sweep como "+1 no score".

3. **4H define direção, 1H define zona, 15m dispara entrada.** Cada timeframe tem função única. Não some pesos entre eles.

4. **Entry, SL e TP devem ser temporalmente coerentes.** Se entry vem de evento histórico (FVG midpoint), SL deve vir do swing que **delimita** esse FVG, não swing solto do mercado atual.

5. **Backtest contra 1-2 anos é prerequisito antes de qualquer dry-run.** Sem backtest com Sharpe > 1.5 e drawdown < 25%, estratégia não avança de fase.

6. **`lookahead-analysis` do freqtrade é obrigatório antes de qualquer dry-run.** SMC tem alto risco de lookahead bias por causa de `swing_highs_lows` precisar de candles futuros para confirmar swings.

7. **Custos realistas no backtest são obrigatórios.** Fee mínima 0.1%, slippage mínimo 0.05%. Estratégia que só dá lucro sem custos não é estratégia.

8. **A infraestrutura é freqtrade, não sistema próprio.** Não proponha reescrever WebSocket, persistência, gestão de ordens. Esse caminho foi explicitamente descartado em abril 2026.

9. **[v2.0] Displacement é critério de validade** (§2.6) — MSS de confirmação e OB estratégico
   sem deslocamento não qualificam entrada. Não trate displacement como filtro opcional.

### 8.2 Sinais de alerta — quando você (Claude) está derivando

Se você se pegar fazendo qualquer uma destas coisas, **pare e releia este documento**:

- Sugerindo "vamos calibrar o threshold do score" → você voltou ao modelo de scanner. SMC não é score-based.
- Propondo "vamos adicionar mais um critério de confluência" → mais critérios não corrigem modelagem errada. Volte para máquina de estados.
- Aceitando como adequado "sinal emitido a cada candle close se condições persistirem" → frequência alta de sinais é red flag, não feature.
- Calculando entry de evento A com SL de evento B sem checar coerência temporal → bug clássico do legado, não repita.
- Modelando "tracker" como módulo separado que simula forward → freqtrade faz isso nativamente. Não reimplemente.
- Sugerindo backtest opcional ou "depois se preocupa com isso" → backtest é primeira validação, não última.
- [v2.0] Auditando um parâmetro da §2.11 "contra a literatura" → esses itens não têm âncora;
  são engenharia declarada. Audita-se presença e coerência, calibra-se por hyperopt sob gate
  out-of-sample.

### 8.3 Perguntas a fazer antes de propor solução

Quando o Marcelo trouxer um problema novo, **antes** de propor solução, faça (mentalmente ou explicitamente) estas perguntas:

1. **Qual estado da máquina está envolvido?** O problema é em ARMED, PENDING_CONFIRMATION, CONFIRMED, ou em transição entre eles? Se a resposta não couber em estados, você está modelando errado.

2. **A solução proposta preserva coerência temporal?** Se você está calculando dois preços, ambos vêm do mesmo momento estrutural?

3. **Já validei que não é problema da inteligência (estratégia) sendo confundido com problema de infraestrutura?** Se for de infra, freqtrade já resolve. Se for de inteligência, é nosso trabalho.

4. **Posso propor backtest antes de propor implementação?** Em quase todos os casos, a resposta é sim. Backtest é mais barato que código novo.

5. **Esta solução tem expectativa realista?** Se você está sugerindo algo que "vai dar 10% ao mês", você está derivando. Releia Parte 7.

### 8.4 Comportamento quando o Marcelo questiona

O Marcelo é inteligente, paciente, e identifica buracos lógicos em raciocínios — incluindo nos meus. Quando ele questionar uma proposta sua:

- **Não defenda automaticamente.** Releia a crítica dele. É comum ele estar certo.
- **Não capitule também automaticamente.** Se você tem razão técnica, explique por quê.
- **Reconheça erros explicitamente.** "Você está certo, eu inverti causa e efeito" é resposta legítima e construtiva. Não escorrega para "agradeço a observação" sem corrigir.
- **Quando em dúvida, traga dados.** Search, código, números. Não opinião.

---

## Parte 9 — Catálogo conceitual das assinaturas [v2.0]

> Especificação conceitual mínima de cada assinatura implementada. Complementa (não substitui)
> a tabela de hooks de `CONCEITOS_LUXALGO_HOOKS.md §13`. Campos: **família** (§2.1.1),
> sequência, zona, confirmação, **semântica de OB** consumida (§2.10), **tempo** (§2.8),
> direção. Requisitos desta Parte são `[v2.0]` por inteiro: divergência código↔spec aqui é
> *lacuna esperada* na Parte 2, salvo onde o requisito já constava do canônico anterior.

**A1 — OB Retest + CHoCH** · Família I · continuação. OB ativo alinhado ao viés 4H → preço
retorna à zona → confirmação por MSS/CHoCH **com displacement** (§2.6) no TF menor. Semântica
de OB: estratégica (§2.10) como conceito; a zona operacional atual vem do primitivo LuxAlgo —
divergência de semântica a classificar na Parte 2. Tempo: qualificadora. Direção: OB de alta →
long; de baixa → short, a favor do viés.

**A2 — Sweep + Swing OB Retest** · Família I com catalisador (fronteira com a II) ·
continuação. Sweep de liquidez → retorno ao swing OB ativo → confirmação. Tempo:
qualificadora. Direção: reversão-do-sweep alinhada ao viés.

**A3 — Triple Confirmation (OB+FVG+Sweep)** · Família I, grau A+ · continuação. Confluência
intra-zona (OB e FVG sobrepostos) + sweep prévio → retorno → confirmação conforme §2.11
(conjunção declarada). Tempo: qualificadora.

**A4a — IFVG Retest** · Família I · reversão · viés 4H: independente [v2.1 — G6, calibrável]. FVG mitigado inverte o papel (definição PAC);
retest da zona invertida com confirmação; a inversão vale com displacement no rompimento
(§2.6). Tempo: qualificadora. Direção: a do papel invertido.

**A5 — Direct OB Tap** · Família I, modo Risk Entry (§3.4) · continuação agressiva. Toque na
zona sem confirmação LTF; exige zona de qualidade (volumetric como qualificador opcional).
Tempo: qualificadora.

**A6 — Unicorn (Breaker + FVG)** · fronteira I/II · reversão · viés 4H: independente [v2.1 — G6, calibrável]. Sequência do breaker: sweep no
extremo do OB → falha do OB (close além do extremo, não wick) → MSS confirmando → zona =
sobreposição breaker+FVG do movimento que o quebrou → retest. Direção: a do breaker. Fonte:
innercircletrader.net/tutorials/ict-breaker-block-trading. Tempo: qualificadora.

**A7 — Silver Bullet** · Família II · **decisão adotada: variante majoritária** — dentro da
janela (§2.8): sweep de liquidez → **MSS com displacement** → **primeiro FVG criado pelo
impulso** → entrada no retest do FVG. Tempo: **obrigatória** (a janela define a assinatura;
deslocamento fora da janela não é Silver Bullet). Direção: reversão-do-sweep alinhada ao viés
diário — o rótulo "continuação" do catálogo de hooks refere-se ao viés, não ao sweep. Alvo:
liquidez oposta da sessão. **Variante minoritária registrada** (sweep+FVG sem MSS explícito —
corresponde à formulação anterior do catálogo e à implementação atual): fluxcharts.com. Fontes
da majoritária: grandalgo.com; fxnx.com; tradingfinder.com/education/forex/ict-silver-bullet.

**A9 — EQH/EQL Sweep + CHoCH** · Família II · reversão · viés 4H: independente [v2.1 — G6, calibrável]. Sweep de EQH/EQL → CHoCH com
displacement (§2.6) → entrada. Tempo: qualificadora. Direção: reversão-do-sweep.

**A10 — OTE** · Família II (a retração arma sobre o impulso do MSS — coerente com o hook DTFX
§10.3) · continuação do impulso. Spec integral em §2.7: dealing range do impulso; retração
cruza o EQ; entrada na faixa 62–79% (70,5% central) **com confluência OB/FVG e confirmação**;
SL além do 100%; alvos conforme §2.9. Tempo: qualificadora (janela 8:30–11h NY citada no
corpus; status experimental — §2.8).

**Não-especificadas aqui:** A4b, A11 (reservada), A12 — sem implementação; permanecem apenas
na tabela de hooks até entrarem em onda própria.

---

## Anexo A — Repositórios e referências estudados

**Bibliotecas de detecção SMC (utilizadas):**
- `joshyattridge/smart-money-concepts` (PyPI: `smartmoneyconcepts==0.0.27`) — base de cálculo SMC, ~1.5k stars
- Variantes (não recomendadas): `tpwilo/smc`, `smtlab/smartmoneyconcepts`, `sailoo121/ss_smc`, `Prasad1612/smart-money-concept`

**Bots SMC com decisão (referência conceitual):**
- `starckyang/smc_quant` — padrão "detect FVG → locate OB → wait for retracement → enter"
- `manuelinfosec/profittown-sniper-smc` — fluxo sequencial `detect_bos → detect_order_block → is_perfect_ob → place_limit_order`. **[v2.0] Rebaixado para "amostra de operacionalização":** o README promete performance ("$1k → $3k per day") e falha o critério de confiabilidade para expectativa; aproveitável apenas para estrutura de regra.
- `ilahuerta-IA/mt5_live_trading_bot` — não-SMC, mas exemplo claro de máquina de estados (`SCANNING → ARMED → WINDOW_OPEN → ENTRY`)

**Plataforma adotada:**
- `freqtrade/freqtrade` — ~35k stars, base de infraestrutura escolhida

**Documentação oficial relevante:**
- https://www.freqtrade.io/en/stable/strategy-101/ — tutorial introdutório
- https://www.freqtrade.io/en/stable/strategy-customization/ — referência da `IStrategy`
- https://www.freqtrade.io/en/stable/backtesting/ — comando de backtest
- https://www.freqtrade.io/en/stable/leverage/ — modos futures, margin
- https://www.freqtrade.io/en/stable/exchanges/ — notas específicas OKX
- https://docs.freqtrade.io/en/2025.1/strategy_analysis_example/ — análise de resultados

**Conceitual SMC (referências teóricas):**
- ICT (Inner Circle Trader) — fonte primária dos conceitos
- LuxAlgo SMC — implementação visual amplamente referenciada
- Documento conceitual do projeto: "Análise Técnica: Smart Money Concepts (SMC) em Criptomoedas e Automação"

**[v2.0] Padrão de grading de fontes externas (adotado na Fase A):** T1 quase-primária
(documentação dedicada ao material ICT) / T2 secundária técnica (guias com método explícito) /
T3 vendor-blog. Fontes que prometem performance ficam desqualificadas como âncora de
expectativa (aproveitáveis só para estrutura de regra). Afirmações sustentadas apenas por
convergência T2/T3 recebem no máximo [Provável]. Lista completa de fontes, grading e
divergências entre fontes: `docs/RELATORIO_FASE_A_PARTE1_CONCEITUAL.md` §2 e §8.

---

## Anexo B — Estado final do sistema legado (snapshot abril 2026)

### B.1 Versão lógica vs módulos
- `VERSION` file: 0.1.11
- 8 módulos desalinhados em produção: `smc_engine.py` (0.1.10), `state.py` (0.1.10), `config.py` (0.1.8), `bot_handler.py` (0.1.6), `historical_loader.py` (0.1.6), `lib_version_check.py` (0.1.6), `tracker.py` (0.1.6), `ws_feed.py` (0.1.6)

### B.2 Tags Git
- Existentes: `v0.1.1`, `pre-step8-engine-refactor`
- Ausentes: `v0.1.2` a `v0.1.11`

### B.3 Schema final do `smc_state.db` (referência)
8 tabelas: `smc_state`, `candle_buffer`, `event_tracking`, `signal_lifecycle`, `signal_events`, `signal_emission_tracking`, `bot_state`, `historical_synthesis`. Detalhes completos em `git log`.

### B.4 Distribuição final de sinais (5 dias pós-purge)
- Total: 36 sinais
- Status: 35 timed_out (97.2%), 1 tp1_hit (2.8%), 0 sl_hit
- Direção: 100% LONG, 0% SHORT
- Score: 21 com score 3, 15 com score 4
- Janela: 22/04/2026 00:00 UTC a 25/04/2026 10:00 UTC

### B.5 Bugs identificados não corrigidos
1. `tracker.py` não fazia forward simulation real (`resolved_at_ts == emitted_at_ts`)
2. Cálculo entry vs SL temporalmente incoerente (35/36 LONGs com SL acima do entry)
3. Dedup `signal_emission_tracking` não acumulava (1 linha em vez de ~6-8)
4. Daemon órfão sem supervisor systemd (rodava como filho de bash de SSH antigo)
5. Logs duplicados (fds 1/2 → `logs/daemon.log`, fd 3 → `smc_monitor.log`)
6. `historical_synthesis` table sempre vazia
7. Working tree suja com untracked (`.venv-prod/`, `.venv-validation/`, `tools/`, backups DB)
8. Reboot pendente do SO (linux-image-6.8.0-1049-oracle)

Esses bugs **não serão corrigidos**. Foram documentados como evidência empírica que motivou a decisão de migrar.

---

**Fim do documento.**

> Este documento é vivo. Atualize-o quando aprender algo novo que pertença aqui. Não atualize com mudanças triviais — só com aprendizados que valem ser preservados para Claudes futuros.

