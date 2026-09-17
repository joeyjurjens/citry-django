from __future__ import annotations

from typing import Any

from django_components.util.template_parser import parse_template

__all__ = ["tokenize"]


def tokenize(source: str) -> list[Any]:
    """Django tokens with exact positions, read by django-components' parser."""
    return parse_template(source)
