"""The CSP nonce of the page a Citry server event came from.

A server event can answer with HTML that Citry serializes itself, for example
for an htmx swap or a form post to the handler's own URL. Under a
nonce-based Content Security Policy that HTML has to carry the nonce of the
page it lands in, and the event request does not know that page's nonce: it
is a separate request. So citry-django keeps the nonce in the session when it
renders a page that holds an island, and gives it back to Citry through
Citry's `_csp_nonce` Events setting:

    from citry_django import page_csp_nonce

    app = Citry(
        extensions=[CitryDjangoExtension()],
        extensions_defaults={"events": {"_csp_nonce": page_csp_nonce}},
    )

The session keeps the nonce of the last such page each visitor loaded.
"""

from __future__ import annotations

from typing import Any

#: The session key the nonce is kept under.
SESSION_KEY = "citry_django_csp_nonce"


def page_csp_nonce(event_request: Any) -> str | None:
    """The nonce of the last page with an island this visitor loaded.

    Pass it as Citry's `_csp_nonce` Events setting. Returns None when the
    request has no session or the visitor loaded no such page, which Citry
    reads as a page without a nonce.
    """
    session = getattr(event_request.native, "session", None)
    if session is None:
        return None
    nonce = session.get(SESSION_KEY)
    return nonce if isinstance(nonce, str) else None


def remember_page_nonce(app: Any, request: Any, nonce: str | None) -> None:
    """Keep this page's nonce for the server events it will send.

    Only when the app reads it back through `page_csp_nonce`, so a project
    that has not asked for this gets no session write on every page.
    """
    if nonce is None or getattr(request, "session", None) is None:
        return
    events = app.settings.extensions_defaults.get("events", {})
    if events.get("_csp_nonce") is not page_csp_nonce:
        return
    if request.session.get(SESSION_KEY) != nonce:
        request.session[SESSION_KEY] = nonce
