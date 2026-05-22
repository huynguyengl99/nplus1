"""Context manager and imperative API for standalone N+1 detection.

Use Profiler as a context manager, or setup()/teardown() for imperative use
(Celery tasks, management commands, background jobs, etc.).
"""

import threading
from types import TracebackType
from typing import Any, Self

from nplusone.core import exceptions, listeners, notifiers

# Thread-local storage for imperative setup/teardown
_state = threading.local()


class Profiler:
    """Context manager that detects N+1 query patterns.

    Raises NPlusOneError when an N+1 pattern is detected that doesn't
    match any rule in the whitelist.
    """

    def __init__(self, whitelist: list[dict[str, Any]] | None = None) -> None:
        self.whitelist = [listeners.Rule(**item) for item in (whitelist or [])]
        self._listeners: dict[str, listeners.Listener] = {}

    def __enter__(self) -> Self:
        """Set up detection listeners."""
        for name, listener_type in listeners.listeners.items():
            self._listeners[name] = listener_type(self)
            self._listeners[name].setup()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Tear down detection listeners."""
        for name in list(listeners.listeners.keys()):
            self._listeners.pop(name).teardown()

    def notify(self, message: listeners.Message) -> None:
        """Handle a detection message by raising if not allowlisted."""
        if not message.match(self.whitelist):
            raise exceptions.NPlusOneError(message.message)


class _ImperativeSession:
    """Manages listeners for imperative setup/teardown usage."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}
        self._notifiers = notifiers.init(self.config)
        self.whitelist = [
            listeners.Rule(**item) for item in self.config.get("NPLUSONE_WHITELIST", [])
        ]
        self._listeners: dict[str, listeners.Listener] = {}

    def setup(self) -> None:
        """Set up detection listeners."""
        for name, listener_type in listeners.listeners.items():
            self._listeners[name] = listener_type(self)
            self._listeners[name].setup()

    def teardown(self) -> None:
        """Tear down detection listeners and report findings."""
        for name in list(listeners.listeners.keys()):
            listener = self._listeners.pop(name, None)
            if listener:
                listener.teardown()

    def notify(self, message: listeners.Message) -> None:
        """Dispatch a detection message to all enabled notifiers."""
        if not message.match(self.whitelist):
            for notifier in self._notifiers:
                notifier.notify(message)


def setup(config: dict[str, Any] | None = None) -> None:
    """Start N+1 detection for the current thread.

    Call this at the beginning of a task/job. Call :func:`teardown` when done.

    If ``NPLUSONE_ENABLED`` is False in config/settings, this is a no-op.
    This allows safe use in all environments — just set the flag in prod::

        # settings/base.py
        NPLUSONE_ENABLED = False

        # settings/dev.py
        NPLUSONE_ENABLED = True

    For Django users, config is automatically loaded from Django settings
    if not provided explicitly.

    Usage with Celery::

        from celery.signals import task_prerun, task_postrun
        from nplusone.core.profiler import setup, teardown

        @task_prerun.connect()
        def on_prerun(*args, **kwargs):
            setup()

        @task_postrun.connect()
        def on_postrun(*args, **kwargs):
            teardown()

    Usage in a management command::

        from nplusone.core.profiler import setup, teardown

        class Command(BaseCommand):
            def handle(self, *args, **options):
                setup()
                try:
                    self.do_work()
                finally:
                    teardown()
    """
    if config is None:
        config = _load_django_config()
    if not config.get("NPLUSONE_ENABLED", True):
        return
    session = _ImperativeSession(config)
    session.setup()
    _state.session = session


def teardown() -> None:
    """Stop N+1 detection for the current thread and report findings.

    Must be called after :func:`setup`. Safe to call if setup was not called
    (no-op in that case).
    """
    session: _ImperativeSession | None = getattr(_state, "session", None)
    if session:
        session.teardown()
        _state.session = None


def _load_django_config() -> dict[str, Any]:
    """Try to load config from Django settings. Returns empty dict if unavailable."""
    try:
        from django.conf import settings

        return dict(vars(settings._wrapped))  # type: ignore[misc]
    except Exception:
        return {}
