# Briefing Onda 6 — Order Blocks (`smc_engine/order_blocks.py`)

**Destino do arquivo:** `briefings/onda-06-order-blocks-spec.md`
**Subprojeto:** `smc_freqtrade/`
**Branch de desenvolvimento:** definida pelo Claude Code conforme AGENTS §1.2.
**Versão:** este briefing é da onda; bump de `VERSION` segue AGENTS §1.3.

---

## 1. Contexto

A engine SMC do `smc_freqtrade/` está sendo portada do indicador LuxAlgo
SMC compute-only (`tools/pynecore-validation/luxalgo_smc_compute_only.py`).
Ondas 1-5 já foram mergeadas em `main` cobrindo: types, state, operators
stateless, detecção de pivots (swing/internal/equal), trailing extremes
Premium/Discount/Equilibrium e BOS/CHoCH formal.

A **Onda 6** porta as funções `storeOrdeBlock()` (Pine linhas 223-236)
e `deleteOrderBlocks()` (Pine linhas 200-221), com a integração via
`displayStructure()` (Pine linhas 257 bullish e 271 bearish). É a
primeira onda do projeto cuja unidade de saída tem **ciclo de vida
multi-candle** (criação → ativo → mitigado) — todas as ondas anteriores
emitem eventos por candle ou estados de bias por candle.

A onda também:

- Estende o UDT `OrderBlock` de Onda 1 com 5 campos novos (lifecycle
  + scope + state + hook volumetric), mantendo `bar_time` para
  preservar fidelidade à interface Pine.
- Fecha a decisão pendente §8 #2 do Mapa Camada 1
  (`MAPA_LUXALGO_CAMADA_1_v1.1.md`): "sliding window vs lista
  full-history em `parsedHighs/Lows`" → resolve por
  `df.iloc[start:end]` sem lista global.
- Absorve o **DT-4** do relatório final de consistência da Onda 5
  (`onda-05-final-consistency-report.md`): adiciona subseção §7.6.1
  ao Mapa cobrindo caixas de OB. O patch ao Mapa entra **no mesmo PR
  da implementação Wave 6** (não PR de doc separado).
- Documenta 3 hooks explícitos de absorção do LuxAlgo pago, conforme
  precedente CHoCH+ da Onda 5 e classificação Categoria B em
  `AVALIACAO_LUXALGO_PRICE_ACTION_CONCEPTS_v1.0.md` §6.2:
  - **Onda 6.1 — Volumetric OB** (hook: campo
    `volumetric_intensity` reservado no UDT)
  - **Onda 6.2 — Breaker Blocks** (hook: campo `state` aceita
    `'breaker'` futuramente)
  - **Onda 6.1 — OB Mitigation = Average** (hook: parâmetro
    `mitigation` aceita `'Average'` futuramente)

- **Não toca** `smc_engine/structure.py` (Onda 5, já mergeada). O
  gatilho do OB é a re-leitura das 8 booleans + 4 colunas `*_idx` já
  produzidas pela Onda 5/Onda 3 — sem recomputação de BOS/CHoCH.
- **Não estende** `smc_engine/trailing.py` (Onda 4). `parsed_high` /
  `parsed_low` são específicos do contexto de OB e ficam locais ao
  módulo `order_blocks.py`.

---

## 2. Premissas técnicas (canônicas)

Premissas fechadas na sessão de planejamento que esta onda assume como
verdade. **Se ao implementar você identificar que alguma é falsa, pare
e levante a divergência** (AGENTS §2.1, "Conflito briefing vs.
realidade").

1. **Gatilho de criação de OB = re-leitura das 8 booleans da Onda 5,
   sem recomputação.** Cada candle X onde algum dos 8 booleans é True
   dispara a criação de exatamente 1 OB no scope/direction
   correspondente:

   | Booleans Onda 5 (`smc_engine/structure.py`) | OB criado |
   |---|---|
   | `bos_internal_bullish` OR `choch_internal_bullish` | bullish internal OB |
   | `bos_internal_bearish` OR `choch_internal_bearish` | bearish internal OB |
   | `bos_swing_bullish` OR `choch_swing_bullish` | bullish swing OB |
   | `bos_swing_bearish` OR `choch_swing_bearish` | bearish swing OB |

   Pine fonte: linha 257 (`storeOrdeBlock(p_ivot, internal, BULLISH)`
   dentro do bloco bullish de `displayStructure`) e linha 271
   (`storeOrdeBlock(p_ivot, internal, BEARISH)` dentro do bloco
   bearish). Em pandas, a re-leitura substitui a chamada Pine.

2. **`parsed_high` / `parsed_low` calculados internamente em
   `order_blocks.py`.** Pine linhas 124-128. Fórmula verbatim:

   ```
   atr_200 = atr_wilder(high, low, close, length=200)        # Pine: ta.atr(200)
   range_measure = cum_sum(true_range(...)) / bar_index      # Pine: ta.cum(ta.tr) / bar_index
   volatility = atr_200  if filter == 'Atr' else range_measure
   high_vol_bar = (high - low) >= 2 * volatility
   parsed_high = where(high_vol_bar, low, high)
   parsed_low  = where(high_vol_bar, high, low)
   ```

   `atr_wilder`, `cum_sum` e `true_range` já existem em
   `smc_engine/operators.py` (Onda 2). NÃO estende `trailing.py`
   (Onda 4) — `parsed_*` só serve para OB.

3. **UDT `OrderBlock` (em `smc_engine/types.py`, Onda 1) estendido
   com 6 campos novos.** A estrutura final fica:

   | Campo | Origem | Significado |
   |---|---|---|
   | `bar_high` | Onda 1 (Pine) | Preço alto da vela parsed-extreme |
   | `bar_low` | Onda 1 (Pine) | Preço baixo da vela parsed-extreme |
   | `bar_time` | Onda 1 (Pine) | Timestamp da vela parsed-extreme (= `t_origin`, ver P12) |
   | `bias` | Onda 1 (Pine) | `BULLISH` (1) ou `BEARISH` (-1) |
   | `t_creation` | **NOVO Onda 6** | Timestamp da vela do break (vela do BOS/CHoCH) |
   | `t_mitigation` | **NOVO Onda 6** | Timestamp da vela de mitigação (None/pd.NaT enquanto ativo) |
   | `t_invalidation` | **NOVO Onda 6** | RESERVADO — sempre None em Wave 6 (hook Onda 6.2) |
   | `scope` | **NOVO Onda 6** | `'internal'` ou `'swing'` |
   | `state` | **NOVO Onda 6** | `'active'` ou `'mitigated'` em Wave 6 (hook `'breaker'` Onda 6.2) |
   | `volumetric_intensity` | **NOVO Onda 6** | RESERVADO — sempre None em Wave 6 (hook Onda 6.1) |

   A extensão do UDT é exceção autorizada à mudança cirúrgica
   (AGENTS §2.3): necessidade arquitetural Wave 6 — sem os 5 campos
   novos, o ledger não é construível e o spot-check híbrido fica
   inespecificável.

4. **Mitigação default = Wick** (Pine linha 88 confirma
   `input.string(HIGHLOW, 'OB Mitigation', options=(CLOSE, HIGHLOW))`).
   Parâmetro da função pública: `mitigation: Literal['Close', 'Wick'] = 'Wick'`.

   Trigger em candle X (após `t_creation`):
   - Bearish OB mitigated se `bearish_source[X] > OB.bar_high`.
   - Bullish OB mitigated se `bullish_source[X] < OB.bar_low`.

   Sources (Pine linhas 122-123):
   - `bearish_source = close if mitigation == 'Close' else high`
   - `bullish_source = close if mitigation == 'Close' else low`

   É parâmetro **global** da chamada, não por-zona, espelhando o
   input global do Pine.

5. **Slice da janela do parsed-extreme: `df.iloc[int(pivot_idx):int(break_idx)]`,
   semi-aberto à direita** (`[pivot_idx, break_idx)`). Espelha Pine
   `array.slice(parsedHighs__global__, p_ivot.barIndex, bar_index)`
   (linhas 227-231). `pivot_idx` lido de
   `COL_<SCOPE>_<HIGH|LOW>_IDX` no candle do break — float64 com bar
   position, conversão `int(...)` antes do slice. Para bullish OB,
   busca `argmin(parsed_low)` na janela; para bearish OB, busca
   `argmax(parsed_high)` na janela.

   Fecha decisão pendente §8 #2 do Mapa
   (`MAPA_LUXALGO_CAMADA_1_v1.1.md`): "sliding window vs lista
   full-history" → sliding window via `df.iloc`, sem lista global.
   Memória O(1) extra além do próprio DataFrame.

6. **Sem invalidação separada.** Pine fonte NÃO tem regra de
   invalidação distinta da mitigação. A única remoção de OB é via
   `deleteOrderBlocks` (= mitigação, linhas 200-221). O cap de 100
   OBs (`array.pop` em `storeOrdeBlock` quando size ≥ 100, linhas
   234-235) é **bound de implementação Pine, NÃO regra semântica** —
   NÃO portar. Campo `t_invalidation` permanece reservado (sempre
   None/`pd.NaT` em Wave 6) como hook para Onda 6.2 (Breaker Blocks
   podem introduzir invalidação semântica pós-mitigação).

7. **Ordem dentro do mesmo candle**: Pine linhas 313-317 estabelecem
   a sequência `displayStructure(True)` → `displayStructure()` →
   `deleteOrderBlocks(True)` → `deleteOrderBlocks()`. Traduzindo:

   - **internal CREATE → swing CREATE → internal MITIGATE → swing MITIGATE.**

   Em pandas, isso se traduz em duas passagens:

   1. **CREATE pass** (vetorizado): para cada vela X com algum dos 8
      booleans True, emitir OB record. Ordem dentro de X:
      `internal_bullish_create` → `internal_bearish_create` →
      `swing_bullish_create` → `swing_bearish_create`. Reflete em
      `ob_id` sequencial.
   2. **MITIGATION pass** (vetorizado por OB): para cada OB já no
      ledger, busca primeira vela `> t_creation` que satisfaz a
      condição de mitigação. Ordenação interna: internal antes de
      swing (espelha Pine linhas 316-317). Como cada OB carrega
      `scope`, a ordenação é resolvida via sort do ledger antes da
      busca.

8. **Lookahead-safe por construção.** Como toda onda anterior, sem
   `shift(-N)`. Os inputs consumidos são:
   - 8 booleans da Onda 5 (já lookahead-safe).
   - 4 colunas `*_idx` da Onda 3 (lookahead-safe via materialização
     atrasada em `pivot_idx = position - size`).
   - OHLCV bruto + `atr_wilder` (lookback only).

   Nenhum input desta onda introduz dependência de candles futuros.

9. **Volumetric OB / Breaker Blocks / OB Mitigation = Average
   postergados com hooks no UDT.** Classificação Categoria B em
   `AVALIACAO_LUXALGO_PRICE_ACTION_CONCEPTS_v1.0.md` §6.2 — não
   exigem mudança arquitetural, só adicionam colunas/options.
   Precedente direto: CHoCH+ da Onda 5.

   Hooks reservados na Wave 6:
   - `OrderBlock.volumetric_intensity: Optional[float] = None` —
     Onda 6.1 (Volumetric OB) preencherá com fração `buy_volume / total_volume`
     da janela `[pivot_idx, break_idx)`.
   - `OrderBlock.state: str` aceita `'breaker'` — Onda 6.2 (Breaker
     Blocks) refatora `deleteOrderBlocks` para transição
     `'active' → 'breaker'` em vez de remoção imediata.
   - Parâmetro `mitigation` aceita `'Average'` — Onda 6.1 adiciona
     terceiro modo (midpoint da caixa = `(bar_high + bar_low) / 2`).

   Wave 6 emite apenas `state ∈ {'active', 'mitigated'}`,
   `volumetric_intensity is None` sempre, `mitigation ∈ {'Close', 'Wick'}`
   sempre.

10. **Cap de 100 OBs NÃO portado.** Pine linhas 234-235
    (`if array.size(orderBlocks) >= 100: array.pop(orderBlocks)`) é
    bound para evitar acúmulo no estado persistente do Pine streaming.
    Em pandas vetorizado sobre DataFrame finito, não há acúmulo
    indefinido — o ledger termina com o último candle do input.

11. **Política de mitigação: `date > t_creation`** (estritamente
    posterior). NÃO permite mitigação na mesma vela do CREATE.

    **Divergência potencial vs Pine.** Pine roda
    `deleteOrderBlocks` DEPOIS de `displayStructure` no mesmo candle
    (linhas 313-317), o que em tese permite que um OB recém-criado
    seja mitigado no próprio candle do nascimento. Em pandas, essa
    coexistência CREATE+MITIGATE no mesmo timestamp é rejeitada por
    decisão arquitetural ("OB não pode morrer ao nascer"): mais
    conservador, mais legível, evita race entre os dois eventos no
    mesmo índice temporal.

    Em prática, a divergência é praticamente irrelevante: para que
    Pine mitigue no candle do nascimento, o `bullish_source` ou
    `bearish_source` da vela atual já teria que ter ultrapassado o
    bar_low / bar_high da vela parsed-extreme — cenário que
    raramente ocorre porque a vela atual é a do break (close cruza
    o pivot, mas wicks raramente furam o lado oposto da janela).

12. **Equivalência terminológica**: `bar_time` (campo do UDT
    inherited do Pine) ≡ `t_origin` (termo arquitetural) ≡ Pine
    `barTime` (linhas 68-73, 232) = timestamp da vela parsed-extreme
    dentro da janela `[pivot_idx, break_idx)`. **NÃO renomear** o
    campo do UDT (interface preservation, AGENTS §2.3). O restante
    deste briefing e o código da implementação usam exclusivamente
    `bar_time`. `t_origin` aparece apenas em prosa documentacional
    quando for útil para diferenciar das demais marcas temporais.

---

## 3. Plano de execução numerado

Cada passo declara seu critério de verificação local. Critério global
do PR é §6.

1. **Estender `smc_engine/types.py`** adicionando 6 campos ao UDT
   `OrderBlock`: `t_creation`, `t_mitigation`, `t_invalidation`,
   `scope`, `state`, `volumetric_intensity`. Manter os 4 campos
   existentes (`bar_high`, `bar_low`, `bar_time`, `bias`). Atualizar
   o docstring estruturado (AGENTS §1.4) explicando a equivalência
   `bar_time ≡ t_origin` e os 3 campos reservados.
   *Verifica:* `OrderBlock(bar_high=1.0, bar_low=0.5, bar_time=0,
   bias=1, t_creation=0, scope='swing')` constrói; campos
   reservados defaultam para None.

2. **Criar `smc_engine/order_blocks.py`** implementando
   `detect_order_blocks` conforme spec do §4. Inclui:
   - Constantes `COL_OB_*` no topo (8 booleans, prefixo alinhado
     com `COL_BOS_*` da Onda 5).
   - Helpers privados (vetorizados, sem loop por candle quando
     possível): `_compute_parsed_high_low(...)`,
     `_emit_create_events(...)`, `_resolve_mitigations(...)`.
   - Função pública `detect_order_blocks(df, *, ob_filter='Atr',
     mitigation='Wick', atr_length=200) -> tuple[pd.DataFrame,
     pd.DataFrame]`.

   *Verifica:* `from smc_engine.order_blocks import detect_order_blocks,
   COL_OB_SWING_BULLISH_CREATED, ...` funciona; chamada sobre
   DataFrame de 200 candles produz `(df_per_candle, ledger)`
   onde `df_per_candle` tem +8 colunas booleans e `ledger` tem
   schema correto (11 colunas).

3. **Criar `smc_freqtrade/tests/test_smoke_wave6.py`** com smoke
   sintético conforme §5. *Verifica:* `pytest` passa; cobertura dos
   8 cenários listados em §5.

4. **Atualizar `smc_engine/__init__.py`** exportando
   `detect_order_blocks` e as 8 constantes `COL_OB_*` da Onda 6.
   *Verifica:* `from smc_engine import detect_order_blocks` funciona;
   `__all__` inclui as constantes novas. `OrderBlock` continua
   exportado.

5. **Atualizar `docs/MAPA_LUXALGO_CAMADA_1_v1.1.md`** com:
   - Nova subseção **§7.6.1** ("Caixas de Order Block: regra
     canônica de leitura visual"), texto exato em §7 deste
     briefing.
   - **§7.8** entradas atualizadas para Volumetric OB, Breaker
     Blocks, OB Mitigation = Average (texto exato em §7 deste
     briefing).
   - **§8** fechamento da decisão pendente #2 (texto exato em §7
     deste briefing).

   *Verifica:* `grep -n '§7.6.1' docs/MAPA_LUXALGO_CAMADA_1_v1.1.md`
   retorna a nova subseção; tabela de §7.8 reflete os 3 status
   "Decidido"; tabela de §8 reflete decisão #2 como "FECHADA".

6. **Smoke spot-check sobre golden CSV** (rodar localmente, não
   commitado nesta onda — produto vai como artefato no PR para
   Marcelo conferir visualmente vs LuxAlgo gratuito TradingView).
   *Verifica:* `python -c "import pandas as pd; from smc_engine import detect_pivots, compute_trailing_extremes, detect_structure, detect_order_blocks; df = pd.read_csv(...); df = detect_pivots(df); df = compute_trailing_extremes(df); df = detect_structure(df); df_ob, ledger = detect_order_blocks(df); print(len(ledger), ledger['bias'].value_counts(), ledger['state'].value_counts())"`
   produz contagens plausíveis. Spot-check contra os ~12 OBs do
   §3.1 do relatório final da Onda 5 conforme §8 deste briefing.

---

## 4. Spec funcional

### 4.1 Assinatura pública

```python
def detect_order_blocks(
    df: pd.DataFrame,
    *,
    ob_filter: Literal['Atr', 'Range'] = 'Atr',
    mitigation: Literal['Close', 'Wick'] = 'Wick',
    atr_length: int = 200,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    OBJETIVO
        Portagem vetorizada de storeOrdeBlock() + deleteOrderBlocks()
        do LuxAlgo SMC (Pine linhas 200-236), integrada via re-leitura
        das 8 booleans BOS/CHoCH da Onda 5. Detecta criação e
        mitigação de Order Blocks em duas escalas (internal e swing)
        e duas direções (bullish e bearish), produzindo (a) um
        DataFrame com 8 eventos booleans por candle e (b) um ledger
        com uma linha por OB de ciclo de vida completo.

    FONTE DE DADOS
        df: DataFrame com no mínimo OHLC + as 4 colunas COL_*_IDX
            produzidas por detect_pivots() (Onda 3) para os escopos
            swing e internal + as 8 booleans BOS/CHoCH produzidas por
            detect_structure() (Onda 5).
        ob_filter: replica orderBlockFilterInput do Pine (linha 87).
            'Atr' usa ta.atr(atr_length); 'Range' usa
            ta.cum(ta.tr) / bar_index. Determina volatilityMeasure
            para detecção de high-volatility bars na inversão de
            parsedHigh/parsedLow.
        mitigation: replica orderBlockMitigationInput do Pine
            (linha 88). 'Wick' (default, = HIGHLOW no Pine) usa
            high/low como fonte de mitigação; 'Close' usa close.
        atr_length: replica o length de ta.atr() no Pine (linha 124,
            hardcoded em 200). Exposto como parâmetro para facilitar
            testes sintéticos com horizonte curto.

    LIMITAÇÕES CONHECIDAS
        Lookahead-safe por construção: consome apenas COL_*_IDX e
            8 booleans já materializados pelas ondas 3 e 5 (todos
            lookahead-safe). Nenhum shift(-N) interno.

        Política de mitigação `date > t_creation` (estritamente
            posterior) diverge sutilmente do Pine (que executa
            deleteOrderBlocks no MESMO candle do create). Decisão
            fechada no briefing da Onda 6 §2 P11 — "OB não pode
            morrer ao nascer". Cenário praticamente irrelevante
            (close cruza pivot mas wicks raramente furam lado oposto
            da janela no mesmo candle).

        Volumetric Order Blocks (LuxAlgo pago) NÃO são detectados
            nesta onda. Hook reservado: campo
            OrderBlock.volumetric_intensity default None. Decisão
            arquitetural fechada no briefing da Onda 6: feature do
            LuxAlgo Price Action Concepts pago, adiada para
            Onda 6.1 com hook explícito. Ver
            docs/AVALIACAO_LUXALGO_PRICE_ACTION_CONCEPTS_v1.0.md
            §4.2 (spec conceitual) e §6.2 (classificação Categoria B).

        Breaker Blocks (LuxAlgo pago) NÃO são detectados nesta onda.
            Hook reservado: campo OrderBlock.state aceita futuro
            valor 'breaker' (Wave 6 só emite 'active' e 'mitigated').
            Decisão arquitetural fechada no briefing da Onda 6:
            adiada para Onda 6.2.

        OB Mitigation Method = Average (LuxAlgo pago) NÃO é
            implementada nesta onda. Hook reservado: parâmetro
            mitigation aceita futuro valor 'Average'. Adiada para
            Onda 6.1.

        Cap de 100 OBs do Pine (linhas 234-235) NÃO é portado —
            bound de implementação Pine, não regra semântica.

    NÃO FAZER
        Não usar shift(-N) em ponto algum.
        Não recomputar BOS/CHoCH — consumir as 8 booleans da Onda 5.
        Não estender smc_engine/trailing.py (Onda 4) — parsed_*
            ficam locais ao módulo order_blocks.py.
        Não emitir efeitos colaterais sobre o DataFrame de entrada
            (operar sobre df.copy()).
        Não inline-ar nomes de coluna — usar as constantes COL_OB_*
            definidas no topo do módulo.
        Não popular EngineState (Mapa §2 v1.1).
        Não detectar Volumetric OB — Onda 6.1.
        Não detectar Breaker Blocks — Onda 6.2.
        Não implementar mitigation='Average' — Onda 6.1.
        Não portar o cap de 100 OBs do Pine.
        Não renomear OrderBlock.bar_time → t_origin (P12).
    """
```

### 4.2 Constantes de coluna (topo do módulo)

```python
COL_OB_INTERNAL_BULLISH_CREATED = "ob_internal_bullish_created"
COL_OB_INTERNAL_BEARISH_CREATED = "ob_internal_bearish_created"
COL_OB_SWING_BULLISH_CREATED = "ob_swing_bullish_created"
COL_OB_SWING_BEARISH_CREATED = "ob_swing_bearish_created"
COL_OB_INTERNAL_BULLISH_MITIGATED = "ob_internal_bullish_mitigated"
COL_OB_INTERNAL_BEARISH_MITIGATED = "ob_internal_bearish_mitigated"
COL_OB_SWING_BULLISH_MITIGATED = "ob_swing_bullish_mitigated"
COL_OB_SWING_BEARISH_MITIGATED = "ob_swing_bearish_mitigated"
```

Constantes opcionais (default não-exposto; audit decide se promove):
`COL_PARSED_HIGH = "parsed_high"`, `COL_PARSED_LOW = "parsed_low"`.

### 4.3 Schema de output

A função retorna `tuple[pd.DataFrame, pd.DataFrame]`:

**`df_per_candle`** — cópia do input com 8 colunas anexadas. Todas
`bool` não-nullable, default `False`.

| Coluna | Dtype | Significado |
|---|---|---|
| `ob_internal_bullish_created` | bool | OB bullish internal nasce neste candle (= candle do break) |
| `ob_internal_bearish_created` | bool | OB bearish internal nasce neste candle |
| `ob_swing_bullish_created` | bool | OB bullish swing nasce neste candle |
| `ob_swing_bearish_created` | bool | OB bearish swing nasce neste candle |
| `ob_internal_bullish_mitigated` | bool | Algum OB bullish internal é mitigado neste candle |
| `ob_internal_bearish_mitigated` | bool | Algum OB bearish internal é mitigado neste candle |
| `ob_swing_bullish_mitigated` | bool | Algum OB bullish swing é mitigado neste candle |
| `ob_swing_bearish_mitigated` | bool | Algum OB bearish swing é mitigado neste candle |

Observação: as colunas `*_mitigated` são marcadas com `True` em todo
candle X onde **pelo menos um** OB do scope/direction é mitigado.
Múltiplos OBs simultaneamente mitigados em X produzem um único
`True` na coluna (não soma).

**`ledger`** — DataFrame com uma linha por OB, ordenado por
`t_creation`. Colunas:

| Coluna | Dtype | Significado |
|---|---|---|
| `ob_id` | Int64 | Sequencial 0, 1, 2... na ordem de criação |
| `scope` | string | `'internal'` ou `'swing'` |
| `bias` | Int8 | `BULLISH` (1) ou `BEARISH` (-1) |
| `bar_high` | float64 | `OrderBlock.bar_high` |
| `bar_low` | float64 | `OrderBlock.bar_low` |
| `bar_time` | Int64 (≡ t_origin) | `OrderBlock.bar_time` |
| `t_creation` | Int64 | Timestamp da vela do break |
| `t_mitigation` | Int64 nullable (pd.NaT se ativo) | Timestamp da mitigação |
| `t_invalidation` | Int64 nullable | RESERVADO — sempre pd.NaT |
| `state` | string | `'active'` ou `'mitigated'` |
| `volumetric_intensity` | float64 nullable | RESERVADO — sempre pd.NA |

Tipos de timestamp: `Int64` nullable em milissegundos epoch (consistente
com Pine `time`). Conversão para `pd.Timestamp` fica a cargo dos
consumidores.

### 4.4 Invariantes que o smoke deve cobrir

1. **Re-emissão controlada.** Para cada (candle X, scope, direction),
   no máximo 1 OB é criado. Vetorial: `df_per_candle['ob_<s>_<d>_created'].sum() == len(ledger.query("scope == <s> and bias == <d>"))`.

2. **`t_creation` casa com o candle do break.** Para todo `ob_id` no
   ledger, `t_creation` é exatamente o timestamp do candle onde o
   boolean correspondente da Onda 5 é True.

3. **`bar_time ≤ t_creation` sempre.** O parsed-extreme está
   contido na janela `[pivot_idx, break_idx)`, com `pivot_idx ≤ bar_time
   < break_idx`.

4. **`t_mitigation > t_creation` quando preenchido (P11).** Para
   todo `ob_id` com `t_mitigation` não-nulo,
   `t_mitigation > t_creation` estrito.

5. **`bar_high >= bar_low` sempre.** Trivial — a vela
   parsed-extreme tem `high >= low`.

6. **`bias` ∈ `{BULLISH, BEARISH}`** (constantes existentes em
   `smc_engine.types`).

7. **`scope` ∈ `{'internal', 'swing'}`.**

8. **`state` ∈ `{'active', 'mitigated'}`** (Wave 6 não emite
   `'breaker'`).

9. **`state == 'active'` se e somente se `t_mitigation is pd.NaT`.**

10. **`t_invalidation is pd.NaT` para todos os OBs** (Wave 6 não
    invalida).

11. **`volumetric_intensity is pd.NA` para todos os OBs** (Wave 6
    não computa).

12. **Coexistência de múltiplos OBs ativos** é permitida no mesmo
    candle e mesmo (scope, direction). O ledger não deduplica por
    proximidade — cada break emite um OB.

### 4.5 Algoritmo (em prosa, sem código pronto)

1. **Computar `parsed_high` / `parsed_low`** sobre todo o DataFrame
   (vetorizado), conforme P2.

2. **CREATE pass** (vetorizado):

   Para cada uma das 4 combinações `(scope, direction)`, identificar
   candles X onde `bos_<scope>_<direction> | choch_<scope>_<direction>`
   é True. Para cada X:

   a. Ler `pivot_idx = df[COL_<SCOPE>_<HIGH if BULLISH else LOW>_IDX].iloc[X]`
      (vela do swing/internal que foi quebrada). Pine: linha 244
      (`p_ivot = internalHigh if internal else swingHigh` para
      bullish, e simétrico para bearish — linha 258).

   b. Slicear `window_parsed = df.iloc[int(pivot_idx):X]` (semi-aberto
      à direita, P5). NOTA: se `pivot_idx` for `NaN`, abortar a
      criação deste OB e logar — significa que o break disparou antes
      do pivot materializar, o que indica bug em Onda 3/5 (não em
      Onda 6).

   c. Para BULLISH OB: `extreme_idx = window_parsed['parsed_low'].idxmin()`.
      Para BEARISH OB: `extreme_idx = window_parsed['parsed_high'].idxmax()`.

   d. Construir `OrderBlock`:
      - `bar_high = window_parsed.loc[extreme_idx, 'parsed_high']`
      - `bar_low = window_parsed.loc[extreme_idx, 'parsed_low']`
      - `bar_time = df.iloc[extreme_idx]['date']` (ou equivalente —
        depende do esquema do DataFrame de entrada)
      - `bias = BULLISH | BEARISH`
      - `t_creation = df.iloc[X]['date']`
      - `t_mitigation = None`
      - `t_invalidation = None`
      - `scope = 'internal' | 'swing'`
      - `state = 'active'`
      - `volumetric_intensity = None`

   e. Emitir record no ledger com `ob_id` sequencial. Marcar
      `df_per_candle.loc[X, 'ob_<scope>_<direction>_created'] = True`.

   Ordem das 4 combinações dentro de cada candle X (P7):
   internal-bullish → internal-bearish → swing-bullish → swing-bearish.

3. **MITIGATION pass** (vetorizado por OB):

   Para cada `ob_id` no ledger (ordenado por internal-first então
   swing-first, P7):

   a. Selecionar `source = high` (bearish OB, Wick) | `low` (bullish
      OB, Wick) | `close` (Close mode, ambos os lados).

   b. Filtrar `mask = df['date'] > ob.t_creation` (P11, estritamente
      posterior).

   c. Para BEARISH OB: `hits = df.loc[mask, source] > ob.bar_high`.
      Para BULLISH OB: `hits = df.loc[mask, source] < ob.bar_low`.

   d. Se `hits.any()`: `t_mit = df.loc[hits.idxmax(), 'date']` →
      `ob.t_mitigation = t_mit`, `ob.state = 'mitigated'`. Marcar
      `df_per_candle.loc[hits.idxmax(), 'ob_<scope>_<direction>_mitigated'] = True`.
      Senão: ob permanece com `t_mitigation is pd.NaT`, `state = 'active'`.

4. **Retorno**: `(df_per_candle, ledger)`.

Observação sobre vetorização: o CREATE pass percorre 4 séries de
candles (uma por combinação scope×direction); o número total de OBs
criados é tipicamente O(centenas) sobre 720 candles 4H — o loop por
OB no MITIGATION pass é aceitável e mantém clareza. Vetorização
total cross-OB exigiria broadcast (n_obs × n_candles) que é
desnecessária para o volume real.

---

## 5. Smoke test sintético (descrição conceitual)

Arquivo: `smc_freqtrade/tests/test_smoke_wave6.py`.

### 5.1 Fixture sintética

DataFrame de N=300 candles com OHLC fabricado para produzir, ao
passar pela pipeline completa `detect_pivots → compute_trailing_extremes →
detect_structure → detect_order_blocks`, a seguinte sequência
verificável:

- **Fase 1 (candles ~0-80):** alta gradual seguida de pullback que
  forma swing high (length=50) em ~candle 20 e swing low em ~candle
  60. Internal pivots distribuídos. *Esperado:* nenhum OB criado
  ainda (BOS/CHoCH só ocorre quando há break do pivot materializado).

- **Fase 2 (~80-140):** preço fura o swing high (close > level). A
  Onda 5 emite `bos_swing_bullish` ou `choch_swing_bullish` em algum
  candle X. *Esperado:* Onda 6 emite `ob_swing_bullish_created[X] == True`
  e adiciona OB ao ledger com `bias == BULLISH`, `scope == 'swing'`,
  `t_creation == df.iloc[X]['date']`, `bar_time` dentro da janela
  `[swing_high_idx[X], X)`.

- **Fase 3 (~140-200):** preço cai e fura o swing low. Onda 5
  emite `choch_swing_bearish` em Y. *Esperado:* `ob_swing_bearish_created[Y] == True`,
  novo OB no ledger. Em algum candle Z ∈ (X, Y), o preço retraça
  para o bullish OB criado em fase 2 com `low < ob.bar_low` (Wick) —
  *esperado:* `ob_swing_bullish_mitigated[Z] == True`, e o OB
  bullish do ledger ganha `t_mitigation = df.iloc[Z]['date']`,
  `state = 'mitigated'`.

- **Fase 4 (~200-260):** novo break bullish (CHoCH bullish, porque
  bias prévio agora é BEARISH). Cria novo bullish swing OB. Mantém
  o bearish swing OB da fase 3 ativo (preço não retraçou o
  suficiente).

- **Fase 5 (~260-300):** outro break bullish na mesma direção (= BOS,
  porque bias atual é BULLISH). Cria novo bullish swing OB. No
  final do DataFrame, espera-se:
  - `state` distribution: ≥ 2 OBs `'active'` e ≥ 1 OB `'mitigated'`.
  - Coexistência ≥ 2 OBs `'active'` simultâneos (verificável via
    contagem de `ledger.query("t_creation <= t and (t_mitigation > t or t_mitigation.isna())")`
    para algum candle t).

### 5.2 Asserts canônicos (lista descritiva)

```python
import pandas as pd
import pytest

from smc_engine import (
    BULLISH,
    BEARISH,
    detect_pivots,
    compute_trailing_extremes,
    detect_structure,
    detect_order_blocks,
)


def test_smoke_wave6_lifecycle(synthetic_df):
    df = detect_pivots(synthetic_df, swings_length=50, internal_length=5, equal_length=3)
    df = compute_trailing_extremes(df)
    df = detect_structure(df)
    df_out, ledger = detect_order_blocks(df, mitigation='Wick')

    # Invariante 1: re-emissão controlada
    for scope in ('internal', 'swing'):
        for direction in (BULLISH, BEARISH):
            col_created = f"ob_{scope}_{'bullish' if direction == BULLISH else 'bearish'}_created"
            assert df_out[col_created].sum() == len(
                ledger.query("scope == @scope and bias == @direction")
            )

    # Invariante 4: t_mitigation > t_creation estrito (P11)
    mitigated = ledger.dropna(subset=['t_mitigation'])
    assert (mitigated['t_mitigation'] > mitigated['t_creation']).all()

    # Invariante 5: bar_high >= bar_low
    assert (ledger['bar_high'] >= ledger['bar_low']).all()

    # Invariante 10: t_invalidation sempre pd.NaT em Wave 6
    assert ledger['t_invalidation'].isna().all()

    # Invariante 11: volumetric_intensity sempre None em Wave 6
    assert ledger['volumetric_intensity'].isna().all()

    # Invariante 8: state ∈ {'active', 'mitigated'} (sem 'breaker')
    assert set(ledger['state'].unique()).issubset({'active', 'mitigated'})

    # Cobertura mínima: pelo menos 1 mitigated, pelo menos 1 active
    assert (ledger['state'] == 'mitigated').sum() >= 1
    assert (ledger['state'] == 'active').sum() >= 1


def test_smoke_wave6_mitigation_close_mode(synthetic_df):
    """Modo Close usa close como source, não high/low. Esperado: mitigações
    são *menos frequentes* que no modo Wick (Close mais conservador)."""
    df = detect_pivots(synthetic_df, swings_length=50, internal_length=5, equal_length=3)
    df = compute_trailing_extremes(df)
    df = detect_structure(df)
    _, ledger_wick = detect_order_blocks(df, mitigation='Wick')
    _, ledger_close = detect_order_blocks(df, mitigation='Close')

    n_mit_wick = (ledger_wick['state'] == 'mitigated').sum()
    n_mit_close = (ledger_close['state'] == 'mitigated').sum()
    assert n_mit_close <= n_mit_wick


def test_smoke_wave6_bar_time_within_window(synthetic_df):
    """bar_time (= t_origin) cai dentro da janela [pivot_idx, t_creation)."""
    df = detect_pivots(synthetic_df, swings_length=50, internal_length=5, equal_length=3)
    df = compute_trailing_extremes(df)
    df = detect_structure(df)
    _, ledger = detect_order_blocks(df)

    for _, ob in ledger.iterrows():
        # bar_time corresponde a um candle dentro da janela
        assert ob['bar_time'] < ob['t_creation']


def test_smoke_wave6_parsed_high_low_inversion(synthetic_df):
    """High-volatility bars invertem parsedHigh/parsedLow (Pine linhas 127-128)."""
    # Smoke local sem expor parsed_*: verifica indiretamente que
    # OBs criados em candles de alta volatilidade têm bar_high/bar_low
    # com a inversão correta (sanity-check; teste mais detalhado em
    # implementation review).
    pass  # Detalhar quando implementation review acontecer
```

### 5.3 Spot-check híbrido contra os ~12 OBs visuais (obrigatório)

Plano em §8 deste briefing. Não é unit test (`pytest`) — é
ferramenta de validação que roda sobre o golden CSV e produz
relatório com taxa de match contra os 12 OBs do §3.1 do relatório
final da Onda 5.

---

## 6. Critério de aceite global do PR

- [ ] `pytest smc_freqtrade/tests/test_smoke_wave6.py` passa
- [ ] Pylint/black/isort sem warnings (padrão do projeto)
- [ ] `python -c "from smc_engine import detect_order_blocks; help(detect_order_blocks)"`
      mostra docstring estruturado conforme AGENTS §1.4
- [ ] Spot-check manual sobre golden CSV produz ledger com contagens
      plausíveis (ordem de dezenas; inserir
      `len(ledger), ledger['bias'].value_counts(), ledger['state'].value_counts()`
      no body do PR)
- [ ] §7.6.1 (nova subseção) e §7.8 e §8 #2 do Mapa Camada 1
      atualizados conforme §7 deste briefing
- [ ] Hooks Onda 6.1 e Onda 6.2 documentados no docstring de
      `order_blocks.py` e em §7.8 do Mapa
- [ ] Working tree limpo após implementação (AGENTS §3, §4.3)
- [ ] `VERSION` bumpada conforme AGENTS §1.3 — Marcelo confirma
      número explicitamente no PR (esperado: 0.6.0)
- [ ] Spot-check híbrido contra os ~12 OBs do §3.1 do relatório
      final da Onda 5 — relatório anexado ao body do PR

---

## 7. Atualização do `docs/MAPA_LUXALGO_CAMADA_1_v1.1.md`

Patches a aplicar **no mesmo PR da implementação Wave 6** (não PR
de doc separado). Texto exato proposto.

### 7.1 Nova subseção §7.6.1 — Caixas de Order Block

Adicionar após §7.6, antes de §7.7:

> **§7.6.1 Caixas de Order Block — regra canônica de leitura visual**
>
> Para Order Blocks (caixas retangulares no LuxAlgo SMC), a regra
> geral §7.6 ("label no ponto médio horizontal, evento temporal =
> fim da linha") aplica-se com os seguintes refinamentos:
>
> - **"Linha" =** caixa retangular do OB no chart, projetada
>   horizontalmente da vela de origem (`bar_time` ≡ `t_origin`) até
>   a vela de mitigação (`t_mitigation`), ou até a vela atual se o
>   OB ainda estiver ativo.
> - **"Fim da linha" =** `t_mitigation` quando preenchido; vela
>   atual (ou último candle visível no screenshot) caso ativo.
> - **"Ponto médio horizontal" (label) =** midpoint temporal de
>   `[bar_time, t_mitigation or current]`. **NÃO** é midpoint de
>   `[t_creation, t_mitigation]`. Razão: visualmente o LuxAlgo
>   desenha a caixa a partir da vela parsed-extreme (= `bar_time` no
>   UDT Pine, linhas 68-73 e 232), não da vela do break.
> - **Comparação engine ↔ visual:**
>   - `bar_time` da engine ↔ candle esquerdo da caixa visual (±1).
>   - `t_mitigation` da engine ↔ candle direito visível onde a caixa
>     termina / o preço penetra (±1).
>   - `[bar_low, bar_high]` da engine ↔ topo/fundo verticais da
>     caixa visual (tolerância ±5% do ATR).
> - **Caixas ainda ativas no screenshot:** se a caixa se estende até
>   o limite direito do screenshot, verificar que `t_mitigation is
>   pd.NaT` no ledger; comparar `bar_time` contra a borda esquerda
>   da caixa.
>
> Esta subseção é referência canônica para o spot-check da Onda 6.
> Aplica-se também a Breaker Blocks (Onda 6.2 futura) com o
> refinamento adicional: caixa "breaker" tem **duas** extremidades
> direitas — primeira mitigação (estado `'active' → 'breaker'`) e
> remoção definitiva (estado `'breaker' → 'removed'`). Detalhar
> quando Onda 6.2 for absorvida.

### 7.2 §7.8 — Atualizações de status

Substituir as 3 linhas correspondentes na tabela existente:

| Feature do pago | Onda da portagem em que entra | Status |
|---|---|---|
| Volumetric Order Blocks | Onda 6.1 | **Decidido** — hook `volumetric_intensity` em `order_blocks.py` |
| Breaker Blocks | Onda 6.2 | **Decidido** — hook campo `state` aceita `'breaker'` |
| OB Mitigation Method = Average | Onda 6.1 | **Decidido** — hook parâmetro `mitigation` aceita `'Average'` |

### 7.3 §8 — Decisão pendente #2 fechada

Atualizar entrada existente:

| # | Decisão | Status v1.1 | Bloqueia onda |
|---|---|---|---|
| 2 | Sliding window vs lista full-history em `parsedHighs/Lows` | **FECHADA** — `df.iloc[start:end]` sem lista global. Memória O(1) extra além do próprio DataFrame. Confirmado em Onda 6 §2 P5. | — |

---

## 8. Hooks de absorção do LuxAlgo pago

Esta onda fixa convenção para hooks de absorção. Cada hook é um par
(comentário no docstring do módulo afetado) + (entrada na §7.8 do
Mapa) + (campo reservado no UDT).

### 8.1 Hook Onda 6.1 — Volumetric Order Blocks (criado nesta onda)

No docstring de `smc_engine/order_blocks.py`, seção `LIMITAÇÕES
CONHECIDAS`:

> Volumetric Order Blocks (LuxAlgo pago) NÃO são detectados nesta
> onda. Hook reservado: campo `OrderBlock.volumetric_intensity`
> default `None`. Decisão arquitetural fechada no briefing da
> Onda 6: feature do LuxAlgo Price Action Concepts pago, adiada
> para Onda 6.1 com hook explícito. Ver
> `docs/AVALIACAO_LUXALGO_PRICE_ACTION_CONCEPTS_v1.0.md` §4.2 (spec
> conceitual) e §6.2 (classificação Categoria B — extensão sem
> mudança arquitetural; preenche `volumetric_intensity` durante o
> CREATE pass somando volume da janela `[pivot_idx, break_idx)`).

### 8.2 Hook Onda 6.2 — Breaker Blocks (criado nesta onda)

No docstring de `smc_engine/order_blocks.py`, seção `LIMITAÇÕES
CONHECIDAS`:

> Breaker Blocks (LuxAlgo pago) NÃO são detectados nesta onda. Hook
> reservado: campo `OrderBlock.state` aceita futuro valor
> `'breaker'`. Wave 6 só emite `'active'` e `'mitigated'`. Decisão
> arquitetural fechada no briefing da Onda 6: feature do LuxAlgo
> Price Action Concepts pago, adiada para Onda 6.2. Ver
> `docs/AVALIACAO_LUXALGO_PRICE_ACTION_CONCEPTS_v1.0.md` §4.2 (spec
> conceitual) e §6.2 (classificação Categoria B — refatora
> `_resolve_mitigations` para state-aware: `'active' → 'breaker'`
> em vez de remoção; segunda mitigação remove definitivamente).

### 8.3 Hook Onda 6.1 — OB Mitigation = Average (criado nesta onda)

No docstring de `smc_engine/order_blocks.py`, parâmetro `mitigation`:

> O parâmetro `mitigation` aceita apenas `'Close'` e `'Wick'` em
> Wave 6. Valor `'Average'` (midpoint da caixa, ou seja
> `(bar_high + bar_low) / 2`) é hook reservado para Onda 6.1
> (LuxAlgo Price Action Concepts pago).

### 8.4 Plano de spot-check híbrido (consume material da Onda 5)

Material pré-existente: §3.1 do
`smc_freqtrade/briefings/onda-05-final-consistency-report.md` —
13 OBs visualmente mapeados em BTC-USDT-SWAP 4H OKX (Jan-Abr 2026)
com schema:

- `Tipo` — bullish / bearish
- `Período` — date range visual da caixa
- `Faixa de preço` — low-high da caixa
- `Shot` — número(s) de screenshot

Procedimento de spot-check:

1. Pipeline completa roda sobre `tests/golden/data/btc_usdt_swap_4h_window.csv`:
   `df = detect_pivots(df); df = compute_trailing_extremes(df); df = detect_structure(df); df, ledger = detect_order_blocks(df)`.
2. Para cada OB visual `(Tipo, Período, Faixa)`:
   a. Buscar entradas no `ledger` com `bias == Tipo` e
      `[bar_time, t_mitigation or current]` ∩ `Período` ≠ ∅.
   b. Verificar `[bar_low, bar_high]` ⊆ tolerância de `Faixa`
      (±5% do ATR local).
   c. Tolerância temporal: ±1 candle (Mapa §7.4).
3. Match exato (com tolerâncias) = ratificado. Divergência
   classificada conforme Mapa §7.6:
   - **(a) Bug da engine** — abre PR de correção dedicado.
   - **(b) Diferença esperada por feature do pago** que a portagem
     ainda não absorveu (Volumetric OB, Breakers, Average) —
     registrar em §7.8 do Mapa, NÃO é bug.
   - **(c) Ambiguidade na referência** — Marcelo decide.
4. Aplicação da regra canônica §7.6.1 (nova, ver §7 deste briefing):
   label visual no midpoint de `[bar_time, t_mitigation or current]`;
   "fim da linha" = `t_mitigation` ou último candle visível.

Esperado: dos 13 OBs visuais, ≥10 ratificados em (a) ou (b). Casos
não-ratificados viram lista de divergências para o relatório anexado
ao PR.

---

## 9. Cláusula de conflito briefing vs realidade

Se ao implementar você identificar que qualquer das 12 premissas
técnicas de §2 é falsa ou ambígua na realidade do código (Onda 3 ou
Onda 5 diferentes do que este briefing assume; Pine fonte tem
comportamento não-coberto pelo Mapa; coluna de pivots tem dtype
inesperado; etc.):

1. **Pare imediatamente.** Não improvise.
2. **Reporte ao Marcelo** o gap específico, com evidência (linha do
   Pine, coluna do DataFrame, output do smoke divergindo, etc.).
3. **Aguarde decisão explícita** de Marcelo: (a) ajustar premissa via
   PR de atualização do briefing, (b) ajustar Mapa via PR dedicado,
   (c) outra orientação.

Bypass não é solução (AGENTS §1.0). Suposição calibrada não é
substituto a resposta canônica do Marcelo.

---

## 10. Referências canônicas

Ler antes de iniciar a implementação, na ordem:

1. `AGENTS.md` — governança (§1, §2, §3, §4).
2. `docs/MAPA_LUXALGO_CAMADA_1_v1.1.md` — especialmente §3
   (inventário de funções), §4 (primitivas Pine), §6 Onda 6, §7.6 e
   §7.6.1 (após patch desta onda), §7.8, §8 #2 (decisão pendente que
   esta onda fecha).
3. `docs/AVALIACAO_LUXALGO_PRICE_ACTION_CONCEPTS_v1.0.md` — §4.2
   (Volumetric OB + Breakers spec), §4.x (OB Mitigation = Average),
   §6.2 (categorização Categoria B).
4. `docs/SMC_PRINCIPIOS_E_LEGADO.md` — definição dogmática SMC de
   OB (gap documental; ver §11 item 4 deste briefing).
5. `tools/pynecore-validation/luxalgo_smc_compute_only.py` — Pine
   fonte; foco em linhas 68-73 (UDT `orderBlock`), 122-128 (setup
   parsedHigh/Low + filter), 200-221 (`deleteOrderBlocks`),
   223-236 (`storeOrdeBlock`), 238-272 (`displayStructure` com
   gatilhos em 257 e 271), 306-319 (sequência por candle).
6. `smc_freqtrade/briefings/onda-05-bos-choch-spec.md` — template
   estrutural deste briefing; spec da Onda 5 que esta onda consome.
7. `smc_freqtrade/briefings/onda-05-final-consistency-report.md` —
   §3.1 (12 OBs pré-mapeados, material do spot-check), §6.2
   (recomendação para Onda 6), **DT-4** (Mapa §7.6 patch — agora
   absorvido em §7 deste briefing).
8. `smc_freqtrade/smc_engine/types.py` — Onda 1, UDT `OrderBlock`
   atual (4 campos; esta onda adiciona 6).
9. `smc_freqtrade/smc_engine/operators.py` — Onda 2, primitivas
   `atr_wilder`, `cum_sum`, `true_range` (consumidas para
   `parsed_high`/`parsed_low`).
10. `smc_freqtrade/smc_engine/pivots.py` — Onda 3, contratos das 4
    colunas `*_idx` consumidas (dtype `float64`, bar position).
11. `smc_freqtrade/smc_engine/trailing.py` — Onda 4, padrão de
    código (groupby segmentado, ffill, sem loop por candle).
12. `smc_freqtrade/smc_engine/structure.py` — Onda 5, contrato das
    8 booleans BOS/CHoCH consumidas como gatilho de CREATE.

Operacional do PR (branch, smoke obrigatório, link raw, body, método
de abertura, tag pós-merge): AGENTS §1.2, §1.5, §3 — não duplicado
neste briefing (AGENTS §1.6).

---

## 11. Itens em aberto para a sessão de audit

Lista enxuta de pontos onde esta sessão de planning não fechou
decisão. Cada item precisa de segunda passada com olhar adversarial
antes da sessão de implementação.

1. **Slice exclusive vs inclusive end (P5).** Confirmar que Pine
   `array.slice(arr, from, to)` é `[from, to)` (exclusive end)
   antes da implementação. Hipótese atual (espelha sintaxe Python e
   convenção da maioria das linguagens de array); PyneCore compilou
   verbatim — verificar comportamento em `pynecore.lib.array` ou
   via teste sintético no smoke da Wave 6. Impacto: se exclusive,
   `df.iloc[pivot_idx:break_idx]` correto. Se inclusive,
   `df.iloc[pivot_idx:break_idx + 1]`. Erro de 1 candle no
   parsed-extreme.

2. **Contrato de saída: tuple vs helper separado.** Wave 6 propõe
   `detect_order_blocks(df) -> tuple[pd.DataFrame, pd.DataFrame]`,
   quebrando o padrão Onda 5 (`detect_structure(df) -> pd.DataFrame`).
   Audit decide se a clareza arquitetural (ledger lifecycle
   queryable) compensa a quebra de padrão, ou se a alternativa
   `df = detect_order_blocks(df); ledger = get_order_blocks_ledger(df)`
   (helper separado, com ledger reconstruído a partir das colunas
   booleans + state interno cacheado em `df.attrs`) é preferível.

3. **Naming das 8 colunas booleans.** Wave 6 propõe `ob_<scope>_<direction>_created` /
   `_mitigated`. Alternativa Pine-faithful: `ob_alert_<scope><direction>`
   (espelha `currentAlerts.internalBullishOrderBlock` etc. do Pine).
   Audit decide. Recomendação atual: `created/mitigated` mais
   informativo e separa CREATE de MITIGATE em colunas distintas.

4. **Gap dogmático SMC vs LuxAlgo.** `docs/SMC_PRINCIPIOS_E_LEGADO.md`
   sugere implicitamente que origem do OB = última vela de cor
   oposta antes do break (definição dogmática). LuxAlgo usa lógica
   diferente: vela com extremo de `parsed_low`/`parsed_high` na
   janela `[pivot_idx, break_idx)` — pode coincidir, pode não. Wave 6
   segue Pine fonte (fidelidade ao gratuito, AGENTS §1.0.1
   hierarquia de fontes). Audit decide se isso vira:
   - (a) Nova entrada em §7.8 do Mapa ("divergência esperada
     não-bug, dogmático SMC ≠ LuxAlgo"), ou
   - (b) Investigação adicional para codificar a definição
     dogmática em `SMC_PRINCIPIOS_E_LEGADO.md` antes da
     implementação, ou
   - (c) Aceitar implicitamente como pré-condição da portagem
     ("LuxAlgo gratuito é referência canônica de match exato",
     Mapa §7.1).

---

*Fim do briefing Onda 6.*
