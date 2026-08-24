# citry-django-compressor

Route [Citry](https://citry.dev) component assets through [django-compressor](https://django-compressor.readthedocs.io/) for preprocessing and minification.

## Why?

Citry collects each component's CSS and JS and emits them into the page. If your project uses django-compressor for asset preprocessing (SCSS, Less, CoffeeScript, ...) and minification, this extension bridges the two.

## Installation

```bash
pip install citry-django-compressor
```

## Usage

Register the extension with your Citry instance:

```python
from citry import Citry
from citry_django import CitryDjangoExtension
from citry_django_compressor import CitryCompressorExtension

app = Citry(
    extensions=[
        CitryDjangoExtension(),
        CitryCompressorExtension(),
    ]
)
```

### Inline Content with Precompilation

To mark inline content for precompilation, set its `type` attribute to match a `COMPRESS_PRECOMPILERS` entry:

```python
from citry import Component
from citry.ext.dependencies import Style, Script


class MyComponent(Component):
    class Dependencies:
        css = [
            Style(content="...", attrs={"type": "text/x-scss"}),
        ]
        js = [
            Script(content="square = (x) -> x * x", attrs={"type": "text/coffeescript"}),
        ]
```

### File-Based Assets

For file-based assets, use the `Dependencies` class with a URL and `type` attribute. Use Django's `static()` to respect your `STATIC_URL` setting:

```python
from django.templatetags.static import static
from citry import Component
from citry.ext.dependencies import Style


class MyComponent(Component):
    class Dependencies:
        css = [
            Style(url=static("component.scss"), attrs={"type": "text/x-scss"}),
        ]
```

Django-compressor will find the file via staticfiles, precompile it, and output a compressed URL.

### Django Settings

Configure django-compressor as usual:

```python
INSTALLED_APPS = [
    # ...
    "compressor",
]

STATICFILES_FINDERS = [
    # ...
    "compressor.finders.CompressorFinder",
]

COMPRESS_PRECOMPILERS = (
    ("text/x-scss", "django_libsass.SassCompiler"),
    ("text/x-sass", "django_libsass.SassCompiler"),
    ("text/less", "lessc {infile} {outfile}"),
    ("text/coffeescript", "coffee --compile --stdio"),
)
```

### Custom File Type Mapping

By default, the extension maps these file extensions to MIME types:

| Extension | MIME Type |
|-----------|-----------|
| `.scss` | `text/x-scss` |
| `.sass` | `text/x-sass` |
| `.less` | `text/less` |
| `.styl` | `text/stylus` |
| `.coffee` | `text/coffeescript` |

Extend or override with `CITRY_COMPRESSOR_FILE_TYPES`:

```python
CITRY_COMPRESSOR_FILE_TYPES = {
    ".myformat": "text/x-myformat",
}
```

## How It Works

1. Citry collects each component's CSS and JS during rendering
2. Citry deduplicates identical assets (same content or URL)
3. Before emitting, the extension's `on_dependencies` hook fires
4. Assets with precompiler `type` attributes are collected
5. They're fed to django-compressor's programmatic API
6. The original dependencies are replaced with URL-based ones pointing to compressed output

Citry's `$component()` callbacks and `js_data()` work normally - they're just JavaScript content that passes through compression unchanged.

## Limitations

- **`css_file` / `js_file`**: When using Citry's `css_file = "component.scss"`, the file content is inlined and the filename is not preserved. The extension cannot detect the file type automatically. Use the `Dependencies` class with explicit `type` attribute instead.

## License

MIT
