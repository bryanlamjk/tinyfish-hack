"""Prompt builders for Tinyfish travel deal searches."""

from __future__ import annotations

from textwrap import dedent


def build_goal(
    *,
    destination: str,
    date_hint: str | None,
    category: str,
    currency: str,
    max_results: int,
) -> str:
    """Build a goal that asks Tinyfish for normalized travel experience deals."""
    timing = date_hint or "the user's travel window is flexible"
    return dedent(
        f"""
        Find the best-value travel experiences in {destination}.

        Focus on {category}.
        Travel timing: {timing}.
        Preferred display currency: {currency}.
        Return up to {max_results} strongest options.

        Search the current website thoroughly for experiences such as guided tours,
        classes, workshops, attraction bundles, day trips, skip-the-line tickets,
        and other bookable activities. Prioritize deals, discounts, limited-time
        offers, bundles, sale badges, coupon messaging, and unusually strong value
        for money.

        For each option, extract:
        - title
        - provider
        - price
        - original_price if shown
        - currency
        - discount_text
        - duration
        - rating
        - review_count
        - location
        - short_reason_it_is_a_good_deal
        - booking_url

        Return valid JSON with this shape:
        {{
          "destination": "{destination}",
          "searched_category": "{category}",
          "results": [
            {{
              "title": "string",
              "provider": "string or null",
              "price": "string or null",
              "original_price": "string or null",
              "currency": "{currency}",
              "discount_text": "string or null",
              "duration": "string or null",
              "rating": "string or null",
              "review_count": "string or null",
              "location": "string or null",
              "short_reason_it_is_a_good_deal": "string",
              "booking_url": "string"
            }}
          ],
          "summary": "1-2 sentence summary of the strongest deals found on this site"
        }}

        If the site has no relevant results, return:
        {{
          "destination": "{destination}",
          "searched_category": "{category}",
          "results": [],
          "summary": "No strong matches found on this site."
        }}
        """
    ).strip()


def build_provider_discovery_prompt(
    *,
    destination: str,
    category: str,
    date_hint: str | None,
    max_providers: int,
) -> str:
    """Build a grounded Gemini prompt for ticket provider discovery."""
    timing = date_hint or "flexible travel dates"
    return dedent(
        f"""
        Use Google Search grounding to find {max_providers} strong ticket or experience
        providers for travelers going to {destination}.

        Focus on sites that are likely to sell or list bookable options for:
        {category}

        Travel timing: {timing}.

        Prioritize:
        - established booking marketplaces
        - official attraction or experience ticketing sites
        - sites that are useful starting points for browsing and comparing offers

        Avoid:
        - blog posts
        - affiliate roundups
        - news articles
        - generic informational pages with no bookable inventory

        Return provider URLs that Tinyfish can open directly, preferably homepages,
        destination pages, or activity category pages.

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
