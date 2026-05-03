"""
Koda Temple — Resource Oracle Data Fetcher
==========================================
Pulls live Otherdeed floor prices by resource type, tier,
sediment, and artifact presence from the Reservoir API.

HOW TO RUN (no technical knowledge needed):
  1. Make sure Python is installed on your computer
  2. Open Terminal (Mac) or Command Prompt (Windows)
  3. Type: python koda_temple_data.py
  4. It will print current prices and save a snapshot file

To install the one required library:
  pip install requests

No API key needed for basic usage.
"""

import json
import time
import sys
from datetime import datetime, timezone

try:
    import requests
except ImportError:
    print("Installing 'requests' library...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests"])
    import requests

# ─────────────────────────────────────────────
#  Configuration
# ─────────────────────────────────────────────

COLLECTION   = "otherdeed-for-otherside"
RESERVOIR    = "https://api.reservoir.tools"
COINGECKO    = "https://api.coingecko.com/api/v3"
SNAPSHOT_DIR = "."  # saves price_snapshot_YYYY-MM-DD.json in current folder

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

HEADERS = {"accept": "application/json"}
REQUEST_DELAY = 0.4  # seconds between API calls (be polite)

# ─────────────────────────────────────────────
#  Data fetching
# ─────────────────────────────────────────────

def get_eth_price():
    """Fetch current ETH/USD price from CoinGecko."""
    try:
        url = f"{COINGECKO}/simple/price"
        r = requests.get(url, params={"ids": "ethereum", "vs_currencies": "usd"}, timeout=10)
        return r.json().get("ethereum", {}).get("usd")
    except Exception as e:
        print(f"  [warn] Could not fetch ETH price: {e}")
        return None


def get_collection_stats():
    """Fetch overall collection floor, volume, and listing count."""
    try:
        url = f"{RESERVOIR}/collections/v7"
        r = requests.get(url, params={"id": COLLECTION, "limit": 1}, headers=HEADERS, timeout=15)
        data = r.json()
        col = data.get("collections", [{}])[0]
        return {
            "floor_eth":    col.get("floorAsk", {}).get("price", {}).get("amount", {}).get("native"),
            "volume_24h":   col.get("volume", {}).get("1day"),
            "volume_7d":    col.get("volume", {}).get("7day"),
            "on_sale_count": col.get("onSaleCount"),
            "total_supply":  col.get("tokenCount"),
        }
    except Exception as e:
        print(f"  [warn] Could not fetch collection stats: {e}")
        return {}


def get_trait_floor(trait_type, trait_value):
    """
    Fetch floor price for a specific trait value.
    E.g. trait_type="Anima", trait_value="3"
    """
    try:
        url = f"{RESERVOIR}/collections/{COLLECTION}/attributes/explore/v5"
        params = {
            "attributeKey":   trait_type,
            "attributeValue": trait_value,
            "limit": 1,
        }
        r = requests.get(url, params=params, headers=HEADERS, timeout=15)
        data = r.json()
        attrs = data.get("attributes", [])
        if attrs:
            price = attrs[0].get("floorAskPrice", {}).get("amount", {}).get("native")
            count = attrs[0].get("onSaleCount")
            return {"floor": price, "listed": count}
        return {"floor": None, "listed": None}
    except Exception as e:
        print(f"  [warn] {trait_type}={trait_value}: {e}")
        return {"floor": None, "listed": None}


# ─────────────────────────────────────────────
#  Build the full market snapshot
# ─────────────────────────────────────────────

def build_snapshot():
    snapshot = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "eth_usd":    None,
        "collection": {},
        "resources":  {},
        "sediments":  {},
        "artifact":   {},
    }

    print("\n🔮 Koda Temple — Resource Oracle")
    print("=" * 46)

    # ETH price
    print("\n  Fetching ETH price…")
    snapshot["eth_usd"] = get_eth_price()
    eth = snapshot["eth_usd"]
    if eth:
        print(f"  ETH/USD: ${eth:,.0f}")

    # Collection stats
    print("\n  Fetching collection stats…")
    stats = get_collection_stats()
    snapshot["collection"] = stats
    floor = stats.get("floor_eth")
    if floor:
        usd = f"  (~${floor * eth:,.0f})" if eth else ""
        print(f"  Collection floor: {floor:.4f} ETH{usd}")
    if stats.get("on_sale_count"):
        print(f"  Listed: {stats['on_sale_count']:,} deeds")
    if stats.get("volume_24h"):
        print(f"  24h volume: {stats['volume_24h']:.1f} ETH")
    time.sleep(REQUEST_DELAY)

    # Resources by tier
    print("\n  ── Resource Floors ──")
    for resource in RESOURCES:
        snapshot["resources"][resource] = {}
        print(f"\n  {resource.upper()} ({RESOURCE_DESCRIPTIONS[resource]})")
        for tier in [3, 2, 1]:
            result = get_trait_floor(resource, str(tier))
            snapshot["resources"][resource][f"tier_{tier}"] = result
            floor_str = f"{result['floor']:.4f} ETH" if result["floor"] else "no data"
            count_str = f"({result['listed']} listed)" if result["listed"] else ""
            label = ["●", "◆", "▲"][3 - tier]  # T3=▲, T2=◆, T1=●
            print(f"    {label} Tier {tier}: {floor_str}  {count_str}")
            time.sleep(REQUEST_DELAY)

    # Sediments
    print("\n  ── Sediment Floors ──")
    for sediment in SEDIMENTS:
        result = get_trait_floor("Sediment", sediment)
        snapshot["sediments"][sediment] = result
        floor_str = f"{result['floor']:.4f} ETH" if result["floor"] else "no data"
        print(f"  {sediment}: {floor_str}")
        time.sleep(REQUEST_DELAY)

    # Artifacts
    print("\n  ── Artifact Premium ──")
    art = get_trait_floor("Artifact", "Yes")
    snapshot["artifact"] = art
    base_floor = snapshot["collection"].get("floor_eth")
    if art["floor"]:
        print(f"  With artifact floor: {art['floor']:.4f} ETH")
        if base_floor and base_floor > 0:
            premium = ((art["floor"] - base_floor) / base_floor) * 100
            print(f"  Premium vs. base floor: +{premium:.1f}%")
    if art["listed"]:
        print(f"  Artifact deeds listed: {art['listed']}")

    return snapshot


# ─────────────────────────────────────────────
#  Save snapshot to JSON
# ─────────────────────────────────────────────

def save_snapshot(snapshot):
    date_str = datetime.now().strftime("%Y-%m-%d")
    filename = f"price_snapshot_{date_str}.json"
    with open(filename, "w") as f:
        json.dump(snapshot, f, indent=2)
    # Also save as latest — this is what the dashboard reads from GitHub Pages
    with open("price_snapshot_latest.json", "w") as f:
        json.dump(snapshot, f, indent=2)
    print(f"\n  ✓ Snapshot saved: {filename}")
    print(f"  ✓ Latest updated: price_snapshot_latest.json")
    return filename


# ─────────────────────────────────────────────
#  Summary table
# ─────────────────────────────────────────────

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


# ─────────────────────────────────────────────
#  Main
# ─────────────────────────────────────────────

if __name__ == "__main__":
    print("\nStarting Koda Temple data fetch…")
    print("(This takes ~30 seconds while querying each trait)\n")

    try:
        snapshot = build_snapshot()
        save_snapshot(snapshot)
        print_summary(snapshot)
        print("  Done. Open koda_temple_dashboard.html in your browser to see the live display.\n")
    except KeyboardInterrupt:
        print("\n\n  Interrupted. Partial data not saved.")
    except Exception as e:
        print(f"\n  Error: {e}")
        print("  Check your internet connection and try again.")
