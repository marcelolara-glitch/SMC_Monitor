# Verificação documental do Freqtrade — Referência canônica para SMC_Freqtrade

**Data:** 2026-05-03
**Fontes consultadas (4 páginas oficiais):**
1. https://www.freqtrade.io/en/stable/strategy-customization/
2. https://www.freqtrade.io/en/stable/strategy-callbacks/
3. https://www.freqtrade.io/en/stable/lookahead-analysis/
4. https://www.freqtrade.io/en/stable/strategy-advanced/

**Propósito:** substituir inferências sobre Freqtrade por **citações verbatim** da documentação oficial. Este documento é a base de evidência para fechar a Decisão Pendente #1 do mapa LuxAlgo Camada 1 e para desenhar a integração SMC↔Freqtrade nas próximas fases.

---

## 1. Modelo de execução de uma `IStrategy`

### 1.1 Hierarquia de funções por modo de execução

| Função | Quando é chamada | Modo de execução | Tipo de processamento |
|---|---|---|---|
| `populate_indicators(dataframe, metadata)` | Uma vez por backtest, ou a cada candle close em dry/live | "called once during backtesting" | Vetorizado sobre DataFrame inteiro |
| `populate_entry_trend(dataframe, metadata)` | Idem | Idem | Vetorizado sobre DataFrame inteiro |
| `populate_exit_trend(dataframe, metadata)` | Idem | Idem | Vetorizado sobre DataFrame inteiro |
| `bot_loop_start(current_time)` | "once per candle in backtest/hyperopt mode" / "every 5 seconds in dry/live" | Por candle no backtest | Lógica pair-independent |
| `custom_stoploss(pair, trade, current_time, current_rate, current_profit, after_fill)` | "Called for open trade every iteration (roughly every 5 seconds) until a trade is closed" | Por trade aberto | Stateful por trade |
| `custom_exit(pair, trade, current_time, current_rate, current_profit)` | Idem | Por trade aberto | Stateful por trade |
| `adjust_trade_position(trade, current_time, ...)` | "called for each candle in `timeframe` or `timeframe_detail`" | Por candle, por trade | Stateful por trade |
| `order_filled(pair, trade, order, current_time)` | "Called right after an order fills" | Evento discreto | Stateful por trade |
| `confirm_trade_entry(...)` | "right before placing a entry order" | Evento discreto | Validação |
| `leverage(...)` | Antes de abrir trade em futures | Evento discreto | Configuração |

### 1.2 Diferença crítica vetorizado vs callback

**Verbatim:** *"the main strategy functions (`populate_indicators()`, `populate_entry_trend()`, `populate_exit_trend()`) should be used in a vectorized way, and are only called once during backtesting, callbacks are called whenever needed. As such, you should avoid doing heavy calculations in callbacks to avoid delays during operations."*

**Implicação para arquitetura SMC:** trabalho pesado da engine SMC vai em `populate_indicators` (vetorizado, roda uma vez para o backtest inteiro). Callbacks recebem o DataFrame já analisado via `dp.get_analyzed_dataframe()` e fazem apenas leitura.

### 1.3 Trade open assumption

**Verbatim:** *"In backtesting, signals are generated on candle close. Trades are then initiated immediately on next candle open."*

**Implicação para máquina de estados SMC:** a transição CONFIRMED → trade real **não acontece no candle do sinal** — acontece no abertura do próximo candle. Há 1 candle de delay nativo. Importante para reconciliar timestamps no golden dataset.

---

## 2. Multi-timeframe — confirmação de viabilidade do Conflito A

### 2.1 Mecanismo via `informative_pairs()` + `merge_informative_pair()`

**Verbatim — informative_pairs como tuple:**

> *"The pairs need to be specified as tuples in the format `("pair", "timeframe")`, with pair as the first and timeframe as the second argument."*

```python
def informative_pairs(self):
    return [("ETH/USDT", "5m"),
            ("BTC/TUSD", "15m"),
            ]
```

**Verbatim — merge_informative_pair renomeia colunas automaticamente:**

> *"All columns of the informative dataframe will be available on the returning dataframe in a renamed fashion: 'date_1d', 'open_1d', 'high_1d', 'low_1d', 'close_1d', 'rsi_1d'"*

### 2.2 Limitação estrutural — TF informative > TF base

**Verbatim:**

> *"Using informative timeframes smaller than the main dataframe timeframe is not recommended with this method, as it will not use any of the additional information this would provide."*

**Implicação para SMC com 3 TF (15m, 1H, 4H):**
- O `timeframe` da `IStrategy` deve ser o **menor** dos três (15m).
- 1H e 4H entram via `informative_pairs()` ou via `@informative` decorator.
- **Não há outra opção arquitetural** — esta é uma restrição do Freqtrade.

### 2.3 Decorator `@informative` — alternativa idiomática

**Verbatim:**

```python
@informative('1h')
def populate_indicators_1h(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
    dataframe['rsi'] = ta.RSI(dataframe, timeperiod=14)
    return dataframe
```

> *"All decorated `populate_indicators_*` methods run in isolation, and do not have access to data from other informative pairs. However, all informative dataframes for each pair are merged and passed to main `populate_indicators()` method."*

**Implicação para SMC:** podemos rodar a engine SMC **3 vezes** (uma por TF) — uma em `populate_indicators_4h`, uma em `populate_indicators_1h`, uma em `populate_indicators` (15m). Cada uma escreve suas próprias colunas no DataFrame do TF respectivo. O `@informative` faz o merge automaticamente. O Conflito A do mapa fica resolvido por construção: **a engine não precisa de `request.security` porque o Freqtrade já faz multi-TF nativamente**.

### 2.4 Aviso explícito contra `.merge()` puro

**Verbatim:**

> *"don't use `.merge()` to combine longer timeframes onto shorter ones. Instead, use the [informative pair] helpers. (A plain merge can implicitly cause a lookahead bias as date refers to open date, not close date)."*

**Implicação:** a engine SMC **não pode fazer merge de TF internamente**. Se algum módulo precisar de input multi-TF, ele recebe via colunas já mergeadas pelo `merge_informative_pair`.

---

## 3. Lookahead bias — confirmação do Conflito B

### 3.1 Como o `lookahead-analysis` opera

**Verbatim:**

> *"It will start with a backtest of all pairs to generate a baseline for indicators and entries/exits. After this initial backtest runs, it will look if the `minimum-trade-amount` is met... After setting the baseline it will then do additional backtest runs for every entry and exit separately. When these verification backtests complete, it will compare both dataframes (baseline and sliced) for any difference in columns' value and report the bias."*

**Tradução:** método **diferencial**, não estático. Roda backtest várias vezes truncando dados em pontos diferentes; se um indicador mudar de valor quando candles futuros são removidos, ele tem lookahead.

### 3.2 Padrões proibidos listados explicitamente

**Verbatim:**

> *"Examples of lookahead-bias:*
> - *`shift(-10)` looks 10 candles into the future.*
> - *Using `iloc[]` in populate_* functions to access a specific row in the dataframe.*
> - *For-loops are prone to introduce lookahead bias if you don't tightly control which numbers are looped through.*
> - *Aggregation functions like `.mean()`, `.min()` and `.max()`, without a rolling window, will calculate the value over the whole dataframe, so the signal candle will 'see' a value including future candles. A non-biased example would be to look back candles using `rolling()` instead: e.g. `dataframe['volume_mean_12'] = dataframe['volume'].rolling(12).mean()`*
> - *`ta.MACD(dataframe, 12, 26, 1)` will introduce bias with a signalperiod of 1.*"

**Implicação para SMC modular:**
- `request.security(..., lookahead=barmerge.lookahead_on)` do LuxAlgo equivale a `shift(-N)` em pandas. **Conflito B selado: não replicar.**
- Função `swing_highs_lows` que precisa de N candles à direita para confirmar swing **vai falhar** no lookahead-analysis se publicar a coluna no candle do swing. Solução: publicar com atraso de N candles (swing detectado em X aparece na coluna `swing_high` somente em X+N).

### 3.3 Limitação a observar

**Verbatim:**

> *"`lookahead-analysis` can only verify / falsify the trades it calculated and verified. If the strategy has many different signals / signal types, it's up to you to select appropriate parameters to ensure that all signals have triggered at least once. Signals that are not triggered will not have been verified. This would lead to a false-negative."*

**Implicação:** o backtest de validação SMC precisa ter timerange e diversidade suficientes para acionar **todos os 16 alertconditions do LuxAlgo** pelo menos uma vez. Senão, lookahead pode passar despercebido.

### 3.4 Caveat sobre limit orders

**Verbatim:**

> *"limit orders in combination with `custom_entry_price()` and `custom_exit_price()` callbacks can cause late / delayed entries and exists, causing false positives. To avoid this - market orders are forced for this command."*

**Implicação:** se a estratégia SMC usar Risk Entry (limit orders) conforme documento de princípios Parte 3.4, o lookahead-analysis vai forçar market orders na verificação — não invalida o teste, mas o trade real terá comportamento diferente.

---

## 4. Coerência temporal — solução para Bug 2 do sistema legado

### 4.1 Persistência de metadata por trade via `trade.set_custom_data()`

**Verbatim:**

> *"Freqtrade allows storing/retrieving user custom information associated with a specific trade in the database. Using a trade object, information can be stored using `trade.set_custom_data(key='my_key', value=my_value)` and retrieved using `trade.get_custom_data(key='my_key')`. Each data entry is associated with a trade and a user supplied key (of type `string`). This means that this can only be used in callbacks that also provide a trade object."*

**Verbatim — recomendação de tipos:**

> *"It is recommended that simple data types are used `[bool, int, float, str]` to ensure no issues when serializing the data that needs to be stored."*

### 4.2 Hook `order_filled` para gravar metadata no momento da entrada

**Verbatim:**

```python
def order_filled(self, pair: str, trade: Trade, order: Order, current_time: datetime, **kwargs) -> None:
    dataframe, _ = self.dp.get_analyzed_dataframe(trade.pair, self.timeframe)
    last_candle = dataframe.iloc[-1].squeeze()

    if (trade.nr_of_successful_entries == 1) and (order.ft_order_side == trade.entry_side):
        trade.set_custom_data(key="entry_candle_high", value=last_candle["high"])

    return None
```

**Implicação para coerência temporal SMC:**

No momento em que o trade abre (Bug 2 do sistema legado), gravar via `order_filled`:
- `setup_id` — identidade do setup que disparou o trade
- `ob_anchor_low` — mínima do OB que define a zona (para ancorar SL de LONG)
- `ob_anchor_high` — máxima do OB que define a zona (para ancorar SL de SHORT)
- `ob_anchor_time` — timestamp do candle de origem do OB
- `fvg_anchor_top` / `fvg_anchor_bottom` — se a zona é FVG
- `swing_anchor_low` / `swing_anchor_high` — swing que delimita a zona

Esses valores **nunca mais mudam** durante a vida do trade. SL e TP futuros leem via `trade.get_custom_data()`, não recalculam do mercado atual. **Bug 2 do sistema legado eliminado por construção.**

### 4.3 `custom_stoploss` ancorado em valor absoluto via dataframe

**Verbatim — exemplo do parabolic SAR (template direto para SMC):**

```python
def custom_stoploss(self, pair: str, trade: Trade, current_time: datetime,
                    current_rate: float, current_profit: float, after_fill: bool,
                    **kwargs) -> float | None:

    dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
    last_candle = dataframe.iloc[-1].squeeze()

    stoploss_price = last_candle["sar"]

    if stoploss_price < current_rate:
        return stoploss_from_absolute(stoploss_price, current_rate, is_short=trade.is_short)

    return None
```

**Adaptação para SMC:**

```python
def custom_stoploss(self, pair, trade, current_time, current_rate, current_profit, after_fill, **kwargs):
    ob_anchor_low = trade.get_custom_data(key='ob_anchor_low')
    if ob_anchor_low is None:
        return None  # No-change

    sl_price = ob_anchor_low * 0.999  # buffer abaixo do OB anchor
    return stoploss_from_absolute(sl_price, current_rate, is_short=trade.is_short, leverage=trade.leverage)
```

**SL ancorado no OB que originou o trade**, não em swing solto do mercado atual. Princípio do documento de princípios respeitado por construção.

### 4.4 Dataframe access em callbacks — regras

**Verbatim:**

> *"You may access dataframe in various strategy functions by querying it from dataprovider... You can use `.iloc[-1]` here because `get_analyzed_dataframe()` only returns candles that backtesting is allowed to see. This will not work in `populate_*` methods, so make sure to not use `.iloc[]` in that area."*

**Implicação:** `.iloc[-1]` em callbacks é seguro. `.iloc[]` em `populate_*` é proibido (causa lookahead).

---

## 5. Mapeamento conceitual SMC ↔ Freqtrade — versão verificada

A divisão de responsabilidades fica **documentalmente confirmada** assim:

| Conceito SMC do documento de princípios | Onde mora no Freqtrade | Verificado em |
|---|---|---|
| Engine SMC produz dados crus bar-a-bar | `populate_indicators` (3 vezes via `@informative` para 4H/1H/15m) | Strategy customization §Customize Indicators, §Informative pairs |
| Estado SMC exposto como colunas | DataFrame retornado por `populate_indicators` | Strategy customization §Dataframe |
| Setup ARMED detectado | Coluna `setup_armed` no DataFrame | Mesma seção |
| Setup PENDING_CONFIRMATION | Coluna `setup_pending` no DataFrame | Idem |
| Setup CONFIRMED dispara entrada | `populate_entry_trend` lê coluna e seta `enter_long`/`enter_short` | Strategy customization §Entry signal rules |
| Trade abre no candle seguinte ao sinal | Comportamento nativo, "next candle open" | Strategy customization §Trade order assumptions |
| Identidade do setup persiste no trade | `trade.set_custom_data(key='setup_id', ...)` no `order_filled` | Strategy advanced §Storing information (Persistent) |
| Coerência temporal: SL ancorado no OB original | `custom_stoploss` lê `trade.get_custom_data('ob_anchor_low')` + `stoploss_from_absolute` | Strategy callbacks §Custom stoploss + §Common helpers |
| INVALIDATED após CONFIRMED (trend macro mudou) | `custom_exit` lê coluna do dataframe atual | Strategy callbacks §Custom exit signal |
| TPs parciais estruturais | `adjust_trade_position` retorna stake negativo | Strategy callbacks §Adjust trade position |
| Forward simulation real | Nativo do framework (Bug 4 do sistema legado eliminado) | Bot basics §Backtesting execution logic |
| Validação anti-lookahead | Comando `freqtrade lookahead-analysis` | Lookahead analysis §How does the command work |

---

## 6. Decisões pendentes do mapa Camada 1 — status atualizado

### Decisão #1 — Verificação documental do Freqtrade

**Status: FECHADA.** Este documento é o resultado. A arquitetura modular pura é compatível com `IStrategy` por construção. Engine SMC vive em `populate_indicators` (vetorizado), máquina de estados vive em colunas do DataFrame + callbacks. Não há corpo estranho.

### Decisão #3 — Conflito A (multi-TF na engine vs na IStrategy)

**Status: FECHADA.** Multi-TF é responsabilidade da `IStrategy` via `@informative` ou `informative_pairs()` + `merge_informative_pair()`. Engine SMC opera no TF nativo do DataFrame que recebe. **`request.security` do LuxAlgo não tem equivalente direto na engine** — fica como detalhe interno do `drawFairValueGaps` que será resolvido na Onda 7 (FVG) via input já mergeado pelo Freqtrade.

### Decisão #4 — Conflito B (não replicar `lookahead_on`)

**Status: FECHADA.** Documento confirma que `shift(-N)` é proibido e `lookahead-analysis` detecta. Portagem de `drawFairValueGaps` deve usar dados do TF maior **somente após o candle daquele TF fechar** (atraso de 1 candle do TF maior). Diferença em relação ao TradingView documentada.

### Decisão #2 — Sliding window vs lista full-history

**Status: AINDA ABERTA.** O Freqtrade tem `startup_candle_count` que define quantos candles a estratégia precisa antes de gerar sinais. Mas isso não responde se as listas internas da engine SMC (parsedHighs/Lows) devem ser sliding window ou full. **Decisão recomendada:** sliding window com `maxlen` configurável, suficiente para cobrir o maior `swingsLengthInput` (default 50) com folga (talvez 1000). Reduz memória para hyperopt sem perder dados úteis. Resolver no PR da Onda 6 (Order Blocks).

### Decisão #5 — Conflito C (regra exata de Liquidity Sweep)

**Status: AINDA ABERTA.** Não há nada na documentação do Freqtrade que ajude — é decisão conceitual SMC. Vai ser resolvida no briefing da Onda 8 com base no documento de princípios + literatura SMC.

### Decisão #6 — Geração do golden dataset

**Status: AINDA ABERTA.** Trabalho manual no TradingView. Pode ser feito em paralelo às primeiras ondas de portagem.

---

## 7. Consequências para a arquitetura modular pura

### 7.1 Estrutura final confirmada

```
SMC_Freqtrade/
├── smc_engine/                       ← biblioteca Python pura
│   ├── __init__.py
│   ├── types.py                      ← dataclasses (Pivot, OrderBlock, FairValueGap, ...)
│   ├── state.py                      ← EngineState (17 atributos persistentes)
│   ├── operators.py                  ← cross_over, cross_under, atr_wilder, etc.
│   ├── pivots.py                     ← Onda 3
│   ├── trailing.py                   ← Onda 4
│   ├── premium_discount.py           ← Onda 4 (não está no LuxAlgo, novo)
│   ├── structure.py                  ← Onda 5 (BOS/CHoCH)
│   ├── order_blocks.py               ← Onda 6
│   ├── fair_value_gaps.py            ← Onda 7 (sem lookahead_on)
│   ├── liquidity_sweep.py            ← Onda 8 (não está no LuxAlgo, novo)
│   └── engine.py                     ← Onda 9 (orquestração: recebe DataFrame, retorna DataFrame)
├── tests/
│   ├── unit/
│   ├── integration/
│   └── golden/
│       └── btc_4h_30days_luxalgo.json   ← golden dataset
└── user_data/strategies/
    └── SMCStrategy.py                ← Onda 10 (IStrategy: usa @informative para 1H e 4H)
```

### 7.2 Assinatura confirmada da engine

A engine consume e produz DataFrame. Função pública:

```python
# em smc_engine/engine.py
def analyze(dataframe: pd.DataFrame, **params) -> pd.DataFrame:
    """
    Recebe DataFrame com colunas ['date', 'open', 'high', 'low', 'close', 'volume']
    Retorna mesmo DataFrame com colunas SMC adicionadas:
      'swing_high', 'swing_low', 'internal_high', 'internal_low',
      'eqh', 'eql', 'sweep_bullish', 'sweep_bearish',
      'ob_top', 'ob_bottom', 'ob_id', 'ob_active',
      'fvg_top', 'fvg_bottom', 'fvg_id', 'fvg_active',
      'bos_internal', 'choch_internal', 'bos_swing', 'choch_swing',
      'trend_internal', 'trend_swing',
      'trailing_top', 'trailing_bottom',
      'premium_discount_zone'  # 'premium' | 'equilibrium' | 'discount'
    """
```

### 7.3 Esqueleto da `SMCStrategy` confirmado

```python
class SMCStrategy(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = '15m'  # menor TF, conforme limitação documental do Freqtrade
    can_short = True
    use_custom_stoploss = True
    stoploss = -0.10  # hard limit, custom_stoploss define a real

    @informative('4h')
    def populate_indicators_4h(self, dataframe, metadata):
        return analyze(dataframe, mode='swing_only')  # só trend macro

    @informative('1h')
    def populate_indicators_1h(self, dataframe, metadata):
        return analyze(dataframe, mode='full')  # zona detection (OB+FVG)

    def populate_indicators(self, dataframe, metadata):
        # 15m: confirmation entry detection (BOS/CHoCH 15m)
        dataframe = analyze(dataframe, mode='internal_focus')
        # Após @informative o dataframe já tem colunas '_4h' e '_1h'.
        # Lógica de máquina de estados em colunas auxiliares:
        dataframe = compute_setup_state(dataframe)  # ARMED/PENDING/CONFIRMED
        return dataframe

    def populate_entry_trend(self, dataframe, metadata):
        dataframe.loc[
            (dataframe['setup_state'] == 'CONFIRMED') &
            (dataframe['setup_direction'] == 'long'),
            ['enter_long', 'enter_tag']
        ] = (1, 'smc_confirmed_long')
        # idem para short
        return dataframe

    def order_filled(self, pair, trade, order, current_time, **kwargs):
        # Grava ancoragem temporal do setup
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        trade_candle = dataframe.loc[
            dataframe['date'] == timeframe_to_prev_date(self.timeframe, trade.open_date_utc)
        ].squeeze()
        if not trade_candle.empty:
            trade.set_custom_data('ob_anchor_low', float(trade_candle['ob_bottom']))
            trade.set_custom_data('ob_anchor_high', float(trade_candle['ob_top']))
            trade.set_custom_data('setup_id', str(trade_candle['setup_id']))

    def custom_stoploss(self, pair, trade, current_time, current_rate,
                        current_profit, after_fill, **kwargs):
        ob_low = trade.get_custom_data('ob_anchor_low')
        ob_high = trade.get_custom_data('ob_anchor_high')
        if trade.is_short:
            sl_price = (ob_high or current_rate) * 1.001
        else:
            sl_price = (ob_low or current_rate) * 0.999
        return stoploss_from_absolute(sl_price, current_rate,
                                      is_short=trade.is_short,
                                      leverage=trade.leverage)
```

**Esse esqueleto é a próxima ação concreta** depois de fechar as ondas 1-9 da engine.

---

## 8. O que mudou em relação à minha resposta anterior

Para registro de honestidade epistêmica:

| Afirmação anterior | Status | Correção / confirmação |
|---|---|---|
| `populate_indicators` recebe DataFrame e retorna DataFrame | **Confirmado** | Verbatim: "Adds several different TA indicators to the given DataFrame" |
| Multi-TF via `informative_pairs` + `merge_informative_pair` | **Confirmado** | Verbatim: ver §2.1 deste documento |
| Engine modular consome DataFrames diretamente | **Confirmado** | A `IStrategy` consome via `@informative` ou `dp.get_pair_dataframe()`, e a engine recebe DataFrame puro |
| `lookahead-analysis` opera sobre colunas pandas | **Refinado** | Mecanismo é diferencial (compara baseline vs sliced dataframes), não estático sobre colunas. Detecta via mudança de valor, não por inspeção de código |
| Arquitetura modular pura encaixa nativamente no Freqtrade | **Confirmado** | Toda a divisão de responsabilidades mapeada no §5 deste documento bate com hooks documentados |
| Limitação de TF informative > base não estava em minha resposta anterior | **Adicionado** | Restrição estrutural não inferida antes, agora documentada |
| Coerência temporal via `trade.set_custom_data` não estava em minha resposta anterior | **Adicionado** | Solução para Bug 2 do sistema legado documentada agora |

A decisão modular pura permanece **certa**, agora por evidência documental forte e não mais por inferência.

---

**Fim do documento.**

Versão: 1.0
Próxima ação: este documento + o mapa Camada 1 viram a base do briefing de implementação da Onda 1 (types.py + state.py).

