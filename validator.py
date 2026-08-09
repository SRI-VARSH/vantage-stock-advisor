

from config import HARD_CAPS


def validate_portfolio(picks: list, equity_amount: float, qualified_symbols: set,
                        excluded_sectors: list, max_single_stock_pct: float = None) -> dict:
    violations = []
    cap_pct = max_single_stock_pct or HARD_CAPS["max_single_stock_pct"]
    cap_pct = min(cap_pct, HARD_CAPS["absolute_max_single_stock_pct"])

    total_allocated = sum(p["amount"] for p in picks)
    max_per_stock = equity_amount * (cap_pct / 100)

    # Check 1: every picked stock actually exists in the qualified shortlist
    for p in picks:
        if p["symbol"] not in qualified_symbols:
            violations.append(f"{p['symbol']} is not in the qualified shortlist (rejected)")

    # Check 2: no single stock exceeds the concentration cap
    for p in picks:
        if p["amount"] > max_per_stock + 0.01:  # small float tolerance
            violations.append(
                f"{p['symbol']} amount ₹{p['amount']:.0f} exceeds the "
                f"{cap_pct:.0f}% single-stock cap (₹{max_per_stock:.0f})"
            )

    # Check 3: total allocated does not exceed the equity amount available
    if total_allocated > equity_amount + 0.01:
        violations.append(
            f"Total allocated ₹{total_allocated:.0f} exceeds available equity amount ₹{equity_amount:.0f}"
        )

    # Check 4: no excluded sector present
    for p in picks:
        if p.get("sector") in (excluded_sectors or []):
            violations.append(f"{p['symbol']} is in an excluded sector ({p.get('sector')})")

    return {
        "is_valid": len(violations) == 0,
        "violations": violations,
    }
