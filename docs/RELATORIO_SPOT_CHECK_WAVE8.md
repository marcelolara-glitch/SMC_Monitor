# Relatório — Spot-check Onda 8 — Liquidity Sweep

**Data:** 2026-05-14
**Engine VERSION:** smc_freqtrade 0.7.0 (Onda 8 mergeada via PR #51,
engine run via PR #52)
**Dataset:** golden CSV BTC-USDT-SWAP 4H, 2026-01-01 → 2026-04-30,
720 candles, hash `1a3f746cfe6095ad544c46c66e1500306627ea5224cdc3708ef994af2b3ef3fa`
**Ratificador:** Marcelo (engine output + screenshots TradingView +
spot-check assistido por LLM).
**Ledger:** `smc_freqtrade/tests/golden/sweeps_ledger_v1.csv`

## 1. Metodologia

Spot-check híbrido em três rounds, cada round corrigindo um problema
de setup do round anterior:

| Round | Config TV | Indicador no chart | exact | partial | not_found | cannot_verify | Taxa de match |
|-------|-----------|--------------------|-------|---------|-----------|---------------|---------------|
| 1 | `Only Wicks` (errado) | TradingView genérico | 27 | 12 | 44 | 22 | 47.0% |
| 2 | `Wicks + Outbreaks & Retest` | Não-OKX, com SMC principal interferindo | 27 | 33 | 39 | 6 | 60.6% |
| 3 | `Wicks + Outbreaks & Retest` | BTCUSDT 4H OKX, indicador isolado | **58** | **28** | **18** | **1** | **82.7%** |

Setup canônico (round 3):
- TradingView: BTCUSDT · 4h · OKX (perpetual swap)
- Indicador: `Liquidity Sweeps [LuxAlgo]` (gratuito, **separado**
  do SMC principal)
- Parâmetros: `Swings=5`, `Options='Wicks + Outbreaks & Retest'`,
  `Extend=true`, `Max bars=300`
- Bull cores: verde (sólido + extensão xadrez), Bear cores:
  vermelho (sólido + extensão xadrez)
- 8 capturas em janelas de ~15 dias cobrindo 2026-01-01 → 2026-04-30

Critérios de classificação (round 3):
- `exact_match`: box/linha do indicador no mesmo candle e no mesmo
  preço (±0.1%)
- `partial_match`: objeto Pine no mesmo nível/região, mas com
  cor/oposição divergente, extensão de box anterior, ou candle/preço
  ambíguo
- `not_found`: engine emitiu sweep, sem objeto Pine correspondente
- `cannot_verify`: screenshot não cobre, zoom insuficiente, ou
  encoberto por UI

## 2. Distribuição por tipo (round 3)

| Tipo | exact | partial | not_found | cannot_verify | Total |
|------|-------|---------|-----------|---------------|-------|
| sweep_bullish_wick | 15 | 6 | 5 | 1 | 27 |
| sweep_bearish_wick | 19 | 5 | 3 | 0 | 27 |
| sweep_bullish_retest | 16 | 10 | 5 | 0 | 31 |
| sweep_bearish_retest | 8 | 7 | 5 | 0 | 20 |
| **Total** | **58** | **28** | **18** | **1** | **105** |

Taxa de match por tipo: bullish_wick 78%, bearish_wick 89%,
bullish_retest 84%, bearish_retest 75%. Todas as categorias acima
de 70%; bearish_wick é a mais limpa.

## 3. Padrões de divergência identificados

Os 46 eventos ambíguos restantes (18 not_found + 28 partial_match)
seguem três padrões consistentes:

**3.1 Eventos dentro de zona Pine estendida sem nova borda visível
no candle.**
O `extend=true` do Pine mantém uma sweep area ativa após o evento
inicial. Novos pivots no mesmo nível, durante essa janela de
extensão, não geram nova borda visual mas são emitidos pela engine
como novos sweeps. Comportamento **diferente, não errado** — a
engine rastreia cada pivot independentemente via `next_id`
auto-incremento (decisão §7 do briefing canônico da Onda 8 — O2).

Exemplos: sweep_idx 65, 115, 117, 118, 136 (todos `partial_match`
com observação "dentro de zona estendida").

**3.2 Retests onde o Pine mostra cor oposta no mesmo nível.**
O mesmo pivot pode disparar primeiro um wick sweep (pre-break) e
depois — se houver close-break subsequente — um outbreak & retest
(pós-break). Mas o Pine remove o pivot do pool após o primeiro
evento (regra `tak=True → cleanup`). A engine pode emitir ambos
sobre pivots adjacentes com mesmo nível, fiel ao briefing.

Exemplos: sweep_idx 162, 163, 301, 542, 573, 592, 599, 611
(todos `partial_match` com observação "cor/oposicao divergente").

**3.3 Cluster Jan 20–28 e Feb 23–28 com sobreposição visual alta.**
Períodos de máxima volatilidade no dataset (BTC caindo de ~95k pra
~75k) criam densidade alta de pivots e sweeps. O Pine sobrepõe
boxes, dificultando leitura visual mas sem afetar a validade lógica
dos eventos. Densidade é característica do mercado nesses períodos,
não falha de detector.

Exemplos: sweep_idx 124, 141, 146 (cluster Jan), 320, 352 (cluster
Feb).

## 4. Observação sobre "varridas finas"

Cinco `not_found` em `sweep_bullish_wick` (sweep_idx 124, 141, 146,
297, 322) correspondem a casos onde o wick fura o pivot por valor
pequeno em termos absolutos ($46 a $516) durante candles de alta
volatilidade ($1k+ de range). A regra Pine `low < level AND close >
level` aceita qualquer perfuração, independentemente da magnitude.

Foi avaliada a hipótese de bug, mas o Pine **também** emite sweep
nesses casos no source. A discrepância visual deve-se a sobreposição
de boxes/zonas estendidas (padrão 3.1), não a falha lógica.

Possível extensão futura (sub-onda 8.3): parâmetro
`sweep_atr_threshold` filtrando wicks proporcionalmente menores que
X% do ATR. Hook já reservado na assinatura conforme briefing canônico
da Onda 8.

## 5. Conclusão

**Validação aprovada.** Engine `detect_liquidity_sweeps` mostra
fidelidade alta ao Pine `Liquidity Sweeps [LuxAlgo]` no spot-check
híbrido (82.7% de taxa de match, com 100% das categorias acima de
70%). Os ambíguos restantes têm explicações estruturais documentadas
(extensão de zona, sobreposição, identidade de pivots adjacentes) e
não apontam para bug.

Onda 8 está apta a:
- Bump de VERSION 0.7.0 → 0.8.0 (este PR)
- Consumo a jusante por state machine (Onda 9.5) e estratégia
  Freqtrade (Onda 10+)

Próximos passos não relacionados a este PR:
- Sub-ondas 8.1–8.5 conforme hooks reservados na assinatura
- Onda 9 (verificação cruzada Freqtrade)
