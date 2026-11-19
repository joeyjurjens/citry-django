"""A small Django site with Citry's routes mounted and two Events islands.

The render-inputs test posts server events to it, and the browser test
loads its page. Point `CITRY_APP` at `tests.events_site.app:app` and
`ROOT_URLCONF` at `tests.events_site.urls` (pytest's `urls` marker).
"""
