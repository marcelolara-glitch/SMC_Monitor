# Onda 5 — Audit Report (pré-implementação)

**Briefing auditado:** `smc_freqtrade/briefings/onda-05-bos-choch-spec.md` (PR #37, mergeado, 600 linhas).
**Sessão:** auditoria estrita, zero implementação.
**Método:** confronto linha-a-linha do briefing com Pine fonte (`tools/pynecore-validation/luxalgo_smc_compute_only.py`), módulos Onda 3/4 (`pivots.py`, `trailing.py`, `types.py`, `__init__.py`), AGENTS §1.4/§2.1/§2.2, Mapa Camada 1 v1.1 §6/§7/§8, Avaliação Price Action Concepts §4.1/§6.2/§8. Snapshot lido via `git show origin/main:<path>`.

---

## 1. Sumário executivo

Briefing tem **2 achados BLOQUEANTES** que precisam ser corrigidos antes da implementação, **6 RECOMENDADOS** e **3 OPCIONAIS**. Os bloqueantes são:

1. **A.7 — §2.7 snippet Pine incorreto** (reconstrução errada na sessão anterior). O snippet do briefing usa `math.min(close, open) - low`; o Pine fonte usa `math.min(close, open - low)`. A prosa "mistura preço com distância de wick" descrevia o Pine correto, mas o snippet contradiz a prosa. Implementação seguindo o briefing como está produziria filtro de confluence **diferente do LuxAlgo**.

2. **D.1 — §7.4 do briefing colide com §7.7 já existente no Mapa**. Briefing propõe "adicionar §7.7 (Divergências esperadas vs golden visual)", mas o Mapa Camada 1 v1.1 já tem §7.7 (Para os Conflitos A/B/C). Renumerar para §7.8 ou empurrar o §7.7 atual para §7.8.

Os RECOMENDADOS cobrem: docstring fora do padrão AGENTS §1.4 (B.4.1), gaps de cobertura no smoke test (C.5.2.1 a C.5.2.4), interdependência bias↔evento sem solução prescrita (B.4.5), tipografia §11→§8 (A.8). Os OPCIONAIS são `__all__` da Onda 4 já com bug pré-existente, escolha pd.NA vs 0 para neutro, e nota sobre ordem de declaração de `internal_length` em pivots.py.

**Caminho recomendado:** PR de doc dedicado corrigindo briefing **antes** de iniciar implementação. Sem o patch dos bloqueantes, a implementação produziria divergência confirmada vs Pine fonte (no caso A.7) e o PR de Mapa quebraria a numeração existente (no caso D.1).

---

## 2. Achados por categoria

### A) Premissas técnicas (§2 do briefing)

#### A.1 — Premissa §2.1 (gatilho close-cross)

- **Severidade:** OPCIONAL (validada).
- **Localização:** linhas 48-54 do briefing.
- **Status:** Pine linhas 247 (`ta.crossover(close, p_ivot.currentLevel)`) e 261 (`ta.crossunder(close, p_ivot.currentLevel)`) confirmam gatilho exatamente como descrito. Sem ação.

#### A.2 — Premissa §2.2 (escopos consumidos)

- **Severidade:** OPCIONAL (validada).
- **Localização:** linhas 56-58 do briefing.
- **Status:** Pine linhas 309-311 confirmam que `displayStructure` (chamado em 313-314) consome apenas `swingHigh/swingLow/internalHigh/internalLow`. Equal pivots não entram. Sem ação.

#### A.3 — Premissa §2.3 (BOS vs CHoCH por bias)

- **Severidade:** OPCIONAL (com nota).
- **Localização:** linhas 60-63 do briefing.
- **Status:** condição `tag = 'CHoCH' if t_rend.bias == BEARISH else 'BOS'` confirmada em Pine linha 248 (bullish branch) e 262 (bearish branch). **Nota:** Pine inicializa `trend(0)`, NÃO `trend(na)` (linhas 109-110). Briefing trata neutro como `pd.NA`; mapeamento é semanticamente equivalente para a classificação (`0 != BEARISH` e `pd.NA != BEARISH` ambos resultam em `'BOS'`), mas a escolha pd.NA vs 0 deve estar explícita no docstring de `detect_structure`. Ver achado B.4.3.

#### A.4 — Premissa §2.4 (trends por scope independentes)

- **Severidade:** OPCIONAL (validada).
- **Localização:** linhas 65-68 do briefing.
- **Status:** Pine linhas 109-110 confirmam que `swingTrend` e `internalTrend` são `Persistent[trend]` separados. As duas chamadas a `displayStructure` (linhas 313-314) usam o trend correspondente. Sem ação.

#### A.5 — Premissa §2.5 (flag crossed por segmento) — nomes de coluna

- **Severidade:** RECOMENDADO.
- **Localização:** linhas 70-76 do briefing.
- **Problema:** prosa descreve segmentação corretamente (cada novo pivot = novo segmento via `cumsum`), mas não declara os nomes literais das colunas que delimitam segmentos. Implementação precisará referenciar `COL_SWING_HIGH_IDX`, `COL_SWING_LOW_IDX`, `COL_INTERNAL_HIGH_IDX`, `COL_INTERNAL_LOW_IDX` (de `pivots.py:80-86`). Briefing usa template abstrato `COL_<SCOPE>_<HIGH|LOW>_IDX`.
- **Correção proposta:** acrescentar nota ao final de §2.5: "Constantes consumidas em `pivots.py`: `COL_SWING_HIGH_IDX`, `COL_SWING_LOW_IDX`, `COL_INTERNAL_HIGH_IDX`, `COL_INTERNAL_LOW_IDX`. Cada bullish-break-de-swing-high segmenta por `COL_SWING_HIGH_IDX.notna().cumsum()`; cada bearish-break-de-swing-low por `COL_SWING_LOW_IDX.notna().cumsum()`; idem para internal."

#### A.6 — Premissa §2.6 (suppressão internal vs swing) — nomes de coluna

- **Severidade:** RECOMENDADO.
- **Localização:** linhas 78-81 do briefing.
- **Problema:** prosa descreve corretamente que `internal_*_level != swing_*_level` é pré-condição para internal disparar (Pine linhas 246, 259). Pine compara `internalHigh.currentLevel != swingHigh.currentLevel` antes de qualquer ffill — sempre o último pivot conhecido. Em pandas, isso vira `level_active = internal_*_level.ffill()` e `swing_*_level.ffill()`. Briefing não declara os nomes literais das colunas.
- **Correção proposta:** acrescentar nota: "Em pandas vetorizado: `extra_internal_bullish = COL_INTERNAL_HIGH_LEVEL.ffill() != COL_SWING_HIGH_LEVEL.ffill()`; `extra_internal_bearish = COL_INTERNAL_LOW_LEVEL.ffill() != COL_SWING_LOW_LEVEL.ffill()`."

#### A.7 — Premissa §2.7 (snippet Pine bullishBar/bearishBar) — **BLOQUEANTE**

- **Severidade:** BLOQUEANTE.
- **Localização:** linhas 83-99 do briefing (especificamente linhas 88-94, dentro do bloco de código `pine`).
- **Problema:** o snippet **reconstruído na sessão anterior está errado**. Briefing tem:

  ```
  bullishBar := high - math.max(close, open) > math.min(close, open) - low
  bearishBar := high - math.max(close, open) < math.min(close, open) - low
  ```

  Pine fonte (`tools/pynecore-validation/luxalgo_smc_compute_only.py` linhas 242-243) tem:

  ```
  bullishBar = high - math.max(close, open) > math.min(close, open - low)
  bearishBar = high - math.max(close, open) < math.min(close, open - low)
  ```

  A diferença é onde fecha o parêntese de `math.min`: no briefing, `math.min(close, open) - low` = `min(open, close) - low` = wick inferior do candle. No Pine, `math.min(close, open - low)` = mínimo entre o preço de fechamento e a distância open-to-low. **A prosa do briefing logo abaixo ("mistura preço com distância de wick") descreve corretamente o Pine fonte, mas contradiz o snippet.** Portar o snippet errado produziria filtro de confluence diferente do LuxAlgo gratuito — divergência sistemática vs golden.

- **Correção proposta:** substituir o bloco `pine` (linhas 87-94) por:

  ```pine
  // Pine linhas 239-243 (verbatim do PyneComp output)
  bullishBar: Persistent[bool] = True
  bearishBar: Persistent[bool] = True
  if internalFilterConfluenceInput:
      bullishBar = high - math.max(close, open) > math.min(close, open - low)
      bearishBar = high - math.max(close, open) < math.min(close, open - low)
  ```

  Mantendo a prosa que segue ("mistura preço com distância de wick") inalterada — a prosa estava certa.

#### A.8 — Premissa §2.8 (cross-reference §11)

- **Severidade:** RECOMENDADO (tipográfico).
- **Localização:** linha 103 do briefing: "Ver §11 deste briefing."
- **Problema:** briefing termina em §10. O destino correto é §8 (Hooks de absorção do LuxAlgo pago).
- **Correção proposta:** trocar "§11" por "§8".

#### A.9 — Premissa §2.9 (lookahead-safe)

- **Severidade:** OPCIONAL (validada).
- **Localização:** linhas 105-108 do briefing.
- **Status:** consistente com `pivots.py` linhas 196-200, 287-291. Sem ação.

---

### B) Spec funcional (§4 do briefing)

#### B.4.1 — Docstring de `detect_structure` fora do padrão AGENTS §1.4 — **BLOQUEANTE no PR de implementação, RECOMENDADO no patch de briefing**

- **Severidade:** RECOMENDADO no briefing (BLOQUEANTE quando PR de implementação for criado).
- **Localização:** linhas 156-186 do briefing (corpo da docstring proposta).
- **Problema:** AGENTS §1.4 (linhas 152-163 de `AGENTS.md`) declara que toda função pública deve ter docstring com 4 seções nomeadas: **OBJETIVO**, **FONTE DE DADOS**, **LIMITAÇÕES CONHECIDAS**, **NÃO FAZER**. Briefing propõe formato numpydoc (Parameters/Returns) + apenas 1 das 4 seções obrigatórias (LIMITAÇÕES CONHECIDAS). Faltam: cabeçalho explícito **OBJETIVO**, seção **FONTE DE DADOS**, seção **NÃO FAZER**. `pivots.py` (linhas 268-304) e `trailing.py` (linhas 107-143) usam o formato canônico — o briefing diverge da prática estabelecida no projeto.
- **Correção proposta:** substituir o corpo da docstring (linhas 156-186) por estrutura canônica. Modelo:

  ```
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

#### B.4.2 — Constantes de coluna §4.2

- **Severidade:** OPCIONAL.
- **Localização:** linhas 191-202 do briefing.
- **Status:** os 10 nomes (`bos_internal_bullish`, etc.) seguem a convenção snake_case dos UDTs do Pine (lowercase + underscore). Não há colisão com colunas da Onda 3 ou Onda 4. Sem ação.

#### B.4.3 — Schema §4.3 (mapeamento neutro→pd.NA)

- **Severidade:** RECOMENDADO.
- **Localização:** linhas 206-208 do briefing.
- **Problema:** texto diz "trend bias começa pd.NA". O Pine inicializa `trend(0)` (linhas 109-110), não `trend(na)`. Implementação correta dá o mesmo resultado de classificação, mas a escolha entre `pd.NA` (Int8 nullable) e `0` (int não-nullable + Int8 com fallback) é uma decisão de Camada 2 que afeta como o smoke test compara valores. Briefing assume pd.NA sem justificativa.
- **Correção proposta:** acrescentar 1 frase em §4.3 logo após "constantes já em `types.py`": "Mapeamento neutro: o Pine inicializa `trend(0)`, mas a porta usa `pd.NA` (Int8 nullable) por simetria com o tratamento de pivots Onda 3 antes da materialização. Equivalente para classificação BOS/CHoCH (`0 != BEARISH` e `pd.NA != BEARISH` ambos colapsam para 'BOS')."

#### B.4.4 — Invariantes §4.4

- **Severidade:** OPCIONAL.
- **Localização:** linhas 225-244 do briefing.
- **Status:** as 5 invariantes cobrem: mutual exclusion, monotonicidade do bias, segmentação, asymmetria CHoCH/BOS na inversão, supressão internal-vs-swing. Cobertura conceitual adequada. Sem ação.

#### B.4.5 — Algoritmo §4.5: interdependência bias↔evento — **RECOMENDADO**

- **Severidade:** RECOMENDADO.
- **Localização:** linhas 246-296 do briefing.
- **Problema:** §4.5 passos 7-8 reconhecem a circularidade ("classificação BOS/CHoCH precisa do bias **anterior** ao break, mas o bias só é atualizado pelo break") mas resolvem com texto vago ("computar primeiro a coluna bias_pre_event... Detalhamento Camada 2 fica para a sessão de implementação"). A circularidade tem duas soluções viáveis e o briefing não recomenda nenhuma:
  - **(α) Loop sequencial sobre eventos.** Itera os candles de evento em ordem temporal; para cada evento, lê o bias acumulado, classifica, atualiza bias. O(K) onde K = nº de eventos. Trivial; sem prova de equivalência necessária.
  - **(β) Vetorização com cycle-breaking.** Detectar primeiro os candles de evento bruto (`first_in_segment & extra_condition`) **independentemente** da classificação BOS/CHoCH — porque a direção (bullish/bearish) já basta para construir o `bias_running`. Depois construir `bias_running` por escopo via `cumsum`/`ffill` sobre os eventos brutos com sinal. Por fim, `bias_pre_event = bias_running.shift(1)` permite classificar cada evento sem ciclo. Totalmente vetorizado, O(N).
  - A análise de invariantes (§4.4 #1) garante que dentro de um mesmo escopo+candle os eventos bullish e bearish são mutuamente exclusivos (fisicamente impossível close > swingHigh AND close < swingLow no mesmo candle), portanto a vetorização (β) é segura.
- **Recomendação técnica:** **(β) — vetorização com cycle-breaking.** Razões: (1) consistente com o padrão da Onda 3 (`pivots.py`) e Onda 4 (`trailing.py:78-99`), que evitam loops por candle; (2) testável diretamente via `bias_running.shift(1)` como coluna intermediária verificável; (3) o ganho de perf é marginal sobre 720 candles mas significativo se a engine for chamada por análise multi-instrumento.
- **Correção proposta:** substituir os 2 últimos parágrafos de §4.5 (linhas 289-296) por:

  ```
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
  ```

---

### C) Smoke test (§5 do briefing)

#### C.5.1 — Fixture sintética §5.1

- **Severidade:** OPCIONAL.
- **Localização:** linhas 304-332 do briefing.
- **Status:** descrição em prosa é suficiente para Code construir fixture determinística. Os marcadores temporais ("~candle 20 e swing low em ~candle 60", "níveis materializam só em candle 70 e 110") são consistentes com `swings_length=50`. Sem ação. **Nota subjacente:** fixture deve usar `pd.RangeIndex` (numérico, contíguo) para os asserts atuais funcionarem — ver C.5.2.4.

#### C.5.2.1 — Asserts não cobrem internal — **RECOMENDADO**

- **Severidade:** RECOMENDADO.
- **Localização:** linhas 349-373 do briefing (`test_smoke_wave5_swing_sequence`).
- **Problema:** o teste cobre apenas swing (4 booleans `bos_swing_*` / `choch_swing_*`). Os 4 booleans `bos_internal_*` / `choch_internal_*` ficam sem teste de sequência específico. `test_smoke_wave5_mutual_exclusion` cobre todos os 8 mas só na invariante de exclusão mútua (§4.4 #1).
- **Correção proposta:** acrescentar `test_smoke_wave5_internal_sequence` paralelo a `test_smoke_wave5_swing_sequence`, usando os booleans `bos_internal_*` / `choch_internal_*` e `internal_trend_bias`. A fixture §5.1 já produz pivots internal (length=5) ao longo dos candles 0-300, então internal events naturalmente acontecem entre fases swing — basta ler as colunas correspondentes.

#### C.5.2.2 — `internal_filter_confluence=True` não testado — **RECOMENDADO**

- **Severidade:** RECOMENDADO.
- **Localização:** §5.3 (linhas 401-406). Texto chama de "caso opcional".
- **Problema:** §5.3 está apenas em prosa, sem código de teste. Filtro não-testado é filtro quebrado: o snippet Pine de §2.7 (achado A.7 acima) tem fórmula idiossincrática (`min(close, open - low)`) cujo erro de transcrição já vimos uma vez. Sem teste, regressão futura não detecta.
- **Correção proposta:** acrescentar `test_smoke_wave5_confluence_filter` que:
  - Roda `detect_structure(df_pivots, internal_filter_confluence=False)` → out_default
  - Roda `detect_structure(df_pivots, internal_filter_confluence=True)` → out_filtered
  - Asserta: para cada um dos 4 booleans internal: `(out_default[col] >= out_filtered[col]).all()` (filtro só remove eventos, nunca cria).
  - Asserta: para cada um dos 4 booleans swing: `(out_default[col] == out_filtered[col]).all()` (swing inafetado).
  - Asserta: `out_filtered[<4 booleans internal>].sum().sum() < out_default[<4 booleans internal>].sum().sum()` (algum evento de fato é filtrado — caso contrário o teste é vacuamente verdadeiro).

#### C.5.2.3 — Asserts cobrem 1 dos 4 quadrantes da invariante "flag crossed por segmento" — **RECOMENDADO**

- **Severidade:** RECOMENDADO.
- **Localização:** linhas 388-398 do briefing (`test_smoke_wave5_crossed_flag_per_segment`).
- **Problema:** o teste segmenta por `out["swing_high_idx"]` e checa `bos_swing_bullish | choch_swing_bullish`. Cobre apenas o quadrante swing/bullish. Faltam: swing/bearish (segmentar por `swing_low_idx`), internal/bullish (segmentar por `internal_high_idx`), internal/bearish (segmentar por `internal_low_idx`).
- **Correção proposta:** parametrizar o teste com `pytest.mark.parametrize` sobre os 4 quadrantes. Esqueleto:

  ```python
  @pytest.mark.parametrize("idx_col,event_cols", [
      ("swing_high_idx", ("bos_swing_bullish", "choch_swing_bullish")),
      ("swing_low_idx", ("bos_swing_bearish", "choch_swing_bearish")),
      ("internal_high_idx", ("bos_internal_bullish", "choch_internal_bullish")),
      ("internal_low_idx", ("bos_internal_bearish", "choch_internal_bearish")),
  ])
  def test_smoke_wave5_crossed_flag_per_segment(synthetic_df, idx_col, event_cols):
      df = detect_pivots(synthetic_df, swings_length=50, internal_length=5, equal_length=3)
      df = compute_trailing_extremes(df)
      out = detect_structure(df)
      segment_id = out[idx_col].notna().cumsum()
      events = out[event_cols[0]] | out[event_cols[1]]
      counts = events.groupby(segment_id).sum()
      assert (counts <= 1).all()
  ```

#### C.5.2.4 — `y - 1` / `z - 1` / `w > z` assumem índice numérico — **RECOMENDADO**

- **Severidade:** RECOMENDADO.
- **Localização:** linhas 363, 368, 372 do briefing.
- **Problema:** as expressões `out.loc[y - 1, ...]`, `out.loc[z - 1, ...]`, `assert w > z` assumem que o índice é numérico contíguo (`pd.RangeIndex`). Se a fixture §5.1 vier a usar `pd.DatetimeIndex` (que é o realista para CSVs OHLCV de produção), `y - 1` faria `Timestamp - 1ns` ou falharia, e `w > z` seria comparação de timestamps (correto, mas escondendo a diferença com `>` em integer position).
- **Correção proposta:** reescrever os asserts já no briefing usando `out.index.get_loc()`:

  ```python
  y_pos = out.index.get_loc(y)
  prev_idx = out.index[y_pos - 1]
  assert out.loc[prev_idx, "swing_trend_bias"] == BULLISH
  ```

  Custo de escrita marginal, evita refator futuro quando engine for testada contra CSV de produção (DatetimeIndex).

#### C.5.3 — §5.3 declara filtro como "opcional"

- **Severidade:** RECOMENDADO (relacionado a C.5.2.2).
- **Localização:** linha 401 do briefing: "(caso opcional)".
- **Problema:** o filtro é o único parâmetro da função; "opcional" sugere que o teste pode ser pulado. Combinado com C.5.2.2, leva à omissão. **Removendo o "opcional", §5.3 vira obrigatório** (alinhado com o critério de aceite §6 que diz "pytest passa" sem qualificação).
- **Correção proposta:** trocar título "### 5.3 Confluence filter (caso opcional)" por "### 5.3 Confluence filter (obrigatório)".

---

### D) Atualização do Mapa (§7 do briefing)

#### D.1 — §7.4 do briefing colide com §7.7 já existente no Mapa — **BLOQUEANTE**

- **Severidade:** BLOQUEANTE.
- **Localização:** linhas 490-513 do briefing (texto que propõe "Subseção nova §7.7 (Divergências esperadas vs golden visual)").
- **Problema:** o Mapa Camada 1 v1.1 atual (lido de `origin/main:docs/MAPA_LUXALGO_CAMADA_1_v1.1.md`, linhas 516-527) **já tem §7.7 com título "Para os Conflitos A/B/C do mapa"**. Adicionar uma nova §7.7 pelo briefing geraria colisão de numeração. Implementação cega seguindo o briefing produziria seção duplicada ou sobrescreveria o conteúdo dos Conflitos A/B/C.
- **Correção proposta:** **renumerar a subseção nova para §7.8** (não tem §7.8 hoje). Ajustar todas as referências cruzadas no briefing:
  - linha 461: "ratificado por screenshot do gratuito (§7.6)" — sem mudança.
  - linha 480: "registrada em §7.7 abaixo" → "registrada em §7.8 abaixo".
  - linha 490: "### 7.4 Subseção nova §7.7..." → "### 7.4 Subseção nova §7.8...".

#### D.2 — §7.1 (briefing) consistente com §7.1 do Mapa atual

- **Severidade:** OPCIONAL.
- **Localização:** linhas 435-453 do briefing.
- **Status:** texto proposto enriquece a versão atual do Mapa §7.1 (linhas 438-451) acrescentando "match exato com tolerância ±1 candle (§7.4)" e marcando o pago como "conceitual auxiliar". Compatível. Sem ação.

#### D.3 — §7.5 (briefing) — entrada nova em §7.5 do Mapa

- **Severidade:** OPCIONAL.
- **Localização:** linhas 455-462 do briefing.
- **Status:** §7.5 do Mapa atual (linhas 489-497) lista 6 itens (CSV, JSON, schema, ferramentas, README). Adicionar "Output canônico engine-derived" como 7º item é coerente. Sem ação. **Nota lateral:** briefing diz "formato definido na Onda 9, antecipado em smoke local até lá" — a Onda 9 (Mapa linhas 354-360) é "Orquestração e API pública", não é onde o formato seria fixado. Pode ser um issue para a Onda 5.5 ou para um briefing dedicado de golden.

#### D.4 — §7.6 (briefing) — Bybit vs OKX — **RECOMENDADO**

- **Severidade:** RECOMENDADO.
- **Localização:** linhas 469-470 do briefing.
- **Problema:** novo fluxo §7.6 menciona "chart BTC-USDT-SWAP 4H **Bybit**", mas §7.2 atual do Mapa (linha 455) declara "**OKX**, mesmo provedor da produção". "Bybit" no briefing foi engano de redação — fonte canônica do CSV é OKX, alinhado com Mapa §7.2.
- **Correção proposta:** trocar "Bybit" por "OKX" em §7.6 (linha 469-470 do briefing), mantendo consistência com Mapa §7.2.

#### D.5 — §7.7 (briefing) — entrada nova em §8 (decisões pendentes)

- **Severidade:** OPCIONAL.
- **Localização:** linhas 515-523 do briefing.
- **Status:** §8 atual do Mapa (linhas 533-541) tem 7 linhas numeradas 1-7. Adicionar "8 (novo) — Onda 5.5 — incluir CHoCH+" cabe. Atualizar #6 de "Aberta" para "FECHADA — método engine-derived + spot-check híbrido" é coerente com §8.1 do AVALIACAO (linha 353): "Golden dataset: gratuito ou pago como referência visual?". Sem ação.

---

### E) Hook Onda 5.5 (§8 do briefing)

#### E.1 — Cross-references AVALIACAO §4.1 e §6.2 corretas

- **Severidade:** OPCIONAL (validada).
- **Localização:** linhas 533-544 do briefing.
- **Status:** AVALIACAO §4.1 (linhas 177-185) e §6.2 (linhas 301-320) existem com o conteúdo descrito. §6.2 menciona explicitamente "CHoCH+ (Supported CHoCH) — extensão de `displayStructure` (Onda 5). Adiciona estado `failed_swing_observed` por trend." — match literal com o briefing. Sem ação.

---

## 3. Decisões que precisavam de Marcelo (RESOLVIDAS)

### M.1 — Categoria de patch para os bloqueantes — **RESOLVIDA**

**Decisão:** **(b)** PR de doc consolidado com bloqueantes + RECOMENDADOS antes da implementação. OPCIONAIS podem ser silenciados ou tratados inline durante a sessão de implementação, conforme cada caso.

### M.2 — Recomendação técnica B.4.5 (vetorização vs loop sequencial) — **RESOLVIDA**

**Decisão:** aprovada **(β) vetorização com cycle-breaking** como escolha canônica para `detect_structure`. Razões aceitas: direção (bullish/bearish) precede classificação BOS/CHoCH e independe dela; padrão consistente com Onda 3 (`pivots.py`) e Onda 4 (`trailing.py:78-99`); testabilidade via `bias_running` como coluna intermediária verificável. **Esta decisão vira premissa nova no PR de patch do briefing** (a ser inserida no §4.5 do briefing canônico, conforme correção proposta em B.4.5).

### M.3 — D.4: Bybit vs OKX — **RESOLVIDA**

**Decisão:** **OKX** é a fonte canônica do CSV golden, alinhada com §7.2 atual do Mapa. "Bybit" no briefing §7.6 foi engano de redação. **PR de patch do briefing deve corrigir "Bybit" → "OKX" em §7.6 (linhas 469-470 do briefing).**

### M.4 — C.5.2.4: opção 1 vs opção 2 — **RESOLVIDA**

**Decisão:** **opção 2** — reescrever asserts em §5.2 com `out.index.get_loc()` agora. Custo marginal de escrita, evita refator futuro quando engine for testada contra CSV de produção (DatetimeIndex). Correção proposta em C.5.2.4 acima já reflete esta escolha.

---

## 4. Caminho recomendado

**(b) PR de doc dedicado consolidando todos os achados (bloqueantes + RECOMENDADOS) antes de iniciar a implementação.**

Justificativa:
- Bloqueantes (A.7, D.1) **garantidamente** produziriam falha de match vs golden (A.7) ou quebra do Mapa (D.1) se ignorados. Sem patch, a sessão de implementação queimaria tempo investigando "por que minha porta diverge?".
- RECOMENDADOS (B.4.1 docstring, B.4.5 algoritmo, C.5.2 cobertura, D.4 Bybit→OKX) são economicamente baratos para corrigir agora e custam re-trabalho se descobertos durante implementação.
- OPCIONAIS podem ser silenciados ou tratados in-line.

Estrutura proposta do PR de doc:
- Branch: `claude/onda-05-briefing-patch-<hash>`
- 1 commit consolidado tocando apenas `smc_freqtrade/briefings/onda-05-bos-choch-spec.md`
- Body do PR lista os achados resolvidos (referência: este audit report).
- Após merge: nova sessão Code de implementação com briefing patched + audit report como inputs.

Lista canônica de correções a aplicar no PR de patch:

| # | Achado | Tipo | Ação |
|---|---|---|---|
| 1 | A.5 | RECOMENDADO | Acrescentar nota com nomes literais COL_*_IDX em §2.5 |
| 2 | A.6 | RECOMENDADO | Acrescentar nota com fórmula vetorizada em §2.6 |
| 3 | A.7 | **BLOQUEANTE** | Substituir snippet Pine em §2.7 (parêntese de `math.min`) |
| 4 | A.8 | RECOMENDADO | "§11" → "§8" em §2.8 |
| 5 | B.4.1 | RECOMENDADO | Reescrever docstring §4.1 nas 4 seções AGENTS §1.4 |
| 6 | B.4.3 | RECOMENDADO | Acrescentar 1 frase em §4.3 sobre mapeamento neutro→pd.NA |
| 7 | B.4.5 | RECOMENDADO | Substituir 2 últimos parágrafos de §4.5 por algoritmo (β) |
| 8 | C.5.2.1 | RECOMENDADO | Acrescentar `test_smoke_wave5_internal_sequence` em §5.2 |
| 9 | C.5.2.2 | RECOMENDADO | Acrescentar `test_smoke_wave5_confluence_filter` em §5.2 |
| 10 | C.5.2.3 | RECOMENDADO | Parametrizar `test_smoke_wave5_crossed_flag_per_segment` para 4 quadrantes |
| 11 | C.5.2.4 | RECOMENDADO | Reescrever `y - 1`/`z - 1` com `out.index.get_loc()` em §5.2 |
| 12 | C.5.3 | RECOMENDADO | Trocar "(caso opcional)" por "(obrigatório)" em §5.3 |
| 13 | D.1 | **BLOQUEANTE** | Renumerar §7.7 proposta para §7.8 em §7.4 do briefing |
| 14 | D.4 | RECOMENDADO | "Bybit" → "OKX" em §7.6 (linhas 469-470) |

---

## 5. Apêndice: arquivos consultados (snapshot `origin/main`)

| Arquivo | Linhas relevantes lidas |
|---|---|
| `tools/pynecore-validation/luxalgo_smc_compute_only.py` | 17-34, 95-119, 238-272, 309-314 |
| `smc_freqtrade/smc_engine/pivots.py` | 79-92 (constantes COL_*), 196-200 (idx materialization), 268-304 (docstring canônica) |
| `smc_freqtrade/smc_engine/trailing.py` | 78-99 (`_segmented_running_extreme`), 107-143 (docstring canônica) |
| `smc_freqtrade/smc_engine/types.py` | 45-46 (`BULLISH`/`BEARISH`), 85-98 (`Trend` UDT) |
| `smc_freqtrade/smc_engine/__init__.py` | 21-76 (exports atuais) |
| `AGENTS.md` | 152-163 (§1.4), 205-247 (§2.1, §2.2) |
| `docs/MAPA_LUXALGO_CAMADA_1_v1.1.md` | 308-313 (§6 Onda 5), 432-528 (§7 com §7.7 já ocupado), 531-541 (§8 decisões) |
| `docs/AVALIACAO_LUXALGO_PRICE_ACTION_CONCEPTS_v1.0.md` | 177-185 (§4.1 CHoCH+), 301-320 (§6.2 Categoria B), 349-365 (§8 decisões) |

---

*Fim do audit report Onda 5.*
