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

5. **`smc_engine/trailing.py`** — porta `updateTrailingExtremes` e inclui
   Premium / Discount / Equilibrium como função pura sobre `trailing.top` /
   `trailing.bottom`.

**Nota (decisão de arquitetura, 2026-05-14):** Premium/Discount foi
**absorvido em `trailing.py`** em vez de ganhar módulo próprio
`premium_discount.py`. Razão: PD é função pura (sem estado próprio,
sem dependência fora de `trailing.top`/`trailing.bottom`), portanto
não justifica módulo separado. Ver `smc_engine/trailing.py` (constantes
`PD_ZONE_PREMIUM` / `PD_ZONE_DISCOUNT` e derivação inline da zona).

**Validação:** assertions sobre faixa correta dada `(trailing_top, trailing_bottom, close)`.

### Onda 5 — Estrutura (BOS/CHoCH)

7. **`smc_engine/structure.py`** — porta `displayStructure` (BOS/CHoCH bullish e bearish, internal e swing).

**Validação:** golden dataset com candles onde BOS e CHoCH ocorrem no LuxAlgo TradingView.

### Onda 6 — Order Blocks

8. **`smc_engine/order_blocks.py`** — porta `storeOrdeBlock` e `deleteOrderBlocks`. **Esta é a função do bug 7 do PyneCore** — em Python puro `list.index()` ou `np.argmax/argmin` resolve trivialmente.

**Decisão pendente a fechar aqui:** sliding window vs full-history em `parsedHighs/Lows`. Recomendação inicial: `df.iloc[start:end]` com índices do DataFrame, sem lista global. Memória O(1) extra além do próprio DataFrame.

**Validação:** golden dataset.

### Onda 7 — Fair Value Gaps

9. **`smc_engine/fvg.py`** — porta `drawFairValueGaps` e `deleteFairValueGaps`.

**Assinatura mergeada (Onda 7, PR #49):**

```python
def detect_fair_value_gaps(
    df: pd.DataFrame,
    *,
    auto_threshold: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Retorna (ledger, df_per_candle):
      - ledger: um row por FVG com lifecycle (`bar_time`, `t_creation`,
        `t_mitigation`, `t_invalidation`, `state ∈ {'active','mitigated'}`).
      - df_per_candle: df original + 4 colunas boolean agregadas
        (BULLISH/BEARISH × CREATED/MITIGATED).
    """
```

**Nota (alinhamento Mapa ↔ código mergeado):**

- **Nome do módulo:** `fvg.py` (não `fair_value_gaps.py`). Renomear
  pós-merge quebraria imports históricos por zero ganho funcional.
- **Parâmetro `df_fvg_tf`:** previsto na v1.1 do Mapa mas **movido para
  hook futuro Onda 7.3 (FVG MTF)**. A assinatura mergeada é mono-TF
  (`df` único). O hook está reservado e documentado nas
  **LIMITAÇÕES CONHECIDAS** do `fvg.py`. Ver §7.8 deste mapa
  (linha "FVG Multi-Timeframe").
- **Parâmetro `volatility_threshold`:** previsto na v1.1 mas **movido
  para hook futuro Onda 7.x**. Reservado nas LIMITAÇÕES CONHECIDAS.
  Ver §7.8 (linha "Volatility Threshold multiplicativo").
- **Parâmetro `state`:** não necessário — a engine FVG é stateless
  (DataFrame in, DataFrame+ledger out).

**Conflito B aplicado:** **não replicar `lookahead_on`**. Confiar no merge feito pelo Freqtrade. Documentar atraso de 1 candle do TF maior em relação ao output do TradingView.

**Validação:** golden dataset, com nota explícita sobre o atraso.

### Onda 8 — Liquidity Sweep (novo, não está no LuxAlgo)

10. **`smc_engine/liquidity_sweep.py`** — **módulo novo**, especificado a partir do framework SMC. Consome os EQH/EQL do LuxAlgo e detecta a varrida.

**Decisão pendente:** especificar regra exata de detecção (briefing dedicado).

**Validação:** dataset com sweeps conhecidos (manualmente identificados em BTC 4H), assertion sobre detecção correta.

### Onda 9 — Orquestração e API pública da engine bruta

11. **`smc_engine/engine.py`** — função `analyze(dataframe, **params)` que recebe um `DataFrame` e retorna um `DataFrame` com colunas adicionadas. Internamente chama os módulos das ondas 3-8 na ordem correta.
12. **`smc_engine/__init__.py`** — exporta `analyze` como API pública principal, mais os módulos individuais para uso avançado.

**Validação:** rodar engine completa contra `btc_4h_30days.csv`, comparar **todos os 22 tipos de evento** (conforme `tests/golden/schema/golden_schema.json:51-75`) contra golden ratificado.

**Nota (decomposição dos 22 tipos):** 4 BOS (bullish/bearish × internal/swing) + 4 CHoCH (bullish/bearish × internal/swing) + 8 OB (formed/mitigated × 4 variantes bullish/bearish×internal/swing) + 4 FVG (formed/mitigated × bullish/bearish) + 2 EQ (EQH/EQL). Total: 22 `event_type` enumerados no schema. PD zones (premium/equilibrium/discount) são tratadas separadamente em `zones[]` (3 `zone_type`).

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

O documento "SMC — Princípios e Legado" estabelece que fidelidade ao LuxAlgo
SMC é não-negociável. A maneira concreta de provar fidelidade é o golden
dataset descrito nesta seção.

### 7.1 Indicador de referência

**LuxAlgo - Smart Money Concepts** (gratuito) — referência canônica de
**match exato** da portagem. A engine deve detectar exatamente o que o
gratuito detecta, com tolerância ±1 candle (§7.4).

**LuxAlgo - Price Action Concepts™** (pago) — referência **conceitual
auxiliar** para escopo de ondas futuras. NÃO é referência de match da
portagem em curso porque tem 7 blocos adicionais (CHoCH+, Volumetric OB,
Breakers, Liquidity Grabs, Trendlines, Patterns, Imbalances expandidos)
que o gratuito não tem e a portagem só absorverá em ondas futuras
dedicadas.

Análise comparativa completa em
`docs/AVALIACAO_LUXALGO_PRICE_ACTION_CONCEPTS_v1.0.md`. Decisões de
absorção feature-a-feature ficam para os briefings das Ondas 5.5+
conforme decisão pendente §8 deste mapa.

### 7.2 Janela e densidade

- **Instrumento:** BTC-USDT-SWAP (OKX, mesmo provedor da produção).
- **Timeframe:** 4H.
- **Janela:** 720 candles 4H (~120 dias).
- **Timezone:** UTC (TradingView configurado em UTC antes da captura).
- **Densidade:** 6-8 screenshots cobrindo a janela completa, 90-120 candles
  por screenshot.

### 7.3 Escopo do golden

**Incluído:**

- BOS bullish/bearish (internal e swing)
- CHoCH bullish/bearish (internal e swing)
- OB formação e mitigação (internal e swing)
- FVG formação e mitigação
- EQH/EQL alerts
- Premium/Discount/Equilibrium zones

**Excluído:**

- Swing/internal/equal pivots por candle. Validados por testes sintéticos da
  Onda 3 (já mergeada). Razão: leitura visual humana de screenshots dá
  precisão de evento (±1 candle), não de candle exato. Pivots por candle
  exigem precisão de candle exato — incompatível com o método.
- Features exclusivas do Price Action Concepts pago (CHoCH+, Volumetric OB,
  Breakers, Liquidity Grabs, Trendlines, Patterns, Inverse/Double FVG, Volume
  Imbalance, Opening Gap).

### 7.4 Tolerância de match

**±1 candle (4 horas em TF 4H).** Os testes consumidores das Ondas 5+ devem
asseverar "este BOS foi detectado dentro de ±1 candle do timestamp esperado",
não match candle-exato.

### 7.5 Estrutura do golden

- **Localização:** `smc_freqtrade/tests/golden/`
- **CSV de OHLCV:** `data/btc_usdt_swap_4h_window.csv` (versionado por
  hash SHA-256 registrado em `meta.ohlcv_csv_sha256`).
- **JSON do golden:** `golden/btc_usdt_swap_4h_luxalgo_smc.json`.
- **Schema:** `schema/golden_schema.json` (JSON Schema draft-07).
- **Ferramentas:** `tools/golden_validator.py`, `tools/ohlcv_fetcher.py`.
- **README com fluxo:** `README.md`.
- **Output canônico engine-derived:** `tests/golden/golden/<nome>_engine_output.parquet`
  (formato definido na Onda 9, antecipado em smoke local até lá).
  Produzido pela engine ao longo das ondas, ratificado por screenshot
  do gratuito (§7.6).

### 7.6 Fluxo de produção e atualização

1. Marcelo configura TradingView em UTC e aplica o **LuxAlgo - Smart
   Money Concepts** em chart BTC-USDT-SWAP 4H OKX (mesmo CSV de
   `data/btc_usdt_swap_4h_window.csv`).
2. Engine SMC roda sobre o CSV, produz output canônico (§7.5).
3. Marcelo captura 6-8 screenshots do TradingView com o gratuito
   aplicado, cobrindo a janela completa, em ordem cronológica.
4. Sessão Claude.ai + Marcelo: cada screenshot é comparado com o
   output canônico. Match (±1 candle) → ratificado. Divergência →
   classificada em uma de três categorias:
   - **(a) Bug da engine** — abre PR de correção dedicado.
   - **(b) Diferença esperada por feature do pago** que a portagem
     ainda não absorveu (CHoCH+ até Onda 5.5, Volumetric OB até onda
     futura, etc.) — registrada em §7.8 abaixo, NÃO é bug.
   - **(c) Ambiguidade na referência** — Marcelo decide.
5. Após ratificação completa, Marcelo abre PR de "feat(golden):
   ratificar Onda N" anexando o output canônico ao
   `tests/golden/golden/`. Os screenshots ficam fora do repo
   (Drive de Marcelo).

Marcelo **não** estrutura o JSON manualmente. Engine produz; Marcelo
ratifica visualmente.

#### 7.6.1 — Regra de leitura visual canônica do LuxAlgo SMC

Para validar a engine contra screenshots do LuxAlgo, o timestamp do
evento detectado deve ser comparado contra a **extremidade direita**
dos marcadores visuais, conforme tabela:

| Marcador LuxAlgo | Ponto de comparação para validação engine |
|---|---|
| BOS / CHoCH | Fim da linha tracejada (candle do close-cross) |
| OB | Candle de trigger/validação (não o de origem da caixa) |
| FVG | Terceiro candle do padrão (quando o gap fica conhecido) |
| EQH / EQL | Último pivot que completa a condição de igualdade |
| HH / LH / HL / LL | Candle do pivot real (não o de confirmação) |

O label de texto do LuxAlgo (`BOS`, `CHoCH`, etc.) costuma estar no
ponto médio aproximado da linha — é referência visual apenas, **NÃO é
o timestamp do evento**.

Esta regra é canônica e se aplica ao spot-check de todas as ondas
(atual e futuras).

#### 7.6.2 — Caixas de Order Block: refinamento de §7.6.1

Para Order Blocks (caixas retangulares no LuxAlgo SMC), a regra
genérica de §7.6.1 ("OB | Candle de trigger/validação, não o de
origem da caixa") aplica-se como ponto de validação. Esta subseção
adiciona convenções específicas de label e mapeamento engine↔visual,
necessárias para o spot-check híbrido da Onda 6:

- **"Linha" =** caixa retangular do OB no chart, projetada
  horizontalmente da vela de origem (`bar_time` ≡ `t_origin`) até
  a vela de mitigação (`t_mitigation`), ou até a vela atual se o
  OB ainda estiver ativo.
- **"Fim da linha" =** `t_mitigation` quando preenchido; vela
  atual (ou último candle visível no screenshot) caso ativo.
- **"Ponto médio horizontal" (label) =** midpoint temporal de
  `[bar_time, t_mitigation or current]`. **NÃO** é midpoint de
  `[t_creation, t_mitigation]`. Razão: visualmente o LuxAlgo
  desenha a caixa a partir da vela parsed-extreme (= `bar_time` no
  UDT Pine, linhas 68-73 e 232), não da vela do break.
- **Comparação engine ↔ visual:**
  - `bar_time` da engine ↔ candle esquerdo da caixa visual (±1).
  - `t_mitigation` da engine ↔ candle direito visível onde a caixa
    termina / o preço penetra (±1).
  - `[bar_low, bar_high]` da engine ↔ topo/fundo verticais da
    caixa visual (tolerância ±5% do ATR).
- **Caixas ainda ativas no screenshot:** se a caixa se estende até
  o limite direito do screenshot, verificar que `t_mitigation is
  pd.NaT` no ledger; comparar `bar_time` contra a borda esquerda
  da caixa.

Esta subseção é referência canônica para o spot-check da Onda 6.
Aplica-se também a Breaker Blocks (Onda 6.2 futura) com o
refinamento adicional: caixa "breaker" tem **duas** extremidades
direitas — primeira mitigação (estado `'active' → 'breaker'`) e
remoção definitiva (estado `'breaker' → 'removed'`). Detalhar
quando Onda 6.2 for absorvida.

Para regras temporais detalhadas por tipo de marcador (BOS, CHoCH,
pivots, EQH/EQL, FVG, OB), tolerâncias e procedimento de
comparação engine ↔ visual, ver
`docs/REFERENCIA_VALIDACAO_VISUAL_LUXALGO.md`.

#### 7.6.3 — Caixas de Fair Value Gap: refinamento de §7.6.1

Para Fair Value Gaps (caixas pequenas no LuxAlgo SMC, tipicamente
preenchidas com cor translúcida), a regra genérica de §7.6.1
("FVG | Candle de criação = terceiro do padrão") aplica-se como
ponto de validação. Esta subseção adiciona convenções específicas
de label e mapeamento engine↔visual, necessárias para o spot-check
híbrido da Onda 7:

- **"Caixa do FVG" =** retângulo pequeno no chart, projetado
  horizontalmente do primeiro candle do padrão de 3 (= `bar_time`
  no UDT) até a primeira vela em que o gap é considerado mitigado
  (`t_mitigation`), ou até a vela atual se o FVG ainda estiver
  ativo.
- **"Fim da caixa" =** `t_mitigation` quando preenchido; vela
  atual (ou último candle visível no screenshot) caso ativo.
- **Mapeamento engine ↔ visual:**
  - `bar_time` da engine ↔ candle esquerdo da caixa visual (±1).
    NOTA: em FVG, `bar_time` ≠ `t_creation` por construção
    (`bar_time` = primeiro candle do padrão; `t_creation` =
    terceiro candle, quando o gap fica conhecido — ver decisão
    D5 do plan Onda 7).
  - `t_creation` da engine ↔ vela em que a caixa "aparece" no
    LuxAlgo (terceiro candle do padrão de 3), também ±1.
  - `t_mitigation` da engine ↔ candle direito onde a caixa termina
    no LuxAlgo (±1).
  - `[bottom, top]` da engine ↔ bordas inferior/superior da caixa
    visual (tolerância ±0.5% do preço).
- **Caixas ainda ativas no screenshot:** se a caixa se estende até
  o limite direito do screenshot, verificar `t_mitigation is
  pd.NaT` no ledger; comparar `bar_time` contra a borda esquerda
  da caixa.
- **Assimetria de armazenamento bullish vs bearish:** o ledger
  armazena `top > bottom` para ambos os lados por convenção
  geométrica normalizada (decisão Wave 7 §7.10). O Pine literal
  inverte para bearish; ver §7.10 para a justificativa e as
  implicações de mitigação.
- **Caixas "preenchidas parcialmente" no LuxAlgo:** wick que entra
  na caixa mas não atravessa a borda oposta NÃO mitiga o FVG na
  Wave 7 (semântica full-fill simétrica). Ledger reporta `state =
  'active'` nesses casos.

Esta subseção é referência canônica para o spot-check da Onda 7
(PR #49) e para spot-checks futuros das sub-ondas 7.1, 7.2, 7.3.

Para regras temporais detalhadas por tipo de marcador (BOS, CHoCH,
pivots, EQH/EQL, FVG, OB), tolerâncias e procedimento de
comparação engine ↔ visual, ver
`docs/REFERENCIA_VALIDACAO_VISUAL_LUXALGO.md`.

### 7.7 Para os Conflitos A/B/C do mapa

- **Conflito A (multi-TF):** fechado pela arquitetura Freqtrade (`@informative`).
  Golden é por TF, não cross-TF.
- **Conflito B (lookahead):** fechado. Golden registra FVGs do TradingView,
  testes esperam mesmo output **com atraso de 1 candle do TF maior**.
  Diferença documentada nos testes.
- **Conflito C (Liquidity Sweep):** ainda em aberto. Onda 8 vai especificar
  regra exata. O LuxAlgo gratuito **não detecta sweep** (só EQH/EQL como
  zona); a Onda 8 vai introduzir detecção própria. Golden NÃO contém
  Liquidity Sweep events — eles são especificados na Onda 8 e validados
  separadamente.

### 7.8 Divergências esperadas vs golden visual

Estas divergências entre output da portagem (referência: gratuito) e
screenshots do pago (caso o usuário do golden esteja no pago em vez
de no gratuito) são **diferenças documentadas, NÃO bugs**:

| Feature do pago | Onda da portagem em que entra | Status |
|---|---|---|
| CHoCH+ (Supported CHoCH) | Onda 5.5 | **Decidido** — hook em `structure.py` |
| Volumetric Order Blocks | Onda 6.1 | **Decidido** — hook `volumetric_intensity` em `order_blocks.py` |
| Breaker Blocks | Onda 6.2 | **Decidido** — hook campo `state` aceita `'breaker'` |
| OB Mitigation Method = Average | Onda 6.1 | **Decidido** — hook parâmetro `mitigation` aceita `'Average'` |
| OB Metrics (% volume total) | Onda 6.1 (extensão Volumetric) | Pendente — pós-processamento das colunas Volumetric OB |
| OB Internal Activity (Positive/Negative Association) | Onda 6.1 (extensão Volumetric) | Pendente — derivado de buy_volume vs sell_volume |
| Hide Overlap | Onda 6.x | Pendente — flag de pós-filtro em `order_blocks.py` |
| Strong/Weak Volume % | Onda 6.x | Pendente — análoga a Volumetric OB para swing extremos |
| Premium/Discount com 4 níveis | Onda 4.x refinamento | Pendente — Equilibrium ganha top e bottom em vez de linha única |
| Inverse FVG | Onda 7.1 | **Decidido** — hook campo `is_inverse` em `types.py` / `fvg.py` |
| Double FVG / Balanced Price Range | Onda 7.2 | **Decidido** — hook campo `is_double` em `types.py` / `fvg.py` |
| FVG Multi-Timeframe (`fairValueGapsTimeframeInput`) | Onda 7.3 | **Decidido** — hook parâmetro `df_fvg_tf` reservado na assinatura |
| Volatility Threshold multiplicativo (pago) | Onda 7.x | **Decidido** — hook parâmetro `volatility_threshold` reservado na assinatura |
| Liquidity Grabs (varrida) | Onda 8 | Já mapeada — decisão #5 |
| Liquidity Trendlines | Decisão de escopo | Categoria C |
| Chart Pattern Detection | Decisão de escopo | Categoria C |
| Volume Imbalance / Opening Gap | **Excluído** (perpetual swap 24/7) | Recomendação técnica AVALIACAO §4.5 |

Esta tabela é a fonte da verdade para "o que esperar de divergência
visual" e é atualizada a cada onda que absorve uma feature.

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

### 7.10 Divergências intencionais da portagem vs LuxAlgo (gratuito ou pago, conforme a feature)

Categoria distinta de §7.8 (features do pago não implementadas) e
§7.9 (dogma SMC vs LuxAlgo gratuito): divergências entre a
**portagem Python** e o **LuxAlgo gratuito (Pine literal)** que
foram introduzidas conscientemente durante uma onda, com
justificativa documentada.

**Princípio canônico (releitura de §7.1)**: a portagem prioriza
fidelidade ao LuxAlgo gratuito sobre fidelidade ao dogma SMC. Mas
quando uma decisão de implementação técnica (vetorização,
consistência geométrica, normalização de schema) gera divergência
inevitável do Pine literal, a divergência é registrada aqui com
plano de validação empírica.

**Divergências registradas**:

| # | Divergência | Pine literal | Portagem | Onda | Validação |
|---|---|---|---|---|---|
| 1 | Bearish FVG mitigation semantics | First-touch (predicate `high > high[t]`, pois Pine armazena `top = high[t]`) | Full-fill simétrico (predicate `high > low[t-2]`, com convenção normalizada `top > bottom` para ambos os lados) | Onda 7 | 5 fvg_ids candidatos (8, 11, 15, 69, 70) do golden 4h 2026-01 a 2026-04 reservados para validação visual no TradingView (LuxAlgo gratuito); spot-check PR #49 reportou 9/9 match de estado nos 9 FVGs ratificados, mas V4/V5 não discriminam entre as duas semânticas |
| 2 | Breaker Block — ciclo de vida do registro morto | FluxCharts/PAC remove o breaker da lista ativa quando ele é invalidado pelo lado oposto (`bullishOrderBlocksList.remove(i)`); o registro deixa de existir | Preserva o registro no ledger com `state = 'breaker_broken'` e `t_invalidation` definido; nenhum registro é apagado, estado terminal é explícito | Onda 6.2 | Histórico imutável consultável pós-execução via ledger; mesma filosofia da Onda 6 (mitigação preserva `t_mitigation`) e do ledger de FVG da Onda 7. Golden 4h pós-Wave 6.2: 21 breakers no ledger (1 vivo `state == 'mitigated'` + 20 mortos `state == 'breaker_broken'`); LuxAlgo gratuito mostraria apenas o vivo |
| 3 | BPR — input FVGs divergem do ICT Concepts | `ICT Concepts [LuxAlgo]` constrói BPR sobre FVGs displacement-based (`body > meanBody`) | Compomos sobre FVGs SMC-portados (`auto_threshold` cumulativo do LuxAlgo SMC). Portamos o algoritmo de overlap (condições §3.1), não os inputs — os BPRs-membros divergem dos do ICT | Onda 7.2 | Golden 4h: 2 BPRs (1 UP, 1 DN), 4 FVGs com `is_double=True`. Spot-check visual contra ICT Concepts (`i_BPR=true`) requer considerar a divergência de membros |
| 4 | BPR — pareamento event-driven vs per-bar | `ICT Concepts` atualiza "último par" a cada barra | Pareamento event-driven: na criação de cada FVG, busca o oposto ativo mais recente. Funcionalmente alinhados para o caso "último par"; divergência só materializaria se múltiplos pares fossem relevantes (hook futuro) | Onda 7.2 | Equivalência funcional validada no golden 4h (mesmos 2 BPRs que o "último par" produziria). Nota Wave 9.5: BPR break/lifecycle é hook futuro aditivo |
| 5 | CHoCH+ — janela B1 usa último pivot confirmado | PAC reavalia a pré-condição contra o contexto de preço no instante do break (incremental) | Janela B1: o último pivot oposto **confirmado** antes do break (via `ffill().shift(1)` do evento HL/LH). Em transições rápidas, um pivot recente ainda não confirmado pode não estar refletido, mantendo um estado anterior | Onda 5.5 | Referência = PAC **pago**. 4/5 eventos internal do golden 4h ratificados na vírgula; 1 divergência (#699, 2026-04-27 12:00): pivot âncora confirmado 16 candles antes, durante alta com higher highs não-confirmados → portagem marca CHoCH+ bearish que o PAC não desenha. Não é lookahead (pivot já confirmado); é diferença de expiração da janela. Benigna para uso como filtro de qualidade opcional |
| 6 | Volumetric OB `volume_pct` — denominador no instante de criação | PAC paid pode definir o percentual sobre uma janela de OBs renderizados no chart (subset diferente); sem código de referência PAC paid disponível | Fórmula derivada da definição PAC verbatim: `volume_pct_X = volume_total_X / sum(volume_total_Y para Y ativo em T_X)`, onde "ativo em T_X" = `t_creation_Y <= T_X AND (t_mitigation_Y is NaT OR t_mitigation_Y > T_X)`. Denominador computado no instante de criação sobre OBs ativos naquele instante (lookahead-safe). Fórmulas volumétricas (`volume_bullish`/`volume_bearish`/`volume_total`) derivadas verbatim do Pine FluxCharts "Volumized Order Blocks" (MPL 2.0) | Onda 6.1 | Sem código PAC paid para validação direta. Fórmulas FluxCharts verificáveis no TradingView (indicador gratuito). `volume_pct` é aditivo e não afeta os campos existentes |

**Quando uma divergência desta categoria é admissível**:

1. A divergência é descoberta e documentada DURANTE a onda (não
   pós-hoc), com decisão registrada nas LIMITAÇÕES CONHECIDAS do
   módulo.
2. O spot-check da onda reporta 0 blocking sob a semântica
   adotada.
3. Há plano explícito de validação empírica futura (candidatos
   discriminadores no golden) caso queira-se fechar a questão.

Cada entrada nesta tabela é candidata a revisão se validação visual
futura mostrar que o Pine literal está alinhado com a leitura visual
do LuxAlgo gratuito e a portagem não — nesse caso, reverter para a
semântica Pine.

---

## 8. Decisões pendentes consolidadas (atualizado v1.1)

| # | Decisão | Status v1.1 | Bloqueia onda |
|---|---|---|---|
| 1 | Verificação documental do Freqtrade | **FECHADA** (documento `VERIFICACAO_FREQTRADE.md`) | — |
| 2 | Sliding window vs lista full-history em `parsedHighs/Lows` | **FECHADA na Onda 6**: sliding window via `df.iloc[start:end]`, sem lista global. Memória O(1) extra além do próprio DataFrame. Confirmado em briefing Onda 6 §2 P5. | — |
| 3 | Conflito A — multi-TF é responsabilidade da `IStrategy` | **FECHADA** (verificação Freqtrade §2) | — |
| 4 | Conflito B — não replicar `lookahead_on` | **FECHADA** (verificação Freqtrade §3) | — |
| 5 | Conflito C — regra exata de Liquidity Sweep | **Aberta** | Onda 8 |
| 6 | Geração do golden dataset | **FECHADA — método engine-derived + spot-check híbrido (gratuito match, pago conceitual) registrado em §7** | Onda 3 em diante |
| 7 (novo) | Onde mora `setup_state.py` (engine vs strategy) | **FECHADA** — dentro de `smc_engine/` como módulo opcional | Onda 9.5 |
| 8 (novo) | Onda 5.5 — incluir CHoCH+ baseado em failed HH/LL detectado por pivots da Onda 3 | Aberta | Onda 5.5 (futura) |

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
| §7 (Validação golden) | "comparar contra exportação manual do TradingView" sem precisar versão | Reescrita completa fixando indicador (gratuito), janela, escopo, tolerância, fluxo, exclusões | PR Golden Infra (Mai/2026) |

---

## 11. Histórico de revisões pós-v1.1

Patches documentais aplicados ao Mapa após a publicação da v1.1, sem
bump de versão (não alteram VERSION nem código de produção).

- **2026-05-14 — Patch documental pré-Onda 9**
  - §6 Onda 4: remoção de `premium_discount.py` (absorvido em `trailing.py`).
  - §6 Onda 7: nome do módulo (`fvg.py`) e assinatura
    (`detect_fair_value_gaps(df, *, auto_threshold=False) -> tuple[df,df]`)
    alinhados ao código mergeado na Onda 7 (PR #49). `df_fvg_tf` movido
    para hook Onda 7.3; `volatility_threshold` movido para hook Onda 7.x.
  - §6 Onda 9: "16 eventos" → "22 tipos de evento", alinhado ao schema
    canônico `tests/golden/schema/golden_schema.json`.

---

## 12. Issues abertas pós-Onda 9

Issues técnicas e documentais identificadas durante o spot-check da
Onda 9, formalmente abertas para reinvestigação em ondas futuras.
Nenhuma é bloqueante para a evolução do projeto — a engine
`analyze()` foi ratificada com 226 events + 34 zones (PR #59).

### 12.1. ob_id=7 — Divergência visual isolada (candle 184)

**Categoria:** Possível divergência semântica em `detect_structure`
ou interpretação visual.
**Origem:** Spot-check Onda 9, caso 1 dos 5 candles validados
manualmente por Marcelo.
**Estado da engine:** ob_bearish_internal_formed em
`t_creation=2026-01-31T16:00:00Z`, `bar_high=84690.20`,
`bar_low=80918.10`, `state='active'`.

**Observação visual reportada:** caixa internal bearish
aproximadamente em 86k-86.5k (range ~500 pontos), left edge
próximo do candle 184. Bounds engine apontam para 80.9k-84.7k
(range 3772 pontos).

**Diagnóstico já feito:**
- Engine matematicamente correta. Range 3772 = range intrabar
  natural do candle 174 (O=84603,80, H=84690,20, L=80918,10,
  C=82631,80).
- Janela `[pivot_pos:break_pos)` = [174:184) confirmada equivalente
  a `parsedHighs.slice(p_ivot.barIndex, bar_index)` do Pine.
- Pivot lido via `ffill()` em pos=184 retorna corretamente 174 (5
  candles após confirmação `pivot_internal_length=5`).
- Hipóteses H1-H5 originais e H4' (ffill amplo) **descartadas
  empiricamente** (correlação gap×range = 0,08).

**Hipóteses remanescentes para reinvestigação:**
1. `detect_structure` pode disparar BOS bearish em candle diferente
   do Pine TradingView, consumindo pivot anterior (ex.: pivot=149,
   low=86033,50, vigente até pos=178) — divergência estaria
   upstream, não em `_emit_create_record`.
2. Caixa em ~86k observada por Marcelo pode ser de outro OB ativo
   visualmente próximo, não ob_id=7.
3. Interpretação visual pode ter confundido caixa internal com
   outro tipo (Swing, FVG, PD zone).

**Plano de resolução:**
- Re-validação manual focada em chart fresco com janela estendida
  pós-2026-04-30, ou
- Análise detalhada com Marcelo das caixas visíveis no candle 184
  com zoom máximo no TradingView, ou
- Investigação algorítmica focada em `detect_structure` linha por
  linha contra o Pine `displayStructure` (luxalgo_smc_compute_only.py
  linhas 238-272).

**Não-bloqueante.** Engine produz histórico imutável correto; o
problema, se existir, está em rendering visual rolling do LuxAlgo
ou em interpretação de screenshot. Onda 10 (IStrategy Freqtrade)
pode prosseguir.

### 12.2. EQH/EQL — **RESOLVIDO (Wave 8.2 canônica; 0-alerts no golden por ATR(200) warmup, esperado)**

**Categoria:** Divergência algorítmica em `smc_engine/pivots.py`.
**Origem:** Spot-check Onda 9 (Apêndice A do GPT-5).
**Status:** **RESOLVIDO.** Wave 8.2 (PR #62, commit fde4607)
reescreveu EQH/EQL fiel ao Pine SMC Concepts. A fórmula está
canonicamente correta. O 0-alerts sobre o golden 720 candles tem
causa raiz CONHECIDA E ESPERADA: ATR(200) warmup.

**Lição aprendida (Wave 8.1 → 8.2):**
A Wave 8.1 portou por engano a fórmula do indicador **`ICT
Concepts`** (banda dinâmica `atr(10)/a` + 3+ swings same-direction).
O EQH/EQL canônico vem do **`SMC Concepts`** (indicador gratuito
distinto), cujo Pine compilado está em
`tools/pynecore-validation/luxalgo_smc_compute_only.py` linhas
89-90, 124, 155-195:

```python
# Pine SMC Concepts (canônico):
equalHighsLowsLengthInput = input.int(3, 'EQH/EQL Bars', minval=1)
equalHighsLowsThresholdInput = input.float(0.1, minval=0, maxval=0.5)
atrMeasure = ta.atr(200)
# getCurrentStructure(equalHighsLowsLengthInput, True):
if equalHighLow and abs(p_ivot.currentLevel - high[size]) < equalHighsLowsThresholdInput * atrMeasure:
    currentAlerts.equalHighs = True
p_ivot.lastLevel = p_ivot.currentLevel
p_ivot.currentLevel = high[size]
```

i.e., compara o pivot novo APENAS contra o pivot imediatamente
anterior (`currentLevel`), com threshold ESTÁTICO `0.1 × atr(200)`.

**SMC Concepts ≠ ICT Concepts.** Não são intercambiáveis. Tabela
comparativa:

| Aspecto | Wave 8.1 (ICT Concepts — ERRADA) | Wave 8.2 (SMC Concepts — CANÔNICA) |
|---|---|---|
| Pivots comparados | 3+ dentro de banda | 2 consecutivos (currentLevel vs novo) |
| Threshold | dinâmico `atr/a` (a=10/margin) | estático `0.1 × atr(200)` |
| Lookback | 50 pivots same-direction | apenas o pivot imediatamente anterior |
| ATR | `atr(10)` | `atr(200)` |

**Estado atual (Wave 8.2):**
- Função `detect_eqh_eql()` reescrita fiel ao Pine SMC Concepts.
- 4 parâmetros da Wave 8.1 removidos do `SMCConfig`
  (`eq_atr_length`, `eq_margin`, `eq_lookback_pivots`, `eq_min_pivots`).
  Reusa `pivot_equal_threshold=0.1` e `pivot_equal_length=3` (Wave 3).
- ATR length=200 hardcoded em `EQ_ATR_LENGTH_CANONICAL` (fiel ao
  Pine `ta.atr(200)`).
- Colunas removidas: `equal_*_band_high`, `equal_*_band_low`,
  `equal_*_pivot_count` (faziam sentido só na fórmula de banda).
- Colunas mantidas: `equal_*_alert`, `equal_*_level_midpoint`,
  `equal_*_pivot_indices` (par dos 2 pivots).

**Resultado sobre o golden 720 candles 4H (Wave 8.2):**
- **0 EQH** + **0 EQL** alerts detectados (regrediu ao estado
  pré-Wave-8.1, mas agora por motivo conhecido e canônico).
- Os 226 events + 34 zones ratificados em Onda 9 permanecem
  **inalterados em quantidade e identidade** (EQH/EQL nunca
  contribuíram para esses 226).
- Ledger vazio em `tests/golden/wave8_2_eqheql_events.csv`;
  README adjacente
  (`tests/golden/wave8_2_eqheql_events.README.md`) documenta
  diagnóstico quantitativo.

**Análise do gap vs ground truth:**

Dos 5 níveis de **alta confiança** do briefing Wave 8.2 §5:

| Ground truth | Candle | ATR(200) NaN? | Detectado? |
|---|---|---|---|
| EQL ~94.4k @ 15 jan | ~84 | sim | não |
| EQH ~89.3k @ 27-28 jan | ~160 | sim | não |
| EQH ~79.1k @ 1-2 fev | ~190 | sim | não |
| EQH ~68.8k @ 27 fev | ~340 | não | não (diff ~2k+ USD vs thresh ~120) |
| EQH ~67.2k @ 3 abr | ~570 | não | não (diff 150 USD vs thresh 110) |

ATR(200) só estabiliza em idx 199 (~3 fev), mascarando 3 dos 5
níveis. Os 2 restantes (pós-warmup) não casam pela margem do
threshold canônico (`0.1 × atr200 ≈ 100-130 USD` vs movimentos
típicos entre pivots equal-length de 500-3000 USD na janela).

**Causa raiz confirmada (investigação read-only pós-merge):**

Diagnóstico via script read-only sobre o golden provou:

1. Pivots equal-length CORRETOS — contagem por modo (swing=5,
   internal=48, equal=71 highs) segue a progressão esperada de
   detecção de pivots. Wave 3 (fundação) está sã. Confirmado também
   indiretamente: BOS/CHoCH (que consomem swing/internal) bateram
   100% no spot-check Onda 5 e Onda 9.

2. Fórmula 8.2 CANÔNICA — fiel ao Pine SMC Concepts.

3. **Causa do 0-alerts: ATR(200) warmup.** O golden tem 720 candles
   começando 1 jan 2026; os primeiros ~199 estão em warmup do
   ATR(200). Os EQH/EQL de alta confiança do ground truth (94.4k,
   89.3k, 79.1k — todos pré-3-fev) caem na zona de warmup, onde a
   fórmula suprime alert por ATR NaN/instável. O Pine no TradingView
   roda sobre histórico completo (ATR estável). Mesma fórmula,
   contexto de dados diferente.

**Implicação:** EQH/EQL funcionará corretamente em produção (daemon
24/7 com histórico longo, ATR sempre estável). A limitação é
exclusiva do golden curto.

**Item não-bloqueante registrado:** estender o golden com ~200
candles de warmup pré-janela (out-dez 2025) para validar EQH/EQL
contra o ground truth numa janela futura. Sem prioridade —
EQH/EQL não bloqueia nenhuma onda do caminho crítico.

**Lição de processo:** (a) validar a equivalência conceitual da
fonte antes de portar fórmula (SMC Concepts ≠ ICT Concepts);
(b) fazer spot-check ANTES do merge, não depois; (c) ATR de período
longo (200) exige janela de dados com warmup suficiente.

### 12.3. Inconsistência `meta.scope_included` no schema canônico

**Categoria:** Inconsistência documental no template do gerador
golden.
**Origem:** Observação durante revisão do JSON ratificado PR #59.

**Sintoma:**
`meta.scope_included` no template emitido por
`tests/golden/tools/generate_golden_engine_output.py` lista:

```
"EQH/EQL alerts"
```

Como tipo coberto pelo schema. Mas empiricamente esta janela
produziu **zero** alerts (vide §12.2), e o `ratification_notes`
documenta isso como dívida.

**Plano de resolução:**
- Opção A: Manter `scope_included` como está (declaração de
  intenção de cobertura, não de presença na janela específica), e
  apenas referenciar §12.2 quando aplicável.
- Opção B: Ajustar template do gerador para distinguir "scope
  conceitual" (tipos cobertos pelo schema) vs "scope efetivo"
  (tipos com pelo menos 1 ocorrência na janela). Implicaria PR
  pequeno em `generate_golden_engine_output.py`.

**Decisão preferencial:** Opção A (mais simples, não há perda de
informação porque §12.2 já cobre a divergência específica). PR
opcional para a Opção B fica disponível como melhoria menor.

**Não-bloqueante.** Apenas dívida documental.

---

### Resumo §12

| Issue | Categoria | Bloqueante | Onda candidata para resolução |
|---|---|---|---|
| 12.1 ob_id=7 | Divergência visual isolada | Não | Pós-Onda 10 ou em janela fresca |
| 12.2 EQH/EQL formula | RESOLVIDO (Wave 8.2 canônica; 0-alerts no golden = ATR warmup, esperado) | Não | Resolvido. Validação opcional: golden com warmup pré-janela |
| 12.3 scope_included | Documental | Não | Melhoria opcional |

---

**Fim do mapa Camada 1 v1.1.**

SHA-256 do arquivo fonte mapeado: `9433ca63fc85f5613f307d0964347193c98578f58daf10cdbb391a98b6bbf8b1`
Documento companion: `VERIFICACAO_FREQTRADE.md` (referência documental Freqtrade)

