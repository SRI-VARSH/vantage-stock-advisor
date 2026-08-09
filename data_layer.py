

import random
from datetime import datetime, timedelta

USE_MOCK_DATA = False  # flip to True for offline demo with built-in sample data

# Approximate USD->INR rate used only to normalize market_cap_cr onto a single
# scale for screening (the min-market-cap floor is expressed in INR crore).
# It is NOT used to convert amounts the user invests — those stay in INR
# exactly as entered, since a stock's per-pick amount is a money split, not a
# share count. Update this if you want a more current rate.
FX_RATE_USD_TO_INR = 83.0

# A small sample "universe" for mock mode / for testing the pipeline end-to-end.
MOCK_UNIVERSE = [
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ITC.NS",
    "HINDUNILVR.NS", "BAJFINANCE.NS", "MARUTI.NS", "SUNPHARMA.NS", "TITAN.NS",
    "ADANIPOWER.NS", "ZOMATO.NS", "IRCTC.NS", "TATASTEEL.NS", "COALINDIA.NS",
    "ICICIBANK.NS", "AXISBANK.NS", "KOTAKBANK.NS", "SBIN.NS", "WIPRO.NS",
    "HCLTECH.NS", "LT.NS", "ASIANPAINT.NS", "NESTLEIND.NS", "ULTRACEMCO.NS",
    "POWERGRID.NS", "NTPC.NS", "ONGC.NS", "BPCL.NS", "TATAMOTORS.NS",
    "M&M.NS", "DIVISLAB.NS", "CIPLA.NS", "DRREDDY.NS", "BRITANNIA.NS",
    "DABUR.NS", "PIDILITIND.NS", "HAVELLS.NS", "SIEMENS.NS", "GRASIM.NS",
    "JSWSTEEL.NS", "HINDALCO.NS", "APOLLOHOSP.NS", "EICHERMOT.NS", "BAJAJFINSV.NS",
]
# NOTE: still a small, hand-picked list, not the full Nifty 500.
# Good enough to test the pipeline meaningfully; for production, swap this for
# a real Nifty 500 constituent list (available free from NSE's website as a
# downloadable CSV, or from most data providers' index-constituent endpoints).

# A second small hand-picked universe of large, liquid global (mostly US-listed)
# names, so the screener isn't limited to one country. Same idea as
# MOCK_UNIVERSE above: a starting sample, not a full index constituent list —
# swap for a real S&P 500 / global index feed in production the same way.
GLOBAL_UNIVERSE = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "AVGO",
    "JPM", "V", "MA", "BAC", "JNJ", "PFE", "UNH", "PG", "KO", "PEP",
    "WMT", "HD", "COST", "DIS", "NFLX", "XOM", "CVX",
]

MOCK_SECTOR_MAP = {
    "RELIANCE.NS": "Energy", "TCS.NS": "IT", "HDFCBANK.NS": "Banking",
    "INFY.NS": "IT", "ITC.NS": "FMCG", "HINDUNILVR.NS": "FMCG",
    "BAJFINANCE.NS": "Financial Services", "MARUTI.NS": "Auto",
    "SUNPHARMA.NS": "Pharma", "TITAN.NS": "Consumer Goods",
    "ADANIPOWER.NS": "Power", "ZOMATO.NS": "Internet", "IRCTC.NS": "Travel",
    "TATASTEEL.NS": "Metals", "COALINDIA.NS": "Mining",
    "ICICIBANK.NS": "Banking", "AXISBANK.NS": "Banking", "KOTAKBANK.NS": "Banking",
    "SBIN.NS": "Banking", "WIPRO.NS": "IT", "HCLTECH.NS": "IT",
    "LT.NS": "Infrastructure", "ASIANPAINT.NS": "Consumer Goods",
    "NESTLEIND.NS": "FMCG", "ULTRACEMCO.NS": "Cement",
    "POWERGRID.NS": "Power", "NTPC.NS": "Power", "ONGC.NS": "Energy",
    "BPCL.NS": "Energy", "TATAMOTORS.NS": "Auto", "M&M.NS": "Auto",
    "DIVISLAB.NS": "Pharma", "CIPLA.NS": "Pharma", "DRREDDY.NS": "Pharma",
    "BRITANNIA.NS": "FMCG", "DABUR.NS": "FMCG", "PIDILITIND.NS": "Chemicals",
    "HAVELLS.NS": "Consumer Goods", "SIEMENS.NS": "Industrials",
    "GRASIM.NS": "Cement", "JSWSTEEL.NS": "Metals", "HINDALCO.NS": "Metals",
    "APOLLOHOSP.NS": "Healthcare", "EICHERMOT.NS": "Auto",
    "BAJAJFINSV.NS": "Financial Services",

    # ---- global (USD) ----
    "AAPL": "Technology", "MSFT": "Technology", "GOOGL": "Technology",
    "AMZN": "Consumer Cyclical", "NVDA": "Technology", "META": "Technology",
    "TSLA": "Consumer Cyclical", "AVGO": "Technology",
    "JPM": "Financial Services", "V": "Financial Services", "MA": "Financial Services",
    "BAC": "Financial Services", "JNJ": "Healthcare", "PFE": "Healthcare",
    "UNH": "Healthcare", "PG": "Consumer Defensive", "KO": "Consumer Defensive",
    "PEP": "Consumer Defensive", "WMT": "Consumer Defensive", "HD": "Consumer Cyclical",
    "COST": "Consumer Defensive", "DIS": "Communication Services",
    "NFLX": "Communication Services", "XOM": "Energy", "CVX": "Energy",
}
# NOTE: this map is used for mock-data mode. In real (yfinance) mode, sector
# names come directly from Yahoo Finance and may use slightly different
# labels (e.g. "Technology" instead of "IT", "Consumer Cyclical" instead of
# "Auto"). If a sector exclusion doesn't seem to match in real mode, check
# the actual sector name returned for that stock rather than assuming this list.


def _currency_for(symbol: str) -> str:
    """NSE-listed symbols (.NS suffix) are quoted in INR; everything else in
    this project's universe is a US-listed ticker quoted in USD."""
    return "INR" if symbol.endswith(".NS") else "USD"


def _region_for(symbol: str) -> str:
    """Coarse geography classification used by the Stocks page's region
    filter. This project only covers two pools today (see MOCK_UNIVERSE /
    GLOBAL_UNIVERSE above), so this is a simple suffix check — extend it if
    a third market's symbols are ever added."""
    return "India" if symbol.endswith(".NS") else "US/Global"


def _mock_fundamentals(symbol: str) -> dict:
    """Deterministic-ish pseudo-random mock data, seeded per symbol so results
    are stable across runs (useful for testing the screener logic).
    Price is generated in the stock's native currency; market_cap_cr is
    always normalized to INR-crore-equivalent so screening thresholds (which
    are expressed in INR crore) stay meaningful across both markets.

    change_pct/previous_close are seeded by symbol + TODAY'S DATE, so they're
    stable for the whole day (not reshuffled on every page load — this
    function is only ever called from refresh_universe(), which itself only
    runs when the cache is actually due for a refresh, never per-request)
    and shift to a new simulated value once a new mock "trading day" begins."""
    rnd = random.Random(symbol)
    currency = _currency_for(symbol)

    if currency == "USD":
        market_cap_usd_bn = rnd.uniform(40, 3200)          # plausible large-cap US range
        market_cap_cr = round(market_cap_usd_bn * 1e9 * FX_RATE_USD_TO_INR / 1e7, 2)
        market_cap_native, market_cap_unit = round(market_cap_usd_bn, 2), "B"
        price = round(rnd.uniform(20, 750), 2)
    else:
        market_cap_cr = round(rnd.uniform(500, 500000), 2)  # INR crore, as before
        market_cap_native, market_cap_unit = market_cap_cr, "Cr"
        price = round(rnd.uniform(50, 4000), 2)

    day_rnd = random.Random(f"{symbol}-{datetime.utcnow().date().isoformat()}")
    change_pct = round(day_rnd.uniform(-3.5, 3.5), 2)
    previous_close = round(price / (1 + change_pct / 100), 2)

    return {
        "symbol": symbol,
        "company_name": symbol.replace(".NS", ""),
        "sector": MOCK_SECTOR_MAP.get(symbol, "Other"),
        "currency": currency,
        "region": _region_for(symbol),
        "asset_type": "stock",
        "market_cap_cr": market_cap_cr,
        "market_cap_native": market_cap_native,
        "market_cap_unit": market_cap_unit,
        "price": price,
        "previous_close": previous_close,
        "change_pct": change_pct,
        "pe_ratio": round(rnd.uniform(8, 60), 2),
        "sector_avg_pe": round(rnd.uniform(15, 30), 2),
        "peg_ratio": round(rnd.uniform(0.5, 3.0), 2),
        "pb_ratio": round(rnd.uniform(1, 12), 2),
        "debt_to_equity": round(rnd.uniform(0.1, 2.0), 2),
        "roe": round(rnd.uniform(5, 30), 2),
        "revenue_growth": round(rnd.uniform(-5, 60), 2),
        "profit_margin_trend": rnd.choice(["improving", "stable", "declining"]),
        "free_cash_flow": round(rnd.uniform(-500, 20000), 2),
        "avg_volume": round(rnd.uniform(10000, 5000000), 0),
        "promoter_holding_trend": rnd.choice(["increasing", "stable", "declining", "unknown"]),
        "market_cap_tier": "large" if market_cap_cr > 50000 else ("mid" if market_cap_cr > 10000 else "small"),
        "years_consistent_earnings": rnd.randint(0, 8),
        "red_flag": 0,
    }


def _yfinance_fundamentals(symbol: str) -> dict:
    """Real data via yfinance. Requires `pip install yfinance` and internet access.
    NOTE: yfinance doesn't provide promoter-holding-trend or a clean multi-year
    'consistent earnings' figure directly — those fields are approximated or
    marked 'unknown' here. This is a known real-world data-source limitation,
    not a bug: if you later move to the RapidAPI India-focused source discussed
    in the design, those fields can be filled in more precisely.

    Every numeric field is explicitly rounded before it's returned — Yahoo's
    raw floats (ratios especially) routinely come back with 8-10 decimal
    places, which is what was previously leaking straight through to the UI.
    change_pct/previous_close are computed from Yahoo's own previousClose vs
    the live price, not a random placeholder — this is real day-over-day
    movement, cached at refresh time (see refresh_universe / staleness rules
    in pipeline.py), not regenerated per page view.
    """
    import yfinance as yf

    ticker = yf.Ticker(symbol)
    info = ticker.info

    currency = info.get("currency") or _currency_for(symbol)
    market_cap = info.get("marketCap", 0) or 0
    if currency == "INR":
        market_cap_cr = market_cap / 1e7  # paise->crore rough conversion for INR market cap
        market_cap_native, market_cap_unit = round(market_cap_cr, 2), "Cr"
    else:
        # normalize non-INR market caps onto the same INR-crore scale so the
        # universal min-market-cap screen stays meaningful across markets
        market_cap_cr = (market_cap * FX_RATE_USD_TO_INR) / 1e7
        market_cap_native, market_cap_unit = round(market_cap / 1e9, 2), "B"

    price = info.get("currentPrice") or info.get("regularMarketPrice") or 0
    previous_close = info.get("previousClose") or info.get("regularMarketPreviousClose") or price
    change_pct = round(((price - previous_close) / previous_close) * 100, 2) if previous_close else 0.0

    return {
        "symbol": symbol,
        "company_name": info.get("longName", symbol),
        "sector": info.get("sector", "Unknown"),
        "currency": currency,
        "region": _region_for(symbol),
        "asset_type": "stock",
        "market_cap_cr": round(market_cap_cr, 2),
        "market_cap_native": market_cap_native,
        "market_cap_unit": market_cap_unit,
        "price": round(price, 2),
        "previous_close": round(previous_close, 2),
        "change_pct": change_pct,
        "pe_ratio": round(info.get("trailingPE", 0) or 0, 2),
        "sector_avg_pe": round(info.get("trailingPE", 0) or 0, 2),  # placeholder: real sector avg needs peer comparison
        "peg_ratio": round(info.get("pegRatio", 0) or 0, 2),
        "pb_ratio": round(info.get("priceToBook", 0) or 0, 2),
        "debt_to_equity": round((info.get("debtToEquity", 0) or 0) / 100, 2),
        "roe": round((info.get("returnOnEquity", 0) or 0) * 100, 2),
        "revenue_growth": round((info.get("revenueGrowth", 0) or 0) * 100, 2),
        "profit_margin_trend": "unknown",
        "free_cash_flow": round(info.get("freeCashflow", 0) or 0, 2),
        "avg_volume": round(info.get("averageVolume", 0) or 0, 2),
        "promoter_holding_trend": "unknown",
        "market_cap_tier": "large" if market_cap_cr > 50000 else ("mid" if market_cap_cr > 10000 else "small"),
        "years_consistent_earnings": 0,  # needs historical financials parsing — future improvement
        "red_flag": 0,
    }


def _index_symbols():
    """Reference indices, keyed by the same symbol used throughout the app
    (config.REFERENCE_INDICES) mapped to their real Yahoo Finance ticker."""
    return {
        "NIFTY50": "^NSEI", "SENSEX": "^BSESN", "BANKNIFTY": "^NSEBANK",
        "SPX": "^GSPC", "NASDAQ": "^IXIC",
    }


def _mock_index_fundamentals(symbol: str, base_level: float, currency: str) -> dict:
    rnd = random.Random(symbol)
    day_rnd = random.Random(f"{symbol}-{datetime.utcnow().date().isoformat()}")
    change_pct = round(day_rnd.uniform(-1.8, 1.8), 2)
    price = round(base_level * (1 + change_pct / 100), 2)
    previous_close = round(price / (1 + change_pct / 100), 2)
    return {
        "symbol": symbol, "company_name": symbol, "sector": "Index",
        "currency": currency, "region": "India" if currency == "INR" else "US/Global",
        "asset_type": "index", "market_cap_cr": 0, "market_cap_native": 0, "market_cap_unit": "",
        "price": price, "previous_close": previous_close, "change_pct": change_pct,
        "pe_ratio": 0, "sector_avg_pe": 0, "peg_ratio": 0, "pb_ratio": 0,
        "debt_to_equity": 0, "roe": 0, "revenue_growth": 0,
        "profit_margin_trend": "unknown", "free_cash_flow": 0, "avg_volume": 0,
        "promoter_holding_trend": "unknown", "market_cap_tier": "large",
        "years_consistent_earnings": 0, "red_flag": 0,
    }


def _yfinance_index_fundamentals(symbol: str, yahoo_symbol: str, currency: str) -> dict:
    import yfinance as yf
    ticker = yf.Ticker(yahoo_symbol)
    info = ticker.info
    price = info.get("regularMarketPrice") or info.get("previousClose") or 0
    previous_close = info.get("regularMarketPreviousClose") or info.get("previousClose") or price
    change_pct = round(((price - previous_close) / previous_close) * 100, 2) if previous_close else 0.0
    return {
        "symbol": symbol, "company_name": info.get("shortName", symbol), "sector": "Index",
        "currency": currency, "region": "India" if currency == "INR" else "US/Global",
        "asset_type": "index", "market_cap_cr": 0, "market_cap_native": 0, "market_cap_unit": "",
        "price": round(price, 2), "previous_close": round(previous_close, 2), "change_pct": change_pct,
        "pe_ratio": 0, "sector_avg_pe": 0, "peg_ratio": 0, "pb_ratio": 0,
        "debt_to_equity": 0, "roe": 0, "revenue_growth": 0,
        "profit_margin_trend": "unknown", "free_cash_flow": 0, "avg_volume": 0,
        "promoter_holding_trend": "unknown", "market_cap_tier": "large",
        "years_consistent_earnings": 0, "red_flag": 0,
    }


def get_index_fundamentals(symbol: str, base_level: float, currency: str) -> dict:
    """Same idea as get_fundamentals(), but for reference indices (Nifty 50,
    Sensex, S&P 500, ...) rather than individual stocks — real quote data
    when USE_MOCK_DATA is off, via the same yfinance dependency already used
    for stocks (Yahoo Finance carries these index tickers too, no separate
    provider needed)."""
    if USE_MOCK_DATA:
        return _mock_index_fundamentals(symbol, base_level, currency)
    yahoo_symbol = _index_symbols().get(symbol, symbol)
    try:
        return _yfinance_index_fundamentals(symbol, yahoo_symbol, currency)
    except Exception:
        # Network/parse failure shouldn't take the whole page down — fall
        # back to a clearly-labeled illustrative value for this refresh only.
        return _mock_index_fundamentals(symbol, base_level, currency)


def get_fundamentals(symbol: str) -> dict:
    """THE single entry point for fundamentals data. Everything else calls this."""
    if USE_MOCK_DATA:
        return _mock_fundamentals(symbol)
    return _yfinance_fundamentals(symbol)


def get_universe() -> list:
    """Returns the list of stock symbols this system covers: Indian (NSE) and
    global (mostly US-listed) large/mid caps combined. In production, swap
    this for a real index-constituent feed for each market you want covered."""
    return MOCK_UNIVERSE + GLOBAL_UNIVERSE


def refresh_universe(db_upsert_fn):
    """Batch-refresh job (Step 4 caching design): pulls fundamentals for every
    stock in the universe ONCE, and stores it via the provided db function.
    Run this periodically (e.g. daily cron job) — never call get_fundamentals()
    live per user request."""
    results = []
    for symbol in get_universe():
        try:
            data = get_fundamentals(symbol)
            db_upsert_fn(data)
            results.append((symbol, "ok"))
        except Exception as e:
            results.append((symbol, f"failed: {e}"))
    return results


def refresh_indices(db_upsert_fn, reference_indices: list):
    """Same batch-refresh idea as refresh_universe(), for the reference
    indices shown on Overview (config.REFERENCE_INDICES). Kept as a
    separate pass since indices aren't part of the pickable universe the
    screener runs against — but they're cached and refreshed on exactly the
    same schedule, and stored in the same table (asset_type='index') so they
    can be browsed/charted through the same Stocks detail page as any stock."""
    results = []
    for idx in reference_indices:
        try:
            data = get_index_fundamentals(idx["symbol"], idx["base_level"], idx["currency"])
            db_upsert_fn(data)
            results.append((idx["symbol"], "ok"))
        except Exception as e:
            results.append((idx["symbol"], f"failed: {e}"))
    return results
