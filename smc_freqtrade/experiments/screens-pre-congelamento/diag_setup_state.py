import pandas as pd
from freqtrade.configuration import Configuration
from freqtrade.enums import RunMode
from freqtrade.optimize.backtesting import Backtesting
PAIR = "BTC/USDT:USDT"
cfg = Configuration.from_files(["config_backtest.json"])
cfg["strategy"] = "SMCStrategy"
cfg["timerange"] = "20240601-20260601"
cfg["export"] = "none"
cfg["runmode"] = RunMode.BACKTEST
bt = Backtesting(cfg)
data, _ = bt.load_bt_data()
bt._set_strategy(bt.strategylist[0])
print("dados:", {p: len(d) for p, d in data.items()})
df = bt.strategy.advise_all_indicators(data)[PAIR].copy()
print("shape pos-indicadores:", df.shape)
mtf4 = [c for c in df.columns if c.endswith("_4h")]
mtf1 = [c for c in df.columns if c.endswith("_1h")]
print(f"\nMTF: {len(mtf4)}x _4h, {len(mtf1)}x _1h")
for c in (mtf4[:4] + mtf1[:4]):
    print(f"   {c}: {df[c].notna().mean():.1%} nao-nulo")
for col in ["setup_state", "setup_direction", "setup_signature"]:
    print(f"\n=== {col} ===")
    print(df[col].value_counts(dropna=False).to_string() if col in df.columns else "!!! AUSENTE")
act = [c for c in df.columns if c.startswith("active_")]
if act:
    print(f"\nactive_* ({len(act)} cols): {df[act].notna().any(axis=1).mean():.1%} das linhas com algum nao-nulo")
dfe = bt.strategy.advise_entry(df, {"pair": PAIR})
sl = int(dfe["enter_long"].fillna(0).sum()) if "enter_long" in dfe.columns else "n/a"
ss = int(dfe["enter_short"].fillna(0).sum()) if "enter_short" in dfe.columns else "n/a"
print(f"\n=== enter_long={sl}  enter_short={ss}")
