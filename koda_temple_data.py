import json, os, sys, time
from datetime import datetime, timezone
try:
    import requests
except ImportError:
    import subprocess; subprocess.check_call([sys.executable,"-m","pip","install","requests"]); import requests

COLLECTION_SLUG = "otherdeed"
CONTRACT = "0x34d85c9CDeB23FA97cb08333b511ac86E1C4E258"
OPENSEA_API = "https://api.opensea.io/api/v2"
COINGECKO = "https://api.coingecko.com/api/v3"
OPENSEA_KEY = os.environ.get("OPENSEA_API_KEY", "")
SNAPSHOT_DIR = "."
REQUEST_DELAY = 0.6
SCAN_LISTINGS = 200

def hdr():
    h = {"accept": "application/json"}
    if OPENSEA_KEY: h["X-API-KEY"] = OPENSEA_KEY
    return h

def from_wei(v, d=18):
    try: return int(v) / (10**d)
    except: return None

def eth_price():
    try: return requests.get(f"{COINGECKO}/simple/price", params={"ids":"ethereum","vs_currencies":"usd"}, timeout=10).json().get("ethereum",{}).get("usd")
    except: return None

def coll_stats():
    try:
        r = requests.get(f"{OPENSEA_API}/collections/{COLLECTION_SLUG}/stats", headers=hdr(), timeout=15)
        if not r.ok: return {}
        d = r.json(); tot = d.get("total",{}); v24=v7=None
        for iv in d.get("intervals",[]):
            if iv.get("interval")=="one_day": v24=iv.get("volume")
            elif iv.get("interval")=="seven_day": v7=iv.get("volume")
        return {"floor_eth":tot.get("floor_price"),"volume_24h":v24,"volume_7d":v7}
    except: return {}

def cheapest(limit=200):
    res=[]; cur=None
    while len(res)<limit:
        p={"limit":50}
        if cur: p["next"]=cur
        try:
            r=requests.get(f"{OPENSEA_API}/listings/collection/{COLLECTION_SLUG}/best",headers=hdr(),params=p,timeout=20)
            if not r.ok: break
            d=r.json()
            for l in d.get("listings",[]):
                of=l.get("protocol_data",{}).get("parameters",{}).get("offer",[{}])
                tid=of[0].get("identifierOrCriteria") if of else None
                pi=l.get("price",{}).get("current",{})
                pr=from_wei(pi.get("value"),pi.get("decimals",18))
                if tid and pr is not None: res.append((tid,pr))
            cur=d.get("next")
            if not d.get("listings") or not cur: break
        except: break
        time.sleep(REQUEST_DELAY)
    return res[:limit]

def traits(tid):
    try:
        r=requests.get(f"{OPENSEA_API}/chain/ethereum/contract/{CONTRACT}/nfts/{tid}",headers=hdr(),timeout=15)
        return r.json().get("nft",{}).get("traits",[]) if r.ok else []
    except: return []

def scan():
    print(f"Scanning {SCAN_LISTINGS} listings...")
    ls=cheapest(SCAN_LISTINGS); print(f"Got {len(ls)}")
    fl={}
    for i,(tid,p) in enumerate(ls):
        if i%25==0: print(f"{i}/{len(ls)}")
        for t in traits(tid):
            tt=t.get("trait_type",""); tv=str(t.get("value",""))
            if tt and tv:
                fl.setdefault(tt,{})
                if tv not in fl[tt]: fl[tt][tv]=p
        time.sleep(REQUEST_DELAY)
    print(f"Trait keys: {list(fl.keys())}")
    return fl

if __name__=="__main__":
    sn={"fetched_at":datetime.now(timezone.utc).isoformat(),"eth_usd":None,"collection":{},"resources":{},"environments":{},"sediments":{},"artifact":{}}
    sn["eth_usd"]=eth_price(); eth=sn["eth_usd"]
    st=coll_stats(); sn["collection"]=st; floor=st.get("floor_eth")
    print(f"ETH/USD: {eth}  Floor: {floor}")
    f=scan()
    for t in [3,2,1]:
        v=f.get("Resource Tier",{}).get(str(t)); print(f"Resource T{t}: {v}")
        sn["resources"][f"tier_{t}"]={"floor":v}
    for t in [5,4,3,2,1]:
        v=f.get("Environment Tier",{}).get(str(t)); print(f"Env T{t}: {v}")
        sn["environments"][f"tier_{t}"]={"floor":v}
    for t in [3,2,1]:
        v=f.get("Sediment Tier",{}).get(str(t)); print(f"Sed T{t}: {v}")
        sn["sediments"][f"tier_{t}"]={"floor":v}
    art=min([v for k,v in f.get("Artifact",{}).items() if k and k.lower() not in("","none","null")],default=None)
    sn["artifact"]={"floor":art}; print(f"Artifact: {art}")
    open("./price_snapshot_latest.json","w").write(json.dumps(sn,indent=2))
    print("Done.")
