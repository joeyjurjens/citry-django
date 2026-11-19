"""The locale a region renders in: Django's active language.

Citry reads a render's locale only from the `citry_i18n` provide, so without
this every region would render in the app's default locale whatever language
Django activated for the request.

TODO(E1): a component that a server event re-renders gets no locale yet.
Citry has no public way for an app to supply that render's inputs.
"""

from __future__ import annotations

import logging
from typing import Any

from citry.ext.i18n import I18nNotConfiguredError, make_context
from django.utils import translation

logger = logging.getLogger("citry_django")

#: The provide key Citry reads a render's locale from.
LOCALE_PROVIDE = "citry_i18n"

#: Languages already reported as missing from an app, so the log names each
#: one once per process rather than on every region.
reported: set[tuple[int, str]] = set()


def locale_context(app: Any) -> Any | None:
    """A locale context for Django's active language, or None without i18n.

    Django spells a language `pt-br` or `en-us`. Citry accepts both case
    forms, and an app that lists only `en` gets `en` for `en-us`, the way
    Django itself falls back from a regional variant to its base language. A
    language the app does not list at all renders in the app's default
    locale, and the log says so once.
    """
    language = translation.get_language()
    candidates = [language] if language else []
    if language and "-" in language:
        candidates.append(language.split("-", 1)[0])
    try:
        for candidate in candidates:
            try:
                return make_context(app, locale=candidate)
            except ValueError:
                continue
        if language and (id(app), language) not in reported:
            reported.add((id(app), language))
            logger.warning(
                "Django's active language %r is not one of the Citry app's locales, "
                "so Citry content renders in the app's default locale. Add it to the "
                "app's i18n locales to translate it.",
                language,
            )
        return make_context(app)
    except I18nNotConfiguredError:
        # The app has no translations at all, so there is no locale to pass.
        return None
