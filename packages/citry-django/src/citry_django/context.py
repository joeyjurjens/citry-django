"""
What a component's own template can read of the host's context.

Citry's rule is that a component takes its inputs: whatever the template around
it could see is not automatically its to read. Django's rule is the opposite -
an ``{% include %}`` sees everything the including template saw - and a Django
project is written expecting that.

Neither is wrong, so this is a setting rather than a decision, named after the
one django-components has for the same job.

``"isolated"`` (default)
    Citry's rule. A component reads its inputs and its own ``template_data``.

``"django"``
    Django's rule. The host's context is there to fall back on, under the
    component's own names. A component that defines ``product`` uses its own;
    one that does not falls through to the host's.

A context processor is ambient in both, because it is ambient in Django too:
every template Django renders has ``user`` and ``LANGUAGE_CODE``, whatever
rendered it. The setting is about the *view's* context, which is the part
Django hands down and Citry does not.
"""

from __future__ import annotations

#: The values ``context_behavior`` accepts.
CONTEXT_BEHAVIORS = frozenset({"django", "isolated"})
