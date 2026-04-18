import sqlite3
import os
from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.getenv("DB_PATH", "pe_history.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS stocks (
                ticker   TEXT PRIMARY KEY,
                company  TEXT NOT NULL,
                sector   TEXT NOT NULL,
                added_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS pe_snapshots (
                ticker       TEXT NOT NULL,
                date         TEXT NOT NULL,
                price        REAL,
                trailing_eps REAL,
                trailing_pe  REAL,
                forward_pe   REAL,
                PRIMARY KEY (ticker, date),
                FOREIGN KEY (ticker) REFERENCES stocks(ticker) ON DELETE CASCADE
            )
        """)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.commit()


# --- stocks ---

def list_stocks():
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM stocks ORDER BY sector, ticker").fetchall()
    return [dict(r) for r in rows]


def get_stock(ticker: str):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM stocks WHERE ticker = ?", (ticker,)).fetchone()
    return dict(row) if row else None


def insert_stock(ticker: str, company: str, sector: str, added_at: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO stocks (ticker, company, sector, added_at) VALUES (?, ?, ?, ?)",
            (ticker, company, sector, added_at),
        )
        conn.commit()


def delete_stock(ticker: str):
    with get_conn() as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("DELETE FROM stocks WHERE ticker = ?", (ticker,))
        conn.commit()


# --- pe_snapshots ---

def upsert_snapshot(ticker: str, date: str, price: float, trailing_eps: float,
                    trailing_pe: float, forward_pe: float):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO pe_snapshots (ticker, date, price, trailing_eps, trailing_pe, forward_pe)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(ticker, date) DO UPDATE SET
                price        = excluded.price,
                trailing_eps = excluded.trailing_eps,
                trailing_pe  = excluded.trailing_pe,
                forward_pe   = excluded.forward_pe
        """, (ticker, date, price, trailing_eps, trailing_pe, forward_pe))
        conn.commit()


def get_history(ticker: str, days: int = 90):
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT * FROM pe_snapshots
            WHERE ticker = ?
            ORDER BY date DESC
            LIMIT ?
        """, (ticker, days)).fetchall()
    return [dict(r) for r in reversed(rows)]


def get_all_tickers():
    with get_conn() as conn:
        rows = conn.execute("SELECT ticker FROM stocks").fetchall()
    return [r["ticker"] for r in rows]
