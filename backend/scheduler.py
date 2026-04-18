"""Daily 4:30 PM ET job: write closing snapshot to SQLite for all tickers."""
from datetime import date
import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from backend.database import get_all_tickers, upsert_snapshot
from backend.fetcher import fetch_live_pe

ET = pytz.timezone("US/Eastern")


def _write_daily_snapshots():
    today = date.today().isoformat()
    for ticker in get_all_tickers():
        try:
            data = fetch_live_pe(ticker)
            upsert_snapshot(
                ticker=ticker,
                date=today,
                price=data.get("price"),
                trailing_eps=data.get("trailing_eps"),
                trailing_pe=data.get("trailing_pe"),
                forward_pe=data.get("forward_pe"),
            )
        except Exception:
            pass


def start_daily_scheduler(scheduler: BackgroundScheduler) -> BackgroundScheduler:
    scheduler.add_job(
        _write_daily_snapshots,
        "cron",
        day_of_week="mon-fri",
        hour=16,
        minute=30,
        timezone=ET,
        id="daily_snapshot",
    )
    return scheduler
