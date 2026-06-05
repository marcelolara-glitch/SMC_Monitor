# Auditoria de Causalidade / Lookahead — Wave 10.0

> **Status:** ratificado (Marcelo, conversa de abertura da Wave 10). Doc
> canônico do subprojeto. Destino no repo: `docs/AUDITORIA_CAUSALIDADE_W10.0.md`.
>
> **Princípio §0 aplicado:** todo veredito é ancorado em leitura verbatim do
> código em `main` (`marcelolara-glitch/SMC_Monitor`, `smc_freqtrade/`, HEAD
> `e77a993`, VERSION `0.9.12`) e da fonte primária do **Freqtrade 2026.3**
> (tag pinada em `requirements`). Citações no formato `arquivo:linha`. Nada
> inferido.

---

## 0. Veredito

**O engine é causal por construção.** Em todas as 6 camadas auditadas, o valor
de cada coluna no candle `T` depende **somente** de dados `≤ T`. Não há
`shift(-N)` em ponto algum do código (só aparece em docstrings dizendo "não
usar"). A hipótese de que "a fidelidade visual perseguida nas 9 ondas pode
enganar o backtest porque o engine back-data estrutura" está **refutada na
fonte**.

Consequência direta: **a Wave 10 não tem um bug de lookahead intra-TF para caçar
nem corrigir.** Os riscos reais são (a) o **lag de confirmação** das estruturas
— correto, porém grande e dependente do TF; (b) a **fronteira de integração**
com o Freqtrade (ledgers vs colunas; merge MTF; `startup_candle_count`); e (c) o
**lookahead inter-TF** do merge — que é responsabilidade do Freqtrade e está
coberto (§6).

> **Alerta de regressão:** briefar o Code para "auditar e corrigir back-dating"
> faria ele caçar um bug inexistente ou — pior — adicionar `shift` defensivo a
> código já causal, **dobrando o atraso do sinal**. **Não autorizar alteração no
> engine por motivo de lookahead.**

---

## 1. Método

Lidos verbatim: `pivots.py`, `structure.py`, `order_blocks.py`, `fvg.py`,
`liquidity_sweep.py`, `setup_state.py`, `zone_projection.py`, `engine.py`,
`result.py`, `__init__.py`, `VERSION`, `requirements`, golden CSV/README; e, no
Freqtrade 2026.3, `templates/sample_strategy.py`, `strategy/interface.py`,
`strategy/informative_decorator.py`, `strategy/strategy_helper.py`,
`commands/arguments.py`.

**Não** verificado por execução nesta auditoria: a suíte de 281 testes (exige
`freqtrade==2026.3` instalado) e as ferramentas `lookahead-analysis` /
`recursive-analysis` (exigem scaffold — 10a/10b).

---

## 2. Resultado por camada (causalidade intra-TF)

| Camada | Fonte | Mecanismo causal | Veredito |
|---|---|---|---|
| **Pivots** (swing/internal/equal) | `pivots.py:152-225` | `*_level/idx` materializa na **linha do candle de confirmação** `T`, com valor `high.shift(size)` = `high[T−size]` e `idx = T−size` como *ponteiro para trás*. Docstring: "materializa apenas no candle X (X = swing real + size)". | **Causal** [Certo] |
| **Structure** (BOS/CHoCH/CHoCH+) | `structure.py:132-153, 286-333` | Cruzamento `close > level & close.shift(1) <= level.shift(1)`; bias e nível via `shift(1)`/`ffill().shift(1)`. Só shifts **positivos**. | **Causal** [Certo] |
| **Order Blocks** (criação) | `order_blocks.py:232` | `t_creation = df['date'].iloc[break_pos]` — nasce no candle do **break**; janela do extremo `iloc[pivot_pos:break_pos]` (passado). | **Causal** [Certo] |
| **OB — `bb_volume`** | `order_blocks.py:241-261` | **Guarda** `if t_pos <= break_pos and t_pos < len(df)`: só agrega `volume[extreme+1/+2]` se `≤ break_pos`. Sem futuro. | **Causal** [Certo] |
| **OB — mitigação / morte do breaker** | `order_blocks.py:412-432` | `after_create = dates > t_creation`; `argmax` do **primeiro** toque; coluna `*_mitigated.loc[hit_label] = True` marca no **candle do toque**. | **Causal** [Certo] |
| **FVG** (criação / mitigação / IFVG) | `fvg.py:24, 47, 181` | Gap "determinado quando o terceiro candle fecha"; `t >= 2`; mitigação `date > t_creation` estrita. | **Causal** [Certo] |
| **Liquidity Sweep** | `liquidity_sweep.py:8-33` | As 4 condições dependem do **`close` do candle atual**; mitigação por `close` cruzando o nível. | **Causal** [Certo] |
| **Setup FSM** (matcher) | `setup_state.py:281-283` | `_rolling_any` = `rolling(window).max() > 0` sobre `[T−window+1, T]`. `RESOLVED` fica **fora** (stateless). | **Causal** [Certo] |

---

## 3. O achado de design real — LAG DE CONFIRMAÇÃO (e escala por TF)

Causalidade correta **implica** que uma estrutura só é conhecível algum tempo
depois de imprimir. Não é bug — é propriedade.

| Conceito | Lag (candles) | 4H | 1H | 15m | Fonte |
|---|---|---|---|---|---|
| **Swing pivot** | `swings_length` = **50** | ~8,3 d | ~2,1 d | ~12,5 h | `pivots.py` default 50 |
| Internal pivot | `internal_length` = **5** | ~20 h | ~5 h | ~75 min | default 5 |
| Equal pivot (EQH/EQL) | `equal_length` = **3** | ~12 h | ~3 h | ~45 min | default 3 |
| Structure swing | herda swing (**≥50**) | ≥8,3 d | ≥2,1 d | ≥12,5 h | consome `swing_*` |
| Order Block | lag do pivô **+** `(break − extremo)` | variável ≥ pivô | — | — | `t_creation = break_pos` |
| FVG | ~2 (fecha no 3º candle) | ~8 h | ~2 h | ~30 min | `fvg.py` |
| Mitigação / `active_*` | **0** (no candle do evento) | imediato | imediato | imediato | §2 |

**Implicação:** o mesmo parâmetro (`swing=50`) tem significado físico distinto
por TF — 8 dias no 4H, 12,5 h no 15m. As entradas devem ler o que as colunas
expõem **no candle de decisão** (garantido por `active_*`, §4). A pertinência dos
parâmetros por TF é assunto de **calibração (10c)**, não de fidelidade de
portagem (a fórmula é idêntica em qualquer TF).

---

## 4. Interface e pipeline MTF — `active_*`/`setup_*`, NUNCA os ledgers

`zone_projection.py:1-43` implementa o predicado **causal** de zona ativa,
avaliado por candle:

```
t_creation <= T AND (t_mitigation is NaT OR t_mitigation > T)
```

As **32 colunas `active_*`** existem para atravessar o merge `@informative` ("só
carrega colunas do `df`, nunca os ledgers"). A 9.5a já construiu essa ponte.

**Pipeline MTF verificado (fluxo da IStrategy da 10a):**
- `analyze(df, config) -> AnalyzeResult` é **single-TF**; retorna
  `df, ledger_ob, ledger_fvg, ledger_bpr, meta` — **sem `df_setup_state`**
  (`result.py:34-57`).
- O matcher é a função **separada** `compute_setup_state(df, config)`
  (`smc_engine/__init__.py:187`), que **exige colunas já mergeadas**
  (`setup_state.py:244`): viés do sufixo **`_4h`** (`trend_suffix`), zona do
  **`_1h`** (`zone_suffix`) e confirmação da base 15m (`setup_state.py:152-154`).
- Logo: `analyze()` roda 1× por TF (15m base + 1H/4H via `@informative`); o
  Freqtrade merge-eia com sufixo `{coluna}_{tf}`; e `compute_setup_state` roda na
  base lendo `_4h`/`_1h`/base.

**Risco residual (fronteira, não engine):** os **ledgers** carregam
`t_mitigation`/`t_invalidation` **futuros** relativos a `T`. Ler ledger em
`populate_*` **vaza futuro**.

> **Política (firme):** em `populate_*` consumir **somente** `active_*`,
> `setup_*` e demais colunas causais. Ledgers só off-line/relatórios.

---

## 5. Decisão MTF fechada (Conflito A) + reconciliação da spec

**MTF é responsabilidade da IStrategy, não do engine** — fechado na fundação e
na Wave 9.4 (MAPA §5.1 "Conflito A: FECHADO"; `VERIFICACAO_FREQTRADE.md`
§2.3-2.4). Base **15m**, informativos **1H/4H** via `@informative` nativo. O
engine **não** coordena TFs (de propósito — mantém `analyze()` simples e
testável).

`tools/mtf_align.py::align_informative` (Wave 9.4, 10 testes) é o **espelho de
teste** de `merge_informative_pair` — para validar a mecânica MTF em
sandbox/golden **sem subir o Freqtrade**. **Não é a via de produção e não deve
ser aposentado:** a IStrategy usa `@informative` nativo; o `align_informative`
permanece como ferramenta de validação offline (a equivalência das duas é o que
sela o backtest in-sandbox vs Freqtrade).

Reconciliação de `VERIFICACAO_FREQTRADE.md` §7.1 (derivou): `fair_value_gaps.py`
→ **`fvg.py`**; **`premium_discount.py` não existe**; módulos extra
(`fib_ote.py`, `zone_projection.py`, `structure.py`, `trailing.py`,
`sessions.py`); golden é CSV (`btc_usdt_swap_4h_window.csv`, 720 candles 4H — o
oráculo **visual ratificado é só 4H**; CSVs 1H/15m são fixtures de mecânica).
Decisões #2/#5 apontavam para ondas já mergeadas e causais (§2). **Ação:** anotar
§7.1/§6 como derivada em chore de doc.

---

## 6. Política de auditoria de lookahead

**No engine:** nenhuma alteração (causal por construção).

**Na fronteira (10a/10b), conforme fonte 2026.3:**
1. Consumir `active_*`/`setup_*`; **nunca** ledgers em `populate_*` (§4).
2. **MTF via `@informative` nativo.** Ordem confirmada em `interface.py`
   (`advise_indicators`): os métodos `@informative` rodam e são **mergeados
   ANTES** de `populate_indicators` → dentro de `populate_indicators` o df já tem
   `_1h`/`_4h`, e o matcher pode rodar ali. Sufixo `{coluna}_{tf}`
   (`informative_decorator.py:46-49`). **Lookahead inter-TF** (candle de TF maior
   não-fechado) é tratado pelo `merge_informative_pair` que o `@informative` usa
   (e espelhado pela guarda C3 testada em `align_informative`).
3. `startup_candle_count`: warm-up dominado por `ta.atr(200)`. **Medir com
   `recursive-analysis` (variância 0% = suficiente), não arbitrar.** Roda na 10a
   (sem entradas). Com base 15m + informativo 4H, o warm-up em candles base é
   grande — por isso medir, não estimar.
4. `lookahead-analysis`: selo empírico → **10b** (precisa de trades;
   falso-negativo se a assinatura disparar 0 trade, ex. A3).

---

## 7. Bootstrap + fonte Freqtrade (W-D1 concluído)

- VERSION **0.9.12**; HEAD `e77a993` (PR #79 mergeado: "101 colunas / 3
  ledgers"); tags até `smc-freqtrade-v0.9.12`. 9 assinaturas
  (`setup_state.py:109`).
- `freqtrade==2026.3` pinado; engine é freqtrade-free (sem import). Fonte
  primária = **tag 2026.3** (não `stable`).
- **W-D1 concluído nesta sessão.** Verificado em 2026.3: `IStrategy`
  `INTERFACE_VERSION=3` + atributos (`sample_strategy.py`); `@informative` (TF ≥
  base, sufixo `{col}_{tf}`, merge antes de `populate_indicators`);
  `recursive-analysis` é subcomando CLI (`optimize/analysis/recursive.py`);
  `merge_informative_pair`/`stoploss_from_absolute` em `strategy_helper.py`.
- 281 testes: confirmar na VM.

---

## 8. Pendências (fora da 10a)

- **W-D4** — método de ratificação por backtest (in/out-of-sample,
  walk-forward, nº mínimo de trades/assinatura). Antes da 10c.
- **W-D5** — bump-alvo (sugestão: minor `0.10.0`; decisão de Marcelo no merge).
- Validação por-TF do engine em 1H/15m (sem oráculo visual) — relevante para a
  **calibração (10c)**, não bloqueia a 10a.
- `lookahead-analysis` + callbacks ancorados (SL no OB) — **10b**.

---

## 9. Decomposição da Wave 10

`10.0` (este doc, ratificado) → **`10a`** scaffold IStrategy base-15m + MTF
(`@informative` 1H/4H) + `populate_indicators(analyze)` + `compute_setup_state` +
`recursive-analysis`, sem entradas → `10b` entry/exit + callbacks ancorados +
`lookahead-analysis` → `10c` backtest 2 anos + calibração/poda (A3/A10).
