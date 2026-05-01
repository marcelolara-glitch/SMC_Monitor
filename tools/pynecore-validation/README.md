# tools/pynecore-validation

Experimento de validação cruzada entre o LuxAlgo SMC traduzido para
Python (via PyneCore) e o LuxAlgo SMC original rodando no TradingView.

## Por que existe

Antes de integrar a lógica SMC à `IStrategy` do Freqtrade, precisamos
confirmar empiricamente que a tradução Pine→Python preserva fidelidade
canônica. A validação é feita comparando:

- **Saídas Python:** os 16 alertcondition disparam quando? Em quais candles?
- **Saídas TradingView:** o LuxAlgo desenha BOS/CHoCH/OB/FVG/EQH/EQL nos
  mesmos candles?

Se ambos coincidirem, a tradução está fiel e podemos avançar.

## Janela do experimento

- **Par:** BTC/USDT-PERP (Binance)
- **Timeframe:** 4h
- **Janela:** 30 dias (~180 candles)
- **Período exato:** definido em runtime pelo `run_validation.py`

## Como rodar

```bash
# 1. Criar venv isolado (uma vez)
cd ~/SMC_Monitor
python3 -m venv .venv-pynetest
source .venv-pynetest/bin/activate
pip install -r tools/pynecore-validation/requirements.txt

# 2. Garantir que candles 4h do BTC estão baixados pelo Freqtrade
# (devem estar em ~/SMC_Monitor/user_data/data/binance/futures/BTC_USDT_USDT-4h-futures.feather)

# 3. Rodar validação
cd tools/pynecore-validation
python3 run_validation.py

# 4. Sair do venv
deactivate
```

## Saídas geradas

Em `tools/pynecore-validation/output/` (gitignored):

- `events_full.csv` — uma linha por candle, 16 colunas booleanas
  (todas as alertconditions). Fonte de verdade para auditoria.
- `events_summary.csv` — apenas linhas onde algum evento disparou.
  Formato: `timestamp, event_type, candle_close`.

## Próximo passo

Após gerar os CSVs, comparar visualmente com screenshot do TradingView
mostrando o LuxAlgo SMC original aplicado na mesma janela.

Os 16 alertcondition rastreados:

1. Internal Bullish BOS
2. Internal Bullish CHoCH
3. Internal Bearish BOS
4. Internal Bearish CHoCH
5. Bullish BOS (Swing)
6. Bullish CHoCH (Swing)
7. Bearish BOS (Swing)
8. Bearish CHoCH (Swing)
9. Bullish Internal OB Breakout
10. Bearish Internal OB Breakout
11. Bullish Swing OB Breakout
12. Bearish Swing OB Breakout
13. Equal Highs (EQH)
14. Equal Lows (EQL)
15. Bullish FVG
16. Bearish FVG
