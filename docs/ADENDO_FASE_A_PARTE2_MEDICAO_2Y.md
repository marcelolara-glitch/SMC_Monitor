# ADENDO AO RELATÓRIO FASE A / PARTE 2 — Medições de 2 anos (VM, BTC + ETH)

> **Natureza:** complemento de evidência ao `RELATORIO_FASE_A_PARTE2_FIDELIDADE.md`, executando
> as medições pendentes do §7 daquele relatório. Mantém a disciplina da Fase A: **nenhuma
> métrica de P&L, nenhuma proposta de correção** (pertencem ao Briefing 2).
>
> **Proveniência:** script `~/fase_a/medicao_2y.py` executado pelo Marcelo na VM em 2026-07-04;
> output integral em `~/fase_a/medicao_2y_output.txt`. Insumos:
> `user_data/diag_df.parquet` (BTC, 315 colunas) e `user_data/diag_df_eth.parquet` (ETH, 303
> colunas), ambos n=70.081 candles 15m, 2024-06-01 → 2026-06-01. A FSM foi **re-executada**
> sobre a base mergeada nos dois modos (`confirmation` e `risk`), por assinatura (solo) e na
> composição multi-9 (modo confirmation), com `smc_engine.setup_state` do repositório da VM.
>
> **Método do `mitigated` espúrio:** lower-bound sem ledger — o OB capturado é considerado
> ainda-vivo se seu id volta a ser promovido em candle posterior à invalidação. O complemento é
> "indeterminado", não "genuíno".

---

## 1. Status atualizado dos achados (golden → 2 anos)

| Achado | Golden (4m BTC) | BTC 2 anos | ETH 2 anos | Status |
|---|---|---|---|---|
| **G1** escape-moedor | 97–99% inval. escaped; vida mediana 1 candle; dist. armação med 2,5–7,2% | idem; **arm>2pct: 62–99%** por assinatura; dist med 2,3–6,8% (p90 até 23%) | idem; arm>2pct 74–99%; dist med 3,1–9,5% (p90 até 27%) | **Confirmado, definitivo.** Mecanismo domina os dois ativos e modos |
| **G2** ChoCH∧rej mesmo-candle | 10 co-ocorrências / 11.520 (8,7/10k) | 73 / 70.081 (**10,4/10k**) | 40 / 70.081 (**5,7/10k**) | **Confirmado.** Modo confirmation: **7 CONFIRMED (BTC) e 8 (ETH) em 2 anos, somando as 9 assinaturas** (~3,5 trades/ano/ativo) |
| **G3** mitigated espúrio | 15/15 (100%) | lower-bound 65–100% por assinatura (ex.: A3 22/22 conf, 26/26 risk) | idem (ex.: A3 7/7; A2 29/36) | **Confirmado** nos dois ativos e modos |
| **G4** teto do volpct vs 0,2 | bull 0,130 / bear 0,242 (janela) | **bull 0,110 / bear 0,199 → A5 = 0 setups em 2 anos nos 2 modos** | bull 0,231 (467 candles >0,2 → 228 setups) / bear 0,128 | **Confirmado e ampliado:** limiar acima do teto em 3 dos 4 lados-ativo. Correção ao golden: janelas curtas inflam o pct (menos OBs ativos no denominador); os valores de 2 anos prevalecem |
| **G5** gate de OB na A9 | presente | presente (A9 = 22.348 setups solo, 0 CONF em conf) | idem (25.519 solo) | Confirmado por leitura de código; comportamento coerente com o gate |
| **G6** reversões sem gate 4H | tensão doc | trend_changed = 0–9 casos por assinatura (flips 4h = 21 em 2 anos) | idem (flips = 17) | Inalterado; invalidação por trend é quase inerte mesmo em 2 anos |
| **G7** OBs invertidos | 4/689 (15m, internal, contidos) | não re-medido (exige ledger; não está no parquet) | idem | Inalterado; medição de ledger fica para o ciclo de correção |
| **G8** lacunas-[v2.0] | presentes | presentes (displacement/EQ-cross/OB-estratégico/A7-MSS ausentes por construção) | idem | Inalterado (esperadas) |
| **G9 (novo)** máscara do slot único | não medido | **slot ocupado em 69.356/70.081 candles (99%); 63% por setups de vida ≤1 candle.** Multi-9 vs solo: A10 24.564→**1**; A7 2.064→**3**; A6 678→**0**; A9 22.348→**62** | ocupado 70.078/70.081; 74% por vida ≤1. A7 2.358→**0**; A6 3.246→**4**; A10 27.486→**12**; A9 25.519→**20** | **Novo achado estrutural [BUG-FID]:** prioridade D3 + slot único + churn G1 = starvation quase total das assinaturas de prioridade ≥5 em execução combinada. Qualquer backtest multi-assinatura na FSM atual mede apenas A2/A3/A4a/A1 |

## 2. Síntese por assinatura (solo)

Formato: setups (conf) / CONFIRMED conf / CONFIRMED risk / arm>2pct (conf).

| A# | BTC | ETH |
|---|---|---|
| A1 | 28.563 / 0 / 187 / 99% | 31.881 / 1 / 170 / 99% |
| A2 | 20.984 / 0 / 169 / 98% | 24.375 / 1 / 158 / 99% |
| A3 | 1.785 / 0 / 60 / 92% | 2.182 / 1 / 67 / 96% |
| A4a | 14.865 / **4** / **1.136** / 89% | 16.258 / 2 / **1.281** / 90% |
| A5 | **0 setups (2 modos)** | 228 / 0 / 1 / 99% |
| A6 | 678 / 0 / 107 / 71% | 3.246 / 0 / 160 / 92% |
| A7 | 2.064 / 2 / 321 / 62% | 2.358 / 1 / 324 / 76% |
| A9 | 22.348 / 0 / 212 / 97% | 25.519 / 1 / 207 / 99% |
| A10 | 24.564 / 1 / 370 / 98% | 27.486 / 1 / 350 / 98% |

Totais CONFIRMED: confirmation **7 (BTC) / 8 (ETH)**; risk **2.562 (BTC) / 2.718 (ETH)**, com a
A4a respondendo por 44–47% do modo risk.

## 3. Contadores de base (2 anos)

- ChoCH internal: 1.021/1.021 (BTC b/s), 990/990 (ETH). Rejeições: ~6,4–6,9k por lado.
- OTE quase-permanente confirmado: ativa em 86–92% (BTC) e 89–95% (ETH) dos candles.
- Killzones: 2.920 candles por janela por ativo (4/dia × 730 dias) — grade correta.
- Trend 4h: 21 flips (BTC) / 17 (ETH) em 2 anos; distribuição 54/45% (BTC, long/short) e
  43/57% (ETH).
- Schema: BTC 315 colunas vs ETH 303 — deriva de 12 colunas entre as duas gerações de parquet
  [Provável: colunas extras de diagnóstico numa rodada]; nenhuma das colunas exigidas faltou.

## 4. Implicação para o veredito histórico (registro, sem P&L)

O screen de 2 anos operou em modo risk sobre esta mesma mecânica: amostrou majoritariamente
A4a, mediu A5-BTC sobre **zero** setups, mediu A7/A9/A10 nas variantes simplificadas com os
gates G1/G3/G5 ativos, e — se combinado — sob a máscara G9. O resultado negativo daquele
screen é um veredito sobre **esta máquina**, não sobre as assinaturas conforme o conceito
ratificado v2.0. A recíproca também vale: nada aqui evidencia edge; o teste do conceito
ratificado ainda não aconteceu.

## 5. Encerramento da fase de medição

Com este adendo, os itens [AMOSTRAL] do relatório da Parte 2 estão decididos (G4 ampliado;
assimetrias A5/A6 explicadas por teto de gate + regime; trend-invalidation inerte) e o item
pendente do §7 (efeito-máscara) virou o achado G9. Insumo quantitativo do Briefing 2:
**completo**. Correções, priorização e gates out-of-sample pertencem ao Briefing 2.
