"""
User-configurable economic parameters, persisted to data/settings.json.
Physical/mathematical constants (gold purity, troy oz) stay in config.py.
"""

import json
import os

SETTINGS_FILE = "data/settings.json"

DEFAULTS = {
    # Dollar growth model
    "year_start_dollar":      154_000,   # free-market dollar on Farvardin 1
    "annual_inflation_pct":   35.84,     # % annual dollar growth (yields ~4,600/mo at 154k)
    "use_auto_growth":        False,     # True = derive monthly growth from inflation rate
    "monthly_growth_manual":  4_600,     # manual monthly dollar growth (Toman)

    # Scenario inflation multipliers
    "optimistic_multiplier":  1.5,       # inflation grows 1.5× faster than baseline
    "realistic_multiplier":   1.0,       # baseline growth
    "conservative_multiplier": 0.5,      # inflation grows 0.5× slower than baseline

    # Gold USD forecast (end of Shamsi year)
    "gold_target_eoy_usd":    0,         # analyst target for gold $/oz at year-end; 0 = no forecast (use current)

    # Signal rules
    "min_rr_ratio":           3.0,       # minimum R/R for a BUY signal

    # Shamsi year (informational, used in UI labels)
    "shamsi_year":            1405,
}


def load() -> dict:
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            saved = json.load(f)
        return {**DEFAULTS, **saved}
    return DEFAULTS.copy()


def save(data: dict):
    os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def get_monthly_growth(s: dict = None) -> float:
    """Monthly Toman growth for the dollar."""
    if s is None:
        s = load()
    if s.get("use_auto_growth"):
        return s["year_start_dollar"] * s["annual_inflation_pct"] / 100 / 12
    return float(s["monthly_growth_manual"])


def get_year_start_dollar(s: dict = None) -> float:
    if s is None:
        s = load()
    return float(s["year_start_dollar"])


def get_min_rr_ratio(s: dict = None) -> float:
    if s is None:
        s = load()
    return float(s.get("min_rr_ratio", 3.0))
