# MoneyTree — Engineering Spec

## Overview
A local web application for tracking P/E ratios across a personal stock watchlist.
Stocks are grouped by official sector. The user can add/remove stocks from the UI.
A 90-day P/E trend chart is shown per stock. Price data is polled every 15 minutes
during market hours via yfinance (Yahoo Finance). A daily snapshot is written to SQLite
at 4:30 PM ET after market close.

---

## Goals
- Spend ~5 minutes/day reviewing P/E trends
- Spot P/E spikes visually without any manual research
- Learn stocks by sector and understand relative valuations

## Non-Goals (for now)
- Sub-minute real-time streaming
- Email or push alerts
- Multi-user support
- Mobile app
- Authentication

---

## Architecture

```
Browser (HTML/CSS/JS)
      │
      │  REST (JSON)
      ▼
FastAPI (Python)          ← runs on localhost:8000
      │
      ├── yfinance         ← Yahoo Finance data (price, EPS, sector, metadata)
      ├── Poller           ← polls yfinance every 15 min during market hours
      │                      (M–F, 9:30 AM–4:00 PM ET only)
      └── SQLite           ← stores daily P/E snapshots per ticker
```

---

## Data Model

### Table: `stocks`
| Column   | Type | Description                        |
|----------|------|------------------------------------|
| ticker   | TEXT | Primary key e.g. "AAPL"           |
| company  | TEXT | Full name e.g. "Apple Inc."        |
| sector   | TEXT | Official sector from yfinance      |
| added_at | TEXT | ISO date when user added the stock |

### Table: `pe_snapshots`
| Column       | Type  | Description                          |
|--------------|-------|--------------------------------------|
| ticker       | TEXT  | Foreign key → stocks.ticker          |
| date         | TEXT  | YYYY-MM-DD                           |
| price        | REAL  | Closing price                        |
| trailing_eps | REAL  | TTM earnings per share               |
| trailing_pe  | REAL  | price ÷ trailing_eps                 |
| forward_pe   | REAL  | Analyst estimate based P/E           |

Unique constraint on `(ticker, date)` — one row per stock per day.

---

## API Endpoints

### Stocks (Watchlist Management)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/stocks` | List all tracked stocks grouped by sector |
| POST | `/stocks` | Add a ticker to watchlist (fetches metadata from yfinance) |
| DELETE | `/stocks/{ticker}` | Remove a ticker and all its history |

### P/E Data
| Method | Path | Description |
|--------|------|-------------|
| GET | `/stocks/{ticker}/pe` | Today's P/E snapshot (live from yfinance) |
| GET | `/stocks/{ticker}/history` | 90-day P/E history from SQLite |

### Utility
| Method | Path | Description |
|--------|------|-------------|
| POST | `/refresh` | Manually trigger a data refresh for all tickers |
| GET | `/health` | Server health check |

---

## Frontend Pages

### Main Dashboard (`/`)
- Stocks grouped by sector (e.g. Technology, Energy, Retail)
- Each sector is a collapsible section
- Each stock card shows:
  - Company name + ticker
  - Today's price
  - Trailing P/E (color coded: green <15, yellow 15–30, red >30)
  - 90-day P/E trend chart (line graph, spikes highlighted)
- "Add Stock" button → opens modal → user types ticker → stock appears in correct sector
- "Remove" button per stock card

### No separate pages — single page app (SPA)

---

## Frontend Tech

| Concern | Choice | Reason |
|---------|--------|--------|
| Framework | Vanilla HTML + JS (no framework) | Simple, no build step, easy to learn |
| Charts | Chart.js | Lightweight, good line charts, no React needed |
| Styling | CSS (no Tailwind) | Zero dependencies |
| API calls | `fetch()` (native browser) | No libraries needed |

---

## Data Refresh Strategy

| Trigger | What happens |
|---------|-------------|
| Every 15 min (market hours) | Poller fetches live price for all tickers via yfinance, recomputes P/E, updates in-memory state served to browser |
| Daily at 4:30 PM ET (close) | Writes the day's final P/E snapshot to SQLite as the canonical daily record |
| Outside market hours | Polling stops — browser shows last known values with a "Market closed" indicator |
| Manual "Refresh" button | Forces an immediate fetch regardless of schedule |
| New stock added | Immediately fetches today's data + backfills 90 days of history into SQLite |
| Stock removed | Deletes stock row + all its pe_snapshots |

**Market hours:** Monday–Friday, 9:30 AM–4:00 PM US/Eastern.
Backfill on add: reconstructs 90-day P/E history using yfinance price history + quarterly EPS.

---

## Spike Detection Logic
- Compute 90-day average P/E for the stock
- A data point is a "spike" if it exceeds average × 1.2 (20% above average)
- Spikes are highlighted as red dots on the trend chart
- No alert — visual only

---

## Project File Structure

```
moneyTree/
├── backend/
│   ├── main.py          # FastAPI app, all routes
│   ├── database.py      # SQLite schema + query helpers
│   ├── fetcher.py       # yfinance calls, backfill logic
│   ├── poller.py        # 15-min market-hours polling loop
│   └── scheduler.py     # Daily 4:30 PM ET snapshot writer
├── frontend/
│   ├── index.html       # Single page, all UI
│   ├── style.css        # Styles
│   └── app.js           # fetch() calls + Chart.js rendering
├── pe_history.db        # SQLite database (auto-created)
├── requirements.txt     # Python dependencies
├── .env.example         # Environment variable template
└── SPEC.md              # This file
```

---

## Python Dependencies
- `fastapi` — API framework
- `uvicorn` — ASGI server
- `yfinance` — Yahoo Finance market data
- `pandas` — data wrangling for yfinance output
- `python-dotenv` — env var management
- `pytz` — timezone handling (market hours check)
- `apscheduler` — runs the 15-min poller + daily 4:30 PM job in background

---

## Running Locally

```bash
# Install dependencies
pip3 install -r requirements.txt

# Start API server
uvicorn backend.main:app --reload --port 8000

# Open in browser
open http://localhost:8000
```

---

## Open Questions / Future
- Hosting: Railway or Render (~$5/mo) when ready to access from phone
- Alerts: email digest when P/E spikes (deferred)
- Forward P/E comparison view (deferred)
- Sector average P/E benchmark line on chart (deferred)
