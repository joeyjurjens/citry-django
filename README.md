# citry-django

citry-django lets you use [Citry](https://github.com/citry-dev/citry)
components in a Django project. Django's template system stays as it is, and
there is no new template dialect to learn.

Any `{% tag %}` you can `{% load %}` works inside a Citry component, including
tags from packages like Wagtail, crispy-forms and django-compressor. Citry
components work in the Django templates you already have. Neither syntax
changes, so you can migrate one `<c-*>` element at a time.

## Contents

- [Requirements](#requirements)
- [Install](#install)
- [Using Django and Citry together](#using-django-and-citry-together)
- [Writing component inputs](#writing-component-inputs)
- [Choosing what components read](#choosing-what-components-read)
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

The test suite runs against the newest Citry, currently 1.1.0.

## Install

Install the package, point Django's template backend at it, and tell it where
your Citry instance lives:

```bash
pip install citry-django
```

```python
# settings.py
CITRY_APP = "myproject.citry_app:app"

TEMPLATES = [
    {
        # Replaces the DjangoTemplates backend.
        "BACKEND": "citry_django.backend.CitryTemplates",
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

That is the whole setup. You do not add anything to `INSTALLED_APPS`; the
backend registers its tag itself.

Your existing templates keep working. A template with no Citry syntax renders
exactly as before, and `{% extends %}`, `{% block %}` and every tag you already
use work as they did. Loaders you configure yourself are kept too, so a package
that ships its own loader still works.

### Optional packages

| Package | What it adds |
|---|---|
| [citry-django-compressor](packages/citry-django-compressor) | Runs each component's CSS and JS through django-compressor: precompiled, minified, and combined into one file per response. |
| [citry-django-djc](packages/citry-django-djc) | Reads Django's template syntax the way django-components does, for a project migrating off django-components. |

```bash
pip install citry-django[compressor]
pip install citry-django[django-components]
```

### Using django-components

If your project uses
[django-components](https://github.com/django-components/django-components),
install the extra and pass its tokenizer to the extension:

```bash
pip install citry-django[django-components]
```

```python
from citry_django import CitryDjangoExtension
from citry_django_djc import tokenize

app = Citry(extensions=[CitryDjangoExtension(tokenizer=tokenize)])
```

django-components compiles templates with its own tokenizer. It reads a `%}`
inside a quoted argument as part of the argument, where Django's lexer ends the
tag there. Passing the tokenizer to the extension makes the extension and
django-components agree on where such a tag ends.

## Using Django and Citry together

Write Django tags in a component's template and `<c-*>` elements in a Django
template, each in its normal syntax. A `<c-*>` element in a Django template,
with its content, is a *region*; Citry compiles the region, and Django
compiles the rest of the template. Each engine's own parser decides which
parts belong to it, and citry-django adds no template syntax of its own.

### Django tags in a component

Write a Django tag in a component's template as you would in a Django
template, with the `{% load %}` it needs:

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

Tags that use `takes_context` need the request. Pass it as a template global:

```python
hero = Hero(title="Hi", image=img, page=page)
hero.render(template_globals={"request": request})
```

A `<c-*>` region in a Django template passes the request down as a render
global, so a tag that needs it gets it at any depth. You pass it yourself only
when you render a component straight from Python.

What else a component can read depends on the `context_behavior` setting. By
default a component reads its inputs and the values your context processors
provide. With `context_behavior="django"` it also reads the host template's
context, as an `{% include %}` does. See
[Choosing what components read](#choosing-what-components-read).

### Components in Django templates

Write Citry's own element syntax. You need no `{% load %}` and no wrapper tag:

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
tags, so you can migrate progressively, one region at a time.

You can write an input in two ways, and they mean different things:

```html
<!-- Django -->
<c-hero title="{{ page.title }}" image="{{ page.hero_image }}" />
<!-- Citry -->
<c-hero c-title="page.title" c-image="page.hero_image" />
```

While migrating, use the first form. It reads like every other attribute in the
template around it. Use the second form, a Python expression, when the value is
more than a lookup:

```html
<c-hero c-title="page.title.upper()" c-count="len(articles)" />
```

A `c-x` expression gives the component its result. A plain attribute does the
same only when the whole value is one `{{ dotted.path }}`: then `image` arrives
as the image, not a rendering of it. See
[Writing component inputs](#writing-component-inputs) for the full rule.

### Citry features in a region

A region is compiled by Citry itself, so every Citry feature works in it:

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

- **`{% load %}` at the top of the file also applies inside regions**, so a tag
  written in a component body needs no second `{% load %}`.
- **Context variables reach the region.** A region inside
  `{% for article in articles %}` can use `article`. (A component's own
  template reads context by a different rule; see
  [Choosing what components read](#choosing-what-components-read).)

### Django blocks around components

A Django block can wrap Citry components:

```html
{% if page.featured %}
  <li class="featured"><c-article-card c-page="page"/></li>
{% else %}
  <li><c-article-card c-page="page"/></li>
{% endif %}
```

Django evaluates the block first and renders only the branch it takes, so:

- **A guard skips what it hides.**
  `{% if user.is_staff %}<c-admin-panel/>{% endif %}` does not render the panel
  for anyone else.
- **Citry can read names that Django binds.**
  `{% with n=5 %}<p>{{ n }}</p>{% endwith %}` works, and a Django `{% for %}`
  can drive Citry components with its loop variable.

Nesting works in either direction: `{% if %}` inside `<c-for>`, `<c-for>`
inside `{% if %}`.

#### Islands in Django blocks

A component that needs Vue (one with `js_data()`, `Events`, Vue bindings or
its own `js`) runs as its own Vue app, called an *island*. When such a
component stands inside a Django block of a component's template, it becomes
an island where it stands:

```html
<ul>
  {% for item in items %}
    <li><c-like-button c-item="item"/></li>
  {% endfor %}
</ul>
```

This gives one island per row, and the `<ul>` and `<li>` stay plain HTML. A
Django `{% for %}` needs no `#c-key`, in a component or in a Django template,
because each iteration's component is the root of its own app. A Citry
`<c-for>` that repeats a component that needs Vue inside one island still needs
`#c-key`.

Put components that work together in one Citry component, so they share an
island. An island can update only the components inside it, so a server event
in one row cannot re-render another row.

A component becomes an island only when no Vue app already holds it.
citry-django therefore waits until the whole `<c-*>` region has rendered (or,
for a component you render straight from Python or that a server event
renders, until that component has rendered), and then decides:

- When nothing else in the region needs Vue, each such component becomes its
  own island, as in the list above.
- When something else in the region needs Vue, the whole region is one Vue
  app, and it holds these components too. The HTML that Django writes around
  them goes into that app as finished blocks; see
  [Django content in Vue components](#django-content-in-islands).
- The same happens when such a component holds content that the component
  around it passes in, between its tags or in a `<c-fill>`. Vue cannot own
  that content from a separate app, so the component cannot be an island of
  its own. If Citry then refuses such a region in a Django template, the
  error names that component.

A page rendered through a Django template loads Citry's browser runtime once,
however many islands it holds; see
[Where a component's assets go](#where-a-components-assets-go). A component you
render straight from Python has no such page, so each island inside it writes
its own copy, and the browser runs it once.

#### Django content in islands

A component that needs Vue can hold what Django renders: a fill written in a
Django template, or a static component whose own template has Django tags.

```html
{% load i18n %}
<c-modal title="Help">
  {% translate "Read the guide first." %}
  {% if user.is_staff %}
    <a href="{% url 'admin:index' %}">Admin</a>
  {% endif %}
</c-modal>
```

Citry puts Django's output into the Vue app as finished blocks of HTML. Vue
inserts each block as it is and never compiles it, so Vue syntax in it,
such as `{{ }}` or `@click` in a visitor's text, stays text. These work inside
the blocks:

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
hold, and the error says what to change:

| Django output inside a component that needs Vue | What to do |
|---|---|
| HTML that is not complete, such as `{{ html\|safe }}` holding an unclosed `<div>` | Make the HTML complete, or keep each Django tag inside the element it opens |
| A component that needs Vue inside an element of HTML that a template with Django tags wrote | Write the element and the Django tag around the component as Citry: `<c-if>` and `<c-for>` for `{% if %}` and `{% for %}` |
| A `<script>` | Move it into the component's `js`, or onto the page outside the component |
| A `<noscript>` | Move it onto the page outside the component |
| HTML inside `<svg>`, `<math>` or a text-only element such as `<textarea>` | Write that markup as Citry, or pass the text in as a value |
| Vue syntax in a template that also has Django tags | Compute the Django value in `template_data()` (`reverse()`, `static()`, `gettext()`), or move the Vue syntax into a component whose template has no Django tags |

To keep Django content on the page after a server event, put it in a
component's template, and render that component inside the one the handler
returns. A server event renders a component again with only what its handler
passes. A fill that the page's Django template wrote is not part of that, so
after a handler returns the modal above, the modal shows its fallback content
instead of the fill. Django tags in a component's own template render again
for the event, with what
[`render_inputs`](#context-for-server-events) gives them.

## Writing component inputs

Use `c-x="..."` for a Python expression, and a plain attribute for Django
syntax. You can write every input either way, so neither form limits what you
can pass.

```html
<c-icon image="{{ product.image }}" />
<c-link href="{% url 'basket:summary' %}" />
<c-badge label="{{ count }} left" />
```

### `c-x` versus plain attributes

What the component receives depends on what the value is:

- A plain attribute whose whole value is one `{{ dotted.path }}` gives the
  component the object itself, so it gets an image or a model, not a rendering
  of one. Django's own `Variable` resolves the path: dictionary key, then
  attribute, then index, calling what it finds unless it is marked
  `alters_data`.
- Any other plain value (a tag, a filter, or text beside the interpolation)
  arrives as a string.

A name that does not exist resolves to the template engine's
`string_if_invalid` (empty by default), as the same path would in a Django
template. Citry normally treats an absent name as an error, but this case
deliberately does not, so that a `{{ }}` path means in a component what it
means in Django.

### Django or Citry interpolation

Both engines write interpolation as `{{ }}`, so citry-django decides each one
separately. There is nothing to configure. citry-django checks the same filter
registry that your `{% load %}` lines fill, so filters from any package work.

| Expression | Goes to | Because |
|---|---|---|
| `{{ x\|date:"Y-m-d" }}` | Django | not valid Python |
| `{{ page.title }}` | Django | a plain dotted path, where Django's lookup does more than Python's |
| `{{ body\|richtext }}` | Django | `richtext` is a filter your `{% load %}` lines registered |
| `{{ ', '.join(names) }}` | Citry | a call |
| `{{ a \| b }}` | Citry | `b` is not a registered filter, so this is a bitwise or |

Inside a quoted attribute value, a `{{ }}` always goes to Django, without any
of those checks. Citry reads such a value as literal text, so if Django did not
resolve it, nobody would, and the braces would reach the page.

## Choosing what components read

Set `context_behavior` to choose what a component's own template can read
besides the inputs you pass it.

### Which `context_behavior` to use

- **Moving existing Django templates over:** use `context_behavior="django"`.
  A component then sees the same variables an `{% include %}` would, so your
  templates keep working.
- **Writing new components:** keep the default, `"isolated"`. A component sees
  only what you pass it (plus `request` and your context processors' values),
  so you can tell what it uses by reading the place that calls it.

Context processors work in both modes.

```python
extension = CitryDjangoExtension(context_behavior="django")
app = Citry(extensions=[extension])
```

Any other value raises `ValueError` when you create the extension. The name
and the values follow [the django-components
setting](https://django-components.github.io/django-components/docs/concepts/advanced/component_context_scope/)
that does the same job.

### What `context_behavior` changes

With `"isolated"`, Citry's own rule, a component takes its inputs and nothing
else, apart from context processor values. What the template around it can
see is not automatically available to it. With `"django"`, Django's rule, a component's own template falls back to
the host's context (the context the surrounding Django template was rendered
with), at any depth of nesting. An `{% include %}` works this way,
and a Django project is usually written expecting it.

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

If the component sets `heading` in its own `template_data`, its own value
wins. The host's context is only a fallback, and citry-django does not copy it
into the component.

### Context processors

Whatever your `context_processors` put in a template's context is available to
every component, at any depth, in both modes, as in Django. That includes
`user`, `LANGUAGE_CODE`, `MEDIA_URL` and anything your own project adds:

```html
<p>Hello {{ user.get_short_name }}</p>
<a href="{{ request.path }}">this page</a>
```

citry-django reads them from the engine's own processor list, not from how the
host happened to be rendered, so a template rendered without `RequestContext`
has them too. It names no processor, so a project's own works the same way as
Django's.

`context_behavior` controls only the *view's* context, which Django passes down
to an included template and Citry does not.

**For extension authors:** in both modes the whole host context is provided
under `"django"`, so an extension can reach host state with
`self.inject("django")`.

### Language and locale

When your Citry app has translations, a region renders in the language Django
activated for the request (`get_language()`), so `tr()` follows
`LocaleMiddleware` and `translation.override()` the way `{% translate %}`
does. A regional variant falls back to its base language: `en-us` uses `en`
when the app lists only `en`. A language the app does not list renders in
the app's default locale, and citry-django logs a warning the first time.
A component a server event renders gets the locale too, once you set
`render_inputs` (see the next section).

### Context for server events

To give a component that a server event renders the `request`, your context
processors' values and the locale, set `render_inputs` as Citry's
`_render_inputs` Events setting. Without it, the component has none of them,
because when a server event's handler returns a component, Citry renders it
again outside any Django template.

```python
from citry_django import CitryDjangoExtension, render_inputs

app = Citry(
    extensions=[CitryDjangoExtension()],
    extensions_defaults={"events": {"_render_inputs": render_inputs}},
)
```

Citry then calls it once for each server event call whose handler returns
a component, after Django's and Citry's CSRF checks, the State check and
the handler. The component gets what a region gets on the page: `request` and
your context processors' values as template globals, those values under
`self.inject("django")`, and Django's active language as its locale.

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

citry-django writes each component's CSS and JavaScript once per page. Mount
[Citry's routes](#mounting-citrys-routes) so the browser can load Citry's
runtime from a URL instead of getting it inline.

### Where a component's assets go

A Django template renders each `<c-*>` region on its own, and each region
that needs Vue is its own Vue app, an *island*. Citry returns a region's asset
tags separately from its HTML, and the region writes them around its HTML:
CSS before it, JavaScript after it. The HTML then works on its own, so you can
store it and render it again later.

The backend opens a *page* around the outermost render. When the render has
finished, the page collects the tags, writes each one once, and, if you named a
place for them, moves them there:

```html
<head>
  <c-css />
</head>
<body>
  {% block content %}{% endblock %}
  <c-js />
</body>
```

A `<c-css />` or `<c-js />` sets where the tags go when it stands in the
Django template itself, outside any component. Without one, the tags stay
beside the region that wrote them, still written once.
`CITRY_COLLECT_PAGE_ASSETS = False` turns the whole thing off.

The page sorts the tags into three groups:

- Citry's browser runtime and its preload hints, written once per page;
- component CSS and JavaScript, written once per page;
- each island's own stylesheet, configuration block and start script. Every
  configuration block and start script is kept, because each names its own
  island. With [Citry's routes](#mounting-citrys-routes) mounted, the stylesheet
  is a link, and islands that load the same file share one link that names
  all of them. Without the routes it is an inline `<style>`, and islands
  with the same styles share one that names all of them.

At the `<c-css />` or `<c-js />` position, the runtime tags come first, then
the component tags, then the island tags.

Islands that translate in the browser work the same way: each island
carries its own messages in its configuration block, and the i18n runtime
they share is written once.

Each comment a region writes around its tags carries a signature (an
HMAC-SHA256) of those tags,
keyed from your `SECRET_KEY` (with `SECRET_KEY_FALLBACKS` accepted, as
Django accepts them for its own signed values). The page moves only tags
whose comment matches and leaves anything else that looks like one where it
is. A `<c-css />` or `<c-js />` is signed for the page that wrote it, so one
inside `{% cache %}` does not collect on a later page; the tags then stay
beside their regions. Keep `<c-css />` and `<c-js />` outside cached blocks.

A region's HTML does not depend on the page that produced it, because nothing
in the markup refers back to it. So `{% cache %}` around a region that needs no
Vue works. So does a rendered fragment you stored and send back later, and a
base template you kept in a dict.

Do not cache a region that holds an island. Its State tokens expire, its
CSP nonce belongs to an earlier response, and a cached copy does not make
Django send the CSRF cookie that the island's server events need.

The page collects nothing under `CITRY_DEPS_STRATEGY = "fragment"`: each
region keeps the tags Citry places for it.

### Partial responses and htmx

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

#### Using fragments

- Mount [Citry's routes](#mounting-citrys-routes). A fragment loads the runtime
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
- Under a nonce-based Content Security Policy, a partial's islands must carry
  the nonce of the page they land in, not the nonce of the partial's own
  response. citry-django looks for that nonce in this order:

    1. The `X-Citry-Page-Nonce` header, read with Citry's
       `page_nonce_from_headers()`, so each tab gets its own. A page that
       holds an island and has a nonce writes the htmx snippet from Citry's
       docs ([Nonces in fragments](https://citry.dev/security/#html-fragments)),
       which sends `Citry.pageNonce()` in this header with each request to
       the page's own origin. A request that is not htmx's can send the header
       itself.
    2. The nonce citry-django keeps in the session, if the app asked for that
       (see [CSP nonce in server event HTML](#csp-nonce-in-server-event-html)).
    3. The nonce of the partial's own response. The browser then refuses to
       start the island.

  A page without an island writes no snippet, so the first partial it loads
  gets no header.

  The snippet checks the URL against both the page's address and its base URL,
  so a `<base>` tag cannot send the nonce to another site. A `base-uri 'none'`
  or `'self'` directive in your policy helps too. A URL on your site that
  redirects to an address taken from the request passes the header on to
  another site. Django's own redirect helpers check the host
  (`url_has_allowed_host_and_scheme`), so use them. To keep the header to the
  URLs that answer with fragments, set
  [`CITRY_PAGE_NONCE_PATHS`](#citry_page_nonce_paths).
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
- Put an island on every page that swaps in fragments, so the page loads the
  runtime and its plugins. On Citry 1.1.0, a fragment's loader adds Citry's
  runtime but not the browser code of Citry's extensions. If the app
  configures `i18n` and the page has no island of its own, the first fragment
  is discarded, and the browser console shows `missing or incompatible Citry
  browser plugin: i18n`. Citry tracks this in
  [citry#810](https://github.com/citry-dev/citry/issues/810).
- A component without Vue in a partial gets its `<link>`, `<style>` and
  `<script>` tags in the partial itself, each written once.
- With `DEBUG` on, a response written for a whole page that holds an island
  but has no `<body>`, `<html>` or doctype issues `PartialResponseWarning`.
  It is usually a partial that citry-django could not recognise, such as
  one fetched without `HX-Request`.

### Declaring assets

Declare a component's own stylesheet and script with `css` / `css_file` /
`js` / `js_file`. Declare a library or file that the component only depends on
with `Dependencies`. The two are not interchangeable:

| | `css` / `css_file` / `js` / `js_file` | `Dependencies` |
|---|---|---|
| What it is for | The component's own stylesheet and behaviour | A charting library, a shared theme, a third-party script |
| How it arrives | Citry reads the file and hands over its contents | A URL the browser fetches |
| Where the file may live | Anywhere Citry's `dirs` reach, so beside the component | Anywhere staticfiles reaches |
| `css_data()` / `js_data()` | Feeds them | Does nothing |
| `$component(...)` | Registered, and the client runtime is shipped | Not registered |
| Read from disk | Once per class, then cached | Never: the browser fetches it |

#### A component's own files

```python
class Slider(Component):
    css_file = "slider/slider.scss"
    js_file = "slider/slider.js"

    def css_data(self, kwargs, slots):
        return {"accent": kwargs.accent}

    def js_data(self, kwargs, slots):
        return {"slides": len(kwargs.images)}
```

Citry reads both files, resolved against its `dirs`, and passes the contents
to the render, so `styles()` and staticfiles are not involved. You also get
three things: `css_data()` becomes custom properties scoped to this
instance's elements, `js_data()` values become members of the `component`
object that the `$component(({ component }) => ...)` callback receives, and
Citry ships the client runtime because it can see that the component asked
for one.

The contents arrive as a dependency like any other, so
[citry-django-compressor](#one-file-per-response) compiles and combines
them into one file. Without it they are written inline into every page, which
also means a `.scss` reaches the browser uncompiled.

#### Files a component depends on

```python
from citry_django import scripts, styles


class Slider(Component):
    class Dependencies:
        css = styles(["vendor/swiper.css"])
        js = scripts(["vendor/swiper.js"])
```

`styles()` and `scripts()` turn the static paths your project already uses
into the form Citry expects. Both accept a path or a list of paths, and take
extra HTML attributes as keywords, so you can keep paths in constants and set
the tag's attributes where you use them:

```python
css = styles(Css.CARD, Css.GRID, media="screen")
```

`media` is the HTML attribute: it lands on the `<link>` as `media="screen"`, so
the browser skips that stylesheet when printing. Anything else you pass is
written out the same way.

The output is a `<script src>` or a `<link href>`, the same as writing one
in a template by hand. There is no registration and no per-render data, and
the browser caches the file by itself.

Both functions live in `citry_django` and do not depend on compression.
Without the compressor extension they produce plain static URLs.

### Where asset files live

Put the files beside the component, for either kind of declaration:

```
components/slider/slider.py
components/slider/slider.scss
components/slider/slider.js
```

For `css_file` and `js_file` that is all it takes: Citry resolves the path
against its own `dirs` and reads the file itself, so staticfiles never sees
it.

A `Dependencies` entry is a URL, so Django has to find the file as well. Add
`ComponentFinder`, which serves those same `dirs` to staticfiles:

```python
# settings.py
STATICFILES_FINDERS = [
    "django.contrib.staticfiles.finders.FileSystemFinder",
    "django.contrib.staticfiles.finders.AppDirectoriesFinder",
    # Before CompressorFinder, so a component's own file wins over a
    # copy an earlier `collectstatic` left behind.
    "citry_django.finders.ComponentFinder",
    "compressor.finders.CompressorFinder",
]
```

Citry and Django use one list of directories, so they cannot disagree: what
Citry resolves is what Django finds, what `collectstatic` collects, and what
django-compressor reads. The compressor package knows nothing about
components; it reads a static file like any other.

`ComponentFinder` serves only assets from those directories. A component's
`.py` and `.html` files are not static files, though they sit beside ones
that are. `ComponentFinder.served` is the set of served suffixes, and
`is_served()` is the rule that uses it; subclass to change either.

An ordinary `myapp/static/card/card.css` keeps working with no finder
involved. `styles()` calls Django's own `static()` either way, so the
URL follows `STATIC_URL` and whatever storage you configured. In production
`collectstatic` gathers both, and django-compressor reads from `COMPRESS_ROOT`
(your `STATIC_ROOT` unless you say otherwise) and writes its output under
`CACHE/`, which `compressor.finders.CompressorFinder` then serves and collects.

This covers only the assets Citry collects. Citry cannot see CSS that a Django
template asks for itself; keep using a `{% compress %}` block around it.

### Compiling assets

A `.scss`, `.less` or `.coffee` file has to be compiled before a browser can
read it. django-compressor does that, and it picks the precompiler by the
asset's `type` alone. Map each suffix your project compiles to a type, once:

```python
# settings.py
COMPRESS_PRECOMPILERS = (
    ("text/x-scss", "django_libsass.SassCompiler"),
)
CITRY_COMPRESSOR_FILE_TYPES = {".scss": "text/x-scss"}
```

Now one call can name both kinds of file, and each gets the right treatment:

```python
css = styles(["card/card.css", "card/card.scss"])
```

The mimetype is an arbitrary string that must match your
`COMPRESS_PRECOMPILERS` entry exactly. citry-django does not guess a mapping: without
the mapping, a `.scss` file arrives as source and leaves as source. An asset
that names its own `type` always wins.

A `css_file` uses the same mapping. It has no URL to read a suffix from,
because it arrives as contents, so the extension asks the component which file
it declared.

#### Using `css_data()` with Sass

Sass and `css_data()` run at different times, so they do not interfere:

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

Sass runs on the server and resolves the nesting. The browser resolves a
custom property, so `var(--accent)` passes through the precompiler untouched.
The result is one compiled file for the rules and a small `<style>` for each
distinct set of values.

Sass cannot read a `css_data()` value while it compiles.
`darken(var(--accent), 10%)` has nothing to darken, because that value does
not exist at compile time. A custom property can stand only where a CSS value
can, so it cannot pick a selector, drive a `@media` query, or feed an
`@each`.

`css_data()` values are strings, finite numbers, or `None`. A dict or a list
is refused. To hand over what you would put in a Sass map, pass several
properties instead, or move the data to `js_data()`, which takes arbitrary
JSON.

Anything that shapes the CSS itself, rather than filling in a value, belongs
in the stylesheet or in a Sass function, where it is compiled once into the
shared file.

### One file per response

With [citry-django-compressor] installed, the page combines a response's
assets into one compressed file, placed where `<c-css />` and `<c-js />`
stand:

```python
from citry_django_compressor import CitryCompressorExtension

app = Citry(
    extensions=[CitryDjangoExtension(), CitryCompressorExtension()],
)
```

Without a `<c-css />` or `<c-js />`, each region gets a file of its own,
because a combined file needs a place to go and citry-django does not choose
one for you. Either way the page drops repeats first, so a stylesheet that two
regions both asked for is compiled once.

**For extension authors:** any extension can combine assets the same way. The
page emits `on_page_assets` with the response's component tags, once for the
CSS and once for the JavaScript, and what it returns is what gets placed.
Without a `<c-css />` or `<c-js />` it emits the hook once per region
instead, with `collected=False`. Beside the tags it passes
`entries`: for each tag Citry described, a `SerializedAssetEntry` naming the
components that declared it, and `instance=True` when it may hold one
render's data, such as `css_data()` values. Bundle only tags whose entry says
`instance=False`. The runtime and island tags never reach the hook: Citry's
browser runtime checks their URLs and `integrity` attributes, so a bundle of
them would break the islands.

[citry-django-compressor]: packages/citry-django-compressor

### Mounting Citry's routes

Mount Citry's routes so the browser loads Citry's client runtime from a URL.
Without them, Citry has no URL to put in a `src`, so it inlines the whole
runtime bundle into every page, on every request:

```python
# urls.py
from citry_django.urls import urlpatterns as citry_urls

urlpatterns = [*citry_urls(app, "/citry"), ...]
```

Put it where URL paths start at the site root, normally the root URLconf.
The routes already sit under the prefix you pass, and Citry points every `src`
at that prefix. Inside `path("citry/", include(...))` the prefix is added
twice and every file answers 404. If you wrapped the call that way for
citry-django 0.3, drop the wrapper when you upgrade to 0.4.

This call wraps Citry's own Django routes and gzips each file for a client
that asks. A web server cannot do that for these files, because they come from
a view, so an nginx rule naming a static directory never reaches them. Only
the routes that serve files are gzipped. Citry's event endpoints sit beside
them and answer each request separately, so the mount leaves them alone.

Citry decides how long a browser keeps each file, and the mount passes
Citry's `Cache-Control` and `ETag` through. Citry names the runtime and
the JavaScript that defines each Vue island by a hash of their content, such as
`/citry/citry.173bbfea….js`, and marks them `immutable`. A file whose content
can change at the same name, such as `cache/<class_id>.js`, gets `no-cache`
and an `ETag`, so after a deploy the browser asks again and gets the new
component JS. A gzipped file's `ETag` is marked weak (`W/"…"`), because the
compressed body is a different body with the same content.

## Settings

Only `CITRY_APP` is required. The others have working defaults; set them to
change the behavior.

| Setting | Default |
|---|---|
| [`CITRY_APP`](#citry_app) | *required* |
| [`CITRY_DEPS_STRATEGY`](#citry_deps_strategy) | `"document"` |
| [`CITRY_COLLECT_PAGE_ASSETS`](#citry_collect_page_assets) | `True` |
| [`CITRY_COMPRESSOR_FILE_TYPES`](#citry_compressor_file_types) | `{}` |
| [`CITRY_PAGE_NONCE_PATHS`](#citry_page_nonce_paths) | `None` |

#### `CITRY_APP`

Dotted path to your `Citry` instance, with an optional `:attr` suffix:

```python
CITRY_APP = "myproject.citry_app:app"
```

It may also name a callable, which lets a project pick between engines at
render time. citry-django resolves it once and caches the result.

#### `CITRY_DEPS_STRATEGY`

Controls what a `<c-*>` region writes out. The values are Citry's own names:

| | |
|---|---|
| `"document"` | The asset tags and the client runtime. Use this for a page. |
| `"simple"` | The tags alone. Use this for an email or a static page, where per-instance JS would have nothing to run against. |
| `"ignore"` | Nothing. Use this only when something downstream collects the assets; otherwise the page loads unstyled. |

Under `"document"`, an island in a [partial
response](#partial-responses-and-htmx) is written as a
fragment. `"fragment"` writes every region that way.

`"simple"` and `"ignore"` suit static pages only. A component that needs Vue
(one with `js_data()`, `Events`, Vue bindings or its own `js`) does nothing in
the browser without its scripts, so a region holding one raises
`IslandStrategyError` under either value.

#### `CITRY_COLLECT_PAGE_ASSETS`

Whether a response writes each asset once. When off, every region writes
everything it asked for beside itself, which means the browser runtime once
per island.

Turn it off to rule out the page as a cause while debugging, or if something
else in your project does the collecting.

#### `CITRY_MINIFY_ASSETS`

Delete this setting; citry-django 0.4.0 removed it. Citry pins each file it
serves with an `integrity` hash of its bytes, so a browser refuses a minified
copy. With the setting on, loading [the mount](#mounting-citrys-routes) raises
`ImproperlyConfigured`. Set to `False`, it is ignored.

#### `CITRY_COMPRESSOR_FILE_TYPES`

Maps a file suffix to the mimetype your project compiles it under. See
[Compiling assets](#compiling-assets). Only read when citry-django-compressor
is installed.

The compressor extension takes one option of its own, `sort`, which orders the
contents of a bundle. It is on by default, so the same set of components makes
the same file wherever they sit on the page.

#### `CITRY_PAGE_NONCE_PATHS`

The URL path prefixes that htmx sends the page's CSP nonce to, in the
`X-Citry-Page-Nonce` header (see [partial
responses](#partial-responses-and-htmx)). `None`, the
default, sends it to every path on the page's own origin:

```python
CITRY_PAGE_NONCE_PATHS = ["/cards/", "/partials/"]
```

A prefix matches the start of the URL path, so `"/cards/"` covers
`/cards/42`. Each prefix must start with `/`; another value raises
`ImproperlyConfigured` when a page writes the snippet. A partial whose
request does not send the header falls back as described there.

## Limits

### Tags that rewrite output

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

### Caching tags around components

Inside a component's template, a Django tag that caches its body cannot enclose
a component:

```html
{# First render is fine. On a cache hit: RuntimeError #}
{% cache 300 sidebar %}<c-sidebar/>{% endcache %}
```

What the cache stores is a placeholder, because the real markup only exists once
the surrounding block finishes. On a later hit the body never runs, so there is
nothing left to put back.

Cache the component with Citry instead:

```python
class Sidebar(Component):
    citry = app

    class Cache:
        ttl = 300
```

A `<c-*>` region in a *Django* template is unaffected, since it renders to
finished HTML before the cache tag sees it.

### Where islands can go

citry-django raises `IslandPlacementError` when a component that needs Vue
stands where the browser would move or drop its `<div>`. Vue mounts each
island on a `<div>` where the component stood. The browser closes a `<p>`
before a `<div>`, moves a `<div>` out of a table unless it sits in a cell,
drops one inside a `<select>`, and leaves SVG or MathML for it. The component
would show up somewhere else, or not at all:

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

### Django blocks across regions

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

The rule is about Django tags and `<c-*>` elements only. A tag and a plain
HTML element may overlap freely:

```html
{# renders exactly as plain Django #}
{% if a %}<div>{% endif %}</div>

{# fine, an element could not go here #}
<div class="{% if a %}on{% endif %}">x</div>
```

### Where to put `{% extends %}`

Use `{% extends %}` in a Django template, and put components inside it. A
component is a fragment, not a page:

```python
class Page(Component):
    citry = app
    template = '{% extends "base.html" %}...'  # not supported
```

The same goes for a component that writes the whole document, with
`<!doctype html>` and `<head>`. Put that skeleton in a Django template,
with `<c-css />` in its `<head>` and `<c-js />` before `</body>`. As a
region, such a component gets its tags written before the doctype when it
needs Vue, where the browser does not read them as part of `<head>`.

### `{% verbatim %}` markers

`{% verbatim %}` keeps both engines out of its body, so `{{ x }}` is emitted
literally. But Citry stamps an identity marker (a `data-cid-...` attribute it uses to
track the component) on the first element a component produces, and a literal
tag written first in the body can catch one:

```html
{% verbatim %}<c-button label="x"/>{% endverbatim %}
```

```html
<c-button label="x" data-cid-cltlb3y4j=""/>
```

To avoid this, put anything before the tag, such as a newline or a comment.

### Filters win over variables

If a filter and a variable have the same name, the filter wins:

```html
{{ a|length }}
```

With `a = [1, 2, 3]` and a variable also called `length`, this renders `3`: the
filter, not a bitwise or. Rename the variable if you meant the operator.

### Literal `<c-*>` text

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

To run `citry format` and `citry check` on templates with Django syntax, pass
your app:

```bash
citry --app myproject.citry_app:app check
```

With the app, the formatter leaves Django's syntax exactly as written and
formats only the Citry parts around it. The checker skips its unresolved-name
check on mixed templates, since a Django `{% for %}` can introduce names Citry
cannot see. `citry check --static` does not load your app, so it cannot recognise
Django syntax at all.

### Django's CSRF settings

Server events work with Django's default CSRF settings. If your project
changes them, pass them to Citry with `csrf_settings()`.

Citry's server events (`Events`) pass Django's own CSRF check: the browser
reads the `csrftoken` cookie and sends it back in the `X-CSRFToken` header.
A page asks Django for the token, as `{% csrf_token %}` does, when Citry's
`needs_csrf_token()` says one of its islands may send it: a component with
server events, or a `<c-i18n client>` provider that loads another locale's
messages. Django then sets the cookie even on a page without a form. A page
whose islands need no token does not ask, so it stays cacheable. With
Django's default settings the token is not written into the page.

To pass your settings to Citry, call `csrf_settings()` when you build the app:

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
403. In that case an island that needs the token writes a small script that
names them (`Citry.configure({csrf: ...})`), and citry-django issues a
`CsrfSettingsWarning` that tells you to use `csrf_settings()`.

One more case writes the script: a partial response without a CSP nonce.
On a page without a nonce, Citry ignores the names in a fragment's block,
because markup injected into the page could have written them, so the
script names them instead. Each of these scripts carries the page's CSP
nonce when there is one, and waits up to five seconds for Citry's
runtime, which a fragment loads later.

### CSP nonce in server event HTML

A nonce is a one-time value that lets a script run under a Content Security
Policy. Citry's own browser runtime needs nothing here to apply a server
event's update to the app already on the page. A client of your own, such as
htmx, that inserts a handler's HTML answer needs the nonce of the page that
sent the call. The event request does not carry it, so use one of the two
routes below.

Under a nonce-based Content Security Policy, a region passes the request's
nonce to Citry, so every island on the page carries it. The nonce is read
from the template context (`csp_nonce` or `CSP_NONCE`), from django-csp's
`request.csp_nonce`, or from Django's own CSP middleware.

When the client sends the nonce in the `X-Citry-Page-Nonce` header, as the
snippet a page with an island writes makes htmx do, Citry reads it itself,
and you need no setting. Citry lists the header in `Vary` on every event answer, and
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

Once you set `_csp_nonce`, Citry asks only that function for the nonce, so
`page_csp_nonce` uses the `X-Citry-Page-Nonce` header when the call sent
one. Otherwise it
gives back the nonce citry-django kept in the session when it rendered a
page that holds a component that needs Vue. Pass the function itself:
citry-django keeps the nonce only when the setting is `page_csp_nonce`. It
needs Django's session middleware, and it saves the session on every such
page view, creating one for a visitor who had none. Once a visitor has a
kept nonce, every whole page they load replaces it, with or without an
island, and saves the session too. The session keeps the nonce of the last
page a visitor loaded, so with several tabs open, a call without the header
from an older tab gets the newer tab's nonce, and the browser refuses to
start the HTML. A [partial response](#partial-responses-and-htmx)
without the header uses the kept nonce in the same way.

### Injection safety

Citry-rendered output is never inserted into Django template *source*, so a
`{%` in user data stays inert. In the same way, Django's output inside a
component that needs Vue reaches the browser as HTML that Vue inserts but
never compiles, so a `{{ }}` or a Vue attribute in user data stays text.

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

```text
packages/citry-django/            the main package
packages/citry-django-compressor/  optional: django-compressor assets
packages/citry-django-djc/         optional: django-components syntax
testproject/                       the Wagtail site the tests use
tests/                             pytest suites
```

Components live in `testproject/citry_app.py` and are built on `citry-ui`. The
project has Wagtail, an asset pipeline, seven third-party tag libraries and
`django-components` switched on at once. Nothing in it is written for the tests;
the libraries are packages people actually install.

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

