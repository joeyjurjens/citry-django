from __future__ import annotations

from typing import Any

from citry import Citry, Component

from citry_django import CitryDjangoExtension, page_csp_nonce, render_inputs

#: Where Citry's routes are mounted in `urls.py`.
PREFIX = "/citry"

app = Citry(
    autodiscover=False,
    extensions=[CitryDjangoExtension()],
    secret="events-site-test-secret-" * 2,
    extensions_defaults={
        "events": {"_render_inputs": render_inputs, "_csp_nonce": page_csp_nonce},
        "i18n": {"source_locale": "en", "locales": ["en", "de"]},
    },
)
app.set_mounted_prefix(PREFIX)


class CounterState:
    count: int = 0


class Counter(Component):
    """Counts clicks on the server, and shows what Django gave its render.

    Every `{{ }}` here is Citry's: Django cannot parse `request.path or ""`,
    and a component that needs Vue cannot hold Django syntax.
    """

    citry = app
    State = CounterState

    class Kwargs:
        label: str = "counter"
        count: int = 0

    class Events:
        def bump(self, state: CounterState) -> Any:
            # Returning the component makes Citry render it again, with the
            # inputs `render_inputs` gives.
            state.count += 1
            return Counter(label="bumped", count=state.count)

    def template_data(self, kwargs: Any, slots: Any) -> dict[str, Any]:
        django = self.inject("django")
        return {
            "label": kwargs.label,
            "count": kwargs.count,
            "locale": self.inject("citry_i18n").locale,
            "user": django["user"].is_authenticated,
            "has_messages": "messages" in django,
        }

    template = """
        <div class="counter">
          <button
            type="button"
            class="bump"
            @c-click="bump"
          >{{ label }}: {{ count }}</button>
          <span class="locale">{{ locale }}</span>
          <span class="path">{{ request.path or "" }}</span>
          <span class="user">{{ user }}</span>
          <span class="django">{{ has_messages }}</span>
        </div>
    """


app.register(Counter, "counter")


class Modal(Component):
    """An interactive component whose fill a Django template writes."""

    citry = app

    class Kwargs:
        title: str = ""

    class State(Kwargs):
        pass

    class Events:
        def close(self, state: Any) -> Any:
            return Modal(title="closed")

    def template_data(self, kwargs: Any, slots: Any) -> dict[str, Any]:
        return {"title": kwargs.title}

    template = """
        <div class="modal">
          <h2>{{ title }}</h2>
          <c-slot>fallback</c-slot>
          <button
            type="button"
            class="close"
            @c-click="close"
          >x</button>
        </div>
    """


app.register(Modal, "modal")
