"""Django integration for N+1 detection.

Patches are applied only when ``NPLUSONE_ENABLED`` is True (or unset).
If ``NPLUSONE_ENABLED = False`` in Django settings, importing this module
is a no-op — no monkey patches, no signal hooks, zero overhead.
"""

from django.conf import settings

from nplusone.ext.django.middleware import NPlusOneMiddleware

if getattr(settings, "NPLUSONE_ENABLED", True):
    from nplusone.ext.django.patch import apply_patches

    apply_patches()

__all__ = ["NPlusOneMiddleware"]
