from __future__ import annotations

from django import template

from ..nodes import CitryFragment

register = template.Library()


@register.tag("citryfragment")
def citryfragment(parser: template.base.Parser, token: template.base.Token) -> CitryFragment:
    """
    The tag the region marker compiles to.

    Registered as a Django builtin by :mod:`citry_django.backend`, because the
    rewriter injects it into templates that have no ``{% load %}`` line of their
    own. It is generated, never written by hand.
    """
    bits = token.split_contents()
    if len(bits) != 4:
        msg = "{% citryfragment %} takes three arguments and is generated, not written by hand."
        raise template.TemplateSyntaxError(msg)
    try:
        source, origin, around = (bytes.fromhex(bit.strip("\"'")).decode() for bit in bits[1:])
    except (ValueError, UnicodeDecodeError) as exc:
        msg = f"{{% citryfragment %}} received a malformed payload: {exc}"
        raise template.TemplateSyntaxError(msg) from exc
    return CitryFragment(source, origin, open_elements=around.split())
