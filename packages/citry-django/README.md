# citry-django

Citry and Django's template engines, composed.

```python
from citry import Citry
from citry_django import CitryDjangoExtension

app = Citry(extensions=[CitryDjangoExtension()])
```

```python
# settings.py
TEMPLATES = [{"BACKEND": "citry_django.backend.CitryTemplates", "APP_DIRS": True, ...}]
CITRY_APP = "myproject.app:app"
```

Any `{% tag %}` you can `{% load %}` in Django then works inside a Citry
component, and Citry components work in your existing Django templates. Neither
syntax changes, and the adapter names no tag: each engine's own parser decides
what belongs to it.

See the [repository README](https://github.com/joeyjurjens/citry-django) for the
full picture, the limits, and how it works.

## Optional extras

```bash
pip install citry-django[sekizai]
```

Routes each component's own CSS and JS through [django-sekizai], so an existing
asset pipeline handles them. See `citry-django-sekizai`.

[django-sekizai]: https://github.com/django-cms/django-sekizai
