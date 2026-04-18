from contextlib import asynccontextmanager
from datetime import date, datetime
import pytz
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from backend.database import (
    init_db, list_stocks, get_stock, insert_stock, delete_stock,
    get_history, get_all_tickers, upsert_snapshot,
)
from backend.fetcher import fetch_metadata, fetch_live_pe, backfill_history
from backend.poller import start_poller, get_live, invalidate, add_ticker, _is_market_open
from backend.scheduler import start_daily_scheduler

ET = pytz.timezone("US/Eastern")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    scheduler = start_poller()
    start_daily_scheduler(scheduler)
    yield
    scheduler.shutdown()


app = FastAPI(title="MoneyTree", lifespan=lifespan)


# ── Utility ──────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "time": datetime.now(ET).isoformat()}


@app.post("/refresh")
def refresh():
    tickers = get_all_tickers()
    results = {}
    for ticker in tickers:
        try:
            data = fetch_live_pe(ticker)
            from backend.poller import live_cache
            live_cache[ticker] = data
            results[ticker] = data
        except Exception as e:
            results[ticker] = {"error": str(e)}
    return {"refreshed": results}


# ── Stocks (Watchlist) ────────────────────────────────────────────────────────

@app.get("/stocks")
def get_stocks():
    stocks = list_stocks()
    from backend.poller import live_cache, _is_market_open
    grouped: dict[str, list] = {}
    for s in stocks:
        ticker = s["ticker"]
        live = live_cache.get(ticker)
        s["live"] = live
        s["market_open"] = _is_market_open()
        sector = s["sector"]
        grouped.setdefault(sector, []).append(s)
    return grouped


class AddStockRequest(BaseModel):
    ticker: str


@app.post("/stocks", status_code=201)
def add_stock(body: AddStockRequest):
    ticker = body.ticker.strip().upper()
    if get_stock(ticker):
        raise HTTPException(status_code=409, detail=f"{ticker} already in watchlist")
    try:
        meta = fetch_metadata(ticker)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Could not fetch data for {ticker}: {e}")

    insert_stock(
        ticker=meta["ticker"],
        company=meta["company"],
        sector=meta["sector"],
        added_at=date.today().isoformat(),
    )
    backfill_history(ticker)
    add_ticker(ticker)
    return get_stock(ticker)


@app.delete("/stocks/{ticker}", status_code=204)
def remove_stock(ticker: str):
    ticker = ticker.upper()
    if not get_stock(ticker):
        raise HTTPException(status_code=404, detail=f"{ticker} not found")
    delete_stock(ticker)
    invalidate(ticker)


# ── P/E Data ──────────────────────────────────────────────────────────────────

@app.get("/stocks/{ticker}/pe")
def get_pe(ticker: str):
    ticker = ticker.upper()
    if not get_stock(ticker):
        raise HTTPException(status_code=404, detail=f"{ticker} not found")
    try:
        data = fetch_live_pe(ticker)
        from backend.poller import live_cache
        live_cache[ticker] = data
        return data
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/stocks/{ticker}/history")
def get_pe_history(ticker: str):
    ticker = ticker.upper()
    if not get_stock(ticker):
        raise HTTPException(status_code=404, detail=f"{ticker} not found")
    rows = get_history(ticker, days=90)

    if not rows:
        return {"ticker": ticker, "history": [], "spike_threshold": None, "avg_pe": None}

    pes = [r["trailing_pe"] for r in rows if r["trailing_pe"] is not None]
    avg_pe = round(sum(pes) / len(pes), 2) if pes else None
    spike_threshold = round(avg_pe * 1.2, 2) if avg_pe else None

    for r in rows:
        r["is_spike"] = (
            r["trailing_pe"] is not None
            and spike_threshold is not None
            and r["trailing_pe"] > spike_threshold
        )

    return {"ticker": ticker, "history": rows, "avg_pe": avg_pe, "spike_threshold": spike_threshold}


# ── Frontend (serve static files) ────────────────────────────────────────────

app.mount("/static", StaticFiles(directory="frontend"), name="static")


@app.get("/")
def index():
    return FileResponse("frontend/index.html")
