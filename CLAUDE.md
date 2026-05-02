# Gold Trading System — Project Memory

## What This Is
A Flask web app for tracking Iranian 18k gold trades against a fundamental-value model.
The core idea: gold has an **intrinsic value** based on the global gold price and a
**baseline dollar** that grows predictably with inflation. Deviations from that IV
generate buy/sell/hold signals. All text in the UI is Persian (RTL, `fa-IR` locale).

Run with: `python app.py` → http://localhost:5000

---

## File Map

| File | Purpose |
|---|---|
| `app.py` | Flask routes |
| `config.py` | Physical constants only (purity, troy oz, DB path) |
| `settings.py` | User-configurable params persisted to `data/settings.json` |
| `strategy.py` | All signal/IV/scenario math |
| `fetcher.py` | Live price scraping (bonbast.com) + cache |
| `history.py` | Historical data fetcher — tgju.org APIs, bulk pagination, SQLite storage |
| `analysis.py` | Correlation engine — lead-lag table, per-year OLS baseline, Pearson r |
| `database.py` | SQLite — trades + market_cache + historical_prices tables |
| `templates/index.html` | Main dashboard (RTL dark terminal theme) |
| `templates/settings.html` | Settings page with live preview |
| `templates/history.html` | Historical correlation analysis page |
| `data/settings.json` | Runtime settings (overrides DEFAULTS in settings.py) |
| `data/gold_trades.db` | SQLite database |

---

## Core Formula

```
18k Intrinsic Value (Toman/gram) = (gold_oz_usd × baseline_dollar / 31.1035) × (750/999)
```

- `GOLD_PURITY_18K = 750/999` — exact 18k purity ratio (NOT 0.75)
- `TROY_OZ_TO_GRAM = 31.1035`
- Both are physical constants in `config.py`, never user-settable

### Baseline Dollar (daily precision)
```
baseline = year_start_dollar + days_since_farvardin_1 × daily_growth
daily_growth = monthly_growth / 30.4375        (365.25 / 12)
monthly_growth = year_start × annual_inflation / 100 / 12   (auto mode)
             OR manual_monthly_growth                         (manual mode)
```

**Critical**: IV is always anchored to the BASELINE dollar, never the market dollar.
The market dollar is only used to compute `dollar_dev`.

---

## Signal Logic (Two-Dimensional)

```
dollar_dev = (market_dollar - baseline_dollar) / baseline_dollar × 100
gold_dev   = (market_gold_18k - IV_at_baseline) / IV_at_baseline × 100
```

**Step 1 — Dollar premium check** (when `dollar_dev > 0`):
```
adj_rr = |gold_dev| / dollar_dev
if adj_rr < min_rr_ratio  →  HOLD_DOLLAR (orange, "#ff8c00")
```
Dollar is overvalued; a correction would drag gold down with it.
Only proceed to gold signal if gold discount is large enough to absorb dollar risk.

**Step 2 — Gold deviation signal**:
```
If dollar_dev < 0:  effective_dev = gold_dev + dollar_dev  (undervalued dollar boosts buy case)
Else:               effective_dev = gold_dev

effective_dev < -15  →  STRONG_BUY  (green,  "#00e676", rr=8.0)
effective_dev < -5   →  BUY         (mint,   "#69f0ae", rr=4.5)
effective_dev < +5   →  HOLD        (yellow, "#ffd740", rr=1.5)
effective_dev < +15  →  SELL_PARTIAL(orange, "#ff6d00", rr=-2.5)
else                 →  STRONG_SELL (red,    "#ff1744", rr=-6.0)
```

---

## Settings System

All user-configurable values live in `settings.py` / `data/settings.json`.
Never read from `config.py` for these — always `_settings.load()`.

| Key | Default | Description |
|---|---|---|
| `year_start_dollar` | 154,000 | Free-market USD/Toman on Farvardin 1 |
| `annual_inflation_pct` | 35.84 | % annual dollar growth (used in auto mode) |
| `use_auto_growth` | False | True = derive monthly from inflation; False = use manual |
| `monthly_growth_manual` | 4,600 | Toman/month (used in manual mode) |
| `optimistic_multiplier` | 1.5 | Scenario growth multiplier |
| `realistic_multiplier` | 1.0 | Scenario growth multiplier |
| `conservative_multiplier` | 0.5 | Scenario growth multiplier |
| `gold_target_eoy_usd` | 0 | Analyst end-of-year gold price target in USD/oz; 0 = no forecast (gold stays fixed in scenarios) |
| `min_rr_ratio` | 3.0 | Minimum adj R/R for BUY signal when dollar is hot |
| `shamsi_year` | 1405 | Display only |

Helper functions (always accept optional `s=None`, load if None):
- `_settings.get_monthly_growth(s)` — respects auto/manual toggle
- `_settings.get_year_start_dollar(s)`
- `_settings.get_min_rr_ratio(s)`

---

## Live Data — bonbast.com

Two-step scrape (must preserve session between steps):
1. `GET https://www.bonbast.com/` → regex `param:\s*['"]([^'"]+)['"]` to extract token
2. `POST https://www.bonbast.com/json` with `data={"param": token}`

Response fields used:
- `usd1` → free-market USD in Toman
- `gol18` → 18k gold price in Toman/gram (used as market_price_18k)
- `ounce` → NOT used for gold USD (Tehran local reflection, inaccurate vs COMEX)

**Gold USD source**: Yahoo Finance COMEX `GC=F` is the PRIMARY source.
→ `https://query1.finance.yahoo.com/v8/finance/chart/GC=F`
→ `response["chart"]["result"][0]["meta"]["regularMarketPrice"]`
Bonbast `ounce` field is the fallback only if Yahoo is unreachable.

Cache TTL: 300 seconds (in SQLite `market_cache` table).

---

## API Response from `/api/market`

The JS dashboard reads these fields from `GET /api/market`:

```json
{
  "gold_usd": 3300,
  "usd_toman": 166750,
  "gold_18k_toman": 19500000,
  "fetched_at": "...",
  "sources_ok": { "gold_usd": true, "usd_toman": true, "gold_18k_toman": true },
  "shamsi_month": 2,
  "shamsi_year": 1405,
  "year_start_dollar": 145000,
  "monthly_growth": 7250,
  "daily_growth": 238.3,
  "days_elapsed": 58,
  "baseline_dollar": 158835,
  "dollar_deviation_pct": 4.99,
  "intrinsic_value_18k": 19200000,
  "market_price_18k": 19500000,
  "gold_24k_gram_toman": 17600000,
  "deviation_pct": 1.56,
  "rr": 1.5,
  "rr_acceptable": false,
  "signal": "HOLD_DOLLAR",
  "signal_fa": "صبر — حباب دلار",
  "signal_color": "#ff8c00",
  "signal_description": "...",
  "scenarios": [...],
  "portfolio": { "total_grams": 5.0, "total_cost_toman": 90000000, "avg_price_per_gram": 18000000, "trade_count": 2 },
  "pnl": { "current_value_toman": 97500000, "pnl_toman": 7500000, "pnl_pct": 8.33 }
}
```

---

## Database Schema

```sql
CREATE TABLE trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    weight_grams REAL NOT NULL,
    price_per_gram_toman REAL NOT NULL,
    total_cost_toman REAL NOT NULL,
    gold_usd_at_time REAL,
    usd_toman_at_time REAL,
    baseline_dollar_at_time REAL,
    intrinsic_value_at_time REAL,
    deviation_pct_at_time REAL,
    signal_at_time TEXT,
    notes TEXT,
    status TEXT DEFAULT 'holding'   -- 'holding' | 'sold' | 'partial'
);

CREATE TABLE market_cache (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

Trade status flow: `holding` → `sold` or `partial` via `PATCH /api/trades/<id>`.
Portfolio summary only counts rows where `status = 'holding'`.

---

## UI Architecture

- **Dark trading terminal theme**: `--bg: #0d1117`, `--surface: #161b22`
- **RTL layout** (`dir="rtl"`, `lang="fa"`)
- **Persian numbers** everywhere via `.toLocaleString('fa-IR')`
- **Shamsi months** displayed using JS `Intl.DateTimeFormat` with `fa-IR` locale
- All pages have `Cache-Control: no-store` headers (Flask sets this explicitly)

### Dashboard sections (index.html)
1. **KPI row** — gold USD, market dollar + dollar_dev %, 18k bazaar price, baseline dollar, IV at baseline, gold deviation %
2. **Gauge card** — SVG needle gauge showing gold deviation + baseline formula box:
   `{year_start} + {days_elapsed} روز × {daily_growth} = {baseline_dollar} تومان`
3. **Signal card** — badge + Persian description + R/R display
4. **Scenarios** — 3×3 grid (optimistic/realistic/conservative × 3m/6m/12m) with prices and target dates
5. **Portfolio summary** — total grams, total cost, avg price, P&L
6. **Trades table** — 13 columns including snapshot values at time of trade
7. **Add trade modal** — pre-fills market snapshot; records full context

### Settings page (settings.html)
- Dollar growth model section (year start, inflation %, auto/manual toggle, manual monthly)
- Live preview: formula box + end-of-year projection, updates on every keystroke
- Scenario multipliers section + live scenario preview
- Signal rules section (min R/R, shamsi year)
- Save → `PUT /api/settings`; revert button reloads from server

---

## Historical Analysis System

### Database table
```sql
CREATE TABLE historical_prices (
    date           TEXT PRIMARY KEY,   -- YYYY-MM-DD gregorian
    usd_toman      REAL,               -- USD close in Toman (Rial ÷ 10)
    gold_18k_toman REAL,               -- 18k gold close in Toman/gram (Rial ÷ 10)
    source         TEXT DEFAULT 'tgju'
);
```

### Data sources (tgju.org)
- Dollar: `price_dollar_rl` — 3,840 records, 2011-11-26 → present
- Gold 18k: `geram18` — 3,392 records, 2013-07-22 → present
- Merged overlapping range: ~3,200 rows from 2013-07-22
- **Column indices**: gold col[0]=close, dollar col[3]=close, both col[6]=gregorian date
- Prices in Rial — divide by 10 to store as Toman
- Date format from API: `"2013/07/22"` → store as `"2013-07-22"`
- Pagination: `?start=0&length=500&order_dir=asc&convert_to_ad=1` (loop until start >= recordsTotal)

### Correlation method
1. Per-Shamsi-year **inflation-anchored** baseline for USD/Toman:
   - For each year, find the earliest available data point and back-calculate `year_start` (Farvardin-1 value)
     using `year_start = first_usd / (1 + days_elapsed × inflation/100/365.25)`
   - `baseline(date) = year_start × (1 + days_since_farvardin1 × inflation/100/365.25)`
   - Falls back to OLS for years not in the table below
2. `dollar_dev = (usd_toman - baseline) / baseline × 100`
3. Five buckets: `< -10%`, `-10 to -5%`, `-5 to +5%`, `+5 to +10%`, `> +10%`
4. For each bucket/day t, measure gold return at t+7, t+30, t+60, t+90 calendar days
5. Pearson r between dollar_dev and gold_return_30d
6. Analysis result cached 1 hour in `market_cache` key `"correlation_analysis"`
   — cache is **invalidated** automatically after every `/api/history/fetch`

### Official annual inflation rates used in historical baseline (`analysis._SHAMSI_INFLATION`)
| Shamsi | Inflation% | | Shamsi | Inflation% |
|--------|------------|---|--------|------------|
| 1389   | 12.4       | | 1397   | 31.2       |
| 1390   | 21.5       | | 1398   | 41.2       |
| 1391   | 30.5       | | 1399   | 47.1       |
| 1392   | 34.7       | | 1400   | 46.2       |
| 1393   | 15.6       | | 1401   | 53.1       |
| 1394   | 11.9       | | 1402   | 47.4       |
| 1395   |  9.0       | | 1403   | 35.8       |
| 1396   |  9.6       | | 1404   | 48.3       |

### New API routes
- `GET /history` — history.html page
- `POST /api/history/fetch` — trigger bulk tgju import (~30–60s, ~16 API calls)
- `GET /api/history/status` — count/date-range of stored records
- `GET /api/analysis/correlation` — run/cache correlation analysis

## Known Architectural Decisions

**Why baseline dollar, not market dollar, anchors IV?**
The market dollar includes a political/crisis premium that can collapse suddenly.
Anchoring IV to the expected (inflation-projected) dollar prevents buying into a bubble.

**Why two deviations instead of one?**
Gold in Toman = gold_usd × usd_toman. If usd_toman is inflated, the Toman gold price
looks cheap but isn't — it will fall when the dollar corrects. The adj R/R gate
(`|gold_dev| / dollar_dev ≥ min_rr`) ensures the gold discount compensates for dollar risk.

**Why daily interpolation instead of monthly steps?**
Monthly steps create a sawtooth baseline that jumps at month boundaries. Daily linear
interpolation (`days_since_farvardin_1 × daily_growth`) gives a smooth, more accurate baseline.

**Why `750/999` and not `0.75` for 18k purity?**
18k gold is 18/24 = 750 parts per 1000 fine gold by the Iranian standard. Using `750/999`
matches how Iranian bazaar gold is hallmarked and priced.

---

## Common Pitfalls

- **Windows console Unicode**: `print()` with Persian chars crashes on cp1252. Not a real bug.
- **Browser cache**: All routes must return `Cache-Control: no-store`. Already set in Flask.
- **bonbast.com token**: The `param` token rotates per session. Must use the same `requests.Session()` for both the GET and the POST.
- **`MIN_RR_RATIO` in strategy.py**: Must be `_settings.get_min_rr_ratio()`, NOT the constant from `config.py`. The constant in config.py is a stale fallback and should not be used in strategy logic.
- **Scenarios use monthly steps for future projections** (not daily). This is intentional — projecting 3/6/12 months ahead, monthly granularity is sufficient.

**Gold USD in scenarios**: if `gold_target_eoy_usd > 0`, each scenario's future gold price is interpolated:
`future_gold = current_gold + (target - current_gold) × multiplier × (months / 12)`
The same scenario multiplier (1.5/1.0/0.5) scales both dollar growth and gold growth.
Realistic at 12m lands exactly on the user's target. If target = 0, gold is frozen at current price (old behaviour).

---

## Dependencies

```
flask>=3.0.0
requests>=2.31.0
jdatetime>=4.1.1
python-dateutil>=2.9.0
```

Python 3.13, Windows 11. Run: `python app.py` (debug mode, port 5000).
