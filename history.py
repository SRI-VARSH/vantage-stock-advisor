

import random
from datetime import date, datetime, timedelta

RANGE_DAYS = {
    "1w": 7, "2w": 14, "3w": 21, "1m": 30, "2m": 60,
    "3m": 90, "6m": 180, "1y": 365,
}


def _get_intraday_history(symbol: str, current_price: float) -> list:
    """'1D' range: a same-day intraday walk across a standard trading
    session (9:15am–3:30pm), 15-minute steps, ending exactly at the current
    cached price — same deterministic/anchored approach as the daily walk
    below, just at session granularity instead of day granularity."""
    if not current_price or current_price <= 0:
        return []
    daily_vol = random.Random(f"{symbol}-intraday-vol").uniform(0.0015, 0.004)
    session_start = datetime.combine(date.today(), datetime.min.time()).replace(hour=9, minute=15)
    steps = 25  # 9:15 -> 15:30 in 15-min increments
    prices = [current_price]
    price = current_price
    for i in range(steps):
        step_rnd = random.Random(f"{symbol}-intraday-{i}")
        drift = step_rnd.uniform(-daily_vol, daily_vol)
        price = price / (1 + drift)
        prices.append(round(price, 2))
    prices.reverse()
    points = []
    for i, p in enumerate(prices):
        t = session_start + timedelta(minutes=15 * i)
        points.append({"date": t.strftime("%H:%M"), "price": round(p, 2)})
    return points


def get_history(symbol: str, current_price: float, range_key: str = "1m") -> list:
    """Returns a list of {date, price} points ending at exactly
    `current_price`, walking backwards with a deterministic per-symbol
    random walk so the same range always renders the same chart. 'date' is
    an HH:MM label for the '1d' range and a YYYY-MM-DD label otherwise."""
    if range_key == "1d":
        return _get_intraday_history(symbol, current_price)

    days = RANGE_DAYS.get(range_key, 30)
    if not current_price or current_price <= 0:
        return []

    rnd = random.Random(f"{symbol}-history-v1")
    # Slight per-symbol daily volatility, generated once so it's stable
    # across every range request for this symbol (not re-rolled per call).
    daily_vol = rnd.uniform(0.008, 0.028)

    # Walk backwards from today's real price so day 0 (today) is exact.
    prices = [current_price]
    price = current_price
    for _ in range(days):
        # Reverse a plausible day-over-day move: undo today's price by the
        # inverse of a random return, seeded by symbol+day-offset so it's
        # reproducible rather than reshuffled on every page load.
        step_seed = f"{symbol}-{_}"
        step_rnd = random.Random(step_seed)
        drift = step_rnd.uniform(-daily_vol, daily_vol)
        price = price / (1 + drift)
        prices.append(round(price, 2))

    prices.reverse()
    today = date.today()
    points = []
    for i, p in enumerate(prices):
        d = today - timedelta(days=(len(prices) - 1 - i))
        points.append({"date": d.isoformat(), "price": round(p, 2)})
    return points
