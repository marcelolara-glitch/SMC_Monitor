# Mapa estrutural Camada 1 — LuxAlgo SMC

**Versão:** 1.1
**Arquivo fonte:** `luxalgo_smc_compute_only.py`
**SHA-256:** `9433ca63fc85f5613f307d0964347193c98578f58daf10cdbb391a98b6bbf8b1`
**Tamanho:** 341 linhas, 16131 bytes
**Coletado em:** 2026-05-03 (mtime do arquivo: 2026-05-01 16:56)
**Compilador de origem:** PyneComp v6.0.30

**Mudanças desde v1.0:**
- Decisões pendentes #1 e #3 fechadas (Verificação documental Freqtrade encerrou ambas)
- Conflito A reformulado de "decisão pendente" para "responsabilidade da IStrategy"
- Conflito B fechado (não replicar `lookahead_on`)
- Onda 7 (FVG) ganha assinatura concreta com 2 DataFrames
- Onda 10 ganha esqueleto verificado da `SMCStrategy`
- Surge módulo `setup_state.py` (máquina de estados) como responsabilidade da engine, não da IStrategy
- Novo bloco §10 documenta como cada alteração foi derivada da verificação Freqtrade

---

## 0. Convenções deste documento

- "Função" = função Python definida no arquivo (incluindo as nested dentro de `main`).
- "Estado" = variáveis declaradas como `Persistent[...]` que sobrevivem entre invocações (entre candles).
- "Primitiva Pine" = símbolo importado de `pynecore.lib` ou `pynecore.types`.
- Camada 2 (detalhamento por função com pseudocódigo, validação e plano de testes) será gerada **sob demanda, por PR de portagem**, não agora.

---

## 1. Inventário de UDTs (User-Defined Types)

São 6 UDTs definidos no topo do arquivo. Cada um precisa de equivalente Python (provavelmente `dataclass` com defaults ou `NamedTuple` mutável).

| # | UDT | Campos | Função |
|---|---|---|---|
| 1 | `alerts` | 16 booleans (todos `False` por padrão) | Container de eventos detectados no candle atual. Cada bool corresponde a um `alertcondition` no final do `main`. |
| 2 | `trailingExtremes` | `top`, `bottom`, `barTime`, `barIndex`, `lastTopTime`, `lastBottomTime` | Extremos absolutos do range observado, usado para Premium/Discount. |
| 3 | `fairValueGap` | `top`, `bottom`, `bias` | Um FVG individual (entra em lista global). |
| 4 | `trend` | `bias` (1 / -1 / 0) | Direção atual da estrutura (BULLISH/BEARISH/none). |
| 5 | `pivot` | `currentLevel`, `lastLevel`, `crossed`, `barTime`, `barIndex` | Um swing point individual (high ou low). |
| 6 | `orderBlock` | `barHigh`, `barLow`, `barTime`, `bias` | Um OB individual (entra em lista global). |

**Notas conceituais:**
- `pivot.crossed` é a flag que evita re-emitir BOS/CHoCH no mesmo pivot (importante para máquina de estados — alinha com o princípio "monitor não emite a cada candle close").
- `alerts` é resetado a cada candle (instanciado no início do `main` como `currentAlerts: alerts = alerts()` sem `Persistent`). Eventos são "flags do candle atual", não acumuladores.

---

## 2. Inventário de variáveis `Persistent` (estado entre candles)

Toda a "memória" da engine está aqui. São 17 variáveis persistentes:

| # | Nome | Tipo | Conteúdo |
|---|---|---|---|
| 1 | `swingHigh` | `pivot` | Último swing high de longo prazo (length=50). |
| 2 | `swingLow` | `pivot` | Último swing low de longo prazo. |
| 3 | `internalHigh` | `pivot` | Último swing high "interno" (length=5). |
| 4 | `internalLow` | `pivot` | Último swing low interno. |
| 5 | `equalHigh` | `pivot` | Último high candidato a EQH (length=3). |
| 6 | `equalLow` | `pivot` | Último low candidato a EQL. |
| 7 | `swingTrend` | `trend` | Direção da estrutura swing (BOS/CHoCH no length=50). |
| 8 | `internalTrend` | `trend` | Direção da estrutura internal (BOS/CHoCH no length=5). |
| 9 | `fairValueGaps__global__` | `list[fairValueGap]` | Todos os FVGs ativos (não mitigados). |
| 10 | `parsedHighs__global__` | `list[float]` | Highs ajustados (com inversão em "high volatility bars"). |
| 11 | `parsedLows__global__` | `list[float]` | Lows ajustados. |
| 12 | `highs__global__` | `list[float]` | Histórico de highs raw. |
| 13 | `lows__global__` | `list[float]` | Histórico de lows raw. |
| 14 | `times__global__` | `list[int]` | Histórico de timestamps. |
| 15 | `trailing` | `trailingExtremes` | Extremos absolutos atualmente trackeados. |
| 16 | `swingOrderBlocks` | `list[orderBlock]` | Todos os OBs swing ativos (não mitigados). |
| 17 | `internalOrderBlocks` | `list[orderBlock]` | Todos os OBs internal ativos. |

**Implicação para portagem:** essas 17 variáveis viram um objeto `EngineState` (ou equivalente) que a engine consome e atualiza.

**v1.1 — refinamento sobre escopo de estado:** Verificação Freqtrade confirmou que a engine SMC opera em DataFrame único do TF que recebe. Portanto:

- **Estado é por instância** — ao chamar `analyze(dataframe_4h)` e depois `analyze(dataframe_1h)`, são duas execuções totalmente isoladas. Não há estado compartilhado entre TFs.
- **Modelo "engine como função pura"** — a engine recebe DataFrame, internamente cria um `EngineState` temporário, processa candle-a-candle, retorna DataFrame com colunas adicionadas. Estado vive apenas durante a execução de `analyze()`, não persiste entre chamadas.
- **Em backtest do Freqtrade**, `populate_indicators` roda uma vez sobre o histórico inteiro. A engine processa todos os candles e retorna. Não há "tick-a-tick" como no Pine.
- **Em dry/live**, o Freqtrade rerroda `populate_indicators` a cada candle close, com o DataFrame completo (acumulado). A engine sempre processa do zero. Estado não precisa ser serializado entre execuções — é reconstruído.

**Implicação para arrays globais:** `parsedHighs__global__` e `parsedLows__global__` no LuxAlgo crescem indefinidamente porque o Pine simula bar-by-bar. Em pandas vetorizado, são **colunas auxiliares do DataFrame** (`df['parsed_high']`, `df['parsed_low']`), preenchidas em uma única operação vetorizada. Lista global desaparece como conceito. Detalhe arquitetural a fechar na Camada 2 da Onda 6 (Order Blocks), onde `array.slice(parsedHighs__global__, p_ivot.barIndex, bar_index)` vira `df.iloc[p_ivot_idx:current_idx]['parsed_high']`.

---

## 3. Inventário de funções (Camada 1)

São 9 funções nested dentro de `main`, mais o próprio `main`. Numero por ordem de definição no arquivo.

### 3.1 Tabela compacta — visão de todo o arquivo

| # | Função | Chamada por | Estado lê | Estado escreve | Primitivas Pine usadas | Complexidade portagem | Observação principal |
|---|---|---|---|---|---|---|---|
| 1 | `leg(size)` | `getCurrentStructure` | (nenhum) | (nenhum) | `ta.highest`, `ta.lowest`, `Persistent[int]` interno | **Baixa** | Stateless por definição, mas usa `Persistent` interno para "lembrar" a leg. Vetorizável em pandas. |
| 2 | `startOfNewLeg(leg)` | `getCurrentStructure` | (nenhum) | (nenhum) | `ta.change` | **Baixa** | One-liner. `ta.change(x) != 0` ↔ `x != x.shift(1)`. |
| 3 | `startOfBearishLeg(leg)` | `getCurrentStructure` | (nenhum) | (nenhum) | `ta.change` | **Baixa** | One-liner. `ta.change(x) == -1`. |
| 4 | `startOfBullishLeg(leg)` | `getCurrentStructure` | (nenhum) | (nenhum) | `ta.change` | **Baixa** | One-liner. |
| 5 | `getCurrentStructure(size, equalHighLow=False, internal=False)` | `main` (3x) | `swingHigh/Low`, `internalHigh/Low`, `equalHigh/Low`, `trailing`, `atrMeasure` | mesmas + `currentAlerts.equalHighs`, `currentAlerts.equalLows` | `time`, `bar_index`, `low`, `high`, `math.abs`, `na` | **Média-alta** | Função-chave: detecta swings e atualiza pivots. Tem 3 modos (swing, internal, equal-highs-lows) controlados por flags. Atualiza `trailing` apenas no modo swing. |
| 6 | `deleteOrderBlocks(internal=False)` | `main` (2x) | `swingOrderBlocks`, `internalOrderBlocks`, `bearish/bullishOrderBlockMitigationSource` | mesmas + `currentAlerts.*OrderBlock` | (nenhuma direta — opera sobre listas) | **Baixa-média** | Loop sobre OBs ativos, marca como mitigados se preço cruzou. **NÃO vetorizável trivialmente** (estado entre iterações). |
| 7 | `storeOrdeBlock(pivot, internal=False, bias=na)` | `displayStructure` | `parsedHighs/Lows__global__`, `times__global__`, `swing/internalOrderBlocks` | `swing/internalOrderBlocks` | `array.slice`, `array.indexof`, `array.max`, `array.min`, `array.get`, `array.unshift`, `array.pop`, `array.size` | **Média** | **Esta é a função que dispara o bug 7 do PyneCore** (`array.indexof` em `SequenceView`). Em pandas: `df.iloc[start:end]['parsed_high'].idxmax()`. |
| 8 | `displayStructure(internal=False)` | `main` (2x) | `internalHigh/Low`, `swingHigh/Low`, `internalTrend`, `swingTrend`, OHLC | mesmas + `currentAlerts.*BOS/CHoCH` | `ta.crossover`, `ta.crossunder`, `math.max`, `math.min` | **Alta** | **Função mais densa do arquivo.** Detecta BOS/CHoCH bullish e bearish, atualiza trend, dispara `storeOrdeBlock`. Tem lógica de "filtro de confluência" via `bullishBar`/`bearishBar`. |
| 9 | `deleteFairValueGaps()` | `main` | `fairValueGaps__global__`, OHLC atual | `fairValueGaps__global__` | (nenhuma direta) | **Baixa** | Loop sobre FVGs ativos, marca como mitigados. |
| 10 | `drawFairValueGaps()` | `main` | `fairValueGaps__global__`, dados do TF input | `fairValueGaps__global__`, `currentAlerts.bullish/bearishFairValueGap` | `request.security`, `barmerge.lookahead_on`, `timeframe.change`, `ta.cum`, `math.abs`, `bar_index` | **Alta** | **Multi-timeframe via `request.security` com `lookahead_on`.** Usa tupla de 8 valores (bug 6 do PyneCore). **v1.1: assinatura na portagem é diferente — recebe 2 DataFrames pré-mergeados pelo Freqtrade.** Ver Onda 7. |
| 11 | `updateTrailingExtremes()` | `main` | `trailing`, OHLC | `trailing` | `math.max`, `math.min` | **Baixa** | Atualiza extremos absolutos. |
| 12 | `main(...)` | (entry point) | tudo | tudo | todas as anteriores + `script.indicator`, `input.*`, `ta.atr`, `ta.cum`, `ta.tr`, `array.new*`, `array.push` | n/a | Orquestrador. Setup de Persistent + sequência de 9 chamadas no final. |

### 3.2 Sequência de execução por candle (do final do `main`)

```
1. updateTrailingExtremes()              ← atualiza trailing top/bottom
2. deleteFairValueGaps()                 ← invalida FVGs mitigados
3. getCurrentStructure(50, False, False) ← detecta swing pivots (length=50)
4. getCurrentStructure(5, False, True)   ← detecta internal pivots (length=5)
5. getCurrentStructure(3, True, False)   ← detecta EQH/EQL pivots (length=3)
6. displayStructure(True)                ← BOS/CHoCH internal + cria internal OB
7. displayStructure(False)               ← BOS/CHoCH swing + cria swing OB
8. deleteOrderBlocks(True)               ← invalida internal OBs mitigados
9. deleteOrderBlocks(False)              ← invalida swing OBs mitigados
10. drawFairValueGaps()                  ← detecta novos FVGs
11. (16x alertcondition)                 ← expõe os flags de currentAlerts
```

**Implicação para portagem:** essa sequência define a ordem lógica das transformações sobre o DataFrame na função `analyze()`. **Não pode ser mudada** — há dependências de ordem (ex: `displayStructure` precisa que `getCurrentStructure` já tenha rodado para ter pivots atualizados).

### 3.3 Grafo de dependências internas

```
main
├─ updateTrailingExtremes
├─ deleteFairValueGaps
├─ getCurrentStructure (3x, com flags diferentes)
│   ├─ leg
│   ├─ startOfNewLeg
│   ├─ startOfBullishLeg
│   └─ startOfBearishLeg
├─ displayStructure (2x: internal=True, internal=False)
│   └─ storeOrdeBlock
├─ deleteOrderBlocks (2x)
└─ drawFairValueGaps
```

**Profundidade máxima de chamada:** 3 níveis (`main → displayStructure → storeOrdeBlock`).

**Observação importante:** `leg`, `startOfNewLeg`, `startOfBullishLeg`, `startOfBearishLeg` só são chamados de **dentro de `getCurrentStructure`**. Isso significa que podem ser inlinados ou ficar como helpers privados de um único módulo `pivots.py`.

---

## 4. Inventário de primitivas Pine usadas

Cada primitiva do `pynecore.lib` que aparece no LuxAlgo, com mapeamento conceitual para Python idiomático.

### 4.1 Operadores de série temporal (família `ta.*`)

| Primitiva Pine | Onde aparece | Equivalente pandas/numpy | Notas |
|---|---|---|---|
| `ta.atr(200)` | Setup do `main` | `df['atr_200'] = (df['high'] - df['low']).rolling(200).mean()` (versão simples) ou usar `pandas-ta` para ATR Wilder | ATR Wilder é mais correto. Usar `pandas-ta` ou implementar manualmente. |
| `ta.cum(x)` | Setup, `drawFairValueGaps` | `df['x'].cumsum()` | Cumulativo do início ao candle atual. |
| `ta.tr` | Setup | `np.maximum.reduce([h-l, abs(h-c.shift(1)), abs(l-c.shift(1))])` | True Range. |
| `ta.change(x)` | `startOfNewLeg`, `startOfBullishLeg`, `startOfBearishLeg` | `x.diff()` ou `x - x.shift(1)` | Diferença entre candle atual e anterior. |
| `ta.highest(N)` | `leg` | `df['high'].rolling(N).max().shift(1)` | **Atenção:** o `.shift(1)` é crítico para evitar lookahead. |
| `ta.lowest(N)` | `leg` | `df['low'].rolling(N).min().shift(1)` | Idem. |
| `ta.crossover(a, b)` | `displayStructure` | `(a > b) & (a.shift(1) <= b.shift(1))` | Cruzamento bullish. |
| `ta.crossunder(a, b)` | `displayStructure` | `(a < b) & (a.shift(1) >= b.shift(1))` | Cruzamento bearish. |

### 4.2 Operadores de array/lista

| Primitiva Pine | Onde aparece | Equivalente pandas/numpy | Notas |
|---|---|---|---|
| `array.new(0, NA(T))` | Setup | `[]` ou `collections.deque()` | Lista vazia tipada. |
| `array.new_float()` | Setup | `[]` ou `np.array([], dtype=float)` | Lista vazia de floats. |
| `array.new_int()` | Setup | `[]` ou `np.array([], dtype=int)` | Lista vazia de ints. |
| `array.push(arr, x)` | Setup do `main` (a cada candle) | `arr.append(x)` | Adicionar ao final. **Em pandas vetorizado, essa primitiva desaparece** — `parsedHighs__global__` vira coluna `df['parsed_high']`. |
| `array.unshift(arr, x)` | `storeOrdeBlock`, `drawFairValueGaps` | `arr.insert(0, x)` | Adicionar ao início. |
| `array.pop(arr)` | `storeOrdeBlock` (cap de 100) | `arr.pop()` | Remover do final. |
| `array.remove(arr, idx)` | `deleteOrderBlocks`, `deleteFairValueGaps` | `arr.pop(idx)` | Remover por índice. |
| `array.slice(arr, start, end)` | `storeOrdeBlock` | `arr[start:end]` | Slice. |
| `array.size(arr)` | `storeOrdeBlock` | `len(arr)` | Tamanho. |
| `array.get(arr, idx)` | `storeOrdeBlock` | `arr[idx]` | Acesso indexado. |
| `array.indexof(arr, x)` | `storeOrdeBlock` | `arr.index(x)` ou `np.argmax/argmin` | **Bug 7 do PyneCore — esta é a primitiva que quebrou.** Em Python puro funciona. |
| `array.max(arr)` | `storeOrdeBlock` | `max(arr)` ou `np.max(arr)` | Máximo. |
| `array.min(arr)` | `storeOrdeBlock` | `min(arr)` ou `np.min(arr)` | Mínimo. |

### 4.3 Operadores matemáticos

| Primitiva Pine | Onde aparece | Equivalente | Notas |
|---|---|---|---|
| `math.max(a, b)` | `displayStructure`, `updateTrailingExtremes` | `max(a, b)` ou `np.maximum(a, b)` | Trivial. |
| `math.min(a, b)` | `displayStructure`, `updateTrailingExtremes` | `min(a, b)` ou `np.minimum(a, b)` | Trivial. |
| `math.abs(x)` | `getCurrentStructure`, `drawFairValueGaps` | `abs(x)` ou `np.abs(x)` | Trivial. |

### 4.4 Multi-timeframe e tempo

| Primitiva Pine | Onde aparece | Equivalente pandas/numpy | Notas |
|---|---|---|---|
| `request.security(sym, tf, expr, lookahead=...)` | `drawFairValueGaps` | **Não existe equivalente direto.** Ver §5.1 deste documento. | **v1.1: resolvido pela arquitetura Freqtrade.** A engine recebe DataFrame já mergeado pelo `merge_informative_pair`, sem necessidade de `request.security` interno. |
| `barmerge.lookahead_on` | `drawFairValueGaps` | **Proibido em pandas/Freqtrade.** | **v1.1: Conflito B fechado.** `lookahead-analysis` do Freqtrade detecta `shift(-N)` como bias. Não replicar. |
| `timeframe.change(tf)` | `drawFairValueGaps` | Detectar borda de candle no TF maior. Em Freqtrade, a função `merge_informative_pair` já lida com isso. | Trivial em pandas (`df['tf_changed'] = df['tf_high'] != df['tf_high'].shift(1)`). |
| `time` | Setup, `getCurrentStructure`, `updateTrailingExtremes` | `df['date']` (timestamp) | Trivial. |
| `time[N]` | `getCurrentStructure` | `df['date'].shift(N)` | Indexação histórica. |
| `bar_index` | Setup, `getCurrentStructure`, `storeOrdeBlock`, `drawFairValueGaps` | `np.arange(len(df))` ou `df.index` (se for RangeIndex) | Posicional. |
| `bar_index[N]` | `getCurrentStructure` | `df.index - N` (com cuidado de bordas) | Idem. |

### 4.5 Operadores de OHLC (séries built-in do Pine)

| Primitiva Pine | Equivalente pandas | Notas |
|---|---|---|
| `open` / `high` / `low` / `close` | `df['open']` / `df['high']` / `df['low']` / `df['close']` | Trivial. |
| `open[N]` / `high[N]` / `low[N]` / `close[N]` | `.shift(N)` | Indexação histórica. |

### 4.6 Inputs e infra do indicador

| Primitiva Pine | Onde aparece | Equivalente | Notas |
|---|---|---|---|
| `input(...)`, `input.int`, `input.float`, `input.string`, `input.timeframe` | Assinatura de `main` | Parâmetros de função Python ou config dict | Trivial. Ficam como argumentos da factory da engine. |
| `script.indicator(...)` | Decorador de `main` | (descartar) | Metadata do TradingView, sem equivalente. |
| `alertcondition(...)` | Final do `main` (16x) | (descartar) | **No-op no PyneCore** e descartável na portagem. Os booleans de `alerts` já são o output útil — ficam como colunas no DataFrame. |
| `na`, `NA(T)` | Várias | `None`, `np.nan`, ou `pd.NA` | Cuidado: comparações com `na` em Pine retornam `False` automaticamente. Em Python puro precisa de `is None` ou `np.isnan`. |
| `Persistent[T]` | Variáveis de estado | Atributo de objeto `EngineState` (escopo: única chamada de `analyze()`) | Trivial. |
| `udt` decorator | UDTs | `@dataclass` | Trivial. |
| `syminfo.tickerid` | `drawFairValueGaps` | Hardcoded em backtest, irrelevante na portagem | Trivial. |

---

## 5. Conflitos com o documento "SMC — Princípios e Legado"

Conflitos que **não são bugs do LuxAlgo** mas **gaps em relação ao framework SMC dogmático** do projeto. Status atualizado pela verificação Freqtrade.

### 5.1 Conflito A — Multi-timeframe não está modelado dentro do LuxAlgo

**Status v1.1: FECHADO.**

**O que o LuxAlgo faz:** opera no TF nativo do indicador. `request.security` aparece **apenas** no `drawFairValueGaps` para puxar dados do TF do FVG (que pode ser igual ou maior que o TF do indicador).

**O que o documento de princípios pede:** "4H define direção, 1H define zona, 15m dispara entrada" (Parte 2.4). Hierarquia decisória multi-TF.

**Resolução documentada (verificação Freqtrade §2):** multi-TF é responsabilidade da `IStrategy` via `@informative('4h')` + `@informative('1h')` + `populate_indicators` (15m). A engine SMC é chamada **3 vezes** com DataFrames diferentes — uma por TF — produzindo colunas próprias para cada um. O `merge_informative_pair` faz o merge automaticamente sem lookahead bias. **Engine SMC não precisa modelar multi-TF internamente.**

**Restrição estrutural relevante:** o `timeframe` da `IStrategy` deve ser o **menor** dos três (15m). 1H e 4H entram como informative. Não há outra opção (verificação Freqtrade §2.2).

### 5.2 Conflito B — `lookahead=barmerge.lookahead_on` no FVG

**Status v1.1: FECHADO.**

**O que o LuxAlgo faz:** `drawFairValueGaps` chama `request.security(..., lookahead=barmerge.lookahead_on)`, que explicitamente puxa dados do TF maior antes de o candle do TF maior fechar.

**O que o documento de princípios pede:** "Lookahead bias é o erro silencioso que destrói estratégias SMC" (Parte 5.3). Documenta `lookahead-analysis` como obrigatório.

**Resolução documentada (verificação Freqtrade §3):** `lookahead-analysis` do Freqtrade detecta `shift(-N)` como bias por método diferencial (compara baseline vs sliced dataframes). `lookahead_on` em Pine é equivalente direto a `shift(-1)` em pandas. **Decisão fechada: não replicar.** Ao portar `drawFairValueGaps`, usar dados do TF maior **somente após o candle daquele TF fechar** (atraso de 1 candle do TF maior em relação ao output do TradingView). Diferença documentada nos testes do golden dataset.

### 5.3 Conflito C — `equal highs/lows` no LuxAlgo ≠ `liquidity sweep` do framework SMC

**Status v1.1: ainda aberto.**

**O que o LuxAlgo faz:** detecta EQH/EQL como "topos/fundos próximos" via threshold (`equalHighsLowsThresholdInput`). Apenas marca a existência da zona de liquidez. **Não detecta a varrida.**

**O que o documento de princípios pede:** sweep como **gate condicional** com diferenciação de qualidade Setup A+/B (Parte 2.3). Sweep = preço **ultrapassa** o EQH/EQL e **fecha de volta**.

**Implicação:** a engine precisa de um módulo `liquidity_sweep.py` que **não existe no LuxAlgo**. Ele deve consumir os EQH/EQL detectados pelo LuxAlgo (ou pelo equivalente Python) e adicionar a detecção da varrida.

**Decisão pendente:** especificar a regra exata de detecção de sweep. Sugestão inicial baseada na literatura SMC: "candle cujo high ultrapassa o `equalHigh.currentLevel` por mais de X% do ATR e cujo close volta abaixo do `equalHigh.currentLevel`". O X% e a janela temporal viram parâmetros calibráveis em hyperopt. Resolver no briefing da Onda 8.

### 5.4 Não-conflito que parecia conflito — máquina de estados

**Status v1.1: refinado.**

A máquina de estados ARMED → PENDING → CONFIRMED **é responsabilidade conjunta** da engine SMC e da `IStrategy` do Freqtrade:

- **Engine SMC produz dados crus** (OBs ativos, FVGs ativos, BOS/CHoCH, sweeps, trends por TF, premium/discount). Isso é a fundação.
- **Submódulo `setup_state.py` (parte da engine)** consome dados crus + colunas multi-TF mergeadas, produz colunas auxiliares: `setup_id`, `setup_state` (`armed`/`pending`/`confirmed`/`invalidated`), `setup_direction` (`long`/`short`), `setup_zone_low`, `setup_zone_high`. Esse módulo é **opcional** — alguém pode usar a engine apenas para extrair dados crus.
- **`IStrategy` consome `setup_state`** em `populate_entry_trend` (transição para `confirmed` dispara entrada), em `order_filled` (ancora `setup_zone_low/high` em `trade.custom_data`), em `custom_stoploss` (lê ancoragem para SL estrutural), em `custom_exit` (verifica invalidação macro).

**Decisão arquitetural fechada:** `setup_state.py` mora em `smc_engine/`, não em `user_data/strategies/`. Razão: máquina de estados SMC é genérica e reutilizável; estratégias diferentes podem consumir o mesmo `setup_state` com lógicas de entrada distintas.

---

## 6. Plano de portagem em ordem de dependência

Ordem sugerida para implementar a engine, do mais isolado para o mais acoplado. Cada item vira candidato a PR cirúrgico próprio.

### Onda 1 — Fundações (sem dependências internas)

1. **`smc_engine/types.py`** — definir as 6 dataclasses equivalentes aos UDTs (`Pivot`, `Trend`, `Alerts`, `OrderBlock`, `FairValueGap`, `TrailingExtremes`).
2. **`smc_engine/state.py`** — definir `EngineState` com as 17 variáveis Persistent como atributos. Escopo: vida única durante uma chamada de `analyze()`.

**Validação:** instanciação + serialização (smoke test).

### Onda 2 — Operadores stateless e helpers vetorizáveis

3. **`smc_engine/operators.py`** (interno) — funções utilitárias que mapeiam primitivas Pine: `cross_over`, `cross_under`, `change`, `cum_sum`, `true_range`, `atr_wilder`. Tudo vetorizável em pandas.

**Validação:** testes unitários comparando contra `pandas-ta` ou outputs conhecidos.

### Onda 3 — Detecção de pivots (base de tudo)

4. **`smc_engine/pivots.py`** — porta `leg`, `startOfNewLeg`, `startOfBullishLeg`, `startOfBearishLeg`, `getCurrentStructure`. Esta é a função-chave do LuxAlgo: detecta swing/internal/equal pivots.

**Atenção lookahead (verificação Freqtrade §3.2):** `swing_highs_lows` precisa de N candles à direita para confirmar swing. Solução: publicar a coluna `swing_high` com atraso de N candles (swing detectado em X aparece na coluna somente em X+N). Documentar atraso explicitamente.

**Validação:** rodar contra `btc_4h_30days.csv`, comparar pivots detectados contra exportação manual do TradingView (golden dataset).

### Onda 4 — Trailing e premium/discount

5. **`smc_engine/trailing.py`** — porta `updateTrailingExtremes`. Stateful mas trivial.
6. **`smc_engine/premium_discount.py`** — **não existe no LuxAlgo**, mas é trivial: derivar Premium/Discount/Equilibrium do `trailing.top` e `trailing.bottom`.

**Validação:** assertions sobre faixa correta dada `(trailing_top, trailing_bottom, close)`.

### Onda 5 — Estrutura (BOS/CHoCH)

7. **`smc_engine/structure.py`** — porta `displayStructure` (BOS/CHoCH bullish e bearish, internal e swing).

**Validação:** golden dataset com candles onde BOS e CHoCH ocorrem no LuxAlgo TradingView.

### Onda 6 — Order Blocks

8. **`smc_engine/order_blocks.py`** — porta `storeOrdeBlock` e `deleteOrderBlocks`. **Esta é a função do bug 7 do PyneCore** — em Python puro `list.index()` ou `np.argmax/argmin` resolve trivialmente.

**Decisão pendente a fechar aqui:** sliding window vs full-history em `parsedHighs/Lows`. Recomendação inicial: `df.iloc[start:end]` com índices do DataFrame, sem lista global. Memória O(1) extra além do próprio DataFrame.

**Validação:** golden dataset.

### Onda 7 — Fair Value Gaps

9. **`smc_engine/fair_value_gaps.py`** — porta `drawFairValueGaps` e `deleteFairValueGaps`.

**v1.1 — assinatura concreta:**

```python
def detect_fair_value_gaps(
    df_base: pd.DataFrame,
    df_fvg_tf: pd.DataFrame | None = None,
    state: EngineState | None = None,
) -> pd.DataFrame:
    """
    Se df_fvg_tf is None: FVG no mesmo TF de df_base (caso comum).
    Se df_fvg_tf passado: FVG num TF maior (caso LuxAlgo com fairValueGapsTimeframeInput).
       O segundo DataFrame deve ter sido mergeado via merge_informative_pair antes,
       garantindo zero lookahead.
    """
```

**Conflito B aplicado:** **não replicar `lookahead_on`**. Confiar no merge feito pelo Freqtrade. Documentar atraso de 1 candle do TF maior em relação ao output do TradingView.

**Validação:** golden dataset, com nota explícita sobre o atraso.

### Onda 8 — Liquidity Sweep (novo, não está no LuxAlgo)

10. **`smc_engine/liquidity_sweep.py`** — **módulo novo**, especificado a partir do framework SMC. Consome os EQH/EQL do LuxAlgo e detecta a varrida.

**Decisão pendente:** especificar regra exata de detecção (briefing dedicado).

**Validação:** dataset com sweeps conhecidos (manualmente identificados em BTC 4H), assertion sobre detecção correta.

### Onda 9 — Orquestração e API pública da engine bruta

11. **`smc_engine/engine.py`** — função `analyze(dataframe, **params)` que recebe um `DataFrame` e retorna um `DataFrame` com colunas adicionadas. Internamente chama os módulos das ondas 3-8 na ordem correta.
12. **`smc_engine/__init__.py`** — exporta `analyze` como API pública principal, mais os módulos individuais para uso avançado.

**Validação:** rodar engine completa contra `btc_4h_30days.csv`, comparar **todos os 16 eventos** contra golden dataset do TradingView.

### Onda 9.5 — Máquina de estados (novo nas v1.1)

13. **`smc_engine/setup_state.py`** — consome o output de `analyze()` para um TF base + colunas multi-TF mergeadas (de `analyze()` rodado em outros TFs). Produz colunas: `setup_id`, `setup_state`, `setup_direction`, `setup_zone_low`, `setup_zone_high`, `setup_invalidation_reason` (quando aplicável).

**Validação:** dataset com sequências conhecidas de transições (ARMED → preço entra na zona → PENDING → ChoCH 15m → CONFIRMED). Assertions sobre a coluna `setup_state` candle-a-candle.

### Onda 10 — Integração com Freqtrade

14. **`user_data/strategies/SMCStrategy.py`** — `IStrategy` que consome a engine.

**v1.1 — esqueleto verificado documentalmente:**

```python
from freqtrade.strategy import IStrategy, informative, stoploss_from_absolute
from freqtrade.exchange import timeframe_to_prev_date
from smc_engine import analyze, compute_setup_state

class SMCStrategy(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = '15m'
    can_short = True
    use_custom_stoploss = True
    stoploss = -0.10  # hard limit; custom_stoploss define o real

    @informative('4h')
    def populate_indicators_4h(self, dataframe, metadata):
        return analyze(dataframe, mode='swing_only')

    @informative('1h')
    def populate_indicators_1h(self, dataframe, metadata):
        return analyze(dataframe, mode='full')

    def populate_indicators(self, dataframe, metadata):
        dataframe = analyze(dataframe, mode='internal_focus')
        # Após @informative o dataframe já tem colunas '_4h' e '_1h'.
        dataframe = compute_setup_state(dataframe)
        return dataframe

    def populate_entry_trend(self, dataframe, metadata):
        dataframe.loc[
            (dataframe['setup_state'] == 'CONFIRMED')
            & (dataframe['setup_direction'] == 'long'),
            ['enter_long', 'enter_tag']
        ] = (1, 'smc_confirmed_long')
        # idem para short
        return dataframe

    def order_filled(self, pair, trade, order, current_time, **kwargs):
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        trade_date = timeframe_to_prev_date(self.timeframe, trade.open_date_utc)
        trade_candle = dataframe.loc[dataframe['date'] == trade_date].squeeze()
        if not trade_candle.empty:
            trade.set_custom_data('setup_zone_low', float(trade_candle['setup_zone_low']))
            trade.set_custom_data('setup_zone_high', float(trade_candle['setup_zone_high']))
            trade.set_custom_data('setup_id', str(trade_candle['setup_id']))

    def custom_stoploss(self, pair, trade, current_time, current_rate,
                        current_profit, after_fill, **kwargs):
        zone_low = trade.get_custom_data('setup_zone_low')
        zone_high = trade.get_custom_data('setup_zone_high')
        if zone_low is None:
            return None
        sl_price = (zone_high * 1.001) if trade.is_short else (zone_low * 0.999)
        return stoploss_from_absolute(
            sl_price, current_rate,
            is_short=trade.is_short, leverage=trade.leverage
        )
```

---

## 7. Estratégia de validação por golden dataset

O documento "SMC — Princípios e Legado" diz que fidelidade ao LuxAlgo é não-negociável. A maneira concreta de provar fidelidade é:

1. **Golden dataset.** Carregar `btc_4h_30days.csv` no TradingView, aplicar o LuxAlgo SMC original, exportar:
   - Todos os swing highs/lows com timestamp e preço
   - Todos os internal highs/lows com timestamp e preço
   - Todos os EQH/EQL detectados
   - Todos os OBs (swing e internal) com timestamp, range e bias
   - Todos os FVGs com timestamp, range e bias
   - Todos os BOS/CHoCH com timestamp e tipo
2. **Estrutura do golden file:** JSON ou CSV versionado em `tests/golden/btc_4h_30days_luxalgo.json`.
3. **Teste de equivalência por módulo:** cada módulo da engine roda sobre o mesmo CSV, e seu output é comparado contra a fatia correspondente do golden.
4. **Tolerância:** match exato em timestamps; match com tolerância de 0.01% em preços (para acomodar diferenças de arredondamento entre Pine e Python).
5. **Para os Conflitos A/B/C:** o golden documenta o output do LuxAlgo original; os testes da engine podem ter assertions com nota explícita "diverge do LuxAlgo aqui porque [razão do princípio violado]". Conflito B em particular: golden registra FVGs do TradingView, testes esperam mesmo output **com atraso de 1 candle do TF maior**.

A geração do golden dataset é **trabalho manual** que precisa ser feito uma vez no início, antes da Onda 3. Sem ele, validar a portagem é cego.

---

## 8. Decisões pendentes consolidadas (atualizado v1.1)

| # | Decisão | Status v1.1 | Bloqueia onda |
|---|---|---|---|
| 1 | Verificação documental do Freqtrade | **FECHADA** (documento `VERIFICACAO_FREQTRADE.md`) | — |
| 2 | Sliding window vs lista full-history em `parsedHighs/Lows` | **Aberta** | Onda 6 — recomendação `df.iloc[start:end]` documentada |
| 3 | Conflito A — multi-TF é responsabilidade da `IStrategy` | **FECHADA** (verificação Freqtrade §2) | — |
| 4 | Conflito B — não replicar `lookahead_on` | **FECHADA** (verificação Freqtrade §3) | — |
| 5 | Conflito C — regra exata de Liquidity Sweep | **Aberta** | Onda 8 |
| 6 | Geração do golden dataset | **Aberta** | Onda 3 em diante |
| 7 (novo) | Onde mora `setup_state.py` (engine vs strategy) | **FECHADA** — dentro de `smc_engine/` como módulo opcional | Onda 9.5 |

---

## 9. O que esta Camada 1 NÃO contém

Por decisão explícita ("o objetivo é implementar, não documentar"):

- Pseudocódigo detalhado de cada função
- Plano de teste unitário por função
- Critério de validação granular
- Assinaturas Python finais (exceto `analyze()` em §6 Onda 9 e `detect_fair_value_gaps()` em §6 Onda 7)

Cada um desses vira **detalhamento Camada 2** sob demanda, no briefing do PR de portagem do módulo correspondente.

---

## 10. Changelog v1.0 → v1.1

Esta seção rastreia exatamente onde a verificação documental do Freqtrade tocou o mapa, para auditoria futura.

| Seção | Antes (v1.0) | Depois (v1.1) | Origem da mudança |
|---|---|---|---|
| §2 (Persistent) | Implicava listas globais persistindo entre candles | Esclarece que estado vive durante uma chamada de `analyze()` apenas; arrays globais viram colunas do DataFrame | Verificação Freqtrade §1.2 (vetorização sobre DataFrame inteiro) |
| §4.4 (`request.security`) | "Aqui mora a maior decisão arquitetural multi-TF" | "Não existe equivalente direto. Resolvido pela arquitetura Freqtrade" | Verificação Freqtrade §2 |
| §4.4 (`barmerge.lookahead_on`) | "(ver Conflito B)" | "Proibido em pandas/Freqtrade. Conflito B fechado" | Verificação Freqtrade §3 |
| §5.1 (Conflito A) | Decisão pendente | FECHADO — multi-TF na `IStrategy` via `@informative` | Verificação Freqtrade §2 |
| §5.2 (Conflito B) | Decisão pendente | FECHADO — não replicar; documentar atraso | Verificação Freqtrade §3 |
| §5.4 (Máquina de estados) | "Não é responsabilidade da engine" | Refinado — submódulo `setup_state.py` opcional dentro de `smc_engine/` | Verificação Freqtrade §5 (mapeamento SMC↔Freqtrade) |
| §6 Onda 7 (FVG) | Sem assinatura concreta | Assinatura concreta com 2 DataFrames; sem `lookahead_on` | Verificação Freqtrade §3 + §2.4 |
| §6 nova Onda 9.5 | (não existia) | `setup_state.py` formalizado como módulo da engine | Verificação Freqtrade §5 |
| §6 Onda 10 (IStrategy) | "Esta etapa depende da verificação documental" | Esqueleto verbatim verificado | Verificação Freqtrade §7.3 |
| §8 (Decisões pendentes) | 6 itens, sendo 4 abertos | 7 itens (1 novo), sendo 3 abertos | Consolidação geral |

---

**Fim do mapa Camada 1 v1.1.**

SHA-256 do arquivo fonte mapeado: `9433ca63fc85f5613f307d0964347193c98578f58daf10cdbb391a98b6bbf8b1`
Documento companion: `VERIFICACAO_FREQTRADE.md` (referência documental Freqtrade)

