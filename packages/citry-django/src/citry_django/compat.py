"""Names that citry-django-compressor 0.3.x imports from this package.

A project that upgrades citry-django alone keeps its installed compressor,
and that compressor imports `StrEnum` from here. Python 3.11 has it in the
standard library, so this module only passes it on.
"""

from enum import StrEnum

__all__ = ["StrEnum"]
