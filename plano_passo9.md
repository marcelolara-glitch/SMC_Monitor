# Plano de Implementação — Passo 9 (v0.1.2)

## Sumário das mudanças

| # | Mudança | Módulos afetados |
|---|---------|-----------------|
| 1 | Heartbeat 30 min parametrizado | config.py, main.py |
| 2 | Mensagem de sinal enriquecida | signals.py |
| 3 | Notificações por evento relevante | state.py, signals.py, main.py |
| 4 | Remoção de FVG_MIN_SIZE morto | config.py |
| 5 | Bump de versão 0.1.1 → 0.1.2 | config.py, main.py, signals.py, state.py |

---

## Mudança 1 — Heartbeat de 30 minutos parametrizado

- `config.py`: adicionar `HEARTBEAT_INTERVAL_SECONDS = 1800`
- `main.py`: substituir `time.sleep(3600)` por `time.sleep(config.HEARTBEAT_INTERVAL_SECONDS)`

---

## Mudança 2 — Mensagem de sinal enriquecida

### Novos campos no dict retornado por `evaluate()`

```python
{
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

### `format_signal()` atualizado

Seções: Trend MTF, Zona de Entrada, Indicadores 1H Detalhados, Critérios atingidos.
Campos ausentes mostram `—`. Timestamps em `YYYY-MM-DD HH:MM UTC`.
Critérios: todos 6 com ✅/❌ (não só os atendidos).

---

## Mudança 3 — Notificações por evento relevante

### Eventos monitorados

1. `bos_choch` — novo BOS/ChoCH em qualquer TF (4H, 1H, 15m)
2. `sweep` — novo sweep em qualquer TF
3. `trend_change` — mudança de trend no 4H causada por BOS confirmado

### Cache unificado `_event_tracking`

```python
_event_tracking: dict[tuple[str, str, str], dict] = {}
# key: (token, timeframe, event_type)
# value: {"ts": int, "value": str | None}
```

- `bos_choch` e `sweep`: `{"ts": event_ts, "value": None}`
- `trend_change`: `{"ts": ts_do_bos, "value": "bullish"|"bearish"|"neutral"}`

**Um único dict** — evita assimetrias de ciclo de vida entre event_types.

### Regras de deduplicação

**Regra A — Independência por event_type:** cada `event_type` tem dedup independente.
Um ciclo pode emitir múltiplos eventos de tipos diferentes sem bloqueio entre eles.

**Regra B — Priming silencioso:** na primeira observação de uma chave
`(token, tf, event_type)` (cache is None), inicializar silenciosamente sem emitir
notificação. Aplica-se a TODOS os event_types.

**Regra C — Dedup por ts:**
- `bos_choch` e `sweep`: comparação `event["ts"] != cached["ts"]`
- `trend_change`: `(last_bos["ts"] != cached["ts"]) AND (trend_atual != cached["value"])`

**Regra D — Independência do sinal:** eventos e sinais são canais separados;
emissão de um não suprime o outro.

### Tabela SQLite `event_tracking`

```sql
CREATE TABLE IF NOT EXISTS event_tracking (
    token         TEXT    NOT NULL,
    timeframe     TEXT    NOT NULL,
    event_type    TEXT    NOT NULL,
    last_event_ts INTEGER NOT NULL,
    last_value    TEXT,
    updated_at    INTEGER NOT NULL,
    PRIMARY KEY (token, timeframe, event_type)
)
```

`last_value` é NULL para `bos_choch` e `sweep`; para `trend_change` guarda a
direção anterior.

### Novas funções em `state.py`

- `load_event_tracking()` → restaura cache do SQLite; retorna `{}` em falha silenciosa
- `save_event_tracking(cache)` → persiste cache via INSERT OR REPLACE; falha silenciosa

### Novas funções em `signals.py`

- `evaluate_events(token, engine)` → detecta eventos novos, retorna lista de dicts
- `format_event(event, token)` → formata mensagem Markdown para Telegram
- `load_event_tracking()` → popula `_event_tracking` via `state.load_event_tracking()`
- `persist_event_tracking()` → persiste via `state.save_event_tracking()`

### Integração no `main.py`

Boot: `state.init_db()` → `signals.load_event_tracking()` → engine → ...

`on_candle`: após `engine.on_candle`, avaliar eventos antes do sinal:

```python
events = signals.evaluate_events(token, engine)
for event in events:
    telegram.send_signal(signals.format_event(event, token))
signal = signals.evaluate(token, engine)
if signal is not None:
    telegram.send_signal(signals.format_signal(signal))
```

Flush periódico (a cada 100 candles): adicionar `signals.persist_event_tracking()`.

---

## Mudança 4 — Remoção de FVG_MIN_SIZE

`grep -rn FVG_MIN_SIZE` confirma:
- `config.py:40` — definição (a remover)
- `smc_engine.py:280` — comentário apenas (manter)

Remoção segura.

---

## Mudança 5 — Bump de versão

| Módulo | De | Para |
|--------|-----|------|
| `config.py` | 0.1.0 | 0.1.2 |
| `main.py` | 0.1.1 | 0.1.2 |
| `signals.py` | 0.1.0 | 0.1.2 |
| `state.py` | 0.1.0 | 0.1.2 |
| `telegram.py` | intocado | 0.1.1 (preservar) |
| `smc_engine.py` | intocado | 0.1.1 (preservar) |

---

## Casos de teste mental — deduplicação

### Caso A — BOS/ChoCH com mesmo ts (nenhum evento)
`last_bos["ts"] == cached["ts"]` → FALSE → nenhum evento ✓

### Caso B — BOS novo com ts diferente
`last_bos["ts"] != cached["ts"]` → TRUE → evento `bos_choch` emitido ✓

### Caso C — Dois BOS bull consecutivos (mesma direção)
`bos_choch`: T2 != T1 → evento emitido ✓
`trend_change`: T2 != T1 mas `"bullish" == "bullish"` → sem notificação, cache sincroniza ts ✓

### Caso D — bull → bear (reversão de trend)
`bos_choch`: T3 != T1 → evento emitido ✓
`trend_change`: T3 != T1 e `"bearish" != "bullish"` → evento emitido ✓
Total: 2 notificações ✓

### Caso E — Primeiro boot (cache vazio)
Priming silencioso para todas as chaves → nenhuma notificação ✓

### Caso F — Bootstrap (neutral → bullish sem BOS novo)
`last_bos["ts"] == cached["ts"]` → condição FALSE → sem notificação ✓

### Caso G — Restart no meio de reversão (CRÍTICO)
Cache persistido: `{"ts": T1, "value": "bullish"}`. Após restart, BOS bear com ts=T3.
`load_event_tracking()` restaura `{"ts": T1, "value": "bullish"}`.
Priming NÃO dispara (cache not None).
T3 != T1 E "bearish" != "bullish" → evento `trend_change` emitido ✓
A coluna `last_value` garante que este evento raro não seja perdido após restart.
