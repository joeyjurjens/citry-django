"""
Read Django's syntax the way django-components reads it.

Django's own lexer is not string-aware: it ends a tag at the first ``%}`` it
finds, even one inside a quoted argument. django-components replaces the
tokenizer for exactly that reason, so a tag may carry template source as data::

    {% component "code_block" code="{% if user %}Hi{% endif %}" %}{% endcomponent %}

Django's lexer breaks that into five pieces and tries to execute the
``{% endif %}``. django-components reads it as one tag.

The adapter claims byte ranges with whichever tokenizer it was given. Hand it
this one and the two agree::

    from citry_django import CitryDjangoExtension
    from citry_django_djc import tokenize

    app = Citry(extensions=[CitryDjangoExtension(tokenizer=tokenize)])

Without it the two disagree on where such a tag ends, and the adapter raises
rather than splitting the template differently from Django.
"""

from __future__ import annotations

from typing import Any

from django_components.util.template_parser import parse_template

__all__ = ["tokenize"]


def tokenize(source: str) -> list[Any]:
    """Django tokens with exact positions, read by django-components' parser."""
    return parse_template(source)
