"""Django integration for N+1 detection.

Importing this module applies monkey patches to Django's ORM.
"""

from nplusone.ext.django import (
    patch as _patch,  # noqa: F401  # pyright: ignore[reportUnusedImport]
)
from nplusone.ext.django.middleware import NPlusOneMiddleware

__all__ = ["NPlusOneMiddleware"]
