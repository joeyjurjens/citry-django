# citry-django

Django template interop for [Citry](https://github.com/citry-dev/citry): real
Django/Wagtail tags, filters and inheritance inside Citry components, and Citry
components inside existing Django templates.

No per-tag code. The adapter never names a Django tag — it hands regions to
Django's real engine, so anything you can `{% load %}` works.

> **On authorship.** Almost all of the code here was written by an AI (Claude).
> The architecture is mine: which engine owns what, where the boundary sits, and
> which of the approaches below to keep. Read it as a proof of concept whose
> design decisions are deliberate and whose implementation details deserve your
> own review.

## Status

208 tests pass on this machine (Python 3.14t, Django 6.1, Wagtail 7.4.2,
Citry 0.4.3 / citry_core 1.6.0 from PyPI). They all run against one
real Wagtail project in `testproject/`, with Wagtail, an asset pipeline and
six third-party tag libraries switched on at once. No tag library is written for
the tests: they are packages people actually install.

| Suite | What it covers |
|---|---|
| `tests/test_django_in_citry.py` | Django tags, filters and blocks inside Citry components; slots; `{{ }}` ownership |
| `tests/test_citry_in_django.py` | Citry syntax inside Django templates: full Citry semantics, Django untouched |
| `tests/test_transparency.py` | Differential: a transparent Django block changes nothing Citry emits |
| `tests/test_robustness.py` | Adversarial input, and failing where Django itself fails |
| `tests/test_third_party_libs.py` | Real packages: django-compressor, crispy-forms, sorl-thumbnail, django-bootstrap5, widget-tweaks, humanize |
| `tests/test_assets.py` | Citry's own asset handling, and routing it through Sekizai instead |
| `tests/test_wagtail.py` | Wagtail's whole front-end tag surface, plus real pages end to end |
| `tests/test_block_components.py` | A library whose tags inspect their own nodelist rather than its text |

Citry needs two additions for this to work, both generic and neither aware of
Django. They are specified in [`docs/citry-upstream.md`](docs/citry-upstream.md).

## Layout

```
packages/citry-django/           the compatibility layer
packages/citry-django-sekizai/   optional: assets through Sekizai
testproject/                     the Wagtail project every test runs against
tests/                           pytest suites
```

## The model: each engine owns its own files

> **A Citry template is Citry's.** Citry parses it; every `{% ... %}` in it is
> delegated to Django's real engine.
>
> **A Django template is Django's.** Django parses it; every `<c-*>` region in
> it is delegated to Citry's real engine.

Neither side reimplements the other. A Citry region in a Django template is
compiled by *Citry's own parser*, so everything Citry allows works there —
Python expressions in `c-*`, `<c-if>`/`<c-for>`, `<c-slot>`/`<c-fill>`,
`#c-key`, `<c-component c-is="...">`. And a Django tag anywhere is run by
Django, written exactly as you would write it normally, `{% load %}` included.

Delegation is exact rather than heuristic in both directions:

- Citry's grammar has **no `{% %}` construct at all** (control flow is
  `<c-if>`/`<c-for>`, interpolation is `{{ python_expr }}`), so inside a Citry
  template `{% ... %}` is unambiguously Django's.
- Django's lexer knows nothing about `<c-*>`, so inside a Django template those
  regions are unambiguously Citry's.

Django block tags are found by **Django's own parser**, not by pattern matching.
The source is tokenized with `DebugLexer` (exact offsets, correct quoting) and
parsed with Django's real `Parser`; wrapping `Parser.parse(parse_until)` records
which token each block was entered on and which stopped it, so `if / elif /
else / endif` is reconstructed without naming any of them. A third-party block
tag with an unconventional end tag therefore works for free.

### The one asymmetry, and why

`{{ ... }}` means Citry (a Python expression) inside a Citry template and
inside a `<c-*>` region; it still means Django everywhere else in a Django
template. That is deliberate: a Django template is Django's file, so the
`{{ page.title }}` already written in your project has to keep meaning what it
always meant. Adoption must not rewrite what it touches.

## Install

The adapter itself is not published yet. It requires the host-template APIs in
Citry 0.4.3 and Citry Core 1.6.0, described in
[`docs/citry-upstream.md`](docs/citry-upstream.md). This workspace resolves the
released packages from PyPI, and `citry-django` declares `citry>=0.4.3` as its
minimum.

```bash
git clone https://github.com/joeyjurjens/citry-django-poc.git
cd citry-django-poc
uv sync
```

Once the adapter itself is published, installation will be:

```bash
pip install citry-django
pip install citry-django[sekizai]   # optional, assets through Sekizai
```

## Use

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

### Citry inside a Django template

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

Opt in by switching the template backend and pointing at your Citry instance:

```python
CITRY_APP = "myproject.citry_app:app"

TEMPLATES = [{
    "BACKEND": "citry_django.backend.CitryTemplates",   # was DjangoTemplates
    "DIRS": [...],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [...]},
}]
```

This is still Django's own engine — same lexer, same tags, same inheritance.
The backend only rewrites `<c-*>` elements into a tag as the source is loaded,
so templates with no Citry syntax are passed through byte-for-byte. It applies
to every template Django loads, including `base.html` and ones shipped by
third-party apps.

The surrounding template keeps its inheritance, its blocks and its Wagtail
tags. That is what makes a *progressive* migration possible: replace one region
at a time.

#### It is Citry in there, not a dialect

The region is handed to Citry's parser verbatim, so this is all just Citry:

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

Two details that make this work in practice:

- **`{% load %}` travels.** The load lines at the top of the Django template
  are carried into every region cut out of it, so a Wagtail tag written inside
  a component body resolves against them — no second `{% load %}`.
- **Django context reaches Citry.** The context stack is flattened and passed
  in as component inputs, so a region inside `{% for article in articles %}`
  sees `article`. It scopes to the region rather than leaking into every nested
  component.

Django tags *outside* a region were never touched, so `{% extends %}`,
`{% block %}` and the rest keep working exactly as before.

## A Django block can wrap Citry content

```html
{% if page.featured %}
  <li class="featured"><c-article-card c-page="page"/></li>
{% else %}
  <li><c-article-card c-page="page"/></li>
{% endif %}
```

The block is compiled once into a real Django template whose branches hold
markers for the Citry runs, placed by **Django's own parser**. At render time
Django drives: it evaluates the block and asks for only the branch it takes.

Three things follow from that ordering:

- **Guards are lazy.** `{% if user.is_staff %}<c-admin-panel/>{% endif %}` does
  not render the panel for anyone else.
- **Scope is shared.** `{% with n=5 %}<p>{{ n }}</p>{% endwith %}` works, and so
  does a Django-side `{% for %}` driving Citry components with its loop
  variable — the Citry side reads the live Django context.
- **Citry content normally never becomes a string here.** Segments hand Django
  an inert marker and keep their render *parts*, which go straight back into
  Citry's tree. That preserves identity, event/ownership graphs, CSP state, and
  dependency placeholders until Citry serializes the whole tree. A Django tag
  that deliberately HTML-escapes a body is an explicit inert-text boundary;
  other marker transformations fail loudly.

Nesting works in either direction: `{% if %}` inside `<c-for>`, `<c-for>`
inside `{% if %}`.

## `{{ ... }}` — both meanings, decided exactly

Both engines spell interpolation `{{ }}`, so ownership is decided **per
expression at compile time**, from facts rather than a setting:

1. Not a valid Python expression → Django (`{{ x|date:"Y-m-d" }}`).
2. Valid Python *and* shaped like a filter chain — `a|b` where every filter
   position is a bare name Django's **live filter registry** actually knows →
   Django (`{{ body|richtext }}` is Django's precisely because Wagtail
   registered `richtext`).
3. Otherwise → Citry (`{{ ', '.join(names) }}`, and `{{ a | b }}` over two
   values, because `b` is not a registered filter).

There is nothing to configure, and third-party filters work because the rule
consults the registry the template's own `{% load %}` lines populate.

## Assets: Citry's, or your own pipeline

By default Citry serializes each component's declared CSS and JS into the page
itself, and nothing here changes that.

A project that already runs its assets through Sekizai and django-compressor
usually wants them in *its* blocks instead, where they can be bundled and cached
with everything else. Install the optional package and switch Citry's own
injection off:

```bash
pip install citry-django[sekizai]
```

```python
from citry_django_sekizai import SekizaiAssets

app = Citry(extensions=[CitryDjangoExtension(), SekizaiAssets()])
```

```python
# settings.py
CITRY_DEPS_STRATEGY = "ignore"
```

```html
{% load sekizai_tags %}
<head>{% render_block "css" postprocessor "compressor.contrib.sekizai.compress" %}</head>
```

Components keep declaring assets the way Citry documents — `css`, `js`,
`css_file`, `js_file`. The extension reads what Citry already resolved through
`citry.assets`, so there is no second way to declare anything.

The Sekizai holder arrives through `inject("django")`, which the adapter fills
from the host context, so a component nested several levels deep contributes
just as the outermost one does. `tests/test_assets.py` covers both routes.

Separate Citry regions in a Django-owned loop are separate render roots. The
default `document` strategy therefore emits each root's assets; use the Sekizai
integration when the Django page needs cross-region deduplication.

For strict CSP, standalone regions read the nonce from `csp_nonce` or
`CSP_NONCE` in the Django context, then from `request.csp_nonce`.

## Known incompatibilities and limits

**1. A Django tag cannot transform, duplicate, or discard a reached Citry
segment marker.** Control-flow tags such as `{% if %}`, `{% for %}`, and
`{% with %}` preserve the marker and work. A body-transforming construct such
as `{% filter upper %}<c-widget/>{% endfilter %}` changes it, so the adapter
raises `RuntimeError` instead of returning plausible but structurally corrupted
HTML. Pure Django content inside the same tag remains ordinary Django behavior.
`tests/test_serialization_boundaries.py` pins this fail-loud boundary.

**2. A Django block tag cannot straddle a `<c-*>` region boundary in a Django
template.** `{% if x %}` may wrap a whole `<c-card>...</c-card>`, and it may sit
inside one, but it cannot open outside a region and close inside it. Django
rejects that with its own `TemplateSyntaxError`, loudly.

This is *not* a rule about HTML nesting. A Django block and an element may
interleave however they like: `{% if a %}<div>{% endif %}</div>` renders exactly
as plain Django renders it, and a block works inside an attribute value where an
element could never go. Neither engine sees the other's structure, so the two
trees never have to agree.

**3. `{% extends %}` belongs in the Django template, not in a component.** A
component is a fragment, not a page.

**4. `{% verbatim %}` protects its body from both engines**, so `{{ x }}`
inside it is emitted literally. Citry still stamps its identity marker on the
first element of a component's output, so a tag written literally as the very
first thing in a verbatim body can pick one up.

**5. A filter that shares a name with one of your Python variables** is read as
the filter: `{{ a|length }}` means the filter, not `a.__or__(length)`.

**6. Finding regions in Django source is textual.** It skips `{% verbatim %}`
blocks, but a literal `<c-something>` you wanted as *text* elsewhere will be
treated as a region. Wrap it in `{% verbatim %}` to leave it alone. An unclosed
`<c-x>` is left as text rather than guessed at.

### Formatter and checker behavior

Citry's low-level formatter accepts the same `ParseOptions` used by the parser.
When the adapter supplies its foreign spans, the formatter copies those bytes
unchanged and formats only the Citry-owned source around them. It does not try
to format or interpret Django syntax.

`citry --app myproject.citry_app:app check` asks installed extensions for
foreign spans and treats those ranges as unknown. When a Django range may
control its surrounding body, the checker suppresses Citry's unresolved-name
lint for that mixed template because names such as a Django loop
variable are introduced outside Citry's namespace. Other Citry validation
still runs. `citry check --static` deliberately does not import an app or its
extensions, so it cannot recognize Django syntax in a mixed template.

The generic `citry format` command is also app-independent. An editor or Django
adapter that formats mixed templates must call the low-level formatter with
the adapter-produced `ParseOptions`; there is no Django-specific syntax
highlighting, formatting, or hinting in Citry itself.

### Injection safety

Citry-rendered output is never spliced into Django template *source*, so a
`{%` arriving in user data is inert rather than executed. `tests/test_django_in_citry.py`
asserts this.

## Run it yourself

```bash
uv run pytest                      # everything
uv run pytest tests/test_wagtail.py -v

# the demo site, with content
uv run python manage.py migrate
uv run python testproject/seed.py
uv run python manage.py runserver
```

The demo components are in `testproject/citry_app.py`; the Django templates
that embed them are in `testproject/home/templates/home/`.

## What we tried first, and why we moved off it

**A pure-Python adapter, no Citry changes.** Django's structure came from
Django's own lexer and parser, which is fine. The problem is everything after
that: the adapter then had to re-derive *where that structure sat relative to
Citry's own nodes* from the raw source, and splice rendered output back in.
That rediscovery was the largest and by far the most fragile part of the
adapter, and it is where the bugs came from — region boundaries drawn in the
wrong place, `{% comment %}` and `{% verbatim %}` needing hand-written special
cases, and Citry's `data-cid` identity markers quietly disappearing because the
render tree got flattened to a string on the way through.

The failure mode is what makes it a bad trade: every one of those produced
*plausible-looking HTML*. Nothing raised. You find out months later.

**A `<c-foreign>` element.** Rewrite each Django construct into
`<c-foreign open="{% if s %}" close="{% endif %}">…</c-foreign>` and let Citry
parse it as an ordinary unknown component. This needs no parser change at all,
and it works for a surprising amount. It dies on attribute position:

```html
<div class="{% if a %}on{% endif %}">x</div>
```

An element cannot nest inside an attribute value, so that case needs a second
mechanism, and the unity of the design is gone. Splicing also shifts byte
offsets, so diagnostics start pointing at the wrong place.

**Foreign byte spans**, which is what shipped here, have neither problem: a
range is a range wherever it sits, and the masking preserves byte length exactly
so every offset still indexes the original source.

## What Citry has to provide

Two additions, both generic:

**`on_template_foreign_spans(ctx)`** lets an extension return a
`ForeignSpanSet` declaring byte ranges that another engine owns. Citry keeps
them out of its grammar and returns typed, provider-owned claims in tree order,
without learning a single foreign delimiter. A second owner hook must explicitly
resolve every claim before general compiled-template extensions run.

**`Citry.render_template(source, variables, ...)`** renders standalone Citry
source without declaring a public component, which is what a `<c-*>` region
found in a Django template needs. The adapter also uses Citry's public compiled
body handles when Django calls back into already compiled Citry content.

An unresolved claim fails closed during compilation and again at rendering if
an extension bypasses the normal compiler path. Details, including the Rust
side, are in [`docs/citry-upstream.md`](docs/citry-upstream.md).

## How it works

Everything below lives in `packages/citry-django/src/citry_django/`.

- `extension.py` — the Citry extension. Claims Django's byte ranges with
  Django's own `DebugLexer`, and renders a Django-driven block through
  `ForeignNode`, retaining structured Citry renders behind inert markers until
  Django has selected and ordered them.
- `nodes.py` — the Django side: `CitryParser` builds the block's template,
  `CitrySegment` marks where Citry content resumes, and `CitryFragment` renders
  a `<c-*>` region found in a Django template.
- `expressions.py` — decides who owns each `{{ ... }}`, from Django's live
  filter registry.
- `rewrite.py` — locates `<c-*>` regions in Django source using Django's lexer
  to mask its own syntax and Citry's parser to find the elements. No regexes.
- `backend.py` / `loaders.py` — the template backend, mirroring Django's own
  loader shape, and registering the region tag as a Django *builtin* so
  templates the adapter does not own need no `{% load %}`.
- `registry.py` — resolves `settings.CITRY_APP`.
