import pandas as pd, numpy as np
from smc_engine.setup_state import compute_setup_state, SetupConfig
df0 = pd.read_parquet("user_data/diag_df.parquet")
df0 = df0[[c for c in df0.columns if not c.startswith("setup_")]].copy().reset_index(drop=True)
hi=df0["high"].to_numpy(float); lo=df0["low"].to_numpy(float); cl=df0["close"].to_numpy(float)
n=len(df0); FEE,SLIP,HORIZON,RR=0.0005,0.0002,96,3.0; SPLIT=n//2
corte=str(df0["date"].iloc[SPLIT])[:10] if "date" in df0.columns else f"idx {SPLIT}"
def run(sig):
    o=compute_setup_state(df0.copy(),SetupConfig(signature=sig,entry_mode="risk",trend_suffix="4h",zone_suffix="1h"))
    conf=(o["setup_state"]=="CONFIRMED").fillna(False).to_numpy(bool)
    trans=conf&~np.r_[False,conf[:-1]]; idx=np.where(trans)[0]
    dr=o["setup_direction"].astype("string").fillna("").to_numpy()
    zl=o["setup_zone_low"].to_numpy(float); zh=o["setup_zone_high"].to_numpy(float)
    tr=[]; te=[]; last=-1
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
        res-=e*(2*FEE+SLIP)/risk
        (tr if i<SPLIT else te).append(res); last=xi
    return np.array(tr),np.array(te)
print(f"Split em {corte} (RR{RR}, modo risk, expectancy liquida)\n")
for sig in ["A9","A1","A2","A6"]:
    tr,te=run(sig)
    print(f"{sig}:")
    for nome,a in (("treino",tr),("teste ",te)):
        if len(a)==0: print(f"   {nome}: 0 trades"); continue
        print(f"   {nome}: n={len(a)} WR={(a>0).mean():.0%} exp={a.mean():+.2f}R soma={a.sum():+.0f}R")
    print()
