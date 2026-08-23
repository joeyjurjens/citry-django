# citry-django-djc

Let [citry-django] read Django's syntax the way [django-components] does.

```bash
pip install citry-django[django-components]
```

```python
from citry import Citry
from citry_django import CitryDjangoExtension
from citry_django_djc import tokenize

app = Citry(extensions=[CitryDjangoExtension(tokenizer=tokenize)])
```

Django's own lexer ends a tag at the first `%}`, even one inside a quoted
argument. django-components replaces the tokenizer so a tag can carry template
source as data:

```django
{% component "code_block" code="{% if user %}Hi{% endif %}" %}{% endcomponent %}
```

`citry-django` claims byte ranges with whichever tokenizer it was given. Hand it
this one and the two agree; without it they disagree on where that tag ends, and
you get an error.

[citry-django]: https://github.com/joeyjurjens/citry-django
[django-components]: https://github.com/django-components/django-components
