import os, time, json, requests
from datetime import datetime, timezone, timedelta

COLLECTIONS = [
    {"key": "otherdeed", "label": "Otherdeed for Otherside", "slug": "otherdeed",
     "contract": "0x34d85c9CDeB23FA97cb08333b511ac86E1C4E258", "chain": "ethereum"},
    {"key": "expanded",  "label": "Otherdeed Expanded",      "slug": "otherdeed-expanded",
     "contract": "0x790B2cF29Ed4F310bf7641f013C65D4560d28371", "chain": "apechain"},
]

OPENSEA_API          = "https://api.opensea.io/api/v2"
COINGECKO            = "https://api.coingecko.com/api/v3"
OPENSEA_KEY          = os.environ.get("OPENSEA_API_KEY", "")
SNAPSHOT_DIR         = "."
REQUEST_DELAY        = 0.8          # seconds between normal requests
INTER_COL_DELAY      = 45           # seconds to wait between collections
RETRY_DELAYS         = [5, 15, 30]  # backoff on 429
MAX_TRAIT_LOOKUPS    = 100          # max trait lookups per collection (cheapest first)
DIRECTIONS           = ["Western", "Northern", "Eastern", "Southern"]

HDR = {"accept": "application/json", "x-api-key": OPENSEA_KEY}


def get_json(url, params=None, label=""):
    """GET with automatic 429 retry and backoff."""
    for attempt, wait in enumerate([0] + RETRY_DELAYS):
        if wait:
            print(f"  {label} 429 -- waiting {wait}s (attempt {attempt})...", flush=True)
            time.sleep(wait)
        try:
            r = requests.get(url, headers=HDR, params=params, timeout=20)
            if r.status_code == 429:
                continue   # retry
            return r.status_code, r.json()
        except Exception as e:
            print(f"  {label} exception: {e}", flush=True)
            return 0, {}
    print(f"  {label} gave up after retries", flush=True)
    return 429, {}


def eth_usd():
    try:
        r = requests.get(f"{COINGECKO}/simple/price?ids=ethereum&vs_currencies=usd", timeout=10)
        return r.json()["ethereum"]["usd"]
    except Exception:
        return None


def col_stats(slug):
    try:
        r = requests.get(f"{OPENSEA_API}/collections/{slug}/stats", headers=HDR, timeout=15)
        d = r.json()
        total = d.get("total", {})
        return {
            "floor_eth":  total.get("floor_price"),
            "volume_eth": total.get("volume"),
            "num_owners": total.get("num_owners"),
            "listed":     total.get("listed_count"),
        }
    except Exception:
        return {}


def cheapest(slug):
    """Paginate ALL active listings -- 429-safe."""
    results = []
    cur = None
    page_num = 0
    while True:
        params = {"limit": 50}
        if cur:
            params["next"] = cur
        status, d = get_json(
            f"{OPENSEA_API}/listings/collection/{slug}/best",
            params=params,
            label=f"[{slug}] page {page_num}"
        )
        listings = d.get("listings", [])
        print(f"  [{slug}] page {page_num}: HTTP {status}, {len(listings)} listings, keys={list(d.keys())}", flush=True)
        for lst in listings:
            offer = lst.get("protocol_data", {}).get("parameters", {}).get("offer", [{}])
            tid   = offer[0].get("identifierOrCriteria") if offer else None
            price_data = lst.get("price", {}).get("current", {})
            decimals   = int(price_data.get("decimals", 18))
            value      = int(price_data.get("value", 0))
            p = value / (10 ** decimals)
            if tid:
                results.append((tid, p))
        cur = d.get("next")
        time.sleep(REQUEST_DELAY)
        page_num += 1
        if not listings or not cur:
            break
    print(f"  [{slug}] total: {len(results)} listings fetched", flush=True)
    return results


def get_traits(contract, tid, chain="ethereum"):
    url = f"{OPENSEA_API}/chain/{chain}/contract/{contract}/nfts/{tid}"
    status, d = get_json(url, label=f"traits({chain},{tid[:8]})")
    traits = d.get("nft", {}).get("traits", [])
    if status != 200 or not traits:
        print(f"  get_traits: HTTP {status}, traits={len(traits)}, keys={list(d.keys())[:4]}", flush=True)
    return traits


def scan_collection(col):
    """Returns raw_traits and resource_floors."""
    slug     = col["slug"]
    contract = col["contract"]
    chain    = col.get("chain", "ethereum")
    print(f"[{col['key']}] scanning listings (chain={chain})...", flush=True)
    ls = cheapest(slug)

    raw        = {}   # trait_type -> {value: floor_price}
    res_floors = {}   # direction  -> {resource_name: {tier: floor_price}}

    for _i, (tid, p) in enumerate(ls[:MAX_TRAIT_LOOKUPS]):
        tlist = get_traits(contract, tid, chain)
        time.sleep(REQUEST_DELAY)

        token_traits = {}
        for t in tlist:
            tt = t.get("trait_type", "")
            tv = str(t.get("value", ""))
            if tt and tv:
                token_traits[tt] = tv
                raw.setdefault(tt, {})
                if tv not in raw[tt]:
                    raw[tt][tv] = p   # first = cheapest

        for d in DIRECTIONS:
            res_name = token_traits.get(f"{d} Resource")
            res_tier = token_traits.get(f"{d} Resource Tier")
            if res_name and res_tier:
                res_floors.setdefault(d, {})
                res_floors[d].setdefault(res_name, {})
                if res_tier not in res_floors[d][res_name]:
                    res_floors[d][res_name][res_tier] = p

    return raw, res_floors


def scan_sales(col, days=10):
    """Fetch last 10 days of sales; return sales_traits and resource_sales."""
    slug     = col["slug"]
    contract = col["contract"]
    chain    = col.get("chain", "ethereum")
    cutoff   = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp())

    token_last_sale = {}
    cur = None
    page = 0
    while True:
        params = {"event_type": "sale", "occurred_after": cutoff, "limit": 50}
        if cur:
            params["next"] = cur
        status, d = get_json(
            f"{OPENSEA_API}/events/collection/{slug}",
            params=params,
            label=f"[{slug}] sales page {page}"
        )
        events = d.get("asset_events", [])
        for ev in events:
            nft      = ev.get("nft", {})
            tid      = str(nft.get("identifier", ""))
            ts       = ev.get("event_timestamp", 0)
            payment  = ev.get("payment", {})
            decimals = int(payment.get("decimals", 18))
            quantity = int(ev.get("quantity", 1) or 1)
            total_val = int(payment.get("quantity", 0))
            price_eth = (total_val / quantity) / (10 ** decimals) if quantity else 0
            if tid and (tid not in token_last_sale or ts > token_last_sale[tid]["ts"]):
                token_last_sale[tid] = {"price_eth": round(price_eth, 6), "ts": ts}
        cur = d.get("next")
        time.sleep(REQUEST_DELAY)
        page += 1
        if not events or not cur:
            break

    sales_traits   = {}
    resource_sales = {}

    for tid, sale in token_last_sale.items():
        tlist = get_traits(contract, tid, chain)
        time.sleep(REQUEST_DELAY)
        token_traits = {}
        for t in tlist:
            tt = t.get("trait_type", "")
            tv = str(t.get("value", ""))
            if tt and tv:
                token_traits[tt] = tv
                sales_traits.setdefault(tt, {})
                existing = sales_traits[tt].get(tv)
                if not existing or sale["ts"] > existing["ts"]:
                    sales_traits[tt][tv] = {"price_eth": sale["price_eth"], "ts": sale["ts"]}
        for d in DIRECTIONS:
            res_name = token_traits.get(f"{d} Resource")
            res_tier = token_traits.get(f"{d} Resource Tier")
            if res_name and res_tier:
                resource_sales.setdefault(d, {})
                resource_sales[d].setdefault(res_name, {})
                existing = resource_sales[d][res_name].get(res_tier)
                if not existing or sale["ts"] > existing["ts"]:
                    resource_sales[d][res_name][res_tier] = {
                        "price_eth": sale["price_eth"], "ts": sale["ts"]
                    }

    return sales_traits, resource_sales


def build():
    sn = {
        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
        "eth_usd":    eth_usd(),
    }
    for i, col in enumerate(COLLECTIONS):
        if i > 0:
            print(f"--- inter-collection cooldown {INTER_COL_DELAY}s ---", flush=True)
            time.sleep(INTER_COL_DELAY)
        stats                   = col_stats(col["slug"])
        raw, res_floors         = scan_collection(col)
        sales_traits, res_sales = scan_sales(col)
        sn[col["key"]] = {
            "collection":      stats,
            "raw_traits":      raw,
            "resource_floors": res_floors,
            "sales_traits":    sales_traits,
            "resource_sales":  res_sales,
        }
    return sn


if __name__ == "__main__":
    snap = build()
    path = os.path.join(SNAPSHOT_DIR, "price_snapshot_latest.json")
    with open(path, "w") as f:
        json.dump(snap, f, indent=2)
    print(f"Saved {path} -- {snap['fetched_at']}")
