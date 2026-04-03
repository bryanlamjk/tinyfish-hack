"""Prompt builders for Tinyfish travel deal searches."""

from __future__ import annotations

from textwrap import dedent


def build_goal(
    *,
    date_hint: str | None,
    category: str,
    currency: str,
    max_results: int,
) -> str:
    """Build a goal closer to the original working marketplace extraction flow."""
    timing = date_hint or "the user's travel window is flexible"
    return dedent(
        f"""
        Find the best matching bookable ticket or experience options on this website.

        Search request: {category}
        Travel timing: {timing}.
        Preferred display currency: {currency}.
        Return up to {max_results} strongest options.

        Search the current website thoroughly for bookable tickets, tours, passes,
        attraction admission, day trips, classes, and other relevant
        activities that closely match the search request. Prioritize exact or very
        close matches first.

        Favor options that are clearly bookable now and have visible pricing.
        Standard ticket prices are important, but if the site presents multiple
        clearly relevant bookable options, return the ones matching the users request instead of
        returning nothing.

        Rules:
        1. Use only this website.
        2. Use the site's search, category pages, or browse pages if needed.
        3. Close cookie or consent banners if they block the page.
        4. Wait for the pricing section, listing cards, ticket options, or booking widget to fully load before extracting.
        5. If the page is still rendering, shows loading placeholders, or lazy-loads pricing, wait and scroll before deciding there are no results.
        6. If pricing is hidden behind tabs, accordions, or ticket option selectors, click the standard or general admission option first.
        7. Do not click checkout, payment, or final purchase buttons.
        8. Ignore login-only results, blog posts, generic guide pages, and unrelated attractions.
        9. Ignore heavily upsold bundles, memberships, hotel packages, and gift cards unless they are the only clearly relevant priced options.
        10. If some fields are missing, still return the result with null for missing fields.
        11. Return JSON only.

        Return JSON with this exact structure:
        {{
          "searched_category": "{category}",
          "results": [
            {{
              "title": "Example Experience Title",
              "provider": "Example Provider",
              "price": "$67.67",
              "currency": "{currency}",
              "duration": null,
              "rating": null,
              "review_count": null,
              "short_reason_it_is_a_good_deal": "Clearly priced, bookable option that closely matches the request.",
              "booking_url": "https://example.com/booking"
            }}
          ],
          "summary": "1-2 sentence summary of the strongest relevant bookable options found on this site."
        }}

        If the site has no relevant results, return:
        {{
          "searched_category": "{category}",
          "results": [],
          "summary": "No strong matches found on this site."
        }}
        """
    ).strip()


def build_router_prompt(
    *,
    category: str,
    date_hint: str | None,
    site: str | None,
    discover_providers: bool,
) -> str:
    """Build a routing prompt for the top-level orchestrator."""
    timing = date_hint or "no date specified"
    manual_site = site or "none"
    return dedent(
        f"""
        You are the routing layer for a travel booking assistant.

        Decide whether the user query should:
        - go directly to the ticket scraper because a provider or website is already specified
        - go to web search first to discover relevant providers before scraping

        User query: {category}
        Date hint: {timing}
        Manual site preference: {manual_site}
        Provider discovery requested by caller: {str(discover_providers).lower()}

        Routing rules:
        1. Choose "direct_ticket_scrape" when the query explicitly names a website, domain, URL, or provider to search on.
        2. Choose "direct_ticket_scrape" when the caller already supplied a manual site preference.
        3. Choose "search_then_scrape" when the query asks for tickets or bookable options but does not clearly specify where to look.
        4. Prefer direct routing only when the provider instruction is explicit, not implied.
        5. Return JSON only with no markdown fences.

        Return JSON with this exact structure:
        {{
          "route": "direct_ticket_scrape" | "search_then_scrape",
          "reasoning_summary": "short explanation",
          "rewritten_query": "clean search request to pass to downstream tools",
          "provider_name": "explicit provider name if present, otherwise null",
          "provider_url": "explicit provider URL if present, otherwise null"
        }}
        """
    ).strip()


def build_provider_discovery_prompt(
    *,
    category: str,
    date_hint: str | None,
    max_providers: int,
    block_marketplace_providers: bool,
) -> str:
    """Build a grounded Gemini prompt for ticket provider discovery."""
    timing = date_hint or "flexible travel dates"
    marketplace_guidance = (
        """
        Direct providers only:
        - official attraction or experience ticketing sites
        - direct local operators
        - official venue, museum, theme park, cruise, tour, or attraction pages

        Avoid marketplaces and aggregators such as:
        - klook.com
        - trip.com
        - getyourguide.com
        - viator.com
        - expedia.com
        - booking.com
        - kkday.com
        - headout.com
        - tiqets.com
        - pelago.co
        """
        if block_marketplace_providers
        else """
        Include all relevant provider types:
        - direct official ticket providers
        - local operators
        - travel marketplaces and aggregators when they are useful starting points

        Do not block marketplace domains in this mode.
        """
    )
    return dedent(
        f"""
        Use Google Search grounding to find {max_providers} ticket providers for this travel search request: {category}

        Travel timing: {timing}.

        Prioritize:
        - sites that are likely to work for an automated browser agent without login
        - sites that are useful starting points for browsing and comparing offers

        {marketplace_guidance}

        Avoid:
        - blog posts
        - affiliate roundups
        - news articles
        - generic informational pages with no bookable inventory
        - providers that are heavily gated by CAPTCHA, login walls, or aggressive bot protection
        - single attraction detail pages when a broader homepage, destination page, or search page exists
        - provider URLs that land on a single product, single ticket, booking step, or checkout flow

        Return provider URLs that Tinyfish can open directly, strongly preferring main pages only:
        - provider homepage
        - locale homepage
        - top-level destination page
        - top-level search page

        Do not return product-detail, activity-detail, booking, or checkout pages.

        Return only valid JSON with this exact shape and no markdown fences:
        {{
          "search_summary": "short summary",
          "providers": [
            {{
              "provider_name": "string",
              "url": "https://example.com",
              "why_relevant": "string"
            }}
          ]
        }}
        """
    ).strip()
