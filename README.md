# citry-django

Use [Citry](https://github.com/citry-dev/citry) components in a Django project
without giving up Django's template system, and without learning a dialect.

Any `{% tag %}` you can `{% load %}` works inside a Citry component, including
tags from packages like Wagtail, crispy-forms and django-compressor. Citry
components work in the Django templates you already have. Neither syntax
changes, so you can migrate one region at a time.

## Requirements

| | |
|---|---|
| Python | 3.10 – 3.14 |
| Django | 5.2 LTS, 6.0, 6.1 |
| Citry | 0.4.3 or later |

Citry 0.4.3 is where the host-template APIs this is built on were released.

## Installation

```bash
pip install citry-django
```

Point Django's template backend at `citry-django` and tell it where your Citry
instance lives:

```python
# settings.py
CITRY_APP = "myproject.citry_app:app"

TEMPLATES = [
    {
        "BACKEND": "citry_django.backend.CitryTemplates",  # was DjangoTemplates
        "DIRS": [...],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": [...]},
    }
]
```

```python
# myproject/citry_app.py
from citry import Citry
from citry_django import CitryDjangoExtension

app = Citry(extensions=[CitryDjangoExtension()])
```

That is the whole setup. There is no app to add to `INSTALLED_APPS`: the backend
registers its tag itself.

Your existing templates are unaffected: one with no Citry syntax in it renders
exactly as before, and `{% extends %}`, `{% block %}` and every tag you already
use keep working. Loaders you configure yourself are kept as well, so a package
that ships one of its own still works.

### Optional: django-components

If your project uses [django-components](https://github.com/django-components/django-components),
install the extra and hand its tokenizer to the extension:

```bash
pip install citry-django[django-components]
```

```python
from citry_django import CitryDjangoExtension
from citry_django_djc import tokenize

app = Citry(extensions=[CitryDjangoExtension(tokenizer=tokenize)])
```

django-components compiles templates with its own tokenizer, which reads a `%}`
inside a quoted argument where Django's lexer ends the tag. Handing the tokenizer
to the extension ensures both halves agree on where that tag ends.

### Optional: django-compressor

citry-django ships optional packages to integrate with popular Django libraries.
For asset preprocessing and minification with [django-compressor](https://django-compressor.readthedocs.io/):

```bash
pip install citry-django[compressor]
```

```python
from citry_django_compressor import CitryCompressorExtension

app = Citry(extensions=[CitryDjangoExtension(), CitryCompressorExtension()])
```

Components can mark assets for precompilation using the `Dependencies` class:

```python
from django.templatetags.static import static
from citry.ext.dependencies import Style


class MyComponent(Component):
    class Dependencies:
        css = [Style(url=static("component.scss"), attrs={"type": "text/x-scss"})]
```

Django-compressor will find the file via staticfiles, precompile it, and output
a compressed URL.

## Getting started

### Django tags inside a Citry component

```python
from citry import Citry, Component
from citry_django import CitryDjangoExtension

app = Citry(extensions=[CitryDjangoExtension()])


class Hero(Component):
    citry = app
    template = """
    {% load wagtailimages_tags wagtailcore_tags %}
    <header>
      <h1>{{ title }}</h1>
      {% if image %}<figure>{% image image width-600 %}</figure>{% endif %}
      <a href="{% pageurl page %}">{{ page.title }}</a>
    </header>
    """
```

Pass the request so `takes_context` tags work:

```python
Hero(title="Hi", image=img, page=page).render(template_globals={"request": request})
```

### Citry components inside a Django template

Write Citry's own element syntax. No `{% load %}`, no wrapper tag:

```html
{% extends "base.html" %}

{% block content %}
  <c-hero c-title="page.title" c-image="page.hero_image"/>

  <c-card>
    <p>Body content becomes the default slot.</p>
  </c-card>
{% endblock %}
```

The surrounding template keeps its inheritance, its blocks and its Wagtail
tags. That is what makes a *progressive* migration possible: replace one region
at a time.

#### Everything Citry allows works in a region

A region is compiled by Citry itself, so nothing is off limits:

```html
{% load wagtailcore_tags %}

<c-hero c-title="page.title.upper()" c-count="len(articles)"/>

<c-if cond="len(articles) > 0">
  <c-article-list c-articles="articles"/>
</c-if>
<c-else>
  <p>Nothing published yet.</p>
</c-else>

<c-panel>
  <c-fill name="head">Title</c-fill>
  <c-fill name="default">
    {# `{{ }}` here is Citry — a Python expression. #}
    <p>{{ ', '.join(tags) }}</p>
    {# ...and a Wagtail tag still works, written normally. #}
    <a href="{% pageurl page %}">Back</a>
  </c-fill>
</c-panel>

<c-component c-is="which_one" label="dynamic"/>
```

Two things worth knowing:

- **`{% load %}` at the top of the file counts inside regions too**, so a tag
  written in a component body needs no second `{% load %}`.
- **Context variables reach the region.** A region inside
  `{% for article in articles %}` can use `article`.

## A Django block can wrap Citry content

```html
{% if page.featured %}
  <li class="featured"><c-article-card c-page="page"/></li>
{% else %}
  <li><c-article-card c-page="page"/></li>
{% endif %}
```

Django evaluates the block and only asks for the branch it takes, so:

- **Guards are lazy.** `{% if user.is_staff %}<c-admin-panel/>{% endif %}` does
  not render the panel for anyone else.
- **Names Django binds are visible to Citry.** `{% with n=5 %}<p>{{ n }}</p>{% endwith %}`
  works, and a Django `{% for %}` can drive Citry components with its loop
  variable.

Nesting works in either direction: `{% if %}` inside `<c-for>`, `<c-for>`
inside `{% if %}`.

## `{{ ... }}` — both meanings, decided exactly

Both engines spell interpolation `{{ }}`, so each one is decided on its own:

| Expression | Goes to | Because |
|---|---|---|
| `{{ x\|date:"Y-m-d" }}` | Django | not valid Python |
| `{{ page.title }}` | Django | a plain dotted path, where Django's lookup does more than Python's |
| `{{ body\|richtext }}` | Django | `richtext` is a filter your `{% load %}` lines registered |
| `{{ ', '.join(names) }}` | Citry | a call |
| `{{ a \| b }}` | Citry | `b` is not a registered filter, so this is a bitwise or |

There is nothing to configure. Filters from any package work, because the rule
asks the same registry your `{% load %}` lines fill.

## Settings

| Setting | Default | What it does |
|---|---|---|
| `CITRY_APP` | *required* | Dotted path to your `Citry` instance, optionally with a `:attr` suffix. |
| `CITRY_DEPS_STRATEGY` | `"document"` | How a `<c-*>` region in a Django template serializes its assets. Set to `"ignore"` when something else collects them. |

## Known incompatibilities and limits

### A Django tag cannot rewrite a component's output

Control flow around a component is fine:

```html
{% if user.is_staff %}<c-admin-panel/>{% endif %}
{% for item in items %}<c-row c-item="item"/>{% endfor %}
{% with total=basket.total %}<c-summary c-total="total"/>{% endwith %}
```

A tag that transforms the *text* its body produced is not:

```html
{# RuntimeError #}
{% filter upper %}<c-widget/>{% endfilter %}
```

You get an error rather than damaged HTML. Django content inside the same tag
behaves normally, so `{% filter upper %}plain text{% endfilter %}` is fine.

### A Django tag that caches its body cannot enclose a component

This applies inside a component template:

```html
{# First render is fine. On a cache hit: RuntimeError #}
{% cache 300 sidebar %}<c-sidebar/>{% endcache %}
```

What the cache stores is a placeholder, because the real markup only exists once
the surrounding block finishes. On a later hit the body never runs, so there is
nothing left to put back.

Let Citry cache the component instead, which is what you wanted anyway:

```python
class Sidebar(Component):
    citry = app

    class Cache:
        ttl = 300
```

A `<c-*>` region in a *Django* template is unaffected either way, since it
renders to finished HTML before the cache tag ever sees it.

### A Django block cannot straddle a region boundary

In a Django template, a block may wrap a region or sit inside one:

```html
{% if x %}<c-card>body</c-card>{% endif %}      {# fine #}
<c-card>{% if x %}body{% endif %}</c-card>      {# fine #}
```

It cannot open outside a region and close inside it:

```html
{# TemplateSyntaxError: Unclosed tag 'if' #}
{% if x %}<c-card>body{% endif %}</c-card>
```

This is not a rule about HTML. A tag and an element may interleave freely:

```html
{% if a %}<div>{% endif %}</div>              {# renders exactly as plain Django #}
<div class="{% if a %}on{% endif %}">x</div>  {# fine, an element could not go here #}
```

### `{% extends %}` belongs in a Django template

A component is a fragment, not a page:

```python
class Page(Component):
    citry = app
    template = '{% extends "base.html" %}...'  # not supported
```

Extend in the Django template and put components inside it.

### `{% verbatim %}` still picks up an identity marker

`{% verbatim %}` keeps both engines out of its body, so `{{ x }}` is emitted
literally. But Citry stamps its marker on the first element a component
produces, and a literal tag written first in the body can catch one:

```html
{% verbatim %}<c-button label="x"/>{% endverbatim %}
```

```html
<c-button label="x" data-cid-cltlb3y4j=""/>
```

Put anything before it — a newline, a comment — and it is left alone.

### A filter wins over a variable of the same name

```html
{{ a|length }}
```

With `a = [1, 2, 3]` and a variable also called `length`, this renders `3`: the
filter, not a bitwise or. Rename the variable if you meant the operator.

### A literal `<c-*>` in a Django template is read as a region

```html
{# ValueError: this looks like a region and does not resolve #}
<p>Write <c-foo> to make one.</p>
```

Escape it, or hand it to `{% verbatim %}`:

```html
<p>Write &lt;c-foo&gt; to make one.</p>
{% verbatim %}<p>Write <c-foo> to make one.</p>{% endverbatim %}
```

Text inside `<script>` and inside attribute values is left alone already, so
`<script>const t = "<c-foo/>";</script>` needs nothing.

### Tooling on mixed templates

`citry format` and `citry check` need your app to see Django syntax in a
template:

```bash
citry --app myproject.citry_app:app check
```

Given that, the formatter leaves Django's syntax exactly as written and formats
only the Citry parts around it, and the checker skips its unresolved-name lint
on mixed templates, since a Django `{% for %}` can introduce names Citry cannot
see. `citry check --static` does not load your app, so it cannot recognise
Django syntax at all.

### Injection safety

Citry-rendered output is never spliced into Django template *source*, so a
`{%` arriving in user data is inert rather than executed.

## Development

The repository is a [uv](https://docs.astral.sh/uv/) workspace holding all three
packages, plus a Wagtail site the whole suite runs against.

```bash
uv sync
uv run pytest                  # everything
uv run pytest tests/test_end_to_end.py -v
uv run tox                     # the Django matrix: 5.2 LTS, 6.0, 6.1
uv run ruff check . && uv run ruff format --check .
```

The demo site, with real content:

```bash
uv run python manage.py migrate
uv run python testproject/seed.py
uv run python manage.py runserver
```

```
packages/citry-django/           the adapter
packages/citry-django-compressor/ optional: assets through django-compressor
packages/citry-django-djc/       optional: alongside django-components
testproject/                     the Wagtail site every test runs against
tests/                           pytest suites
```

Components live in `testproject/citry_app.py` and are built on `citry-ui`. The
project has Wagtail, an asset pipeline, seven third-party tag libraries and
`django-components` switched on at once. Nothing in it is written for the tests:
they are packages people actually install.

### Making a release

All three packages carry the same version and are released together.

1. Bump `version` in each package's `pyproject.toml` under `packages/`.
2. `uv lock` and commit both, e.g. `Release 0.2.0`.
3. Tag and push:

   ```bash
   git tag v0.2.0
   git push origin main --tags
   ```

4. Draft a GitHub release for that tag and publish it.

Publishing the release triggers `.github/workflows/publish.yml`, which builds
every package in the workspace and uploads them to PyPI through trusted
publishing. Nothing
is uploaded from a laptop, and there is no API token to keep anywhere.

To check what would be uploaded before tagging:

```bash
uv build --all-packages
uvx twine check dist/*
```
