import pandas as pd, numpy as np
from smc_engine.setup_state import compute_setup_state, SetupConfig
df0 = pd.read_parquet("user_data/diag_df.parquet")
df0 = df0[[c for c in df0.columns if not c.startswith("setup_")]].copy().reset_index(drop=True)
hi=df0["high"].to_numpy(float); lo=df0["low"].to_numpy(float); cl=df0["close"].to_numpy(float)
n=len(df0); FEE,SLIP,HORIZON=0.0005,0.0002,96; RRS=[1.5,2.0,3.0]
SIGS=["A1","A2","A3","A4a","A5","A6","A7","A9","A10"]
def pnl(idx,dirs,zlo,zhi,rr):
    liq=[]; bru=[]; rp=[]; last=-1
    for k,i in enumerate(idx):
        if i<=last or i>=n-1: continue
        d=dirs[k]
        if d not in ("long","short"): continue
        e=cl[i]; sl=zlo[k] if d=="long" else zhi[k]
        if not np.isfinite(sl): continue
        if d=="long" and not sl<e: continue
        if d=="short" and not sl>e: continue
        risk=e-sl if d=="long" else sl-e
        if risk<=0: continue
        tp=e+rr*risk if d=="long" else e-rr*risk
        res=None; xi=min(i+HORIZON,n-1)
        for j in range(i+1,min(i+1+HORIZON,n)):
            if d=="long":
                if lo[j]<=sl: res=-1.0; xi=j; break
                if hi[j]>=tp: res=rr; xi=j; break
            else:
                if hi[j]>=sl: res=-1.0; xi=j; break
                if lo[j]<=tp: res=rr; xi=j; break
        if res is None: res=(cl[xi]-e)/risk if d=="long" else (e-cl[xi])/risk
        cost=e*(2*FEE+SLIP)/risk
        bru.append(res); liq.append(res-cost); rp.append(risk/e); last=xi
    return np.array(liq),np.array(bru),np.array(rp)
for sig in SIGS:
    try:
        o=compute_setup_state(df0.copy(),SetupConfig(signature=sig,entry_mode="risk",trend_suffix="4h",zone_suffix="1h"))
    except Exception as ex:
        print(f"{sig}: ERRO -> {ex}\n"); continue
    conf=(o["setup_state"]=="CONFIRMED").fillna(False).to_numpy(bool)
    trans=conf&~np.r_[False,conf[:-1]]; idx=np.where(trans)[0]
    if len(idx)==0: print(f"{sig}: 0 entradas\n"); continue
    dr=o["setup_direction"].astype("string").fillna("").to_numpy()
    zl=o["setup_zone_low"].to_numpy(float); zh=o["setup_zone_high"].to_numpy(float)
    dirs=[dr[i] for i in idx]; zlo=[zl[i] for i in idx]; zhi=[zh[i] for i in idx]
    print(f"{sig}: {len(idx)} entradas (long={dirs.count('long')} short={dirs.count('short')})")
    for rr in RRS:
        liq,bru,rp=pnl(idx,dirs,zlo,zhi,rr)
        if len(liq)==0: print(f"   RR{rr}: 0 validos"); continue
        wr=(bru>0).mean()
        pf=liq[liq>0].sum()/(-liq[liq<0].sum()) if (liq<0).any() else float("inf")
        print(f"   RR{rr}: n={len(liq)} WR={wr:.0%} bruto={bru.mean():+.2f}R liq={liq.mean():+.2f}R risco_zona={rp.mean()*100:.2f}% PF={pf:.2f}")
    print()
