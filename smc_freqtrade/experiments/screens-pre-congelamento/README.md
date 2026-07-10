# experiments/screens-pre-congelamento

Diretório de arquivamento (convenção AGENTS §4.2) dos scripts exploratórios
de P&L cru rodados na VM **antes** do congelamento da candidata V2, durante a
conversa diagnóstica de 2026-07-02→07-08.

## Por que existe

Serve como **evidência canônica** da disclosure em
`docs/DISCLOSURE_E_EMENDA_UNIVERSO_OOS.md` — a correção da premissa do
`docs/CONGELAMENTO_CANDIDATA_V2_E_GATES_EDGE.md` ("nenhum número de P&L
existia") e a emenda pré-registrada do universo OOS (SOL primário, ETH
rebaixado a corroborativo).

## Status: CONGELADO — nunca re-executar

Os scripts aqui são **artefatos históricos**, não ferramentas de trabalho.
Cada re-execução aprofundaria a exposição de regime já registrada na
disclosure (BTC de treino contaminado, ETH screen-level contaminado). Ficam
versionados para leitura e auditoria, **não** para rodar.

## O que é versionado vs descartável

- **Versionado (referência canônica):** os 7 scripts `.py` listados no §1 da
  disclosure — `diag_setup_state.py`, `diag_confirm.py`, `diag_relax.py`,
  `eth_disk.py`, `screen_signatures.py`, `oos_a9.py`, `eth_oos.py`. Serão
  movidos para cá pelo Marcelo (só existem na VM neste momento).
- **Descartável / gitignored:** os caches `*.parquet`
  (`diag_df.parquet`, `diag_df_eth.parquet`) — binários grandes,
  reproduzíveis, cobertos pelo `.gitignore` da raiz.

## Referência

- Disclosure: `docs/DISCLOSURE_E_EMENDA_UNIVERSO_OOS.md`
- Doc de congelamento (imutável): `docs/CONGELAMENTO_CANDIDATA_V2_E_GATES_EDGE.md`
