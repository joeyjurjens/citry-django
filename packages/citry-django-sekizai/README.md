# citry-django-sekizai

Route a Citry component's own CSS and JS through [django-sekizai], so an
existing asset pipeline handles them.

```bash
pip install citry-django[sekizai]
```

```python
from citry import Citry
from citry_django import CitryDjangoExtension
from citry_django_sekizai import SekizaiAssets

app = Citry(extensions=[CitryDjangoExtension(), SekizaiAssets()])
```

```python
# settings.py
CITRY_DEPS_STRATEGY = "ignore"   # stop Citry emitting the assets itself
```

Your base template collects them like any other Sekizai content:

```html
{% load sekizai_tags %}
<head>{% render_block "css" postprocessor "compressor.contrib.sekizai.compress" %}</head>
```

Components declare assets the way Citry documents — `css`, `js`, `css_file`,
`js_file`. This reads what Citry already resolved; it adds no second way to
declare anything.

[django-sekizai]: https://github.com/django-cms/django-sekizai
