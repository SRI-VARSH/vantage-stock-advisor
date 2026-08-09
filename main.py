

import database
import pipeline
import safety


def signup_flow() -> int:
    print("\n--- New User Signup ---")
    name = input("Name: ").strip()
    dob = input("Date of birth (YYYY-MM-DD): ").strip()

    elig = safety.check_eligibility(dob)
    if not elig["eligible"]:
        print(f"\n{elig['message']}")
        raise SystemExit(0)

    monthly_income = input("Approx monthly income (₹): ") or 0
    monthly_expenses = input("Approx monthly expenses (₹): ") or 0

    emergency_fund_amount = input(
        "Total ₹ amount you currently have set aside as an emergency fund (0 if none): "
    ) or 0

    has_debt = input("Do you have high-interest debt (credit card etc)? (y/n): ").strip().lower() == "y"
    debt_amount = (input("Approx debt amount (₹): ") or 0) if has_debt else 0
    existing_net_worth = input("Current total investments/net worth (₹, 0 if none): ") or 0

    print("\nRisk tolerance — if your investment dropped 20% in a month, you would:")
    print("  1. Sell immediately to avoid further loss")
    print("  2. Feel uneasy but hold and wait it out")
    print("  3. See it as a buying opportunity and consider investing more")
    risk_choice = input("Choose 1/2/3: ").strip()

    primary_goal = input("Primary goal (e.g. 'long-term wealth', 'growth in 5 years'): ").strip()
    time_horizon = input("Time horizon in years: ") or 5

    sample_sectors = pipeline.get_available_sectors()
    print(f"  (Sectors this tool currently covers: {', '.join(sample_sectors)})")
    excluded = input("Any of these sectors to exclude (comma-separated, or blank): ").strip()
    excluded_sectors = [s.strip() for s in excluded.split(",") if s.strip()]

    form = {
        "name": name, "dob": dob,
        "monthly_income": monthly_income, "monthly_expenses": monthly_expenses,
        "emergency_fund_amount": emergency_fund_amount,
        "has_high_interest_debt": has_debt, "debt_amount": debt_amount,
        "existing_net_worth": existing_net_worth,
        "risk_choice": risk_choice, "primary_goal": primary_goal,
        "time_horizon_years": time_horizon, "excluded_sectors": excluded_sectors,
    }
    result = pipeline.signup(form)
    if not result["ok"]:
        print(f"\n{result['error']}")
        raise SystemExit(0)

    print(f"\nSignup complete. Your user ID is {result['user_id']} (save this to log in next time).")
    print(f"(That's about {result['emergency_fund_months']} months of expenses covered.)")
    return result["user_id"]


def run_recommendation(user_id: int):
    profile = database.get_user(user_id)
    if not profile:
        print("User not found.")
        return

    amount_available = float(input("\nHow much are you looking to invest this time (₹)? ") or 0)

    print("\nChecking/refreshing stock data cache if needed...")
    result = pipeline.get_recommendation(user_id, amount_available)

    if not result["ok"]:
        print(f"\n{result['error']}")
        return

    print("\n" + "=" * 70)

    if result["safety_warnings"]:
        print("Worth considering first:")
        for w in result["safety_warnings"]:
            print(f"  - {w}")
        print()

    if result["zero_qualified"]:
        print("No stocks currently meet the criteria for your profile. Sample reasons:")
        for r in result["rejection_sample"]:
            print(f"  - {r['symbol']}: {', '.join(r['reasons'])}")
        print("\nTry relaxing a sector exclusion, or a different amount.")
        print("=" * 70)
        return

    print(
        f"Illustrative allocation across {len(result['strategies'])} strategy option(s) — "
        f"this app now suggests a few different ways to use this amount instead of forcing one:"
    )
    print()
    for strat in result["strategies"]:
        print(f"--- {strat['label']} ({strat['equity_pct_used']}% to equity) ---")
        print(f"    {strat['tagline']}")
        if not strat["picks"]:
            print(f"    {strat.get('message', 'No picks for this amount under this strategy.')}")
        else:
            for p in strat["picks"]:
                print(f"  • {p['company_name']} ({p['symbol']}) — ~₹{p['amount']:,.0f} [{p['sector']}]")
                print(f"    {p['reasoning']}")
        print(f"    Remainder not put toward direct equity in this strategy: ₹{strat['remainder_amount']:,.0f}")
        print()

    print(f"Data as of: {result['data_as_of']}")
    print("=" * 70)
    print(
        "\n(Nothing is saved to your tracked list from the CLI yet — pick a strategy in the "
        "web app's Recommend page and use 'Track this strategy' to save it.)"
    )


def main():
    database.init_db()
    print("=== Stock Advisor Agent (MVP) — CLI ===")
    choice = input("New user or existing? (new/existing): ").strip().lower()

    if choice == "new":
        user_id = signup_flow()
    else:
        user_id = int(input("Enter your user ID: ").strip())
        if not database.get_user(user_id):
            print("User not found.")
            return

    run_recommendation(user_id)


if __name__ == "__main__":
    main()
