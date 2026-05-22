"""Django settings for the nplusone test application."""

import logging
import os

SECRET_KEY = "test-secret-key-not-for-production"  # noqa: S105
DEBUG = True
ALLOWED_HOSTS: list[str] = ["*"]

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "tests.testapp",
]

MIDDLEWARE = [
    "django.middleware.common.CommonMiddleware",
    "nplusone.ext.django.NPlusOneMiddleware",
]

ROOT_URLCONF = "tests.testapp.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
            ],
        },
    },
]

DATABASES = {
    "default": {
        "ENGINE": os.environ.get("DJANGO_DB_ENGINE", "django.db.backends.sqlite3"),
        "NAME": os.environ.get("DJANGO_DB_NAME", ":memory:"),
        "USER": os.environ.get("DJANGO_DB_USER", ""),
        "PASSWORD": os.environ.get("DJANGO_DB_PASSWORD", ""),
        "HOST": os.environ.get("DJANGO_DB_HOST", ""),
        "PORT": os.environ.get("DJANGO_DB_PORT", ""),
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

NPLUSONE_LOGGER = logging.getLogger("nplusone")
NPLUSONE_LOG_LEVEL = logging.DEBUG
