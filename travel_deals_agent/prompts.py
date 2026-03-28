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
    """Build a goal that asks Tinyfish for normalized travel experience results."""
    timing = date_hint or "the user's travel window is flexible"
    return dedent(
        f"""
        Find the best matching bookable travel experiences in {destination}.

        Focus on {category}.
        Travel timing: {timing}.
        Preferred display currency: {currency}.
        Return up to {max_results} strongest options.

        Search the current website thoroughly for experiences such as guided tours,
        classes, workshops, attraction bundles, day trips, skip-the-line tickets,
        and other bookable activities. If the category appears to describe a specific
        attraction or activity, prioritize exact or very close matches first.

        Stay tightly anchored to the requested activity. For example, if the user asks
        for "Alcatraz tours", do not drift into generic San Francisco passes, dinner
        cruises, Muir Woods trips, city sightseeing bundles, or unrelated attractions
        unless the requested activity is explicitly included in the title or product
        description.

        Prefer options that are currently bookable and relevant, even if the site
        does not show an explicit discount. If discounts, bundles, sale badges,
        coupon messaging, or strong value signals are present, include them, but do
        not return an empty result just because no discount is visible.

        Use the site's own search, destination pages, or activity pages if needed.
        If there are multiple variants, choose the strongest matches for the exact
        activity first. Only include nearby alternatives if they clearly contain the
        requested activity as a major part of the experience. If you cannot find exact
        or closely matching bookable options, return an empty result instead of
        unrelated experiences.

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
          "summary": "1-2 sentence summary of the strongest matching bookable options found on this site"
        }}

        If the site has no relevant results after searching or browsing, return:
        {{
          "destination": "{destination}",
          "searched_category": "{category}",
          "results": [],
          "summary": "No relevant bookable matches found on this site."
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
        - providers with public browseable inventory pages that are likely to work for an automated browser agent

        Avoid:
        - blog posts
        - affiliate roundups
        - news articles
        - generic informational pages with no bookable inventory
        - providers that are heavily gated by CAPTCHA, login walls, or aggressive bot protection unless there are no better options

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
