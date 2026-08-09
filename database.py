

import sqlite3
import json
import os
import shutil
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "advisor.db")
BACKUP_DIR = os.path.join(os.path.dirname(__file__), "data", "backups")


def get_connection():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            username TEXT UNIQUE,
            password_hash TEXT,
            dob TEXT NOT NULL,
            monthly_income REAL,
            monthly_expenses REAL,
            emergency_fund_months REAL,
            has_high_interest_debt INTEGER,
            debt_amount REAL,
            existing_net_worth REAL,
            existing_holdings TEXT,        -- JSON: {"SYMBOL": amount, ...}
            risk_tier TEXT,                -- conservative / moderate / aggressive
            primary_goal TEXT,
            time_horizon_years INTEGER,
            excluded_sectors TEXT,         -- JSON list
            created_at TEXT,
            updated_at TEXT
        )
    """)

    # --- lightweight migration for DBs created before username/password existed ---
    existing_cols = {row["name"] for row in cur.execute("PRAGMA table_info(users)")}
    if "username" not in existing_cols:
        cur.execute("ALTER TABLE users ADD COLUMN username TEXT")
    if "password_hash" not in existing_cols:
        cur.execute("ALTER TABLE users ADD COLUMN password_hash TEXT")
    if "emergency_fund_amount" not in existing_cols:
        cur.execute("ALTER TABLE users ADD COLUMN emergency_fund_amount REAL DEFAULT 0")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS stock_cache (
            symbol TEXT PRIMARY KEY,
            company_name TEXT,
            sector TEXT,
            currency TEXT DEFAULT 'INR',  -- 'INR' or 'USD' — native currency of price/market cap
            market_cap_cr REAL,           -- always normalized to INR-crore-equivalent, regardless of currency
            price REAL,                   -- in the stock's native currency (see `currency`)
            pe_ratio REAL,
            sector_avg_pe REAL,
            peg_ratio REAL,
            pb_ratio REAL,
            debt_to_equity REAL,
            roe REAL,
            revenue_growth REAL,
            profit_margin_trend TEXT,     -- 'improving' / 'stable' / 'declining'
            free_cash_flow REAL,
            avg_volume REAL,
            promoter_holding_trend TEXT,  -- 'increasing' / 'stable' / 'declining' / 'unknown'
            market_cap_tier TEXT,         -- 'large' / 'mid' / 'small'
            years_consistent_earnings INTEGER,
            red_flag INTEGER DEFAULT 0,
            last_updated TEXT,
            previous_close REAL,
            change_pct REAL,
            market_cap_native REAL,
            market_cap_unit TEXT,
            asset_type TEXT DEFAULT 'stock',
            region TEXT
        )
    """)

    # --- lightweight migration for stock_cache tables created before currency existed ---
    existing_stock_cols = {row["name"] for row in cur.execute("PRAGMA table_info(stock_cache)")}
    if "currency" not in existing_stock_cols:
        cur.execute("ALTER TABLE stock_cache ADD COLUMN currency TEXT DEFAULT 'INR'")
    for col, ddl in [
        ("previous_close", "ALTER TABLE stock_cache ADD COLUMN previous_close REAL"),
        ("change_pct", "ALTER TABLE stock_cache ADD COLUMN change_pct REAL"),
        ("market_cap_native", "ALTER TABLE stock_cache ADD COLUMN market_cap_native REAL"),
        ("market_cap_unit", "ALTER TABLE stock_cache ADD COLUMN market_cap_unit TEXT"),
        ("asset_type", "ALTER TABLE stock_cache ADD COLUMN asset_type TEXT DEFAULT 'stock'"),
        ("region", "ALTER TABLE stock_cache ADD COLUMN region TEXT"),
    ]:
        if col not in existing_stock_cols:
            cur.execute(ddl)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS recommendations (
            rec_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            created_at TEXT,
            input_snapshot TEXT,   -- JSON
            recommended_picks TEXT, -- JSON list of {symbol, amount, reasoning, price_at_rec}
            confirmed_picks TEXT,   -- JSON list, filled in later by user, nullable
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        )
    """)

    conn.commit()
    conn.close()


def backup_database(keep: int = 7) -> str:
    """Copies the live SQLite file into data/backups/ with a timestamp, and
    prunes older backups beyond `keep`. Meant to be called once at app
    startup (see app.py) so every run leaves a restore point from before
    it started writing anything new.

    Restoring: stop the app, copy the backup file you want back over
    data/advisor.db, restart.
    """
    if not os.path.exists(DB_PATH):
        return None  # nothing to back up yet (first run)

    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    dest = os.path.join(BACKUP_DIR, f"advisor_{stamp}.db")
    shutil.copy2(DB_PATH, dest)

    backups = sorted(
        f for f in os.listdir(BACKUP_DIR)
        if f.startswith("advisor_") and f.endswith(".db")
    )
    while len(backups) > keep:
        os.remove(os.path.join(BACKUP_DIR, backups.pop(0)))

    return dest


def create_user(profile: dict) -> int:
    conn = get_connection()
    cur = conn.cursor()
    now = datetime.utcnow().isoformat()
    cur.execute("""
        INSERT INTO users (name, username, password_hash, dob, monthly_income, monthly_expenses,
            emergency_fund_months, emergency_fund_amount, has_high_interest_debt, debt_amount,
            existing_net_worth, existing_holdings, risk_tier, primary_goal,
            time_horizon_years, excluded_sectors, created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        profile["name"], profile.get("username"), profile.get("password_hash"),
        profile["dob"], profile.get("monthly_income"),
        profile.get("monthly_expenses"), profile.get("emergency_fund_months"),
        profile.get("emergency_fund_amount", 0),
        int(profile.get("has_high_interest_debt", False)), profile.get("debt_amount", 0),
        profile.get("existing_net_worth", 0),
        json.dumps(profile.get("existing_holdings", {})),
        profile["risk_tier"], profile.get("primary_goal"),
        profile.get("time_horizon_years"),
        json.dumps(profile.get("excluded_sectors", [])),
        now, now
    ))
    conn.commit()
    user_id = cur.lastrowid
    conn.close()
    return user_id


def _row_to_profile(row) -> dict:
    d = dict(row)
    d["existing_holdings"] = json.loads(d["existing_holdings"] or "{}")
    d["excluded_sectors"] = json.loads(d["excluded_sectors"] or "[]")
    d.pop("password_hash", None)
    return d


def get_user(user_id: int) -> dict:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    return _row_to_profile(row)


def username_exists(username: str) -> bool:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM users WHERE username=?", (username,))
    row = cur.fetchone()
    conn.close()
    return row is not None


def get_user_auth_row(username: str):
    """Returns the raw row (including password_hash) for login checks, or None."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE username=?", (username,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def update_profile(user_id: int, updates: dict) -> bool:
    if not updates:
        return True
    allowed = {
        "name", "monthly_income", "monthly_expenses", "emergency_fund_months",
        "emergency_fund_amount", "has_high_interest_debt", "debt_amount", "existing_net_worth",
        "risk_tier", "primary_goal", "time_horizon_years", "excluded_sectors",
    }
    fields = {k: v for k, v in updates.items() if k in allowed}
    if not fields:
        return True
    if "excluded_sectors" in fields:
        fields["excluded_sectors"] = json.dumps(fields["excluded_sectors"] or [])
    if "has_high_interest_debt" in fields:
        fields["has_high_interest_debt"] = int(bool(fields["has_high_interest_debt"]))

    conn = get_connection()
    cur = conn.cursor()
    set_clause = ", ".join(f"{k}=?" for k in fields.keys())
    values = list(fields.values()) + [datetime.utcnow().isoformat(), user_id]
    cur.execute(f"UPDATE users SET {set_clause}, updated_at=? WHERE user_id=?", values)
    conn.commit()
    conn.close()
    return True


def upsert_stock_cache(stock: dict):
    conn = get_connection()
    cur = conn.cursor()
    stock = dict(stock)
    stock["last_updated"] = datetime.utcnow().isoformat()
    cols = ", ".join(stock.keys())
    placeholders = ", ".join(["?"] * len(stock))
    updates = ", ".join([f"{k}=excluded.{k}" for k in stock.keys() if k != "symbol"])
    cur.execute(f"""
        INSERT INTO stock_cache ({cols}) VALUES ({placeholders})
        ON CONFLICT(symbol) DO UPDATE SET {updates}
    """, list(stock.values()))
    conn.commit()
    conn.close()


def get_all_cached_stocks() -> list:
    """Stocks only (asset_type='stock') — indices are cached in the same
    table but excluded here so the Stocks browse/screener never accidentally
    treats an index as a pickable stock."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM stock_cache WHERE asset_type='stock' OR asset_type IS NULL")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def get_all_cached_indices() -> list:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM stock_cache WHERE asset_type='index'")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def get_cached_stock(symbol: str) -> dict:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM stock_cache WHERE symbol=?", (symbol,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def save_recommendation(user_id: int, input_snapshot: dict, picks: list) -> int:
    conn = get_connection()
    cur = conn.cursor()
    now = datetime.utcnow().isoformat()
    cur.execute("""
        INSERT INTO recommendations (user_id, created_at, input_snapshot, recommended_picks, confirmed_picks)
        VALUES (?,?,?,?,NULL)
    """, (user_id, now, json.dumps(input_snapshot), json.dumps(picks)))
    conn.commit()
    rec_id = cur.lastrowid
    conn.close()
    return rec_id


def confirm_recommendation(rec_id: int, confirmed_picks: list):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("UPDATE recommendations SET confirmed_picks=? WHERE rec_id=?",
                (json.dumps(confirmed_picks), rec_id))
    conn.commit()
    conn.close()


def confirm_recommendation_for_user(user_id: int, rec_id: int) -> bool:
    """Marks a recommendation as 'actually invested' by copying its
    recommended_picks into confirmed_picks — but only if it belongs to this
    user, so one person can't confirm (or infer the existence of) another
    user's recommendation by guessing a rec_id. Returns False if the
    recommendation doesn't exist or isn't theirs."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT recommended_picks FROM recommendations WHERE rec_id=? AND user_id=?",
        (rec_id, user_id),
    )
    row = cur.fetchone()
    if not row:
        conn.close()
        return False
    cur.execute("UPDATE recommendations SET confirmed_picks=? WHERE rec_id=?",
                (row["recommended_picks"], rec_id))
    conn.commit()
    conn.close()
    return True


def get_all_recommendations_for_user(user_id: int) -> list:
    """Full history (confirmed + unconfirmed) — used by the Tracked dashboard section."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""SELECT * FROM recommendations WHERE user_id=?
                   ORDER BY created_at DESC""", (user_id,))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    for r in rows:
        r["input_snapshot"] = json.loads(r["input_snapshot"] or "{}")
        r["recommended_picks"] = json.loads(r["recommended_picks"] or "[]")
        r["confirmed_picks"] = json.loads(r["confirmed_picks"]) if r["confirmed_picks"] else None
    return rows


def get_unconfirmed_recommendations(user_id: int) -> list:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""SELECT * FROM recommendations WHERE user_id=? AND confirmed_picks IS NULL
                   ORDER BY created_at DESC""", (user_id,))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows
