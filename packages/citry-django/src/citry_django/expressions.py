"""
Deciding who owns a ``{{ ... }}`` inside a Citry template.

Both engines spell interpolation the same way, so the decision is made per
expression, at compile time:

1. Not a valid Python expression -> Django (``{{ x|date:"Y-m-d" }}``).
2. A plain dotted path -> Django, whose lookup is a superset of Python's
   attribute access: dictionary, then attribute, then index. ``{{ d.key }}``
   on a dict is why this matters.
3. A filter chain whose filter names Django's live registry knows -> Django.
4. Otherwise -> Citry.

Rule 3 is the only genuine overlap: ``a|b`` is both a filter application and a
bitwise or, resolved by asking the registry the template's own ``{% load %}``
lines populate. A Python variable named after a registered filter is therefore
read as the filter.
"""

from __future__ import annotations

import ast
from functools import cache


def is_django_expression(expression: str, engine, extra_libraries: tuple[str, ...] = ()) -> bool:
    """Whether ``{{ expression }}`` should be handed to Django."""
    text = expression.strip()
    if not text:
        return True

    try:
        parsed = ast.parse(text, mode="eval")
    except SyntaxError:
        # Not Python at all: filter arguments (`|date:"Y-m-d"`), translation
        # syntax, and so on.
        return True

    node = parsed.body

    # A plain dotted path is Django's, because Django's lookup is a superset of
    # Python's attribute access there: it tries dictionary, then attribute,
    # then index. `{{ d.key }}` on a dict is the case that matters -- Python
    # attribute access fails on it, Django resolves it, and every Django
    # template in existence writes it that way.
    if _is_dotted_path(node):
        return True

    if not (isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr)):
        return False

    known = _filter_names(engine, extra_libraries)
    while isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        if not (isinstance(node.right, ast.Name) and node.right.id in known):
            return False
        node = node.left
    return True


def _is_dotted_path(node: ast.AST) -> bool:
    """
    Whether the expression is only names joined by dots, e.g. ``a.b.c``.

    A bare name is excluded: both engines resolve one identically, and leaving
    it with Citry keeps Citry's strictness about unknown names. Anything with a
    call, subscript or operator stays Citry's too, since Django cannot express
    those at all.
    """
    if not isinstance(node, ast.Attribute):
        return False
    while isinstance(node, ast.Attribute):
        node = node.value
    return isinstance(node, ast.Name)


@cache
def _filter_names(engine, extra_libraries: tuple[str, ...]) -> frozenset[str]:
    """Every filter name in scope: the engine's builtins plus loaded libraries."""
    names: set[str] = set()
    for library in engine.template_builtins:
        names.update(library.filters)
    for label in extra_libraries:
        library = engine.template_libraries.get(label)
        if library is not None:
            names.update(library.filters)
    return frozenset(names)
