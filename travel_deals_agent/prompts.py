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
