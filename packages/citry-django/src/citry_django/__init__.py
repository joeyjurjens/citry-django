"""
citry_django -- Citry and Django's template engines, composed.

Each engine owns its own files and delegates the other's syntax to the other's
*real* engine, so both keep their full feature sets::

    from citry import Citry
    from citry_django import CitryDjangoExtension

    app = Citry(extensions=[CitryDjangoExtension()])

Any ``{% tag %}`` you can ``{% load %}`` in Django then works inside a Citry
component, with no per-tag code. For the reverse direction -- Citry syntax in
your existing Django templates -- point ``settings.TEMPLATES`` at
``citry_django.backend.CitryTemplates`` and set ``CITRY_APP``.
"""

from .extension import CitryDjangoExtension, ForeignNode

__all__ = [
    "CitryDjangoExtension",
    "ForeignNode",
]
