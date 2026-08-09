import allocator
import llm_reasoning
import screener
from config import STRATEGY_PROFILES


def run(profile: dict, amount_available: float, all_stocks: list) -> dict:
    """Runs the full agentic recommendation flow for one user + one amount.
    Returns a dict with `screen` (what was screened, and whether the screen
    had to be relaxed) and `strategies` (list of fully-built strategy dicts,
    each with its own equity_amount/picks/etc, in the order defined by
    STRATEGY_PROFILES), plus `comparison` (the plain-language explanation).
    """
    screen_result = screener.screen_with_relaxation(
        all_stocks, profile["risk_tier"], profile.get("excluded_sectors"),
        target_min_qualified=8,
    )

    strategies = []
    if screen_result["qualified"]:
        for spec in STRATEGY_PROFILES:
            allocation = allocator.decide_equity_allocation(
                amount_available,
                profile["risk_tier"],
                profile.get("time_horizon_years") or 5,
                profile.get("emergency_fund_months") or 0,
                bool(profile.get("has_high_interest_debt")),
                ceiling_multiplier=spec["ceiling_multiplier"],
            )
            portfolio = allocator.build_portfolio(
                screen_result["qualified"],
                allocation["equity_amount"],
                profile.get("existing_holdings") or {},
                per_stock_cap_pct=spec["per_stock_cap_pct"],
                min_picks=spec["min_picks"],
            )
            strategies.append({
                "id": spec["id"],
                "label": spec["label"],
                "tagline": spec["tagline"],
                "recommended": bool(spec.get("recommended")),
                **allocation,
                **portfolio,
            })

    comparison = None
    if strategies:
        comparison = llm_reasoning.compare_strategies(profile, amount_available, strategies)

    return {
        "screen": screen_result,
        "strategies": strategies,
        "comparison": comparison,
        "comparison_is_llm": llm_reasoning.is_available(),
    }
