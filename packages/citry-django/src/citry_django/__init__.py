from . import citry_patch
from .assets import scripts, styles
from .extension import CitryDjangoExtension
from .foreign import ForeignNode

citry_patch.apply()

__all__ = [
    "CitryDjangoExtension",
    "ForeignNode",
    "scripts",
    "styles",
]
