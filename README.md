# TravellingFish

TravellingFish is a small full-stack app for finding bookable attraction tickets and travel experiences from live websites.

It combines:

- Gemini provider discovery to find relevant ticketing websites
- TinyFish browser agents to search those websites in parallel
- FastAPI backend that manages sessions and streams events over SSE
- Next.js frontend that shows the provider shortlist, live agent status, and final results

## App Features

The current workflow is:

1. The user enters a free-form search request such as `Singapore Zoo child ticket` or `Universal Studios Japan express pass`.
2. Gemini optionally discovers relevant provider homepages or top-level landing pages.
3. TinyFish launches one run per provider and searches those sites concurrently.
4. The backend normalizes site results into a shared payload.
5. The frontend streams live progress and shows per-site summaries and extracted options.

What works today:

- concurrent TinyFish runs across discovered providers
- direct-provider filtering to avoid marketplaces by default
- live SSE updates for queued, running, retrying, blocked, failed, and completed agents
- optional TinyFish stealth mode (bypass CAPTCHAs etc)
- JSON output from the CLI for downstream inspection
- manual single-site CLI mode for `getyourguide`, `klook`, `viator`, or `airbnb`

Current frontend behavior:

- always uses provider discovery
- lets you set search text, date, currency, provider limit, results per site, direct-provider filtering, and stealth mode
- shows the discovered provider shortlist before and during execution
- embeds TinyFish preview URLs when available

## Repo Layout

- `travel_deals_agent/cli.py`: CLI entrypoint and terminal formatting
- `travel_deals_agent/search_service.py`: shared orchestration, normalization, retries, and event emission
- `travel_deals_agent/provider_discovery.py`: Gemini grounded discovery and provider URL cleanup
- `travel_deals_agent/server.py`: FastAPI app with session creation, polling, and SSE endpoints
- `travel_deals_agent/prompts.py`: TinyFish and Gemini prompt builders
- `travel_deals_agent/config.py`: API key loading from env vars or `.env`
- `frontend/`: Next.js dashboard

## Requirements

- Python 3.11+
- Node.js 18+ recommended
- a TinyFish API key
- a Gemini API key (there's a free tier) if you want provider discovery

## Configuration

Copy `.env.example` to `.env` and fill in your keys:

```env
TINYFISH_API_KEY=your_tinyfish_api_key_here
GEMINI_API_KEY=your_gemini_api_key_here
```

## Quickstart

### 1. Set up Python

PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e . --no-build-isolation
```

macOS or Linux:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e . --no-build-isolation
```

### 2. Add API keys

Create `.env` from `.env.example`, then add at least:

- `TINYFISH_API_KEY`
- `GEMINI_API_KEY`

### 4. Run the web app

Start the backend API:

```powershell
travel-deals-agent-api
```

In a second terminal, start the frontend:

```powershell
cd frontend
npm install
npm run dev
```

Then open `http://localhost:3000`.

By default the frontend expects the backend at `http://localhost:8000`. Override that with `NEXT_PUBLIC_API_BASE_URL` if needed.

### 4 (optional and work in progress). Run the CLI

Single-site mode:

```powershell
python -m travel_deals_agent.cli `
  --site getyourguide `
  --category "Singapore Zoo tickets" `
  --date-hint "2026-04-01" `
  --currency USD `
  --max-results 3
```

Discovery mode across multiple providers:

```powershell
python -m travel_deals_agent.cli `
  --category "Singapore Zoo tickets" `
  --date-hint "2026-04-01" `
  --discover-providers `
  --provider-limit 4 `
  --max-results 3
```

Save the full JSON payload:

```powershell
python -m travel_deals_agent.cli `
  --category "Universal Studios Japan express pass" `
  --discover-providers `
  --json-out results/usj.json
```

## CLI Reference

Important flags:

- `--category`: free-form search request
- `--date-hint`: optional date or travel timing hint
- `--currency`: preferred display currency label
- `--max-results`: max results per site
- `--discover-providers`: run Gemini discovery before TinyFish
- `--provider-limit`: number of providers to discover, `1-5`
- `--allow-marketplaces`: include marketplace domains instead of filtering them out
- `--stealth`: use the TinyFish stealth browser profile
- `--json-out`: save the final payload to disk
- `--show-sse`: print live event messages in the terminal

Supported manual start sites:

- `getyourguide`
- `klook`
- `viator`
- `airbnb`

## API Endpoints

- `GET /api/health`: health check
- `POST /api/searches`: create a search session
- `GET /api/searches/{session_id}`: fetch the final session state
- `GET /api/searches/{session_id}/events`: stream live SSE events

The frontend currently posts requests with provider discovery enabled by default.

## Notes And Limitations

- Travel websites change often, so prompt tuning and retry logic still matter.
- Some providers block automation or expose unstable preview streams. (eg Klook)
- Provider discovery tries to prefer official or direct booking pages, but relevance is still model-driven.
- Price, rating, and discount fields are only as complete as the target site makes them.
