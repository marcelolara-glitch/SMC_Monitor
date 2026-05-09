# Avaliação técnica — LuxAlgo Price Action Concepts vs portagem em curso

**Status:** documento de avaliação (não-briefing). A saída desta análise informa decisões futuras sobre quais ajustes incorporar à portagem `smc_freqtrade/` e em qual onda. **Não há proposta de implementação aqui.**

**Versão:** 1.0
**Data:** 2026-05-07
**Escopo:** comparar LuxAlgo Price Action Concepts™ (pago, invite-only) com (a) o LuxAlgo SMC gratuito (`luxalgo_smc_compute_only.py`, base da portagem) e (b) o estado atual do `smc_freqtrade/` (Ondas 1-3 mergeadas).
**Base de evidência:** documentação pública oficial da LuxAlgo (`docs.luxalgo.com`), descrição do indicador no TradingView, vídeo institucional "Greatest Price Action Indicator on TradingView" (transcrição), 4 screenshots de uso real do indicador no TradingView (D, 4H, 1H BTCUSDT.P + página do indicador). Sem acesso a código fonte do indicador pago.

**Restrições de método:**
- Análise exclusivamente sobre material aberto e observação de comportamento.
- Sem tentativa de extração de Pine source do indicador pago.
- Sem proposta de PR ou alteração de roadmap nesta sessão.
- Sem mexer no estado atual do `smc_freqtrade/` (Ondas 1-3 mergeadas, golden em pausa, Onda 4 pendente).

---

## 1. Sumário executivo

O LuxAlgo SMC gratuito que serviu de base para a portagem é, na verdade, um **subconjunto restrito** do Price Action Concepts pago — provavelmente uma fatia compute-only oferecida como amostra. O pago contém o mesmo núcleo (swing/internal/equal pivots, BOS/CHoCH, OBs com mitigação, FVG, EQH/EQL, Premium/Discount) **mais** sete grandes blocos adicionais que não existem no gratuito:

1. **CHoCH+** — variante "supported" do CHoCH com pré-condição estrutural (failed HH/LL antes do break)
2. **Volumetric Order Blocks** — OBs com volume interno bullish/bearish, métrica de % do total e ranking
3. **Breaker Blocks** — OBs mitigados que viram zonas de S/R com regra própria de invalidação
4. **Liquidity Trendlines** — zonas lineares (não horizontais) de S/R adaptativas com gatilho de breakout
5. **Chart Pattern Detection** — triângulos, wedges, double tops/bottoms, head & shoulders
6. **Liquidity Grabs** — detecção de varrida de liquidez com diferenciação bullish/bearish (este é o **gap C** do mapa atual, ainda em aberto na Onda 8)
7. **Imbalances expandidos** — além do FVG, inclui Inverse FVG, Double FVG (Balanced Price Range), Volume Imbalance, Opening Gap, e Volatility Threshold para filtrar todos eles

**Conclusão de alto nível.** A portagem em curso, baseada no SMC gratuito, está a caminho de cobrir bem o núcleo do framework SMC dogmático do projeto (mapa Camada 1 §5). Os recursos do pago se distribuem em três categorias muito diferentes em termos de impacto:

- Categoria A — **já cobertas pela portagem em curso** (nenhuma ação): núcleo de pivots, BOS/CHoCH básico, FVG básico, OB básico com mitigação, EQH/EQL, Premium/Discount.
- Categoria B — **melhoram a portagem mas não mudam arquitetura** (entrariam como ajustes em ondas futuras): CHoCH+, Volumetric Order Blocks, Breaker Blocks, Mitigation Methods configuráveis (Close/Wick/Average), Inverse FVG, Volatility Threshold.
- Categoria C — **mudam arquitetura ou exigem decisão de design** (potencial Mapa Camada 2): Liquidity Grabs (resolve o gap C que está em aberto), Liquidity Trendlines, Chart Pattern Detection.

Detalhamento por feature em §3 a §5. Mapeamento explícito em §6.

**Importante.** A inconsistência observada empiricamente pelo Marcelo entre o gratuito e o pago é **esperada** — não é bug do gratuito. O gratuito é uma versão didática reduzida; o pago tem variantes refinadas (CHoCH+) e features adicionais (Liquidity Grabs, Volumetric OB, Breakers) que **mudam visualmente o que aparece no chart**. Isso não invalida a portagem em curso, mas deve ser registrado no mapa para evitar confusão durante a produção do golden dataset.

---

## 2. Inventário de features do Price Action Concepts pago

Inventário consolidado a partir da documentação oficial (`docs.luxalgo.com/docs/algos/price-action-concepts/`), descrição no TradingView, página do produto na LuxAlgo e transcrição do vídeo institucional. Cada feature está descrita com a precisão que a fonte aberta permitiu — sem especulação sobre implementação interna.

### 2.1 Market Structure (página `/market-structures`)

- **BOS (Break of Structure)** e **CHoCH (Change of Character)**: idêntico em conceito ao gratuito.
- **CHoCH+ (Supported CHoCH)**: variante do CHoCH com pré-condição estrutural. Para um CHoCH+ bullish, o break do swing low é precedido por um failed higher high (lower high) na tendência bullish anterior. Para CHoCH+ bearish, precedido por failed lower low (higher low). É descrito como sinal de reversão "mais confirmado" que o CHoCH leading.
- **Internal vs Swing Structure**: idem gratuito, mas com **lookback configurável**. Internal: range 5-49. Swing: range 50-100. No gratuito, internal é hardcoded em 5 e swing default 50 com floor de 10.
- **Candle Coloring**: bars coloridas conforme o estado da estrutura interna. 4 tons: dark bullish (CHoCH bullish ativo), regular bullish (BOS bullish ativo), dark bearish (CHoCH bearish ativo), regular bearish (BOS bearish ativo). Tem opção monochrome.
- **Swing High/Low markers (HH/HL/LH/LL)**: rotulação visual dos swing points classificados pela relação com o anterior. Documentação afirma explicitamente que "swing points são exibidos retrospectivamente e não devem ser usados para aplicações em tempo real" — confirma o que o mapa Camada 1 já trata como lookahead inerente da detecção one-sided.
- **Strong/Weak High/Low**: marca extremos de médio prazo com **percentual relativo entre o volume dos dois swings adjacentes** para classificar se o extremo é "strong" ou "weak". Exige dados de volume.

**Visualmente nos screenshots.** O 1H mostra HH/HL/LH/LL e CHoCH/CHoCH+/BOS rotulados. O 4H mostra os mesmos rótulos. O Daily mostra apenas BOS e CHoCH (provavelmente porque CHoCH+ é mais raro em escala diária).

### 2.2 Volumetric Order Blocks (página `/order-blocks`)

- **OB com volume interno**: cada OB tem informação de bullish activity (verde) e bearish activity (vermelho) dentro do intervalo de candles que formou o OB. Visualmente é renderizado como barras horizontais dentro da caixa do OB.
- **Métricas exibidas à direita do OB**:
  - Volume acumulado dentro do intervalo do OB (formato `XX.XXXK`).
  - Percentual: quanto esse OB representa do volume total dos OBs visíveis no chart. A documentação explicita: "esse percentual permite determinar rapidamente quais OBs são mais interessantes". Visível nos screenshots como `(10%)`, `(20%)`, `(50%)`, etc.
- **Internal Activity & Metrics**: dashboard que classifica cada OB pela sua coerência interna — buy volume vs sell volume, com 4 classificações (Buy>Sell, Buy<Sell, Positive Association = OB bullish com buy>sell, Negative Association = OB bullish com sell>buy). Útil para distinguir OBs "limpos" de OBs onde a atividade interna contradiz o bias.
- **Mitigation Methods configuráveis**: Close (fechamento cruza extremidade), Wick (high/low cruza extremidade), Average (cruza nível médio do OB). No gratuito existe Close e Wick (parametrizado por `orderBlockMitigationInput`). No pago o Average é uma terceira opção.
- **Length configurável**: controla o lookback de detecção dos swing points usados para construir OBs. Range 1-20 no gratuito (`internalOrderBlocksSizeInput`, `swingOrderBlocksSizeInput`).
- **Hide Overlap**: oculta OBs sobrepostos preservando o mais recente. Não existe no gratuito (que tem cap fixo de 100 OBs por categoria).
- **MTF Order Blocks**: permite mostrar OBs de outro TF no chart atual. Exemplo da doc: 15m chart mostrando OBs do 1H. **Caveat documentado pela própria LuxAlgo**: "a localização temporal de um OB de outro TF pode diferir da localização no chart do TF nativo, e isso pode fazer OBs já mitigados aparecerem como não-mitigados". Isso é a versão aberta do problema do `lookahead_on` que o mapa já fechou (Conflito B).

### 2.3 Breaker Blocks (subseção de Order Blocks)

- **Conceito**: um OB que foi mitigado e que pode ser revisitado pelo preço passa a ser tratado como zona de S/R **invertida**. Bullish breaker = bullish OB que foi mitigado e agora atua como resistência. Bearish breaker = bearish OB mitigado que agora atua como suporte.
- **Regra de descarte**: bullish breaker desaparece quando o preço sobe além da extremidade superior do breaker; bearish desaparece quando preço desce abaixo da extremidade inferior.
- **Visualização**: caixas com background não-sólido (diferente dos OBs ativos).
- **Toggle**: feature opcional (`Show Breakers`).
- **Não existe no gratuito.** No gratuito, OB mitigado é simplesmente removido (`array.remove` em `deleteOrderBlocks`).

### 2.4 Liquidity Concepts (página `/liquidity`)

- **Liquidity Trendlines**: zonas **lineares** (não horizontais) de S/R que se adaptam dinamicamente. Aparecem só quando há evidência de que participantes do mercado buscaram liquidez naquele nível. Azul = uptrendlines (suporte). Vermelho = downtrendlines (resistência). Quando a extremidade da zona é quebrada, espera-se reversão. Tem alerta de breakout. Documentação destaca que são exibidas retrospectivamente — também sujeitas a lookahead.
- **Chart Pattern Detection**: detecta automaticamente triângulos ascendentes/descendentes/simétricos, broadening wedges, double tops/bottoms, head & shoulders, inverted head & shoulders. Tem dashboard no canto superior direito do chart que exibe o nome do padrão detectado. Quando nada é detectado, mostra trendlines genéricas de suporte/resistência. Lookback configurável.
- **Equal Highs & Lows**: detecta topos/fundos próximos via threshold (igual ao gratuito). Toggle para mostrar com configuração de length. Documentação explicita: "exige que os swing points sejam confirmados, o que toma um número de bars igual ao lookback. Por isso são exibidos retrospectivamente." Também sujeito a lookahead.
- **Liquidity Grabs**: ESTE É O GAP C DO MAPA. Detecção da varrida de liquidez. Bullish grab = atividade em demand area, indica reversão bullish potencial. Bearish grab = atividade em supply area, indica reversão bearish potencial. Bullish grabs renderizados em azul, com "borders" do price low até o body minimum do candle. Bearish em vermelho, do price high até o body maximum. **Se ambos ocorrem na mesma região, pode indicar mercado lateral** — a documentação chama isso de "market indecision". Tem alerta dedicado.

### 2.5 Imbalance Concepts (página `/imbalances`)

- **Fair Value Gaps (FVG)**: idêntico ao gratuito.
- **Inverse FVG**: FVG mitigado pode atuar como zona de retest. Bullish FVG mitigado vira bearish inverse FVG (espera-se retest pra cima). Bearish FVG mitigado vira bullish inverse FVG (retest pra baixo). **Documentação explicita uma decisão de eficiência**: "inverse FVGs sempre são baseados na mitigação do FVG **mais recente** detectado, descartando qualquer FVG histórico que possa ter sido mitigado". Importante para portagem.
- **Double FVG (Balanced Price Range)**: quando dois FVGs sobrepõem suas áreas, a área de overlap é destacada como nova imbalance. Bullish Balanced Price Range = novo bullish FVG sobreposto a bearish FVG anterior. Bearish = inverso. Útil para detectar zonas de duplo interesse institucional.
- **Volume Imbalance**: dois candles adjacentes com **bodies não-sobrepostos mas wicks sobrepostos**. Mais comum em ações ou TFs muito baixos. Diferente de FVG (que é wicks não-sobrepostos com central body).
- **Opening Gap**: dois candles adjacentes com **wicks não-sobrepostos**, deixando área vazia. Comum em ações (gap de abertura) e TFs muito baixos de crypto/forex.
- **Mitigation Methods**: Close, Wick, Average, **None**. Esta última é nova vs OB — permite preservar imbalances já mitigadas para análise histórica.
- **Volatility Threshold**: filtro multiplicativo (multiplier sobre estimador de volatilidade) que descarta imbalances pequenos demais. Increments de 1 produzem resultados visíveis; floats também aceitos. Aplicável a todas as 5 imbalances.
- **Buffer cap explícito de 200 imbalances** (vs 100 OBs no gratuito).

### 2.6 Premium & Discount Zones (página `/pdzones`)

- **3 zonas**: premium (superior), equilibrium (central), discount (inferior).
- Construída sobre os trailing extremes (top/bottom do range observado) — base conceitual idêntica ao `trailingExtremes` do gratuito.
- Uso documentado: "se uma condição indicativa de uptrend ocorrer dentro de discount zone, tem maior chance de ser causa de reversão; idem para downtrend dentro de premium". Cada zona pode também atuar como S/R isolado.
- **Visivelmente expandido nos screenshots**: o 1H mostra `Premium Bottom`, `Equilibrium Top`, `Equilibrium Bottom`, `Discount Top` na object tree — ou seja, são 4 níveis (e não apenas 3). Equilibrium tem largura própria (top e bottom), não é uma linha única.

### 2.7 Highs & Lows MTF (página `/previous-high-low`)

- Plota high/low de períodos anteriores: Daily, Weekly, Monthly, Quarterly, e Monday. Útil como níveis psicológicos de S/R.
- Documentação curta — não consegui detalhar mais sem acessar a página específica.

### 2.8 Fibonacci Retracements

- **Não é Fibonacci tradicional fixo.** A documentação explica que o usuário pode **ancorar os níveis Fibonacci entre dois pontos do toolkit**: pode ser entre Premium/Discount, entre o high/low de um imbalance, etc. É um Fibonacci "configurável por feature" do próprio toolkit.

### 2.9 Sistema de Alertas (página `/alerts`)

- **4 tipos**:
  1. **Pre-built alerts**: 33 alertas prontos cobrindo BOS, CHoCH, CHoCH+, EQH/EQL, OB created/mitigated/breaker/within/entered/exited, Imbalance new/mitigated/within/entered/exited, Trendline breaks, Patterns, Liquidity Grabs.
  2. **Any alert() function call**: agrupamento de múltiplas condições em um único alerta. Suporta placeholders rico (`{ticker}`, `{tf}`, `{open}`, `{high}`, `{low}`, `{close}`, `{volume}`, `{ob_buy_volume}`, `{ob_sell_volume}`, `{ob_volume}`) com formato JSON nativo.
  3. **Custom Alert Creator**: combina condições com operadores `Steps` (sequência ordenada), `OR`, `All` (filtro global), `Invalidate` (reseta sequência). Pode combinar features do toolkit e indicadores externos. Tem **Maximum Step Interval** (limite de barras entre steps) e **Highlight On Chart** (visualização das condições).
  4. **Alert Scripting** (mencionado no vídeo institucional): "build alerts from the ground up with ultimate flexibility. Perfect for advanced users." Documentação dedicada existe mas não foi acessada nesta análise.

**Observação relevante para o projeto.** O Custom Alert Creator com Steps é **conceitualmente uma máquina de estados** muito similar ao que o `setup_state.py` (Onda 9.5 do mapa) precisa fazer — sequência ordenada de condições com invalidação. O LuxAlgo expõe isso como UI; a portagem fará isso como código Python sobre o DataFrame.

---

## 3. Comparação feature-a-feature: pago vs gratuito vs portagem

Tabela densa cobrindo cada feature do pago. Status na portagem refere-se ao estado atual em `smc_freqtrade/` (Ondas 1-3 mergeadas: types, state, operators, pivots).

| # | Feature do pago | Existe no gratuito? | Status na portagem (smc_freqtrade) | Observação |
|---|---|---|---|---|
| 1 | Swing Pivots (length 50-100) | Sim, `swingsLengthInput` | **Cobertos** — `pivots.py` Onda 3 | `swings_length=50` configurável; defaults idênticos |
| 2 | Internal Pivots (length 5-49) | Sim, hardcoded em 5 | **Cobertos** — `pivots.py` Onda 3 | Pago é configurável; portagem é configurável; gratuito é hardcoded. Portagem já melhora aqui |
| 3 | Equal Pivots (length default 3) | Sim, `equalHighsLowsLengthInput` | **Cobertos** — `pivots.py` Onda 3 | Inclusive a flag `equal_high_alert`/`equal_low_alert` |
| 4 | BOS bullish/bearish (Internal + Swing) | Sim | **Onda 5 (pendente)** | Nova nomenclatura `Bullish I-BOS`, `Bullish S-BOS` no pago. Sem impacto na portagem |
| 5 | CHoCH bullish/bearish (Internal + Swing) | Sim, "leading CHoCH" | **Onda 5 (pendente)** | No pago, nomeado `Bullish I-CHOCH`, `Bullish S-CHOCH` |
| 6 | **CHoCH+ (Supported CHoCH)** | **Não** | **Não previsto** | Variante "mais confirmada" — failed HH/LL antes do break. Categoria B |
| 7 | Internal length configurável | Não (hardcoded 5) | **Cobertos** — `internal_length` parâmetro | Portagem já está alinhada ao pago, não ao gratuito |
| 8 | Swing length range completo (50-100) | Range 10+, sem ceiling explícito | **Cobertos** — `swings_length` aceita qualquer int >= 10 (validar Onda 5) | Nominalmente alinhado |
| 9 | Candle Coloring (4 tons + monochrome) | Não | **Não previsto** | Feature visual; não-aplicável a engine compute-only. Sem categoria |
| 10 | HH/HL/LH/LL labels classificados | Não (compute-only não rotula) | **Não previsto** | Visual; rotulação derivada de pivots — pode ser computada em pós-processo |
| 11 | **Strong/Weak Volume %** | Não | **Não previsto** | Exige dados de volume. Categoria B |
| 12 | OB básico (high/low/bias/time) | Sim | **Onda 6 (pendente)** | Conceito core; portagem em ordem |
| 13 | OB Mitigation Method = Close | Sim, `orderBlockMitigationInput` | **Onda 6 (pendente)** | Cobertos |
| 14 | OB Mitigation Method = Wick | Sim, valor `HIGHLOW` (high para bearish, low para bullish) | **Onda 6 (pendente)** | Pago renomeia para "Wick" mas mecânica é a mesma |
| 15 | **OB Mitigation Method = Average** | **Não** | **Não previsto** | Mitigação quando preço cruza nível médio do OB. Categoria B |
| 16 | **Volumetric OB (volume interno bullish/bearish)** | Não | **Não previsto** | Rico — buy_volume / sell_volume / total / %. Categoria B |
| 17 | **OB Metrics (% do volume total dos OBs)** | Não | **Não previsto** | Categoria B |
| 18 | **OB Internal Activity classificação (Positive/Negative Association)** | Não | **Não previsto** | Categoria B |
| 19 | **Hide Overlap (preserva mais recente)** | Não (cap absoluto de 100) | **Não previsto** | Cosmético + economia de buffer. Categoria B |
| 20 | **MTF Order Blocks (mostrar OB de outro TF)** | Não no compute-only | **Não previsto na engine** — resolvido pela `IStrategy` Freqtrade via `@informative` (mapa §2 Conflito A). | Já fechado |
| 21 | **Breaker Blocks (OB mitigado revisitável)** | **Não** | **Não previsto** | Categoria B (com nuance — ver §4.2) |
| 22 | EQH / EQL com threshold ATR-based | Sim, `equalHighsLowsThresholdInput` | **Cobertos** — `pivots.py` Onda 3 (`equal_threshold`) | |
| 23 | EQH / EQL alertas | Sim (`alertcondition`) | **Cobertos** como colunas `equal_high_alert`/`equal_low_alert` | |
| 24 | **Liquidity Grabs bullish/bearish** | **Não** | **Não previsto na engine atual** — a Onda 8 do mapa cobre "Liquidity Sweep" como gap C (decisão pendente sobre regra exata). | Categoria C — alta convergência conceitual com a Onda 8 planejada (ver §4.4) |
| 25 | **Liquidity Trendlines (zonas lineares de liquidez)** | **Não** | **Não previsto** | Categoria C — feature inédita |
| 26 | **Chart Pattern Detection (triângulos, wedges, H&S, double top/bottom)** | **Não** | **Não previsto** | Categoria C — feature inédita |
| 27 | FVG bullish/bearish | Sim, `drawFairValueGaps` | **Onda 7 (pendente, com assinatura concreta no mapa v1.1)** | Cobertos em design |
| 28 | FVG mitigation Close/Wick/Average/None | Mitigation simples (low/high cruza extremidade) | **Onda 7 (pendente)** | Pago tem mais granularidade. Categoria B |
| 29 | **Inverse FVG (FVG mitigado como retest area)** | **Não** | **Não previsto** | Categoria B com nuance — só baseado no FVG mais recente, por design (eficiência) |
| 30 | **Double FVG / Balanced Price Range** | **Não** | **Não previsto** | Categoria B |
| 31 | **Volume Imbalance** | **Não** | **Não previsto** | Pouco aplicável a perpetual swap 24/7 (ausência de gaps) — ver §4.5. Categoria B |
| 32 | **Opening Gap** | **Não** | **Não previsto** | Idem #31 — irrelevante para perpetual 24/7 |
| 33 | **Volatility Threshold (filtro de imbalances)** | Sim parcial (`fairValueGapsThresholdInput` automático) | **Não previsto explicitamente** — engine respeita o threshold automático do gratuito | Pago tem multiplier configurável em todos os 5 imbalances. Categoria B |
| 34 | Premium / Discount básico | Não computado, mas trailing extremes é a base | **Onda 4 (pendente, `premium_discount.py` derivado de trailing)** | Cobertos em design |
| 35 | **Premium / Equilibrium / Discount com 4 níveis** (premium_bottom, equilibrium_top, equilibrium_bottom, discount_top) | Não no compute-only | **Não previsto na granularidade do pago** | Equilibrium tem largura própria — Categoria B |
| 36 | Trailing Extremes (top/bottom absolutos do range observado) | Sim, `trailing.top` / `trailing.bottom` | **Onda 4 (pendente, `trailing.py`)** | Cobertos em design |
| 37 | **Highs/Lows MTF (Daily/Weekly/Monthly/Quarterly/Monday)** | **Não** | **Não previsto na engine** — pode ser feito na `IStrategy` Freqtrade via `@informative` | Categoria B (resolvível fora da engine) |
| 38 | **Fibonacci ancorável a features (P&D, imbalance, structure)** | **Não** | **Não previsto** | Categoria B — derivável dos níveis primários |
| 39 | **MTF Dashboard (15m, 1h, 4h, 1d)** | Não no compute-only | **Não previsto na engine** — resolvido pela `IStrategy` via `@informative` | Já fechado pela arquitetura Freqtrade |
| 40 | **Custom Alert Creator (Steps, OR, Invalidate, All)** | Não | **Conceito coberto** pelo `setup_state.py` (Onda 9.5 do mapa) | Convergência conceitual notável (ver §4.6) |
| 41 | Alertas básicos via `alertcondition()` | Sim, 16 alertas | **No-op — descartado na portagem** (mapa §4.6) | Engine produz colunas booleanas; alerta é responsabilidade do consumidor |

---

## 4. Análise feature-a-feature das categorias B e C

Aprofundamento dos itens que merecem discussão técnica.

### 4.1 CHoCH+ (item 6 da tabela) — Categoria B

**O que é.** Variante "supported" do CHoCH. Em vez de detectar apenas o crossover do close vs swing pivot (como o gratuito faz em `displayStructure`), o pago exige uma pré-condição estrutural: durante a tendência anterior, deve ter ocorrido um **failed higher high** (ou seja, um lower high) antes do CHoCH bullish; ou um **failed lower low** (higher low) antes do CHoCH bearish.

**Por que isso importa para o framework SMC.** O CHoCH "leading" puro é mais frequente mas mais ruidoso — pode ocorrer em retração técnica que não significa reversão real. O CHoCH+ é um **filtro de qualidade**: já houve sinal de fraqueza antes do break formal, então a probabilidade de reversão é maior. Isso converge com o princípio "narrativa sequencial vs checklist" do `SMC_PRINCIPIOS_E_LEGADO.md` §2.1.

**Impacto na portagem.** Não muda arquitetura. É uma regra adicional dentro de `displayStructure` (Onda 5 pendente). Inputs: detecção de pivots já existe (Onda 3), só precisa armazenar mais um estado por trend (`failed_swing_observed: bool` que reseta a cada trend change). Bumpa complexidade do `structure.py` em ~30%.

**Observação para o golden dataset.** Se o golden é produzido com o LuxAlgo pago (referência visual), os marcadores CHoCH+ vão aparecer no chart. A portagem atual (baseada no gratuito) **vai marcar isso como CHoCH simples**. Sem a feature, o golden e a portagem divergirão visualmente em uma fração dos eventos. Decisão a tomar: incluir CHoCH+ na Onda 5, ou aceitar divergência documentada.

### 4.2 Volumetric Order Blocks + Breaker Blocks (itens 16-21) — Categoria B

**O que é.** Volumetric OB enriquece cada OB com:
- Buy volume e sell volume internos (decompõe o volume agregado por bias do candle).
- Total volume.
- Percentual do total dos OBs visíveis (ranking implícito).
- Classificação Positive/Negative Association (consistência interna do bias).

Breaker Block é uma variante de estado: OB que foi mitigado **não desaparece** — vira "breaker" e atua como zona de S/R invertida até que o preço escape definitivamente.

**Por que isso importa para SMC.** Volume interno é uma das formas mais robustas de classificar **força** de um OB. OB com volume de 50% do total dos OBs visíveis é uma zona muito mais relevante que OB com 5%. O ranking implícito permite **filtrar OBs fracos** sem definir threshold absoluto (que varia de mercado para mercado).

Breaker Block é um conceito que aparece com frequência na literatura ICT pura (mais que CHoCH+, inclusive). Um OB mitigado que age como breaker é onde "smart money cobriu posição e agora opera o lado oposto" — narrativa coerente com o framework.

**Impacto na portagem.**

- **Volumetric OB**: requer dados de volume no DataFrame de entrada. Pandas vetorizado: `buy_volume = df[df['close'] > df['open']]['volume']`, `sell_volume = df[df['close'] < df['open']]['volume']`. Não muda arquitetura, mas requer `volume` como dependência obrigatória do DataFrame (hoje a engine só exige `high`, `low`, `close`). Adiciona ~6 colunas ao output da Onda 6 (`ob_buy_volume`, `ob_sell_volume`, `ob_total_volume`, `ob_pct_of_total`, `ob_association` (`positive`/`negative`/`neutral`)).

- **Breaker Block**: muda a regra de descarte do `deleteOrderBlocks`. Em vez de remover na mitigação, **transitiona para estado breaker**. Depois do estado breaker, tem sua própria regra de remoção (preço além da extremidade do breaker). Requer adicionar campo `state` (`active`/`breaker`/`removed`) ao `OrderBlock` UDT. Não muda arquitetura, mas refatora `order_blocks.py` da Onda 6.

**Categoria.** B (sem mudança arquitetural), mas com 2 sub-decisões: (a) aceitar volume como input obrigatório, (b) refatorar UDT do OB pra ter state machine de 3 estados.

### 4.3 Liquidity Trendlines (item 25) — Categoria C

**O que é.** Zonas **não-horizontais** (trendlines com inclinação) que delimitam acúmulo de liquidez ao longo do tempo. Aparecem quando há "evidência de que market participants buscaram liquidez" — ou seja, é uma forma de detecção retrospectiva.

**Por que isso é Categoria C.** Toda a engine atual (gratuito + portagem) opera com zonas **horizontais** — OB tem `top` e `bottom` constantes, FVG idem, Premium/Discount idem. Trendline é zona com inclinação `m` e intercept `b`, e a coluna no DataFrame não é mais um nível mas uma função do tempo.

Estruturalmente, isso significa:
- Schema de output muda — colunas auxiliares passam a ser fórmulas, não níveis.
- Detecção de "preço dentro da trendline" vira `df['close'] vs (m * df['x'] + b)` em cada candle, não comparação simples.
- A `setup_state.py` (Onda 9.5) precisa ser estendida para reconhecer zona-trendline além de zona-horizontal.

**Impacto na portagem.** Mudança de design de zonas. Possivelmente Mapa Camada 2.

### 4.4 Liquidity Grabs (item 24) — Categoria C, alta convergência com a Onda 8

**O que é.** Detecção da varrida de liquidez. Bullish grab: candle com atividade significativa em demand area (preço sondou abaixo de um EQL ou swing low e voltou). Bearish grab: idem em supply area. Renderizado com "borders" (bordas coloridas) sobre o wick do candle.

**Por que isso é central.** A Onda 8 do mapa Camada 1 v1.1 (`liquidity_sweep.py`) é exatamente essa feature, e está em **decisão pendente** (mapa §8 #5). O texto do mapa diz: "especificar a regra exata de detecção. Sugestão inicial baseada na literatura SMC: 'candle cujo high ultrapassa o `equalHigh.currentLevel` por mais de X% do ATR e cujo close volta abaixo do `equalHigh.currentLevel`'."

**O que o pago revela sobre a regra.** A documentação do pago descreve Liquidity Grab como "atividade em área de demanda/oferta" — note que **não** é restrito a EQH/EQL. Pode ser sobre swing pivots em geral. E a definição usa "borders ranging from price low to candle body minimum" (bullish) ou "from price high to candle body maximum" (bearish) — ou seja, **a regra parece ser: wick longo cruzando o nível + close de volta**. Isso é mais geral que o que o mapa Camada 1 prevê.

**Implicação imediata para a portagem.** Quando a Onda 8 for endereçada, o pago oferece referência conceitual mais rica que apenas EQH/EQL. A regra exata ainda precisa ser inferida por golden dataset (comparando o que o LuxAlgo pago renderiza vs o que a portagem detecta), mas a direção é clara: **aplicável também a swing pivots, não só a equal pivots**.

**Categoria.** Tecnicamente C (decisão de design), mas com escopo já reservado na roadmap (Onda 8). Não é feature inédita — é a feature que justamente está em aberto.

### 4.5 Imbalances expandidos (itens 28-33) — Categoria B (com nuance)

**Inverse FVG.** Conceitualmente importante para SMC: FVG mitigada vira retest area de bias oposto. A documentação explicita que **só o FVG mais recente é tratado como inverse** (decisão de eficiência). Se a portagem implementar isso, deve seguir mesmo critério para evitar explosão de colunas auxiliares. Categoria B.

**Double FVG / Balanced Price Range.** Dois FVGs sobrepostos formam zona reforçada. Na prática: união de bullish FVG sobreposto a bearish FVG anterior = bullish BPR. Pode ser computado como pós-processamento das colunas FVG existentes. Categoria B trivial.

**Volume Imbalance e Opening Gap.** Aplicáveis principalmente a stocks ou TFs muito baixos. **Para perpetual swap 24/7 (BTC-USDT-SWAP do projeto), esses dois são essencialmente irrelevantes** — não há fechamento de mercado, então não há opening gap; e candles consecutivos quase nunca têm bodies não-sobrepostos com wicks sobrepostos em TFs de 15m+. Recomendação: **não implementar** na portagem por estarem fora do mercado-alvo.

**Volatility Threshold para imbalances.** O gratuito tem threshold automático para FVG via `fairValueGapsThresholdInput`. O pago expõe isso como **multiplier configurável** aplicável a todas as 5 imbalances. Útil para hyperopt no Freqtrade — uma constante calibrável. Categoria B trivial (basta expor o multiplier no `detect_fair_value_gaps` da Onda 7).

### 4.6 Custom Alert Creator vs setup_state.py (item 40) — convergência

A leitura do Custom Alert Creator do pago revela uma convergência interessante com o `setup_state.py` (Onda 9.5 do mapa Camada 1 v1.1). Comparação:

| Conceito do Custom Alert Creator | Equivalente no `setup_state.py` planejado |
|---|---|
| Steps (sequência ordenada) | Transições de estado: ARMED → PENDING_CONFIRMATION → CONFIRMED |
| Step 1 (gatilho inicial) | Gatilho de transição (vazio) → ARMED |
| Step 2, 3... (gatilhos seguintes) | Gatilhos das transições subsequentes |
| Invalidate Step | Transição → INVALIDATED |
| Maximum Step Interval | Timeout entre transições (ex: "6h sem atividade no ARMED") |
| OR Step | Múltiplas formas de chegar ao mesmo estado |
| All Step | Filtros transversais (ex: "trend 4H bullish em todos os steps") |

**Interpretação.** O LuxAlgo pago expõe via UI o que o `setup_state.py` planeja fazer via código Python sobre o DataFrame. Isso é validação conceitual do design — não é uma feature a portar. **Não há ação a tomar aqui.** Apenas registrar que o conceito de máquina de estados SMC é o mesmo nos dois mundos (UI declarativa vs código vetorizado), e isso reforça a corretude do roadmap atual.

---

## 5. Avaliação da inconsistência observada pelo Marcelo

A motivação da análise foi a observação empírica de que o LuxAlgo SMC gratuito apresenta inconsistências de comportamento durante a produção do golden dataset. A explicação técnica completa, a partir do material lido:

1. **O gratuito é uma fatia compute-only do pago.** O `luxalgo_smc_compute_only.py` tem 341 linhas, 16131 bytes, e cobre apenas: pivots (swing/internal/equal), BOS/CHoCH simples, OBs simples (com mitigation Close/Wick), FVG simples, Premium/Discount via trailing extremes. Tudo o que está em §2 deste documento (CHoCH+, Volumetric OB, Breakers, Liquidity Grabs, Trendlines, Patterns, Imbalances expandidos) **não existe no gratuito**. Não é bug — é arquitetura intencional de produto (open source vs invite-only).

2. **As inconsistências visuais que você observa entre gratuito e pago são consequência direta dessa diferença de feature set.** O gratuito **não pode** mostrar CHoCH+, então onde o pago marca CHoCH+ o gratuito marca apenas CHoCH (ou nada, se a regra do pago descartou um CHoCH leading que estava perto). O gratuito **não pode** mostrar Liquidity Grab. O gratuito mostra OB sem volume, sem ranking, e descarta na mitigação em vez de tornar breaker. Cada uma dessas diferenças é visível no chart como "indicador pago tem mais marcações" ou "indicador pago tem marcações em lugares diferentes".

3. **Para a portagem em curso, a referência canônica de fidelidade ainda é o gratuito.** Isso porque a portagem foi mapeada a partir do `luxalgo_smc_compute_only.py` (mapa Camada 1). O golden dataset que valida a portagem tem que ser produzido a partir de **uma destas duas opções**:
   - **Opção A (atual):** rodar o LuxAlgo SMC gratuito no TradingView e exportar o que ele detecta. Match exato com a portagem é a meta.
   - **Opção B:** usar o LuxAlgo Price Action Concepts pago como referência visual e aceitar que a portagem **não vai bater 100%** porque está baseada num subset. Isso requer registrar explicitamente quais features do pago não existem na portagem (essencialmente a coluna "Não previsto" do §3).

A decisão entre A e B não é tomada aqui, mas o documento `SMC_FREQTRADE_DECISÃO_FECHADA_GOLDEN.md` (referenciado no `userMemories`) já indica que o golden é produzido por Claude.ai/Code a partir de **referência visual** do Marcelo (screenshot TradingView com LuxAlgo aplicado). Se a referência visual for o pago, estamos efetivamente na Opção B — o que **deveria estar documentado** no mapa Camada 1.

**Recomendação para evitar surpresa futura.** Antes da Onda 4 começar, fechar explicitamente: o golden é referência ao gratuito ou ao pago? Se ao pago, atualizar o `MAPA_LUXALGO_CAMADA_1_v1.1.md` §7 (estratégia de validação por golden dataset) para listar as divergências esperadas e categorizá-las como "diferença documentada" vs "bug a investigar".

---

## 6. Mapeamento em três categorias

Conforme pedido, distribuição das features do pago em três buckets de impacto.

### 6.1 Categoria A — Já cobertas pela portagem em curso (nenhuma ação)

Features que a portagem cobre ou já tem prevista nas ondas mergeadas / planejadas. Nenhuma divergência arquitetural com o pago.

- Swing/Internal/Equal Pivots (Onda 3 — mergeada).
- BOS/CHoCH bullish/bearish (Onda 5 — pendente).
- Internal length configurável (Onda 3 já cobriu — portagem é mais flexível que o gratuito aqui).
- OB básico com mitigation Close/Wick (Onda 6 — pendente).
- FVG bullish/bearish (Onda 7 — pendente, com assinatura concreta no mapa v1.1).
- EQH/EQL com threshold ATR-based (Onda 3 — mergeada).
- Trailing Extremes top/bottom (Onda 4 — pendente).
- Premium/Discount básico de 3 zonas (Onda 4 — pendente, derivado de trailing).
- Multi-TF (resolvido pela `IStrategy` Freqtrade — fechado no mapa v1.1 §5.1).
- Highs/Lows MTF (resolvível na `IStrategy` via `@informative` — não é responsabilidade da engine).
- MTF Dashboard (resolvido pela `IStrategy`).
- Custom Alert Creator (conceitualmente coberto pelo `setup_state.py` da Onda 9.5).

### 6.2 Categoria B — Melhoram a portagem mas não mudam arquitetura

Features que cabem como ajuste em ondas existentes ou ondas adicionais sem refatorar arquitetura. Cada item entra como "candidato a sub-onda" ou "ajuste local em onda existente".

- **CHoCH+ (Supported CHoCH)** — extensão de `displayStructure` (Onda 5). Adiciona estado `failed_swing_observed` por trend.
- **OB Mitigation Method = Average** — opção adicional em `deleteOrderBlocks` (Onda 6). Trivial.
- **Volumetric OB com volume interno** — exige `volume` como input obrigatório do DataFrame; adiciona ~6 colunas ao output da Onda 6.
- **OB Metrics (% do volume total)** — pós-processamento das colunas Volumetric OB. Trivial.
- **OB Internal Activity (Positive/Negative Association)** — derivado de buy_volume vs sell_volume. Trivial.
- **Hide Overlap** — flag de pós-filtro em `order_blocks.py` (Onda 6).
- **Strong/Weak Volume %** — exige volume; análoga a Volumetric OB mas para swing extremos.
- **Breaker Blocks** — refatora UDT do OB para state machine de 3 estados (`active`/`breaker`/`removed`). Localizado em `order_blocks.py` (Onda 6).
- **FVG Mitigation Methods Close/Wick/Average/None** — análogo ao OB, opções adicionais em `deleteFairValueGaps` (Onda 7).
- **Inverse FVG** — extensão da Onda 7 com regra "só o FVG mais recente vira inverse".
- **Double FVG / Balanced Price Range** — pós-processamento das colunas FVG. Trivial.
- **Volatility Threshold como multiplier configurável** — expor como parâmetro em `detect_fair_value_gaps` (Onda 7).
- **Premium / Equilibrium / Discount com 4 níveis** — refinamento do `premium_discount.py` (Onda 4) — Equilibrium passa a ter top e bottom em vez de ser linha única.
- **Fibonacci ancorável a features** — derivável das colunas existentes; pode virar módulo opcional `smc_engine/fibonacci.py` em onda futura.

**Decisão típica para itens da Categoria B:** Marcelo decide caso-a-caso quais entram em ondas existentes (CHoCH+ na Onda 5, mitigation methods nas suas ondas correspondentes) e quais ficam para depois ou nunca (Volume Imbalance e Opening Gap, por exemplo, são irrelevantes para perpetual swap).

### 6.3 Categoria C — Mudam arquitetura ou exigem decisão de design

Features que requerem revisão do mapa, possivelmente Mapa Camada 2 dedicado, antes de implementar.

- **Liquidity Grabs (varrida de liquidez)** — esta é a **Onda 8 já planejada** no mapa Camada 1 v1.1, com decisão pendente (#5) sobre regra exata. O LuxAlgo pago oferece referência conceitual mais rica que apenas EQH/EQL — sugere aplicação a swing pivots em geral. **Quando a Onda 8 for endereçada, o material observado do pago deve ser parte do briefing dessa onda.** Esta é a maior convergência entre o que falta na portagem e o que o pago oferece.

- **Liquidity Trendlines (zonas lineares de liquidez)** — feature inédita. Muda o schema de zonas (de horizontal para função do tempo). Schema de output da engine, regra de "preço dentro da zona", e `setup_state.py` precisariam ser estendidos. Decisão arquitetural significativa.

- **Chart Pattern Detection (triângulos, wedges, H&S, double tops/bottoms)** — feature inédita, fora do framework SMC dogmático do projeto. Requer pipeline de detecção de padrões geométricos (não trivial em pandas vetorizado). Decisão de escopo: o projeto SMC quer absorver detecção de patterns clássicos, ou mantém-se restrito ao núcleo SMC?

**Decisão típica para itens da Categoria C:** Marcelo decide se a feature entra no roadmap **antes** de implementar. Para Liquidity Grabs especificamente, a decisão já está tomada (entra na Onda 8); para as outras duas, exige discussão de escopo.

---

## 7. O que esta avaliação NÃO entrega

Por escopo declarado:

- Não há briefing para Claude Code.
- Não há proposta de PR.
- Não há definição de regra exata para implementar Liquidity Grab (regra do pago é só observada visualmente — a especificação técnica fica na Onda 8 quando ela for endereçada).
- Não há reordenação do roadmap.
- Não há estimativa de esforço por feature (depende de calibração caso-a-caso).
- Não há recomendação de "implementar X agora" — todas as decisões de incorporação ficam para o Marcelo, ondas futuras.

---

## 8. Decisões em aberto que esta análise revela

Para Marcelo decidir em sessões posteriores (não nesta):

1. **Golden dataset: gratuito ou pago como referência visual?** Hoje o memory diz que Marcelo entrega referência visual (screenshot TradingView com LuxAlgo aplicado). Não está explícito se é o gratuito ou o pago. Se for o pago (provável, dado que é o que ele assinou), o mapa Camada 1 §7 precisa ser atualizado para listar divergências esperadas (essencialmente as features da Categoria A que **estão no pago e não no gratuito**: CHoCH+, Volumetric OB, Breakers, Liquidity Grabs, Trendlines, Patterns).

2. **CHoCH+ entra na Onda 5?** Decisão tomada antes da Onda 5 começar. Se sim, o briefing dessa onda referencia este documento §4.1.

3. **Volumetric OB entra na Onda 6?** Implica `volume` virar input obrigatório do DataFrame (hoje exige só `high`/`low`/`close`). Decisão antes da Onda 6.

4. **Breaker Blocks entram na Onda 6?** Implica refatorar UDT do OB para state machine. Decisão antes da Onda 6.

5. **Liquidity Grabs (Onda 8) — especificação da regra.** Material observado do pago deve ser incorporado ao briefing da Onda 8 quando ela for ativada. Decisão pendente #5 do mapa.

6. **Categoria C (Liquidity Trendlines, Chart Patterns) — entra no roadmap ou fica fora?** Decisão de escopo.

7. **Volume Imbalance e Opening Gap — explicitamente excluídos?** Recomendação técnica: sim, irrelevantes para perpetual swap 24/7. Mas requer decisão registrada para evitar reabertura.

---

## 9. Referências consultadas

**Documentação oficial LuxAlgo:**

- `https://docs.luxalgo.com/docs/algos/price-action-concepts/introduction`
- `https://docs.luxalgo.com/docs/algos/price-action-concepts/market-structures`
- `https://docs.luxalgo.com/docs/algos/price-action-concepts/order-blocks`
- `https://docs.luxalgo.com/docs/algos/price-action-concepts/liquidity`
- `https://docs.luxalgo.com/docs/algos/price-action-concepts/imbalances`
- `https://docs.luxalgo.com/docs/algos/price-action-concepts/pdzones`
- `https://docs.luxalgo.com/docs/algos/price-action-concepts/alerts`
- `https://docs.luxalgo.com/docs/luxalgo-toolkits/changelog/price-action-concepts` (changelog histórico)

**Página do produto:**

- `https://www.luxalgo.com/library/indicator/luxalgo-price-action-concepts/`

**TradingView:**

- `https://www.tradingview.com/script/ZGl2xWym-LuxAlgo-Price-Action-Concepts/` (descrição + release notes)

**Vídeo institucional:**

- "Greatest Price Action Indicator on TradingView" — transcrição completa fornecida pelo Marcelo (10 minutos).

**Material visual:**

- Screenshots BTCUSDT.P 1H/4H/D do TradingView com LuxAlgo Price Action Concepts pago aplicado (4 imagens fornecidas pelo Marcelo).
- Screenshot da página do indicador no TradingView (1 imagem).

**Documentos canônicos do projeto (lidos antes da análise):**

- `AGENTS.md` (raiz do repo)
- `docs/MAPA_LUXALGO_CAMADA_1_v1.1.md`
- `docs/SMC_PRINCIPIOS_E_LEGADO.md`
- `tools/pynecore-validation/luxalgo_smc_compute_only.py`
- `smc_freqtrade/smc_engine/pivots.py`

---

**Fim do documento de avaliação.**

