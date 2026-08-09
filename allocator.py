

from config import HARD_CAPS, STRATEGY_PROFILES


def decide_equity_allocation(
    amount_available: float,
    risk_tier: str,
    time_horizon_years: int = 5,
    emergency_fund_months: float = 0,
    has_high_interest_debt: bool = False,
    ceiling_multiplier: float = 1.0,
) -> dict:
    """Step 4: decide how much of the user's money goes to direct equity at all,
    vs. staying in other layers (funds/FDs/etc — not built in this MVP, just noted).

    The risk-tier ceiling in HARD_CAPS is the baseline maximum for that risk
    tier. `ceiling_multiplier` lets a specific strategy (see STRATEGY_PROFILES
    in config.py) scale that baseline up or down — this is how "Steady",
    "Balanced" and "Focused" end up genuinely different amounts of equity
    exposure for the exact same profile and money, instead of one number
    being forced on everyone. It can never push the final % above 100.

    Within whatever ceiling results, two things scale the actual amount used:

    1. Time horizon — a standard "glide path" idea: even an aggressive
       investor with a 1-year horizon shouldn't necessarily put their full
       ceiling into equity, since there's less time to recover from a
       downturn.
    2. Existing financial cushion — if the emergency fund is already fully
       funded (SAFETY_BUFFER's minimum, or more) and there's no high-interest
       debt, the safety-net purpose the "remainder" is partly protecting is
       already met, so more of the ceiling is used regardless of horizon.
       This does NOT raise the ceiling itself — it only decides how much of
       the already-set ceiling gets used right now.
    """
    base_ceiling_pct = HARD_CAPS["max_equity_pct_of_total"][risk_tier]
    equity_ceiling_pct = min(100.0, round(base_ceiling_pct * ceiling_multiplier, 1))

    if time_horizon_years >= 10:
        horizon_factor = 1.0
    elif time_horizon_years >= 5:
        horizon_factor = 0.9
    elif time_horizon_years >= 2:
        horizon_factor = 0.75
    else:
        horizon_factor = 0.6

    cushioned = (emergency_fund_months >= 6) and not has_high_interest_debt
    if cushioned:
        horizon_factor = max(horizon_factor, 0.9)

    equity_pct_used = round(equity_ceiling_pct * horizon_factor, 1)
    equity_amount = amount_available * (equity_pct_used / 100)
    return {
        "equity_amount": round(equity_amount, 2),
        "equity_pct_used": equity_pct_used,
        "equity_ceiling_pct": equity_ceiling_pct,
        "base_ceiling_pct": base_ceiling_pct,
        "cushioned": cushioned,
        "remainder_amount": round(amount_available - equity_amount, 2),
        "note": (
            "Not a savings shortfall — this is a deliberate diversification "
            "choice. This app only picks individual stocks, and putting 100% "
            "of any amount into hand-picked single stocks is riskier than "
            "spreading some of it into a diversified vehicle like an index "
            "fund. The remainder is what we suggest keeping out of "
            "individual-stock picking, not money you're short on."
        ),
    }


def _rank_weighted_waterfill(ranked_symbols: list, total: float, cap: float) -> tuple:
    """Splits `total` across `ranked_symbols` (best-ranked first gets a
    larger initial share), capped per symbol at `cap`. Unlike a plain
    weighted split, this doesn't just cap-and-drop the overflow: whatever a
    cap blocks is redistributed onto the remaining not-yet-capped symbols,
    repeating until either the full amount is placed or every symbol is at
    its cap. Returns (amounts_dict, genuinely_unallocated_leftover) — the
    leftover is only ever > 0 if there simply aren't enough symbols to
    absorb `total` even with everyone at their cap."""
    amounts = {sym: 0.0 for sym in ranked_symbols}
    open_syms = list(ranked_symbols)
    remaining = total

    for _ in range(len(ranked_symbols) + 1):
        if not open_syms or remaining <= 0.01:
            break
        weights = {sym: (len(open_syms) - i) for i, sym in enumerate(open_syms)}
        weight_sum = sum(weights.values())
        still_open = []
        placed_this_round = 0.0
        for sym in open_syms:
            share = remaining * (weights[sym] / weight_sum)
            room = cap - amounts[sym]
            take = min(share, room)
            amounts[sym] += take
            placed_this_round += take
            if amounts[sym] < cap - 0.01:
                still_open.append(sym)
        remaining -= placed_this_round
        open_syms = still_open

    return amounts, max(remaining, 0.0)


def build_portfolio(qualified_stocks: list, equity_amount: float, existing_holdings: dict,
                     per_stock_cap_pct: float = None, min_picks: int = 5) -> dict:
    """
    Rule-based portfolio construction, run once per strategy:
      1. Filter out stocks the user is already heavily holding (avoid further over-concentration)
      2. Rank remaining candidates by a simple composite score
      3. Pick a starting number of stocks that SCALES CONTINUOUSLY with the
         amount available (not a few fixed buckets), so a bigger amount
         genuinely broadens the pool used, and a strategy asking for more
         names (min_picks) gets them whenever the candidate list allows.
      4. Water-fill the equity amount across them, capped per-stock at
         `per_stock_cap_pct` (defaults to HARD_CAPS max_single_stock_pct,
         always clamped below the absolute hard ceiling) — growing the pool
         of stocks used if capping would otherwise leave money unplaced, so
         the full equity amount actually gets allocated somewhere whenever
         the candidate list is large enough to support it.
    """
    if equity_amount < HARD_CAPS["min_amount_for_diversification"]:
        return {
            "picks": [],
            "message": (
                f"₹{equity_amount:,.0f} is too small to meaningfully diversify across "
                "individual stocks while respecting safe concentration limits. Consider "
                "a diversified index/mutual fund for this amount instead of direct stocks."
            ),
        }

    cap_pct = per_stock_cap_pct or HARD_CAPS["max_single_stock_pct"]
    cap_pct = min(cap_pct, HARD_CAPS["absolute_max_single_stock_pct"])

    # Step 1: avoid stocks user is already heavily concentrated in (simple heuristic:
    # skip if existing holding in that stock already exceeds the per-stock cap value)
    max_stock_value = equity_amount * (cap_pct / 100)
    candidates = [
        s for s in qualified_stocks
        if existing_holdings.get(s["symbol"], 0) < max_stock_value
    ]

    if not candidates:
        return {
            "picks": [],
            "message": "No qualifying stocks remain after accounting for your existing holdings "
                       "(to avoid further over-concentration). Consider reviewing your existing "
                       "positions or relaxing sector exclusions.",
        }

    # Step 2: simple composite score — higher ROE, positive growth, lower debt = better
    def score(s):
        return (
            s.get("roe", 0) * 1.0
            + s.get("revenue_growth", 0) * 0.5
            - s.get("debt_to_equity", 0) * 10
            - s.get("pe_ratio", 0) * 0.2
        )

    ranked = sorted(candidates, key=score, reverse=True)
    by_symbol = {s["symbol"]: s for s in ranked}

    # Continuous scaling: roughly one more name for every ~₹6,000 of equity
    # money, floored by the strategy's min_picks and by how tight the
    # per-stock cap is (a tighter cap mathematically *requires* more names
    # to place the same amount of money), and never more than the pool has.
    cap_driven_floor = int((100 / cap_pct) + 1) if cap_pct else min_picks
    start_n = max(min_picks, cap_driven_floor, round(equity_amount / 6000))
    start_n = max(1, min(start_n, len(ranked)))

    # Step 3 & 4: water-fill starting with `start_n` names, growing the pool
    # (up to every qualifying candidate) if the per-stock cap leaves a
    # genuine shortfall that more names could absorb.
    n = start_n
    amounts, unallocated = {}, equity_amount
    while True:
        active_symbols = [s["symbol"] for s in ranked[:n]]
        amounts, unallocated = _rank_weighted_waterfill(active_symbols, equity_amount, max_stock_value)
        if unallocated <= 1 or n >= len(ranked):
            break
        n = min(len(ranked), n + 5)

    picks = []
    for sym in [s["symbol"] for s in ranked[:n]]:
        amt = amounts.get(sym, 0.0)
        if amt <= 1:
            continue
        stock = by_symbol[sym]
        picks.append({
            "symbol": stock["symbol"],
            "company_name": stock.get("company_name", stock["symbol"]),
            "sector": stock.get("sector", "Unknown"),
            "amount": round(amt, 2),
            "price_at_rec": stock.get("price"),
            "currency": stock.get("currency", "INR"),
            "score_roe": round(stock.get("roe") or 0, 1),
            "score_growth": round(stock.get("revenue_growth") or 0, 1),
            "score_debt_to_equity": round(stock.get("debt_to_equity") or 0, 2),
            "score_pe": round(stock.get("pe_ratio") or 0, 1),
            "reasoning": (
                f"Passed the fundamental screen for your risk tier. "
                f"ROE {round(stock.get('roe') or 0, 1)}%, "
                f"revenue growth {round(stock.get('revenue_growth') or 0, 1)}%, "
                f"debt-to-equity {round(stock.get('debt_to_equity') or 0, 2)}, "
                f"P/E {round(stock.get('pe_ratio') or 0, 1)}."
            ),
        })

    # sort by amount descending for display (biggest conviction first)
    picks.sort(key=lambda p: p["amount"], reverse=True)
    allocated_total = sum(p["amount"] for p in picks)

    return {
        "picks": picks,
        "per_stock_cap_pct": cap_pct,
        "allocated_total": round(allocated_total, 2),
        "unallocated": round(equity_amount - allocated_total, 2),
        "message": (
            f"₹{equity_amount - allocated_total:,.0f} of the equity amount couldn't be "
            f"placed without breaching the {cap_pct:.0f}% single-stock "
            "cap, even after using every qualifying stock available. Consider a diversified "
            "fund for that portion, or trying a smaller amount."
        ) if (equity_amount - allocated_total) > 1 else None,
    }
