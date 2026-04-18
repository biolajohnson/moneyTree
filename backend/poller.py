"""Background poller: refreshes live P/E every 15 minutes during market hours."""
from datetime import datetime
import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from backend.database import get_all_tickers
from backend.fetcher import fetch_live_pe

ET = pytz.timezone("US/Eastern")

# Shared in-memory cache: ticker → latest live data dict
live_cache: dict[str, dict] = {}


def _is_market_open() -> bool:
    now = datetime.now(ET)
    if now.weekday() >= 5:
        return False
    market_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = now.replace(hour=16, minute=0, second=0, microsecond=0)
    return market_open <= now <= market_close


def _poll():
    if not _is_market_open():
        return
    tickers = get_all_tickers()
    for ticker in tickers:
        try:
            live_cache[ticker] = fetch_live_pe(ticker)
        except Exception:
            pass


def start_poller() -> BackgroundScheduler:
    scheduler = BackgroundScheduler()
    scheduler.add_job(_poll, "interval", minutes=15, id="poller")
    scheduler.start()
    return scheduler


def get_live(ticker: str) -> dict | None:
    return live_cache.get(ticker.upper())


def invalidate(ticker: str):
    live_cache.pop(ticker.upper(), None)


def add_ticker(ticker: str):
    try:
        live_cache[ticker.upper()] = fetch_live_pe(ticker)
    except Exception:
        pass
