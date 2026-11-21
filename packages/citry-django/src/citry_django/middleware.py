"""Mark responses whose HTML depends on the page nonce a request sent.

A partial's islands carry the CSP nonce of the page they land in, which the
page sends in the `X-Citry-Page-Nonce` header (see `islands.island_csp_nonce`).
A request can put any value there, and the value only reaches the answer to
that same request, unless a shared cache stores the answer and hands it to
someone else. Citry marks its own event answers for that; a partial is
answered by the project's own view, so this middleware marks it:

    MIDDLEWARE = [
        ...,
        "citry_django.middleware.PageNonceMiddleware",
    ]
"""

from __future__ import annotations

from typing import Any

from citry import PAGE_NONCE_HEADER
from django.utils.cache import patch_cache_control, patch_vary_headers
from django.utils.deprecation import MiddlewareMixin

from .islands import PAGE_NONCE_STATE


class PageNonceMiddleware(MiddlewareMixin):
    """Add `Vary: X-Citry-Page-Nonce`, and `no-store` when the header was used.

    Only a response whose Citry output looked for the header is touched. Every
    such answer lists the header in `Vary`, so a cache keeps an answer
    written without a nonce apart from one written with it. One that used
    the nonce from the header also gets `Cache-Control: no-store`, as
    Citry's own event answers do, so no cache keeps it at all.
    """

    def process_response(self, request: Any, response: Any) -> Any:
        state = getattr(request, PAGE_NONCE_STATE, None)
        if state is None:
            return response
        patch_vary_headers(response, [PAGE_NONCE_HEADER])
        if state == "sent":
            patch_cache_control(response, no_store=True)
        return response
