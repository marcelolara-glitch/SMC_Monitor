# SMC Monitor — Legado, Princípios e Aprendizados

> **Status do projeto:** o sistema próprio (`main.py` + `signals.py` + `tracker.py` + 8 módulos de apoio) foi descontinuado em abril de 2026, após Check Up técnico revelar problemas estruturais de modelagem. Este documento preserva o aprendizado e estabelece princípios que devem orientar qualquer futuro sistema SMC, dentro ou fora deste repositório.
>
> **Próxima fase:** subprojeto `smc_freqtrade/` neste mesmo repositório, com freqtrade como base de infraestrutura e lógica SMC implementada como `IStrategy` customizada. O sistema legado é preservado em `legacy/` para referência.
>
> **Última atualização:** 2026-04-26.

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

### 2.5 Invalidação é tão importante quanto entrada

**Princípio.** Setups morrem o tempo todo. Um especialista deleta setups com naturalidade. Se preço passou da zona sem voltar, ou voltou mas sem confirmação, ou confirmou mas o contexto macro mudou — o setup morre. Sistema sem invalidação acumula "zumbis" que parecem ativos mas são lixo.

**Por que isso importa.** O sistema legado mantinha sinais "vivos" por 24h independente do que o mercado fazia. Em alguns clusters, 5 sinais idênticos foram emitidos consecutivamente porque o setup persistia (sem o preço chegar a testá-lo) — todos terminaram em timeout sem nem perto de bater SL ou TP. Era ruído amplificado.

**Como fazer certo.** Critérios de invalidação explícitos para cada estado:

- **ARMED → invalidado** se OB/FVG mitigado, se preço escapou >2% acima/abaixo da zona sem voltar, ou se 6h sem atividade
- **PENDING_CONFIRMATION → invalidado** se preço atravessou a zona inteira sem confirmar, ou se contexto macro 4H mudou direção, ou se N candles 15m sem confirmação (timeout)
- **CONFIRMED → trade ativo**, com SL e TP estruturais. Saída por SL, TP, ou trailing.

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

### 8.2 Sinais de alerta — quando você (Claude) está derivando

Se você se pegar fazendo qualquer uma destas coisas, **pare e releia este documento**:

- Sugerindo "vamos calibrar o threshold do score" → você voltou ao modelo de scanner. SMC não é score-based.
- Propondo "vamos adicionar mais um critério de confluência" → mais critérios não corrigem modelagem errada. Volte para máquina de estados.
- Aceitando como adequado "sinal emitido a cada candle close se condições persistirem" → frequência alta de sinais é red flag, não feature.
- Calculando entry de evento A com SL de evento B sem checar coerência temporal → bug clássico do legado, não repita.
- Modelando "tracker" como módulo separado que simula forward → freqtrade faz isso nativamente. Não reimplemente.
- Sugerindo backtest opcional ou "depois se preocupa com isso" → backtest é primeira validação, não última.

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

## Anexo A — Repositórios e referências estudados

**Bibliotecas de detecção SMC (utilizadas):**
- `joshyattridge/smart-money-concepts` (PyPI: `smartmoneyconcepts==0.0.27`) — base de cálculo SMC, ~1.5k stars
- Variantes (não recomendadas): `tpwilo/smc`, `smtlab/smartmoneyconcepts`, `sailoo121/ss_smc`, `Prasad1612/smart-money-concept`

**Bots SMC com decisão (referência conceitual):**
- `starckyang/smc_quant` — padrão "detect FVG → locate OB → wait for retracement → enter"
- `manuelinfosec/profittown-sniper-smc` — fluxo sequencial `detect_bos → detect_order_block → is_perfect_ob → place_limit_order`
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

