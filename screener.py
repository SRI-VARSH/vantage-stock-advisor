

from config import RISK_TIER_THRESHOLDS, UNIVERSAL_MINIMUMS


def passes_universal_minimums(stock: dict) -> tuple:
    """Layer A: same bar for every user, regardless of risk tier."""
    reasons_failed = []

    if stock["market_cap_cr"] < UNIVERSAL_MINIMUMS["min_market_cap_cr"]:
        reasons_failed.append("market cap below minimum floor")

    if stock["avg_volume"] < UNIVERSAL_MINIMUMS["min_avg_volume"]:
        reasons_failed.append("trading volume too low / illiquid")

    if stock.get("free_cash_flow", 0) <= 0:
        reasons_failed.append("free cash flow not positive")

    # Positive earnings proxy: PE ratio must be positive and defined
    # (a negative/zero/undefined PE typically means no earnings or a loss)
    if not stock.get("pe_ratio") or stock["pe_ratio"] <= 0:
        reasons_failed.append("no positive earnings (PE undefined or non-positive)")

    if stock.get("red_flag"):
        reasons_failed.append("active red flag (fraud/regulatory/auditor issue)")

    return (len(reasons_failed) == 0, reasons_failed)


def passes_risk_tier_thresholds(stock: dict, risk_tier: str) -> tuple:
    """Layer B: thresholds scale by risk tier — conservative strictest, aggressive loosest."""
    t = RISK_TIER_THRESHOLDS[risk_tier]
    reasons_failed = []

    sector_avg_pe = stock.get("sector_avg_pe") or stock.get("pe_ratio", 1)
    pe_limit = sector_avg_pe * t["pe_max_vs_sector_multiple"]
    if stock.get("pe_ratio", 999) > pe_limit:
        reasons_failed.append(f"P/E too high vs sector average for {risk_tier} tier")

    if stock.get("peg_ratio", 999) > t["peg_max"]:
        reasons_failed.append(f"PEG ratio too high for {risk_tier} tier")

    if stock.get("pb_ratio", 999) > t["pb_max"]:
        reasons_failed.append(f"Price-to-book too high for {risk_tier} tier")

    if stock.get("debt_to_equity", 999) > t["debt_to_equity_max"]:
        reasons_failed.append(f"Debt-to-equity too high for {risk_tier} tier")

    if stock.get("roe", -999) < t["roe_min"]:
        reasons_failed.append(f"ROE below minimum for {risk_tier} tier")

    growth = stock.get("revenue_growth", -999)
    if growth < t["revenue_growth_min"] or growth > t["revenue_growth_max"]:
        reasons_failed.append(f"Revenue growth outside acceptable range for {risk_tier} tier")

    if stock.get("profit_margin_trend") == "declining":
        reasons_failed.append("profit margin trend declining")

    if stock.get("market_cap_tier") not in t["market_cap_tiers_allowed"]:
        reasons_failed.append(f"market cap tier not allowed for {risk_tier} tier")

    if stock.get("promoter_holding_trend") == "declining":
        reasons_failed.append("promoter/insider holding trend declining")

    return (len(reasons_failed) == 0, reasons_failed)


def passes_user_exclusions(stock: dict, excluded_sectors: list) -> tuple:
    """Layer C: user-specific sector/company exclusions, applied last.
    Matching is case-insensitive and whitespace-tolerant, since users may type
    'gold' when the stored sector is 'Gold' — a literal match would silently
    let the exclusion do nothing, which is worse than being lenient here."""
    normalized_excluded = {s.strip().lower() for s in (excluded_sectors or [])}
    stock_sector = (stock.get("sector") or "").strip().lower()
    if stock_sector in normalized_excluded:
        return (False, [f"sector '{stock.get('sector')}' excluded by user preference"])
    return (True, [])


def screen_stocks(all_stocks: list, risk_tier: str, excluded_sectors: list = None) -> dict:
    """
    Runs all three layers against every cached stock.
    Returns a dict with 'qualified' (list of stocks that passed all checks)
    and 'rejected' (list of {symbol, reasons} for transparency/debugging).
    """
    qualified = []
    rejected = []

    for stock in all_stocks:
        ok_a, fail_a = passes_universal_minimums(stock)
        if not ok_a:
            rejected.append({"symbol": stock["symbol"], "reasons": fail_a})
            continue

        ok_b, fail_b = passes_risk_tier_thresholds(stock, risk_tier)
        if not ok_b:
            rejected.append({"symbol": stock["symbol"], "reasons": fail_b})
            continue

        ok_c, fail_c = passes_user_exclusions(stock, excluded_sectors)
        if not ok_c:
            rejected.append({"symbol": stock["symbol"], "reasons": fail_c})
            continue

        qualified.append(stock)

    return {"qualified": qualified, "rejected": rejected}


# Risk tiers ordered loosest-constraint-last so the relaxation ladder below
# only ever *loosens* the bar (conservative user relaxing into moderate-tier
# thresholds), never the reverse.
_TIER_LADDER = ["conservative", "moderate", "aggressive"]


def screen_with_relaxation(all_stocks: list, risk_tier: str, excluded_sectors: list = None,
                            target_min_qualified: int = 8) -> dict:
    """
    Agentic behavior: rather than silently handing back the same tiny
    hand-picked shortlist every time (which is what makes recommendations
    feel identical regardless of the amount entered), this widens the
    search step by step — using the NEXT risk tier's thresholds as Layer B —
    only if the strict screen doesn't surface enough qualified names, and it
    always says so plainly so nothing is hidden from the user.

    Returns everything screen_stocks() returns, plus:
      "tier_used": the risk tier whose thresholds actually produced this list
      "relaxed": bool — True if we had to loosen past the user's own tier
    """
    start_idx = _TIER_LADDER.index(risk_tier) if risk_tier in _TIER_LADDER else 1
    result = None
    tier_used = risk_tier
    for tier in _TIER_LADDER[start_idx:]:
        result = screen_stocks(all_stocks, tier, excluded_sectors)
        tier_used = tier
        if len(result["qualified"]) >= target_min_qualified:
            break

    result = result or {"qualified": [], "rejected": []}
    result["tier_used"] = tier_used
    result["relaxed"] = tier_used != risk_tier
    return result
