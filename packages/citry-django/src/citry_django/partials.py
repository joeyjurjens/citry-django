"""Responses that hold part of a page, such as an htmx swap.

A full page loads Citry's browser runtime once and starts each island from
the configuration block beside it. A partial response is inserted into a page
that is already loaded: by htmx, by a `fetch()` of the project's own, or as a
Django template partial (`"page.html#name"`). That page may or may not have
the runtime yet, and a start script inserted with `innerHTML` never runs. So
citry-django writes each island in a partial response with Citry's
`"fragment"` strategy: a small loader that adds the runtime only when the page
lacks it, and a data block the runtime finds by itself once the HTML is in
the page.

A partial is also not a page of its own: its islands must carry the CSP nonce
of the page they land in, not the nonce of the response that carried them.
"""

from __future__ import annotations

from typing import Any

#: The request attribute a view sets to say its response is part of a page.
PARTIAL_ATTRIBUTE = "citry_partial"


def is_partial(request: Any) -> bool:
    """Whether `request` asks for part of a page rather than a whole one.

    htmx sends `HX-Request: true` with every request it makes, including a
    boosted link, whose answer it swaps into the page's `<body>`. A view that
    returns part of a page to a client of its own, or as JSON, sets
    `request.citry_partial = True`. A render without a request is a page.
    """
    if request is None:
        return False
    if getattr(request, PARTIAL_ATTRIBUTE, False) is True:
        return True
    headers = getattr(request, "headers", None)
    return headers is not None and headers.get("HX-Request") == "true"


class PartialResponseWarning(UserWarning):
    """A response written for a whole page looks like part of one."""
