"""
Django syntax inside a dynamic attribute.

Citry reads ``c-x="..."`` as a Python expression and refuses foreign source
there outright - ``FOREIGN_SPAN_UNSUPPORTED_POSITION: a Citry expression
attribute cannot contain foreign source`` - so the adapter's usual route for an
attribute holding Django syntax (``ForeignHtmlAttr`` -> ``DjangoHtmlAttr``) is
never reached: Citry produces no foreign attribute to replace. The syntax is
therefore taken out of the source before Citry's parser sees it, which is why
this is opt-in.

A port from Django meets two shapes, and they differ in what they produce:

    c-bind="{{ self.icon.kwargs }}"      a value Django's lookup can find
    c-url="{% url 'basket:summary' %}"   a tag whose result is a string

A lone ``{{ dotted.path }}`` becomes a call to :func:`django_lookup`, which is
Django's own ``Variable``: key, then attribute, then index, calling what it
finds, and declining to call anything marked ``alters_data``. It returns *the
object*, so a component receives an image or a model rather than a rendering of
one. That is the whole reason to reach for this over ``{{ }}`` in text.

Everything else - a tag, a filter, text around the interpolation - produces a
string whatever happens, and a *static* attribute may already hold foreign
source. So the ``c-`` prefix is dropped and the adapter's existing path does
the work unchanged.
"""

from __future__ import annotations

import re
from functools import cache

from django.template import Context, Template
from django.template.base import Variable

from .expressions import is_dotted_path

#: A dynamic attribute. Quotes are matched as a pair and the value may not
#: contain the quote that opened it, which is the rule Citry's parser applies.
_ATTR = re.compile(
    r"""(?P<space>\s)c-(?P<name>[A-Za-z_@$][\w:.@$-]*)="""
    r"""(?P<quote>["'])(?P<value>(?:(?!(?P=quote)).)*)(?P=quote)""",
    re.S,
)

#: The value is one interpolation and nothing else.
_LONE = re.compile(r"^\s*\{\{(?P<expression>.*?)\}\}\s*$", re.S)

_DJANGO_SYNTAX = ("{{", "{%")

LOOKUP_GLOBAL = "citry_django_lookup"

#: The name the resolved root is bound to while Django walks the rest of the
#: path. Never seen by a template; it only has to be a legal Django variable.
_ROOT = "root"


def rewrite_attrs(source: str) -> str:
    """Take Django syntax out of every ``c-`` attribute value in `source`."""
    if "c-" not in source or not any(mark in source for mark in _DJANGO_SYNTAX):
        return source
    return _ATTR.sub(_rewrite_one, source)


def _rewrite_one(match: re.Match[str]) -> str:
    value = match.group("value")
    if not any(mark in value for mark in _DJANGO_SYNTAX):
        return match.group(0)

    space, name, quote = match.group("space"), match.group("name"), match.group("quote")
    lone = _LONE.match(value)
    expression = lone.group("expression").strip() if lone else ""

    if lone and expression.isidentifier():
        # A bare name resolves the same in both engines, which is why
        # `is_dotted_path` excludes it. Leave it to Citry, whose strictness
        # about unknown names is worth keeping.
        return f'{space}c-{name}="{expression}"'

    if lone and is_dotted_path(expression):
        root, _, path = expression.partition(".")
        # Double-quoted, because the call quotes its own argument with an
        # apostrophe and so cannot close the attribute early.
        return f"{space}c-{name}=\"{LOOKUP_GLOBAL}({root}, '{path}')\""

    # A string either way: an ordinary attribute, which Citry accepts and the
    # adapter already renders through Django.
    return f"{space}{name}={quote}{value}{quote}"


def django_lookup(root: object, path: str) -> object:
    """`path` resolved off `root` the way a Django template resolves it.

    Django's own ``Variable`` does the walking, so the rules are not restated
    here and do not drift: dictionary key, then attribute, then numeric index,
    calling what it finds unless that is marked ``do_not_call_in_templates`` or
    ``alters_data``.

    A missing name raises ``VariableDoesNotExist``. Django's *rendering* of a
    ``{{ }}`` swallows that and prints nothing; an attribute is an input rather
    than output, and Citry treats an absent name as an error, so it is left to
    propagate.
    """
    context = Context({_ROOT: root})
    # `alters_data` is answered with the engine's `string_if_invalid`, which
    # Django reads off the bound template. Binding an empty one keeps that
    # branch on Django's answer rather than a crash or an invention here.
    with context.bind_template(_carrier()):
        return Variable(f"{_ROOT}.{path}").resolve(context)


@cache
def _carrier() -> Template:
    """An empty template, for the engine settings a lookup may consult."""
    from .extension import get_django_engine

    return Template("", engine=get_django_engine().engine)
