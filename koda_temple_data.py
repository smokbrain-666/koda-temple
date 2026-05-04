"""
Koda Temple — Resource Oracle Data Fetcher
==========================================
Pulls live Otherdeed floor prices by resource tier,
sediment, and artifact presence from the OpenSea v2 API.

NOTE: The OpenSea v2 /traits endpoint no longer returns per-trait floor
      prices (API format changed). The /listings endpoint ignores trait
      filters. This script works around both limitations by:
        1. Fetching the cheapest N listings from OpenSea
        2. Looking up each token's traits individually
        3. Building a real floor map per trait from actual listing prices

HOW TO RUN:
  OPENSEA_API_KEY=your_key_here python koda_temple_data.py

For GitHub Actions, add OPENSEA_API_KEY as a repository secret.
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
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests"])
    import requests

# ── Configuration ─────────────────────────────────────────────────────────────

COLLECTION_SLUG   = "otherdeed"
CONTRACT          = "0x34d85c9CDeB23FA97cb08333b511ac86E1C4E258"
OPENSEA_API       = "https://api.opensea.io/api/v2"
COINGECKO         = "https://api.coingecko.com/api/v3"
OPENSEA_KEY       = os.environ.get("OPENSEA_API_KEY", "")
SNAPSHOT_DIR      = "."
REQUEST_DELAY     = 0.6
SCAN_LISTINGS     = 200

RESOURCE_DIRECTIONS = ["Eastern", "Northern", "Southern", "Western"]

# ── Helpers ───────────────────────────────────────────────────────────────────

def headers():
    h = {"accept": "application/json"}
    if OPENSEA_KEY:
        h["X-API-KEY"] = OPENSEA_KEY
    return h

def eth_from_wei(value_str, decimals=18):
    try:
        return int(value_str) / (10 ** decimals)
    except (TypeError, ValueError):
        return None

# ── Data fetching ─────────────────────────────────────────────────────────────

def get_eth_price():
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
    try:
        r = requests.get(
            f"{OPENSEA_API}/collections/{COLLECTION_SLUG}/stats",
            headers=headers(),
            timeout=15,
        )
        if not r.ok:
            print(f"  [warn] Collection stats {r.status_code}: {r.text[:200]}")
            return {}
        data  = r.json()
        total = data.get("total", {})
        vol_24h = vol_7d = None
        for iv in data.get("intervals", []):
            if iv.get("interval") == "one_day":
                vol_24h = iv.get("volume")
            elif iv.get("interval") == "seven_day":
                vol_7d = iv.get("volume")
        return {
            "floor_eth":    total.get("floor_price"),
            "volume_24h":   vol_24h,
            "volume_7d":    vol_7d,
            "on_sale_count": None,
            "total_supply": None,
        }
    except Exception as e:
        print(f"  [warn] Could not fetch collection stats: {e}")
        return {}

def get_cheapest_listings(limit=200):
    results = []
    next_cursor = None
    while len(results) < limit:
        params = {"limit": 50}
        if next_cursor:
            params["next"] = next_cursor
        try:
            r = requests.get(
                f"{OPENSEA_API}/listings/collection/{COLLECTION_SLUG}/best",
                headers=headers(), params=params, timeout=20,
            )
            if not r.ok:
                print(f"  [warn] Listings {r.status_code}")
                break
            data = r.json()
            for lst in data.get("listings", []):
                offer = lst.get("protocol_data", {}).get("parameters", {}).get("offer", [{}])
                token_id = offer[0].get("identifierOrCriteria") if offer else None
                pi = lst.get("price", {}).get("current", {})
                price_eth = eth_from_wei(pi.get("value"), pi.get("decimals", 18))
                if token_id and price_eth is not None:
                    results.append((token_id, price_eth))
            next_cursor = data.get("next")
            if not data.get("listings") or not next_cursor:
                break
        except Exception as e:
            print(f"  [warn] Listings error: {e}")
            break
        time.sleep(REQUEST_DELAY)
    return results[:limit]

def get_nft_traits(token_id):
    try:
        r = requests.get(
            f"{OPENSEA_API}/chain/ethereum/contract/{CONTRACT}/nfts/{token_id}",
            headers=headers(), timeout=15,
        )
        if not r.ok:
            return []
        return r.json().get("nft", {}).get("traits", [])
    except Exception:
        return []

def scan_trait_floors():
    print(f"\n  Scanning {SCAN_LISTINGS} cheapest listings for trait data...")
    listings = get_cheapest_listings(SCAN_LISTINGS)
    print(f"  Retrieved {len(listings)} listings")
    floors = {}
    for i, (token_id, price_eth) in enumerate(listings):
        if i % 25 == 0:
            print(f"  Fetching traits {i}/{len(listings)} ...")
        traits = get_nft_traits(token_id)
        for trait in traits:
            t_type = trait.get("trait_type", "")
            t_val  = str(trait.get("value", ""))
            if not t_type or not t_val:
                continue
            if t_type not in floors:
                floors[t_type] = {}
            if t_val not in floors[t_type]:
                floors[t_type][t_val] = price_eth
        time.sleep(REQUEST_DELAY)
    print(f"  Categories with data: {', '.join(sorted(floors.keys()))}")
    return floors

def get_resource_tier_floor(trait_floors, tier):
    tier_str = str(tier)
    candidates = []
    for direction in RESOURCE_DIRECTIONS:
        f = trait_floors.get(f"{direction} Resource Tier", {}).get(tier_str)
        if f is not None:
            candidates.append(f)
    return min(candidates) if candidates else None

def get_artifact_floor(trait_floors):
    art_dict = trait_floors.get("Artifact", {})
    floors = [v for k, v in art_dict.items() if k and k.lower() not in ("", "none", "null")]
    return min(floors) if floors else None

# ── Build snapshot ────────────────────────────────────────────────────────────

def build_snapshot():
    if not OPENSEA_KEY:
        print("\n  WARNING: No OPENSEA_API_KEY set.")
    snapshot = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "eth_usd":    None,
        "collection": {},
        "resources":  {},
        "sediments":  {},
        "artifact":   {},
    }
    print("\n  Fetching ETH/USD...")
    snapshot["eth_usd"] = get_eth_price()
    eth = snapshot["eth_usd"]
    if eth:
        print(f"  ETH/USD: ${eth:,.0f}")
    print("\n  Fetching collection stats...")
    stats = get_collection_stats()
    snapshot["collection"] = stats
    floor = stats.get("floor_eth")
    if floor:
        usd = f"  (~${floor * eth:,.0f})" if eth else ""
        print(f"  Collection floor: {floor:.4f} ETH{usd}")
    if stats.get("volume_24h"):
        print(f"  24h volume: {stats['volume_24h']:.1f} ETH")
    trait_floors = scan_trait_floors()
    print("\n  ── Resource Tier Floors ──")
    for tier in [3, 2, 1]:
        f = get_resource_tier_floor(trait_floors, tier)
        label = ["●", "◆", "◇"][3 - tier]
        print(f"  {label} Tier {tier}: {f'{f:.4f} ETH' if f else 'not in scanned sample'}")
        snapshot["resources"][f"tier_{tier}"] = {"floor": f, "listed": None}
    print("\n  ── Sediment Tier Floors ──")
    for tier in [3, 2, 1]:
        f = trait_floors.get("Sediment Tier", {}).get(str(tier))
        print(f"  Sediment T{tier}: {f'{f:.4f} ETH' if f else 'no data'}")
        snapshot["sediments"][f"tier_{tier}"] = {"floor": f}
    print("\n  ── Artifact Floor ──")
    art_floor = get_artifact_floor(trait_floors)
    snapshot["artifact"] = {"floor": art_floor}
    if art_floor and floor:
        pct = round(((art_floor - floor) / floor) * 100)
        print(f"  Artifact floor: {art_floor:.4f} ETH  (+{pct}% vs base)")
    else:
        print(f"  Artifact floor: {art_floor}")
    return snapshot

def save_snapshot(snapshot):
    path = os.path.join(SNAPSHOT_DIR, "price_snapshot_latest.json")
    with open(path, "w") as f:
        json.dump(snapshot, f, indent=2)
    print(f"\n  Saved → {path}")
    return path

if __name__ == "__main__":
    print("=" * 60)
    print("  Koda Temple — Resource Oracle")
    print("=" * 60)
    snapshot = build_snapshot()
    save_snapshot(snapshot)
    print("\n  Done.")
