import os, pandas as pd, numpy as np
from smc_engine.setup_state import compute_setup_state, SetupConfig
PAIR="ETH/USDT:USDT"; PARQUET="user_data/diag_df_eth.parquet"
if not os.path.exists(PARQUET):
    from freqtrade.configuration import Configuration
    from freqtrade.enums import RunMode
    from freqtrade.optimize.backtesting import Backtesting
    cfg=Configuration.from_files(["config_backtest.json"])
    cfg["strategy"]="SMCStrategy"; cfg["timerange"]="20240601-20260601"
    cfg["export"]="none"; cfg["runmode"]=RunMode.BACKTEST
    cfg["exchange"]["pair_whitelist"]=[PAIR]
    bt=Backtesting(cfg)
    print("whitelist:", bt.pairlists.whitelist)
    assert PAIR in bt.pairlists.whitelist, "whitelist nao trocou para ETH - abortando"
    data,_=bt.load_bt_data(); bt._set_strategy(bt.strategylist[0])
    df=bt.strategy.advise_all_indicators(data)[PAIR].copy()
    df.to_parquet(PARQUET); print("parquet ETH salvo:", df.shape)
df0=pd.read_parquet(PARQUET)
df0=df0[[c for c in df0.columns if not c.startswith("setup_")]].copy().reset_index(drop=True)
hi=df0["high"].to_numpy(float); lo=df0["low"].to_numpy(float); cl=df0["close"].to_numpy(float)
n=len(df0); FEE,SLIP,HORIZON,RR=0.0005,0.0002,96,3.0
hold=cl[-1]/cl[0]-1
def run(sig):
    o=compute_setup_state(df0.copy(),SetupConfig(signature=sig,entry_mode="risk",trend_suffix="4h",zone_suffix="1h"))
    conf=(o["setup_state"]=="CONFIRMED").fillna(False).to_numpy(bool)
    trans=conf&~np.r_[False,conf[:-1]]; idx=np.where(trans)[0]
    dr=o["setup_direction"].astype("string").fillna("").to_numpy()
    zl=o["setup_zone_low"].to_numpy(float); zh=o["setup_zone_high"].to_numpy(float)
    out=[]; last=-1
    for i in idx:
        if i<=last or i>=n-1: continue
        d=dr[i]
        if d not in ("long","short"): continue
        e=cl[i]; sl=zl[i] if d=="long" else zh[i]
        if not np.isfinite(sl): continue
        if d=="long" and not sl<e: continue
        if d=="short" and not sl>e: continue
        risk=e-sl if d=="long" else sl-e
        if risk<=0: continue
        tp=e+RR*risk if d=="long" else e-RR*risk
        res=None; xi=min(i+HORIZON,n-1)
        for j in range(i+1,min(i+1+HORIZON,n)):
            if d=="long":
                if lo[j]<=sl: res=-1.0;xi=j;break
                if hi[j]>=tp: res=RR;xi=j;break
            else:
                if hi[j]>=sl: res=-1.0;xi=j;break
                if lo[j]<=tp: res=RR;xi=j;break
        if res is None: res=(cl[xi]-e)/risk if d=="long" else (e-cl[xi])/risk
        res-=e*(2*FEE+SLIP)/risk; out.append(res); last=xi
    return np.array(out)
print(f"\nETH buy&hold no periodo: {hold:+.0%}\n")
for sig in ["A9","A1","A2","A6"]:
    r=run(sig)
    if len(r)==0: print(f"{sig}: 0 trades"); continue
    pf=r[r>0].sum()/(-r[r<0].sum()) if (r<0).any() else float("inf")
    print(f"{sig} (RR{RR}): n={len(r)} WR={(r>0).mean():.0%} exp={r.mean():+.2f}R soma={r.sum():+.0f}R PF={pf:.2f}")
