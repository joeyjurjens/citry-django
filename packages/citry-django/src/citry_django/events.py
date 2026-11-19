"""What a component that a Citry server event renders gets from Django.

`render_inputs` gives a component that a server event re-renders what a
region gets on the page: the `request`, Django's context processors, the
`inject("django")` values and Django's active language. Set it as Citry's
`_render_inputs` Events setting:

    from citry_django import page_csp_nonce, render_inputs

    app = Citry(
        extensions=[CitryDjangoExtension()],
        extensions_defaults={
            "events": {
                "_render_inputs": render_inputs,
                "_csp_nonce": page_csp_nonce,
            },
        },
    )

The values describe the server event's request, not the page's: its path is
the event route, and the view's own context does not exist.

`page_csp_nonce` gives back the CSP nonce of the page a server event came
from.

A server event can answer with HTML that Citry serializes itself, which a
client of the app's own, such as htmx, inserts into the page. Under a
nonce-based Content Security Policy that HTML has to carry the nonce of the
page it lands in, and the event request does not know that page's nonce: it
is a separate request. So citry-django keeps the nonce in the session when it
renders a page that holds an island, and gives it back to Citry through
Citry's `_csp_nonce` Events setting, as in the example above.

The session keeps the nonce of the last such page each visitor loaded.
"""

from __future__ import annotations

from typing import Any

from citry.ext.events import EventRequest, RenderInputs

from .context import HOST_PROVIDE
from .engine import context_processors
from .i18n import LOCALE_PROVIDE, locale_context
from .registry import get_citry_app

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


def render_inputs(event_request: EventRequest) -> RenderInputs:
    """The render inputs a region gets on the page, for a server event's render.

    Pass it as Citry's `_render_inputs` Events setting. Citry calls it after
    the event's CSRF and State checks and the handler, and passes the result
    to every component a `Render` action renders for that call.

    Returns:
        `request` and Django's context processors as template globals; the
        same context processor values under `inject("django")`; and, when
        the app has i18n, Django's active language as the render's locale.
    """
    request = event_request.native
    processors = context_processors(request)
    template_globals: dict[str, Any] = dict(processors)
    if request is not None:
        template_globals["request"] = request
    # A region provides the page's whole Django context here. An event has no
    # view, so only what the context processors give is there.
    provides: dict[str, Any] = {HOST_PROVIDE: dict(processors)}
    locale = locale_context(get_citry_app())
    if locale is not None:
        provides[LOCALE_PROVIDE] = locale
    return {"template_globals": template_globals, "provides": provides}
