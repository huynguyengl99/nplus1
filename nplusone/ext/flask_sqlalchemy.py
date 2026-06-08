"""Flask-SQLAlchemy integration for N+1 detection.

Provides a Flask extension that manages detection listeners
per-request and configures notification backends from Flask config.
"""

import logging
from typing import Any

from flask import g, request

from nplusone.core import listeners, notifiers, signals
from nplusone.ext.sqlalchemy import apply_patches as _apply_sa_patches

_debug_logger = logging.getLogger("nplusone.debug")

_HTTP_ERROR_STATUS_THRESHOLD = 400


def get_worker() -> Any:
    """Get the current Flask request as the worker identifier."""
    try:
        return request._get_current_object()  # type: ignore[attr-defined]
    except RuntimeError:
        return None


def setup_state() -> None:
    """Configure signals to use Flask request-scoped workers."""
    signals.get_worker = get_worker


setup_state()


class NPlusOne:
    """Flask extension for N+1 query detection.

    Automatically detects N+1 and unused eager load patterns
    during request handling.

    Configuration keys (in Flask app.config):
    - NPLUSONE_ENABLED: Master switch (default True). Set False in prod.
    - NPLUSONE_LOG: Enable logging (default True)
    - NPLUSONE_RAISE: Enable exception raising (default False)
    - NPLUSONE_WHITELIST: List of rule dicts to suppress warnings
    - NPLUSONE_LOGGER: Custom logger instance
    - NPLUSONE_LOG_LEVEL: Custom log level
    - NPLUSONE_SKIP_EAGER_ON_ERROR: Skip eager checks on error responses
      (status >= 400). Default True.
    - NPLUSONE_EAGER_LOAD_SKIP: Optional callable (request, response) -> bool
    - NPLUSONE_DEBUG: Enable verbose signal logging (default False)
    """

    def __init__(self, app: Any | None = None) -> None:
        self.app = app
        self._notifiers: list[notifiers.Notifier] = []
        self.whitelist: list[listeners.Rule] = []
        self._enabled: bool = True
        self._debug: bool = False
        self._skip_eager_on_error: bool = True
        self._eager_load_skip: Any = None
        if app is not None:
            self.init_app(app)

    def load_config(self, app: Any) -> None:
        """Load configuration from Flask app config."""
        self._enabled = app.config.get("NPLUSONE_ENABLED", True)
        self._debug = app.config.get("NPLUSONE_DEBUG", False)
        self._skip_eager_on_error = app.config.get("NPLUSONE_SKIP_EAGER_ON_ERROR", True)
        self._eager_load_skip = app.config.get("NPLUSONE_EAGER_LOAD_SKIP", None)
        self._notifiers = notifiers.init(app.config)
        self.whitelist = [
            listeners.Rule(**item) for item in app.config.get("NPLUSONE_WHITELIST", [])
        ]

    def _should_skip_eager(self, response: Any) -> bool:
        """Determine whether to skip eager load checks for this response."""
        if self._eager_load_skip is not None:
            return bool(self._eager_load_skip(request, response))
        if self._skip_eager_on_error and hasattr(response, "status_code"):
            return bool(response.status_code >= _HTTP_ERROR_STATUS_THRESHOLD)
        return False

    def init_app(self, app: Any) -> None:
        """Initialize the extension with a Flask application."""
        _apply_sa_patches()

        @app.before_request
        def connect() -> None:
            self.load_config(app)
            if not self._enabled:
                return
            g.listeners = getattr(g, "listeners", {})
            for name, listener_type in listeners.listeners.items():
                g.listeners[name] = listener_type(self)
                g.listeners[name].setup()
            if self._debug:
                debug_listener = listeners.DebugListener(self)
                debug_listener.setup()
                g.listeners["debug"] = debug_listener
                _debug_logger.debug(
                    "REQUEST START: %s %s", request.method, request.path
                )

        @app.teardown_request
        def ensure_cleanup(exc: BaseException | None = None) -> None:
            listener_dict = getattr(g, "listeners", None)
            if listener_dict:
                for listener in listener_dict.values():
                    listener.cleanup()
                g.listeners = {}

        @app.after_request
        def disconnect(response: Any) -> Any:
            if not getattr(g, "listeners", None):
                return response
            skip_eager = self._should_skip_eager(response)
            for name in list(listeners.listeners.keys()):
                listener = g.listeners.pop(name, None)
                if listener:
                    if skip_eager and isinstance(listener, listeners.EagerListener):
                        listener.cleanup()
                    else:
                        listener.teardown()
            # Tear down debug listener
            debug_listener = g.listeners.pop("debug", None)
            if debug_listener:
                debug_listener.teardown()
            if self._debug:
                _debug_logger.debug(
                    "REQUEST END: %s %s → %s",
                    request.method,
                    request.path,
                    response.status_code,
                )
            return response

    def notify(self, message: listeners.Message) -> None:
        """Dispatch a detection message to all enabled notifiers."""
        if not message.match(self.whitelist):
            for notifier in self._notifiers:
                notifier.notify(message)

    def ignore(self, signal: str) -> Any:
        """Return a context manager that ignores the named signal."""
        return signals.ignore(getattr(signals, signal))
