# MasG EV Tool

Cross-platform EV scanner for prediction market opportunities. Compares prices on Polymarket and Kalshi against FanDuel sportsbook odds to find mispriced markets, with phone push notifications for new opportunities.

## Quick Start

### Prerequisites

- Python 3.12
- Node.js 18+
- API keys:
  - [The Odds API](https://the-odds-api.com/) (free tier: 500 req/month)
  - [Kalshi](https://kalshi.com/) API key (optional)
  - [Pushover](https://pushover.net/) for phone notifications (optional)

### 1. Clone and set up the backend

```bash
cd masg-ev-tool/backend
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Mac/Linux
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env with your API keys
```

### 3. Set up the frontend

```bash
cd masg-ev-tool/frontend
npm install
```

### 4. Run

**Option A** -- Use the start script (Windows):
```bash
start-dev.bat
```

**Option B** -- Manual (two terminals):
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

## How It Works

### Rule Engine Pipeline

Every opportunity goes through a two-pass evaluation:

**Pass A -- Feature Extraction**
- Fetches markets from Polymarket and Kalshi
- Fetches FanDuel odds via The Odds API
- Matches events across platforms by player/team names + date proximity
- Computes all pricing, confidence, and ambiguity metrics

**Pass B -- Rule Engine**
- Evaluates 20 named rules from a centralized policy table
- Each rule is CRITICAL (fail = SKIP) or DOWNGRADE (fail = WATCH)
- Classifies every opportunity as BUY, WATCH, or SKIP with full reasoning

### Classification

| Status | Meaning |
|--------|---------|
| **BUY** | All rules pass: positive edge above threshold, high confidence match, no ambiguity |
| **WATCH** | Positive edge but one or more quality/ambiguity concerns (e.g., edge too thin, confidence gap) |
| **SKIP** | Critical failure: no edge, live event, name mismatch, line mismatch, etc. |

### Key Metrics

- **Edge** = devigged true probability - market price - 1c cost buffer
- **True probability** = FanDuel odds after removing the bookmaker's vig (multiplicative devig)
- **Kelly** = fractional Kelly criterion (1/5 Kelly, capped at 25%) for position sizing
- **FD Confidence** = High/Medium/Low based on overround and line width

## Phone Alerts

The monitoring system scans for new BUY opportunities on a configurable interval and sends instant push notifications to your phone via Pushover.

### Setup

1. Create a [Pushover](https://pushover.net/) account and install the app on your phone
2. Add your user key and app token to `backend/.env`
3. Open the dashboard and expand the **Phone Alerts** panel
4. Choose a preset or customize settings
5. Press **Start Monitoring**

### How Alerts Work

- The system scans all platforms on your configured refresh interval (default: every 15 minutes)
- When a new BUY opportunity is found, you get an instant push notification with the event, side, EV%, price, and a link to the platform
- **Cooldown** prevents the same opportunity from buzzing your phone repeatedly. Once you're alerted about "Alcaraz +6.2% EV", that specific opportunity is silenced for the cooldown window (default: 30 minutes). If the edge improves significantly (3%+), it breaks through the cooldown because that's new actionable information. Different opportunities always alert immediately.

### Presets

| Preset | Min EV | Refresh | Cooldown | Max Alerts/hr |
|--------|--------|---------|----------|---------------|
| Conservative | 8% | 30 min | 60 min | 5 |
| Standard | 5% | 15 min | 30 min | 10 |
| Aggressive | 3% | 10 min | 15 min | 20 |

### API Budget

The Odds API free tier allows 500 requests/month. Each scan uses ~5 requests (one per sport). At 15-minute intervals that's ~20 requests/hour. Monitor the **API Budget** counter in the alerts panel to track usage.

## Supported Sports

| Sport | Odds API | Polymarket | Kalshi |
|-------|----------|------------|--------|
| Tennis | All ATP/WTA | H2H | H2H |
| Cricket IPL | H2H | H2H | H2H |
| Rugby NRL | H2H | H2H | H2H |
| UFL | H2H | -- | H2H |
| Hockey AHL | H2H | H2H | H2H |

## Project Structure

```
masg-ev-tool/
├── backend/
│   ├── main.py                        # FastAPI app
│   ├── routers/
│   │   ├── opportunities.py           # /api/opportunities
│   │   ├── monitor.py                 # /api/monitor (alerts)
│   │   └── odds.py                    # /api/odds (debug)
│   ├── services/
│   │   ├── engine_config.py           # All engine thresholds
│   │   ├── rule_engine.py             # Policy table + classification
│   │   ├── feature_extractor.py       # Pass A: feature extraction
│   │   ├── opportunities.py           # Two-pass pipeline
│   │   ├── normalizer.py              # Name normalization
│   │   ├── odds_provider.py           # FanDuel odds (The Odds API)
│   │   ├── matcher.py                 # Event matching
│   │   ├── devig.py                   # Vig removal
│   │   ├── sports_config.py           # Supported sports
│   │   ├── events.py                  # Polymarket Gamma API
│   │   ├── price_history.py           # Historical prices
│   │   ├── adapters/
│   │   │   ├── base.py                # MarketAdapter protocol
│   │   │   ├── polymarket.py          # Polymarket adapter
│   │   │   └── kalshi.py              # Kalshi adapter
│   │   └── monitor/
│   │       ├── config.py              # Alert presets + config
│   │       ├── manager.py             # Alert decisions + dedup
│   │       ├── notifier.py            # Pushover notifications
│   │       ├── state.py               # Alert state persistence
│   │       ├── scheduler.py           # Monitoring orchestrator
│   │       ├── odds_poller.py         # Scheduled Odds API poller
│   │       ├── ws_polymarket.py       # Polymarket WebSocket
│   │       └── ws_kalshi.py           # Kalshi WebSocket
│   ├── tests/
│   │   ├── test_rule_engine.py        # 115 rule engine tests
│   │   ├── test_feature_extractor.py  # 46 feature extraction tests
│   │   ├── test_normalizer.py         # 33 normalization tests
│   │   └── test_ambiguity.py          # 10 ambiguity detection tests
│   └── models/
│       └── market.py                  # Market data model
├── frontend/
│   ├── app/
│   │   ├── page.tsx
│   │   └── components/dashboard/
│   │       ├── DashboardClient.tsx
│   │       ├── OpportunitiesTable.tsx
│   │       ├── MarketDetailPanel.tsx
│   │       └── NotificationSettings.tsx
│   └── lib/
│       ├── api.ts                     # Opportunities API client
│       ├── monitor-api.ts             # Monitor API client
│       └── types.ts                   # TypeScript types
└── start-dev.bat
```

## API Endpoints

### Opportunities

| Endpoint | Description |
|----------|-------------|
| `GET /api/opportunities` | Matched opportunities with edge/kelly/status |
| `GET /api/opportunities?min_edge=0.03` | Filter by minimum edge (3%) |
| `GET /api/opportunities?platform=kalshi` | Filter by platform |
| `GET /api/opportunities/policy` | Current rule policy table (20 rules) |
| `GET /api/opportunities/history` | Price history for a market |
| `GET /api/opportunities/debug` | Full pipeline diagnostic trace |

### Monitoring

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/monitor/config` | GET | Current alert settings |
| `/api/monitor/config` | POST | Update settings (does not start/stop) |
| `/api/monitor/start` | POST | Start monitoring loop |
| `/api/monitor/stop` | POST | Stop monitoring loop |
| `/api/monitor/status` | GET | Live status, countdown, API budget |
| `/api/monitor/history` | GET | Recent alert history |
| `/api/monitor/test` | POST | Send test push notification |

## Configuration

Engine thresholds (query parameters on `/api/opportunities`):

| Parameter | Default | Description |
|-----------|---------|-------------|
| `min_edge` | 0.05 | Minimum edge for BUY (5%) |
| `wide_market_min_edge` | 0.08 | Edge required for wide lines (8%) |
| `survival_threshold` | 0.85 | Match confidence below this = SKIP |
| `buy_threshold` | 0.90 | Match confidence below this = WATCH |
| `min_true_probability` | 0.40 | Devigged probability floor |

To add a new sport, edit `backend/services/sports_config.py`.

## Tests

```bash
cd backend
.venv\Scripts\activate
python -m pytest tests/ -v
```

204 tests covering all 20 policy rules, normalization edge cases, feature extraction, and ambiguity detection.
