# Tinyfish Travel Deals Agent

This repo gives you a small starting point for a Tinyfish-powered agent that looks for strong-value travel experiences like guided tours, workshops, classes, and activity bundles.

It is intentionally simple:

- Tinyfish handles the browser automation, now with concurrent runs across multiple providers.
- Gemini can optionally discover relevant provider URLs with Google Search grounding.
- A FastAPI backend exposes the concurrent search flow to a Next.js frontend.
- Your code defines the search goal, aggregates the results, and streams progress to the UI.

## What this starter does

The CLI:

- can start from one travel-experience marketplace such as GetYourGuide or Klook
- can optionally use Gemini to discover 3-5 relevant provider URLs first
- runs Tinyfish across all selected providers concurrently
- requests normalized JSON with prices, discount clues, ratings, booking links, and site summaries
- prints a readable summary and can optionally save raw JSON

The web app:

- lets the user enter a search category from a Next.js interface
- launches a backend search session
- shows a live panel for each concurrent Tinyfish agent
- streams progress and site-level results into the page

## Setup

1. Activate your environment.

```bash
source venv/bin/activate
```

2. Install the local package in editable mode.

```bash
pip install -e . --no-build-isolation
```

This starter can run directly from the repo, so you do not need packaging before your first test.

3. Create a local `.env` from `.env.example`, then add your API keys.

4. Add your Tinyfish API key.

```bash
export TINYFISH_API_KEY=your_api_key_here
```

You can get a key from `https://agent.tinyfish.ai/api-keys`.

5. If you want provider discovery, add your Gemini API key too.

```bash
export GEMINI_API_KEY=your_api_key_here
```

You can also use `GOOGLE_API_KEY`. The discovery step uses Gemini with Google Search grounding.

## First run

```bash
python -m travel_deals_agent.cli \
  --destination "Tokyo" \
  --site getyourguide \
  --date-hint "April 2026" \
  --currency USD \
  --max-results 5
```

Or save the structured result:

```bash
python -m travel_deals_agent.cli \
  --destination "Barcelona" \
  --site klook \
  --category "food tours and workshops" \
  --json-out results/barcelona-klook.json
```

If you want provider discovery plus concurrent Tinyfish runs:

```bash
python -m travel_deals_agent.cli \
  --destination "Rome" \
  --category "museum tickets and skip-the-line experiences" \
  --discover-providers \
  --provider-limit 4 \
  --max-results 3
```

## Web app

Start the Python API:

```bash
travel-deals-agent-api
```

Then start the Next.js frontend:

```bash
cd frontend
npm install
npm run dev
```

The frontend expects the API at `http://localhost:8000` by default. If you need a different backend URL, set `NEXT_PUBLIC_API_BASE_URL` before running the frontend.

## Provider discovery workflow

To discover relevant provider URLs before Tinyfish starts browsing, use:

```bash
python -m travel_deals_agent.cli \
  --destination "Rome" \
  --category "museum tickets and skip-the-line experiences" \
  --discover-providers \
  --provider-limit 4 \
  --max-results 3
```

That workflow does this:

1. Gemini uses Google Search grounding to find 3-5 relevant ticket providers.
2. The Gemini response returns structured provider URLs.
3. Tinyfish runs once per discovered URL and now does that concurrently.

## Supported sites

- `getyourguide`
- `klook`
- `viator`
- `airbnb`

These are just starting URLs for the manual mode. Tinyfish will navigate from there based on the goal prompt.

## Files

- `travel_deals_agent/cli.py`: CLI entrypoint and result formatting
- `travel_deals_agent/search_service.py`: shared concurrent search workflow used by CLI and API
- `travel_deals_agent/server.py`: FastAPI server for frontend-driven searches
- `travel_deals_agent/prompts.py`: prompt template that tells Tinyfish what to extract
- `travel_deals_agent/config.py`: API key loading
- `travel_deals_agent/provider_discovery.py`: Gemini discovery step for provider URLs
- `frontend/`: Next.js dashboard for launching searches and watching agent streams

## Good next upgrades

Once this starter is working, the next useful steps are:

1. Run the agent across multiple sites and merge/rank the results locally.
2. Add a deal scoring function that rewards discount size, rating, and review volume.
3. Store historical runs so you can compare whether a deal is actually improving over time.
4. Add filters like budget cap, trip length, family-friendly, or private group only.
5. Build a small FastAPI or Streamlit UI on top of the CLI.

## Important caveat

This starter is best for prototyping. Marketplace websites change often, and some deals only appear for certain dates, currencies, or regions. Expect to iterate on the prompt and possibly use Tinyfish's stealth mode for harder sites:

```bash
python -m travel_deals_agent.cli --destination "Seoul" --site klook --stealth
```
