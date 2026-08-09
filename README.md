# Stock Advisor Agent — MVP (CLI + Web)

This is the working MVP slice of the full architecture we designed:
Signup → real/cached stock data → 15-criteria fundamental screen → simple
rule-based portfolio construction → hard-cap validation → plain output.

**Two ways to use it, same underlying logic:**
- `main.py` — terminal/CLI version
- `app.py` — a Flask web app, multi-page and server-rendered (`templates/`,
  `static/style.css`, `static/script.js`)

Both call the exact same business logic in `pipeline.py`, so there's no
duplicated or drifting logic between them — this was refactored specifically
so fixing or improving one interface can't silently leave the other outdated.

Tested and confirmed working in this environment (mock data): signup, the
happy-path recommendation, the "zero stocks qualify" edge case, the minor/age
eligibility gate, and the full web API flow (sectors → signup → profile →
recommendation → rejected-minor-signup) all verified via direct HTTP calls.

## Running with Docker

The fastest way to run this without setting up a Python environment.

```bash
# 1. copy the env template and fill in a real SECRET_KEY
cp .env.example .env
python3 -c "import secrets; print(secrets.token_hex(32))"   # paste the output into .env

# 2. build and start
docker compose up --build

# App is now at http://localhost:5000
```

- The SQLite database persists in a named Docker volume (`vantage-data`), so
  `docker compose down` / rebuilding the image doesn't wipe your users or
  cached stock data — only `docker compose down -v` does.
- `GEMINI_API_KEY` in `.env` is optional — see `llm_reasoning.py`. Leave
  it blank and the app works fine with templated reasoning instead.
- The image runs the app with `gunicorn` (production WSGI server) instead of
  Flask's own dev server. It's deliberately started with a single worker
  process (see the comment in `Dockerfile`) — the "recommendation persists
  across navigation" feature and SQLite access are both process-local, so
  multiple worker *processes* would need that cache moved to Redis/the
  database first. `--threads 4` gives it real concurrency without that
  problem.
- Without Docker: `pip install -r requirements.txt && python app.py` still
  works exactly as before (binds to `0.0.0.0:5000` by default now, or
  whatever `PORT` env var you set, so it also works unmodified on platforms
  like Render/Railway that inject their own `PORT`).

## Pushing to GitHub

```bash
git init
git add .
git commit -m "Initial commit: Vantage stock advisor"
git branch -M main
git remote add origin https://github.com/<your-username>/<your-repo>.git
git push -u origin main
```

`.gitignore` already excludes `data/` (the local SQLite DB — never commit
user data) and `.env` (never commit secrets). `.env.example` is committed
instead, as the template collaborators copy from.

## What changed in this revision

**Second pass (latest):**
- **Visual identity**: replaced the default purple/teal AI-template palette
  with a warm parchment background + burnt-rust/deep-pine accents, added a
  serif display font (Fraunces) for headings and the wordmark, and recolored
  the logo/sidebar to match — meant to read as a deliberately designed
  product rather than a generic scaffold.
- **Rounding**: found and fixed the actual source of long decimals — real
  Yahoo Finance data in `_yfinance_fundamentals()` wasn't being rounded on
  several fields (P/E, ROE, debt/equity, etc.). Every numeric field returned
  from live data is now explicitly rounded before it reaches the UI.
- **Filters now survive navigating into a stock and back**: the Stocks page
  passes its current filter querystring along via `?ref=...` on every stock
  link; the detail page's "Back to Stocks" reads it back, so the exact same
  filtered view is restored instead of resetting.
- **Chart**: added a "1D" range (intraday, 15-minute steps across a
  9:15–3:30 session) alongside the existing 1W–1Y ranges, and a hover
  tooltip that follows the cursor along the line showing the exact price
  and date/time at that point (touch-drag works too, for mobile).
- **Sector / market-cap / geography filters are now checkboxes**, not single
  dropdowns — you can select multiple sectors (or cap tiers, or regions) at
  once instead of being limited to one.
- **Currency correctness**: found a real bug — the stock detail page's
  market cap was hardcoded to always display in ₹-crore, even for USD
  stocks like AAPL. Added proper native-currency market cap fields
  end-to-end (`market_cap_native` / `market_cap_unit`) so it's now shown
  correctly in the stock's own currency and unit ($ B vs. ₹ Cr).
- **Renamed "Advancers"/"Decliners" to "Gainers"/"Losers"** on the Overview
  stat cards, matching the labels already used on the Top Movers list.
- **Added a Geography filter** (India vs. US/Global) on the Stocks page,
  based on each symbol's home exchange.
- **Indices are now real, live data — and viewable like any stock**: Nifty
  50, Sensex, Nifty Bank, S&P 500, and Nasdaq are fetched via the same
  yfinance path used for individual stocks (real tickers: `^NSEI`,
  `^BSESN`, `^NSEBANK`, `^GSPC`, `^IXIC`), cached the same way, and each
  index card on Overview is now clickable through to its own detail/chart
  page — same infrastructure as a stock, since they share the same cache
  table (`asset_type='index'`).
- **Overview's Gainers/Losers list and the index cards are now clickable**,
  linking straight to that stock or index's detail page.
- **Data refresh reliability, and no more random numbers standing in for
  real data**: replaced the flat 48-hour staleness window with a
  market-hours-aware one — refreshes at most every 15 minutes while NSE is
  open, forces one more refresh in the 45 minutes right after the 3:30pm
  close (specifically to catch the final settle price instead of serving a
  stale mid-session one), and uses a calmer window outside trading hours.
  Every place that previously called `random.uniform()` to fake a daily %
  change (the ticker, the Stocks list, the stock detail page) now reads the
  real `change_pct` computed once at refresh time from Yahoo's actual
  previous-close vs. current price, cached in the database rather than
  re-rolled on every page view.

**First pass:**
Rebuilt around one central idea: **suggest, don't force** — plus made the app
actually agentic instead of a single fixed formula.

**New: the recommendation agent (`agent.py`, `llm_reasoning.py`)**
- Recommendations are no longer one forced portfolio. `agent.py` runs the
  screen once and builds **three genuinely different strategy options**
  (Steady / Balanced / Focused — see `STRATEGY_PROFILES` in `config.py`),
  each with its own equity % and per-stock cap, and you pick which trade-off
  you're comfortable with.
- If too few stocks qualify under your risk tier, the screen adaptively
  widens (`screener.screen_with_relaxation`) instead of silently handing
  back the same tiny list every time — and says so on the page.
- Every pick shows the actual numbers that got it there (ROE, growth, D/E,
  P/E), and links to a full detail page for that stock.
- Set `GEMINI_API_KEY` to have Gemini 2.5 Flash write the cross-strategy
  comparison live; without it, a clear templated comparison is used instead
  — nothing about eligibility or the hard safety caps ever depends on this key.

**New: Stocks section (`/dashboard/stocks`, `/dashboard/stocks/<symbol>`)**
- Browse the full screened universe with filters (sector, market-cap tier,
  search, sort).
- Click into any company for fundamentals + a price chart with adjustable
  range (1W/2W/3W/1M/2M/3M/6M/1Y), via `history.py` + `/api/history/<symbol>`.
  This project has no live intraday feed, so the series is a deterministic,
  clearly-labeled illustrative walk anchored to the real current price —
  same approach the daily ticker already used.

**Fixed, in order raised:**
1. Password too short: now shows inline red text under the field
   immediately (was silently refusing to advance with no explanation).
2. Ticker tape speed now scales with how many stocks are in it, so it stays
   readable regardless of universe size (was a fixed 45s regardless of
   count).
3. Recommend page redesigned around the multi-strategy cards above.
4. Profile header name color/overlap fixed (explicit color + repositioned
   text so it never sits over the cover gradient).
5. A recommendation now survives navigating away and back — it's cached
   server-side per user until you submit a new amount or hit "Start a new
   recommendation" (was lost on every navigation).
6. Emergency fund: the profile edit form never actually had a field for it
   — that was the bug. Added `emergency_fund_amount`, and editing it now
   recomputes the months-of-expenses figure the recommendation engine reads.
7. Logo added (`static/logo.svg`) — sidebar, auth pages, browser tab.
8. Reference indices (Nifty 50, Sensex, Nifty Bank, S&P 500, Nasdaq) always
   shown on Overview — illustrative, same as the ticker, and separate from
   the pickable universe.
9. Allocation logic reworked to be sound and to actually respond to your
   amount: per-stock cap and pick count now scale continuously with the
   amount (was fixed buckets, which is why the same couple of stocks kept
   showing up regardless of amount); the "not all of it goes to direct
   equity" behavior is now one of three selectable strategies instead of a
   single hard-coded number, and is explained plainly on the page.
10. General robo-advisor UX patterns applied: per-pick fundamentals shown
    inline, sortable/filterable universe browser, adjustable-range charts,
    reference indices, multi-option recommendations with an explicit
    rationale — patterns common across apps like Groww/Zerodha/INDmoney.

## What you need to do to run this for real

### 1. Install packages
```bash
pip install -r requirements.txt
```
(If you get a "externally managed environment" error on Linux, use:
`pip install -r requirements.txt --break-system-packages`, or better, use a
virtual environment: `python -m venv venv && source venv/bin/activate` first.)

### 2. Run the web version (recommended)
```bash
python app.py
```
Then open **http://127.0.0.1:5000** in your browser.

The web UI ("Vantage") is a proper multi-page app now, not a single-page
JS app — every section has its own URL and the server does real redirects,
the same pattern you'd see on most production sites:

- **`/login`, `/signup`** — real `<form>` posts. On success the server sets
  a signed session cookie and issues a **302 redirect** to `/dashboard`; you
  can never navigate back to a stale login/signup page while logged in
  (they redirect you straight to the dashboard instead). Signup is a
  4-step wizard (account → finances → risk & goals → sector exclusions)
  with a real username/password, hashed with Werkzeug. The left panel is
  just the brand and a one-line tagline — no filler copy.
- **`/dashboard`** — a live-feeling "Market Pulse" homepage: a scrolling
  ticker tape across the whole stock universe (India + global, correct ₹/$
  per stock), advancers/decliners, top gainers/losers, sector performance,
  and a single CTA into Get Recommendation. Nothing personal (no profile
  stats) lives here on purpose — see the note on this below.
- **`/dashboard/recommend`** — enter (or quick-pick) an amount; results
  render as a summary strip, a CSS-only donut for the equity/remainder
  split, a colour-coded sector breakdown, and per-stock cards with their
  own allocation bar and native listed price (₹ or $, whichever the stock
  actually trades in) — all computed server-side. Also shows *why* the
  equity % is what it is (risk tier ceiling × a time-horizon glide factor,
  see below) plus the tax note and full disclaimer from `config.py`.
- **`/dashboard/tracked`** — every recommendation you've generated, newest
  first, as history — not automatically counted as money invested. Each one
  has an **"I actually made this investment"** button; only after you click
  it does that amount count toward "Total invested (confirmed)". The
  summary row shows both that confirmed total and the separate "Total
  recommended" figure, so the two are never conflated.
- **`/dashboard/profile`** — a real settings-page pattern: a cover-banner
  header (avatar, name, quick-fact chips) with a view/edit toggle — no
  JavaScript, just a CSS-driven checkbox — instead of reusing the signup
  wizard's UI. Saves with a POST/redirect/GET so refreshing never
  re-submits the form.
- **`/logout`** — clears the session, redirects to `/login`.

### The equity-allocation glide path
`allocator.decide_equity_allocation()` still respects the hard per-risk-tier
ceiling in `config.HARD_CAPS` (30% / 50% / 70%) as a genuine maximum — that
part is deliberately rigid, per the original design. What's new: the actual
percentage *used* now scales down for a shorter time horizon, since less
time to recover from a downturn is a reason to be more conservative even
within your risk tier:

| Time horizon | % of your tier's ceiling used |
|---|---|
| 10+ years | 100% |
| 5–9 years | 90% |
| 2–4 years | 75% |
| under 2 years | 60% |

So "aggressive + 12yr horizon" → 70% equity, but "aggressive + 1yr horizon"
→ 42% equity. Same risk tier, different outcome — it's no longer a flat
per-tier constant.

### Confirmed investments vs. recommendations
`recommendations.confirmed_picks` existed in the schema from the start but
was never wired to anything. It now is: `POST
/dashboard/tracked/<rec_id>/confirm` copies that recommendation's picks into
`confirmed_picks` (checked against `session['user_id']` first, so you can't
confirm someone else's recommendation by guessing an ID). "Total invested"
on the Tracked page only ever sums confirmed recommendations.

All of `/dashboard/*` is guarded by a `login_required` check — visiting any
of those URLs while logged out redirects to `/login`; visiting `/login` or
`/signup` while already logged in redirects to `/dashboard`.

`static/script.js` is small — it drives the signup wizard's step navigation,
the debt-amount reveal, filling the amount field from quick-pick chips, and
a couple of purely cosmetic touches (a ticking clock, the ticker-tape
marquee is pure CSS). It doesn't talk to any API; every real action is a
normal form submission.

The original JSON API (`POST /api/signup`, `POST /api/auth/register`,
`POST /api/auth/login`, `PUT /api/profile/<user_id>`, `GET
/api/tracked/<user_id>`, `POST /api/recommend`, `GET /api/user/<user_id>`)
is still there for programmatic use, but the web UI no longer depends on it.

### 2b. Or run the CLI version
```bash
python main.py
```
Same logic, terminal prompts instead of a browser.

### 3. Switch from mock data to real data
Open `data_layer.py` and change this one line near the top:
```python
USE_MOCK_DATA = True   # change to False
```
That's it — nothing else needs to change, because every other file only ever
calls `data_layer.get_fundamentals()`, never a data provider directly.

### 4. About the data source — no signup needed for the MVP
The real-data path uses **`yfinance`**, a free Python library that pulls data
from Yahoo Finance. **No API key, no signup required.** This is why I chose it
for the MVP over the RapidAPI option we discussed earlier — it gets you to a
working, real-data version immediately with zero account creation.

The universe now spans two markets: `data_layer.MOCK_UNIVERSE` (44 NSE-listed
Indian stocks, `.NS` suffix) and `data_layer.GLOBAL_UNIVERSE` (25 large-cap
US-listed stocks, no suffix — yfinance resolves these directly). Both are
screened together. Prices and market cap stay in each stock's native
currency for display (`currency` field: `"INR"` or `"USD"`); market cap is
additionally normalized onto a single INR-crore-equivalent scale internally
(`FX_RATE_USD_TO_INR` in `data_layer.py`, currently 83 — update it if you
want a more current rate) purely so the universal minimum-market-cap screen
stays meaningful across both markets. The amount you actually invest always
stays in ₹ exactly as you typed it — that split is a money allocation, not a
share-count conversion, so it's unaffected by which currency a given stock
trades in.

Trade-off, honestly stated: `yfinance` doesn't cleanly expose two fields from
our original 15-criteria design — **promoter/insider holding trend** and a
precise **multi-year consistent-earnings count**. These are marked
`"unknown"` / `0` in the code right now (see the comment in
`_yfinance_fundamentals()` in `data_layer.py`). The screener still runs
correctly on the other 13 criteria. Also note: in real mode, sector names
come directly from Yahoo Finance and may differ slightly from the mock
sector list shown during signup (e.g. "Technology" instead of "IT") — the
exclusion matching is case-insensitive but won't catch a completely
different label, so double-check a stock's actual sector if an exclusion
doesn't seem to apply.

### 5. If you want those two missing fields later (optional upgrade)
This requires the India-focused RapidAPI source discussed during design.
To get it:
1. Go to rapidapi.com and create a free account.
2. Search for **"Indian Stock Exchange"** in the RapidAPI marketplace (there
   are a couple of similarly-named listings from different publishers —
   check each one's documentation tab for which fields it actually returns
   before picking one, since I couldn't verify their exact free-tier limits
   from this environment).
3. Subscribe to its free tier — you'll get an API key (`X-RapidAPI-Key`).
4. Add a new function `_rapidapi_fundamentals(symbol)` in `data_layer.py`
   following the same shape as `_yfinance_fundamentals()`, and point
   `get_fundamentals()` at it. This is exactly the "single point of change"
   the architecture was built for — nothing else needs touching.
5. Store the key in a `.env` file (never hardcode it, never commit it to
   GitHub) and load it with `python-dotenv` (`pip install python-dotenv`).

## Project structure
```
stock_advisor/
├── config.py         # every tunable rule (caps, thresholds, tax note) in one place
├── database.py       # SQLite storage: profiles, cached stock data, tracked recs, backups
├── data_layer.py      # the single swappable data-fetching layer (mock or yfinance)
├── screener.py       # 15-criteria fundamental screen
├── safety.py         # age eligibility gate + safety-buffer check
├── allocator.py       # rule-based portfolio construction + time-horizon glide path
├── validator.py       # deterministic post-construction hard-cap check
├── output.py          # CLI-only text formatting
├── pipeline.py        # SHARED business logic — used by both main.py and app.py
├── main.py            # CLI entry point
├── app.py             # Flask web backend — routes, sessions, page rendering
├── templates/
│   ├── base.html               # shared layout: sidebar dashboard shell / auth shell
│   ├── _flash.html             # flash-message partial
│   ├── login.html
│   ├── signup.html             # 4-step wizard
│   ├── dashboard_overview.html # Market Pulse homepage
│   ├── dashboard_recommend.html
│   ├── dashboard_tracked.html  # history + confirm-investment action
│   └── dashboard_profile.html  # cover-banner + view/edit toggle
├── static/
│   ├── style.css     # frontend styling
│   └── script.js     # small progressive-enhancement JS (no API calls)
└── data/
    ├── advisor.db     # created automatically on first run (SQLite file)
    └── backups/        # timestamped snapshots, made automatically on every startup
```

## What's included in this MVP (per our agreed scope)
- Full signup flow (age gate, safety-buffer inputs, risk tolerance, sector exclusions)
- Real or mock stock data across two markets (India + a global US-heavy set), cached in SQLite, refreshed on staleness
- 15-criteria fundamental screen (universal + risk-tier + user exclusions)
- Rule-based portfolio construction within hard safety caps, with a
  time-horizon glide factor on top of the risk-tier equity ceiling
- Deterministic validator catching any cap violations before output
- Both a CLI and a browser-based, multi-page web UI, sharing identical logic
- Recommendations are saved to the database as history; a "confirm investment"
  action lets the user mark which ones they actually acted on, and only those
  count toward the "Total invested" figure shown on the Tracked page
- Automatic timestamped database backups on every app startup

## What's deliberately NOT in this MVP yet (per our agreed MVP boundary)
- Rebalancing review
- Movement explainer ("why did this stock move today")
- The full agentic, tool-using LLM reasoning step (Call 1 from the design) —
  `allocator.py` currently uses a simple deterministic ranking formula instead
- Tax-rule nuance beyond the one informational note (no per-trade capital
  gains calculation, no brokerage/STT modeling)
- Production-grade security hardening (a hardcoded dev `secret_key`, no CSRF
  protection, no login rate limiting, no HTTPS enforcement — see the note
  below before ever deploying this anywhere reachable by other people)
- yfinance's missing promoter-holding / consistent-earnings fields
- A real index-constituent feed — both universes are still small, hand-picked
  lists (44 NSE names, 25 US names), not full Nifty 500 / S&P 500 coverage

These were all intentionally deferred so you could see the core pipeline work
end-to-end first, per the MVP plan. My honest suggestion for what's next:
the security hardening list above, since that's the actual gap between
"looks and behaves like a real product" and "is safe to expose to other
people" — everything else at this point is refinement on top of a working
core.

## A note on running this outside your own machine
`app.py` currently runs Flask's built-in development server
(`debug=False, port=5000`) — appropriate for local testing, but **not**
meant for production hosting as-is. If you ever deploy this somewhere
public, use a production WSGI server (e.g. gunicorn) and add the security
items from the list above first.

