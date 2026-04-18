import time
import yfinance as yf
from datetime import date, timedelta
from backend.database import upsert_snapshot

# Global throttle: ensure at least 3s between Yahoo Finance requests
_last_yf_call: float = 0.0
_MIN_INTERVAL = 3.0


def _throttle():
    global _last_yf_call
    elapsed = time.time() - _last_yf_call
    if elapsed < _MIN_INTERVAL:
        time.sleep(_MIN_INTERVAL - elapsed)
    _last_yf_call = time.time()


def _get_info(symbol: str, retries: int = 4) -> dict:
    """Fetch .info with throttle + retry + exponential backoff."""
    last_exc = None
    for attempt in range(retries):
        try:
            _throttle()
            info = yf.Ticker(symbol).info
            if info and len(info) > 5:
                return info
        except Exception as exc:
            last_exc = exc
            print(f"[fetcher] attempt {attempt} failed for {symbol}: {type(exc).__name__}: {exc}")
        time.sleep(2 ** attempt)  # extra backoff on top of throttle
    raise RuntimeError(
        f"Could not fetch data for {symbol}: {last_exc}"
    ) from last_exc


def fetch_metadata(ticker: str) -> dict:
    info = _get_info(ticker)
    return {
        "ticker": ticker.upper(),
        "company": info.get("longName") or info.get("shortName") or ticker.upper(),
        "sector": info.get("sector") or "Unknown",
        "_info": info,  # pass through so callers can reuse it
    }


def fetch_live_pe(ticker: str, info: dict | None = None) -> dict:
    if info is None:
        info = _get_info(ticker)
    price = info.get("currentPrice") or info.get("regularMarketPrice")
    trailing_eps = info.get("trailingEps")
    trailing_pe = info.get("trailingPE")
    forward_pe = info.get("forwardPE")

    if trailing_pe is None and price and trailing_eps and trailing_eps != 0:
        trailing_pe = round(price / trailing_eps, 2)

    return {
        "ticker": ticker.upper(),
        "price": price,
        "trailing_eps": trailing_eps,
        "trailing_pe": trailing_pe,
        "forward_pe": forward_pe,
        "date": date.today().isoformat(),
    }


def backfill_history(ticker: str, days: int = 90, info: dict | None = None):
    """Backfill daily P/E snapshots. Pass `info` to avoid a redundant API call."""
    if info is None:
        info = _get_info(ticker)

    trailing_eps = info.get("trailingEps")
    forward_pe_val = info.get("forwardPE")

    end = date.today()
    start = end - timedelta(days=days + 10)

    _throttle()
    hist = yf.Ticker(ticker).history(
        start=start.isoformat(), end=end.isoformat(), interval="1d"
    )
    if hist.empty:
        return

    for ts, row in hist.iterrows():
        day = ts.date().isoformat()
        price = round(float(row["Close"]), 4)
        t_pe = round(price / trailing_eps, 2) if trailing_eps and trailing_eps != 0 else None
        upsert_snapshot(
            ticker=ticker.upper(),
            date=day,
            price=price,
            trailing_eps=trailing_eps,
            trailing_pe=t_pe,
            forward_pe=forward_pe_val,
        )


def refresh_all(tickers: list[str]) -> dict[str, dict]:
    results = {}
    for ticker in tickers:
        try:
            results[ticker] = fetch_live_pe(ticker)
        except Exception as e:
            results[ticker] = {"error": str(e)}
    return results
