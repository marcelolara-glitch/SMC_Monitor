# Plano — Passo 9 (v0.1.2)

## 1. Arquivos alterados e mudanças

| Arquivo | Mudanças |
|---|---|
| `config.py` | Remover `FVG_MIN_SIZE`, adicionar `HEARTBEAT_INTERVAL_SECONDS = 1800`, bump header + VERSION `0.1.0 → 0.1.2` |
| `state.py` | Adicionar DDL + `init_db` toca na nova tabela, `load_event_tracking()`, `save_event_tracking()`, bump header `0.1.0 → 0.1.2` |
| `signals.py` | `evaluate()` retorna dict expandido; `format_signal()` reescrita; adicionar `evaluate_events()`, `format_event()`, `load_event_tracking()`, `persist_event_tracking()`, dois dicts de módulo (`_event_tracking`, `_prev_trend_4h`); bump header `0.1.0 → 0.1.2` |
| `main.py` | `_heartbeat_loop` usa `config.HEARTBEAT_INTERVAL_SECONDS`; `main()` chama `signals.load_event_tracking()` após `state.init_db()`; `on_candle` processa eventos; flush periódico chama `signals.persist_event_tracking()`; bump header + VERSION `0.1.1 → 0.1.2` |

Arquivos **não alterados**: `telegram.py`, `smc_engine.py`, `ws_feed.py`, `lib_version_check.py`.

---

## 2. Schema final da tabela `event_tracking`

```sql
CREATE TABLE IF NOT EXISTS event_tracking (
    token         TEXT    NOT NULL,
    timeframe     TEXT    NOT NULL,
    event_type    TEXT    NOT NULL,
    last_event_ts INTEGER NOT NULL,
    updated_at    INTEGER NOT NULL,
    PRIMARY KEY (token, timeframe, event_type)
)
```

---

## 3. Assinaturas completas das funções novas

### `state.py`

```python
def load_event_tracking() -> dict:
    """
    OBJETIVO: restaurar cache de rastreamento de eventos do SQLite na inicialização.
    FONTE DE DADOS: tabela event_tracking no banco SQLite (config.DB_PATH).
    LIMITAÇÕES CONHECIDAS: falhas de I/O são silenciosas — retorna dict vazio.
    NÃO FAZER: sem cálculo SMC; sem acesso direto ao engine.
    Retorna dict no formato {(token, timeframe, event_type): last_event_ts}.
    """

def save_event_tracking(cache: dict) -> None:
    """
    OBJETIVO: persistir cache de rastreamento de eventos no SQLite.
    FONTE DE DADOS: dict {(token, timeframe, event_type): last_event_ts}.
    LIMITAÇÕES CONHECIDAS: falhas de I/O são silenciosas — warning no log, sem raise.
    NÃO FAZER: sem cálculo SMC; sem acesso direto ao engine.
    """
```

### `signals.py`

```python
def evaluate_events(token: str, engine: SMCEngine) -> list[dict]:
    """
    OBJETIVO: detectar eventos novos (BOS/ChoCH, sweep, trend change 4H)
              comparando estado atual do engine contra cache _event_tracking.
    FONTE DE DADOS: engine.get_state() para cada TF; _event_tracking para
                    último ts notificado por chave; _prev_trend_4h para
                    direção de trend anterior no 4H.
    LIMITAÇÕES CONHECIDAS: trend_change só considera transições causadas
                           por BOS/ChoCH confirmado (bootstrap ignorado);
                           dedup é por event_ts, não por hash do dict;
                           na primeira chamada por token, caches são
                           inicializados sem notificação.
    NÃO FAZER: não enviar Telegram aqui; não persistir cache aqui.
    Retorna lista de dicts: {"event_type": str, "timeframe": str, "data": dict}.
    """

def format_event(event: dict, token: str) -> str:
    """Formata dict de evento para mensagem Markdown pronta para Telegram."""

def load_event_tracking() -> None:
    """Popula _event_tracking a partir de state.load_event_tracking()."""

def persist_event_tracking() -> None:
    """Persiste _event_tracking via state.save_event_tracking()."""
```

---

## 4. Samples das mensagens

### BOS/ChoCH novo (4H)
```
🔔 BOS 4H — BTC-USDT-SWAP
Direção: bull
Preço rompido: 66800.0000
Timestamp: 2026-04-17 12:00 UTC
```

### ChoCH 1H
```
🔔 ChoCH 1H — BTC-USDT-SWAP
Direção: bear
Preço rompido: 67010.0000
Timestamp: 2026-04-17 14:00 UTC
```

### Sweep novo (1H)
```
💧 Sweep 1H — BTC-USDT-SWAP
Direção: low
Preço varrido: 66950.0000
Close do candle: 67050.0000
Timestamp: 2026-04-17 15:00 UTC
```

### Trend change 4H
```
🔄 Trend 4H mudou — BTC-USDT-SWAP
bearish → bullish
Causado por: BOS bull @ 66800.0000
Timestamp: 2026-04-17 12:00 UTC
```

### `format_signal` enriquecido (todos os campos presentes)
```
🟢 *LONG — BTC-USDT-SWAP*
Score: *5/6*  | Preço atual: `67234.5000`

━━ Trend Multi-Timeframe ━━
4H: bullish  (última BOS: bull @ 66800.0000 em 2026-04-17 12:00 UTC)
1H: bullish  (última ChoCH: bull @ 67010.0000 em 2026-04-17 14:00 UTC)
15m: bullish (última BOS: bull @ 67180.0000 em 2026-04-17 16:45 UTC)

━━ Zona de Entrada ━━
Entrada: `67050.0000` – `67180.0000`
SL: `66983.9573`
TP1: `67420.0000`

━━ Indicadores 1H Detalhados ━━
OB referência (bull):
  range: `67050.0000` – `67180.0000`
  volume: `12340.5000`
  displacement: `0.42%`
FVG adjacente (bull):
  range: `67150.0000` – `67220.0000`
  midpoint: `67185.0000`
  status: active
Sweep recente (1H):
  direção: low
  preço varrido: `66950.0000`
  idade: 3 candles
Premium/Discount (1H):
  posição: 0.38 (discount)
  swing_high: `67500.0000`
  swing_low: `66500.0000`
  equilibrium: `67000.0000`

━━ Critérios atingidos ━━
  ✅ OB ativo no 1H
  ✅ FVG adjacente ao OB (1H)
  ✅ Liquidity Sweep recente
  ✅ Zona Premium/Discount correta
  ❌ BOS/ChoCH confirmado no 15m
  ✅ Tendência 4H alinhada
```

### `format_signal` com campos ausentes (exercita travessões)
```
🔴 *SHORT — BTC-USDT-SWAP*
Score: *4/6*  | Preço atual: `67234.5000`

━━ Trend Multi-Timeframe ━━
4H: bearish  (última BOS: bear @ 67500.0000 em 2026-04-17 10:00 UTC)
1H: neutral  (—)
15m: neutral (—)

━━ Zona de Entrada ━━
Entrada: `67400.0000` – `67500.0000`
SL: `67567.5000`
TP1: —

━━ Indicadores 1H Detalhados ━━
OB referência: —
FVG adjacente: —
Sweep recente: —
Premium/Discount (1H):
  posição: 0.72 (premium)
  swing_high: `67500.0000`
  swing_low: `66500.0000`
  equilibrium: `67000.0000`

━━ Critérios atingidos ━━
  ❌ OB ativo no 1H
  ❌ FVG adjacente ao OB (1H)
  ✅ Liquidity Sweep recente
  ✅ Zona Premium/Discount correta
  ✅ BOS/ChoCH confirmado no 15m
  ✅ Tendência 4H alinhada
```

---

## 5. Casos de teste mental — deduplicação

### BOS/ChoCH

**Setup:** `_event_tracking = {("BTC-USDT-SWAP", "4H", "bos_choch"): 1700000000000}`

**Caso A — mesmo ts:** `state_4h["last_bos"]["ts"] == 1700000000000`
- `cached_ts = 1700000000000`
- `last_bos["ts"] != cached_ts` → **FALSE**
- Resultado: **nenhum evento emitido** ✓

**Caso B — ts diferente:** `state_4h["last_bos"]["ts"] == 1700001000000`
- `cached_ts = 1700000000000`
- `last_bos["ts"] != cached_ts` → **TRUE**
- Cache atualizado: `_event_tracking[...] = 1700001000000`
- Resultado: **evento bos_choch emitido** ✓

### Trend change

**Caso C — dois BOS bull consecutivos (mesma direção):**
- `_event_tracking[(token, "4H", "trend_change")] = T1`, `_prev_trend_4h[token] = "bullish"`
- Novo ciclo: `last_bos["ts"] = T2 > T1`, `state["trend"] = "bullish"`
- `T2 != T1` → TRUE (novo BOS detectado)
- `"bullish" != _prev_trend_4h["bullish"]` → **FALSE**
- Resultado: cache atualizado para T2, **nenhuma notificação** ✓ (direção não mudou)

**Caso D — bull → bear:**
- `_prev_trend_4h[token] = "bullish"`, novo BOS bear com ts T3
- `T3 != cached_ts` → TRUE; `"bearish" != "bullish"` → TRUE
- Resultado: cache atualizado, `_prev_trend_4h[token] = "bearish"`, **notificação emitida** ✓

**Caso E — primeiro boot (cache vazio):**
- `_event_tracking.get(key) = None`, token não em `_prev_trend_4h`
- Lógica de inicialização: priming silencioso — caches populados com ts/trend atuais
- Resultado: **sem notificação** ✓

**Caso F — bootstrap (neutral → bullish sem BOS novo):**
- `state_4h["last_bos"]` permanece com ts anterior (nenhum BOS novo detectado)
- `last_bos["ts"] == cached_ts` → **FALSE** (sem novo BOS)
- Resultado: **nenhuma notificação** ✓

---

## 6. FVG_MIN_SIZE — confirmação de segurança

Grep completo de `FVG_MIN_SIZE` no repositório:

```
config.py:40      FVG_MIN_SIZE = 0.001   ← definição (a ser removida)
smc_engine.py:280 # NÃO FAZER: não aplicar filtro FVG_MIN_SIZE...  ← comentário apenas
```

Nenhum outro módulo importa ou referencia `FVG_MIN_SIZE` em código executável.
Remoção da linha `config.py:40` é **segura**. O comentário em `smc_engine.py:280` permanece como documentação de decisão de design.

---

## Notas de implementação adicionais

### Dicts de módulo em `signals.py`

```python
# (token, timeframe, event_type) → último ts notificado
_event_tracking: dict[tuple[str, str, str], int] = {}

# token → última direção de trend 4H notificada (para detect trend_change)
_prev_trend_4h: dict[str, str] = {}
```

`_prev_trend_4h` não é persistido no DB — LIMITAÇÃO CONHECIDA documentada na docstring de `evaluate_events`. Na primeira chamada por token, ambos os caches são inicializados silenciosamente sem notificação.

### Ordem de boot em `main.py`

```
_setup_logging()
→ _get_lib_version()
→ _smoke_test_library()
→ state.init_db()          ← cria tabela event_tracking se não existe
→ signals.load_event_tracking()   ← NOVO: popula _event_tracking do DB
→ engine = SMCEngine()
→ _restore_engine_state()
→ threads (heartbeat, version-check)
→ ws_feed.start(on_candle)
```

### Campos novos no dict de retorno de `evaluate()`

```python
return {
    # campos existentes
    "token":        token,
    "direction":    direction,
    "score":        score,
    "criteria":     criteria,
    "entry_zone":   entry_zone,
    "sl_price":     sl_price,
    "tp1":          tp1,
    "timestamp":    now_ms,
    # NOVOS
    "ref_ob":       ref_ob,           # dict OB ou None
    "ref_fvg":      matched_fvg,      # dict FVG que passou no overlap, ou None
    "ref_sweep":    ref_sweep,        # dict sweep ou None
    "ref_sweep_tf": ref_sweep_tf,     # "1H" | "15m" | None
    "trend_states": {
        "4H":  {"trend": ..., "last_bos": ...},
        "1H":  {"trend": ..., "last_bos": ...},
        "15m": {"trend": ..., "last_bos": ...},
    },
    "pd_details": {
        "label":       ...,   # "premium" | "discount" | "equilibrium"
        "position":    ...,   # float 0.0–1.0
        "swing_high":  ...,
        "swing_low":   ...,
        "equilibrium": ...,
    },
    "current_price": ...,     # último close do buffer 15m
}
```
