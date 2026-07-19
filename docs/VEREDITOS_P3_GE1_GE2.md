# VEREDITOS P3 — GE-1/GE-2 (treino BTC, janela congelada)

> **Status:** tabela de vereditos pré-registrada do protocolo §4-P3
> (`docs/CONGELAMENTO_CANDIDATA_V2_E_GATES_EDGE.md` §3, universo emendado por
> `docs/DISCLOSURE_E_EMENDA_UNIVERSO_OOS.md` §4). O commit deste documento
> encerra o P3 e é **pré-condição** de qualquer execução sobre SOL (P4).
> Imutável após merge; correções ⇒ novo ciclo §4-P5.

## §1. Identificação da execução

- Código: `main @ bc5fcc4` (pós-Waves 10.1–10.7); config `beb0e3e`
  (`futures_funding_rate=0`) + chaves da Wave 10.2 (`fee=0.0005`,
  `stoploss=-0.99`, `SMCStrategyCandidate`).
- Ambiente: VM Oracle, freqtrade 2026.3, execução 2026-07-19 00:25→01:25 UTC.
- Export: `user_data/backtest_results/p3-2026-07-19_01-25-08.*`.
- Timerange executado: 2023-04-01→2026-06-30 (warm-up ratificado, Wave 10.4);
  **janela de veredito: 2024-07-01→2026-06-30** via
  `p3_report --gates --window-start 2024-07-01` — 251 trades no export,
  91 pré-janela descartados (2023-04-10…2024-06-30), **160 na janela**.
- GE-0: known-answer 30 passed na VM imediatamente antes da execução.

## §2. Tabela de vereditos (saída verbatim do `p3_report`)

| sid | n | wins | wr | soma_R | expectancy_R | profit_abs | GE-1 | GE-2 | veredito |
|---|---:|---:|---:|---:|---:|---:|---|---|---|
| A1 | 15 | 5 | 0.333 | -0.1091 | -0.0073 | +4.1084 | PARKED | FAIL | PARKED |
| A10 | 3 | 0 | 0.000 | -3.1592 | -1.0531 | -6.3041 | PARKED | FAIL | PARKED |
| A2 | 5 | 1 | 0.200 | -2.1602 | -0.4320 | -7.9689 | PARKED | FAIL | PARKED |
| A3 | 4 | 1 | 0.250 | -0.8431 | -0.2108 | -2.0326 | PARKED | FAIL | PARKED |
| A4a | 33 | 14 | 0.424 | +8.8561 | +0.2684 | +25.1409 | PASS | PASS | **PASS-treino** |
| A6 | 4 | 0 | 0.000 | -4.3339 | -1.0835 | -6.5615 | PARKED | FAIL | PARKED |
| A7 | 19 | 4 | 0.211 | -9.2478 | -0.4867 | -6.3190 | PARKED | FAIL | PARKED |
| A9 | 77 | 26 | 0.338 | -1.8628 | -0.0242 | +15.2375 | PASS | FAIL | **FAIL-treino** |

A5: **0 entradas** em toda a execução — PARKED por construção, conforme
pré-registrado (§1.2 do doc de congelamento: teto empírico de `volume_pct_min`);
revisita pertence à fase de hyperopt.

## §3. Asteriscos obrigatórios (declarados no congelamento)

1. **Funding=0** (OKX não serve histórico >4 meses): funding real de BTC é
   majoritariamente positivo ⇒ longs inflados. Cota superior estimada:
   ~0,03%/dia de posição ⇒ com risco médio de zona ~2% e duração média ~2 dias,
   ~0,03R por trade. **A4a** (edge concentrado em longs): +0,2684R − ~0,03R
   permanece claramente positivo — veredito robusto ao viés. **A9**: −0,0242R
   está dentro da banda do viés (e o viés a favoreceria); o FAIL fica ainda mais
   sólido, não menos.
2. **Slippage não modelado** (limitação declarada, favorece a candidata):
   PASS-treino da A4a carrega este asterisco até avaliação com slippage.
3. **Nota anti-racionalização:** `profit_abs > 0` com `expectancy_R < 0` (A9,
   A1) não constitui aprovação — a métrica pré-registrada é expectância em R
   líquida de fee. Registrado para impedir relitígio pós-hoc.

## §4. Consequências (ordem de operações)

- **A4a → P4/GE-3:** OOS primário **SOL/USDT:USDT** (virgem, emenda §4);
  ETH corroborativo com asterisco. Nenhum script toca SOL antes do P4; a
  primeira leitura de SOL é o próprio GE-3.
- **A9 → FAIL-treino:** entra no acervo da fase de hyperopt como hipótese a
  re-testar sob novo pré-registro (não é exclusão — regra permanente).
- **A1, A2, A3, A6, A7, A10 → PARKED** (amostra insuficiente); **A5 → PARKED
  por construção.** Estacionadas, nunca descartadas.

## §5. Fato observacional (sem valor de gate; registro para hyperopt)

Assimetria long/short no período estendido: +3,98% vs −2,18% (parcialmente
explicada pelo item §3.1). A mecânica de saída conferiu com o desenho:
`smc_rr_target` ≈ +2R médio, `stop_loss` ≈ −1R médio.

---

*Escrito em 2026-07-19. Fecha P3. Próximo passo autorizado: P4 (SOL primário,
ETH corroborativo), somente após merge deste documento.*
