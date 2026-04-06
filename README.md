# MasG EV Tool

Cross-platform EV scanner for prediction market opportunities. Compares prices on Polymarket and Kalshi against FanDuel sportsbook odds to find mispriced markets.

## Quick Start

### Prerequisites

- Python 3.12
- Node.js 18+
- API keys:
  - [The Odds API](https://the-odds-api.com/) (free tier: 500 req/month)
  - [Kalshi](https://kalshi.com/) API key (optional)

### 1. Clone and set up the backend

```bash
cd masg-ev-tool/backend
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Mac/Linux
pip install -r requirements.txt
```

### 2. Configure environment

Create `backend/.env`:

```
ODDS_API_KEY=your_odds_api_key_here
KALSHI_API_KEY=your_kalshi_api_key_here
```

### 3. Set up the frontend

```bash
cd masg-ev-tool/frontend
npm install
```

### 4. Run

**Option A** — Use the start script (Windows):
```bash
start-dev.bat
```

**Option B** — Manual (two terminals):
```bash
# Terminal 1: backend
cd backend
.venv\Scripts\activate
uvicorn main:app --reload --port 8000

# Terminal 2: frontend
cd frontend
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

## What It Does

- Fetches live odds from FanDuel via The Odds API (truth source)
- Fetches market prices from Polymarket (Gamma API) and Kalshi
- Matches events across platforms by player/team names + date proximity
- Computes edge = true probability - market price
- Applies Kelly criterion for position sizing
- Displays opportunities sorted by edge with BUY/WATCH status

## Supported Sports

| Sport | Odds API | Polymarket | Kalshi |
|-------|----------|------------|--------|
| Tennis | All ATP/WTA | H2H, totals, handicap | H2H |
| MMA/UFC | H2H | H2H | H2H |
| Cricket IPL | H2H | H2H | H2H |
| Rugby NRL | H2H | H2H | H2H |
| UFL | H2H | -- | H2H |
| Hockey AHL | H2H | H2H | H2H |

## Project Structure

```
masg-ev-tool/
├── backend/
│   ├── main.py                    # FastAPI app
│   ├── routers/
│   │   ├── opportunities.py       # /api/opportunities (main endpoint)
│   │   └── odds.py                # /api/odds (debug)
│   ├── services/
│   │   ├── sports_config.py       # Supported sports config
│   │   ├── opportunities.py       # Core EV pipeline
│   │   ├── odds_provider.py       # FanDuel odds (The Odds API)
│   │   ├── matcher.py             # Event matching engine
│   │   ├── devig.py               # Vig removal math
│   │   ├── events.py              # Polymarket Gamma API
│   │   ├── price_history.py       # Historical prices
│   │   └── adapters/
│   │       ├── base.py            # MarketAdapter protocol
│   │       ├── polymarket.py      # Polymarket adapter
│   │       └── kalshi.py          # Kalshi adapter
│   └── models/
│       └── market.py              # Market data model
├── frontend/
│   ├── app/
│   │   ├── page.tsx               # Scanner page
│   │   ├── layout.tsx             # App shell
│   │   └── components/dashboard/
│   │       ├── DashboardClient.tsx # Main client component
│   │       ├── OpportunitiesTable.tsx
│   │       ├── MarketDetailPanel.tsx
│   │       ├── PriceChart.tsx
│   │       └── NavWalletButton.tsx
│   └── lib/
│       ├── api.ts                 # Backend API client
│       └── types.ts               # TypeScript types
└── start-dev.bat                  # Windows dev launcher
```

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/opportunities` | Matched opportunities with edge/kelly/status |
| `GET /api/opportunities?min_edge=0.03` | Filter by minimum edge (3%) |
| `GET /api/opportunities?platform=kalshi` | Filter by platform |
| `GET /api/opportunities/history?platform=polymarket&market_id=123` | Price history |
| `GET /api/opportunities/debug` | Pipeline diagnostic trace |
| `GET /api/odds/tennis` | Raw FanDuel tennis odds |

## Configuration

Engine thresholds are configurable per request via query parameters:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `min_edge` | 0.05 | Minimum edge for BUY status |
| `wide_market_min_edge` | 0.08 | Edge required for wide lines |
| `min_event_match_confidence` | 0.90 | Match confidence threshold |

To add a new sport, edit `backend/services/sports_config.py`.
