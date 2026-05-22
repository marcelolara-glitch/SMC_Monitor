# Wave 8.2 — Ledger EQH/EQL (Pine SMC Concepts canônico)

## Estado: VAZIO — escalação Briefing Wave 8.2 §7

Após reescrita canônica fiel ao Pine LuxAlgo `SMC Concepts`
(`tools/pynecore-validation/luxalgo_smc_compute_only.py` linhas
89-90, 124, 155-195), a engine produziu **0 alerts** EQH/EQL sobre
os 720 candles 4H do golden BTC-USDT-SWAP.

## Diagnóstico (briefing §7 — "parar e reportar")

Fórmula aplicada (verificada contra o Pine fonte):

- 2 pivots same-direction CONSECUTIVOS (currentLevel anterior vs novo)
- Pool: equal-length pivots (length=3, leg via `getCurrentStructure`)
- Threshold: estático `0.1 × ta.atr(200)` (Pine hardcoded)
- Comparação estrita `<` (Pine `<`, não `<=`)
- ATR Wilder, length=200

### Resultado quantitativo

| Métrica | EQH | EQL |
|---|---|---|
| Pivots equal-length detectados | 71 | 72 |
| Pares consecutivos pós-ATR-warmup (idx >= 199) | 50 | 51 |
| Pares pré-warmup (ATR NaN, ignorados) | 20 | 21 |
| Matches (`diff < 0.1 × atr200`) | **0** | **0** |
| Near-misses (`diff < 2 × thresh`) | 2 | 4 |

### Comparativo contra ground truth (briefing §5)

Dos 5 níveis de **alta confiança** do ground truth ChatGPT vs LuxAlgo
TradingView, **nenhum** foi reproduzido pela fórmula canônica:

| Ground truth | Candle aprox. | ATR warmup? | Engine detectou? |
|---|---|---|---|
| EQL ~94.4k @ 15 jan | ~84 | sim (NaN) | não |
| EQH ~89.3k @ 27-28 jan | ~160 | sim (NaN) | não |
| EQH ~79.1k @ 1-2 fev | ~190 | sim (NaN) | não |
| EQH ~68.8k @ 27 fev | ~340 | não | não (diff ~2000+ USD) |
| EQH ~67.2k @ 3 abr | ~570 | não | não (diff ~150 USD, thresh ~110) |

### Hipóteses (não confirmadas)

Per briefing §7 — **não inventar adaptações**. Possíveis causas:

1. **ATR warmup do janela 720 candles** mascara os 4 EQH/EQL de
   alta confiança pré-fevereiro. Em TradingView (full history),
   ATR(200) estaria definida desde candle 0.
2. **Threshold 0.1 × atr(200) é muito apertado** para BTC 4H
   (~100-130 USD vs movimentos típicos entre pivots equal-length
   de 500-3000 USD).
3. **Pool de pivots equal-length=3 produz mais granularidade**
   do que o LuxAlgo SMC TradingView visualiza, intercalando pivots
   "ruidosos" entre EQH/EQL reais.
4. **Detecção de legs (Wave 3)** pode estar divergente do Pine
   em alguma sub-condição — diagnóstico read-only separado, fora
   do escopo da Wave 8.2.
5. **Pine fonte usado** (`luxalgo_smc_compute_only.py`) pode ser
   versão diferente da que ChatGPT viu no TradingView.

## Próximos passos sugeridos (decisão de Marcelo)

- Investigação read-only contra o Pine ao vivo no TradingView para
  confirmar que LuxAlgo SMC realmente desenha os EQH/EQL listados
  no ground truth.
- Comparar pool de pivots equal-length da engine vs Pine (pode haver
  divergência de leg detection).
- Considerar se o ground truth ChatGPT misturou indicadores SMC
  Concepts + ICT Concepts (que tem fórmula diferente).

**Não-bloqueante para a Wave 8.2:** a implementação canônica está
fiel ao Pine fonte verificado. Quaisquer ajustes para reproduzir
ground truth precisam de evidência adicional (re-verificação visual
ou Pine fonte alternativo), não chute de parâmetros.
