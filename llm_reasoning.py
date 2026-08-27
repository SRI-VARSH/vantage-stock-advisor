
import json
import os
from dotenv import load_dotenv

load_dotenv()
MODEL = "gemini-3.6-flash"


def _client():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return None
    try:
        from google import genai
    except ImportError:
        return None
    try:
        return genai.Client(api_key=api_key)
    except Exception:
        return None


def is_available() -> bool:
    return _client() is not None


def _fallback_compare(profile: dict, strategies: list) -> str:
    names = ", ".join(s["label"] for s in strategies)
    return (
        f"Based on your {profile.get('risk_tier', 'moderate')} risk tier and "
        f"{profile.get('time_horizon_years', 5)}-year horizon, here are three ways to put this "
        f"amount to work: {names}. Each uses a different share of your money in direct equity "
        "and a different number of stocks — review the numbers on each card and pick the "
        "trade-off you're most comfortable with. None of these is the 'right' answer; they're "
        "options, not a single directive."
    )


def compare_strategies(profile: dict, amount: float, strategies: list) -> str:
    """Returns a short paragraph comparing the strategies for this specific
    person and amount. `strategies` is the list of already-computed strategy
    dicts (label, equity_amount, equity_pct_used, picks count, per_stock_cap_pct)."""
    client = _client()
    if not client:
        return _fallback_compare(profile, strategies)

    slim = [
        {
            "label": s["label"],
            "equity_amount": s.get("equity_amount"),
            "equity_pct_used": s.get("equity_pct_used"),
            "num_picks": len(s.get("picks", [])),
            "per_stock_cap_pct": s.get("per_stock_cap_pct"),
            "top_sectors": sorted({p["sector"] for p in s.get("picks", [])})[:5],
        }
        for s in strategies
    ]
    prompt = (
        "You are an assistant inside a personal equity-advisor app. A user has entered an "
        f"amount of ₹{amount:,.0f} to invest. Their profile: risk tier="
        f"{profile.get('risk_tier')}, time horizon={profile.get('time_horizon_years')} years, "
        f"primary goal={profile.get('primary_goal') or 'not specified'}, "
        f"emergency fund months={profile.get('emergency_fund_months')}, "
        f"high-interest debt={profile.get('has_high_interest_debt')}.\n\n"
        f"Three portfolio strategies were already computed deterministically (do not change "
        f"the numbers, only explain them): {json.dumps(slim)}\n\n"
        "In under 120 words, write a plain-language paragraph comparing the three strategies "
        "for THIS person specifically — what trade-off each one represents, and what kind of "
        "person each suits. Do not recommend one over the others as 'the answer' — present them "
        "as options they get to choose between. No markdown, no bullet points, just prose. "
        "Never claim certainty about future returns."
    )
    try:
        resp = client.models.generate_content(model=MODEL, contents=prompt)
        text = (resp.text or "").strip()
        return text or _fallback_compare(profile, strategies)
    except Exception:
        return _fallback_compare(profile, strategies)
