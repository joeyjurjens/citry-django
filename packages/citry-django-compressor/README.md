# citry-django-compressor

Routes Citry components' CSS and JS through [django-compressor](https://django-compressor.readthedocs.io/), so they are preprocessed, minified and served as compressed files.

## When it applies

It works on responses rendered through citry-django's template backend: your `<head>` lives in a Django template, and Citry renders `<c-*>` regions inside it. citry-django's page collects the regions' assets, and this package bundles them into one file per response. Say where with `<c-css />` and `<c-js />` in your base template.

A component you render straight from Python, such as `str(Page())` or `Page().render()`, has no citry-django page around it, so this package does not see its assets. Render it from a Django template to get them compressed.

## Setup

```bash
pip install citry-django-compressor
```

```python
# myproject/citry_app.py
from citry import Citry
from citry_django import CitryDjangoExtension
from citry_django_compressor import CitryCompressorExtension

app = Citry(extensions=[CitryDjangoExtension(), CitryCompressorExtension()])
```

Components keep declaring assets [the way Citry documents](https://citry.dev/advanced/js-and-css-dependencies/). Nothing else is added to a component.

## What it does

When a page has finished, citry-django hands this extension the page's component tags through its `on_page_assets` hook: once for the CSS and once for the JavaScript. The extension feeds the ones it can read to django-compressor and puts the compressed file where the first of them stood.

It is offered only the tags of components that need no Vue. A component that needs Vue (one with `js`, `js_data()`, `Events` or Vue bindings) is its own Vue app, an *island*, and Citry's browser runtime checks the URL and `integrity` of an island's tags, so its CSS and JavaScript stay exactly as Citry wrote them. Citry's runtime scripts are left alone too.

Of the tags it is offered, it takes:

- a stylesheet link or a script file under `COMPRESS_URL`, unless Citry serves it from its own routes;
- a component's own `<style>`, and a `<style>` whose `type` you declared in `Dependencies`.

It leaves alone a file somewhere else, such as a CDN, and the `<style>` holding one instance's `css_data()` values, so one page's data never ends up in a shared file.

Results come from django-compressor's cache where that is allowed, keyed the way the `{% compress %}` tag keys it, on a digest of the content plus the mtimes of its sources. Without that every render recompiles its SCSS from scratch.

## Citry's dependency strategy

This package works on the tags Citry writes, so `CITRY_DEPS_STRATEGY`, citry-django's setting for what gets serialized, decides what it can reach. Leave it at its default: on `"ignore"` Citry writes no tags, there is nothing to compress, and a page loads without its component styles.

## Settings

Everything is django-compressor's own configuration. There is no separate setting for whether to compress: `COMPRESS_ENABLED` decides, exactly as it does for the template tag.

```python
# settings.py
COMPRESS_ENABLED = True
COMPRESS_PRECOMPILERS = (("text/x-scss", "django_libsass.SassCompiler"),)
STATICFILES_FINDERS = [..., "compressor.finders.CompressorFinder"]
```

A compressor class named in `COMPRESSORS` is used here too, the same one a `{% compress %}` block uses, so a project that names its output files its own way gets that for component assets as well.

There is no setting here at all. What compiles an asset is the asset's own `type`, written the way you would write it in a template:

```python
class Dependencies:
    css = [Style(url=static("theme.scss"), attrs={"type": "text/x-scss"})]
```

django-compressor picks its precompiler on that attribute and nothing else, so a `.scss` that declares no type arrives as source and leaves as source, exactly as a `<link href="x.scss">` without one would inside a `{% compress %}` block. The mimetype is an arbitrary string that has to match your `COMPRESS_PRECOMPILERS` entry exactly.

## Options

| Option | Default | What it does |
| --- | --- | --- |
| `force` | `None` | A callable answering whether this render must bypass the cache. |

`force` exists for output that depends on something the cache key cannot see. Wagtail's preview of unsaved theme settings is the case it was written for: the compiled CSS differs, the content and mtimes do not, so a cached entry would show the wrong thing.

```python
CitryCompressorExtension(force=lambda: getattr(get_current_request(), "is_preview", False))
```

## Limitations

A component that needs Vue keeps its assets as Citry wrote them, so SCSS or another language that needs a precompiler does not work in its `css`. Compile it ahead of time, or move the styles to a component that needs no Vue.

Bundling a whole response needs somewhere to put the result, so a base template that writes no `<c-css />` or `<c-js />` gets one compressed file per `<c-*>` region instead: the assets stay where Citry put them, and putting a bundle somewhere you did not ask for it would be worse than not making one. Repeats are still dropped first, so a stylesheet two regions both asked for is compiled once either way.

## License

MIT
