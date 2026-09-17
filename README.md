# citry-django

Use [Citry](https://github.com/citry-dev/citry) components in a Django project
without giving up Django's template system, and without learning a dialect.

Any `{% tag %}` you can `{% load %}` works inside a Citry component, including
tags from packages like Wagtail, crispy-forms and django-compressor. Citry
components work in the Django templates you already have. Neither syntax
changes, so you can migrate one region at a time.

## Contents

- [Requirements](#requirements)
- [Install](#install)
- [How the two engines meet](#how-the-two-engines-meet)
- [Writing an input](#writing-an-input)
- [What a component can read](#what-a-component-can-read)
- [Assets](#assets)
- [Settings](#settings)
- [Limits](#limits)
- [Development](#development)

## Requirements

| | |
|---|---|
| Python | 3.10 - 3.14 |
| Django | 5.2 LTS, 6.0, 6.1 |
| Citry | 0.5.1 or later |

The suite runs against the newest Citry, currently 0.5.1.

## Install

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

### Optional packages

| Package | What it adds |
|---|---|
| [citry-django-compressor](packages/citry-django-compressor) | Each component's CSS and JS through django-compressor: precompiled, minified, and one file for a whole response. |
| [citry-django-djc](packages/citry-django-djc) | Django's syntax read the way django-components reads it, for a project migrating off it. |

```bash
pip install citry-django[compressor]
pip install citry-django[django-components]
```

### Reading django-components' syntax

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

## How the two engines meet

Neither syntax changes. Each engine's own parser decides what belongs to
it, and this package names no tag of its own.

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

      {% if image %}
        <figure>{% image image width-600 %}</figure>
      {% endif %}

      <a href="{% pageurl page %}">{{ page.title }}</a>
    </header>
    """
```

Pass the request so `takes_context` tags work:

```python
Hero(title="Hi", image=img, page=page).render(template_globals={"request": request})
```

A `<c-*>` region in a Django template does this for you: it hands the request
down as a render global, so a tag needs it at any depth. You only pass it
yourself when you render a component straight from Python.

What else a component sees is
[`context_behavior`](#what-a-component-can-read): isolated, so it takes its
inputs and nothing else, or `"django"`, so the host's context is there to fall
back on the way it is in an `{% include %}`.

### Citry components inside a Django template

Write Citry's own element syntax. No `{% load %}`, no wrapper tag:

```html
{% extends "base.html" %}

{% block content %}
  <c-hero title="{{ page.title }}" image="{{ page.hero_image }}" />

  <c-card>
    <p>Body content becomes the default slot.</p>
  </c-card>
{% endblock %}
```

The surrounding template keeps its inheritance, its blocks and its Wagtail
tags. That is what makes a *progressive* migration possible: replace one region
at a time.

Both ways of writing that input work, and they mean different things:

```html
<c-hero title="{{ page.title }}" image="{{ page.hero_image }}" />   <!-- Django -->
<c-hero c-title="page.title" c-image="page.hero_image" />           <!-- Citry -->
```

The first stays closest to the template around it, reads the same as every
other attribute on the page, and is the one to reach for while migrating. The
second is a Python expression, which is what you want as soon as the value is
more than a lookup:

```html
<c-hero c-title="page.title.upper()" c-count="len(articles)" />
```

Either way a lone `{{ dotted.path }}` hands the component the *object*, not a
rendering of it, so `image` arrives as the image. See
[Writing an input](#writing-an-input) for the whole rule.

### Everything Citry allows works in a region

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
    {# `{{ }}` here is Citry - a Python expression. #}
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

### A Django block can wrap Citry content

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

## Writing an input

### `c-x` is Python, a plain attribute is Django

`c-x="..."` is a Python expression and stays Citry's; Django's syntax belongs in an ordinary attribute. Every input a component takes can be written either way, so there is nothing you can only say with one of them.

```html
<c-icon image="{{ product.image }}" />
<c-link href="{% url 'basket:summary' %}" />
<c-badge label="{{ count }} left" />
```

What the component receives depends on what the value can be. A lone `{{ dotted.path }}` is resolved by Django's own `Variable` - dictionary key, then attribute, then index, calling what it finds unless it is marked `alters_data` - and arrives as **the object**, so a component gets an image or a model rather than a rendering of one. Anything else - a tag, a filter, text beside the interpolation - can only be a string, and arrives as one.

A name that is not there resolves to the engine's `string_if_invalid`, empty by default, which is what the same path would render in a Django template. Citry treats an absent name as an error and this does not, deliberately: the point of writing `{{ }}` is that the path means what it means in Django.

### `{{ ... }}` - both meanings, decided exactly

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

One position decides without asking: inside a quoted attribute value, a `{{ }}`
is always Django's. Citry reads such a value as literal text, so leaving it to
Citry would mean nobody resolved it and the braces reached the page.

## What a component can read

Two rules meet here, and neither is wrong.

Citry's is that a component takes its inputs: what the template around it could see is not automatically its to read. Django's is the opposite - an `{% include %}` sees everything the including template saw - and a Django project is written expecting that. So it is a setting, named after [the django-components one](https://django-components.github.io/django-components/docs/concepts/advanced/component_context_scope/) that does the same job:

```python
app = Citry(extensions=[CitryDjangoExtension(context_behavior="django")])
```

`"isolated"` (the default) keeps Citry's rule. `"django"` lets a component's own template fall back to the host's context:

```python
def article_list(request):
    return render(request, "articles.html", {"heading": "Latest"})
```

```html
<!-- articles.html -->
<c-article-header/>
```

```html
<!-- ArticleHeader's own template, under context_behavior="django" -->
<h1>{{ heading }}</h1>
```

A fallback is all it is: a component that defines `heading` in its own `template_data` uses that one. Nothing is shadowed, and nothing is copied.

### Context processors are ambient in both

Whatever your `context_processors` put in a template's context is there for every component, at any depth, whichever mode you choose - because that is what they are in Django. `user`, `LANGUAGE_CODE`, `MEDIA_URL`, and anything your own project adds:

```html
<p>Hello {{ user.get_short_name }}</p>
<a href="{{ request.path }}">this page</a>
```

They are read from the engine's own processor list rather than inherited from how the host happened to be rendered, so a template rendered without `RequestContext` has them too. Nothing here names a processor, so a project's own arrives on the same footing as Django's.

The setting is about the *view's* context, which is the part Django hands down and Citry does not.

For an extension that has to reach host state whatever the mode, the whole context is provided under `"django"`: `self.inject("django")`.

## Assets

### Where a component's assets go

A Django template renders each `<c-*>` region on its own, and Citry places what
a region collected when that region is serialized. Left alone that gives one
`<style>` beside every component, the client runtime once per region rather
than once per page, and no way to say the tags belong in the head.

So the backend opens a *page* around the outermost render. A region still
places its own assets and keeps them, which is what lets you store its HTML and
render it again later. The page only reads back where they are, drops what it
has placed already, and moves them if you named a spot:

```html
<head>
  <c-css />
</head>
<body>
  {% block content %}{% endblock %}
  <c-js />
</body>
```

Those are Citry's own placeholders. Without them the tags stay where Citry put
them, still deduplicated. `CITRY_COLLECT_PAGE_ASSETS = False` turns the whole
thing off.

Nothing in the markup refers back to the page that produced it, so a region's
HTML stands on its own. `{% cache %}` around one works. So does a rendered
fragment you stored and send back later, and a base template you kept in a
dict, which is the kind of thing an admin does more often than it sounds.

### Declaring what a component needs

A component declares its assets with Citry's `Dependencies` class. `styles()`
and `scripts()` turn the static paths a project already writes into what Citry
wants:

```python
from citry import Component
from citry_django import scripts, styles


class Card(Component):
    class Dependencies:
        css = styles(["card/card.css"])
        js = scripts(["card/card.js"])
```

Both accept a path or a list of them, and take extra attributes as keywords, so
a project can keep its paths in constants and write the tag's own attributes
where it names them:

```python
css = styles(Css.CARD, Css.GRID, media="screen")
```

`media` is the HTML attribute: it lands on the `<link>` as
`media="screen"`, so the browser skips that stylesheet when printing. Anything
else you pass is written out the same way.

They live in `citry_django` and know nothing about compression. Without the
compressor extension they are plain static URLs.

### Where those files live

Nowhere special. A component's stylesheet is an ordinary static file:

```
myapp/static/card/card.css
```

`styles()` calls Django's own `static()`, so the URL follows `STATIC_URL` and
whatever storage you configured. In development the staticfiles finders read it
straight from the app. In production `collectstatic` gathers it like any other
static file, and django-compressor reads from `COMPRESS_ROOT` (your
`STATIC_ROOT` unless you say otherwise) and writes its output under `CACHE/`,
which `compressor.finders.CompressorFinder` then serves and collects.

This covers the assets Citry collects, and only those. A Django template that
asks for its own CSS is not Citry's to see, and a `{% compress %}` block around
it is still the way to say so.

### Compiling what a browser cannot read

A `.scss`, `.less` or `.coffee` has to be compiled first. That is
django-compressor's job, and it picks its precompiler on one thing only: the
asset's `type`. Name the suffixes your project compiles, once:

```python
# settings.py
COMPRESS_PRECOMPILERS = (("text/x-scss", "django_libsass.SassCompiler"),)
CITRY_COMPRESSOR_FILE_TYPES = {".scss": "text/x-scss"}
```

Now a call can name both kinds and each gets what it needs:

```python
css = styles(["card/card.css", "card/card.scss"])
```

The mimetype is an arbitrary string that has to match your
`COMPRESS_PRECOMPILERS` entry exactly, so nothing is assumed: without the
mapping a `.scss` arrives as source and leaves as source. An asset that names
its own `type` always wins.

### One file for a whole response

With [citry-django-compressor] installed, the page is also where a response's
assets become one compressed file, in the spot `<c-css />` and `<c-js />` name:

```python
from citry_django_compressor import CitryCompressorExtension

app = Citry(extensions=[CitryDjangoExtension(), CitryCompressorExtension()])
```

Without a spot to put it, each region keeps the file it made: bundling a whole
response needs somewhere to put the result, and putting it where you did not
ask for it would be worse than not making one.

Any extension can do the same. The page emits `on_page_assets` once per group
with the whole response's tags, and what it returns is what gets placed.

[citry-django-compressor]: packages/citry-django-compressor

### Citry's own routes

Citry serves its client runtime itself. Mount it, or it has nowhere to point a
`src` at and inlines the whole bundle into every page, on every request:

```python
# urls.py
from citry_django.urls import urlpatterns as citry_urls

urlpatterns = [
    *citry_urls(app, "/citry"),
    ...
]
```

That wraps Citry's own Django routes and prepares each response the way a web
server prepares a file, because these are not files a web server serves: they
come from a view, so an nginx rule naming a static directory never reaches
them. Each response gets gzip for a client that asks, an `ETag`, and
`Cache-Control: public, max-age=31536000, immutable`. Only the routes that are
files: Citry mounts its event endpoints beside them, and those answer per
request.

Forever is safe because the mount carries a release segment:

```
/citry/a1b2c3d4/citry.js
```

`Citry.build_url` is the prefix plus the route's path, so a segment in the
prefix is in every URL Citry builds. Citry names its own routes, and
`citry.js` is `citry.js` at every version, so without this a browser told to
keep one forever would keep the wrong one after an upgrade. The segment is
derived from the installed Citry version and from
[`CITRY_MINIFY_ASSETS`](#citry_minify_assets), which are the two things that
change the bytes.

That is also why there is no setting for how long: the URL says which bytes it
serves, so the answer is always forever.

Those files ship unminified and staticfiles cannot see them, so this mount is
the only place able to shrink them.

## Settings

One is required; the rest have a working default and exist for a project that
needs to say otherwise.

| Setting | Default |
|---|---|
| [`CITRY_APP`](#citry_app) | *required* |
| [`CITRY_DEPS_STRATEGY`](#citry_deps_strategy) | `"document"` |
| [`CITRY_COLLECT_PAGE_ASSETS`](#citry_collect_page_assets) | `True` |
| [`CITRY_MINIFY_ASSETS`](#citry_minify_assets) | `False` |
| [`CITRY_COMPRESSOR_FILE_TYPES`](#citry_compressor_file_types) | `{}` |

#### `CITRY_APP`

Dotted path to your `Citry` instance, with an optional `:attr` suffix:

```python
CITRY_APP = "myproject.citry_app:app"
```

It may also name a callable, which is how a project picks between engines at
render time. Resolved once and cached.

#### `CITRY_DEPS_STRATEGY`

What a `<c-*>` region serializes, using Citry's own names:

| | |
|---|---|
| `"document"` | The asset tags and the client runtime. What a page wants. |
| `"simple"` | The tags alone. For an email or a static page, where per-instance JS would have nothing to run against. |
| `"ignore"` | Nothing. Only when something downstream collects the assets; otherwise the page loads unstyled. |

#### `CITRY_COLLECT_PAGE_ASSETS`

Whether one response places each asset once. Off, every region places
everything it asked for, which means the client runtime once per region.

Turn it off to rule the page out while debugging, or if a host of yours
does the collecting.

#### `CITRY_MINIFY_ASSETS`

Whether Citry's own runtime is minified on its way out of
[the mount](#citrys-own-routes). Citry ships it unminified and staticfiles
cannot see it, so this is the only place able to shrink it. Needs
django-compressor, and is off because it costs the minifier's time on every
cold cache. Turning it on changes the release segment, so browsers pick the
new file up on their own.

#### `CITRY_COMPRESSOR_FILE_TYPES`

Suffix to the mimetype your project compiles it under. See
[Compiling what a browser cannot read](#compiling-what-a-browser-cannot-read).
Only read when citry-django-compressor is installed.

That extension takes one option of its own, `sort`, which decides the order
inside a bundle. On by default, so the same set of components is the same file
wherever they sit on the page.

## Limits

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

Put anything before it - a newline, a comment - and it is left alone.

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

