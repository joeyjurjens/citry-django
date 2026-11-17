"""Django's syntax around and inside components that run with Vue.

Citry 1.0 turns a region with an interactive component into a Vue app, and its
Vue step accepts template text only in the typed forms Citry's own compiler
writes, or as `Markup`. Everything Django renders reaches it as plain text, so
each case here raised `UnsupportedPreparedView` until that text was marked.
"""

import pytest

VUE_JS = "$component({ data() { return { count: 0 } } })"


def vue_apps(html: str) -> int:
    return html.count('id="citry-vue-')


@pytest.fixture
def interactive(component):
    component('<button @click="count++">{{ label }}</button>', name="vue-button", js=VUE_JS)
    component(
        '<form @submit.prevent="count++">{% csrf_token %}<input name="q"></form>',
        name="vue-form",
        js=VUE_JS,
    )
    component(
        '<ul @click="count++">{% for item in items %}<li>{{ item }}</li>{% endfor %}</ul>',
        name="vue-list",
        js=VUE_JS,
    )
    component(
        '<div @click="count++">{% if items %}<p>has items</p>{% endif %}</div>',
        name="vue-if",
        js=VUE_JS,
    )


@pytest.mark.usefixtures("interactive")
class TestDjangoInsideAnInteractiveComponent:
    def test_csrf_token(self, render_django, rf):
        html = render_django("<c-vue-form />", request=rf.get("/"))
        assert 'name="csrfmiddlewaretoken"' in html
        assert vue_apps(html) == 1

    def test_a_loop(self, render_django):
        html = render_django('<c-vue-list c-items="items" />', items=["a", "b"])
        assert "<li>a</li><li>b</li>" in html
        assert vue_apps(html) == 1

    def test_a_condition(self, render_django):
        html = render_django('<c-vue-if c-items="items" />', items=["a"])
        assert "<p>has items</p>" in html


@pytest.mark.usefixtures("interactive")
class TestDjangoAroundAnInteractiveComponent:
    """Django tags in the host template, around the component tag."""

    @pytest.mark.parametrize(
        "source",
        [
            '{% load static %}<c-vue-button label="x" />',
            '{% with label="x" %}<c-vue-button c-label="label" />{% endwith %}',
            '{% if items %}<c-vue-button label="x" />{% endif %}',
            '{% spaceless %}<c-vue-button label="x" />{% endspaceless %}',
        ],
    )
    def test_a_block_tag(self, render_django, source):
        html = render_django(source, items=["a"])
        assert vue_apps(html) == 1

    def test_a_fragment_cache(self, render_django, settings):
        settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
        source = '{% load cache %}{% cache 300 vue %}<c-vue-button label="x" />{% endcache %}'
        assert vue_apps(render_django(source)) == 1

    def test_a_loop_is_one_app_per_iteration(self, render_django):
        """Django renders each pass of the loop as its own region, so each is
        its own Vue app."""
        source = '{% for item in items %}<c-vue-button c-label="item" />{% endfor %}'
        html = render_django(source, items=["a", "b", "c"])
        assert vue_apps(html) == 3


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Needs Citry: inside an interactive render, the text between a Citry tag and a "
        "Django block must be a complete HTML fragment, so a tag opened outside the block "
        "and closed after it is rejected."
    ),
)
def test_html_that_crosses_a_django_block(component, render_django):
    component(
        '<ul>{% for item in items %}<li><c-vue-button c-label="item" /></li>{% endfor %}</ul>',
        name="static-list-of-buttons",
    )
    component('<button @click="count++">{{ label }}</button>', name="vue-button", js=VUE_JS)
    html = render_django('<c-static-list-of-buttons c-items="items" />', items=["a", "b"])
    assert html.count("<li>") == 2
