# Dívida de calibração — A3 (Wave 9.5a → resolver na Wave 10)

> **REDIRECIONAMENTO (Wave 9.5c):** este doc foi escrito na 9.5a assumindo
> "9.5c = backtest". A sequência real (ver §12 de `CONCEITOS_LUXALGO_HOOKS.md`)
> coloca a calibração de parâmetros (`pending_timeout`, tolerância de
> `zone_crossed`, janela ChoCH↔rejeição) contra dado amplo na **Wave 10**
> (backtest estruturado de 2 anos). A 9.5c **não calibra nada** — só codifica
> assinaturas. O próprio diagnóstico abaixo admite que 1 janela de 4 meses é
> overfit; a varredura de parâmetros é por assinatura isolada na Wave 10.
> Conteúdo de diagnóstico preservado abaixo como ponto de partida.

> Registro para `docs/` ou changelog interno. Medições obtidas rodando
> o pipeline MTF real (`analyze` 4h/1h/15m → `align_informative` →
> `compute_setup_state`) sobre o golden **BTC-USDT-SWAP jan–abr 2026**
> (11.520 candles 15m). Não é bug — é calibração pendente, deliberadamente
> adiada para a **Wave 10** (backtest) por falta de amostra na 9.5a.

## Fato observado

A3 (Triple Confirmation), com a config default da 9.5a, produz no golden:

| setup_state | candles |
|---|---|
| ARMED | 713 |
| PENDING_CONFIRMATION | 47 (= 4 episódios distintos) |
| INVALIDATED | 484 (escaped 473, timeout 8, zone_crossed 2, mitigated 1) |
| CONFIRMED | 0 |

A fiação está viva (ARMED/PENDING surgem no dado real; colunas `_4h`/
`_1h`/zona promovida atravessam o merge). O caminho CONFIRMED é provado
pela trajetória sintética determinística. O zero em dado real é
seletividade + calibração, não defeito.

## Diagnóstico (medido, não inferido)

Os 4 episódios PENDING terminam assim:
- timeout: 2 (duração chega a 16 candles, o limite atual)
- zone_crossed: 2 (um `close` abaixo da zona encerra o setup)

Sweep recente NÃO é o gargalo: presente em 47/47 candles PENDING.
O gargalo é que, nos ~12 candles médios em que o preço fica na zona,
não aparece a tempo a coincidência ChoCH 15m + vela de rejeição na
direção do trade. Co-ocorrência ChoCH&rejeição no mesmo candle = 15 em
11.520; nenhuma caiu dentro de uma janela PENDING.

Teste de sensibilidade (afrouxar ChoCH↔rejeição para janela rolling):
- mesmo-candle (atual): 0 CONFIRMED
- K=4 candles: ainda 0 CONFIRMED (o teto bruto sobe para 222
  co-ocorrências, mas nenhuma dentro de PENDING)

Conclusão: afrouxar só a simultaneidade não basta. Os limitantes reais
são a janela de timeout e a tolerância de `zone_crossed`.

## Itens a calibrar na 9.5c (contra backtest mais amplo)

1. `pending_timeout_candles` (default 16). Episódios morrem no limite —
   testar 24–32, dando mais espaço para o ChoCH formar.
2. Tolerância de `zone_crossed`. Hoje `close < setup_zone_low` (long) é
   estrito; 2 episódios morreram por um único fechamento que pode ter
   sido o próprio wick de absorção/sweep. Avaliar
   `close < setup_zone_low * (1 - tol)`.
3. Janela ChoCH↔rejeição (hoje mesmo-candle). Reavaliar K rolling junto
   dos itens 1–2, não isoladamente.

Princípio: calibrar os 3 contra 1 dataset de 4 meses com 4 episódios é
overfit. A 9.5c deve usar janela mais ampla (estender via
`tests/golden/tools/ohlcv_fetcher.py`) e/ou múltiplos ativos antes de
cravar números.

## O que NÃO mudar

A spec da 9.5a está fiel ao briefing e auditada (232 testes verdes, sem
lookahead, ledgers/colunas íntegros). Nenhuma alteração de código na
9.5a por conta desta dívida — ela é input da 9.5c.
