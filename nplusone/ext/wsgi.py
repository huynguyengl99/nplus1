"""WSGI middleware for N+1 detection.

Wraps a WSGI application with the Profiler context manager.
"""

from typing import Any

from nplusone.core import profiler


class NPlusOneMiddleware:
    """WSGI middleware that detects N+1 query patterns."""

    def __init__(
        self,
        app: Any,
        whitelist: list[dict[str, Any]] | None = None,
    ) -> None:
        self.app = app
        self.whitelist = whitelist

    def __call__(self, environ: dict[str, Any], start_response: Any) -> Any:
        """Wrap the WSGI application with N+1 profiling."""
        with profiler.Profiler(whitelist=self.whitelist):
            return self.app(environ, start_response)
