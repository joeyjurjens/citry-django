from __future__ import annotations

import sys

if sys.version_info >= (3, 11):
    from enum import StrEnum
else:
    from enum import Enum

    class StrEnum(str, Enum):
        """`enum.StrEnum`, which Python only grew in 3.11.

        A member has to *be* its value, not merely carry it: the values here
        travel into HTML comments, into regular expressions and into
        django-compressor, which builds file names out of them. Plain
        `str, Enum` would put `Kind.CSS` in all three, so `__str__` and
        `__format__` are the ones that matter.
        """

        def __str__(self) -> str:
            return str(self.value)

        def __format__(self, spec: str) -> str:
            return str.__format__(self.value, spec)


__all__ = ["StrEnum"]
