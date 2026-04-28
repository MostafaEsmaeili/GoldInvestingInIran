"""
Historical price fetcher — tgju.org APIs for USD/Toman and 18k gold (Toman/gram).

Dollar API:  price_dollar_rl  — col[3]=close (Rial), col[6]=gregorian date YYYY/MM/DD
Gold API:    geram18          — col[0]=close (Rial), col[6]=gregorian date YYYY/MM/DD

All prices stored as Toman (Rial ÷ 10).
Incremental: on update, only records newer than the last stored date are fetched.
After each fetch the full dataset is exported to data/historical_prices.csv (committed to repo).
"""

import time
import requests
import jdatetime
import database
from datetime import datetime, date, timedelta

_BASE    = "https://api.tgju.org/v1/market/indicator/summary-table-data"
_BATCH   = 500
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}


def _to_persian_date(date_str: str) -> str:
    """Convert YYYY-MM-DD gregorian to YYYY/MM/DD Persian for tgju from= param."""
    d  = date.fromisoformat(date_str)
    jd = jdatetime.date.fromgregorian(date=d)
    return f"{jd.year}/{jd.month:02d}/{jd.day:02d}"


def _parse_price(s) -> float | None:
    try:
        return float(str(s).replace(",", "").strip()) / 10  # Rial → Toman
    except (ValueError, TypeError):
        return None


def _fetch_series(key: str, col_close: int, from_persian: str = None) -> list[dict]:
    """
    Paginate the tgju summary-table-data API for one series.
    from_persian: Persian calendar date string YYYY/MM/DD — only fetch from this date onward.
    """
    results = []
    start   = 0
    total   = None

    while True:
        url = (
            f"{_BASE}/{key}"
            f"?lang=fa&order_dir=asc&start={start}&length={_BATCH}&convert_to_ad=1"
        )
        if from_persian:
            url += f"&from={from_persian}"

        try:
            r = requests.get(url, headers=_HEADERS, timeout=30)
            r.raise_for_status()
            payload = r.json()
        except Exception as e:
            print(f"[history] error fetching {key} at start={start}: {e}")
            break

        if total is None:
            total = int(payload.get("recordsTotal", 0))
            label = f"from {from_persian}" if from_persian else "full history"
            print(f"[history] {key}: {total} records ({label})")

        rows = payload.get("data", [])
        if not rows:
            break

        for row in rows:
            try:
                date_str = str(row[6]).replace("/", "-")   # "2013/07/22" → "2013-07-22"
                price    = _parse_price(row[col_close])
                if date_str and price and price > 0:
                    results.append({"date": date_str, "price_toman": price})
            except (IndexError, TypeError):
                continue

        start += _BATCH
        print(f"[history] {key}: fetched {min(start, total)}/{total}")
        if start >= total:
            break
        time.sleep(0.25)  # be polite to tgju.org

    return results


def fetch_and_store_all() -> dict:
    """
    Incrementally fetch dollar and gold from tgju, merge by date, upsert to SQLite,
    then export the full dataset to CSV.
    Returns a stats dict.
    """
    started = datetime.now()

    # Incremental: only fetch records newer than what we already have
    status      = database.get_historical_status()
    last_date   = status.get("to")          # YYYY-MM-DD or None
    from_persian = None
    if last_date:
        next_day     = date.fromisoformat(last_date) + timedelta(days=1)
        from_persian = _to_persian_date(next_day.isoformat())
        print(f"[history] Incremental fetch from {from_persian} (last stored: {last_date})")
    else:
        print("[history] No existing data — fetching full history")

    print("[history] Fetching USD/Toman series (price_dollar_rl)...")
    dollar_rows = _fetch_series("price_dollar_rl", col_close=3, from_persian=from_persian)

    print("[history] Fetching 18k gold series (geram18)...")
    gold_rows = _fetch_series("geram18", col_close=0, from_persian=from_persian)

    dollar_by_date = {r["date"]: r["price_toman"] for r in dollar_rows}
    gold_by_date   = {r["date"]: r["price_toman"] for r in gold_rows}

    common_dates = sorted(set(dollar_by_date) & set(gold_by_date))
    new_rows = [
        {
            "date":           d,
            "usd_toman":      dollar_by_date[d],
            "gold_18k_toman": gold_by_date[d],
            "source":         "tgju",
        }
        for d in common_dates
    ]

    if new_rows:
        database.upsert_historical(new_rows)

    # Export full dataset to CSV for repo
    database.export_historical_to_csv()

    elapsed    = round((datetime.now() - started).total_seconds(), 1)
    final_stat = database.get_historical_status()
    date_range = {"from": final_stat["from"], "to": final_stat["to"]}

    print(f"[history] Done. {len(new_rows)} new rows. Total in DB: {final_stat['count']}. {elapsed}s")
    return {
        "dollar_fetched":  len(dollar_rows),
        "gold_fetched":    len(gold_rows),
        "new_rows":        len(new_rows),
        "total_stored":    final_stat["count"],
        "date_range":      date_range,
        "elapsed_seconds": elapsed,
        "incremental":     from_persian is not None,
    }
