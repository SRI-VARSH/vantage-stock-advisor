

from datetime import datetime
from config import DISCLAIMER, TAX_RULES, COUNTRY


def format_recommendation(profile: dict, safety_check: dict, allocation_decision: dict,
                           portfolio_result: dict, data_as_of: str) -> str:
    lines = []

    # 1. Safety warning first, if any
    if not safety_check["is_adequate"]:
        lines.append("⚠️  A couple of things worth considering first:")
        for w in safety_check["warnings"]:
            lines.append(f"   - {w}")
        lines.append("")

    # 2. Reasoning summary
    lines.append(
        f"Based on your profile ({profile['risk_tier']} risk tier, "
        f"goal: {profile.get('primary_goal', 'long-term growth')}), here's an illustrative "
        f"allocation approach for the ₹{allocation_decision['equity_amount']:,.0f} suggested "
        f"for direct equity out of your available amount:"
    )
    lines.append("")

    # 3. Picks or fallback message
    if portfolio_result.get("message") and not portfolio_result["picks"]:
        lines.append(portfolio_result["message"])
    else:
        for p in portfolio_result["picks"]:
            lines.append(
                f"  • {p['company_name']} ({p['symbol']}) — ~₹{p['amount']:,.0f} "
                f"[{p['sector']}]\n"
                f"    {p['reasoning']}"
            )
        lines.append("")
        lines.append(
            f"Suggested remainder (₹{allocation_decision['remainder_amount']:,.0f}): "
            f"{allocation_decision['note']}"
        )

    # 4. Tax awareness note (Step 11 - informational only)
    lines.append("")
    lines.append(f"Tax note ({COUNTRY}): {TAX_RULES[COUNTRY]['note']}")

    # 5. Data freshness
    lines.append("")
    lines.append(f"Data as of: {data_as_of}")

    # 6. Disclaimer
    lines.append("")
    lines.append(DISCLAIMER)

    # 7. Tracking notice
    lines.append("")
    lines.append(
        "This recommendation has been logged. Next time you use this tool, "
        "you'll be asked whether you actually acted on it (fully, partially, or not at all) "
        "so future recommendations can account for what you really hold."
    )

    return "\n".join(lines)


def format_rejection_report(rejected: list, limit: int = 5) -> str:
    """Shown when zero or very few stocks qualify — transparency instead of silently
    lowering standards (Step 8 edge case)."""
    lines = ["No stocks currently meet the criteria for your profile. Sample reasons:"]
    for r in rejected[:limit]:
        lines.append(f"  - {r['symbol']}: {', '.join(r['reasons'])}")
    lines.append(
        "\nWould you like to relax a specific constraint (e.g. allow mid-cap stocks, "
        "or remove a sector exclusion)? None of the standards were silently lowered to force a result."
    )
    return "\n".join(lines)
