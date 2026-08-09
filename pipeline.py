

from datetime import datetime, timedelta, timezone, time as dtime

from werkzeug.security import generate_password_hash, check_password_hash

import database
import data_layer
import screener
import safety
import allocator
import validator
import agent
from config import DATA_STALENESS_HOURS, TAX_RULES, DISCLAIMER, COUNTRY, STRATEGY_PROFILES, REFERENCE_INDICES

# NSE trading session, IST (UTC+5:30) — used to decide how aggressively to
# refresh the cache. This project only tracks NSE + a US-listed pool, and US
# market hours aren't modeled separately here; NSE hours are used as the
# "is *a* market open right now" signal since the two universes are refreshed
# together in one batch. Good enough for this project's purpose (not
# splitting refresh cadence per exchange); revisit if that ever matters.
IST = timezone(timedelta(hours=5, minutes=30))
MARKET_OPEN_IST = dtime(9, 15)
MARKET_CLOSE_IST = dtime(15, 30)
INTRADAY_REFRESH_MINUTES = 15   # refresh at most this often WHILE the market is open
POST_CLOSE_REFRESH_MINUTES = 45  # one more prompt refresh shortly after close, to pick up final settle prices


def _market_is_open(now_ist: datetime) -> bool:
    return now_ist.weekday() < 5 and MARKET_OPEN_IST <= now_ist.time() <= MARKET_CLOSE_IST


def _minutes_since_close(now_ist: datetime) -> float:
    close_dt = now_ist.replace(hour=MARKET_CLOSE_IST.hour, minute=MARKET_CLOSE_IST.minute, second=0, microsecond=0)
    return (now_ist - close_dt).total_seconds() / 60


def get_available_sectors() -> list:
    return sorted(set(data_layer.MOCK_SECTOR_MAP.values()))


def _build_profile_dict(form: dict) -> dict:
    monthly_expenses = float(form.get("monthly_expenses", 0) or 0)
    emergency_fund_amount = float(form.get("emergency_fund_amount", 0) or 0)
    emergency_fund_months = (
        round(emergency_fund_amount / monthly_expenses, 1) if monthly_expenses > 0 else 0
    )

    risk_tier = {"1": "conservative", "2": "moderate", "3": "aggressive"}.get(
        str(form.get("risk_choice")), "moderate"
    )

    return {
        "name": form["name"],
        "dob": form["dob"],
        "monthly_income": float(form.get("monthly_income", 0) or 0),
        "monthly_expenses": monthly_expenses,
        "emergency_fund_amount": emergency_fund_amount,
        "emergency_fund_months": emergency_fund_months,
        "has_high_interest_debt": bool(form.get("has_high_interest_debt", False)),
        "debt_amount": float(form.get("debt_amount", 0) or 0),
        "existing_net_worth": float(form.get("existing_net_worth", 0) or 0),
        "existing_holdings": {},
        "risk_tier": risk_tier,
        "primary_goal": form.get("primary_goal", ""),
        "time_horizon_years": int(form.get("time_horizon_years", 5) or 5),
        "excluded_sectors": form.get("excluded_sectors", []) or [],
    }


def signup(form: dict) -> dict:
    """
    form keys expected: name, dob, monthly_income, monthly_expenses,
    emergency_fund_amount, has_high_interest_debt (bool), debt_amount,
    existing_net_worth, risk_choice ('1'/'2'/'3'), primary_goal,
    time_horizon_years, excluded_sectors (list of str)

    Returns: {"ok": True, "user_id": int} or {"ok": False, "error": str}
    """
    elig = safety.check_eligibility(form["dob"])
    if not elig["eligible"]:
        return {"ok": False, "error": elig["message"]}

    profile = _build_profile_dict(form)
    user_id = database.create_user(profile)
    return {"ok": True, "user_id": user_id, "emergency_fund_months": profile["emergency_fund_months"]}


def register(form: dict) -> dict:
    """
    Full account creation used by the web UI: everything signup() does, plus a
    username/password so the person can log back in later without remembering a
    numeric user ID.

    Extra form keys required: username, password (min 6 chars, kept simple for the MVP).
    """
    username = (form.get("username") or "").strip()
    password = form.get("password") or ""

    if not username or len(username) < 3:
        return {"ok": False, "error": "Choose a username of at least 3 characters."}
    if len(password) < 6:
        return {"ok": False, "error": "Choose a password of at least 6 characters."}
    if database.username_exists(username):
        return {"ok": False, "error": "That username is already taken."}

    elig = safety.check_eligibility(form["dob"])
    if not elig["eligible"]:
        return {"ok": False, "error": elig["message"]}

    profile = _build_profile_dict(form)
    profile["username"] = username
    profile["password_hash"] = generate_password_hash(password)

    user_id = database.create_user(profile)
    return {
        "ok": True,
        "user_id": user_id,
        "name": profile["name"],
        "emergency_fund_months": profile["emergency_fund_months"],
    }


def login(username: str, password: str) -> dict:
    row = database.get_user_auth_row((username or "").strip())
    if not row or not row.get("password_hash"):
        return {"ok": False, "error": "Invalid username or password."}
    if not check_password_hash(row["password_hash"], password or ""):
        return {"ok": False, "error": "Invalid username or password."}

    profile = database.get_user(row["user_id"])
    return {"ok": True, "user_id": row["user_id"], "profile": profile}


def update_profile(user_id: int, updates: dict) -> dict:
    current = database.get_user(user_id)
    if not current:
        return {"ok": False, "error": "User not found."}

    # Emergency fund is stored as BOTH a raw amount (what the profile form
    # actually lets someone edit) and a derived "months of expenses" figure
    # (what the allocator reads). Whenever either the amount or the monthly
    # expenses changes, months must be recomputed here — otherwise editing
    # your profile silently stops updating the number the recommendation
    # engine actually uses, which is exactly the "why won't my emergency
    # fund reflect what I edited" bug this fixes.
    if "emergency_fund_amount" in updates or "monthly_expenses" in updates:
        amount = float(updates.get("emergency_fund_amount", current.get("emergency_fund_amount") or 0) or 0)
        expenses = float(updates.get("monthly_expenses", current.get("monthly_expenses") or 0) or 0)
        updates = dict(updates)
        updates["emergency_fund_amount"] = amount
        updates["emergency_fund_months"] = round(amount / expenses, 1) if expenses > 0 else 0

    database.update_profile(user_id, updates)
    return {"ok": True, "profile": database.get_user(user_id)}


def get_tracked_recommendations(user_id: int) -> dict:
    if not database.get_user(user_id):
        return {"ok": False, "error": "User not found."}
    return {"ok": True, "recommendations": database.get_all_recommendations_for_user(user_id)}


def refresh_data_if_needed() -> str:
    """Returns the data_as_of timestamp string, refreshing the cache if stale.

    Staleness is now market-hours-aware instead of one flat 48-hour window:
      - While the (NSE) market is open: refresh at most every
        INTRADAY_REFRESH_MINUTES, so prices don't drift far from reality
        during the trading session.
      - Just after close (within POST_CLOSE_REFRESH_MINUTES of 3:30pm IST):
        force one more refresh even if the last one was recent, to capture
        the actual final settle price for the day — this is specifically
        what fixes "I checked right after close and the price was stale":
        the old flat 48-hour window had no concept of "the session that
        matters just ended," so it could easily still be serving a
        mid-session price from hours earlier as if it were final.
      - Outside market hours otherwise (evenings/weekends): the last
        session's data doesn't change, so the normal DATA_STALENESS_HOURS
        window applies rather than refreshing needlessly.

    Also refreshes the reference indices (config.REFERENCE_INDICES) on the
    exact same cadence, from the exact same "is this actually stale right
    now" check — they're cached in the same table as stocks and share this
    one staleness decision instead of drifting out of sync with it.
    """
    cached = database.get_all_cached_stocks()
    now_ist = datetime.now(IST)
    needs_refresh = True
    data_as_of = "never refreshed"

    if cached:
        latest = max(s["last_updated"] for s in cached)
        data_as_of = latest
        age = datetime.utcnow() - datetime.fromisoformat(latest)

        if _market_is_open(now_ist):
            needs_refresh = age > timedelta(minutes=INTRADAY_REFRESH_MINUTES)
        elif 0 <= _minutes_since_close(now_ist) <= POST_CLOSE_REFRESH_MINUTES:
            # Just closed: make sure at least one refresh has happened since
            # today's close, regardless of the normal staleness window.
            last_updated_ist = datetime.fromisoformat(latest).replace(tzinfo=timezone.utc).astimezone(IST)
            close_today = now_ist.replace(hour=MARKET_CLOSE_IST.hour, minute=MARKET_CLOSE_IST.minute, second=0, microsecond=0)
            needs_refresh = last_updated_ist < close_today
        else:
            needs_refresh = age > timedelta(hours=DATA_STALENESS_HOURS)

    if needs_refresh:
        data_layer.refresh_universe(database.upsert_stock_cache)
        data_layer.refresh_indices(database.upsert_stock_cache, REFERENCE_INDICES)
        data_as_of = datetime.utcnow().isoformat()

    return data_as_of


def get_recommendation(user_id: int, amount_available: float) -> dict:
    """
    Runs the agentic recommendation flow for an existing user and returns a
    structured result with MULTIPLE strategy options (see agent.py) instead
    of one forced portfolio:
    {
      "ok": bool,
      "error": str | None,               # set if something stopped the flow (e.g. ineligible)
      "safety_warnings": [str],
      "zero_qualified": bool,
      "rejection_sample": [...],          # only if zero_qualified
      "screen_relaxed": bool,             # True if the screen had to widen past the user's tier
      "screen_tier_used": str,
      "strategies": [...],                # list of {id, label, tagline, picks, equity_amount, ...}
      "comparison": str,                  # plain-language comparison across strategies
      "comparison_is_llm": bool,
      "data_as_of": str,
      "amount_available": float,
    }
    """
    profile = database.get_user(user_id)
    if not profile:
        return {"ok": False, "error": "User not found."}

    elig = safety.check_eligibility(profile["dob"])
    if not elig["eligible"]:
        return {"ok": False, "error": elig["message"]}

    if amount_available <= 0:
        return {"ok": False, "error": "Enter an amount greater than zero."}

    data_as_of = refresh_data_if_needed()
    safety_check = safety.check_safety_buffer(profile)
    all_stocks = database.get_all_cached_stocks()

    agent_result = agent.run(profile, amount_available, all_stocks)
    screen_result = agent_result["screen"]

    base = {
        "ok": True,
        "error": None,
        "safety_warnings": safety_check["warnings"],
        "zero_qualified": not screen_result["qualified"],
        "rejection_sample": screen_result["rejected"][:5] if not screen_result["qualified"] else [],
        "screen_relaxed": screen_result.get("relaxed", False),
        "screen_tier_used": screen_result.get("tier_used", profile["risk_tier"]),
        "risk_tier": profile["risk_tier"],
        "time_horizon_years": profile.get("time_horizon_years"),
        "tax_note": TAX_RULES[COUNTRY]["note"],
        "disclaimer": DISCLAIMER,
        "data_as_of": data_as_of,
        "amount_available": amount_available,
    }

    if not screen_result["qualified"]:
        base["strategies"] = []
        base["comparison"] = None
        base["comparison_is_llm"] = False
        return base

    # Deterministic, auditable safety re-check on every strategy before it's
    # ever shown to the user — same validator, run once per strategy.
    qualified_symbols = {s["symbol"] for s in screen_result["qualified"]}
    for strat in agent_result["strategies"]:
        if not strat.get("picks"):
            continue
        validation = validator.validate_portfolio(
            strat["picks"], strat["equity_amount"], qualified_symbols,
            profile["excluded_sectors"], max_single_stock_pct=strat.get("per_stock_cap_pct"),
        )
        if not validation["is_valid"]:
            return {
                "ok": False,
                "error": f"Internal validation failed for the '{strat['label']}' strategy — "
                         "recommendation blocked for safety: " + "; ".join(validation["violations"]),
            }

    base["strategies"] = agent_result["strategies"]
    base["comparison"] = agent_result["comparison"]
    base["comparison_is_llm"] = agent_result["comparison_is_llm"]
    return base


def track_strategy(user_id: int, amount_available: float, strategy_id: str) -> dict:
    """Re-derives ONE specific strategy (deterministically, from the same
    inputs) and saves it as a tracked recommendation. Kept as a separate step
    from get_recommendation() on purpose: generating/comparing options should
    never itself write to the database — only the person's explicit choice
    to track one should."""
    result = get_recommendation(user_id, amount_available)
    if not result["ok"]:
        return result
    strat = next((s for s in result["strategies"] if s["id"] == strategy_id), None)
    if not strat or not strat.get("picks"):
        return {"ok": False, "error": "That strategy has no picks to track for this amount."}

    profile = database.get_user(user_id)
    rec_id = database.save_recommendation(
        user_id,
        {
            "amount_available": amount_available,
            "risk_tier": profile["risk_tier"],
            "strategy_id": strat["id"],
            "strategy_label": strat["label"],
            "equity_amount": strat["equity_amount"],
        },
        strat["picks"],
    )
    return {"ok": True, "rec_id": rec_id, "strategy": strat}
