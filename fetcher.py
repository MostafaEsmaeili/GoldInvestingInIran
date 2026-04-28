"""
Live market data fetcher.

Primary source: bonbast.com (parallel/free market rates)
  - Scrapes a session token from the homepage, then POSTs to /json
  - Returns: usd1 (Toman), gol18 (Toman/gram 18k), ounce (USD spot)

Fallback for gold USD: Yahoo Finance GC=F

All results are cached in SQLite for CACHE_TTL_SECONDS.
"""

import json
import re
import requests
import database
from config import CACHE_TTL_SECONDS
from datetime import datetime

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}
_TIMEOUT = 15


def _fetch_bonbast() -> dict | None:
    """
    Fetch all live rates from bonbast.com in a single session.
    Returns a dict with at minimum: usd1, gol18, ounce
    """
    cached = database.cache_get("bonbast_raw", CACHE_TTL_SECONDS)
    if cached is not None:
        return cached

    try:
        session = requests.Session()

        # Step 1: GET homepage to extract the rotating session param
        r = session.get(
            "https://www.bonbast.com/",
            headers={**_HEADERS, "Accept": "text/html,application/xhtml+xml,*/*"},
            timeout=_TIMEOUT,
        )
        r.raise_for_status()

        m = re.search(r"param:\s*['\"]([^'\"]+)['\"]", r.text)
        if not m:
            print("[fetcher] bonbast: param token not found in page")
            return None
        param = m.group(1)

        # Step 2: POST to /json with the extracted param
        r2 = session.post(
            "https://www.bonbast.com/json",
            data={"param": param},
            headers={
                **_HEADERS,
                "Content-Type": "application/x-www-form-urlencoded",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": "https://www.bonbast.com/",
            },
            timeout=_TIMEOUT,
        )
        r2.raise_for_status()
        data = json.loads(r2.content.decode("utf-8"))

        if "usd1" not in data:
            print(f"[fetcher] bonbast: unexpected response keys: {list(data.keys())[:8]}")
            return None

        database.cache_set("bonbast_raw", data)
        return data

    except Exception as e:
        print(f"[fetcher] bonbast error: {e}")
        return None


def get_gold_price_usd() -> float | None:
    cached = database.cache_get("gold_usd", CACHE_TTL_SECONDS)
    if cached is not None:
        return cached

    # Primary: Yahoo Finance COMEX GC=F (international spot price)
    try:
        r = requests.get(
            "https://query1.finance.yahoo.com/v8/finance/chart/GC=F",
            headers=_HEADERS,
            timeout=_TIMEOUT,
        )
        r.raise_for_status()
        price = float(r.json()["chart"]["result"][0]["meta"]["regularMarketPrice"])
        database.cache_set("gold_usd", price)
        return price
    except Exception as e:
        print(f"[fetcher] Yahoo Finance GC=F error: {e}")

    # Fallback: bonbast ounce field (Tehran local reflection, less accurate)
    data = _fetch_bonbast()
    if data and data.get("ounce"):
        try:
            price = float(str(data["ounce"]).replace(",", ""))
            database.cache_set("gold_usd", price)
            return price
        except (ValueError, TypeError):
            pass

    return None


def get_usd_toman() -> float | None:
    cached = database.cache_get("usd_toman", CACHE_TTL_SECONDS)
    if cached is not None:
        return cached

    data = _fetch_bonbast()
    if data and data.get("usd1"):
        try:
            toman = float(str(data["usd1"]).replace(",", ""))
            database.cache_set("usd_toman", toman)
            return toman
        except (ValueError, TypeError):
            pass

    return None


def get_gold_18k_toman() -> float | None:
    cached = database.cache_get("gold_18k_toman", CACHE_TTL_SECONDS)
    if cached is not None:
        return cached

    data = _fetch_bonbast()
    if data and data.get("gol18"):
        try:
            toman = float(str(data["gol18"]).replace(",", ""))
            database.cache_set("gold_18k_toman", toman)
            return toman
        except (ValueError, TypeError):
            pass

    return None


def get_all_market_data() -> dict:
    gold_usd = get_gold_price_usd()
    usd_toman = get_usd_toman()
    gold_18k_toman = get_gold_18k_toman()

    return {
        "gold_usd": gold_usd,
        "usd_toman": usd_toman,
        "gold_18k_toman": gold_18k_toman,
        "fetched_at": datetime.now().isoformat(),
        "sources_ok": {
            "gold_usd": gold_usd is not None,
            "usd_toman": usd_toman is not None,
            "gold_18k_toman": gold_18k_toman is not None,
        },
    }
