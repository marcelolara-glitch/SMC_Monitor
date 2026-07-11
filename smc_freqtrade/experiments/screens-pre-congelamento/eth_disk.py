from pathlib import Path
import pandas as pd, numpy as np
from freqtrade.data.history import load_pair_history
from freqtrade.enums import CandleType
from freqtrade.configuration import TimeRange
from freqtrade.strategy.strategy_helper import merge_informative_pair
from smc_engine import analyze, compute_setup_state, SetupConfig
DATADIR = Path("user_data/data/okx"); TR = TimeRange.parse_timerange("20240501-20260601")
def load(pair, tf):
    last=None
    for fmt in ("feather","parquet","json"):
        try:
            d=load_pair_history(pair,tf,DATADIR,timerange=TR,candle_type=CandleType.FUTURES,data_format=fmt)
            if d is not None and len(d): return d
        except Exception as e: last=e
    raise RuntimeError(f"sem dados {pair} {tf}: {last}")
def merge_inf(base, raw, inf_tf):
    inf=analyze(raw).df.copy(); inf=inf.rename(columns=lambda c:f"{c}_{inf_tf}")
    return merge_informative_pair(base,inf,"15m",inf_tf,ffill=True,append_timeframe=False,date_column=f"date_{inf_tf}")
def build(pair):
    b=load(pair,"15m"); b=merge_inf(b,load(pair,"4h"),"4h"); b=merge_inf(b,load(pair,"1h"),"1h")
    return analyze(b).df.reset_index(drop=True)
print("=== VALIDACAO: pipeline disco vs parquet BTC de referencia ===")
btc=compute_setup_state(build("BTC/USDT:USDT").copy(),SetupConfig())
ref=pd.read_parquet("user_data/diag_df.parquet")
m=btc.merge(ref[["date","close_4h","close_1h","setup_state"]].rename(columns={"close_4h":"c4r","close_1h":"c1r","setup_state":"ssr"}),on="date",how="inner")
m=m[m["date"]>=pd.Timestamp("2024-06-01",tz="UTC")].reset_index(drop=True)
print(f"datas comuns (>=2024-06-01): {len(m)}")
ok4=np.isclose(m["close_4h"].to_numpy(float),m["c4r"].to_numpy(float),equal_nan=True).mean()
ok1=np.isclose(m["close_1h"].to_numpy(float),m["c1r"].to_numpy(float),equal_nan=True).mean()
ss=(m["setup_state"].astype("string").fillna("").to_numpy()==m["ssr"].astype("string").fillna("").to_numpy()).mean()
print(f"close_4h igual: {ok4:.4f} | close_1h igual: {ok1:.4f} | setup_state concordancia: {ss:.4f}")
if not (ok4>0.999 and ok1>0.999 and ss>0.99):
    print("\n!!! VALIDACAO FALHOU - pipeline diverge. NAO processando ETH.")
    d=m[m["setup_state"].astype('string').fillna('')!=m["ssr"].astype('string').fillna('')].head(8)
    print(d[["date","setup_state","ssr"]].to_string()); raise SystemExit(0)
print(">>> VALIDACAO OK - pipeline fiel. Processando ETH.\n")
eth=build("ETH/USDT:USDT"); eth=eth[eth["date"]>=pd.Timestamp("2024-06-01",tz="UTC")].reset_index(drop=True)
eth.to_parquet("user_data/diag_df_eth.parquet"); print("parquet ETH salvo:",eth.shape)
df0=eth[[c for c in eth.columns if not c.startswith("setup_")]].copy().reset_index(drop=True)
hi=df0["high"].to_numpy(float); lo=df0["low"].to_numpy(float); cl=df0["close"].to_numpy(float)
n=len(df0); FEE,SLIP,HORIZON,RR=0.0005,0.0002,96,3.0; hold=cl[-1]/cl[0]-1
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
