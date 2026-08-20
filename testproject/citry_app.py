"""
The project's Citry instance and its components.

Every Wagtail tag used below (``{% image %}``, ``{% pageurl %}``,
``{% richtext %}``, ``{% include_block %}``) is resolved by *Django's* engine
through the adapter. The adapter contains no Wagtail-specific code whatsoever:
these work for the same reason they work in an ordinary Django template, which
is that the component's own ``{% load %}`` line travels with the region.
"""

from citry import Citry, Component

from citry_django import CitryDjangoExtension
from citry_django_sekizai import SekizaiAssets

# No configuration is needed for `{{ body|richtext }}` and friends: a `{{ }}`
# is read as a Django filter expression when Django's live filter registry
# actually knows the filter, and stays a Python expression otherwise.
app = Citry(
    extensions=[CitryDjangoExtension(), SekizaiAssets()],
    # Citry's expression sandbox exposes no builtins unless you hand them over.
    template_globals={"len": len},
)


class Hero(Component):
    """Wagtail's `{% image %}` and `{% richtext %}` inside a Citry component."""

    citry = app
    template = """
    {% load wagtailimages_tags wagtailcore_tags %}
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
    `{% pageurl %}` is `takes_context` -- it needs the real request.

    It is also in *attribute* position here, which the adapter handles with a
    delegate node rather than a wrapper element.
    """

    citry = app
    template = """
    {% load wagtailcore_tags %}
    <div class="card">
      <a href="{% pageurl page %}">{{ page.title }}</a>
      <span class="summary">{{ page.summary }}</span>
    </div>
    """


app.register(ArticleCard, "article-card")


class ArticleList(Component):
    """
    The interleaving case, for real.

    A Wagtail/Django `{% if %}` wraps a *Citry* component invocation, inside a
    Citry `<c-for>` loop. Neither engine could do this alone.
    """

    citry = app
    template = """
    {% load wagtailcore_tags %}
    <section class="articles">
      <h2>{{ heading }}</h2>
      <ul>
        <c-for each="page in articles">
          {% if page.featured %}
            <li class="featured-wrap">
              <span class="star">*</span>
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


class RichBody(Component):
    """`{% richtext %}` -- a Wagtail filter-style tag over a StreamField value."""

    citry = app
    template = """
    {% load wagtailcore_tags %}
    <article class="body">{{ body|richtext }}</article>
    """


app.register(RichBody, "rich-body")


class Card(Component):
    """A component with a slot, filled by the body of `<c-card>...</c-card>`."""

    citry = app
    template = """
    <aside class="card"><c-slot/></aside>
    """


app.register(Card, "card")


class StreamBody(Component):
    """
    A StreamField rendered with Wagtail's `{% include_block %}`.

    Each block renders through its own Wagtail template, so this pulls a whole
    second template-loading pass inside a Citry component.
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


class Button(Component):
    """A component with both kinds of asset, declared the way Citry documents."""

    citry = app
    css = ".btn{color:red}"
    js = 'console.log("btn")'
    template = '<button class="btn">{{ label }}</button>'


app.register(Button, "button")


class AssetGroup(Component):
    """Reaches `Button` only through nesting, so its assets travel up a level."""

    citry = app
    css = ".asset-group{border:1px solid}"
    template = '<div class="asset-group"><c-button label="grouped"/></div>'


app.register(AssetGroup, "asset-group")


class Plain(Component):
    """Declares no assets at all, and so should contribute none."""

    citry = app
    template = "<hr>"


app.register(Plain, "plain")
