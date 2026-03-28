# Tinyfish Travel Deals Agent

This repo gives you a small starting point for a Tinyfish-powered agent that looks for strong-value travel experiences like guided tours, workshops, classes, and activity bundles.

It is intentionally simple:

- Tinyfish handles the browser automation.
- Your code defines a strong search goal and formats the result.
- You can swap destinations, categories, and source sites from the CLI.

## What this starter does

The CLI:

- starts from one travel-experience marketplace such as GetYourGuide or Klook
- asks Tinyfish to search for high-value experiences in a destination
- requests normalized JSON with prices, discount clues, ratings, and booking links
- prints a readable summary and can optionally save raw JSON

## Setup

1. Activate your environment.

```bash
source venv/bin/activate
```

2. Install the local package in editable mode.

```bash
python -m travel_deals_agent.cli --help
```

This starter can run directly from the repo, so you do not need packaging before your first test.

2. Add your Tinyfish API key.

```bash
export TINYFISH_API_KEY=your_api_key_here
```

You can get a key from `https://agent.tinyfish.ai/api-keys`.

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

If you do want the CLI command later, try:

```bash
pip install -e . --no-build-isolation
```

## Supported sites

- `getyourguide`
- `klook`
- `viator`
- `airbnb`

These are just starting URLs. Tinyfish will navigate from there based on the goal prompt.

## Files

- `travel_deals_agent/cli.py`: CLI entrypoint and result formatting
- `travel_deals_agent/prompts.py`: prompt template that tells Tinyfish what to extract
- `travel_deals_agent/config.py`: API key loading

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
