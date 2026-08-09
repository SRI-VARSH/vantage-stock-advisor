

from datetime import date
from config import SAFETY_BUFFER, MIN_AGE


def calculate_age(dob_str: str) -> int:
    """dob_str format: YYYY-MM-DD. Age is always calculated live — never stored/updated manually."""
    dob = date.fromisoformat(dob_str)
    today = date.today()
    age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
    return age


def check_eligibility(dob_str: str) -> dict:
    """Hard gate: minors cannot get investment recommendations from this tool."""
    age = calculate_age(dob_str)
    if age < MIN_AGE:
        return {
            "eligible": False,
            "age": age,
            "message": (
                "This tool provides investment-related content only for users "
                f"{MIN_AGE}+ years old. Investing as a minor requires a guardian "
                "and a different process this tool doesn't cover. No investment "
                "recommendations can be generated for this profile."
            ),
        }
    return {"eligible": True, "age": age, "message": None}


def check_safety_buffer(profile: dict) -> dict:
    """
    Soft warning, not a block (Step 3 decision).
    Returns whether the user's safety net looks adequate, plus a warning message if not.
    Recommendation generation proceeds regardless of the result.
    """
    months_covered = profile.get("emergency_fund_months", 0) or 0
    has_debt = bool(profile.get("has_high_interest_debt"))

    warnings = []
    if months_covered < SAFETY_BUFFER["min_emergency_months"]:
        warnings.append(
            f"You currently have about {months_covered:.1f} months of expenses saved "
            f"as an emergency fund. A common guideline is {SAFETY_BUFFER['min_emergency_months']}+ "
            "months before investing significant amounts. Consider building this alongside investing."
        )
    if has_debt:
        warnings.append(
            "You've indicated you're carrying high-interest debt. Paying this down often "
            "provides a more certain 'return' than most investments, and is generally worth "
            "prioritizing alongside or before new investing."
        )

    return {
        "is_adequate": len(warnings) == 0,
        "warnings": warnings,
    }
