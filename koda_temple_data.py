"""
Koda Temple â Resource Oracle Data Fetcher
==========================================
Pulls live Otherdeed floor prices by resource type, tier,
sediment, and artifact presence from the OpenSea v2 API.

NOTE: Reservoir shut down their API on Oct 15 2025.
      This script now uses OpenSea v2.

HOW TO RUN (no technical knowledge needed):
  1. Get a FREE OpenSea API key at: https://docs.opensea.io/reference/api-keys
  2. Open Terminal (Mac) or Command Prompt (Windows)
  3. Run:  OPENSEA_API_KEY=your_key_here  python koda_temple_data.py
     (On Windows:  set OPENSEA_API_KEY=your_key_here && python koda_temple_data.py)
  4. It will print current prices and save a snapshot file

For GitHub Actions, add OPENSEA_API_KEY as a repository secret.

To install the one required library:
  pip install requests
"""

import json
import os
import sys
import time
from datetime import datetime, timezone

try:
    import requests
except ImportError:
    print("Installing 'requests' library...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests"])
    import requests

# âââââââââââââââââââââââââââââââââââââââââââââ
#  Configuration
# âââââââââââââââââââââââââââââââââââââââââââââ

COLLECTION_SLUG  = "otherdeed"
OPENSEA_API      = "https://api.opensea.io/api/v2"
COINGECKO        = "https://api.coingecko.com/api/v3"
OPENSEA_KEY      = os.environ.get("OPENSEA_API_KEY", "")
SNAPSHOT_DIR     = "."
REQUEST_DELAY    = 0.5  # seconds between API calls

RESOURCES = ["Anima", "Ore", "Shard", "Root"]
RESOURCE_DESCRIPTIONS = {
    "Anima": "Research & mystical energy",
    "Ore":   "Metal & industrial power",
    "Shard": "Stone & crystalline matter",
    "Root":  "Wood & organic growth",
}

SEDIMENTS = [
    "Biogenic Swamp",
    "Chemical Goo",
    "Rainbow Atmos",
    "Cosmic Dream",
    "Infinite Expanse",
]

# âââââââââââââââââââââââââââââââââââââââââââââ
#  Helpers
# âââââââââââââââââââââââââââââââââââââââââââââ

def headers():
    h = {"accept": "application/json"}
    if OPENSEA_KEY:
        h["X-API-KEY"] = OPENSEA_KEY
    return h

def eth_from_unit(unit_str):
    """Convert a string like '0.45' to float."""
    try:
        return float(unit_str)
    except (TypeError, ValueError):
        return None

def eth_from_wei(value_str, decimals=18):
    """Convert wei string to ETH float."""
    try:
        return int(value_str) / (10 ** decimals)
    except (TypeError, ValueError):
        return None

# âââââââââââââââââââââââââââââââââââââââââââââ
#  Data fetching
# âââââââââââââââââââââââââââââââââââââââââââââ

def get_eth_price():
    """Fetch current ETH/USD price from CoinGecko (no key needed)."""
    try:
        r = requests.get(
            f"{COINGECKO}/simple/price",
            params={"ids": "ethereum", "vs_currencies": "usd"},
            timeout=10,
        )
        return r.json().get("ethereum", {}).get("usd")
    except Exception as e:
        print(f"  [warn] Could not fetch ETH price: {e}")
        return None


def get_collection_stats():
    """Fetch overall collection floor and volume from OpenSea."""
    try:
        r = requests.get(
            f"{OPENSEA_API}/collections/{COLLECTION_SLUG}/stats",
            headers=headers(),
            timeout=15,
        )
        if not r.ok:
            print(f"  [warn] Collection stats returned HTTP {r.status_code}: {r.text[:200]}")
            return {}
        data = r.json()
        total = data.get("total", {})

        vol_24h = vol_7d = None
        for iv in data.get("intervals", []):
            if iv.get("interval") == "one_day":
                vol_24h = iv.get("volume")
            elif iv.get("interval") == "seven_day":
                vol_7d = iv.get("volume")

        return {
            "floor_eth":     total.get("floor_price"),
            "volume_24h":    vol_24h,
            "volume_7d":     vol_7d,
            "on_sale_count": None,
            "total_supply":  total.get("count"),
        }
    except Exception as e:
        print(f"  [warn] Could not fetch collection stats: {e}")
        return {}


def get_all_trait_floors():
    """
    Fetch ALL trait floors for the collection in a single OpenSea call.
    Returns: {trait_type: {trait_value: {"floor": float|None, "listed": int|None}}}

    OpenSea v2 /traits/{slug} response shape:
      { "categories": { "Anima": { "type": "string",
           "values": [ { "value": "3", "floor": {"unit": "0.45"}, "listing_count": 5 } ] } } }
    """
    try:
        r = requests.get(
            f"{OPENSEA_API}/traits/{COLLECTION_SLUG}",
            headers=headers(),
            timeout=20,
        )
        if not r.ok:
            print(f"  [warn] Traits endpoint returned HTTP {r.status_code}: {r.text[:200]}")
            return {}

        data = r.json()
        categories = data.get("categories", {})

        result = {}
        for trait_type, cat_data in categories.items():
            result[trait_type] = {}
            values = cat_data.get("values", []) if isinstance(cat_data, dict) else []
            for v in values:
                val_str = str(v.get("value", ""))
                floor_info = v.get("floor") or {}
                floor_eth = eth_from_unit(floor_info.get("unit"))
                result[trait_type][val_str] = {
                    "floor":  floor_eth,
                    "listed": v.get("listing_count"),
                }
        return result

    except Exception as e:
        print(f"  [warn] Could not fetch traits: {e}")
        return {}


def get_trait_floor_from_listings(trait_type, trait_value):
    """
    Fallback per-trait query using best listings endpoint.
    Slower (one request per trait) but works if /traits/ doesn't include floors.
    """
    try:
        r = requests.get(
            f"{OPENSEA_API}/listings/collection/{COLLECTION_SLUG}/best",
            params={"trait_type": trait_type, "trait_value": str(trait_value), "limit": 1},
            headers=headers(),
            timeout=15,
        )
        if not r.ok:
            return {"floor": None, "listed": None}

        listings = r.json().get("listings", [])
        if not listings:
            return {"floor": None, "listed": None}

        price_data = listings[0].get("price", {}).get("current", {})
        floor_eth = eth_from_wei(
            price_data.get("value"),
            price_data.get("decimals", 18),
        )
        return {"floor": floor_eth, "listed": None}

    except Exception as e:
        print(f"  [warn] {trait_type}={trait_value} listings: {e}")
        return {"floor": None, "listed": None}


def lookup_trait(all_traits, trait_type, trait_value, use_fallback=True):
    """
    Look up a trait floor from the bulk traits dict.
    Falls back to a per-listing query if the trait isn't in the bulk data
    or if its floor is None.
    """
    info = all_traits.get(trait_type, {}).get(str(trait_value))
    if info and info.get("floor") is not None:
        return info

    if use_fallback:
        time.sleep(REQUEST_DELAY)
        return get_trait_floor_from_listings(trait_type, trait_value)

    return {"floor": None, "listed": None}

# âââââââââââââââââââââââââââââââââââââââââââââ
#  Build the full market snapshot
# âââââââââââââââââââââââââââââââââââââââââââââ

def build_snapshot():
    if not OPENSEA_KEY:
        print("\n  â ï¸  No OPENSEA_API_KEY set. Data will be limited.")
        print("     Get a free key at: https://docs.opensea.io/reference/api-keys\n")

    snapshot = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "eth_usd":    None,
        "collection": {},
        "resources":  {},
        "sediments":  {},
        "artifact":   {},
    }

    print("\nð® Koda Temple â Resource Oracle")
    print("=" * 46)

    # ETH price
    print("\n  Fetching ETH priceâ¦")
    snapshot["eth_usd"] = get_eth_price()
    eth = snapshot["eth_usd"]
    if eth:
        print(f"  ETH/USD: ${eth:,.0f}")

    # Collection stats
    print("\n  Fetching collection statsâ¦")
    stats = get_collection_stats()
    snapshot["collection"] = stats
    floor = stats.get("floor_eth")
    if floor:
        usd = f"  (~${floor * eth:,.0f})" if eth else ""
        print(f"  Collection floor: {floor:.4f} ETH{usd}")
    if stats.get("volume_24h"):
        print(f"  24h volume: {stats['volume_24h']:.1f} ETH")
    time.sleep(REQUEST_DELAY)

    # Fetch ALL trait floors in one call
    print("\n  Fetching trait floorsâ¦")
    all_traits = get_all_trait_floors()
    has_traits = bool(all_traits)
    if has_traits:
        print(f"  Trait categories loaded: {', '.join(all_traits.keys())}")
    else:
        print("  [warn] Trait bulk fetch failed â will query per-trait via listings")
    time.sleep(REQUEST_DELAY)

    # Resources by tier
    print("\n  ââ Resource Floors ââ")
    for resource in RESOURCES:
        snapshot["resources"][resource] = {}
        print(f"\n  {resource.upper()} ({RESOURCE_DESCRIPTIONS[resource]})")
        for tier in [3, 2, 1]:
            result = lookup_trait(all_traits, resource, str(tier))
            snapshot["resources"][resource][f"tier_{tier}"] = result
            floor_str = f"{result['floor']:.4f} ETH" if result["floor"] else "no data"
            count_str = f"({result['listed']} listed)" if result.get("listed") else ""
            label = ["â", "â", "â²"][3 - tier]
            print(f"    {label} Tier {tier}: {floor_str}  {count_str}")

    # Sediments
    print("\n  ââ Sediment Floors ââ")
    for sediment in SEDIMENTS:
        result = lookup_trait(all_traits, "Sediment", sediment)
        snapshot["sediments"][sediment] = result
        floor_str = f"{result['floor']:.4f} ETH" if result["floor"] else "no data"
        print(f"  {sediment}: {floor_str}")

    # Artifacts
    print("\n  ââ Artifact Premium ââ")
    art = lookup_trait(all_traits, "Artifact", "Yes")
    snapshot["artifact"] = art
    base_floor = snapshot["collection"].get("floor_eth")
    if art["floor"]:
        print(f"  With artifact floor: {art['floor']:.4f} ETH")
        if base_floor and base_floor > 0:
            premium = ((art["floor"] - base_floor) / base_floor) * 100
            print(f"  Premium vs. base floor: +{premium:.1f}%")
    if art.get("listed"):
        print(f"  Artifact deeds listed: {art['listed']}")

    return snapshot

# âââââââââââââââââââââââââââââââââââââââââââââ
#  Save snapshot to JSON
# âââââââââââââââââââââââââââââââââââââââââââââ

def save_snapshot(snapshot):
    date_str = datetime.now().strftime("%Y-%m-%d")
    filename = f"price_snapshot_{date_str}.json"
    with open(filename, "w") as f:
        json.dump(snapshot, f, indent=2)
    with open("price_snapshot_latest.json", "w") as f:
        json.dump(snapshot, f, indent=2)
    print(f"\n  â Snapshot saved: {filename}")
    print(f"  â Latest updated: price_snapshot_latest.json")
    return filename

# âââââââââââââââââââââââââââââââââââââââââââââ
#  Summary table
# âââââââââââââââââââââââââââââââââââââââââââââ

def print_summary(snapshot):
    eth = snapshot.get("eth_usd")
    print("\n" + "=" * 46)
    print("  RESOURCE ORACLE SUMMARY")
    print("=" * 46)

    for resource in RESOURCES:
        tiers = snapshot["resources"].get(resource, {})
        t3 = tiers.get("tier_3", {}).get("floor")
        t2 = tiers.get("tier_2", {}).get("floor")
        t1 = tiers.get("tier_1", {}).get("floor")
        t3s = f"{t3:.3f}" if t3 else " ?.???  "
        t2s = f"{t2:.3f}" if t2 else " ?.???  "
        t1s = f"{t1:.3f}" if t1 else " ?.???  "
        print(f"  {resource:<8}  T1:{t1s}  T2:{t2s}  T3:{t3s} ETH")

    print()
    best_sed = None
    best_sed_floor = 0
    for sed, data in snapshot["sediments"].items():
        f = data.get("floor")
        if f and f > best_sed_floor:
            best_sed_floor = f
            best_sed = sed
    if best_sed:
        print(f"  Top sediment: {best_sed} ({best_sed_floor:.3f} ETH)")

    art_floor = snapshot["artifact"].get("floor")
    base_floor = snapshot["collection"].get("floor_eth")
    if art_floor and base_floor:
        premium = ((art_floor - base_floor) / base_floor) * 100
        print(f"  Artifact premium: +{premium:.0f}% over base floor")

    if eth:
        print(f"\n  ETH price at fetch: ${eth:,.0f}")
    print()

# âââââââââââââââââââââââââââââââââââââââââââââ
#  Main
# âââââââââââââââââââââââââââââââââââââââââââââ

if __name__ == "__main__":
    print("\nStarting Koda Temple data fetchâ¦")
    print("(This takes ~30 seconds while querying each trait)\n")
    try:
        snapshot = build_snapshot()
        save_snapshot(snapshot)
        print_summary(snapshot)
        print("  Done. Open koda_temple_dashboard.html to see the live display.\n")
    except KeyboardInterrupt:
        print("\n\n  Interrupted. Partial data not saved.")
    except Exception as e:
        print(f"\n  Error: {e}")
        import traceback; traceback.print_exc()
        print("  Check your internet connection and API key, then try again.")
