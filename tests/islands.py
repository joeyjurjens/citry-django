"""Read the Vue islands out of rendered HTML, for tests.

An island is one Vue app on the page: a host element where the region stood,
one JSON configuration block and one start script. These patterns read
Citry's output as the browser would see it, so a test can count islands
without depending on how Citry spells the rest of its attributes.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

#: The element Vue mounts on. Citry names it after the app id.
HOST = re.compile(r'<div id="citry-vue-(?P<app>[0-9a-f]+)"')

#: The configuration block the runtime reads to start one app.
CONFIG = re.compile(r'<script type="application/json"[^>]*>(?P<json>.*?)</script>', re.S)

#: The script that starts one app once the runtime has loaded.
START = re.compile(r'<script type="module"[^>]*>.*?</script>', re.S)


#: Citry's browser runtime: inline when the app has no mounted routes, else a
#: script loaded from its content-hashed URL.
RUNTIME = re.compile(
    r"<script\b[^>]*>/\* Citry interactive runtime\."
    r'|<script\b[^>]*\bsrc="[^"]*/citry\.[0-9a-f]+\.js"'
)


def runtime_scripts(html: str) -> int:
    """How many copies of Citry's browser runtime `html` loads."""
    return len(RUNTIME.findall(html))


@dataclass(frozen=True)
class Islands:
    hosts: list[str]
    configs: list[dict]
    starts: list[str]

    def __len__(self) -> int:
        return len(self.hosts)


def islands(html: str) -> Islands:
    """Every island in `html`, in page order."""
    return Islands(
        hosts=[match.group("app") for match in HOST.finditer(html)],
        configs=[json.loads(match.group("json")) for match in CONFIG.finditer(html)],
        starts=[match.group(0) for match in START.finditer(html)],
    )
