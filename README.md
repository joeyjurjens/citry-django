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
| Python | 3.11 - 3.14 |
| Django | 5.2 LTS, 6.0, 6.1 |
| Citry | 1.1.0 or later, below 2 |

The suite runs against the newest Citry, currently 1.1.0.

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

#### Components that need Vue inside a Django block

A component that needs Vue (one with `js_data()`, `Events`, Vue bindings or
its own `js`) runs as its own Vue app, an *island*. Inside a Django block of a
component's template, each such component becomes an island where it stands:

```html
<ul>
  {% for item in items %}
    <li><c-like-button c-item="item"/></li>
  {% endfor %}
</ul>
```

gives one island per row, and the `<ul>` and `<li>` stay plain HTML. A Django
`{% for %}` needs no `#c-key`, in a component or in a Django template, because
each iteration's component is the root of its own app. A Citry `<c-for>` that
repeats an interactive component inside one island still needs `#c-key`.

A component becomes an island only when no Vue app holds it already. So
citry-django waits until the whole `<c-*>` region has rendered, or, for a
component you render straight from Python or that a server event renders,
until that component has. Then it decides:

- When nothing else in the region needs Vue, each such component becomes its
  own island, as in the list above.
- When something else in the region needs Vue, the whole region is one Vue
  app, and it holds these components too. The HTML that Django writes around
  them goes into that app as finished blocks; see
  [Django content inside an interactive component](#django-content-inside-an-interactive-component).
- The same happens when such a component holds content that the component
  around it passes in, between its tags or in a `<c-fill>`. Vue cannot own
  that content from a separate app, so the component cannot be an island of
  its own. If Citry then refuses such a region in a Django template, the
  error names that component.

A page rendered through a Django template loads Citry's browser runtime
once however many islands it holds; see
[Where a component's assets go](#where-a-components-assets-go). A
component you render straight from Python has no such page, so each island
inside it writes its own copy, and the browser runs it once. An
island can update only the components inside it: a server
event in one row cannot re-render another row. Put components that work
together in one Citry component, so they share an island.

#### Django content inside an interactive component

An interactive component can hold what Django renders: a fill written in a
Django template, or a static component whose own template has Django tags.

```html
{% load i18n %}
<c-modal title="Help">
  {% translate "Read the guide first." %}
  {% if user.is_staff %}<a href="{% url 'admin:index' %}">Admin</a>{% endif %}
</c-modal>
```

Citry puts Django's output into the Vue app as finished blocks of HTML. Vue
inserts each block as it is and never compiles it, so Vue syntax in it,
such as `{{ }}` or `@click` in a visitor's text, stays text. Inside these
blocks the following work:

- value tags, filters, `{% if %}`, `{% for %}` and `{% with %}`;
- components that need no Vue;
- a component that needs Vue between two complete pieces of Django HTML, or
  inside a Django block, as long as no element that Django writes encloses
  it. It is part of the same app.

A component that needs Vue may also have Django tags in its own template,
such as `{% url %}` in a component with `js_data()`, as long as that
template has no Vue syntax. Citry writes the template as a finished block
too.

citry-django raises `IslandContentError` for Django output that Vue cannot
hold, and says what to change:

| Django output inside an interactive component | What to do |
|---|---|
| HTML that is not complete, such as `{{ html\|safe }}` holding an unclosed `<div>` | Make the HTML complete, or keep each Django tag inside the element it opens |
| A component that needs Vue inside an element of HTML that a template with Django tags wrote | Write the element and the Django tag around the component as Citry: `<c-if>` and `<c-for>` for `{% if %}` and `{% for %}` |
| A `<script>` | Move it into the component's `js`, or onto the page outside the component |
| A `<noscript>` | Move it onto the page outside the component |
| HTML inside `<svg>`, `<math>` or a text-only element such as `<textarea>` | Write that markup as Citry, or pass the text in as a value |
| Vue syntax in a template that also has Django tags | Compute the Django value in `template_data()` (`reverse()`, `static()`, `gettext()`), or move the Vue syntax into a component whose template has no Django tags |

A server event renders a component again with only what its handler
passes. A fill that the page's Django template wrote is not part of that,
so after a handler returns the modal above, the modal shows its fallback
content instead of the fill. Django tags in a component's own template
render again for the event, with what
[`render_inputs`](#what-a-component-a-server-event-renders-can-read) gives
them. So put Django content that must stay after a server event into a
component's template, and render that component inside the one the
handler returns.

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

### The locale is Django's active language

When your Citry app has translations, a region renders in the language
Django activated for the request (`get_language()`), so `tr()` follows
`LocaleMiddleware` and `translation.override()` the way `{% translate %}`
does. A regional variant falls back to its base language: `en-us` uses `en`
when the app lists only `en`. A language the app does not list renders in
the app's default locale, and citry-django logs a warning the first time.
A component a server event renders gets the locale too, once you set
`render_inputs` (see the next section).

### What a component a server event renders can read

When a server event's handler returns a component, Citry renders it again
outside any Django template, so by default it has no `request`, no context
processor values and no locale. Pass `render_inputs` as Citry's
`_render_inputs` Events setting:

```python
from citry_django import CitryDjangoExtension, render_inputs

app = Citry(
    extensions=[CitryDjangoExtension()],
    extensions_defaults={"events": {"_render_inputs": render_inputs}},
)
```

Citry then calls it once for each server event call whose handler returns
a component, after Django's and Citry's CSRF checks, the State check and
the handler. The component gets what a region
gets on the page: `request` and your context processors' values as
template globals, those values under `self.inject("django")`, and Django's
active language as its locale.

The values come from the server event's request, not from the page's:

- `request.path` is the URL of Citry's event route, so a template that
  marks the current page in a menu by its path renders differently.
- The view's own context does not exist, so `self.inject("django")` holds
  only the context processors' values, and `context_behavior="django"` has
  no view context to fall back to. Pass a value the component needs from
  the view in its `Kwargs`, and keep it in its `State`.
- The language comes from the event request: the language cookie or
  `Accept-Language` under `LocaleMiddleware`. The event route has no
  language prefix, so with `i18n_patterns` it can differ from the page's
  language. Keep the page's language in `State` if that matters.

## Assets

### Where a component's assets go

A Django template renders each `<c-*>` region on its own, and each region
that needs Vue is its own Vue app, an *island*. Citry hands a region's asset
tags back apart from its HTML, and the region writes them around its HTML:
CSS before it, JavaScript after it. Its HTML then works on its own, which is
what lets you store it and render it again later.

The backend opens a *page* around the outermost render. When the render has
finished, the page reads the tags back, writes each one once, and moves them
if you named a spot:

```html
<head>
  <c-css />
</head>
<body>
  {% block content %}{% endblock %}
  <c-js />
</body>
```

A `<c-css />` or `<c-js />` names the spot when it stands in the Django
template itself, outside any component. Without one, the tags stay beside the
region that wrote them, still written once.
`CITRY_COLLECT_PAGE_ASSETS = False` turns the whole thing off.

The page sorts the tags into three groups:

- Citry's browser runtime and its preload hints, written once per page;
- component CSS and JavaScript, written once per page;
- each island's own stylesheet, configuration block and start script. Every
  configuration block and start script is kept, because each names its own
  island. With [Citry's routes](#citrys-own-routes) mounted, the stylesheet
  is a link, and islands that load the same file share one link that names
  all of them. Without the routes it is an inline `<style>`, and islands
  with the same styles share one that names all of them.

In a spot, the runtime tags come first, then the component tags, then the
island tags.

Islands that translate in the browser work the same way: each island
carries its own messages in its configuration block, and the i18n runtime
they share is written once.

Each comment a region writes around its tags carries a signature (an
HMAC-SHA256) of those tags,
keyed from your `SECRET_KEY` (with `SECRET_KEY_FALLBACKS` accepted, as
Django accepts them for its own signed values). The page moves only tags
whose comment matches and leaves anything else that looks like one where it
is. A spot is signed for the page that wrote it, so a `<c-css />` inside
`{% cache %}` does not collect on a later page; the tags then stay beside
their regions. Keep the spots outside cached blocks.

Nothing in the markup refers back to the page that produced it, so a region's
HTML stands on its own. `{% cache %}` around a region that needs no Vue
works. So does a rendered fragment you stored and send back later, and a
base template you kept in a dict, which is the kind of thing an admin does
more often than it sounds.

Do not cache a region that holds an island. Its State tokens expire, its
CSP nonce belongs to an earlier response, and a cached copy does not make
Django send the CSRF cookie that the island's server events need.

The page collects nothing under `CITRY_DEPS_STRATEGY = "fragment"`: each
region keeps the tags Citry places for it.

### Partial responses: htmx and template partials

A partial response is HTML that the browser inserts into a page it has
already loaded: an htmx swap, a Django 6 template partial such as
`"cards.html#card"`, or HTML a view returns inside JSON. An island written
for a whole page does not start there. Its start script does not run when
the HTML is inserted, and the page may not have Citry's runtime yet.

So citry-django writes each island in a partial response as a Citry
*fragment*. It treats a response as partial when:

- the request carries `HX-Request: true`, which htmx sends with every
  request, including a boosted link;
- or the view sets `request.citry_partial = True`, for a client of your
  own. A view that sets it to `False` answers a whole page, whatever the
  headers say.

```python
def card(request):
    request.citry_partial = True
    return render(request, "cards.html#card", {"card": card})
```

A fragment holds the island's HTML, a small loader script and a data block.
When the browser inserts it:

1. The loader adds Citry's runtime if the page does not have it yet, and
   does nothing if it does. Two islands inserted before the runtime has
   loaded may each add a runtime tag; the second copy does nothing.
2. The runtime finds the data block and starts the island as its own Vue
   app. Removing the HTML stops the app.
3. The island's server events pass Django's CSRF check and Citry's State
   token check, as every island's do.

htmx runs the loader when it swaps the HTML in. Inserting with `innerHTML`
does not run scripts, so the page must have loaded the runtime already,
for example with an island of its own.

Things to know:

- Mount [Citry's routes](#citrys-own-routes). A fragment loads the runtime
  and the island's files by URL. Without the routes, citry-django writes the
  island for a whole page, as it does for any other response, and with
  `DEBUG` on it issues `PartialResponseWarning`.
- Swap into a plain wrapper with `hx-swap="innerHTML"`. `hx-select`,
  out-of-band swaps, or a swap straight into a `<tbody>` or `<select>` drop
  the data block, and the island shows but does nothing.
- An island in a fragment has no server HTML. It shows once Vue has
  started it.
- When one URL answers both a whole page and a partial, add
  `Vary: HX-Request` to the response (Django's
  `@vary_on_headers("HX-Request")`), so a cache does not hand one out for
  the other.
- Under a nonce-based Content Security Policy, the partial's islands must
  carry the nonce of the page they land in, not the nonce of the partial's
  own response. A page that holds an island and has a nonce writes the
  htmx snippet from Citry's docs ([Nonces in
  fragments](https://citry.dev/security/#html-fragments)), which sends
  `Citry.pageNonce()` in an `X-Citry-Page-Nonce` header with each request to
  the page's own origin. It checks the URL against both the page's address
  and its base URL, so a `<base>` tag cannot send the nonce to another site.
  A `base-uri 'none'` or `'self'` directive in your policy helps too. The partial's islands use that nonce, read with
  Citry's `page_nonce_from_headers()`, so each tab gets its own. A request
  that is not htmx's can send the header itself. Without the header, a
  partial uses the nonce citry-django keeps in the session, if the app
  asked for that (see [HTML a server event sends back needs the page's CSP
  nonce](#html-a-server-event-sends-back-needs-the-pages-csp-nonce)). With
  neither, it carries its own response's nonce, and the browser refuses to
  start it. A page without an island writes no snippet, so the first
  partial it loads gets no header.
- A partial's HTML then depends on a header the request chose, so a shared
  cache must not hand it to anyone else. Add `PageNonceMiddleware`:

  ```python
  MIDDLEWARE = [
      ...,
      "citry_django.middleware.PageNonceMiddleware",
  ]
  ```

  It adds `Vary: X-Citry-Page-Nonce` to each partial whose Citry output
  looked for the header, and `Cache-Control: no-store` when it used it, as
  Citry does for its own event answers. A view under `@cache_page` is
  stored before any middleware sees the response, so do not cache a
  partial view that holds an island, or add
  `@vary_on_headers("X-Citry-Page-Nonce")` inside `@cache_page`.
- If the app configures `i18n` and the page has no island of its own, the
  first fragment is discarded: the loader adds Citry's runtime but not its
  i18n plugin ("missing or incompatible Citry browser plugin: i18n"). Put
  an island on every page that swaps in fragments, so the page loads the
  runtime and its plugins. Citry tracks this in
  [citry#810](https://github.com/citry-dev/citry/issues/810).
- A component without Vue in a partial gets its `<link>`, `<style>` and
  `<script>` tags in the partial itself, each written once.
- With `DEBUG` on, a response written for a whole page that holds an island
  but has no `<body>`, `<html>` or doctype issues `PartialResponseWarning`.
  It is usually a partial that citry-django could not recognise, such as
  one fetched without `HX-Request`.

On Citry 1.1.0, a fragment's loader adds Citry's runtime but not the browser
code of Citry's extensions. With i18n configured, a fragment inserted into a
page that has not loaded that code is discarded, and the browser console
shows `missing or incompatible Citry browser plugin: i18n`. A page with an
island of its own loads it.

### Declaring what a component needs

Two ways, and they are not interchangeable. One is the component's own code;
the other is code it merely depends on.

| | `css` / `css_file` / `js` / `js_file` | `Dependencies` |
|---|---|---|
| What it is for | The component's own stylesheet and behaviour | A charting library, a shared theme, a vendored script |
| How it arrives | Citry reads the file and hands over its contents | A URL the browser fetches |
| Where the file may live | Anywhere Citry's `dirs` reach, so beside the component | Anywhere staticfiles reaches |
| `css_data()` / `js_data()` | Feeds them | Does nothing |
| `$component(...)` | Registered, and the client runtime is shipped | Not registered |
| Read from disk | Once per class, then cached | Never: the browser fetches it |

#### The component's own

```python
class Slider(Component):
    css_file = "slider/slider.scss"
    js_file = "slider/slider.js"

    def css_data(self, kwargs, slots):
        return {"accent": kwargs.accent}

    def js_data(self, kwargs, slots):
        return {"slides": len(kwargs.images)}
```

Citry reads both files against its `dirs` and hands the contents to the
render, so `styles()` and staticfiles are not involved. What you get back is
what makes this worth reaching for: `css_data()` becomes custom properties
scoped to this instance's elements, `js_data()` values become members of the
`component` object that the `$component(({ component }) => ...)` callback
receives, and Citry ships the client runtime because it can see that the
component asked for one.

The contents arrive as a dependency like any other, so
[citry-django-compressor](#one-file-for-a-whole-response) compiles and bundles
them into one file. Without it they are written inline into every page, which
also means a `.scss` reaches the browser uncompiled.

#### Code the component does not own

```python
from citry_django import scripts, styles


class Slider(Component):
    class Dependencies:
        css = styles(["vendor/swiper.css"])
        js = scripts(["vendor/swiper.js"])
```

`styles()` and `scripts()` turn the static paths a project already writes into
what Citry wants. Both accept a path or a list of them, and take extra
attributes as keywords, so a project can keep its paths in constants and write
the tag's own attributes where it names them:

```python
css = styles(Css.CARD, Css.GRID, media="screen")
```

`media` is the HTML attribute: it lands on the `<link>` as `media="screen"`, so
the browser skips that stylesheet when printing. Anything else you pass is
written out the same way.

What comes out is a `<script src>` or a `<link href>`, the same as writing one
in a template by hand. No registration, no per-render data, and the browser
caches it on its own.

They live in `citry_django` and know nothing about compression. Without the
compressor extension they are plain static URLs.

### Where those files live

Beside the component, either way:

```
components/slider/slider.py
components/slider/slider.scss
components/slider/slider.js
```

For `css_file` and `js_file` that is all it takes: Citry resolves the path
against its own `dirs` and reads the file itself, so staticfiles never sees
it.

A `Dependencies` entry is a URL, so Django has to be able to find the file
too. `ComponentFinder` serves those same `dirs` to staticfiles:

```python
# settings.py
STATICFILES_FINDERS = [
    "django.contrib.staticfiles.finders.FileSystemFinder",
    "django.contrib.staticfiles.finders.AppDirectoriesFinder",
    # Before CompressorFinder, so a component's own file wins over a copy an
    # earlier `collectstatic` left behind.
    "citry_django.finders.ComponentFinder",
    "compressor.finders.CompressorFinder",
]
```

One list of directories, so the two cannot drift apart: what Citry resolves is
what Django finds, what `collectstatic` collects, and what django-compressor
reads. Nothing in the compressor package knows about components; it reads a
static file like any other.

Only assets leave those directories. A component's `.py` and its `.html` are
not static files, and a component directory is the one place where they sit
beside ones that are. `ComponentFinder.served` is the set of suffixes, and
`is_served()` the rule it feeds; subclass to change either.

An ordinary `myapp/static/card/card.css` keeps working as it always did, with
no finder involved. `styles()` calls Django's own `static()` either way, so the
URL follows `STATIC_URL` and whatever storage you configured. In production
`collectstatic` gathers both, and django-compressor reads from `COMPRESS_ROOT`
(your `STATIC_ROOT` unless you say otherwise) and writes its output under
`CACHE/`, which `compressor.finders.CompressorFinder` then serves and collects.

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

A `css_file` is covered by the same mapping, though it has no URL to read a
suffix from: it arrives as contents. The component knows what it declared, and
the extension asks it.

#### With `css_data()`

The two happen at different times and do not get in each other's way:

```python
class Badge(Component):
    css_file = "badge/badge.scss"

    def css_data(self, kwargs, slots):
        return {"accent": kwargs.accent}
```

```scss
.badge {
    color: var(--accent);

    &-label { border: 1px solid var(--accent); }
}
```

Sass runs on the server and resolves the nesting; a custom property is
resolved by the browser, so `var(--accent)` passes through the precompiler
untouched. What comes out is one compiled file for the rules and a small
`<style>` per distinct set of values.

What you cannot do is reach a value from `css_data()` while Sass is running.
`darken(var(--accent), 10%)` has nothing to darken: at compile time that value
does not exist yet. The same goes for anything that is not a CSS *value*. A
custom property may stand where a value may stand, so it cannot pick a
selector, drive a `@media` query, or feed an `@each`.

Values are strings, finite numbers, or `None`. A dict or a list is refused,
which is worth knowing if you were hoping to hand over a Sass map: pass
several properties instead, or move it to `js_data()`, which takes arbitrary
JSON.

Anything that shapes the CSS itself, rather than filling in a value, belongs
in the stylesheet or in a Sass function, where it is compiled once into the
shared file.

### One file for a whole response

With [citry-django-compressor] installed, the page is also where a response's
assets become one compressed file, in the spot `<c-css />` and `<c-js />` name:

```python
from citry_django_compressor import CitryCompressorExtension

app = Citry(extensions=[CitryDjangoExtension(), CitryCompressorExtension()])
```

Without a spot to put it, each region gets a file of its own: bundling a whole
response needs somewhere to put the result, and putting it where you did not
ask for it would be worse than not making one. Either way the page drops the
repeats first, so a stylesheet two regions both asked for is compiled once.

Any extension can do the same. The page emits `on_page_assets` with the
response's component tags, once for the CSS and once for the JavaScript, and
what it returns is what gets placed. Without a spot it emits the hook once
per region instead, with `collected=False`. Beside the tags it passes
`entries`: for each tag Citry described, a `SerializedAssetEntry` naming the
components that declared it, and `instance=True` when it may hold one
render's data, such as `css_data()` values. Bundle only tags whose entry says
`instance=False`. The runtime and island tags never reach the hook: Citry's
browser runtime checks their URLs and `integrity` attributes, so a bundle of
them would break the islands.

[citry-django-compressor]: packages/citry-django-compressor

### Citry's own routes

Citry serves its client runtime itself. Mount it, or it has nowhere to point a
`src` at and inlines the whole bundle into every page, on every request:

```python
# urls.py
from citry_django.urls import urlpatterns as citry_urls

urlpatterns = [*citry_urls(app, "/citry"), ...]
```

List it where URL paths start at the site root, normally the root URLconf.
The routes already sit under the prefix you pass, which is also where Citry
points every `src`. Inside `path("citry/", include(...))` the prefix is added
twice and every file answers 404. A project that wrapped the call that way
for citry-django 0.3 drops the wrapper when it upgrades to 0.4.

That wraps Citry's own Django routes and gzips each file for a client that
asks, because these are not files a web server serves: they come from a view,
so an nginx rule naming a static directory never reaches them. It gzips only
the routes that serve files. Citry's event endpoints sit beside them and
answer each request separately, so the mount leaves them alone.

How long a browser keeps each file stays Citry's decision, and the mount
passes Citry's `Cache-Control` and `ETag` through. Citry names the runtime and
the JavaScript that defines each Vue island by a hash of their content, such as
`/citry/citry.173bbfea….js`, and marks them `immutable`. A file whose content
can change at the same name, such as `cache/<class_id>.js`, gets `no-cache`
and an `ETag`, so after a deploy the browser asks again and gets the new
component JS. A gzipped file's `ETag` is marked weak (`W/"…"`), because the
compressed body is a different body with the same content.

## Settings

One is required; the rest have a working default and exist for a project that
needs to say otherwise.

| Setting | Default |
|---|---|
| [`CITRY_APP`](#citry_app) | *required* |
| [`CITRY_DEPS_STRATEGY`](#citry_deps_strategy) | `"document"` |
| [`CITRY_COLLECT_PAGE_ASSETS`](#citry_collect_page_assets) | `True` |
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

Under `"document"`, an island in a [partial
response](#partial-responses-htmx-and-template-partials) is written as a
fragment. `"fragment"` writes every region that way.

`"simple"` and `"ignore"` suit static pages only. A component that needs Vue
(one with `js_data()`, `Events`, Vue bindings or its own `js`) does nothing in
the browser without its scripts, so a region holding one raises
`IslandStrategyError` under either value.

#### `CITRY_COLLECT_PAGE_ASSETS`

Whether one response places each asset once. Off, every region writes
everything it asked for beside itself, which means the browser runtime once
per island.

Turn it off to rule the page out while debugging, or if a host of yours
does the collecting.

#### `CITRY_MINIFY_ASSETS`

Removed in citry-django 0.4.0. Citry pins each file it serves with an
`integrity` hash of its bytes, so a browser refuses a minified copy. With the
setting on, loading [the mount](#citrys-own-routes) raises
`ImproperlyConfigured`; delete the setting. Set to `False` it is ignored.

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

### Where a component that needs Vue may stand

Citry hands a component that needs Vue to Vue as its own app, an *island*,
and Vue mounts it on a `<div>` where the component stood. The browser closes
a `<p>` before a `<div>`, moves a `<div>` out of a table unless it sits in a
cell, drops one inside a `<select>`, and leaves SVG or MathML for it. The
component would show up somewhere else, or not at all, so citry-django raises
`IslandPlacementError` instead:

```html
{# IslandPlacementError: the component needs Vue #}
<p>Hello <c-live-badge/></p>
<table><tr><c-live-cell/></tr></table>
```

Move the enclosing element into the component's own template, or move the
component out of it. A `<li>` in a `<ul>`, a `<td>`, a `<div>` and most other
elements are fine. A component that does not need Vue may stand anywhere.

The check reads the markup of the template the region is written in. A
`<p>` opened inside `{% if %}` counts even when the branch is not taken,
unless another branch opens an element that closes it. The check does not
see an element that an including or parent template opened around an
`{% include %}` or a `{% block %}`, and it does not run for a component you
render directly from Python rather than from a Django template.

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

The same goes for a component that writes the whole document, with
`<!doctype html>` and `<head>`. Put that skeleton in a Django template,
with `<c-css />` in its `<head>` and `<c-js />` before `</body>`. As a
region, such a component gets its tags written before the doctype when it
needs Vue, where the browser does not read them as part of `<head>`.

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

### Server events and Django's CSRF settings

Citry's server events (`Events`) pass Django's own CSRF check: the browser
reads the `csrftoken` cookie and sends it back in the `X-CSRFToken` header.
A page asks Django for the token, as `{% csrf_token %}` does, when Citry's
`needs_csrf_token()` says one of its islands may send it: a component with
server events, or a `<c-i18n client>` provider that loads another locale's
messages. Django then sets the cookie even on a page without a form. A page
whose islands need no token does not ask, so it stays cacheable. With
Django's default settings the token is not written into the page.

When a project changes Django's CSRF settings, give them to Citry when you
build the app, with `csrf_settings()`:

```python
from citry_django import CitryDjangoExtension, csrf_settings

app = Citry(
    extensions=[CitryDjangoExtension()],
    extensions_defaults={"events": {**csrf_settings()}},
)
```

It maps Django's settings to Citry's `_csrf_cookie` and `_csrf_header`
Events settings ([CSRF cookie and
header](https://citry.dev/security/#csrf-names)), which Citry writes into
each island's configuration block for its browser code:

- `CSRF_COOKIE_NAME` becomes `_csrf_cookie`.
- `CSRF_HEADER_NAME`, which Django writes as a `request.META` key such as
  `HTTP_X_MY_CSRF`, becomes the header name `X-MY-CSRF`.
- `CSRF_USE_SESSIONS` or `CSRF_COOKIE_HTTPONLY` makes `_csrf_cookie`
  `None`: no script can read the token from a cookie. Each island that needs
  the token then writes a small script that gives it to Citry
  (`Citry.configure({csrf: {token}})`). It is the same masked token
  `{% csrf_token %}` writes into a form, so a page that Django caches for
  several visitors must not hold it, as with a form.

It returns only what differs from Citry's defaults, so with Django's
defaults it adds nothing. A key you write after the spread wins, such as
`{**csrf_settings(), "_csrf_header": "X-Other"}`, and citry-django does not
check it. When Django's cookie or header name differs from Citry's and the
app does not set it, every server event would fail Django's check with a
403. So an island that needs the token then writes a small script that
names them (`Citry.configure({csrf: ...})`), and citry-django issues a
`CsrfSettingsWarning` that tells you to use `csrf_settings()`.

One more case writes the script: a partial response without a CSP nonce.
On a page without a nonce, Citry ignores the names in a fragment's block,
because markup injected into the page could have written them, so the
script names them instead. Each of these scripts carries the page's CSP
nonce when there is one, and waits up to five seconds for Citry's
runtime, which a fragment loads later.

### HTML a server event sends back needs the page's CSP nonce

Under a nonce-based Content Security Policy, a region passes the request's
nonce to Citry, so every island on the page carries it. The nonce is read
from the template context (`csp_nonce` or `CSP_NONCE`), from django-csp's
`request.csp_nonce`, or from Django's own CSP middleware.

Citry's browser runtime applies a server event's update to the app already
on the page and needs nothing more. A handler whose HTML answer is inserted
into the page by a client of your own, such as htmx, needs the nonce of the
page that sent the call, which the event request does not have. When the
client sends it in the `X-Citry-Page-Nonce` header, as the snippet a page
with an island writes makes htmx do, Citry reads it itself, and you need no
setting. Citry lists the header in `Vary` on every event answer, and
answers a call that sent it with `Cache-Control: no-store`.

For a client that cannot send the header, citry-django can keep each page's
nonce in the session. Pass `page_csp_nonce` as Citry's `_csp_nonce` Events
setting:

```python
from citry_django import CitryDjangoExtension, page_csp_nonce

app = Citry(
    extensions=[CitryDjangoExtension()],
    extensions_defaults={"events": {"_csp_nonce": page_csp_nonce}},
)
```

`page_csp_nonce` uses the `X-Citry-Page-Nonce` header when the call sent
one, because Citry reads only the function once it is set. Otherwise it
gives back the nonce citry-django kept in the session when it rendered a
page that holds a component that needs Vue. Pass the function itself:
citry-django keeps the nonce only when the setting is `page_csp_nonce`. It
needs Django's session middleware, and it saves the session on every such
page view, creating one for a visitor who had none. Once a visitor has a
kept nonce, every whole page they load replaces it, with or without an
island, and saves the session too. The session keeps the nonce of the last
page a visitor loaded, so with several tabs open, a call without the header
from an older tab gets the newer tab's nonce, and the browser refuses to
start the HTML. A [partial response](#partial-responses-htmx-and-template-partials)
without the header uses the kept nonce in the same way.

### Injection safety

Citry-rendered output is never spliced into Django template *source*, so a
`{%` arriving in user data is inert rather than executed. In the same way,
Django's output inside an interactive component reaches the browser as
HTML that Vue inserts but never compiles, so a `{{ }}` or a Vue attribute
arriving in user data stays text.

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

`tests/test_browser.py` loads pages with islands in Chromium, clicks them,
and swaps an island in with htmx. `uv sync` installs Playwright with the other development
tools; run `uv run playwright install chromium` once to download the
browser. Without a browser the tests are skipped.
`PLAYWRIGHT_CHROMIUM_EXECUTABLE` points them at another Chromium build.

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

