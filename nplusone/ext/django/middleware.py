"""Django middleware for N+1 detection.

NPlusOneMiddleware manages detection listeners per-request and
configures notification backends from Django settings.
"""

import fnmatch
import logging
import weakref
from collections.abc import Callable
from typing import Any

from django.conf import settings
from django.utils.deprecation import MiddlewareMixin

from nplusone.core import listeners, notifiers
from nplusone.ext.django.patch import nplus1_context

# Built-in allowlist for models that are known to use internal caching
# (track.md Issue 7: ContentType lookups are cached by Django)
_BUILTIN_ALLOWLIST_MODELS = [
    "contenttypes.ContentType",
]

_HTTP_ERROR_STATUS_THRESHOLD = 400
_debug_logger = logging.getLogger("nplusone.debug")


class DjangoRule(listeners.Rule):
    """Rule subclass that supports Django app_label.ModelName matching."""

    def match_model(self, model: type) -> bool:
        """Match against app_label.ModelName format."""
        return self.model is model or (
            isinstance(self.model, str)
            and fnmatch.fnmatch(
                f"{model._meta.app_label}.{model.__name__}",  # type: ignore[attr-defined]
                self.model,
            )
        )


class NPlusOneMiddleware(MiddlewareMixin):
    """Django middleware that detects N+1 query patterns per-request.

    Supports configuration via Django settings:
    - NPLUSONE_WHITELIST: List of rule dicts to suppress warnings
    - NPLUSONE_LOG: Enable logging (default True)
    - NPLUSONE_RAISE: Enable exception raising (default False)
    - NPLUSONE_LOGGER: Custom logger instance
    - NPLUSONE_LOG_LEVEL: Custom log level
    - NPLUSONE_ERROR: Custom exception class
    - NPLUSONE_SKIP_EAGER_ON_ERROR: Skip eager load checks on error
      responses (status >= 400). Default True.
    - NPLUSONE_EAGER_LOAD_SKIP: Optional callable ``(request, response) -> bool``
      that overrides NPLUSONE_SKIP_EAGER_ON_ERROR when set.
    - NPLUSONE_DEBUG: Enable verbose signal logging (default False).
    - NPLUSONE_REPORT_MODE: "immediate" (default) or "batch".
      In batch mode, all detections are collected and reported together
      at the end of the request.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._listeners: weakref.WeakKeyDictionary[
            Any, dict[str, listeners.Listener]
        ] = weakref.WeakKeyDictionary()
        self._notifiers: list[notifiers.Notifier] = []
        self.whitelist: list[DjangoRule | listeners.Rule] = []
        self.skip_eager_on_error: bool = True
        self.eager_load_skip: Callable[[Any, Any], bool] | None = None
        self.debug: bool = False
        self.report_mode: str = "immediate"
        self._batch: weakref.WeakKeyDictionary[Any, list[listeners.Message]] = (
            weakref.WeakKeyDictionary()
        )

    def load_config(self) -> None:
        """Load configuration from Django settings."""
        self._notifiers = notifiers.init(
            dict(vars(settings._wrapped))  # type: ignore[misc]
        )
        user_whitelist: list[DjangoRule | listeners.Rule] = [
            DjangoRule(**item) for item in getattr(settings, "NPLUSONE_WHITELIST", [])
        ]
        builtin_whitelist: list[DjangoRule | listeners.Rule] = [
            DjangoRule(model=model) for model in _BUILTIN_ALLOWLIST_MODELS
        ]
        self.whitelist = user_whitelist + builtin_whitelist
        self.skip_eager_on_error = getattr(
            settings, "NPLUSONE_SKIP_EAGER_ON_ERROR", True
        )
        self.eager_load_skip = getattr(settings, "NPLUSONE_EAGER_LOAD_SKIP", None)
        self.debug = getattr(settings, "NPLUSONE_DEBUG", False)
        self.report_mode = getattr(settings, "NPLUSONE_REPORT_MODE", "immediate")

    def _should_skip_eager(self, request: Any, response: Any) -> bool:
        """Determine whether to skip eager load checks for this response.

        If NPLUSONE_EAGER_LOAD_SKIP callable is set, it takes precedence.
        Otherwise falls back to NPLUSONE_SKIP_EAGER_ON_ERROR boolean.
        """
        if self.eager_load_skip is not None:
            return bool(self.eager_load_skip(request, response))
        if self.skip_eager_on_error and hasattr(response, "status_code"):
            return bool(response.status_code >= _HTTP_ERROR_STATUS_THRESHOLD)
        return False

    def process_request(self, request: Any) -> None:
        """Set up detection listeners for the current request."""
        self.load_config()
        if not getattr(settings, "NPLUSONE_ENABLED", True):
            return
        # Bind a request-scoped worker ID via contextvars so that the same
        # ID is visible across sync_to_async thread boundaries (ASGI).
        nplus1_context.set(str(id(request)))
        self._listeners[request] = self._listeners.get(request, {})
        for name, listener_type in listeners.listeners.items():
            self._listeners[request][name] = listener_type(self)
            self._listeners[request][name].setup()
        # Set up debug listener if enabled
        if self.debug:
            debug_listener = listeners.DebugListener(self)
            debug_listener.setup()
            self._listeners[request]["debug"] = debug_listener
            _debug_logger.debug("REQUEST START: %s %s", request.method, request.path)
        # Initialize batch collection for this request
        if self.report_mode == "batch":
            self._batch[request] = []

    def process_response(self, request: Any, response: Any) -> Any:
        """Tear down detection listeners and report findings.

        Lazy load (N+1) checks always run. Eager load checks are skipped
        when _should_skip_eager returns True.
        """
        skip_eager = self._should_skip_eager(request, response)
        for name in list(listeners.listeners.keys()):
            listener = self._listeners.get(request, {}).pop(name, None)
            if listener:
                if skip_eager and isinstance(listener, listeners.EagerListener):
                    listener.cleanup()
                else:
                    listener.teardown()
        # Tear down debug listener
        debug_listener = self._listeners.get(request, {}).pop("debug", None)
        if debug_listener:
            debug_listener.teardown()
        # Flush batch if in batch mode
        if self.report_mode == "batch":
            self._flush_batch(request)
        if self.debug:
            _debug_logger.debug(
                "REQUEST END: %s %s → %s",
                request.method,
                request.path,
                getattr(response, "status_code", "?"),
            )
        return response

    def _flush_batch(self, request: Any) -> None:
        """Report all collected messages at once."""
        messages = self._batch.pop(request, [])
        if not messages:
            return
        for notifier in self._notifiers:
            if isinstance(notifier, notifiers.LogNotifier):
                # Log a summary header then each message
                notifier.logger.log(
                    notifier.level,
                    "%d issue(s) in %s %s:",
                    len(messages),
                    request.method,
                    request.path,
                )
                for i, msg in enumerate(messages, 1):
                    notifier.logger.log(notifier.level, "  %d. %s", i, msg.message)
            else:
                # For ErrorNotifier and others, dispatch normally
                for msg in messages:
                    notifier.notify(msg)

    def notify(self, message: listeners.Message) -> None:
        """Dispatch a detection message to all enabled notifiers.

        In batch mode, messages are collected and reported at end of request.
        In immediate mode, messages are dispatched as they are detected.
        """
        if message.match(self.whitelist):
            return
        if self.debug:
            _debug_logger.debug(
                "DETECTED: %s",
                message.message.split("\n")[0],
            )
        if self.report_mode == "batch":
            # Find the current request's batch list
            for _req, batch in self._batch.items():
                batch.append(message)
                return
            # Fallback if no batch found (shouldn't happen)
            self._dispatch_immediate(message)
        else:
            self._dispatch_immediate(message)

    def _dispatch_immediate(self, message: listeners.Message) -> None:
        """Send message to all notifiers immediately."""
        for notifier in self._notifiers:
            notifier.notify(message)
