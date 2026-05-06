"""
Koda Temple â Resource Oracle Data Fetcher
==========================================
Pulls live Otherdeed floor prices for ALL traits from the OpenSea v2 API.
Scans cheapest N listings, looks up each token's traits, builds floor map.

HOW TO RUN:
  OPENSEA_API_KEY=your_key_here python koda_temple_data.py

pip install requests
"""
import json,os,sys,time
from datetime import datetime,timezone
try:
    import requests
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable,"-m","pip","install","requests"])
    import requests

COLLECTION_SLUG="otherdeed"
CONTRACT="0x34d85c9CDeB23FA97cb08333b511ac86E1C4E258"
OPENSEA_API="https://api.opensea.io/api/v2"
COINGECKO="https://api.coingecko.com/api/v3"
OPENSEA_KEY=os.environ.get("OPENSEA_API_KEY","")
SNAPSHOT_DIR="."
REQUEST_DELAY=0.6
SCAN_LISTINGS=200

def hdrs():
    h={"accept":"application/json"}
    if OPENSEA_KEY: h["X-API-KEY"]=OPENSEA_KEY
    return h

def wei(v,d=18):
    try: return int(v)/(10**d)
    except: return None

def eth_price():
    try:
        r=requests.get(f"{COINGECKO}/simple/price",params={"ids":"ethereum","vs_currencies":"usd"},timeout=10)
        return r.json().get("ethereum",{}).get("usd")
    except Exception as e:
        print(f"  [warn] ETH price: {e}"); return None

def col_stats():
    try:
        r=requests.get(f"{OPENSEA_API}/collections/{COLLECTION_SLUG}/stats",headers=hdrs(),timeout=15)
        if not r.ok: print(f"  [warn] stats {r.status_code}"); return {}
        d=r.json(); tot=d.get("total",{})
        v24=v7=None
        for iv in d.get("intervals",[]):
            if iv.get("interval")=="one_day": v24=iv.get("volume")
            elif iv.get("interval")=="seven_day": v7=iv.get("volume")
        return {"floor_eth":tot.get("floor_price"),"volume_24h":v24,"volume_7d":v7}
    except Exception as e:
        print(f"  [warn] col stats: {e}"); return {}

def cheapest(limit=200):
    results=[]; cur=None
    while len(results)<limit:
        params={"limit":50}
        if cur: params["next"]=cur
        try:
            r=requests.get(f"{OPENSEA_API}/listings/collection/{COLLECTION_SLUG}/best",headers=hdrs(),params=params,timeout=20)
            if not r.ok: print(f"  [warn] listings {r.status_code}"); break
            d=r.json()
            for lst in d.get("listings",[]):
                offer=lst.get("protocol_data",{}).get("parameters",{}).get("offer",[{}])
                tid=offer[0].get("identifierOrCriteria") if offer else None
                pi=lst.get("price",{}).get("current",{})
                p=wei(pi.get("value"),pi.get("decimals",18))
                if tid and p is not None: results.append((tid,p))
            cur=d.get("next")
            if not d.get("listings") or not cur: break
        except Exception as e:
            print(f"  [warn] listings error: {e}"); break
        time.sleep(REQUEST_DELAY)
    return results[:limit]

def traits(tid):
    try:
        r=requests.get(f"{OPENSEA_API}/chain/ethereum/contract/{CONTRACT}/nfts/{tid}",headers=hdrs(),timeout=15)
        if not r.ok: return []
        return r.json().get("nft",{}).get("traits",[])
    except: return []

def scan():
    print(f"\n  Scanning {SCAN_LISTINGS} cheapest listings for ALL trait floors...")
    ls=cheapest(SCAN_LISTINGS)
    print(f"  Retrieved {len(ls)} listings")
    fl={}
    for i,(tid,p) in enumerate(ls):
        if i%25==0: print(f"  Fetching traits {i}/{len(ls)} ...")
        for t in traits(tid):
            tt=t.get("trait_type",""); tv=str(t.get("value",""))
            if tt and tv:
                fl.setdefault(tt,{})
                if tv not in fl[tt]: fl[tt][tv]=p
        time.sleep(REQUEST_DELAY)
    print(f"  Trait types found: {', '.join(sorted(fl.keys()))}")
    return fl

def build():
    if not OPENSEA_KEY: print("\n  WARNING: No OPENSEA_API_KEY set.")
    sn={"fetched_at":datetime.now(timezone.utc).isoformat(),"eth_usd":None,
        "collection":{},"resources":{},"environments":{},"sediments":{},
        "artifact":{},"raw_traits":{}}

    print("\n  Fetching ETH/USD...")
    sn["eth_usd"]=eth_price()
    if sn["eth_usd"]: print(f"  ETH/USD: ${sn['eth_usd']:,.0f}")

    print("\n  Fetching collection stats...")
    sn["collection"]=col_stats()
    cf=sn["collection"].get("floor_eth")
    if cf: print(f"  Floor: {cf:.4f} ETH")

    f=scan()
    # Store the full raw trait floor map (all trait types and values)
    sn["raw_traits"]=f

    # Also keep structured summaries for backwards compat
    print("\n  ââ Resource Tier ââ")
    for t in [3,2,1]:
        v=f.get("Resource Tier",{}).get(str(t))
        print(f"  T{t}: {f'{v:.4f} ETH' if v else 'n/a'}")
        sn["resources"][f"tier_{t}"]={"floor":v}

    print("\n  ââ Environment Tier ââ")
    for t in [5,4,3,2,1]:
        v=f.get("Environment Tier",{}).get(str(t))
        print(f"  T{t}: {f'{v:.4f} ETH' if v else 'n/a'}")
        sn["environments"][f"tier_{t}"]={"floor":v}

    print("\n  ââ Sediment Tier ââ")
    for t in [3,2,1]:
        v=f.get("Sediment Tier",{}).get(str(t))
        print(f"  T{t}: {f'{v:.4f} ETH' if v else 'n/a'}")
        sn["sediments"][f"tier_{t}"]={"floor":v}

    print("\n  ââ Artifact ââ")
    art=min([v for k,v in f.get("Artifact",{}).items() if k and k.lower() not in("","none","null")],default=None)
    sn["artifact"]={"floor":art}
    if art: print(f"  Floor: {art:.4f} ETH")

    # Print all other trait types for reference
    skip={"Resource Tier","Environment Tier","Sediment Tier","Artifact"}
    print("\n  ââ All other trait types ââ")
    for tt in sorted(f.keys()):
        if tt in skip: continue
        vals=sorted(f[tt].items(),key=lambda x:x[1])
        print(f"  {tt}: {len(vals)} values, cheapest={vals[0][1]:.4f} ETH ({vals[0][0]})" if vals else f"  {tt}: empty")

    return sn

def save(sn):
    path=os.path.join(SNAPSHOT_DIR,"price_snapshot_latest.json")
    with open(path,"w") as f: json.dump(sn,f,indent=2)
    print(f"\n  Saved -> {path}")
    return path

if __name__=="__main__":
    print("="*60)
    print("  Koda Temple -- Resource Oracle")
    print("="*60)
    save(build())
    print("\n  Done.")
