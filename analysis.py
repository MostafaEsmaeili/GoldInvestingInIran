"""
Correlation analysis engine — dollar deviation vs subsequent gold price changes.

Method:
  1. Build a per-Shamsi-year inflation-anchored baseline for USD/Toman.
     Each year's baseline starts from the actual market value on Farvardin 1
     (back-calculated from the earliest available data point of that year)
     and grows at the official annual inflation rate for that year.
     Formula: baseline(d) = year_start × (1 + d × inflation/100/365.25)
     where d = days elapsed since Farvardin 1.
  2. Compute dollar_dev = (actual - baseline) / baseline × 100 for every day.
  3. Bucket days by dollar_dev level.
  4. For each bucket, measure average 18k gold return over the following
     7 / 30 / 60 / 90 calendar days.
  5. Compute overall Pearson r between dollar_dev and gold_return_30d.
"""

import bisect
import statistics
from datetime import date, datetime, timedelta

import jdatetime
import database

# Official annual CPI inflation rates (%) by Shamsi year.
# Source: Central Bank of Iran / Statistical Centre of Iran.
_SHAMSI_INFLATION: dict[int, float] = {
    1389: 12.4,
    1390: 21.5,
    1391: 30.5,
    1392: 34.7,
    1393: 15.6,
    1394: 11.9,
    1395:  9.0,
    1396:  9.6,
    1397: 31.2,
    1398: 41.2,
    1399: 47.1,
    1400: 46.2,
    1401: 53.1,
    1402: 47.4,
    1403: 35.8,
    1404: 48.3,
}

_DAYS_PER_YEAR = 365.25


# ── Shamsi calendar helpers ────────────────────────────────────────────────────

def _shamsi_year(date_str: str) -> int:
    d = date.fromisoformat(date_str)
    return jdatetime.date.fromgregorian(date=d).year


def _day_of_shamsi_year(date_str: str) -> int:
    d  = date.fromisoformat(date_str)
    jd = jdatetime.date.fromgregorian(date=d)
    return (jd - jdatetime.date(jd.year, 1, 1)).days + 1


# ── Baseline dollar via official inflation rates ───────────────────────────────

def _build_baselines(rows: list[dict]) -> dict[str, float]:
    """
    Per-Shamsi-year inflation-anchored baseline for USD/Toman.

    For each year with a known inflation rate:
      - Find the earliest data point in that year.
      - Back-calculate year_start (Farvardin 1 value) using the inflation rate.
      - baseline(date) = year_start × (1 + days_since_farvardin1 × rate)

    Falls back to OLS regression for years without a known inflation rate.
    Returns {date_str: expected_baseline_toman}.
    """
    by_year: dict[int, list] = {}
    for r in rows:
        if r["usd_toman"]:
            by_year.setdefault(_shamsi_year(r["date"]), []).append(r)

    baselines: dict[str, float] = {}

    for yr, yr_rows in by_year.items():
        inflation = _SHAMSI_INFLATION.get(yr)

        if inflation is None:
            # Fallback: OLS for unknown years
            if len(yr_rows) < 2:
                for r in yr_rows:
                    baselines[r["date"]] = r["usd_toman"]
                continue
            xs  = [float(_day_of_shamsi_year(r["date"])) for r in yr_rows]
            ys  = [r["usd_toman"] for r in yr_rows]
            reg = statistics.linear_regression(xs, ys)
            for r in yr_rows:
                x = float(_day_of_shamsi_year(r["date"]))
                baselines[r["date"]] = reg.intercept + reg.slope * x
            continue

        # Inflation-based baseline anchored to actual Farvardin-1 value.
        # Use the earliest known data point to back-calculate year_start.
        sorted_rows = sorted(yr_rows, key=lambda r: r["date"])
        first       = sorted_rows[0]
        first_d     = _day_of_shamsi_year(first["date"]) - 1   # days since Farvardin 1
        daily_rate  = inflation / 100.0 / _DAYS_PER_YEAR
        year_start  = first["usd_toman"] / (1.0 + first_d * daily_rate)

        for r in sorted_rows:
            d = _day_of_shamsi_year(r["date"]) - 1
            baselines[r["date"]] = year_start * (1.0 + d * daily_rate)

    return baselines


# ── Nearest gold price lookup ──────────────────────────────────────────────────

def _nearest_gold(gold_index: list[str], gold_map: dict[str, float],
                  target: date, max_drift: int = 3) -> float | None:
    target_str = target.isoformat()
    pos = bisect.bisect_left(gold_index, target_str)
    best, best_diff = None, max_drift + 1
    for offset in (0, 1, -1, 2, -2, 3, -3):
        idx = pos + offset
        if 0 <= idx < len(gold_index):
            d_str = gold_index[idx]
            diff  = abs((date.fromisoformat(d_str) - target).days)
            if diff <= max_drift and diff < best_diff:
                best, best_diff = gold_map[d_str], diff
    return best


# ── Bucket definitions ─────────────────────────────────────────────────────────

_BUCKETS = [
    ("< -10%",     "کاهش شدید دلار (زیر ۱۰٪−)",     None,   -10.0),
    ("-10 to -5%", "کاهش دلار (۱۰٪− تا ۵٪−)",       -10.0,   -5.0),
    ("-5 to +5%",  "دلار در محدوده تعادل (±۵٪)",      -5.0,   +5.0),
    ("+5 to +10%", "حباب دلار (۵٪+ تا ۱۰٪+)",         +5.0,  +10.0),
    ("> +10%",     "حباب شدید دلار (بالای ۱۰٪+)",    +10.0,   None),
]

_HORIZONS = [7, 30, 60, 90]


# ── Main analysis ──────────────────────────────────────────────────────────────

def run_correlation() -> dict:
    rows = database.get_historical()
    if len(rows) < 30:
        return {"error": "داده تاریخی کافی نیست. ابتدا داده‌ها را بارگذاری کنید."}

    baselines = _build_baselines(rows)

    enriched = []
    for r in rows:
        baseline = baselines.get(r["date"])
        if baseline and baseline > 0 and r["usd_toman"] and r["gold_18k_toman"]:
            dollar_dev = (r["usd_toman"] - baseline) / baseline * 100
            enriched.append({**r, "dollar_dev": dollar_dev, "baseline": baseline})

    if len(enriched) < 30:
        return {"error": "داده کافی برای تحلیل وجود ندارد."}

    gold_map   = {r["date"]: r["gold_18k_toman"] for r in enriched}
    gold_index = sorted(gold_map)

    # ── Lead-lag table ─────────────────────────────────────────────────────────
    lead_lag = []
    for bucket_key, label_fa, lo, hi in _BUCKETS:
        events = [
            r for r in enriched
            if (lo is None or r["dollar_dev"] >= lo)
            and (hi is None or r["dollar_dev"] < hi)
        ]

        if not events:
            lead_lag.append({
                "bucket": bucket_key, "label_fa": label_fa, "count": 0,
                **{f"avg_gold_{n}d": None for n in _HORIZONS},
                "pct_gold_fell_30d": None,
            })
            continue

        returns: dict[int, list[float]] = {n: [] for n in _HORIZONS}
        for r in events:
            t      = date.fromisoformat(r["date"])
            gold_t = r["gold_18k_toman"]
            for n in _HORIZONS:
                future = _nearest_gold(gold_index, gold_map, t + timedelta(days=n))
                if future:
                    returns[n].append((future - gold_t) / gold_t * 100)

        avg_returns = {}
        for n in _HORIZONS:
            vals = returns[n]
            avg_returns[f"avg_gold_{n}d"] = round(statistics.mean(vals), 2) if vals else None

        fell_30 = returns[30]
        pct_fell = (
            round(sum(1 for v in fell_30 if v < 0) / len(fell_30) * 100, 1)
            if fell_30 else None
        )

        lead_lag.append({
            "bucket":            bucket_key,
            "label_fa":          label_fa,
            "count":             len(events),
            **avg_returns,
            "pct_gold_fell_30d": pct_fell,
        })

    # ── Pearson r (dollar_dev vs gold_return_30d) ──────────────────────────────
    pearson_r = None
    xs_corr, ys_corr = [], []
    for r in enriched:
        t      = date.fromisoformat(r["date"])
        future = _nearest_gold(gold_index, gold_map, t + timedelta(days=30))
        if future and r["gold_18k_toman"]:
            xs_corr.append(r["dollar_dev"])
            ys_corr.append((future - r["gold_18k_toman"]) / r["gold_18k_toman"] * 100)

    if len(xs_corr) >= 3:
        try:
            pearson_r = round(statistics.correlation(xs_corr, ys_corr), 3)
        except statistics.StatisticsError:
            pass

    # ── Monthly chart sample (every ~20th row for performance) ────────────────
    step  = max(1, len(enriched) // 200)
    chart = [
        {"date": r["date"], "dollar_dev": round(r["dollar_dev"], 2),
         "gold_toman": round(r["gold_18k_toman"])}
        for r in enriched[::step]
    ]

    # ── Key insight in Persian ─────────────────────────────────────────────────
    bubble     = next((b for b in lead_lag if b["bucket"] == "> +10%"), None)
    deflated   = next((b for b in lead_lag if b["bucket"] == "< -10%"), None)
    if bubble and bubble["count"] >= 10 and bubble["avg_gold_30d"] is not None:
        pf        = bubble["pct_gold_fell_30d"] or 0
        direction = "کاهش" if bubble["avg_gold_30d"] < 0 else "افزایش"
        # Extra note: compare bubble vs deflated return to show relative impact
        extra = ""
        if deflated and deflated["avg_gold_30d"] is not None:
            diff = bubble["avg_gold_30d"] - deflated["avg_gold_30d"]
            diff_dir = "بیشتر" if diff > 0 else "کمتر"
            extra = f" این {abs(diff):.1f}٪ {diff_dir} از دوره‌های کاهش دلار است."
        insight = (
            f"در {bubble['count']} روزی که دلار بیش از ۱۰٪ بالاتر از پایه تورمی خود بود، "
            f"قیمت طلای ۱۸ عیار در ۳۰ روز بعد به‌طور میانگین "
            f"{abs(bubble['avg_gold_30d']):.1f}٪ {direction} یافت "
            f"({pf:.0f}٪ موارد افت داشتند).{extra}"
        )
    elif pearson_r is not None:
        direction = "منفی" if pearson_r < 0 else "مثبت"
        strength  = "قوی" if abs(pearson_r) > 0.4 else ("متوسط" if abs(pearson_r) > 0.2 else "ضعیف")
        insight = (
            f"همبستگی {direction} {strength} میان انحراف دلار از پایه تورمی و بازده ۳۰ روزه طلا: "
            f"r = {pearson_r}"
        )
    else:
        insight = "داده کافی برای نتیجه‌گیری قطعی وجود ندارد."

    return {
        "generated_at":     datetime.now().isoformat(),
        "records_analyzed": len(enriched),
        "date_range":       {"from": enriched[0]["date"], "to": enriched[-1]["date"]},
        "pearson_r_30d":    pearson_r,
        "lead_lag":         lead_lag,
        "chart_data":       chart,
        "key_insight_fa":   insight,
    }
