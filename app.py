

from functools import wraps
import os

from flask import Flask, request, jsonify, render_template, redirect, url_for, session, flash

import database
import pipeline
import history
import data_layer
from config import REFERENCE_INDICES, STRATEGY_PROFILES

app = Flask(__name__)

# In-memory "last recommendation seen" cache, keyed by user_id. Deliberately
# NOT stored in the database (a comparison the person is still weighing
# isn't a saved record yet — see pipeline.track_strategy) and NOT stored in
# the signed session cookie (three full strategies' worth of picks can
# easily exceed the ~4KB cookie limit). This is what makes navigating away
# to Overview and back keep showing the same result instead of losing it —
# it only clears when the person explicitly starts a new one, or the
# process restarts.
_LAST_RECOMMENDATION = {}

# Reads SECRET_KEY from the environment (set this in production / Docker —
# see docker-compose.yml and the README's Docker section). Falls back to a
# clearly-labeled dev placeholder ONLY for local runs without it set, and
# prints a one-time warning so it's never silently insecure.
_secret_key = os.environ.get("SECRET_KEY")
if not _secret_key:
    _secret_key = "vantage-dev-secret-change-before-deploying"
    print("WARNING: SECRET_KEY is not set — using an insecure dev placeholder. "
          "Set SECRET_KEY before deploying anywhere reachable by other people.")
app.secret_key = _secret_key
database.init_db()
database.backup_database()  # snapshot whatever was there before this run starts writing


# ----------------------------------------------------------------- helpers --
def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login_page"))
        return view(*args, **kwargs)
    return wrapped


@app.context_processor
def inject_session_user():
    user_id = session.get("user_id")
    profile = database.get_user(user_id) if user_id else None
    if user_id and not profile:
        # stale session pointing at a deleted user
        session.clear()
        profile = None
    return {"session_user": profile}


SECTOR_PALETTE = [
    "#29d3c0", "#6c8cff", "#f5b942", "#f2617a", "#8b6cff",
    "#3ddc97", "#ff9f6c", "#5cc8ff", "#e37bff", "#c4d452",
]


def _sector_color(sector, palette_index):
    return SECTOR_PALETTE[palette_index % len(SECTOR_PALETTE)]


def build_market_snapshot() -> dict:
    """Builds the homepage 'market pulse' content: a ticker tape, top movers,
    and sector performance, all from the stock universe already cached in
    stock_cache.

    change_pct now comes straight from the cache (data_layer.py — real
    previous-close-vs-current movement when USE_MOCK_DATA is off, computed
    ONCE per refresh) instead of being re-randomized on every single page
    view. See pipeline.refresh_data_if_needed for exactly when that cache is
    considered stale and re-pulled (market-hours-aware, not a flat window).
    """
    data_as_of = pipeline.refresh_data_if_needed()
    stocks = database.get_all_cached_stocks()

    rows = []
    for s in stocks:
        rows.append({
            "symbol": s["symbol"].replace(".NS", ""),
            "full_symbol": s["symbol"],
            "company_name": s["company_name"],
            "sector": s["sector"],
            "currency": s.get("currency") or "INR",
            "price": s["price"],
            "change_pct": s.get("change_pct") or 0,
        })

    if not rows:
        return {"has_data": False, "data_as_of": data_as_of}

    rows.sort(key=lambda r: r["change_pct"], reverse=True)
    gainers = [r for r in rows if r["change_pct"] > 0][:5]
    losers = sorted([r for r in rows if r["change_pct"] < 0], key=lambda r: r["change_pct"])[:5]
    gainers_count = sum(1 for r in rows if r["change_pct"] > 0)
    losers_count = sum(1 for r in rows if r["change_pct"] < 0)

    sector_totals, sector_counts = {}, {}
    for r in rows:
        sector_totals[r["sector"]] = sector_totals.get(r["sector"], 0) + r["change_pct"]
        sector_counts[r["sector"]] = sector_counts.get(r["sector"], 0) + 1
    sector_perf = sorted(
        ({"sector": sec, "avg_change": round(total / sector_counts[sec], 2)}
         for sec, total in sector_totals.items()),
        key=lambda x: x["avg_change"], reverse=True,
    )
    for i, s in enumerate(sector_perf):
        s["color"] = _sector_color(s["sector"], i)
    best_sector = sector_perf[0]["sector"] if sector_perf else "—"

    # Well-known reference indices (Nifty 50, Sensex, S&P 500, ...) — always
    # shown regardless of screening/exclusions, purely as a familiar anchor
    # point. Cached and refreshed the same way as the stocks above (real
    # data via yfinance when USE_MOCK_DATA is off — see
    # data_layer.get_index_fundamentals) — no per-request randomness here
    # either. Clickable through to their own detail/chart page, same as any
    # stock, since they're stored in the same cache with asset_type='index'.
    indices = []
    cached_indices = {i["symbol"]: i for i in database.get_all_cached_indices()}
    for idx in REFERENCE_INDICES:
        cached = cached_indices.get(idx["symbol"])
        if cached:
            indices.append({**idx, "level": cached["price"], "change_pct": cached.get("change_pct") or 0})
        else:
            indices.append({**idx, "level": idx["base_level"], "change_pct": 0})

    # Ticker scroll speed: readable regardless of universe size. ~70px per
    # ticker item, targeting a slow, readable ~28px/sec crawl (was a fixed
    # 45s regardless of how many items were in it, which got unreadably
    # fast as the universe grew).
    ticker_duration = max(50, round(len(rows) * 70 / 28))

    return {
        "has_data": True,
        "data_as_of": data_as_of,
        "is_mock": data_layer.USE_MOCK_DATA,
        "ticker": rows,
        "ticker_duration": ticker_duration,
        "gainers": gainers,
        "losers": losers,
        "gainers_count": gainers_count,
        "losers_count": losers_count,
        "best_sector": best_sector,
        "sector_perf": sector_perf[:8],
        "indices": indices,
    }


def _build_strategy_view(strat: dict, amount_available: float) -> dict:
    """Fills in everything the template needs to draw ONE strategy card
    (percentages, colors, sector breakdown, donut gradient) without doing
    math in Jinja. Mirrors the single-portfolio version this replaced, just
    run once per strategy now instead of once total."""
    equity = strat.get("equity_amount") or 0
    remainder = strat.get("remainder_amount") or 0
    total = equity + remainder or 1
    strat["equity_pct"] = round((equity / total) * 100)
    strat["total_amount"] = equity + remainder

    picks = strat.get("picks") or []
    sector_order, sector_totals = [], {}
    for pick in picks:
        pick["pct_of_equity"] = round((pick["amount"] / equity) * 100, 1) if equity else 0
        if pick["sector"] not in sector_totals:
            sector_order.append(pick["sector"])
        sector_totals[pick["sector"]] = sector_totals.get(pick["sector"], 0) + pick["amount"]

    sector_breakdown = []
    for i, sector in enumerate(sector_order):
        amt = sector_totals[sector]
        sector_breakdown.append({
            "sector": sector, "amount": amt,
            "pct": round((amt / equity) * 100, 1) if equity else 0,
            "color": _sector_color(sector, i),
        })
    color_by_sector = {row["sector"]: row["color"] for row in sector_breakdown}
    for pick in picks:
        pick["color"] = color_by_sector.get(pick["sector"], SECTOR_PALETTE[0])

    strat["sector_breakdown"] = sector_breakdown
    strat["largest_pick"] = max(picks, key=lambda p: p["amount"]) if picks else None
    strat["donut_gradient"] = (
        f"var(--accent) 0% {strat['equity_pct']}%, var(--border) {strat['equity_pct']}% 100%"
    )
    return strat


def build_agent_view(result: dict, tracked_strategy_ids: set = None) -> dict:
    """Turns pipeline.get_recommendation()'s raw agentic result (multiple
    strategies) into everything dashboard_recommend.html needs to render
    every strategy card plus the cross-strategy comparison."""
    if not result.get("ok") or result.get("zero_qualified") or not result.get("strategies"):
        return result

    tracked_strategy_ids = tracked_strategy_ids or set()
    for strat in result["strategies"]:
        _build_strategy_view(strat, result["amount_available"])
        strat["is_tracked"] = strat["id"] in tracked_strategy_ids
    return result


# -------------------------------------------------------------- top level --
@app.route("/")
def root():
    if session.get("user_id"):
        return redirect(url_for("dashboard_overview"))
    return redirect(url_for("login_page"))


# --------------------------------------------------------------------- auth --
@app.route("/login", methods=["GET", "POST"])
def login_page():
    if session.get("user_id"):
        return redirect(url_for("dashboard_overview"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        result = pipeline.login(username, password)
        if not result["ok"]:
            flash(result["error"], "error")
            return render_template("login.html", prefill_username=username), 401
        session.clear()
        session["user_id"] = result["user_id"]
        return redirect(url_for("dashboard_overview"))

    return render_template("login.html", prefill_username="")


@app.route("/signup", methods=["GET", "POST"])
def signup_page():
    if session.get("user_id"):
        return redirect(url_for("dashboard_overview"))

    sectors = pipeline.get_available_sectors()

    if request.method == "POST":
        form = request.form
        name = form.get("name", "").strip()
        dob = form.get("dob", "")
        username = form.get("username", "").strip()
        password = form.get("password", "")

        if not name or not dob:
            flash("Name and date of birth are required.", "error")
            return render_template("signup.html", sectors=sectors, prefill=form.to_dict()), 400

        payload = {
            "name": name,
            "dob": dob,
            "username": username,
            "password": password,
            "monthly_income": form.get("monthly_income", 0),
            "monthly_expenses": form.get("monthly_expenses", 0),
            "emergency_fund_amount": form.get("emergency_fund_amount", 0),
            "has_high_interest_debt": form.get("has_high_interest_debt") == "on",
            "debt_amount": form.get("debt_amount", 0),
            "existing_net_worth": form.get("existing_net_worth", 0),
            "risk_choice": form.get("risk_choice", "2"),
            "primary_goal": form.get("primary_goal", ""),
            "time_horizon_years": form.get("time_horizon_years", 5),
            "excluded_sectors": form.getlist("excluded_sectors"),
        }
        result = pipeline.register(payload)
        if not result["ok"]:
            flash(result["error"], "error")
            return render_template("signup.html", sectors=sectors, prefill=payload), 400

        session.clear()
        session["user_id"] = result["user_id"]
        flash("Welcome to Vantage — your account is ready.", "success")
        return redirect(url_for("dashboard_overview"))

    return render_template("signup.html", sectors=sectors, prefill={})


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login_page"))


# ---------------------------------------------------------------- dashboard --
@app.route("/dashboard")
@login_required
def dashboard_overview():
    market = build_market_snapshot()
    return render_template("dashboard_overview.html", active="overview", market=market)


@app.route("/dashboard/recommend", methods=["GET", "POST"])
@login_required
def dashboard_recommend():
    user_id = session["user_id"]
    result = None
    submitted_amount = ""

    if request.method == "POST" and request.form.get("form_action") == "new":
        _LAST_RECOMMENDATION.pop(user_id, None)
        return redirect(url_for("dashboard_recommend"))

    if request.method == "POST":
        submitted_amount = request.form.get("amount", "")
        try:
            amount = float(submitted_amount)
            if amount <= 0:
                raise ValueError
        except (TypeError, ValueError):
            flash("Enter an amount greater than zero.", "error")
        else:
            raw = pipeline.get_recommendation(user_id, amount)
            if not raw["ok"]:
                flash(raw["error"], "error")
            else:
                result = build_agent_view(raw)
                # bug fix: a recommendation used to vanish the moment you
                # navigated to another tab and came back. It now stays put
                # (per user) until a new amount is submitted or explicitly
                # cleared via "Start a new recommendation".
                _LAST_RECOMMENDATION[user_id] = {
                    "result": result, "amount": amount, "tracked_ids": set(),
                }
    elif user_id in _LAST_RECOMMENDATION:
        cached = _LAST_RECOMMENDATION[user_id]
        result = build_agent_view(cached["result"], cached["tracked_ids"])
        submitted_amount = str(int(cached["amount"])) if cached["amount"] == int(cached["amount"]) else str(cached["amount"])

    return render_template(
        "dashboard_recommend.html", active="recommend",
        result=result, submitted_amount=submitted_amount,
    )


@app.route("/dashboard/recommend/track", methods=["POST"])
@login_required
def dashboard_recommend_track():
    user_id = session["user_id"]
    strategy_id = request.form.get("strategy_id", "")
    try:
        amount = float(request.form.get("amount", ""))
    except (TypeError, ValueError):
        flash("Couldn't find that recommendation amount — try generating it again.", "error")
        return redirect(url_for("dashboard_recommend"))

    outcome = pipeline.track_strategy(user_id, amount, strategy_id)
    if not outcome["ok"]:
        flash(outcome["error"], "error")
    else:
        flash(f"'{outcome['strategy']['label']}' added to Tracked.", "success")
        cached = _LAST_RECOMMENDATION.get(user_id)
        if cached and cached["amount"] == amount:
            cached["tracked_ids"].add(strategy_id)
    return redirect(url_for("dashboard_recommend"))


@app.route("/dashboard/tracked")
@login_required
def dashboard_tracked():
    recs = database.get_all_recommendations_for_user(session["user_id"])
    all_sectors = set()
    total_recommended = 0.0
    total_invested = 0.0
    confirmed_count = 0
    for rec in recs:
        rec["total_amount"] = sum(p.get("amount", 0) for p in rec["recommended_picks"])
        rec["is_confirmed"] = rec["confirmed_picks"] is not None
        total_recommended += rec["total_amount"]
        if rec["is_confirmed"]:
            total_invested += sum(p.get("amount", 0) for p in rec["confirmed_picks"])
            confirmed_count += 1
        for p in rec["recommended_picks"]:
            all_sectors.add(p["sector"])

    summary = {
        "total_invested": total_invested,
        "total_recommended": total_recommended,
        "confirmed_count": confirmed_count,
        "count": len(recs),
        "sector_count": len(all_sectors),
        "avg_amount": (total_recommended / len(recs)) if recs else 0,
    }
    return render_template("dashboard_tracked.html", active="tracked", recommendations=recs, summary=summary)


@app.route("/dashboard/tracked/<int:rec_id>/confirm", methods=["POST"])
@login_required
def dashboard_confirm_investment(rec_id):
    ok = database.confirm_recommendation_for_user(session["user_id"], rec_id)
    if ok:
        flash("Marked as invested — added to your total invested.", "success")
    else:
        flash("Couldn't find that recommendation.", "error")
    return redirect(url_for("dashboard_tracked"))


@app.route("/dashboard/profile", methods=["GET", "POST"])
@login_required
def dashboard_profile():
    sectors = pipeline.get_available_sectors()

    if request.method == "POST":
        form = request.form
        updates = {
            "name": form.get("name", "").strip(),
            "primary_goal": form.get("primary_goal", ""),
            "monthly_income": float(form.get("monthly_income") or 0),
            "monthly_expenses": float(form.get("monthly_expenses") or 0),
            "emergency_fund_amount": float(form.get("emergency_fund_amount") or 0),
            "existing_net_worth": float(form.get("existing_net_worth") or 0),
            "time_horizon_years": int(form.get("time_horizon_years") or 5),
            "risk_tier": form.get("risk_tier", "moderate"),
            "has_high_interest_debt": form.get("has_high_interest_debt") == "on",
            "excluded_sectors": form.getlist("excluded_sectors"),
        }
        result = pipeline.update_profile(session["user_id"], updates)
        if not result["ok"]:
            flash(result["error"], "error")
        else:
            flash("Profile updated.", "success")
        return redirect(url_for("dashboard_profile"))

    profile = database.get_user(session["user_id"])
    return render_template("dashboard_profile.html", active="profile", profile=profile, sectors=sectors)


# ------------------------------------------------------------------ stocks --
@app.route("/dashboard/stocks")
@login_required
def dashboard_stocks():
    """Browse the full screened universe, with filters — the transparency
    layer the recommendation cards link back into ('why is this in my
    portfolio' -> see it sitting in the full list next to everything else
    that was and wasn't picked).

    Sector/cap-tier/region filters are all multi-select checkboxes (a person
    comparing IT + Banking, or India + US names, shouldn't have to run the
    filter twice) — so each arrives as a list via getlist(), and a stock
    matches if it's in the selected set (or if nothing's selected for that
    filter, everything matches)."""
    pipeline.refresh_data_if_needed()
    all_stocks = database.get_all_cached_stocks()

    sectors_sel = request.args.getlist("sector")
    cap_tiers_sel = request.args.getlist("cap_tier")
    regions_sel = request.args.getlist("region")
    q = request.args.get("q", "").strip().lower()
    sort = request.args.get("sort", "name")

    rows = []
    for s in all_stocks:
        rows.append({**s, "symbol_short": s["symbol"].replace(".NS", ""),
                     "change_pct": s.get("change_pct") or 0})

    if sectors_sel:
        rows = [r for r in rows if r["sector"] in sectors_sel]
    if cap_tiers_sel:
        rows = [r for r in rows if r.get("market_cap_tier") in cap_tiers_sel]
    if regions_sel:
        rows = [r for r in rows if r.get("region") in regions_sel]
    if q:
        rows = [r for r in rows if q in r["company_name"].lower() or q in r["symbol"].lower()]

    sort_keys = {
        "name": lambda r: r["company_name"],
        "price": lambda r: -(r["price"] or 0),
        "change": lambda r: -(r["change_pct"] or 0),
        "roe": lambda r: -(r.get("roe") or 0),
        "market_cap": lambda r: -(r.get("market_cap_cr") or 0),
    }
    rows.sort(key=sort_keys.get(sort, sort_keys["name"]))

    sectors = pipeline.get_available_sectors()
    cap_tiers = ["large", "mid", "small"]
    regions = ["India", "US/Global"]
    # The exact querystring behind the current filtered list, so a link into
    # a stock's detail page can carry it along and "Back to Stocks" restores
    # this same filtered view instead of resetting to an unfiltered one.
    filters_qs = request.query_string.decode()
    return render_template(
        "dashboard_stocks.html", active="stocks", stocks=rows,
        sectors=sectors, cap_tiers=cap_tiers, regions=regions,
        filters={"sectors": sectors_sel, "cap_tiers": cap_tiers_sel, "regions": regions_sel, "q": q, "sort": sort},
        filters_qs=filters_qs,
    )


@app.route("/dashboard/stocks/<path:symbol>")
@login_required
def dashboard_stock_detail(symbol):
    stock = database.get_cached_stock(symbol)
    if not stock:
        flash("That stock isn't in the tracked universe.", "error")
        return redirect(url_for("dashboard_stocks"))

    change_pct = stock.get("change_pct") or 0
    # Carries the filtered-list querystring back, so "Back to Stocks" (and
    # browser back-button muscle memory reinforced by this same link)
    # restores exactly the filters that were active before clicking in,
    # instead of resetting to the unfiltered list.
    back_qs = request.args.get("ref", "")
    back_url = url_for("dashboard_stocks") + (f"?{back_qs}" if back_qs else "")

    return render_template(
        "dashboard_stock_detail.html", active="stocks", stock=stock,
        change_pct=change_pct, back_url=back_url,
    )


@app.route("/api/history/<path:symbol>")
@login_required
def api_history(symbol):
    stock = database.get_cached_stock(symbol)
    if not stock:
        return jsonify({"ok": False, "error": "Unknown symbol."}), 404
    range_key = request.args.get("range", "1m")
    points = history.get_history(symbol, stock["price"], range_key)
    return jsonify({"ok": True, "symbol": symbol, "range": range_key, "points": points,
                     "currency": stock.get("currency", "INR")})


# ------------------------------------------------------ JSON API (optional) --
# Kept for programmatic / future use (e.g. a future mobile client). The web
# UI above no longer depends on these — it uses real form posts + redirects.
@app.route("/api/sectors", methods=["GET"])
def api_sectors():
    return jsonify({"sectors": pipeline.get_available_sectors()})


@app.route("/api/signup", methods=["POST"])
def api_signup():
    form = request.get_json(force=True)
    result = pipeline.signup(form)
    return jsonify(result), 200 if result["ok"] else 400


@app.route("/api/auth/register", methods=["POST"])
def api_register():
    form = request.get_json(force=True)
    result = pipeline.register(form)
    return jsonify(result), 200 if result["ok"] else 400


@app.route("/api/auth/login", methods=["POST"])
def api_login():
    body = request.get_json(force=True)
    result = pipeline.login(body.get("username"), body.get("password"))
    return jsonify(result), 200 if result["ok"] else 401


@app.route("/api/profile/<int:user_id>", methods=["PUT"])
def api_update_profile(user_id):
    updates = request.get_json(force=True)
    result = pipeline.update_profile(user_id, updates)
    return jsonify(result), 200 if result["ok"] else 404


@app.route("/api/tracked/<int:user_id>", methods=["GET"])
def api_tracked(user_id):
    result = pipeline.get_tracked_recommendations(user_id)
    return jsonify(result), 200 if result["ok"] else 404


@app.route("/api/recommend", methods=["POST"])
def api_recommend():
    body = request.get_json(force=True)
    try:
        user_id = int(body["user_id"])
        amount = float(body["amount_available"])
    except (KeyError, ValueError, TypeError):
        return jsonify({"ok": False, "error": "Invalid user_id or amount."}), 400
    result = pipeline.get_recommendation(user_id, amount)
    return jsonify(result), 200 if result["ok"] else 400


@app.route("/api/user/<int:user_id>", methods=["GET"])
def api_get_user(user_id):
    profile = database.get_user(user_id)
    if not profile:
        return jsonify({"ok": False, "error": "User not found."}), 404
    return jsonify({"ok": True, "profile": profile})


if __name__ == "__main__":
    # 0.0.0.0 (not 127.0.0.1) is required so the app is reachable from
    # outside its container when run under Docker — see Dockerfile/
    # docker-compose.yml. PORT is configurable via env for the same reason
    # (platforms like Render/Railway inject their own PORT at runtime).
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
