# smc_freqtrade

Subprojeto do `SMC_Monitor`. Engine SMC (Smart Money Concepts) em Python puro
integrada ao Freqtrade como IStrategy customizada.

**Status:** setup inicial (v0.1.0). Implementação da engine começa na Onda 1.

## Por que este subprojeto existe

Sucede o sistema legado (em `../legacy/` neste mesmo repositório), que foi
descontinuado em abril/2026 após análise honesta de make-vs-buy revelar que
construir e manter infraestrutura própria (WebSocket, persistência, gestão de
ordens) desperdiçava tempo em problemas resolvidos. A inteligência SMC mora
aqui; a infraestrutura passa a ser delegada ao Freqtrade.

Detalhes do raciocínio em
[../docs/SMC_PRINCIPIOS_E_LEGADO.md](../docs/SMC_PRINCIPIOS_E_LEGADO.md).

## Documentos canônicos do projeto

Vivem em `../docs/` no mesmo repositório:

- [SMC_PRINCIPIOS_E_LEGADO.md](../docs/SMC_PRINCIPIOS_E_LEGADO.md) — dogmas SMC e legado do sistema anterior
- [../AGENTS.md](../AGENTS.md) — workflow Claude.ai ↔ Claude Code, regras de PR e desenvolvimento
- [MAPA_LUXALGO_CAMADA_1_v1.1.md](../docs/MAPA_LUXALGO_CAMADA_1_v1.1.md) — inventário estrutural do LuxAlgo SMC
- [VERIFICACAO_FREQTRADE.md](../docs/VERIFICACAO_FREQTRADE.md) — referência Freqtrade verificada documentalmente

## Estrutura

```
smc_freqtrade/
├── smc_engine/          # biblioteca Python pura — engine SMC
├── tests/               # testes da engine (unit + integração + golden)
├── user_data/           # diretório do Freqtrade
│   ├── strategies/      # SMCStrategy.py (Onda 10) e outras
│   ├── data/            # OHLCV baixados — não versionados
│   ├── backtest_results/
│   └── logs/
├── config_backtest.json # config Freqtrade para backtests
├── requirements.txt
└── VERSION
```

## Setup local na VM

```bash
cd /home/ubuntu/SMC_Monitor/smc_freqtrade
python3.11 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
freqtrade --version
```

## Roadmap

10 ondas de portagem do LuxAlgo SMC + Onda 9.5 (máquina de estados) + Onda 10
(SMCStrategy). Detalhes em
[../docs/MAPA_LUXALGO_CAMADA_1_v1.1.md](../docs/MAPA_LUXALGO_CAMADA_1_v1.1.md).

## Datasets

Dois tipos de dados são usados pelo subprojeto e nunca se confundem:

- **Dados históricos OHLCV** (baixados pelo `freqtrade download-data`): usados
  em backtests e hyperopt. Ficam em `user_data/data/` e não são versionados.
- **Golden dataset SMC**: estrutura de eventos detectados pelo LuxAlgo SMC
  original (swings, OBs, FVGs, BOS/CHoCH) sobre uma janela de OHLCV específica.
  Serve **apenas** para validar que nossa engine portada produz outputs
  equivalentes ao Pine original. Produção é responsabilidade Claude.ai +
  Claude Code, a partir de referência visual (screenshot do TradingView com
  o indicador LuxAlgo aplicado) fornecida por Marcelo. Será produzido antes da
  Onda 3 em PR dedicado. Ficará em `tests/golden/` quando produzido. Não é
  parte do setup inicial.

## Versionamento

O subprojeto `smc_freqtrade/` tem versionamento próprio, independente do
sistema legado em `../legacy/`. Sequencial estrito (sem pular). Atual:
`0.1.0`.
