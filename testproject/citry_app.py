"""
The project's Citry instance and its components.

Components are built on `citry_ui`, Citry's own component library, the way a
real site would: the library supplies cards, buttons and badges, and the
components here compose them into the things this site is actually made of.

Every Wagtail tag used below is resolved by *Django's* engine through the
adapter. There is no Wagtail-specific code in the adapter: these work for the
same reason they work in an ordinary Django template, which is that the
component's own `{% load %}` line travels with the region.
"""

import citry_ui
from citry import Citry, Component
from citry.ext.dependencies import Style
from citry_django_djc import tokenize as djc_tokenize
from django.templatetags.static import static

from citry_django import CitryDjangoExtension
from citry_django_compressor import CitryCompressorExtension

# No configuration is needed for `{{ body|richtext }}` and friends: a `{{ }}`
# is read as a Django filter expression when Django's live filter registry
# actually knows the filter, and stays a Python expression otherwise.
app = Citry(
    # django-components compiles templates with its own tokenizer, which is
    # string-aware where Django's lexer is not. Reading the same one keeps both
    # halves of a mixed template agreeing on where a tag ends.
    extensions=[
        CitryDjangoExtension(tokenizer=djc_tokenize),
        CitryCompressorExtension(),
    ],
    # Citry's expression sandbox exposes no builtins unless you hand them over.
    template_globals={"len": len},
)
app.register_library(citry_ui)


class Hero(Component):
    """The masthead of the home page, with the site's own image and intro."""

    citry = app
    template = """
    {% load wagtailimages_tags %}
    <header class="hero">
      <h1>{{ title }}</h1>
      {% if image %}
        <figure>{% image image width-600 alt=title %}</figure>
      {% endif %}
      <div class="intro">{{ intro|safe }}</div>
      <p class="count">{{ len(articles) }} article{{ '' if len(articles) == 1 else 's' }}</p>
    </header>
    """


app.register(Hero, "hero")


class ArticleCard(Component):
    """
    One article in a listing, laid out with the library's card.

    `{% pageurl %}` is `takes_context`, so it needs the real request, and it
    sits in *attribute* position, which the adapter handles with a delegate node
    rather than a wrapper element.
    """

    citry = app
    template = """
    {% load wagtailcore_tags %}
    <c-c-card class_="article-card">
      <c-fill name="header"><a href="{% pageurl page %}">{{ page.title }}</a></c-fill>
      <c-fill name="default"><p class="summary">{{ page.summary }}</p></c-fill>
    </c-c-card>
    """


app.register(ArticleCard, "article-card")


class ArticleList(Component):
    """
    A list of articles, where a featured one is marked with the library's badge.

    A Wagtail `{% if %}` wraps a *Citry* component invocation inside a Citry
    `<c-for>` loop. Neither engine could do this on its own.
    """

    citry = app
    template = """
    <section class="articles">
      <h2>{{ heading }}</h2>
      <ul>
        <c-for each="page in articles">
          {% if page.featured %}
            <li class="featured-wrap">
              <c-c-badge intent="warn">Featured</c-c-badge>
              <c-article-card c-page="page"/>
            </li>
          {% else %}
            <li><c-article-card c-page="page"/></li>
          {% endif %}
        </c-for>
      </ul>
      <c-if cond="not articles">
        <p class="empty">Nothing published yet.</p>
      </c-if>
    </section>
    """


app.register(ArticleList, "article-list")


class Aside(Component):
    """
    A named slot and a default one, filled from a Django template.

    The fallback shows when nothing is given for the named slot.
    """

    citry = app
    template = """
    <aside class="aside">
      <header class="aside-header"><c-slot name="header">Untitled</c-slot></header>
      <c-slot/>
    </aside>
    """


app.register(Aside, "aside")


class StreamBody(Component):
    """
    A StreamField rendered with `{% include_block %}`.

    Each block renders through its own Wagtail template, which pulls a second
    template-loading pass inside a Citry component.
    """

    citry = app
    template = """
    {% load wagtailcore_tags %}
    <div class="stream">
      {% for block in blocks %}
        <div class="block block-{{ block.block_type }}">{% include_block block %}</div>
      {% endfor %}
    </div>
    """


app.register(StreamBody, "stream-body")


# The components below exist for the asset tests. They declare small, exact
# stylesheets so those tests can assert on the content that reaches the page,
# which a real design system's output would make unreadable.


class Swatch(Component):
    citry = app
    css = ".swatch{color:red}"
    js = 'console.log("swatch")'
    template = '<span class="swatch">{{ label }}</span>'


app.register(Swatch, "swatch")


class SwatchGroup(Component):
    """Reaches `Swatch` only through nesting, so its assets travel up a level."""

    citry = app
    css = ".swatch-group{border:1px solid}"
    template = '<div class="swatch-group"><c-swatch label="grouped"/></div>'


app.register(SwatchGroup, "swatch-group")


class Unstyled(Component):
    """Declares no assets at all, and so should contribute none."""

    citry = app
    template = "<hr>"


app.register(Unstyled, "unstyled")


# Components for testing django-compressor integration.
# These use SCSS to verify precompilation works.


class ScssComponent(Component):
    """Uses SCSS syntax to verify precompilation through django-compressor."""

    citry = app
    class Dependencies:
        css = [
            Style(
                content=".scss-test { color: red; &.nested { color: blue; } }",
                attrs={"type": "text/x-scss"},
            ),
        ]
    template = '<div class="scss-test">SCSS works</div>'


app.register(ScssComponent, "scss-component")


class ScssFileComponent(Component):
    """Uses a SCSS file via URL to verify file-based precompilation."""

    citry = app
    class Dependencies:
        css = [
            Style(
                url=static("test.scss"),
                attrs={"type": "text/x-scss"},
            ),
        ]
    template = '<div class="scss-file-test">SCSS file works</div>'


app.register(ScssFileComponent, "scss-file-component")


class ComponentCallbackComponent(Component):
    """Tests that $component() callbacks survive compression."""

    citry = app

    class Kwargs:
        value: str = "default"

    class JsData:
        callback_value: str

    def js_data(self, kwargs: Kwargs, slots) -> JsData:
        return self.JsData(callback_value=kwargs.value)

    js = '$component(({ data }) => { console.log("callback:", data.callback_value); });'

    template = '<div class="callback-test">Callback works</div>'


app.register(ComponentCallbackComponent, "callback-component")


class MixedAssetsComponent(Component):
    """Component with both regular CSS and SCSS to test mixed scenarios."""

    citry = app

    css = ".regular { color: black; }"

    class Dependencies:
        css = [
            Style(
                content=".scss-mixed { &.nested { color: purple; } }",
                attrs={"type": "text/x-scss"},
            ),
        ]

    template = '<div class="mixed-test">Mixed assets</div>'


app.register(MixedAssetsComponent, "mixed-component")


class FileCallbackComponent(Component):
    """Tests file-based JS with $component callback."""

    citry = app

    class Kwargs:
        value: str = "default"

    class JsData:
        file_callback_value: str

    def js_data(self, kwargs: Kwargs, slots) -> JsData:
        return self.JsData(file_callback_value=kwargs.value)

    js_file = "static/file-callback.js"

    template = '<div class="file-callback-test">File callback works</div>'


app.register(FileCallbackComponent, "file-callback-component")
