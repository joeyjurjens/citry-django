from __future__ import annotations

from .compat import StrEnum


class ContextBehavior(StrEnum):
    """What a component's own template may read of the host's context.

    ``ISOLATED`` is Citry's rule: a component takes its inputs and nothing else.
    ``DJANGO`` is Django's: the host's context is there to fall back on, the way
    it is in an ``{% include %}``. The names follow django-components, whose
    setting does the same job.
    """

    ISOLATED = "isolated"
    DJANGO = "django"


#: The values ``context_behavior`` accepts.
CONTEXT_BEHAVIORS = frozenset(ContextBehavior)


#: The key a component reaches the host's own context under, with
#: ``inject(HOST_PROVIDE)``. Named for the engine that owns that context.
HOST_PROVIDE = "django"
