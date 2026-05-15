# Plano canônico Onda 9 — `engine.py` + golden completo

**Status:** plano em revisão (PR de planning). Sem código de produção.
**Branch:** `claude/plan-wave-9-engine-GJoXr`
**Base:** `origin/main` pós-merge do PR #54 (patch documental Mapa v1.1).
**VERSION atual:** `0.8.0` (Ondas 1-8 mergeadas).
**Próximo bump alvo:** `0.9.0` (no PR de implementação da Onda 9, NÃO neste).

---

## 0. Premissas e fontes

Este plano deriva exclusivamente de:

- `docs/MAPA_LUXALGO_CAMADA_1_v1.1.md` pós-#54 (§6 Onda 9, §11 patch
  pré-Onda 9, §7 golden, §8 decisões pendentes).
- Código real mergeado em `smc_freqtrade/smc_engine/` (Ondas 1-8) —
  todas as assinaturas, defaults e dependências citadas abaixo foram
  conferidas no fonte, não inferidas.
- `smc_freqtrade/tests/golden/schema/golden_schema.json` (22 tipos de
  evento ratificados, fechado para a Onda 9).
- `smc_freqtrade/tests/golden/golden/btc_usdt_swap_4h_luxalgo_smc.json`
  (skeleton atual com `events: []` e `zones: []`).
- 7 decisões aprovadas no review do pré-planning (2026-05-14):

| # | Decisão | Resultado |
|---|---------|-----------|
| 1 | PD separado? | Não — permanece em `trailing.py` |
| 2 | Eventos do golden | 22 tipos do schema canônico |
| 3 | Ordem da ratificação | Engine-first — engine produz, Marcelo ratifica |
| 4 | Retorno de `analyze()` | `AnalyzeResult` dataclass |
| 5 | `fvg.py` divergência | Patch documental aplicado (PR #54) |
| 6 | Nome `fvg.py` | Mantém — sem rename |
| 7 | `SMCConfig` | Novo `smc_engine/config.py` |

Toda a infraestrutura técnica do golden (CSV de 720 candles BTC-USDT-SWAP
4H, SHA `1a3f746cfe6095ad544c46c66e1500306627ea5224cdc3708ef994af2b3ef3fa`,
validador, schema) já existe em `smc_freqtrade/tests/golden/` e é
referência canônica para este plano.

**Refinamentos pós-review (2026-05-14):** este plano sofreu 4
patches após review do PR #55, fechando decisões que estavam
punted ao PR de implementação:

1. Threshold mínimo do df: `>= max(pivot_swings_length, ob_atr_length) + 3`.
2. Sem `df.copy()` outer no `analyze()`; teste de invariante cobre.
3. PD zones com bounds candle-a-candle (min/max ao longo da sequência).
4. `meta.ratified` virou campo de schema canônico (micro-PR
   pré-requisito da Onda 9).

Ver Apêndice B para checklist de aprovação.

---

## Seção 1 — `analyze()` e `AnalyzeResult`

### 1.1 Assinatura concreta proposta

```python
# smc_engine/engine.py

def analyze(
    df: pd.DataFrame,
    config: SMCConfig | None = None,
) -> AnalyzeResult:
    """
    Orquestrador da engine SMC. Recebe DataFrame OHLC + 'date' e produz
    AnalyzeResult com df enriquecido + 2 ledgers (OB, FVG) + meta.

    OBJETIVO
        Executar pipeline canônico das Ondas 3-8 sobre um DataFrame
        OHLC, retornando container imutável com df expandido e ledgers
        de Order Blocks e Fair Value Gaps.

    FONTE DE DADOS
        df: DataFrame com no mínimo as colunas {'open', 'high', 'low',
            'close', 'date'} (ver §1.2 abaixo para validação canônica).
        config: SMCConfig | None. Se None, usa SMCConfig() (defaults
            equivalentes ao LuxAlgo SMC gratuito).

    LIMITAÇÕES CONHECIDAS
        Engine é stateless entre chamadas (Mapa §2 v1.1). Cada chamada
            constrói df derivado from scratch.
        Não suporta MTF internamente (Conflito A resolvido pela
            IStrategy / @informative — Mapa §5.1).
        Não consome `lookahead_on` (Conflito B fechado — Mapa §5.2).

    NÃO FAZER
        Não popular EngineState (Mapa §2 v1.1).
        Não emitir efeitos colaterais sobre o df de entrada — trabalhar
            sobre cópia interna.
        Não absorver setup_state.py (é Onda 9.5).
    """
```

Pontos da assinatura:

- **`df` posicional** — não keyword-only — porque é o input principal e
  o uso 95% será `analyze(df)`. Simétrico com os 6 detectores das ondas
  3-8.
- **`config` keyword-only?** Não. Mantém posicional para permitir
  `analyze(df, SMCConfig.aggressive())` em call sites concisos. Não há
  ambiguidade com `*, kwargs` porque a função tem apenas dois
  parâmetros.
- **Retorno `AnalyzeResult`** — não tupla `(df, ledger_ob, ledger_fvg)`.
  Razão: tupla acopla call sites à ordem dos elementos e dificulta
  extensão futura (Onda 9.5 vai precisar adicionar `df_setup_state`
  sem quebrar callers).

### 1.2 Validação de entrada

`analyze()` valida o input antes de orquestrar. Erros levantam
`ValueError` com mensagem explicativa (não silenciam).

**Colunas obrigatórias do `df`:**

| Coluna | Tipo | Uso downstream |
|--------|------|----------------|
| `open` | `float64` | `structure` (bullish/bearish bar via filter), `fvg` (cálculo do threshold) |
| `high` | `float64` | Todos os 6 módulos |
| `low` | `float64` | Todos os 6 módulos |
| `close` | `float64` | `pivots` (ATR), `trailing` (PD ratio), `structure` (cross-over/under), `order_blocks` (parsed), `fvg` (threshold), `liquidity_sweep` (detect) |
| `date` | `pd.Timestamp` ou `int64` ns | `order_blocks`, `fvg` (preenchem `bar_time`, `t_creation`, `t_mitigation` dos ledgers) |

**Validações em `analyze()`:**

1. `df` é `pd.DataFrame` não-vazio. Erro se `len(df) == 0`.
2. As 5 colunas obrigatórias existem. Erro listando ausentes.
3. **Comprimento mínimo:** `len(df) >= max(config.pivot_swings_length,
   config.ob_atr_length) + 3`. Justificativa: pivots Pine usam janela
   centrada de `swings_length` candles para detectar swing
   (precisa ≥ `swings_length` no início da série), ATR Wilder seed
   consome `ob_atr_length` candles (`order_blocks.py` linha de
   `ta.atr(atr_length)`), e os módulos comparativos (`structure`,
   `fvg`) precisam de pelo menos t=2 referencial. Com defaults
   (`swings_length=50`, `ob_atr_length=200`), o threshold concreto
   é **203 candles**.

   **Decisão fechada (2026-05-14 review):** levantar `ValueError`
   com mensagem explicativa em vez de warning + execução parcial.
   Razão: output parcial com colunas NaN no início da série é
   armadilha para callers que iteram por candle — falha silenciosa.
   Mensagem de erro deve incluir o threshold derivado e o `len(df)`
   observado.

   Exemplo de mensagem:
   ```
   analyze() requer len(df) >= 203 candles
   (max(pivot_swings_length=50, ob_atr_length=200) + 3);
   recebeu len(df)=180.
   ```
4. Tipo do `date` é homogêneo (todo `pd.Timestamp` OU todo `int64`).
   Sem coerção implícita: chamador é responsável por normalizar antes.

Comportamento NÃO validado (delegado aos detectores):

- Monotonicidade temporal do `date` — os detectores são lookahead-safe
  por construção; df fora de ordem produzirá output garbage mas não
  crasha. Decisão: confiar no Freqtrade (sempre ordenado) em produção;
  documentar como pré-condição em vez de validar.
- NaN em OHLC — pandas naturalmente propaga; vetorização interna
  trata via `.fillna(False)` em comparações booleanas.

### 1.3 Dataclass `AnalyzeResult`

```python
# Onde morar: smc_engine/result.py (novo arquivo).

@dataclass(frozen=True)
class AnalyzeResult:
    """
    Container imutável retornado por analyze(). Reúne df enriquecido,
    ledgers de OB e FVG, config usada e meta de execução.

    OBJETIVO
        Encapsular os 3 outputs canônicos da engine (df + ledger_ob +
        ledger_fvg) com meta auditável (versão da engine, config,
        candle count, CSV hash quando conhecido) num único objeto
        imutável.

    FONTE DE DADOS
        Produzido apenas por smc_engine.engine.analyze(). Construtor
        livre é tolerado para testes mas não é parte da API pública.

    LIMITAÇÕES CONHECIDAS
        Imutabilidade `frozen=True` — campos mutáveis (pd.DataFrame
            interno) não são copy-on-write. Convenção: chamadores não
            mutam result.df / result.order_blocks_ledger /
            result.fvg_ledger.
        meta não inclui hash do CSV automaticamente — engine não tem
            visibilidade do arquivo fonte. Quem chamou (script /
            estratégia) preenche se quiser.

    NÃO FAZER
        Não adicionar métodos comportamentais (filter_by_state,
            to_json) — esses vivem em ferramentas separadas, não no
            container.
        Não serializar diretamente — uso é via pickle de pytest ou
            mapping manual no script de golden.
    """
    df: pd.DataFrame
    order_blocks_ledger: pd.DataFrame
    fvg_ledger: pd.DataFrame
    config_used: SMCConfig
    meta: dict[str, Any]
```

**Justificativa de localização (`result.py` vs `types.py`):**

- `types.py` atual tem responsabilidade clara: UDTs verbatim do Pine
  fonte (6 dataclasses Pine + constantes int/string). Adicionar
  `AnalyzeResult` lá quebra essa coesão: `AnalyzeResult` não existe no
  Pine, é construção da portagem.
- `result.py` separado deixa `types.py` estável (sem novos imports) e
  torna explícita a fronteira "interface da engine vs UDTs verbatim".
- Custo: +1 arquivo. Benefício: módulo `types.py` permanece auditável
  como mapeamento 1:1 com Pine, sem ruído de containers de orquestração.

**Justificativa de imutabilidade (`frozen=True`):**

- `AnalyzeResult` é retorno de função pura. Mutar campos depois é
  bug, não feature. `frozen=True` torna a violação ruidosa (`FrozenInstanceError`)
  em vez de silenciosa.
- Custo: callers que queiram "anotar" o resultado precisam construir
  novo `AnalyzeResult(**asdict(result), meta={**result.meta, 'extra': X})`.
  Aceitável — uso esperado é leitura.
- Não impede mutação dos `pd.DataFrame` internos (frozen é shallow).
  Documentar convenção: "callers tratam result.df como read-only;
  para modificar, fazer `result.df.copy()` antes". Não vamos
  introduzir cópia automática — custo de memória O(n × colunas)
  desnecessário no caminho comum.

### 1.4 Conteúdo do `meta`

`meta: dict[str, Any]` (não tipado como TypedDict para esta onda;
candidato a hardening em Onda 9.x se houver demanda). Chaves
canônicas:

```python
{
    "engine_version": "0.9.0",             # lido de smc_freqtrade/VERSION
    "candle_count": len(df),               # int
    "first_candle_date": df['date'].iloc[0],   # pd.Timestamp ou int
    "last_candle_date":  df['date'].iloc[-1],
    "modules_run": [                       # lista ordenada para debug
        "detect_pivots",
        "compute_trailing_extremes",
        "detect_structure",
        "detect_order_blocks",
        "detect_fair_value_gaps",
        "detect_liquidity_sweeps",
    ],
    "config_hash": "...",                  # sha256 hex de repr(config)
                                           # — opcional, útil para golden
}
```

**Não incluído (deliberado):**

- `ohlcv_csv_sha256` — engine não tem visibilidade do arquivo fonte;
  o script de geração do golden (§5) preenche separadamente no JSON.
- `produced_at_utc` — engine não toca relógio; redundante com
  artefatos externos (commit time, JSON `produced_at_utc`).

---

## Seção 2 — `SMCConfig` em `smc_engine/config.py`

### 2.1 Catálogo completo de parâmetros das Ondas 3-8

Levantado verbatim dos 6 módulos atualmente mergeados:

**Onda 3 — `pivots.detect_pivots`** (5 parâmetros):

| Parâmetro | Tipo | Default | Origem Pine |
|-----------|------|---------|-------------|
| `swings_length` | `int` | `50` | `swingsLengthInput` |
| `internal_length` | `int` | `5` | hardcoded Pine linha 286 |
| `equal_length` | `int` | `3` | `equalHighsLowsLengthInput` |
| `equal_threshold` | `float` | `0.1` | `equalHighsLowsThresholdInput` |
| `atr` | `pd.Series \| None` | `None` (calcula internamente) | derivado de `ta.atr(200)` |

**Onda 4 — `trailing.compute_trailing_extremes`** (0 parâmetros).
Apenas consome df. Sem inputs.

**Onda 5 — `structure.detect_structure`** (1 parâmetro):

| Parâmetro | Tipo | Default | Origem Pine |
|-----------|------|---------|-------------|
| `internal_filter_confluence` | `bool` | `False` | `internalFilterConfluenceInput` |

**Onda 6 — `order_blocks.detect_order_blocks`** (3 parâmetros):

| Parâmetro | Tipo | Default | Origem Pine |
|-----------|------|---------|-------------|
| `ob_filter` | `Literal['Atr', 'Range']` | `'Atr'` | `orderBlockFilterInput` |
| `mitigation` | `Literal['Close', 'Wick']` | `'Wick'` | `orderBlockMitigationInput` |
| `atr_length` | `int` | `200` | `ta.atr(200)` Pine linha 124 |

**Onda 7 — `fvg.detect_fair_value_gaps`** (1 parâmetro):

| Parâmetro | Tipo | Default | Origem Pine |
|-----------|------|---------|-------------|
| `auto_threshold` | `bool` | `True` | `fairValueGapsThresholdInput` |

**Onda 8 — `liquidity_sweep.detect_liquidity_sweeps`** (4 parâmetros):

| Parâmetro | Tipo | Default | Origem Pine |
|-----------|------|---------|-------------|
| `pivot_sources` | `tuple[str, ...]` | `('equal', 'internal')` | subset de `{'equal','internal','swing'}` |
| `sweep_max_extension_bars` | `int` | `300` | Pine `maxB=300` |
| `sweep_max_pivot_age_bars` | `int` | `2000` | Pine hardcoded 2000 |
| `qualify_with_pd_zone` | `bool` | `False` | extensão da portagem |

**Total:** 14 parâmetros (incluindo `atr` que vira hook não-config).

### 2.2 Estrutura proposta — campos planos

```python
# smc_engine/config.py

from __future__ import annotations
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class SMCConfig:
    """
    Configuração canônica da engine SMC. Agrupa os 14 parâmetros dos
    6 detectores das Ondas 3-8 num único objeto imutável.

    OBJETIVO
        Substituir a passagem ad-hoc de **kwargs ao orquestrador
        analyze() por um container tipado, imutável e auto-validado.

    FONTE DE DADOS
        Construída pelo chamador (script, estratégia, teste). Engine
        consome read-only durante analyze().

    LIMITAÇÕES CONHECIDAS
        Campos planos (não sub-dataclasses por onda) — vide §2.3.
        Sem `atr` aqui (hook não-config): se chamador quiser ATR
            customizado, calcula antes e passa via df. Plain de
            simplicidade dominante.

    NÃO FAZER
        Não inserir campos sem equivalente no Pine ou na portagem
            (ex.: `setup_state_*` é Onda 9.5).
        Não usar typing.Optional sem necessidade — preserva clareza
            de defaults canônicos.
    """
    # ── Onda 3 — pivots ───────────────────────────────────────────
    pivot_swings_length: int = 50
    pivot_internal_length: int = 5
    pivot_equal_length: int = 3
    pivot_equal_threshold: float = 0.1

    # ── Onda 5 — structure ────────────────────────────────────────
    structure_internal_filter_confluence: bool = False

    # ── Onda 6 — order blocks ─────────────────────────────────────
    ob_filter: Literal['Atr', 'Range'] = 'Atr'
    ob_mitigation: Literal['Close', 'Wick'] = 'Wick'
    ob_atr_length: int = 200

    # ── Onda 7 — fair value gaps ──────────────────────────────────
    fvg_auto_threshold: bool = True

    # ── Onda 8 — liquidity sweeps ─────────────────────────────────
    sweep_pivot_sources: tuple[str, ...] = ('equal', 'internal')
    sweep_max_extension_bars: int = 300
    sweep_max_pivot_age_bars: int = 2000
    sweep_qualify_with_pd_zone: bool = False

    def __post_init__(self) -> None:
        ...  # validações — §2.4
```

### 2.3 Decisão: campos planos vs sub-dataclasses

**Avaliadas duas estruturas:**

**(A) Planos** (proposta acima):

```python
SMCConfig(pivot_swings_length=50, ob_mitigation='Wick', ...)
```

**(B) Sub-dataclasses** (alternativa):

```python
SMCConfig(
    pivots=PivotsConfig(swings_length=50),
    order_blocks=OrderBlocksConfig(mitigation='Wick'),
    sweeps=SweepsConfig(...),
)
```

**Decisão: planos (A).**

Razões:

1. **14 campos em 6 grupos** com profundidade média 2-3 não justificam
   o custo de 5 sub-dataclasses (PivotsConfig, StructureConfig,
   OrderBlocksConfig, FVGConfig, SweepsConfig). Sub-grupos só pagam
   quando o número de campos por grupo > 5 ou quando há re-uso entre
   contextos.
2. **API ergonômica.** `SMCConfig(ob_mitigation='Close')` é mais legível
   que `SMCConfig(order_blocks=OrderBlocksConfig(mitigation='Close'))`
   no call site mais comum (overriding 1-2 defaults).
3. **Prefixos por onda** (`pivot_*`, `ob_*`, `sweep_*`) preservam
   pertencimento sem precisar de namespacing aninhado.
4. **Custo de migração futura:** se um dia houver razão real para
   agrupar (ex.: muitos campos novos em Onda 6.1 Volumetric OB),
   refatorar para sub-dataclasses é mecânico — não bloqueia esta onda.

### 2.4 Validações em `__post_init__`

```python
def __post_init__(self) -> None:
    if self.pivot_swings_length < 2:
        raise ValueError(
            f"pivot_swings_length deve ser >= 2 (recebeu "
            f"{self.pivot_swings_length}); Pine fonte usa 50."
        )
    if self.pivot_internal_length < 2:
        raise ValueError(f"pivot_internal_length deve ser >= 2; "
                         f"recebeu {self.pivot_internal_length}")
    if self.pivot_equal_length < 2:
        raise ValueError(f"pivot_equal_length deve ser >= 2; "
                         f"recebeu {self.pivot_equal_length}")
    if not (0 < self.pivot_equal_threshold <= 10):
        raise ValueError("pivot_equal_threshold em ATR-units deve "
                         "estar em (0, 10]; recebeu "
                         f"{self.pivot_equal_threshold}")
    if self.ob_filter not in ('Atr', 'Range'):
        raise ValueError("ob_filter deve ser 'Atr' ou 'Range'; "
                         f"recebeu {self.ob_filter!r}")
    if self.ob_mitigation not in ('Close', 'Wick'):
        raise ValueError("ob_mitigation deve ser 'Close' ou 'Wick' "
                         f"em Wave 6; recebeu {self.ob_mitigation!r}. "
                         "'Average' é hook Onda 6.1.")
    if self.ob_atr_length < 1:
        raise ValueError("ob_atr_length deve ser >= 1; recebeu "
                         f"{self.ob_atr_length}")
    if not self.sweep_pivot_sources:
        raise ValueError("sweep_pivot_sources não pode ser vazio; "
                         "aceita subset de {'equal','internal','swing'}")
    allowed = frozenset({'equal', 'internal', 'swing'})
    for src in self.sweep_pivot_sources:
        if src not in allowed:
            raise ValueError(
                f"sweep_pivot_sources contém valor inválido {src!r}; "
                f"aceita apenas subset de {sorted(allowed)!r}"
            )
    if self.sweep_max_extension_bars < 1:
        raise ValueError("sweep_max_extension_bars deve ser >= 1; "
                         f"recebeu {self.sweep_max_extension_bars}")
    if self.sweep_max_pivot_age_bars < self.sweep_max_extension_bars:
        raise ValueError(
            "sweep_max_pivot_age_bars deve ser >= "
            "sweep_max_extension_bars; recebeu "
            f"{self.sweep_max_pivot_age_bars} < "
            f"{self.sweep_max_extension_bars}"
        )
```

Observação: as validações de `liquidity_sweep._validate_inputs` ficam
**duplicadas** entre `SMCConfig.__post_init__` (catch-cedo) e
`detect_liquidity_sweeps` (catch-tardio, no caso de uso direto sem
SMCConfig). Decisão: aceitar a duplicação — o detector continua
chamável standalone (testes, scripts) sem exigir SMCConfig, então
não pode delegar.

### 2.5 Presets — adiados para Onda 10

```python
# NÃO entrar na Onda 9. Skeleton documentado:
# @classmethod
# def luxalgo_default(cls) -> SMCConfig: ...     # = SMCConfig()
# @classmethod
# def conservative(cls) -> SMCConfig: ...        # length maiores
# @classmethod
# def aggressive(cls)  -> SMCConfig: ...         # length menores
```

**Justificativa:** "conservador" e "agressivo" exigem calibração
empírica (hyperopt) sobre o golden, que ainda não está ratificado.
Definir presets neste momento é especulação. Onda 9 expõe
`SMCConfig()` com defaults LuxAlgo (= match exato do indicador
gratuito) e fica nisso.

Nada bloqueado: callers podem instanciar `SMCConfig(pivot_swings_length=80)`
para "conservador artesanal" sem precisar do classmethod.

---

## Seção 3 — Ordem de orquestração

### 3.1 Grafo de dependências (conferido no código mergeado)

```
                    ┌─────────────────────────────┐
                    │  detect_pivots  (Onda 3)    │
                    │  reads:  open/high/low/close│
                    │  writes: 14 colunas swing/  │
                    │          internal/equal     │
                    └──────┬──────────────────┬───┘
                           │                  │
                           ▼                  ▼
   ┌───────────────────────────┐   ┌──────────────────────────┐
   │ compute_trailing_extremes │   │ detect_structure         │
   │ (Onda 4)                  │   │ (Onda 5)                 │
   │ reads:  swing_*_level     │   │ reads:  swing+internal   │
   │ writes: 4 colunas         │   │         level/idx        │
   │ trailing+pd_zone          │   │ writes: 10 cols BOS/CHoCH│
   └──────────┬────────────────┘   └─────────────┬────────────┘
              │                                  │
              │                                  ▼
              │                  ┌──────────────────────────┐
              │                  │ detect_order_blocks      │
              │                  │ (Onda 6)                 │
              │                  │ reads: COL_*_IDX (Onda3) │
              │                  │      + 8 BOS/CHoCH       │
              │                  │      + 'date'            │
              │                  │ writes: 8 cols + ledger  │
              │                  └──────────────────────────┘
              │
              ▼
   ┌───────────────────────────────────┐
   │ detect_liquidity_sweeps (Onda 8)  │
   │ reads:  *_level/*_idx (Onda 3),   │
   │         pd_zone (Onda 4, opcional)│
   │ writes: 12 colunas sweep_*        │
   └───────────────────────────────────┘

   ┌───────────────────────────────────┐
   │ detect_fair_value_gaps (Onda 7)   │
   │ INDEPENDENTE — só lê OHLC + date  │
   │ writes: 4 colunas + ledger        │
   └───────────────────────────────────┘
```

### 3.2 Sequência canônica dentro de `analyze()`

```python
def analyze(df, config=None):
    if config is None:
        config = SMCConfig()

    _validate_input(df, config)  # §1.2

    # Sem df.copy() outer — cada detector já faz cópia interna
    # (decisão fechada no review 2026-05-14, §3.4).
    work = df

    # 1. Pivots (base de tudo)
    work = detect_pivots(
        work,
        swings_length=config.pivot_swings_length,
        internal_length=config.pivot_internal_length,
        equal_length=config.pivot_equal_length,
        equal_threshold=config.pivot_equal_threshold,
    )

    # 2. Trailing extremes + PD (precisa de swing_*_level)
    work = compute_trailing_extremes(work)

    # 3. Structure BOS/CHoCH (precisa de swing+internal pivots)
    work = detect_structure(
        work,
        internal_filter_confluence=(
            config.structure_internal_filter_confluence
        ),
    )

    # 4. Order Blocks (precisa de pivots COL_*_IDX + 8 booleans Onda 5)
    work, ledger_ob = detect_order_blocks(
        work,
        ob_filter=config.ob_filter,
        mitigation=config.ob_mitigation,
        atr_length=config.ob_atr_length,
    )

    # 5. Fair Value Gaps (independente — só OHLC + date)
    work, ledger_fvg = detect_fair_value_gaps(
        work,
        auto_threshold=config.fvg_auto_threshold,
    )

    # 6. Liquidity Sweeps (precisa de pivots + opcionalmente pd_zone)
    work = detect_liquidity_sweeps(
        work,
        pivot_sources=config.sweep_pivot_sources,
        sweep_max_extension_bars=config.sweep_max_extension_bars,
        sweep_max_pivot_age_bars=config.sweep_max_pivot_age_bars,
        qualify_with_pd_zone=config.sweep_qualify_with_pd_zone,
    )

    return AnalyzeResult(
        df=work,
        order_blocks_ledger=ledger_ob,
        fvg_ledger=ledger_fvg,
        config_used=config,
        meta={
            "engine_version": _read_version(),
            "candle_count": len(work),
            "first_candle_date": work['date'].iloc[0],
            "last_candle_date":  work['date'].iloc[-1],
            "modules_run": [...],
        },
    )
```

### 3.3 Posição do FVG na sequência

FVG é independente (só lê OHLC + date). Tecnicamente paralelizável,
mas:

- O custo de paralelização (threads/processes) supera o ganho em
  workloads de 720 candles (~ms).
- Vetorização em pandas já é multi-thread sob o capô.
- Ordem síncrona facilita debugging (mesmo erro reproduz na mesma
  ordem) e reduz superfície de teste.

**Decisão:** rodar FVG sequencialmente após Order Blocks (passo 5
acima). Posição arbitrária dentro do bloco independente; coloca-se
após OB para que ledgers de OB e FVG sejam construídos em sequência
clara no AnalyzeResult.

### 3.4 Estratégia anti-mutação

Cada detector das Ondas 3-8 já chama `df.copy()` internamente
(conferido no código mergeado: `pivots.py`, `trailing.py`,
`structure.py`, `order_blocks.py`, `fvg.py`, `liquidity_sweep.py`
todos abrem com `df = df.copy()` ou equivalente).

`analyze()` **não** faz cópia outer redundante. A imutabilidade do
input é garantida pelas cópias internas dos detectores.

**Decisão fechada (2026-05-14 review):** confiar nas cópias dos
detectores e validar a invariante via teste de integração, não
via duplicação de cópias.

**Teste de invariante** (em `tests/test_integration_invariants.py`,
§6.1 deste plano):

```python
def test_analyze_does_not_mutate_input():
    df_before = make_synth_df()
    df_snapshot = df_before.copy()
    analyze(df_before)
    pd.testing.assert_frame_equal(df_before, df_snapshot)
```

Se algum detector futuro esquecer a cópia interna, o teste pega
imediatamente. Custo de manter o teste: ~5 linhas; custo de manter
a cópia outer: O(n × colunas) por chamada em produção (negligível
em scale 720, mas conceitualmente impuro).

**Custo cumulativo dos `df.copy()` internos:** 6 cópias sequenciais
(~7 dataframes em pico antes do GC). Para 720 candles × ~50 colunas
finais, pico < 500KB. Aceitável.

**Não otimizar prematuramente nesta onda.** Onda 10 (backtest em
milhares de iterações) pode revelar custo real e abrir issue
separado para perfil.

### 3.5 Error behavior

**Decisão: levantar exceção, não suprimir.**

- Erro em qualquer detector → propaga via `raise` para `analyze()`,
  que propaga para o caller.
- Sem fallback do tipo "se pivots falhar, retorna df sem pivots".
  Razão: estado parcial é pior que falha — caller que ignora o
  raise tem zero garantia de correção.
- Os detectores atuais não levantam exceções espontaneamente (são
  vetorizados e tratam NaN), então erro real significa bug ou
  input inválido — exatamente os casos onde silenciar é dano.

**Caso especial: df muito curto.** `_validate_input` rejeita
explicitamente antes de qualquer detector rodar (§1.2 ponto 3),
com mensagem clara: "df tem N candles; engine requer >= M para
pipeline completo".

---

## Seção 4 — `__init__.py` pós-Onda 9

### 4.1 Adições

Três novos símbolos:

```python
from .engine import analyze
from .config import SMCConfig
from .result import AnalyzeResult
```

Incluídos em `__all__` no início da lista, antes dos UDTs, para
sinalizar que são a API pública principal:

```python
__all__ = [
    # API pública (Onda 9)
    "analyze",
    "SMCConfig",
    "AnalyzeResult",
    # Dataclasses (UDTs)
    "Pivot",
    "Trend",
    ...
]
```

### 4.2 Remoções

**Aviso atual a remover da docstring** (lines 16-18):

```
LIMITAÇÕES CONHECIDAS
    Não há função analyze() ainda. Tentativa de uso para detecção SMC
    completa falha com ImportError até Onda 9.
```

Substituir por:

```
LIMITAÇÕES CONHECIDAS
    `analyze()` opera single-TF. Multi-TF é responsabilidade da
    IStrategy (Mapa §5.1, Conflito A fechado).
    `setup_state` (máquina ARMED → PENDING → CONFIRMED) é hook
    Onda 9.5 (Mapa §6 Onda 9.5).
```

### 4.3 Backward compatibility

**Todos os exports atuais permanecem** — Ondas 3-8 mantêm acesso
direto aos detectores e constantes `COL_*` para casos avançados
(testes, scripts standalone, pesquisa). Confirmado: a contagem
atual é 6 detectores + 50+ constantes `COL_*` + 7 UDTs + 1
EngineState + 4 + 4 = 8 constantes Pine (BULLISH, BEARISH,
BULLISH_LEG, BEARISH_LEG, ATR, RANGE, CLOSE, HIGHLOW).

Nada é renomeado, deprecado ou tocado em Ondas 1-8. **Zero risco de
regressão para callers existentes** (scripts da Onda 8, testes
smoke).

### 4.4 Ordem proposta de `__all__`

```python
__all__ = [
    # ── API pública (Onda 9) ──
    "analyze",
    "SMCConfig",
    "AnalyzeResult",
    # ── Dataclasses (UDTs Pine) ──
    "Pivot", "Trend", "Alerts", "OrderBlock", "FairValueGap",
    "LiquiditySweep", "TrailingExtremes",
    # ── State container ──
    "EngineState",
    # ── Onda 3 ─ pivots ──
    "detect_pivots", "COL_SWING_HIGH_LEVEL", ...
    # ── Onda 4 ─ trailing + PD ──
    "compute_trailing_extremes", ...
    # ── Onda 5 ─ structure ──
    "detect_structure", ...
    # ── Onda 6 ─ order_blocks ──
    "detect_order_blocks", ...
    # ── Onda 7 ─ fvg ──
    "detect_fair_value_gaps", ...
    # ── Onda 8 ─ liquidity_sweep ──
    "detect_liquidity_sweeps", ...
    # ── Constantes Pine ──
    "BULLISH", "BEARISH", "BULLISH_LEG", "BEARISH_LEG",
    "ATR", "RANGE", "CLOSE", "HIGHLOW",
]
```

---

## Seção 5 — Geração do golden completo (engine-first)

### 5.1 Ferramenta

**Arquivo:** `smc_freqtrade/tools/generate_golden_engine_output.py`

(Padrão alinhado com `tools/run_wave8_engine_on_golden.py`, já
mergeado.)

### 5.2 Pipeline

```
1. Parse CLI args
   - --csv PATH (default: tests/golden/data/btc_usdt_swap_4h_window.csv)
   - --schema PATH (default: tests/golden/schema/golden_schema.json)
   - --output PATH (default: tests/golden/golden/btc_usdt_swap_4h_luxalgo_smc.json)
   - --config-preset {default} (luxalgo_default por enquanto)

2. Carrega CSV
   - read_csv normalizando timestamp_utc -> 'date' (pd.Timestamp UTC)
   - Verifica SHA-256 do CSV; aborta se não bater com
     btc_usdt_swap_4h_window.csv.sha256.

3. Roda analyze()
   - config = SMCConfig()  # defaults LuxAlgo
   - result = analyze(df, config)

4. Mapeia colunas → 22 event_type
   (§5.3 detalha as 22 regras)
   Para cada candle do df:
     - Para cada bool column True → emite 1 event dict.
     - timestamp_utc = ISO 8601 do df['date'].iloc[t].
     - candle_idx = t.
     - screenshot_id = "" (placeholder; preenchido no spot-check).

5. Mapeia `pd_zone` → `zones[]` (decisão fechada no review
   2026-05-14: bounds candle-a-candle)

   - Sequências contíguas de mesmo `pd_zone` viram 1 zone com
     `valid_from_utc` (primeiro candle da sequência) e
     `valid_until_utc` (último candle da sequência).
   - `zone_type`: `'premium' | 'discount' | 'equilibrium'`, mapping
     direto.
   - `upper_bound`: `df['trailing_top'].iloc[idx_from:idx_until+1].max()`
     — máximo de `trailing_top` ao longo da sequência inteira da zona.
   - `lower_bound`: `df['trailing_bottom'].iloc[idx_from:idx_until+1].min()`
     — mínimo de `trailing_bottom` ao longo da sequência inteira da zona.

   **Justificativa (candle-a-candle vs snapshot):** as zonas
   Premium/Discount/Equilibrium do LuxAlgo são dinâmicas — o
   trailing extremes pode se expandir/contrair dentro de uma mesma
   zona (sem alterar `pd_zone`). Bounds snapshot do início perde
   informação sobre o range real ocupado pela zona durante sua
   validade. Bounds candle-a-candle (`max`/`min` ao longo da
   sequência) preservam o envelope geométrico completo da zona,
   facilitando spot-check visual contra TradingView (onde a
   visualização sombreia a zona conforme trailing top/bottom mudam).

   **Equilíbrio:** `equilibrium` ocorre exatamente quando
   `pd_ratio == 0.5` (vide §6.1 ponto e). Sequência de equilíbrio
   em prática tem 1 candle só, mas o mapping suporta sequência mais
   longa se ocorrer.

   **Borderline:** se `pd_zone is pd.NA` em algum candle (caso
   extremo: trailing_top == trailing_bottom, `pd_ratio == NaN`),
   interromper a sequência corrente — esse candle não vai em
   nenhuma zone.

6. Monta meta canônica
   - indicator: "LuxAlgo - Smart Money Concepts"
   - indicator_version: "engine-derived v0.9.0"
   - tradingview_timezone: "UTC"
   - instrument: "BTC-USDT-SWAP"
   - exchange: "OKX"
   - timeframe: "4h"
   - window_start_utc / window_end_utc: do df
   - ohlcv_csv_sha256: lido do .sha256 sidecar
   - extracted_by: "engine analyze() automated"
   - structured_by: "engine output v0.9.0, ratified by Marcelo
       via spot-check"   # texto literal (independente do estado de ratificação)
   - produced_at_utc: datetime.utcnow() ISO
   - scope_included / scope_excluded: copy verbatim do skeleton atual
   - match_tolerance_candles: 1

7. Adiciona campo de tracking de ratificação
   - meta.ratified: false   (Marcelo flipa para true após spot-check)
   - meta.ratification_notes: ""

8. screenshots[]: deixar vazio
   - Preenchido manualmente durante spot-check (URLs ou descrições)
   - Schema exige apenas screenshot_id em events; engine emite ""

9. Valida output contra schema (tools/golden_validator.py)
   - Se falhar, aborta com erro descritivo
   - Se passar, grava em --output

10. Imprime estatísticas
    - Total events por event_type
    - Total zones por zone_type
    - Sanity checks: nenhum candle_idx > len(df)-1, nenhum timestamp
      fora do range
```

### 5.3 Mapping rules: coluna df → event_type

Conferido contra `golden_schema.json:51-75` e código dos detectores.

| Coluna df | `event_type` emitido | Campos extras emitidos |
|-----------|----------------------|------------------------|
| `bos_internal_bullish` (Onda 5) | `bos_bullish_internal` | `level`: `df['internal_high_level'].ffill().iloc[t]` |
| `bos_internal_bearish` | `bos_bearish_internal` | `level`: `internal_low_level.ffill()` |
| `bos_swing_bullish` | `bos_bullish_swing` | `level`: `swing_high_level.ffill()` |
| `bos_swing_bearish` | `bos_bearish_swing` | `level`: `swing_low_level.ffill()` |
| `choch_internal_bullish` | `choch_bullish_internal` | `level`: `internal_high_level.ffill()` |
| `choch_internal_bearish` | `choch_bearish_internal` | idem |
| `choch_swing_bullish` | `choch_bullish_swing` | idem |
| `choch_swing_bearish` | `choch_bearish_swing` | idem |
| `ob_internal_bullish_created` (Onda 6) | `ob_bullish_internal_formed` | `ob_top`, `ob_bottom` — buscar no ledger por `(scope='internal', bias=BULLISH, t_creation=df['date'].iloc[t])` |
| `ob_internal_bearish_created` | `ob_bearish_internal_formed` | idem |
| `ob_swing_bullish_created` | `ob_bullish_swing_formed` | idem com `scope='swing'` |
| `ob_swing_bearish_created` | `ob_bearish_swing_formed` | idem |
| `ob_internal_bullish_mitigated` | `ob_bullish_internal_mitigated` | `ob_top`, `ob_bottom` do mesmo registro do ledger (lookup por `t_mitigation`) |
| `ob_internal_bearish_mitigated` | `ob_bearish_internal_mitigated` | idem |
| `ob_swing_bullish_mitigated` | `ob_bullish_swing_mitigated` | idem |
| `ob_swing_bearish_mitigated` | `ob_bearish_swing_mitigated` | idem |
| `fvg_bullish_created` (Onda 7) | `fvg_bullish_formed` | `fvg_top`, `fvg_bottom` — buscar no ledger FVG por `t_creation` |
| `fvg_bearish_created` | `fvg_bearish_formed` | idem |
| `fvg_bullish_mitigated` | `fvg_bullish_mitigated` | idem por `t_mitigation` |
| `fvg_bearish_mitigated` | `fvg_bearish_mitigated` | idem |
| `equal_high_alert` (Onda 3) | `eqh_alert` | `level`: `equal_high_level.iloc[t]` |
| `equal_low_alert` | `eql_alert` | `level`: `equal_low_level.iloc[t]` |

**Match perfeito 22 ↔ 22.** Schema canônico totalmente coberto.

### 5.4 O que NÃO entra no JSON pela engine

- `screenshots[]`: array vazio. Preenchido por Marcelo durante
  spot-check (URLs ou descrições por screenshot_id).

**Campos emitidos com placeholders:**

- `meta.ratified`: emitido como `false`. Marcelo flipa para `true`
  após spot-check completo, via commit dedicado.
- `meta.ratification_notes`: emitido como string vazia. Marcelo
  preenche durante/após spot-check (IDs flagados, decisões de
  interpretação, casos limite).

Ambos os campos são canônicos no schema (ver `tests/golden/schema/
golden_schema.json`, ratificados via micro-PR pré-Onda 9). Engine
emite valores iniciais conforme padrão "engine produz, humano
ratifica" (§7.4).

### 5.5 Decisão: script one-shot vs toolkit permanente

**Recomendação: toolkit permanente.**

Razões:

1. **Reprodutibilidade.** Bugs detectados no spot-check → fix na
   engine → re-rodar o script → diff entre JSONs antigos e novos.
   Ferramenta one-shot quebra esse loop.
2. **Atualização do golden** (Mapa §7.6 fluxo): a engine evolui
   com Ondas 9.5+. Cada onda nova pode adicionar event_types ou
   refinar mappings. Ferramenta permanente é o lugar canônico
   para essa evolução.
3. **CI auxiliar** (futuro): poderia rodar em CI sobre o CSV
   versionado e comparar JSON produzido com golden ratificado,
   acusando regressão automaticamente. Isso só é viável se a
   ferramenta vive no repo.

Custo de mantê-la: módulo de ~200 linhas em `smc_freqtrade/tools/`,
similar em peso ao `run_wave8_engine_on_golden.py` mergeado.

---

## Seção 6 — Testes de integração

### 6.1 Arquivos propostos

Três novos arquivos de teste, todos em `smc_freqtrade/tests/`:

1. **`test_integration_analyze_smoke.py`** — smoke E2E com df sintético
   pequeno (~60 candles), valida:
   - `analyze()` retorna `AnalyzeResult` corretamente formado.
   - `result.df` contém todas as colunas esperadas das Ondas 3-8.
   - `result.order_blocks_ledger` é DataFrame com schema correto
     (mesmo que vazio).
   - `result.fvg_ledger` idem.
   - `result.meta` contém as chaves canônicas.
   - `result.config_used` é o config passado (ou default).

2. **`test_integration_analyze_on_golden.py`** — roda no CSV golden
   (720 candles BTC-USDT-SWAP 4H). Dois modos:
   - **Quando `meta.ratified == true`:** itera `events[]` do JSON e
     valida que cada evento (timestamp, event_type) tem match
     correspondente no output da engine com tolerância ±1 candle.
     Pivot conferido via `candle_idx`.
   - **Quando `meta.ratified == false` (estado inicial):** apenas
     valida que `analyze()` roda sem crashar; produz df com schema
     esperado (todas as colunas das Ondas 3-8); ledgers têm
     dtypes corretos; nenhum NaN inesperado em colunas booleans.

3. **`test_integration_invariants.py`** — invariantes inter-modulares:

   **a.** Para todo OB no ledger:
   - `bar_time <= t_creation` (origem do OB precede o break).
   - `t_creation < t_mitigation` quando `state == 'mitigated'`.
   - `t_mitigation is pd.NaT` quando `state == 'active'`.

   **b.** Para todo FVG no ledger:
   - `bar_time < t_creation` (estritamente — D5 Mapa §7.6.3).
   - `t_creation < t_mitigation` quando `state == 'mitigated'`.

   **c.** Cobertura BOS prévio?
   - Não-invariante: OB pode ser criado por CHoCH inicial sem BOS
     prévio (`internal_trend_bias` inicial é `pd.NA`, primeiro evento
     vira BOS). Vide `structure.py:265-272`. Documentar e NÃO
     transformar em assertion.

   **d.** Sweep só sobre pivot existente?
   - Para todo candle com `sweep_*_wick == True`, o pivot referenciado
     por `sweep_*_level_idx` corresponde a candle com coluna
     `*_level != NaN` (equal ou internal). Asseverável diretamente.

   **e.** PD ratio consistente:
   - `pd_zone == 'premium'` ⇔ `pd_ratio > 0.5`.
   - `pd_zone == 'discount'` ⇔ `pd_ratio < 0.5`.
   - `pd_zone == 'equilibrium'` ⇔ `pd_ratio == 0.5`.
   - `pd_zone is pd.NA` ⇔ `pd_ratio is NaN`.

   **f.** Determinismo:
   - `analyze(df)` rodado N=2 vezes produz `AnalyzeResult` com `df`
     bit-idêntico (`pd.testing.assert_frame_equal`) e ledgers
     bit-idênticos.
   - Implementação: rodar duas vezes em sequência, comparar.

   **g.** Anti-mutação do input:

   - `analyze(df)` não muta `df` recebido. Asseverável via:

     ```python
     def test_analyze_does_not_mutate_input():
         df_before = make_synth_df()
         df_snapshot = df_before.copy()
         _ = analyze(df_before)
         pd.testing.assert_frame_equal(df_before, df_snapshot)
     ```

   - Cobre regressão futura onde algum detector esqueça a cópia
     interna. Vide §3.4 (estratégia anti-mutação).

### 6.2 Pendência de schema dos ledgers

Os ledgers de OB e FVG têm schemas distintos (conferido no código):

- **OB ledger:** 11 colunas — `ob_id, scope, bias, bar_high, bar_low,
  bar_time, t_creation, t_mitigation, t_invalidation, state,
  volumetric_intensity`.
- **FVG ledger:** 11 colunas — `fvg_id, bias, top, bottom, bar_time,
  t_creation, t_mitigation, t_invalidation, state, is_inverse,
  is_double`.

Os testes asseveram esses schemas explicitamente.

---

## Seção 7 — Riscos e decisões pendentes

### 7.1 Performance

**720 candles × 6 módulos sequenciais.**

- 5 dos 6 detectores são totalmente vetorizados em numpy/pandas
  (pivots, trailing, structure, order_blocks parsed_*, fvg).
- `order_blocks` itera por candles de trigger em Python (~dezenas
  de iterações sobre 720 candles); aceitável conforme `order_blocks.py:254`
  comment.
- `liquidity_sweep` itera por candle (loop principal `for t in range(n)`,
  `liquidity_sweep.py:333`); O(n × |pool|), pool com cleanup ativo.

**Estimativa empírica (a confirmar no PR):** pipeline completo sobre
720 candles deve rodar em < 1s. Sem otimização prévia.

**Decisão:** não otimizar nesta onda. Se PR de implementação medir
> 5s em 720 candles, abrir issue separado e investigar profiling.
Onda 10 (integração Freqtrade) pode rodar isso milhares de vezes em
backtest, então custo real só fica óbvio lá.

### 7.2 Memory footprint

- 720 candles × ~50 colunas (OHLC + date + 14 pivots + 4 trailing +
  10 structure + 8 OB + 4 FVG + 12 sweep) = ~36000 floats ≈ 300KB.
- 2 ledgers (OB típico < 50 entries, FVG < 100 entries) — ~30KB.

**Total < 500KB em pico.** Não há decisão a tomar aqui.

### 7.3 Compatibilidade com `populate_indicators` (Onda 10)

Esqueleto do Mapa §6 Onda 10:

```python
@informative('4h')
def populate_indicators_4h(self, dataframe, metadata):
    return analyze(dataframe, mode='swing_only')
```

**Conflito previsto:** o Mapa usa `analyze(dataframe, mode='swing_only')`,
mas a Onda 9 propõe `analyze(df, config: SMCConfig | None = None)`.
O parâmetro `mode` não existe na assinatura proposta.

**Análise:**

- `mode` no Mapa é shorthand documental, não API formal — escrito
  antes da decisão #7 (SMCConfig) ter sido fechada.
- Mapeamento real: `mode='swing_only'` ≈ "SMCConfig customizado
  desabilitando internal_*". Isso pode virar preset em Onda 10
  (`SMCConfig.swing_only()`).
- A `IStrategy` da Onda 10 vai precisar retornar `dataframe` — não
  `AnalyzeResult`. Adapter natural:

  ```python
  @informative('4h')
  def populate_indicators_4h(self, dataframe, metadata):
      result = analyze(dataframe, SMCConfig.swing_only())
      return result.df
  ```

  Custo: 1 linha de boilerplate por TF. Aceitável.

**Decisão:** a assinatura proposta (df + SMCConfig → AnalyzeResult)
não bloqueia Onda 10. Apenas força a IStrategy a fazer `.df` no
retorno. A documentação do `analyze()` deve incluir exemplo
explícito desse uso na docstring.

### 7.4 `meta.ratified` e validador

**Decisão fechada no review 2026-05-14:** `meta.ratified` e
`meta.ratification_notes` serão **adicionados ao schema canônico**
via micro-PR separado, mergeado **antes** da impl da Onda 9.

Justificativa: campos extras não-schema são pegadinha — futuro
contribuidor lê o schema e presume que `ratified` não existe. Patch
de schema é trivial (similar em peso ao patch documental PR #54).

**Estado pós-micro-PR:** schema canônico inclui:

```json
"meta": {
  "properties": {
    ...,
    "ratified": { "type": "boolean" },
    "ratification_notes": { "type": "string" }
  },
  "required": [ ..., "ratified" ]
}
```

Onda 9 emite `ratified: false` e `ratification_notes: ""` no JSON
gerado pela engine. Marcelo flipa `ratified: true` e preenche notas
durante spot-check, via commit dedicado.

**Pré-requisito desta onda:** micro-PR de schema deve estar mergeado
antes do PR de implementação da Onda 9.

### 7.5 Ambiguidade de `ob_top` / `ob_bottom` no evento mitigado

Schema canônico aceita `ob_top` e `ob_bottom` em eventos
`ob_*_mitigated`. Pergunta: que valores emitir nesses?

**Decisão proposta:** emitir os mesmos `bar_high` / `bar_low` do OB
original (consultado via ledger por scope+bias+t_mitigation). Razão:
o "OB sendo mitigado" tem mesma forma geométrica do "OB formado";
spot-check visual compara contra a mesma caixa retangular.

Alternativa rejeitada: emitir candle de mitigação (`high`, `low` do
candle que mitigou). Isso descreve onde o preço chegou, não a caixa
em si — informação útil mas redundante (já está em `timestamp_utc`
e o caller pode consultar `df` se quiser).

### 7.6 Eventos múltiplos no mesmo candle

Schema permite múltiplos eventos por candle (event é uma linha do
array `events[]` sem unique constraint em `candle_idx`).

**Caso: candle X tem `bos_internal_bullish == True` E
`ob_internal_bullish_created == True` simultaneamente.** Esperado e
comum (Pine cria OB no break — `order_blocks.py:_emit_create_events`).
Mapping emite 2 events com mesmo `timestamp_utc`, `candle_idx`,
diferentes `event_type`. Sem deduplicação.

### 7.7 Tolerância de teste vs leitura visual

`match_tolerance_candles: 1` no meta canônico (Mapa §7.4). Os testes
de integração precisam assever match ±1 candle, não candle exato.
Isso já está nos detectores das Ondas 5-8 (cada um documenta
lookahead-safe ± `swings_length` para pivots, etc.).

**Risco residual:** se o LuxAlgo gratuito do TradingView produzir
visualmente eventos sistematicamente off por mais de 1 candle vs
nossa engine, golden falha em massa. Decisão: confiar no spot-check
da Onda 7 (PR #49 reportou 9/9 match em FVG) e da Onda 8 (relatório
em `docs/RELATORIO_SPOT_CHECK_WAVE8.md`) — tolerância vigente
funciona.

### 7.8 Itens que NÃO emergiram como bloqueadores

Auditoria de divergências entre Mapa pós-#54 e código real:

- §1 (Mapa "16 eventos" → "22 tipos"): patch documental PR #54 já
  aplicou; código tem todas as 22 colunas para mapping.
- §7 (PD em `trailing.py`): conferido — `PD_ZONE_*` em
  `trailing.py:69-71`. Decisão 1 não bloqueia.
- §6 (nome `fvg.py`): conferido — `smc_engine/fvg.py` existe.
  Decisão 6 confirmada.
- Schema com 22 event_types: conferido em
  `golden_schema.json:52-75`. Match perfeito.

**Conclusão:** as 7 decisões aprovadas são tecnicamente viáveis no
código real. **Nenhum bloqueador identificado.** Conflict clause do
briefing (briefing §"Conflict clause") **não é acionada**.

---

## Seção 8 — Cronograma de implementação proposto

Sub-passos da Onda 9, em ordem topológica de dependência:

| # | Sub-passo | Critério verificável | Depende de |
|---|-----------|----------------------|------------|
| 1 | Criar `smc_engine/config.py` com `SMCConfig` + validações | `SMCConfig()` instanciável; `SMCConfig(pivot_swings_length=-1)` levanta `ValueError`; smoke test `test_smc_config.py` cobre cada validação | — |
| 2 | Criar `smc_engine/result.py` com `AnalyzeResult` | Dataclass frozen instanciável; tentar mutar campo levanta `FrozenInstanceError` | 1 |
| 3 | Criar `smc_engine/engine.py` com `analyze()` + `_validate_input()` | `analyze(df_minimal_synth)` retorna `AnalyzeResult` com df expandido; smoke test E2E | 1, 2 |
| 4 | Atualizar `smc_engine/__init__.py` | `from smc_engine import analyze, SMCConfig, AnalyzeResult` funciona; aviso "Tentativa de uso ... ImportError" removido da docstring | 3 |
| 5 | Criar `smc_freqtrade/tools/generate_golden_engine_output.py` | Script roda contra CSV golden, produz JSON validável pelo `golden_validator.py` | 3, 4 |
| 6 | Criar `tests/test_integration_analyze_smoke.py` | `pytest tests/test_integration_analyze_smoke.py` passa | 3, 4 |
| 7 | Criar `tests/test_integration_analyze_on_golden.py` | Passa em modo "ratified=false" (apenas valida não-crash + schema do df) | 3, 4 |
| 8 | Criar `tests/test_integration_invariants.py` | Todos os invariantes a-f de §6.1 passam | 3 |
| 9 | Bump VERSION para 0.9.0 | `cat smc_freqtrade/VERSION` retorna `0.9.0`; commit dedicado conforme §1.3 AGENTS.md | 1-8 todos verdes |
| 10 | Atualizar docstring de `__init__.py` (limitações Onda 9.5, etc.) | grep "Onda 9.5" retorna match | 4 |
| 11 | Spot-check do JSON gerado (Marcelo) | Marcelo flipa `meta.ratified` → `true` em PR de "feat(golden): ratificar Onda 9" | 5 |
| 12 | Re-rodar `test_integration_analyze_on_golden.py` em modo "ratified=true" | Match ±1 candle de todos os eventos | 11 |

**Sub-passos paralelizáveis:** 6, 7, 8 podem rodar concorrentemente
após 3 estar verde. 1 e 2 são independentes.

**Caminho crítico:** 1 → 3 → 4 → 5 → 11 (entrega real depende de
ratificação humana).

**Estimativa grosseira (a refinar no briefing de implementação):**

- 1: ~1 sessão (config + validações cuidadosas).
- 2: < 0.5 sessão (dataclass simples).
- 3: ~1 sessão (orquestração + validação).
- 4-5: ~1 sessão.
- 6-8: ~1-2 sessões cada (cobertura ampla).
- 9-10: < 0.5 sessão (bump + docstring).
- 11: depende de disponibilidade do Marcelo.

**Total Code-side:** 5-7 sessões antes da ratificação. PR único ou
PRs incrementais (passos 1-2-3 em PR "feat: engine analyze base";
passos 5-6-7-8 em PR "feat: golden generator + integration tests")
— a decidir no briefing de implementação.

---

## Apêndice A — Referências canônicas

- `docs/MAPA_LUXALGO_CAMADA_1_v1.1.md` §6 Onda 9, §7, §11.
- `docs/MAPA_LUXALGO_CAMADA_1_v1.1.md` §5 (Conflitos A/B/C).
- `smc_freqtrade/tests/golden/schema/golden_schema.json` (22 eventos).
- `smc_freqtrade/tests/golden/README.md` (fluxo de produção).
- `smc_freqtrade/smc_engine/__init__.py` (API atual a estender).
- `smc_freqtrade/smc_engine/{pivots,trailing,structure,order_blocks,fvg,liquidity_sweep}.py`
  (assinaturas verbatim).
- `AGENTS.md` §1.4 (docstring standard a aplicar nos novos módulos).

## Apêndice B — Checklist de aprovação

Antes de partir para o briefing de implementação, Marcelo confirma:

**Decisões fechadas no review 2026-05-14 (PR #55 review):**

- [x] §1.2 — Threshold mínimo: `len(df) >= max(pivot_swings_length, ob_atr_length) + 3`, levanta ValueError.
- [x] §3.4 — Sem `df.copy()` outer; teste de invariante (§6.1 item g) cobre.
- [x] §5.2 — PD zones com bounds candle-a-candle (min/max ao longo da sequência).
- [x] **Pré-requisito:** micro-PR de schema (adiciona `meta.ratified` e `meta.ratification_notes` ao `golden_schema.json`) será mergeado **antes** da impl da Onda 9.

- [ ] §1 — Assinatura de `analyze(df, config)` está OK.
- [ ] §1 — Localização `result.py` está OK (vs `types.py`).
- [ ] §1 — `frozen=True` para `AnalyzeResult` está OK.
- [ ] §2 — Campos planos em `SMCConfig` (vs sub-dataclasses) está OK.
- [ ] §2 — Lista de 14 parâmetros e seus defaults está completa.
- [ ] §2 — Presets adiados para Onda 10 está OK.
- [ ] §3 — Ordem de orquestração e estratégia anti-mutação está OK.
- [ ] §4 — Aviso "ImportError até Onda 9" a remover está OK.
- [ ] §5 — Script permanente (não one-shot) está OK.
- [ ] §5 — Mapping 22 colunas → 22 event_types está completo.
- [ ] §6 — 3 arquivos de teste + invariantes a-f estão OK.
- [ ] §7 — `meta.ratified` como campo extra (não-schema) está OK.
- [ ] §7 — `ob_top/bottom` em eventos mitigated reusa caixa original.
- [ ] §8 — Sub-passos e dependências estão OK; estimativa
      direcional aceita.

**Após aprovação:** próximo PR é "briefing de implementação Onda 9"
(briefing em markdown + Code executa).

---

**Fim do plano canônico Onda 9.**
