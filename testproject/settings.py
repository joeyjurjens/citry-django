"""
Settings for the project the test suite runs against.

Everything is switched on at once on purpose. The point of this project is to
be a realistic host: Wagtail, an asset pipeline (Sekizai and django-compressor),
third-party tag libraries with awkward shapes, and Citry components, all in one
template tree. A change that breaks any of them breaks a test.
"""

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

SECRET_KEY = "test-only-not-a-secret"
DEBUG = True
ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    "testproject.home",
    "testproject.blocks",
    "wagtail_block_components",
    "wagtail.contrib.forms",
    "wagtail.contrib.redirects",
    "wagtail.embeds",
    "wagtail.sites",
    "wagtail.users",
    "wagtail.snippets",
    "wagtail.documents",
    "wagtail.images",
    "wagtail.search",
    "wagtail.admin",
    "wagtail",
    "modelcluster",
    "taggit",
    "django_filters",
    # The asset pipeline a real project already has, which the optional
    # `citry-django-sekizai` package hands Citry's own assets to.
    "sekizai",
    "compressor",
    # Third-party tag libraries, picked for shapes that are awkward to support.
    # None of them is written for these tests, and the adapter names none.
    "crispy_forms",
    "crispy_bootstrap4",
    "widget_tweaks",
    "django_bootstrap5",
    "sorl.thumbnail",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.humanize",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "wagtail.contrib.redirects.middleware.RedirectMiddleware",
]

ROOT_URLCONF = "testproject.urls"
WSGI_APPLICATION = "testproject.wsgi.application"

TEMPLATES = [
    {
        # Citry element syntax in every Django template. Still Django's own
        # engine -- same lexer, tags and inheritance.
        "BACKEND": "citry_django.backend.CitryTemplates",
        "NAME": "citry",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "sekizai.context_processors.sekizai",
            ],
        },
    },
    {
        # A stock Django engine, so tests can render the same source both ways
        # and require the results to match.
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "NAME": "vanilla",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "sekizai.context_processors.sekizai",
            ],
        },
    },
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR.parent / "db.sqlite3",
    }
}

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR.parent / ".static"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATICFILES_FINDERS = [
    "django.contrib.staticfiles.finders.FileSystemFinder",
    "django.contrib.staticfiles.finders.AppDirectoriesFinder",
    "compressor.finders.CompressorFinder",
]

MEDIA_ROOT = BASE_DIR.parent / ".media"
MEDIA_URL = "/media/"

COMPRESS_ROOT = STATIC_ROOT
COMPRESS_ENABLED = False

CRISPY_TEMPLATE_PACK = "bootstrap4"
CRISPY_ALLOWED_TEMPLATE_PACKS = ["bootstrap4"]

WAGTAIL_SITE_NAME = "citry-django testproject"
WAGTAILADMIN_BASE_URL = "http://example.com"
WAGTAILSEARCH_BACKENDS = {"default": {"BACKEND": "wagtail.search.backends.database"}}
DATA_UPLOAD_MAX_NUMBER_FIELDS = 10_000

# Where a `<c-*>` region looks components up. No INSTALLED_APPS entry is needed
# for the adapter: the backend registers its tags itself.
CITRY_APP = "testproject.citry_app:app"

# Citry emits each component's own CSS and JS by default. Individual tests turn
# this off to hand them to Sekizai instead.
CITRY_DEPS_STRATEGY = "document"
