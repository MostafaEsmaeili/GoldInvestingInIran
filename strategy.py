"""
Strategy engine — Iranian gold trading manifesto.

Signal logic — TWO deviations must both be evaluated:

  1. dollar_dev  = (market_dollar - baseline_dollar) / baseline_dollar × 100
     The dollar's own premium over its expected baseline value.
     When positive: dollar is running hot (political/crisis premium).
     When negative: dollar is below expectations (cheap).

  2. gold_dev    = (market_gold_18k - IV_at_baseline) / IV_at_baseline × 100
     Gold's deviation from its intrinsic value at the BASELINE dollar.

BUY requires BOTH conditions to be right (manifesto: "Price < Value"):
  - If dollar_dev > 0: the dollar has a premium.
    The gold price in Toman is partly elevated by this premium.
    When the premium corrects, the Toman gold price falls with it.
    Adjusted R/R = |gold_dev| / dollar_dev.
    If adjusted R/R < MIN_RR_RATIO (3): BUY is suppressed → HOLD/WAIT.
    Only if gold is SO cheap that the discount >> dollar risk (R/R ≥ 3) can we BUY.

  - If dollar_dev ≤ 0: no dollar correction risk.
    Use gold_dev alone for signal.

Example (current state):
  baseline = 158,600  market_dollar = 166,750  dollar_dev = +5.1%
  IV = 20,310,000     market_gold   = 18,550,000  gold_dev  = -8.7%
  Adjusted R/R = 8.7 / 5.1 = 1.7  →  below 3  →  HOLD (not BUY)
"""

import jdatetime
import settings as _settings
from config import GOLD_PURITY_18K, TROY_OZ_TO_GRAM   # physical constants only


# ── Baseline dollar ────────────────────────────────────────────────────────────

_DAYS_PER_MONTH = 30.4375   # 365.25 / 12

def get_current_shamsi_date() -> jdatetime.date:
    return jdatetime.date.today()


def get_current_shamsi_month() -> int:
    return get_current_shamsi_date().month


def _days_since_farvardin1() -> int:
    today = get_current_shamsi_date()
    farvardin1 = jdatetime.date(today.year, 1, 1)
    return (today - farvardin1).days


def baseline_dollar_now() -> float:
    """year_start_dollar + days_since_farvardin_1 × daily_growth"""
    s = _settings.load()
    daily_growth = _settings.get_monthly_growth(s) / _DAYS_PER_MONTH
    return _settings.get_year_start_dollar(s) + _days_since_farvardin1() * daily_growth


# ── Core formulas ──────────────────────────────────────────────────────────────

def intrinsic_value_18k(gold_oz_usd: float, dollar_toman: float) -> float:
    return (gold_oz_usd * dollar_toman / TROY_OZ_TO_GRAM) * GOLD_PURITY_18K


def deviation_pct(market: float, intrinsic: float) -> float:
    if intrinsic <= 0:
        return 0.0
    return (market - intrinsic) / intrinsic * 100


# ── Signal ────────────────────────────────────────────────────────────────────

def _signal_block(gold_dev: float, dollar_dev: float) -> dict:
    """
    Combined signal accounting for both gold undervaluation AND dollar premium risk.

    When dollar_dev > 0, the gold price in Toman is partly supported by the
    dollar premium.  If that premium corrects, gold falls.
    Adjusted R/R = |gold_dev| / dollar_dev must exceed MIN_RR_RATIO to buy.
    """

    # ── Dollar premium check ──────────────────────────────────────────────────
    if dollar_dev > 0:
        adj_rr = abs(gold_dev) / dollar_dev

        if adj_rr < _settings.get_min_rr_ratio():
            # Dollar premium too large relative to gold discount → HOLD
            return dict(
                signal="HOLD_DOLLAR",
                signal_fa="صبر — حباب دلار",
                color="#ff8c00",
                rr=round(adj_rr, 1),
                description=(
                    f"دلار {dollar_dev:.1f}٪ بالاتر از ارزش پایه ماه جاری است. "
                    f"R/R تعدیل‌شده: {adj_rr:.1f} (کمتر از حداقل ۳). "
                    "اگر دلار اصلاح شود، قیمت طلا نیز کاهش می‌یابد. "
                    "منتظر بازگشت دلار به محدوده پایه بمانید."
                ),
            )
        # adj_rr >= MIN_RR_RATIO: gold discount is large enough to absorb dollar risk
        # → fall through to gold-deviation signal below

    # ── Gold deviation signal (dollar risk acceptable or dollar below baseline) ─
    # When dollar is below baseline, it boosts the case for gold (dollar likely to rise).
    # We reflect this as a slight improvement in the effective gold deviation.
    effective_dev = gold_dev
    if dollar_dev < 0:
        # Dollar undervalued: each 1% dollar discount adds buying pressure on gold
        effective_dev = gold_dev + dollar_dev  # more negative = stronger buy

    if effective_dev < -15:
        return dict(
            signal="STRONG_BUY",
            signal_fa="خرید قوی",
            color="#00e676",
            rr=8.0,
            description="قیمت به‌شدت زیر ارزش ذاتی. فرصت استثنایی — ورود پله‌ای فوری.",
        )
    if effective_dev < -5:
        return dict(
            signal="BUY",
            signal_fa="خرید",
            color="#69f0ae",
            rr=4.5,
            description="قیمت پایین‌تر از ارزش ذاتی و دلار در محدوده مناسب. R/R قابل قبول.",
        )
    if effective_dev < 5:
        return dict(
            signal="HOLD",
            signal_fa="نگهداری",
            color="#ffd740",
            rr=1.5,
            description="قیمت در محدوده تعادل. خرید جدید توجیه ریاضی ندارد — صبر کنید.",
        )
    if effective_dev < 15:
        return dict(
            signal="SELL_PARTIAL",
            signal_fa="فروش پله‌ای",
            color="#ff6d00",
            rr=-2.5,
            description="قیمت بالاتر از ارزش ذاتی. پله اول فروش را فعال کنید.",
        )
    return dict(
        signal="STRONG_SELL",
        signal_fa="فروش قوی",
        color="#ff1744",
        rr=-6.0,
        description="حباب قیمتی — احتمالاً هیجان سیاسی/نظامی. فروش پله‌ای فوری.",
    )


# ── Scenarios ─────────────────────────────────────────────────────────────────

def _shamsi_target_dates() -> dict:
    try:
        from dateutil.relativedelta import relativedelta
        from datetime import date
        today = date.today()
        return {
            "3m":  (today + relativedelta(months=3)).isoformat(),
            "6m":  (today + relativedelta(months=6)).isoformat(),
            "12m": (today + relativedelta(months=12)).isoformat(),
        }
    except ImportError:
        from datetime import date, timedelta
        today = date.today()
        return {
            "3m":  (today + timedelta(days=91)).isoformat(),
            "6m":  (today + timedelta(days=182)).isoformat(),
            "12m": (today + timedelta(days=365)).isoformat(),
        }


def _scenarios(gold_oz_usd: float, current_iv: float) -> list:
    base         = baseline_dollar_now()
    target_dates = _shamsi_target_dates()
    scenarios    = []
    base_monthly = _settings.get_monthly_growth()
    s = _settings.load()

    gold_target_eoy = float(s.get("gold_target_eoy_usd", 0))
    gold_annual_delta = (gold_target_eoy - gold_oz_usd) if gold_target_eoy > 0 else 0.0

    for label, label_fa, mult_key in [
        ("optimistic",   "خوش‌بینانه",    "optimistic_multiplier"),
        ("realistic",    "واقع‌بینانه",   "realistic_multiplier"),
        ("conservative", "محافظه‌کارانه", "conservative_multiplier"),
    ]:
        multiplier     = float(s.get(mult_key, {"optimistic_multiplier":1.5,"realistic_multiplier":1.0,"conservative_multiplier":0.5}[mult_key]))
        monthly_growth = base_monthly * multiplier
        targets = {}
        for key in ("3m", "6m", "12m"):
            months         = int(key[:-1])
            future_usd     = base + monthly_growth * months
            future_gold    = gold_oz_usd + gold_annual_delta * multiplier * (months / 12)
            targets[key]   = dict(
                price=round(intrinsic_value_18k(future_gold, future_usd)),
                date=target_dates[key],
                dollar=round(future_usd),
                gold_usd=round(future_gold, 1),
            )

        gain_12m = (targets["12m"]["price"] - current_iv) / current_iv * 100 if current_iv else 0
        scenarios.append(dict(
            label=label,
            label_fa=label_fa,
            monthly_growth_toman=round(monthly_growth),
            gold_target_eoy_usd=round(gold_target_eoy) if gold_target_eoy > 0 else None,
            targets=targets,
            gain_12m_pct=round(gain_12m, 1),
        ))
    return scenarios


# ── Main analysis ─────────────────────────────────────────────────────────────

def analyze(
    gold_oz_usd: float,
    usd_toman_market: float,
    market_price_18k: float | None = None,
) -> dict:
    shamsi_month = get_current_shamsi_month()
    base_dollar  = baseline_dollar_now()

    iv          = intrinsic_value_18k(gold_oz_usd, base_dollar)
    market_gold = market_price_18k if market_price_18k else iv

    gold_dev   = deviation_pct(market_gold, iv)
    dollar_dev = deviation_pct(usd_toman_market, base_dollar)

    sig  = _signal_block(gold_dev, dollar_dev)
    scen = _scenarios(gold_oz_usd, iv)

    s = _settings.load()
    monthly_growth = _settings.get_monthly_growth(s)
    daily_growth   = monthly_growth / _DAYS_PER_MONTH
    year_start     = _settings.get_year_start_dollar(s)
    shamsi_year    = int(s.get("shamsi_year", 1405))
    days_elapsed   = _days_since_farvardin1()

    return dict(
        shamsi_month=shamsi_month,
        shamsi_year=shamsi_year,
        year_start_dollar=round(year_start),
        monthly_growth=round(monthly_growth),
        daily_growth=round(daily_growth, 1),
        days_elapsed=days_elapsed,
        baseline_dollar=round(base_dollar),
        dollar_deviation_pct=round(dollar_dev, 2),
        intrinsic_value_18k=round(iv),
        market_price_18k=round(market_gold),
        gold_24k_gram_toman=round(gold_oz_usd * usd_toman_market / TROY_OZ_TO_GRAM),
        deviation_pct=round(gold_dev, 2),
        rr=sig["rr"],
        rr_acceptable=sig["rr"] >= _settings.get_min_rr_ratio(),
        signal=sig["signal"],
        signal_fa=sig["signal_fa"],
        signal_color=sig["color"],
        signal_description=sig["description"],
        scenarios=scen,
    )


def portfolio_pnl(summary: dict, market_price_18k: float) -> dict:
    grams = summary["total_grams"]
    cost  = summary["total_cost_toman"]
    value = grams * market_price_18k
    pnl   = value - cost
    pnl_p = pnl / cost * 100 if cost else 0
    return dict(
        current_value_toman=round(value),
        pnl_toman=round(pnl),
        pnl_pct=round(pnl_p, 2),
    )
