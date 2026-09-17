from __future__ import annotations

from typing import Any

from django.core.exceptions import ImproperlyConfigured
from django.template import engines
from django.template.backends.django import DjangoTemplates
from django.template.base import DebugLexer
from django.template.exceptions import TemplateSyntaxError
from django.template.utils import InvalidTemplateEngineError


def explain_tokenizer_disagreement(exc: TemplateSyntaxError) -> TemplateSyntaxError:
    """
    Say why Django's parser rejected tags Django's own lexer produced.

    Which byte ranges belong to Django is decided by the extension's
    `tokenizer`, Django's own lexer unless the project passed another. If
    something else compiles the template and it ends tags somewhere else, the
    parser is handed a fragment of a tag, and the error that surfaces explains
    nothing on its own.
    """
    return TemplateSyntaxError(
        f"{exc} -- Django's parser rejected a tag that the configured tokenizer "
        "produced. This usually means your templates are compiled by a different "
        "tokenizer, so its idea of where a tag stops differs from the one read "
        "here. Pass that tokenizer to CitryDjangoExtension(tokenizer=...)."
    )


def django_lexer(source: str) -> list[Any]:
    return DebugLexer(source).tokenize()


def get_django_engine() -> Any:
    """
    Find the project's Django template engine.

    Not simply ``engines["django"]``: a project using
    ``citry_django.backend.CitryTemplates`` (or any other alias) has no engine
    by that name, so the first ``DjangoTemplates``-based engine is used
    instead. Resolved per call because ``engines`` is populated lazily.
    """
    try:
        return engines["django"]
    except InvalidTemplateEngineError:
        pass

    for engine in engines.all():
        if isinstance(engine, DjangoTemplates):
            return engine

    msg = (
        "citry_django needs a Django template engine (a TEMPLATES entry whose "
        "BACKEND is django.template.backends.django.DjangoTemplates, or a "
        "subclass such as citry_django.backend.CitryTemplates), but none is "
        "configured."
    )
    raise ImproperlyConfigured(msg)
