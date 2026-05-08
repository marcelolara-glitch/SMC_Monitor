# Golden Dataset SMC — `tests/golden/`

## 1. Objetivo

Este diretório contém a infraestrutura de **golden dataset** usada para validar
a portagem do indicador `LuxAlgo - Smart Money Concepts` (gratuito, open
source) feita em `smc_freqtrade/smc_engine/` a partir das Ondas 5-8
(BOS/CHoCH, Order Blocks, Fair Value Gaps, Liquidity Sweep).

**Indicador de referência:** LuxAlgo SMC gratuito (open source). NÃO é o
LuxAlgo Price Action Concepts™ (pago, invite-only). Razão: a portagem é mapa
fiel do compute-only `tools/pynecore-validation/luxalgo_smc_compute_only.py`,
que é o gratuito. Validar contra o pago geraria divergências sistêmicas
não-bug.

**Timezone:** UTC (TradingView configurado em UTC antes da captura).

**Janela:** 720 candles 4H (~120 dias) em BTC-USDT-SWAP na OKX.

**Tolerance de match dos testes consumidores:** ±1 candle (4 horas em TF 4H).

## 2. Escopo do golden

### Incluído

- BOS bullish/bearish (internal e swing)
- CHoCH bullish/bearish (internal e swing)
- OB bullish/bearish — formação e mitigação (internal e swing)
- FVG bullish/bearish — formação e mitigação
- EQH/EQL alerts
- Premium/Discount/Equilibrium zones (limites por screenshot, não candle-a-candle)

### Excluído

- Swing/internal/equal pivots por candle (validados por testes sintéticos na
  Onda 3, já mergeada). Razão: leitura visual humana de screenshots dá
  precisão de evento (±1 candle), não de candle exato.
- CHoCH+ (feature exclusiva do LuxAlgo Price Action Concepts pago)
- Volumetric OB metrics (idem)
- Breaker Blocks (idem)
- Liquidity Grabs (idem; será abordado na Onda 8 com regra própria)
- Liquidity Trendlines (idem)
- Chart Patterns (idem)
- Inverse FVG e Double FVG (idem)
- Volume Imbalance e Opening Gap (irrelevantes para perpetual swap 24/7)

## 3. Fluxo de produção (sessão pós-merge)

1. **Configuração TradingView**
   Marcelo configura o TradingView em UTC e aplica o indicador
   `LuxAlgo - Smart Money Concepts` em chart BTC-USDT-SWAP 4H da OKX (mesmo
   provedor do dado em `data/btc_usdt_swap_4h_window.csv`).

2. **Captura dos screenshots**
   Marcelo captura **6-8 screenshots** cobrindo a janela completa, em ordem
   cronológica. Cada screenshot deve ter 90-120 candles visíveis. A densidade
   exata fica a critério de Marcelo no momento da captura — o conversor
   aceita qualquer subdivisão da janela total.

3. **Sessão Claude.ai + Marcelo**
   Cada screenshot é descrito por Marcelo em prosa; Claude.ai/Code produz a
   fatia do JSON estruturado conforme o schema (`schema/golden_schema.json`).
   **Marcelo NUNCA produz JSON manualmente.** A captura visual é dele; a
   estruturação do JSON é Claude.ai/Code.

4. **Validação**
   Roda-se `tools/golden_validator.py` para checar conformidade com o schema,
   coerência interna e integridade do CSV via SHA-256:

   ```bash
   python -m smc_freqtrade.tests.golden.tools.golden_validator \
       --golden tests/golden/golden/btc_usdt_swap_4h_luxalgo_smc.json \
       --csv tests/golden/data/btc_usdt_swap_4h_window.csv
   ```

5. **Pull request**
   Marcelo abre PR de atualização do JSON; review humano antes de merge.

## 4. Fluxo de atualização

Quando o indicador LuxAlgo for atualizado, ou quando a janela for estendida,
o golden é **versionado**, não substituído.

- **Versionamento por hash:** o campo `meta.ohlcv_csv_sha256` guarda o
  SHA-256 do CSV de OHLCV. Qualquer mudança no CSV invalida o hash e o
  validador acusa.
- **Política:** cada atualização gera novo arquivo com sufixo
  (`btc_usdt_swap_4h_luxalgo_smc_v2.json`, `_v3.json`, etc.), preservando
  histórico.

Para gerar/atualizar o CSV, use o `tools/ohlcv_fetcher.py`:

```bash
python -m smc_freqtrade.tests.golden.tools.ohlcv_fetcher \
    --start 2026-01-08T00:00:00Z \
    --end   2026-05-08T00:00:00Z \
    --output tests/golden/data/btc_usdt_swap_4h_window.csv
```

O fetcher imprime o SHA-256 do CSV gerado e grava
`btc_usdt_swap_4h_window.csv.sha256` ao lado. Esse valor deve ser copiado
para `meta.ohlcv_csv_sha256` no golden.

## 5. Schema reference

O schema canônico está em `schema/golden_schema.json` (JSON Schema draft-07).
Campos opcionais que dependem de `event_type` (como `ob_top`, `fvg_top`,
`level`) não são restringidos pelo schema — a validação condicional fica em
`tools/golden_validator.py`.

## 6. Regras imperativas

- **Marcelo NUNCA produz JSON manualmente.** A produção do JSON é
  responsabilidade do Claude.ai/Code em sessão dedicada.
- **Pivots por candle NÃO entram no golden.** Esses ficam validados pelos
  testes sintéticos da Onda 3.
- **Tolerância dos testes consumidores é ±1 candle.** Os testes das Ondas 5+
  asseveram "este BOS foi detectado dentro de ±1 candle do timestamp
  esperado", não match candle-exato.
- **TradingView precisa estar em UTC** antes de qualquer captura. Sem isso,
  há conversão e introdução de erro.
- **CSV não é editado manualmente.** Qualquer mudança invalida o hash
  registrado no `meta.ohlcv_csv_sha256`.

## 7. Estrutura do diretório

```
tests/golden/
├── README.md                                 # este arquivo
├── schema/
│   └── golden_schema.json                    # JSON Schema draft-07
├── data/
│   ├── btc_usdt_swap_4h_window.csv           # OHLCV real (preenchido pós-merge)
│   └── btc_usdt_swap_4h_window.csv.sha256    # hash do CSV
├── golden/
│   └── btc_usdt_swap_4h_luxalgo_smc.json     # golden estruturado
└── tools/
    ├── __init__.py
    ├── golden_validator.py                   # valida JSON contra schema + CSV
    └── ohlcv_fetcher.py                      # gera CSV via OKX REST
```
