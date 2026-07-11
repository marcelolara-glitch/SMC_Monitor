import pandas as pd, numpy as np
from freqtrade.configuration import Configuration
from freqtrade.enums import RunMode
from freqtrade.optimize.backtesting import Backtesting
PAIR = "BTC/USDT:USDT"
cfg = Configuration.from_files(["config_backtest.json"])
cfg["strategy"] = "SMCStrategy"; cfg["timerange"] = "20240601-20260601"
cfg["export"] = "none"; cfg["runmode"] = RunMode.BACKTEST
bt = Backtesting(cfg); data, _ = bt.load_bt_data(); bt._set_strategy(bt.strategylist[0])
df = bt.strategy.advise_all_indicators(data)[PAIR].copy()
try:
    df.to_parquet("user_data/diag_df.parquet"); print("df salvo: user_data/diag_df.parquet")
except Exception as e:
    print("parquet falhou (ok):", e)
def col(n):
    return df[n].fillna(False).to_numpy(bool) if n in df.columns else np.zeros(len(df), bool)
o=df["open"].to_numpy(float); h=df["high"].to_numpy(float); lo=df["low"].to_numpy(float); c=df["close"].to_numpy(float)
choch_b=col("choch_internal_bullish"); choch_s=col("choch_internal_bearish")
sweep_b=col("sweep_bullish_wick")|col("sweep_bullish_retest")
sweep_s=col("sweep_bearish_wick")|col("sweep_bearish_retest")
sr_b=pd.Series(sweep_b).rolling(16,min_periods=1).max().fillna(0).to_numpy(bool)
sr_s=pd.Series(sweep_s).rolling(16,min_periods=1).max().fillna(0).to_numpy(bool)
rng=h-lo; safe=rng>0; rs=np.where(safe,rng,1.0)
ub=np.minimum(o,c); lb=np.maximum(o,c)
bwf=np.where(safe,(ub-lo)/rs,0.0); ewf=np.where(safe,(h-lb)/rs,0.0)
rej_b=safe&(bwf>=0.5)&(c>=lo+0.667*rng)
rej_s=safe&(ewf>=0.5)&(c<=h-0.667*rng)
S=lambda a:int(np.asarray(a).sum())
for nm,ch,rj,sw in [("BULL",choch_b,rej_b,sr_b),("BEAR",choch_s,rej_s,sr_s)]:
    print(f"\n--- {nm} ---")
    print(f"choch={S(ch)}  rej={S(rj)}  sweep_recent={S(sw)}")
    print(f"choch&rej={S(ch&rj)}  choch&sweep={S(ch&sw)}  rej&sweep={S(rj&sw)}")
    print(f"choch&rej&sweep={S(ch&rj&sw)}   <-- confirmacao A3")
