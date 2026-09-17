# citry-django-compressor

Routes Citry components' CSS and JS through [django-compressor](https://django-compressor.readthedocs.io/), so they are preprocessed, minified and served as compressed files.

## Which package do I want?

It depends on who owns the page.

**Citry owns the page.** A view renders one component tree and Citry holds the whole page's deduplicated asset list, placing it through [`<c-css />` and `<c-js />`](https://citry.dev/advanced/asset-placement/). This package takes that list and hands it to django-compressor. **Use this package.**

**Django owns the page.** Your `<head>` lives in a Django template and Citry renders `<c-*>` regions inside it, each collecting its own assets. citry-django's page is what brings those together, and this package bundles what it collected into one file per response. Say where with `<c-css />` and `<c-js />` in your base template. **Use this package.**

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

At serialize time the extension takes the render's final, deduplicated asset lists, feeds them to django-compressor as one CSS group and one JS group, and replaces them with the compressed results. Citry's own runtime scripts are left alone: they are not yours to bundle.

Results come from django-compressor's cache where that is allowed, keyed the way the `{% compress %}` tag keys it, on a digest of the content plus the mtimes of its sources. Without that every render recompiles its SCSS from scratch.

## Citry's dependency strategy

This package rewrites what Citry resolves, so `CITRY_DEPS_STRATEGY`, citry-django's setting for what gets serialized, decides what it can reach. Leave it at its default: on `"ignore"` Citry resolves nothing, there is nothing to compress, and a page loads without its component styles.

## Settings

Everything is django-compressor's own configuration. There is no separate setting for whether to compress: `COMPRESS_ENABLED` decides, exactly as it does for the template tag.

```python
# settings.py
COMPRESS_ENABLED = True
COMPRESS_PRECOMPILERS = (("text/x-scss", "django_libsass.SassCompiler"),)
STATICFILES_FINDERS = [..., "compressor.finders.CompressorFinder"]
```

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

Bundling a whole response needs somewhere to put the result, so a base template that writes no `<c-css />` or `<c-js />` keeps one compressed file per `<c-*>` region: the assets stay where Citry put them, and putting a bundle somewhere you did not ask for it would be worse than not making one.

## License

MIT
