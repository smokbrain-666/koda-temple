"""
Koda Temple — Resource Oracle Data Fetcher
==========================================
Pulls live floor prices for ALL traits from the OpenSea v2 API.
Covers two collections: Otherdeed for Otherside + Otherdeed Expanded.
Paginates through ALL active listings per collection.

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

OPENSEA_API="https://api.opensea.io/api/v2"
COINGECKO="https://api.coingecko.com/api/v3"
OPENSEA_KEY=os.environ.get("OPENSEA_API_KEY","")
SNAPSHOT_DIR="."
REQUEST_DELAY=0.6

COLLECTIONS=[
  {
    "key":"otherdeed",
    "label":"Otherdeed for Otherside",
    "slug":"otherdeed",
    "contract":"0x34d85c9CDeB23FA97cb08333b511ac86E1C4E258",
  },
  {
    "key":"expanded",
    "label":"Otherdeed Expanded",
    "slug":"otherdeed-expanded",
    "contract":"0x790B2cF29Ed4F310bf7641f013C65D4560d28371",
  },
]

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
  except Exception as e: print(f"  [warn] ETH price: {e}"); return None

def col_stats(slug):
  try:
    r=requests.get(f"{OPENSEA_API}/collections/{slug}/stats",headers=hdrs(),timeout=15)
    if not r.ok: print(f"  [warn] stats {r.status_code}"); return {}
    d=r.json(); tot=d.get("total",{})
    v24=v7=None
    for iv in d.get("intervals",[]):
      if iv.get("interval")=="one_day": v24=iv.get("volume")
      elif iv.get("interval")=="seven_day": v7=iv.get("volume")
    return {"floor_eth":tot.get("floor_price"),"volume_24h":v24,"volume_7d":v7}
  except Exception as e: print(f"  [warn] col stats: {e}"); return {}

def cheapest(slug):
  """Paginate all active listings for a collection."""
  results=[]; cur=None
  while True:
    params={"limit":50}
    if cur: params["next"]=cur
    try:
      r=requests.get(f"{OPENSEA_API}/listings/collection/{slug}/best",headers=hdrs(),params=params,timeout=20)
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
    except Exception as e: print(f"  [warn] listings error: {e}"); break
    time.sleep(REQUEST_DELAY)
  return results

def traits(contract,tid):
  try:
    r=requests.get(f"{OPENSEA_API}/chain/ethereum/contract/{contract}/nfts/{tid}",headers=hdrs(),timeout=15)
    if not r.ok: return []
    return r.json().get("nft",{}).get("traits",[])
  except: return []

def scan_collection(col):
  slug=col["slug"]; contract=col["contract"]; label=col["label"]
  print(f"\n  [{label}] Scanning all active listings...")
  ls=cheapest(slug)
  print(f"  [{label}] Retrieved {len(ls)} listings")
  fl={}
  for i,(tid,p) in enumerate(ls):
    if i%25==0: print(f"  [{label}] Fetching traits {i}/{len(ls)} ...")
    for t in traits(contract,tid):
      tt=t.get("trait_type",""); tv=str(t.get("value",""))
      if tt and tv:
        fl.setdefault(tt,{})
        if tv not in fl[tt]: fl[tt][tv]=p
    time.sleep(REQUEST_DELAY)
  print(f"  [{label}] Trait types: {', '.join(sorted(fl.keys()))}")
  return fl

def build():
  if not OPENSEA_KEY: print("\n  WARNING: No OPENSEA_API_KEY set.")
  sn={"fetched_at":datetime.now(timezone.utc).isoformat(),"eth_usd":None}
  print("\n  Fetching ETH/USD...")
  sn["eth_usd"]=eth_price()
  if sn["eth_usd"]: print(f"  ETH/USD: ${sn['eth_usd']:,.0f}")
  for col in COLLECTIONS:
    key=col["key"]; slug=col["slug"]
    print(f"\n  Fetching stats for {col['label']}...")
    stats=col_stats(slug)
    if stats.get("floor_eth"): print(f"  Floor: {stats['floor_eth']:.4f} ETH")
    raw=scan_collection(col)
    sn[key]={"collection":stats,"raw_traits":raw}
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
