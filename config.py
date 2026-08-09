

COUNTRY = "IN"
CURRENCY = "INR"

# ---- Tax rules (Step 11) ----
TAX_RULES = {
    "IN": {
        "ltcg_holding_months": 12,
        "note": "Holding beyond 12 months may receive more favorable long-term "
                "capital gains tax treatment under current Indian tax rules. "
                "Tax rates change with policy — verify current rates before acting.",
    }
}

# ---- Hard safety caps (Step 4 - never bent, regardless of risk tier) ----
HARD_CAPS = {
    "max_single_stock_pct": 20,       # default single-stock cap (used by the "Balanced" strategy)
    "absolute_max_single_stock_pct": 30,  # NO strategy, at any risk tier, may ever exceed this
    "max_equity_pct_of_total": {      # ceiling on how much of total money goes to direct equity
        "conservative": 30,
        "moderate": 50,
        "aggressive": 70,
    },
    "min_amount_for_diversification": 5000,  # below this, redirect to funds instead of direct stocks
}

# ---- Agentic recommendation strategies (Step 12) ----
# The recommendation agent no longer hands back a single forced number. It
# reasons through THREE distinct, clearly-labeled strategies for the same
# amount and risk profile, and lets the person pick which trade-off they're
# comfortable with. `ceiling_multiplier` scales the risk-tier equity ceiling
# from config (never above 100%); `per_stock_cap_pct` is that strategy's own
# diversification cap, always clamped beneath absolute_max_single_stock_pct.
STRATEGY_PROFILES = [
    {
        "id": "steady",
        "label": "Steady & Diversified",
        "tagline": "Smaller equity slice, spread wider — the least exposed to any single stock's swings.",
        "ceiling_multiplier": 0.65,
        "per_stock_cap_pct": 12,
        "min_picks": 8,
    },
    {
        "id": "balanced",
        "label": "Balanced",
        "tagline": "Uses your full risk-tier ceiling with standard diversification. Our suggested default.",
        "ceiling_multiplier": 1.0,
        "per_stock_cap_pct": 20,
        "min_picks": 5,
        "recommended": True,
    },
    {
        "id": "focused",
        "label": "Focused, Higher Conviction",
        "tagline": "Puts more of your amount to work in fewer, higher-scoring names. More concentration risk.",
        "ceiling_multiplier": 1.3,
        "per_stock_cap_pct": 28,
        "min_picks": 3,
    },
]

# ---- Reference indices shown on the Overview page ----
# These are well-known benchmarks (not part of the stock-picking universe) —
# purely so the person always has a familiar reference point on the page.
# Levels are illustrative/simulated for this project, same as the ticker.
REFERENCE_INDICES = [
    {"symbol": "NIFTY50", "name": "Nifty 50", "base_level": 24500, "currency": "INR"},
    {"symbol": "SENSEX", "name": "BSE Sensex", "base_level": 80500, "currency": "INR"},
    {"symbol": "BANKNIFTY", "name": "Nifty Bank", "base_level": 51800, "currency": "INR"},
    {"symbol": "SPX", "name": "S&P 500", "base_level": 5600, "currency": "USD"},
    {"symbol": "NASDAQ", "name": "Nasdaq Composite", "base_level": 17800, "currency": "USD"},
]

# ---- Safety buffer check (Step 3) ----
SAFETY_BUFFER = {
    "min_emergency_months": 3,   # months of expenses considered "safe enough"
}

# ---- Risk-tier dependent screening thresholds (Step 4, Layer B) ----
# Every threshold below is looked up by risk tier during screening.
RISK_TIER_THRESHOLDS = {
    "conservative": {
        "pe_max_vs_sector_multiple": 1.1,   # P/E must be <= 1.1x sector average
        "peg_max": 1.2,
        "pb_max": 4.0,
        "debt_to_equity_max": 0.6,
        "roe_min": 15.0,
        "revenue_growth_min": 5.0,
        "revenue_growth_max": 25.0,
        "market_cap_tiers_allowed": ["large"],
        "min_years_consistent_earnings": 5,
    },
    "moderate": {
        "pe_max_vs_sector_multiple": 1.4,
        "peg_max": 1.8,
        "pb_max": 6.0,
        "debt_to_equity_max": 1.0,
        "roe_min": 12.0,
        "revenue_growth_min": 5.0,
        "revenue_growth_max": 40.0,
        "market_cap_tiers_allowed": ["large", "mid"],
        "min_years_consistent_earnings": 3,
    },
    "aggressive": {
        "pe_max_vs_sector_multiple": 2.0,
        "peg_max": 2.5,
        "pb_max": 10.0,
        "debt_to_equity_max": 1.5,
        "roe_min": 8.0,
        "revenue_growth_min": 5.0,
        "revenue_growth_max": 80.0,
        "market_cap_tiers_allowed": ["large", "mid", "small"],
        "min_years_consistent_earnings": 2,
    },
}

# ---- Universal minimums (Layer A - same for every user, no exceptions) ----
UNIVERSAL_MINIMUMS = {
    "min_market_cap_cr": 1000,       # in crores INR — filters out illiquid microcaps
    "min_avg_volume": 50000,         # average daily trading volume floor
}

# ---- Data staleness ----
DATA_STALENESS_HOURS = 12   # outside market hours only — see pipeline.refresh_data_if_needed
                             # for the market-hours-aware (15-min) refresh cadence used while open

# ---- Minimum age to use this tool (Step 8 edge case: minors) ----
MIN_AGE = 18

DISCLAIMER = (
    "This is educational output only, not personalized financial advice. "
    "It is illustrative, not a directive to buy. Please do your own research "
    "or consult a SEBI-registered investment adviser before acting. "
    "This tool does not execute trades — you would need your own brokerage/Demat account."
)
