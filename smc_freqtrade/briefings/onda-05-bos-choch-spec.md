# Briefing Onda 5 — BOS / CHoCH formal (`smc_engine/structure.py`)

**Destino do arquivo:** `briefings/onda-05-bos-choch-spec.md`
**Subprojeto:** `smc_freqtrade/`
**Branch de desenvolvimento:** definida pelo Claude Code conforme AGENTS §1.2.
**Versão:** este briefing é da onda; bump de `VERSION` segue AGENTS §1.3.

---

## 1. Contexto

A engine SMC do `smc_freqtrade/` está sendo portada do indicador LuxAlgo
SMC compute-only (`tools/pynecore-validation/luxalgo_smc_compute_only.py`).
Ondas 1-4 já foram mergeadas em `main` cobrindo: types, state, operators
stateless, detecção de pivots (swing/internal/equal) e trailing extremes
Premium/Discount/Equilibrium.

A **Onda 5** porta `displayStructure()` (Pine linhas 238-272), que detecta
**Break of Structure (BOS)** e **Change of Character (CHoCH)** sobre os
pivots da Onda 3, em duas escalas (internal `length=5`, swing `length=50`).
É a primeira onda que produz output sobre o CSV de
`tests/golden/data/btc_usdt_swap_4h_window.csv` em formato consumível
para spot-check visual ratificado.

A onda também:

- Atualiza o §7 do `docs/MAPA_LUXALGO_CAMADA_1_v1.1.md` para refletir o
  método de **golden engine-derived + spot-check híbrido** (decisão
  arquitetural fechada nesta sessão de planejamento).
- Documenta hook explícito para **Onda 5.5** (CHoCH+ — variante "supported"
  do CHoCH baseada em failed HH/LL), conforme `AVALIACAO_LUXALGO_PRICE_ACTION_CONCEPTS_v1.0.md`
  §4.1.
- **Não toca** `smc_engine/order_blocks.py` (Onda 6, ainda não iniciada),
  apesar de o Pine fonte chamar `storeOrdeBlock` dentro de
  `displayStructure`. Justificativa: Onda 6 lê os 8 booleans da Onda 5 +
  colunas `*_idx` da Onda 3 para localizar o pivot do break, sem
  necessidade de saída adicional.

---

## 2. Premissas técnicas (canônicas)

Premissas fechadas na sessão de planejamento que esta onda assume como
verdade. **Se ao implementar você identificar que alguma é falsa, pare
e levante a divergência** (AGENTS §2.1, "Conflito briefing vs.
realidade").

1. **Gatilho de break é close-cross verbatim do Pine.** Bullish:
   `(close > level) & (close.shift(1) <= level.shift(1))`. Bearish:
   `(close < level) & (close.shift(1) >= level.shift(1))`. Não é
   "body break" (`min(open,close) > level`) nem "wick break"
   (`high > level`). Justificativa: fidelidade ao Pine fonte
   (`ta.crossover` linha 247, `ta.crossunder` linha 261), alinhamento
   com Mapa §4.1 e com o LuxAlgo pago (AVALIACAO §4.1).

2. **Pivots consumidos: swing (length=50) + internal (length=5).**
   Equal pivots (length=3) NÃO entram em BOS/CHoCH — eles ficam como
   alertas EQH/EQL próprios na Onda 3.

3. **Distinção BOS vs CHoCH baseada em `t_rend.bias` no instante do
   break.** Para break bullish: `tag = 'CHoCH' if t_rend.bias == BEARISH else 'BOS'`. Para break bearish: `tag = 'CHoCH' if t_rend.bias == BULLISH else 'BOS'`. O primeiro break a partir
   do estado neutro inicial (`bias is pd.NA`) é **BOS** — só inversão
   estrita BULLISH↔BEARISH gera CHoCH.

4. **Trends por scope são independentes.** `internalTrend` e
   `swingTrend` são duas máquinas separadas (Mapa §2 itens 7-8).
   Internal pode estar bullish enquanto swing está bearish. Onda 5
   produz duas colunas `*_trend_bias` independentes.

5. **Flag `crossed` previne re-emissão no mesmo pivot, replicado por
   segmentos.** Cada novo pivot do mesmo lado/scope inicia um novo
   segmento; o primeiro candle do segmento onde a condição
   close-cross é True dispara o evento; demais candles do mesmo
   segmento ficam False mesmo se a condição persistir. Implementação
   vetorizada via `cumsum` sobre eventos de pivot novo (padrão
   análogo a `_segmented_running_extreme` em `trailing.py:78-99`).

   Constantes consumidas em `pivots.py`: `COL_SWING_HIGH_IDX`,
   `COL_SWING_LOW_IDX`, `COL_INTERNAL_HIGH_IDX`, `COL_INTERNAL_LOW_IDX`.
   Cada bullish-break-de-swing-high segmenta por
   `COL_SWING_HIGH_IDX.notna().cumsum()`; cada
   bearish-break-de-swing-low por `COL_SWING_LOW_IDX.notna().cumsum()`;
   idem para internal.

6. **Internal só dispara quando `internal_*_level != swing_*_level`.**
   Pine linha 246 (bullish) e 259 (bearish). Quando o nível interno
   converge com o swing (sequência interna confirmou exatamente o
   swing), o internal break é suprimido para evitar duplicar evento.

   Em pandas vetorizado:
   `extra_internal_bullish = COL_INTERNAL_HIGH_LEVEL.ffill() != COL_SWING_HIGH_LEVEL.ffill()`;
   `extra_internal_bearish = COL_INTERNAL_LOW_LEVEL.ffill() != COL_SWING_LOW_LEVEL.ffill()`.

7. **Confluence filter (`internal_filter_confluence`, default `False`)
   adiciona condição extra para internal, NUNCA para swing.** Pine
   linhas 241-243. Quando `True`:

   ```pine
   // Pine linhas 239-243 (verbatim do PyneComp output)
   bullishBar: Persistent[bool] = True
   bearishBar: Persistent[bool] = True
   if internalFilterConfluenceInput:
       bullishBar = high - math.max(close, open) > math.min(close, open - low)
       bearishBar = high - math.max(close, open) < math.min(close, open - low)
   ```

   Portar **verbatim**, incluindo a idiossincrasia de
   `min(close, open-low)` que mistura preço com distância de wick. Não
   racionalizar. Para swing (`internal=False`), `extraCondition = True`
   sempre.

8. **CHoCH+ (variante supported) NÃO faz parte desta onda.** É
   feature do LuxAlgo Price Action Concepts pago, adiada para
   **Onda 5.5** com hook documentado. Ver §8 deste briefing.

9. **Lookahead-safe.** Como toda onda anterior, sem `shift(-N)`. Os
   `_level` materializam apenas no candle `X = candle_real + size`
   (Onda 3); a porta da Onda 5 ffill-a esses níveis para frente, o
   que preserva fidelidade lookahead.

---

## 3. Plano de execução numerado

Cada passo declara seu critério de verificação local. Critério global
do PR é §6.

1. **Criar `smc_engine/structure.py`** implementando `detect_structure`
   conforme spec do §4. Inclui constantes `COL_*` no topo, helpers
   privados (vetorizados, sem loops por candle), função pública.
   *Verifica:* import `from smc_engine.structure import detect_structure, COL_BOS_SWING_BULLISH, ...` funciona; chamada sobre DataFrame de 100
   candles produz cópia com 10 colunas a mais nos dtypes corretos.

2. **Criar `smc_freqtrade/tests/test_smoke_wave5.py`** com smoke
   sintético conforme §5. *Verifica:* `pytest` passa; sequência conhecida
   de pivots dispara cada um dos 8 booleans no candle esperado; trend
   bias acompanha; flag `crossed` (replicado por segmentos) impede
   re-emissão dentro do mesmo segmento.

3. **Atualizar `smc_engine/__init__.py`** exportando `detect_structure`
   e as 10 constantes `COL_*` da Onda 5. *Verifica:* `from smc_engine import detect_structure` funciona; `__all__` inclui as constantes
   novas.

4. **Atualizar `docs/MAPA_LUXALGO_CAMADA_1_v1.1.md` §7** conforme spec
   de §7 deste briefing. *Verifica:* §7 lê coerente após edição;
   referências cruzadas para AVALIACAO §4.1 e §6 estão corretas;
   §8 (decisões pendentes consolidadas) ganha entrada nova "Onda 5.5
   — CHoCH+".

5. **Smoke spot-check sobre golden CSV** (rodar localmente, não
   commitado nesta onda — produto vai como artefato no PR para Marcelo
   conferir visualmente vs TradingView). *Verifica:* `python -c "import pandas as pd; from smc_engine import detect_pivots, compute_trailing_extremes, detect_structure; df = pd.read_csv(...); df = detect_pivots(df); df = compute_trailing_extremes(df); df = detect_structure(df); df[<8 booleans>].sum()"` produz contagens
   plausíveis (ordem de dezenas, não centenas nem zero).

---

## 4. Spec funcional

### 4.1 Assinatura pública

```python
def detect_structure(
    df: pd.DataFrame,
    *,
    internal_filter_confluence: bool = False,
) -> pd.DataFrame:
    """
    OBJETIVO
        Portagem vetorizada de displayStructure() do LuxAlgo SMC
        (Pine linhas 238-272). Detecta Break of Structure (BOS) e Change
        of Character (CHoCH) sobre os pivots produzidos por
        detect_pivots() (Onda 3), em duas escalas independentes:
        internal (length=5) e swing (length=swings_length=50).

    FONTE DE DADOS
        df: DataFrame com no mínimo 'close' + as 8 colunas COL_*_LEVEL e
            COL_*_IDX produzidas por detect_pivots() para os escopos
            swing e internal. Equal pivots NÃO são consumidos.
        internal_filter_confluence: replica internalFilterConfluenceInput
            do Pine (linhas 241-243). Quando True, exige bullishBar /
            bearishBar (computados verbatim, ver linhas 242-243 do Pine
            fonte) como condição extra para breaks internal. NUNCA afeta
            swing.
        A semântica `Persistent[trend].bias = 0` do Pine (estado neutro
            inicial) é mapeada para `pd.NA` nas colunas
            internal_trend_bias / swing_trend_bias. Equivalência:
            `0 != BEARISH` e `pd.NA != BEARISH` ambos colapsam para
            tag = 'BOS' na primeira detecção.

    LIMITAÇÕES CONHECIDAS
        Lookahead-safe por construção: consome apenas COL_*_LEVEL já
            materializados pela Onda 3 (que são lookahead-safe). Nenhum
            shift(-N) interno.

        CHoCH+ (variante "supported" do CHoCH com pré-condição estrutural
            de failed HH/LL na tendência prévia) NÃO é detectado nesta
            onda. Decisão arquitetural fechada no briefing da Onda 5:
            feature do LuxAlgo Price Action Concepts pago, adiada para
            Onda 5.5 com hook explícito. Ver
            docs/AVALIACAO_LUXALGO_PRICE_ACTION_CONCEPTS_v1.0.md §4.1
            (spec conceitual) e §6.2 (classificação como Categoria B —
            extensão sem mudança arquitetural; adiciona regra dentro de
            detect_structure + estado failed_swing_observed por trend).

        Ordem de declaração no Pine (linha 313: displayStructure(True)
            antes de linha 314: displayStructure()) é irrelevante na
            porta vetorizada porque os dois escopos têm trends
            independentes.

    NÃO FAZER
        Não usar shift(-N) em ponto algum.
        Não consumir trailing.* (Onda 4) — irrelevante para BOS/CHoCH.
        Não emitir efeitos colaterais sobre o DataFrame de entrada
            (operar sobre df.copy()).
        Não alterar order_blocks.py (Onda 6) — apesar de Pine chamar
            storeOrdeBlock dentro de displayStructure (linhas 257, 271),
            a Onda 6 lê os 8 booleans da Onda 5 + os COL_*_IDX da Onda 3
            para localizar o pivot do break.
        Não inline-ar nomes de coluna — usar as 10 constantes COL_*
            definidas no topo do módulo.
        Não popular EngineState (Mapa §2 v1.1).
        Não detectar CHoCH+ — Onda 5.5.
    """
```

### 4.2 Constantes de coluna (topo do módulo)

```python
COL_BOS_INTERNAL_BULLISH = "bos_internal_bullish"
COL_BOS_INTERNAL_BEARISH = "bos_internal_bearish"
COL_BOS_SWING_BULLISH = "bos_swing_bullish"
COL_BOS_SWING_BEARISH = "bos_swing_bearish"
COL_CHOCH_INTERNAL_BULLISH = "choch_internal_bullish"
COL_CHOCH_INTERNAL_BEARISH = "choch_internal_bearish"
COL_CHOCH_SWING_BULLISH = "choch_swing_bullish"
COL_CHOCH_SWING_BEARISH = "choch_swing_bearish"
COL_INTERNAL_TREND_BIAS = "internal_trend_bias"
COL_SWING_TREND_BIAS = "swing_trend_bias"
```

### 4.3 Schema de output

10 colunas anexadas. Os 8 booleans saem `bool` não-nullable (default
`False`); os 2 trend bias saem `Int8` nullable (`pd.NA` antes do primeiro
break, `BULLISH=1`/`BEARISH=-1` depois — constantes já em `types.py`).
Mapeamento neutro: o Pine inicializa `trend(0)`, mas a porta usa `pd.NA`
(Int8 nullable) por simetria com o tratamento de pivots Onda 3 antes da
materialização. Equivalente para classificação BOS/CHoCH (`0 != BEARISH`
e `pd.NA != BEARISH` ambos colapsam para 'BOS').

| Coluna | Dtype | Default | Significado |
|---|---|---|---|
| `bos_internal_bullish` | bool | False | Pine `internalBullishBOS` (linha 251) |
| `bos_internal_bearish` | bool | False | Pine `internalBearishBOS` (linha 265) |
| `bos_swing_bullish` | bool | False | Pine `swingBullishBOS` (linha 254) |
| `bos_swing_bearish` | bool | False | Pine `swingBearishBOS` (linha 268) |
| `choch_internal_bullish` | bool | False | Pine `internalBullishCHoCH` (linha 250) |
| `choch_internal_bearish` | bool | False | Pine `internalBearishCHoCH` (linha 264) |
| `choch_swing_bullish` | bool | False | Pine `swingBullishCHoCH` (linha 253) |
| `choch_swing_bearish` | bool | False | Pine `swingBearishCHoCH` (linha 267) |
| `internal_trend_bias` | Int8 (nullable) | pd.NA | `internalTrend.bias` ffill após updates |
| `swing_trend_bias` | Int8 (nullable) | pd.NA | `swingTrend.bias` ffill após updates |

### 4.4 Invariantes que o smoke deve cobrir

1. **Mutual exclusion por scope×direction:** em qualquer candle, no
   máximo um dos `{bos_X_bullish, choch_X_bullish}` é True (idem
   bearish). Pine garante via condição `tag = 'CHoCH' if ... else 'BOS'`.

2. **Trend bias muda apenas em candles de break.** Se nenhum dos 4
   booleans do scope é True no candle X, então `*_trend_bias[X] == *_trend_bias[X-1]` (ou ambos `pd.NA`).

3. **Flag `crossed` por segmento.** Em cada segmento delimitado por
   pivots consecutivos do mesmo lado/scope, no máximo um candle dispara
   `bos_X_*` ou `choch_X_*` no lado correspondente, mesmo que a
   condição close-cross persista nos candles seguintes.

4. **CHoCH só após inversão estrita.** Para qualquer candle X com
   `choch_X_bullish == True`, vale que `*_trend_bias[X-1] == BEARISH`.
   Idem para `choch_X_bearish ⇒ *_trend_bias[X-1] == BULLISH`.

5. **Suppressão internal vs swing convergindo.** Quando
   `internal_*_level.ffill()[X] == swing_*_level.ffill()[X]`, então
   `bos_internal_*` e `choch_internal_*` são False em X (no lado
   correspondente). Swing não tem essa supressão.

### 4.5 Algoritmo (em prosa, sem código pronto)

Para cada combinação `scope ∈ {internal, swing} × direction ∈ {bullish, bearish}`:

1. Selecionar coluna de nível correspondente da Onda 3:
   `level = df[COL_<SCOPE>_<HIGH|LOW>_LEVEL]`.

2. ffill o nível para virar série contínua de "nível ativo": a
   partir do candle X de materialização, `level.ffill()[Y] = level[X]`
   para todo `Y >= X` até o próximo pivot.

3. Identificar segmentos. `pivot_idx = df[COL_<SCOPE>_<HIGH|LOW>_IDX]`.
   `segment_id = pivot_idx.notna().cumsum()`. Cada segmento agrupa o
   período de validade de um pivot (do candle de materialização até
   o candle anterior à próxima materialização).

4. Calcular condição close-cross bruta. Bullish:
   `cross = (close > level_active) & (close.shift(1) <= level_active.shift(1))`.
   Bearish: análogo com `<` e `>=`.

5. Aplicar `extraCondition`. Para internal: `extra = level_active != swing_<HIGH|LOW>_LEVEL.ffill()`. Se `internal_filter_confluence`,
   acrescentar `bullishBar`/`bearishBar` (calculados conforme premissa
   §2.7). Para swing: `extra = True`.

6. Aplicar flag `crossed` por segmento. Filtrar `cross & extra`
   para reter apenas o **primeiro** candle de cada segmento onde a
   condição é True. Implementação: `first_in_segment = (cross & extra) & ~((cross & extra).groupby(segment_id).cumsum().shift(1) > 0)`.

7. Decompor em BOS vs CHoCH. Em cada candle X onde
   `first_in_segment[X] == True`, ler `trend_bias[X-1]` (que precisa
   ser construído cumulativamente — ver passo 8). Se bias prévio era
   oposto ao lado do break → CHoCH; caso contrário (BULLISH/neutro
   para break bullish, BEARISH/neutro para break bearish) → BOS.

8. Construir trend bias por scope. Inicializar como `pd.NA` ao
   longo de todo o DataFrame. Em cada candle de evento (passo 6),
   sobrescrever com `BULLISH` (break bullish) ou `BEARISH` (break
   bearish). ffill após para propagar entre candles. Ordem dos eventos
   importa para a ffill mas não é problema vetorizado: a ffill respeita
   ordem temporal natural do índice.

9. Atribuir as 10 colunas no DataFrame de saída (`result = df.copy()`).

Os passos 7 e 8 têm interdependência aparente: a classificação
BOS/CHoCH precisa do bias **anterior** ao break, mas o bias só é
atualizado pelo break. A vetorização quebra o ciclo em três passos:

(a) Detectar candles de evento bruto por direção
    (bullish_event_raw, bearish_event_raw) usando first_in_segment &
    extra_condition de §4.5 passo 6, **sem distinguir BOS/CHoCH**.
    A direção (bullish/bearish) é determinada pela coluna LEVEL
    consumida e pela sentinela close-cross — independe da
    classificação.
(b) Construir bias_running por escopo via cumsum sobre os eventos
    brutos com sinal: BULLISH (+1) em bullish_event_raw, BEARISH (-1)
    em bearish_event_raw, ffill entre eventos. O resultado é a coluna
    *_trend_bias do output.
(c) Computar bias_pre_event = bias_running.shift(1). Classificar:
    em bullish_event_raw, choch = (bias_pre_event == BEARISH);
    em bearish_event_raw, choch = (bias_pre_event == BULLISH);
    bos = ~choch & event_raw.

A análise de invariantes (§4.4 #1) garante que bullish_event_raw e
bearish_event_raw são mutuamente exclusivos no mesmo candle do mesmo
escopo, então a ordem de aplicação dentro de um candle não importa.
Esta é a abordagem recomendada — alternativa (loop sequencial sobre
eventos) é correta mas inconsistente com o padrão da Onda 3 e Onda 4.

---

## 5. Smoke test sintético (descrição conceitual)

Arquivo: `smc_freqtrade/tests/test_smoke_wave5.py`.

### 5.1 Fixture sintética

DataFrame de N=300 candles com OHLC fabricado para produzir, ao passar
por `detect_pivots(df, swings_length=50, internal_length=5, equal_length=3)` e depois por `detect_structure`, a seguinte sequência
verificável:

- **Fase 1 (candles ~0-80):** alta gradual seguida de pullback que
  forma swing high (length=50) em ~candle 20 e swing low em ~candle
  60. Internal pivots distribuídos. *Esperado:* nenhum BOS/CHoCH ainda
  (níveis materializam só em candle 70 e 110). Trend bias ambos
  `pd.NA`.

- **Fase 2 (~80-140):** preço furá o swing high (close > level).
  *Esperado:* `bos_swing_bullish[X] == True` no candle X do crossover.
  `swing_trend_bias[X] == BULLISH`. Não deve haver `choch_swing_*` em
  X (bias prévio era `pd.NA`, não BEARISH).

- **Fase 3 (~140-200):** preço cai e fura o swing low.
  *Esperado:* `choch_swing_bearish[Y] == True` (porque bias prévio era
  BULLISH). `swing_trend_bias[Y] == BEARISH`.

- **Fase 4 (~200-260):** novo break bullish (ChoCH bullish, porque
  bias prévio agora é BEARISH).
  *Esperado:* `choch_swing_bullish[Z] == True`.
  `swing_trend_bias[Z] == BULLISH`.

- **Fase 5:** outro break bullish na mesma direção (= BOS, porque
  bias atual é BULLISH).
  *Esperado:* `bos_swing_bullish[W] == True`.

### 5.2 Asserts canônicos

```python
import pandas as pd
import pytest

from smc_engine import (
    BULLISH,
    BEARISH,
    detect_pivots,
    compute_trailing_extremes,
    detect_structure,
)


def test_smoke_wave5_swing_sequence(synthetic_df):
    df = detect_pivots(synthetic_df, swings_length=50, internal_length=5, equal_length=3)
    df = compute_trailing_extremes(df)
    out = detect_structure(df)

    # Fase 2: primeiro break bullish a partir de neutro = BOS, não CHoCH
    x = out.index[out["bos_swing_bullish"]][0]
    assert not out.loc[x, "choch_swing_bullish"]
    assert out.loc[x, "swing_trend_bias"] == BULLISH

    # Fase 3: break bearish após BULLISH = CHoCH
    y = out.index[out["choch_swing_bearish"]][0]
    assert not out.loc[y, "bos_swing_bearish"]
    assert out.loc[y, "swing_trend_bias"] == BEARISH
    y_pos = out.index.get_loc(y)
    prev_y = out.index[y_pos - 1]
    assert out.loc[prev_y, "swing_trend_bias"] == BULLISH

    # Fase 4: break bullish após BEARISH = CHoCH
    z = out.index[out["choch_swing_bullish"]][0]
    assert out.loc[z, "swing_trend_bias"] == BULLISH
    z_pos = out.index.get_loc(z)
    prev_z = out.index[z_pos - 1]
    assert out.loc[prev_z, "swing_trend_bias"] == BEARISH

    # Fase 5: break bullish após BULLISH = BOS
    w = out.index[out["bos_swing_bullish"]][-1]
    assert out.index.get_loc(w) > z_pos
    assert not out.loc[w, "choch_swing_bullish"]


def test_smoke_wave5_mutual_exclusion(synthetic_df):
    df = detect_pivots(synthetic_df, swings_length=50, internal_length=5, equal_length=3)
    df = compute_trailing_extremes(df)
    out = detect_structure(df)

    # Invariante §4.4 #1
    assert not (out["bos_swing_bullish"] & out["choch_swing_bullish"]).any()
    assert not (out["bos_swing_bearish"] & out["choch_swing_bearish"]).any()
    assert not (out["bos_internal_bullish"] & out["choch_internal_bullish"]).any()
    assert not (out["bos_internal_bearish"] & out["choch_internal_bearish"]).any()


@pytest.mark.parametrize("idx_col,event_cols", [
    ("swing_high_idx", ("bos_swing_bullish", "choch_swing_bullish")),
    ("swing_low_idx", ("bos_swing_bearish", "choch_swing_bearish")),
    ("internal_high_idx", ("bos_internal_bullish", "choch_internal_bullish")),
    ("internal_low_idx", ("bos_internal_bearish", "choch_internal_bearish")),
])
def test_smoke_wave5_crossed_flag_per_segment(synthetic_df, idx_col, event_cols):
    """Mesmo segmento não dispara duas vezes mesmo com close-cross persistente."""
    df = detect_pivots(synthetic_df, swings_length=50, internal_length=5, equal_length=3)
    df = compute_trailing_extremes(df)
    out = detect_structure(df)
    segment_id = out[idx_col].notna().cumsum()
    events = out[event_cols[0]] | out[event_cols[1]]
    counts = events.groupby(segment_id).sum()
    assert (counts <= 1).all()


def test_smoke_wave5_internal_sequence(synthetic_df):
    """Paralelo a swing_sequence: cobre os 4 booleans internal e internal_trend_bias.

    A fixture §5.1 produz pivots internal (length=5) ao longo dos 300 candles;
    eventos internal naturalmente ocorrem entre fases swing.
    """
    df = detect_pivots(synthetic_df, swings_length=50, internal_length=5, equal_length=3)
    df = compute_trailing_extremes(df)
    out = detect_structure(df)

    internal_events = (
        out["bos_internal_bullish"]
        | out["bos_internal_bearish"]
        | out["choch_internal_bullish"]
        | out["choch_internal_bearish"]
    )
    assert internal_events.any()

    # Primeiro evento internal a partir de neutro: bias prévio é pd.NA, então
    # primeira detecção colapsa para BOS (Pine: tag = 'CHoCH' if bias == BEARISH else 'BOS').
    first_idx = out.index[internal_events][0]
    first_pos = out.index.get_loc(first_idx)
    if first_pos > 0:
        prev_idx = out.index[first_pos - 1]
        assert pd.isna(out.loc[prev_idx, "internal_trend_bias"])
    assert (
        out.loc[first_idx, "bos_internal_bullish"]
        or out.loc[first_idx, "bos_internal_bearish"]
    )
    assert not (
        out.loc[first_idx, "choch_internal_bullish"]
        or out.loc[first_idx, "choch_internal_bearish"]
    )
    if out.loc[first_idx, "bos_internal_bullish"]:
        assert out.loc[first_idx, "internal_trend_bias"] == BULLISH
    else:
        assert out.loc[first_idx, "internal_trend_bias"] == BEARISH


def test_smoke_wave5_confluence_filter(synthetic_df):
    """internal_filter_confluence=True só remove eventos internal; swing inafetado."""
    df = detect_pivots(synthetic_df, swings_length=50, internal_length=5, equal_length=3)
    df = compute_trailing_extremes(df)
    out_default = detect_structure(df, internal_filter_confluence=False)
    out_filtered = detect_structure(df, internal_filter_confluence=True)

    internal_cols = [
        "bos_internal_bullish",
        "bos_internal_bearish",
        "choch_internal_bullish",
        "choch_internal_bearish",
    ]
    swing_cols = [
        "bos_swing_bullish",
        "bos_swing_bearish",
        "choch_swing_bullish",
        "choch_swing_bearish",
    ]

    # Filtro só remove eventos, nunca cria
    for col in internal_cols:
        assert (out_default[col] >= out_filtered[col]).all()

    # Swing inafetado pelo filtro
    for col in swing_cols:
        assert (out_default[col] == out_filtered[col]).all()

    # Algum evento internal é de fato filtrado (caso contrário teste é vacuamente verdadeiro)
    assert (
        out_filtered[internal_cols].sum().sum()
        < out_default[internal_cols].sum().sum()
    )
```

### 5.3 Confluence filter (obrigatório)

Mesma fixture com `internal_filter_confluence=True`. *Esperado:* alguns
dos eventos `bos_internal_*`/`choch_internal_*` desaparecem (filtrados
pela condição `bullishBar`/`bearishBar`). Os eventos swing são
idênticos ao caso default. Assertion: `(df_out_default[booleans internal] >= df_out_filtered[booleans internal]).all()` por candle.

---

## 6. Critério de aceite global do PR

- [ ] `pytest smc_freqtrade/tests/test_smoke_wave5.py` passa
- [ ] Pylint/black/isort sem warnings (padrão do projeto)
- [ ] `python -c "from smc_engine import detect_structure; help(detect_structure)"`
      mostra docstring estruturado conforme AGENTS §1.4
- [ ] Spot-check manual sobre golden CSV produz contagens plausíveis
      (ordem de dezenas; inserir `df[<8 booleans>].sum()` no body do
      PR)
- [ ] §7 do Mapa Camada 1 atualizado conforme §7 deste briefing
- [ ] Hook Onda 5.5 documentado no docstring de `structure.py` e em
      §8 do Mapa
- [ ] Working tree limpo após implementação (AGENTS §3, §4.3)
- [ ] `VERSION` bumpada conforme AGENTS §1.3 — Marcelo confirma número
      explicitamente no PR

---

## 7. Atualização do `docs/MAPA_LUXALGO_CAMADA_1_v1.1.md` §7

Decisão arquitetural fechada na sessão de planejamento: golden visual
do spot-check é **híbrido** — gratuito para match exato, pago para
escopo conceitual de ondas futuras. Isso fixa a decisão pendente
§8 #1 do `AVALIACAO_LUXALGO_PRICE_ACTION_CONCEPTS_v1.0.md`.

### 7.1 Subseção §7.1 (Indicador de referência) — reescrever

Substituir o texto atual por:

> **LuxAlgo - Smart Money Concepts** (gratuito) — referência canônica
> de **match exato** da portagem. A engine deve detectar exatamente o
> que o gratuito detecta, com tolerância ±1 candle (§7.4).
>
> **LuxAlgo - Price Action Concepts™** (pago) — referência **conceitual
> auxiliar** para escopo de ondas futuras. NÃO é referência de match
> da portagem em curso porque tem 7 blocos adicionais (CHoCH+,
> Volumetric OB, Breakers, Liquidity Grabs, Trendlines, Patterns,
> Imbalances expandidos) que o gratuito não tem e a portagem só
> absorverá em ondas futuras dedicadas.
>
> Análise comparativa completa em
> `docs/AVALIACAO_LUXALGO_PRICE_ACTION_CONCEPTS_v1.0.md`. Decisões de
> absorção feature-a-feature ficam para os briefings das Ondas 5.5+
> conforme decisão pendente §8 deste mapa.

### 7.2 Subseção §7.5 (Estrutura do golden) — adicionar

Adicionar entrada sobre output canônico engine-derived:

> **Output canônico engine-derived:** `tests/golden/golden/<nome>_engine_output.parquet`
> (formato definido na Onda 9, antecipado em smoke local até lá).
> Produzido pela engine ao longo das ondas, ratificado por screenshot
> do gratuito (§7.6).

### 7.3 Subseção §7.6 (Fluxo de produção e atualização) — reescrever

Substituir o fluxo "Marcelo descreve screenshot → Claude monta JSON"
pelo método novo:

1. Marcelo configura TradingView em UTC e aplica o **LuxAlgo - Smart Money Concepts** em chart BTC-USDT-SWAP 4H OKX (mesmo CSV de
   `data/btc_usdt_swap_4h_window.csv`).
2. Engine SMC roda sobre o CSV, produz output canônico (§7.5).
3. Marcelo captura 6-8 screenshots do TradingView com o gratuito
   aplicado, cobrindo a janela completa, em ordem cronológica.
4. Sessão Claude.ai + Marcelo: cada screenshot é comparado com o
   output canônico. Match (±1 candle) → ratificado. Divergência →
   classificada em uma de três categorias:
   - **(a) Bug da engine** — abre PR de correção dedicado.
   - **(b) Diferença esperada por feature do pago** que a portagem
     ainda não absorveu (CHoCH+ até Onda 5.5, Volumetric OB até
     onda futura, etc.) — registrada em §7.8 abaixo, NÃO é bug.
   - **(c) Ambiguidade na referência** — Marcelo decide.
5. Após ratificação completa, Marcelo abre PR de "feat(golden):
   ratificar Onda N" anexando o output canônico ao
   `tests/golden/golden/`. Os screenshots ficam fora do repo
   (Drive de Marcelo).

Marcelo **não** estrutura o JSON manualmente. Engine produz; Marcelo
ratifica visualmente.

### 7.4 Subseção nova §7.8 (Divergências esperadas vs golden visual)

Adicionar subseção nova listando features do pago que a portagem em
curso **não absorve por design** (até a onda especificada):

> Estas divergências entre output da portagem (referência: gratuito) e
> screenshots do pago (caso o usuário do golden esteja no pago em
> vez de no gratuito) são **diferenças documentadas, NÃO bugs**:

| Feature do pago | Onda da portagem em que entra | Status |
|---|---|---|
| CHoCH+ (Supported CHoCH) | Onda 5.5 | **Decidido** — hook em `structure.py` |
| Volumetric Order Blocks | Onda 6.x (a decidir) | Pendente |
| Breaker Blocks | Onda 6.y (a decidir) | Pendente |
| OB Mitigation Method = Average | Onda 6.x | Pendente |
| Inverse FVG | Onda 7.x | Pendente |
| Double FVG / Balanced Price Range | Onda 7.x | Pendente |
| Liquidity Grabs (varrida) | Onda 8 | Já mapeada — decisão #5 |
| Liquidity Trendlines | Decisão de escopo | Categoria C |
| Chart Pattern Detection | Decisão de escopo | Categoria C |
| Volume Imbalance / Opening Gap | **Excluído** (perpetual swap 24/7) | Recomendação técnica AVALIACAO §4.5 |

Esta tabela é a fonte da verdade para "o que esperar de divergência
visual" e é atualizada a cada onda que absorve uma feature.

### 7.5 §8 (Decisões pendentes) — adicionar entrada

Adicionar linha na tabela de decisões pendentes:

| 8 (novo) | Onda 5.5 — incluir CHoCH+ baseado em failed HH/LL detectado por pivots da Onda 3 | Aberta | Onda 5.5 (futura) |

Atualizar entrada existente #6 (geração do golden dataset) de "Aberta"
para **"FECHADA — método engine-derived + spot-check híbrido (gratuito
match, pago conceitual) registrado em §7"**.

---

## 8. Hooks de absorção do LuxAlgo pago

Esta onda fixa convenção para hooks de absorção. Cada hook é um par
(comentário no docstring do módulo afetado) + (entrada na §7.8 do
Mapa) + (entrada em §8 decisões pendentes).

### 8.1 Hook Onda 5.5 — CHoCH+ (criado nesta onda)

No docstring de `smc_engine/structure.py`, seção `LIMITAÇÕES CONHECIDAS`:

> CHoCH+ (variante "supported" do CHoCH com pré-condição estrutural
> de failed HH/LL na tendência prévia) NÃO é detectado nesta onda.
> Decisão arquitetural fechada no briefing da Onda 5: feature do
> LuxAlgo pago, adiada para Onda 5.5 com hook explícito. Ver
> `docs/AVALIACAO_LUXALGO_PRICE_ACTION_CONCEPTS_v1.0.md` §4.1 para
> spec conceitual e §6.2 para classificação como Categoria B
> (não muda arquitetura; adiciona regra dentro de `detect_structure` +
> estado `failed_swing_observed` por trend).

### 8.2 Hooks futuros

**Não criar hooks especulativos** para Volumetric OB, Breakers, etc.
nesta onda. Cada hook nasce no briefing da onda que decide
absorvê-la (princípio AGENTS §2.2 simplicidade primeiro).

---

## 9. Cláusula de conflito briefing vs realidade

Se ao implementar você identificar que qualquer das 9 premissas
técnicas de §2 é falsa ou ambígua na realidade do código (Onda 3
diferente do que este briefing assume; Pine fonte tem comportamento
não-coberto pelo Mapa; coluna de pivots tem dtype inesperado; etc.):

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

1. `AGENTS.md` — governança (§1, §2, §3, §4)
2. `docs/MAPA_LUXALGO_CAMADA_1_v1.1.md` — especialmente §3 (inventário
   de funções), §4 (primitivas Pine), §6 Onda 5, §7 (golden, será
   atualizado por esta onda)
3. `docs/AVALIACAO_LUXALGO_PRICE_ACTION_CONCEPTS_v1.0.md` — §4.1
   (CHoCH+ spec), §6 (categorização), §8 (decisões pendentes)
4. `tools/pynecore-validation/luxalgo_smc_compute_only.py` — Pine
   fonte; foco em linhas 238-272 (`displayStructure`), com
   dependências em linhas 155-198 (`getCurrentStructure`) e 17-34
   (UDT alerts)
5. `smc_freqtrade/smc_engine/pivots.py` — Onda 3, contratos das
   colunas consumidas (`COL_*` no topo)
6. `smc_freqtrade/smc_engine/trailing.py` — Onda 4, padrão de
   código (groupby segmentado, ffill, sem loop por candle)
7. `smc_freqtrade/smc_engine/types.py` — constantes `BULLISH`,
   `BEARISH`

Operacional do PR (branch, smoke obrigatório, link raw, body, método
de abertura, tag pós-merge): AGENTS §1.2, §1.5, §3 — não duplicado
neste briefing.

---

*Fim do briefing Onda 5.*
