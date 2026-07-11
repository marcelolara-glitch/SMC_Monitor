# DISCLOSURE — Screens de P&L pré-congelamento + EMENDA pré-registrada do universo OOS

> **Status:** disclosure obrigatória + emenda de universo de dados sob o ciclo §4-P5 do
> `docs/CONGELAMENTO_CANDIDATA_V2_E_GATES_EDGE.md` (o doc de congelamento permanece
> imutável e **não** é editado; esta emenda altera exclusivamente o universo de dados
> do §2 dele — a configuração-candidata do §1 não muda em nenhum campo). Escrita em
> 2026-07-09, antes de qualquer execução P3/P4. Evidência: scripts arquivados em
> `smc_freqtrade/experiments/screens-pre-congelamento/` (ver §5).

---

## §1. Fato: o que rodou na VM antes do congelamento

Inventário dos artefatos não rastreados encontrados na VM em 2026-07-09 (pós-merge do
PR #89), todos criados **durante a conversa diagnóstica de 2026-07-02→07-08, sob
demanda da bancada de análise** (Marcelo executa exclusivamente sob instrução; a
autoria metodológica dos screens é da análise, não do operador):

| Script | O quê | Ativo / janela | Config |
|---|---|---|---|
| `diag_setup_state.py` | pipeline Freqtrade → indicadores → contagens de estado | BTC 2024-06→2026-06 | legada |
| `diag_confirm.py` | idem + cache `diag_df.parquet` | BTC, idem | legada |
| `diag_relax.py` | co-ocorrência de gatilhos (choch/rej/sweep) sobre o cache | BTC, idem | legada |
| `eth_disk.py` | carga de histórico ETH do disco + engine | ETH 2024-05→2026-06 | legada |
| `screen_signatures.py` | **P&L cru engine-level**: 9 assinaturas × RR {1.5, 2, 3}, WR/expectância bruta e líquida/PF, fee 0,05%+slip 0,02% | **BTC** 2024-06→2026-06 | legada, `entry_mode='risk'` |
| `oos_a9.py` | **P&L cru com split temporal** (treino/teste no meio da janela): A9/A1/A2/A6, RR3, expectância líquida | **BTC**, idem | legada, risk |
| `eth_oos.py` | **P&L cru**: A9/A1/A2/A6, RR3, WR/expectância/soma/PF + buy&hold | **ETH** 2024-06→2026-06 | legada, risk |
| `diag_df.parquet` / `diag_df_eth.parquet` | caches de indicadores (BTC / ETH) | — | — |

Semântica do "P&L cru engine-level": entrada no close do candle de CONFIRMED, SL na
borda da zona, TP por múltiplo de R, horizonte fixo de 96 candles, sem harness
Freqtrade, sem execução por trade, sem `custom_stoploss`/`custom_exit`. Os números
foram impressos e vistos.

## §2. Correção da premissa do congelamento

O cabeçalho do doc de congelamento afirma: *"nenhum número de P&L existia quando este
documento foi escrito"*. **A afirmação é falsa como escrita.** A forma verdadeira:
nenhum P&L do **instrumento dos gates** (harness Freqtrade/IStrategy) existia; P&L
cru engine-level existia para BTC (9 assinaturas, config legada em modo risk) e ETH
(4 assinaturas, idem).

**Causa-raiz:** a premissa foi escrita **por inferência**, sem inventário da working
tree da VM — violação do §0 cometida pelo próprio autor do documento de
pré-registro. **Regra derivada (permanente):** nenhuma premissa de pré-registro sobre
"o que já foi computado/visto" se escreve sem inventário prévio da VM
(`git status --short` + leitura dos não-rastreados). Registrada junto às 5 instâncias
de defeito de autoria de briefing.

## §3. Classificação da contaminação

- **BTC (treino):** informado por screens. Aceitável por definição — treino nunca foi
  o ativo protegido — mas fica registrado que a escolha dos habitats por grupo
  (confirmation/risk) foi feita com conhecimento de contagens e de screens crus de
  regime. **Consequência estrutural: BTC não serve como plano B de walk-forward
  "virgem" na janela ≤ 2026-06.**
- **ETH:** contaminado screen-level. Vazou informação de regime — sinal e ordem de
  grandeza da expectância de A9/A1/A2/A6 sob config legada em modo risk. Não vazou o
  resultado do experimento congelado (candidata ≠ config legada; harness ≠ screen),
  mas a virgindade exigida de um OOS primário está perdida.
- **Qualquer terceiro ativo:** virgem. Confirmado pelo operador em 2026-07-09:
  nenhum script exploratório jamais rodou sobre ativo além de BTC e ETH.

## §4. EMENDA pré-registrada — universo OOS (ciclo §4-P5; só dados/gates, candidata intacta)

1. **OOS primário passa a ser `SOL/USDT:USDT`** (OKX, futures/isolated), mesma janela
   (2024-07-01 → 2026-06-30 UTC), mesmos TFs (15m+1h+4h). O GE-3 do doc de
   congelamento é lido sobre SOL: `n_oos ≥ 10` e expectância de mesmo sinal.
2. **ETH é rebaixado a OOS secundário/corroborativo, com asterisco permanente** (em
   especial para A9, A1, A2 e A6 — as medidas em `eth_oos.py`). Papel: corroborar ou
   enfraquecer um veredito de SOL. **Resultado de ETH não pode promover assinatura
   reprovada em SOL, nem reverter PARKED em PASS.**
3. **Proibição explícita:** nenhum script exploratório, screen, contagem ou P&L roda
   sobre SOL antes do P4. A primeira leitura de SOL é o próprio GE-3.
4. Ordem de operações do §4 do doc de congelamento inalterada, com P4 executado
   primeiro em SOL e depois em ETH (corroboração), ambos só após os vereditos de
   treino commitados (P3).

## §5. Arquivamento da evidência

Os 7 scripts são movidos para `smc_freqtrade/experiments/screens-pre-congelamento/`
e **versionados** (referência canônica desta disclosure, convenção AGENTS §4.2 —
diretório com README). Os 2 parquets são movidos para o mesmo diretório e
**gitignorados** (caches reprodutíveis, binários grandes). Nada é re-executado: cada
re-execução aprofundaria a exposição.

---

*Escrita em 2026-07-09, main @ 00e48ad (VERSION 0.11.0). Autoria da falha de
premissa: bancada de análise. Operador isento: execução exclusivamente sob demanda.*
