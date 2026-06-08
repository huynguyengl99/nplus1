"""Listeners that detect N+1 and unnecessary eager load patterns.

LazyListener tracks loaded instances and detects lazy loads on them.
EagerListener tracks eager-loaded relations and detects unused ones.
DebugListener logs all signal activity for debugging.
"""

import fnmatch
import inspect
import logging
from collections import defaultdict
from typing import Any, Protocol

from nplusone.core import signals
from nplusone.core.stack import get_caller

_debug_logger = logging.getLogger("nplusone.debug")


class Rule:
    """A rule for matching N+1 detection results.

    Supports fnmatch patterns on model names for flexible allowlisting.
    """

    def __init__(
        self,
        label: str | None = None,
        model: str | type | None = None,
        field: str | None = None,
    ) -> None:
        self.label = label
        self.model = model
        self.field = field

    def compare(self, label: str, model: type, field: str) -> bool:
        """Check if this rule matches the given detection result."""
        return bool(
            (self.label or self.model or self.field)
            and (self.label is None or self.label == label)
            and (self.model is None or self.match_model(model))
            and (self.field is None or self.field == field)
        )

    def match_model(self, model: type) -> bool:
        """Check if this rule matches the given model."""
        return self.model is model or (
            isinstance(self.model, str) and fnmatch.fnmatch(model.__name__, self.model)
        )


class Message:
    """Base class for detection messages."""

    label: str = ""
    formatter: str = ""

    def __init__(
        self,
        model: type,
        field: str,
        caller: inspect.FrameInfo | None = None,
    ) -> None:
        self.model = model
        self.field = field
        self.caller = caller

    @property
    def message(self) -> str:
        """Format the detection message, including caller info if available."""
        msg = self.formatter.format(
            label=self.label,
            model=self.model.__name__,
            field=self.field,
        )
        if self.caller:
            filename = self.caller.filename
            lineno = self.caller.lineno
            function = self.caller.function
            msg += f"\n  Registered at: {filename}:{lineno} in {function}"
            if self.caller.code_context:
                code = self.caller.code_context[0].strip()
                msg += f"\n                 {code}"
        return msg

    def match(self, rules: list[Rule]) -> bool:
        """Check if this message matches any of the given rules."""
        return any(rule.compare(self.label, self.model, self.field) for rule in rules)


class LazyLoadMessage(Message):
    """Message for detected N+1 lazy load patterns."""

    label = "n_plus_one"
    formatter = "Potential n+1 query detected on `{model}.{field}`"


class EagerLoadMessage(Message):
    """Message for detected unnecessary eager loads."""

    label = "unused_eager_load"
    formatter = "Potential unnecessary eager load detected on `{model}.{field}`"


class NotifyTarget(Protocol):
    """Protocol for objects that can receive notification messages."""

    def notify(self, message: Message) -> None:
        """Handle a detection message."""
        ...


class Listener:
    """Base class for detection listeners."""

    def __init__(self, parent: NotifyTarget) -> None:
        self.parent = parent

    def setup(self) -> None:
        """Connect signal handlers."""

    def teardown(self) -> None:
        """Disconnect signal handlers and report findings."""

    def cleanup(self) -> None:
        """Disconnect signal handlers without reporting."""


class LazyListener(Listener):
    """Detects N+1 lazy load patterns.

    Tracks instances loaded by bulk queries and flags lazy loads on them.
    """

    def setup(self) -> None:
        """Connect to load, ignore_load, and lazy_load signals."""
        self.loaded: set[str] = set()
        self.ignored: set[str] = set()
        worker = signals.get_worker()
        signals.load.connect(self.handle_load, sender=worker, weak=False)
        signals.ignore_load.connect(self.handle_ignore, sender=worker, weak=False)
        signals.lazy_load.connect(self.handle_lazy, sender=worker, weak=False)

    def cleanup(self) -> None:
        """Disconnect signal handlers without reporting."""
        worker = signals.get_worker()
        signals.load.disconnect(self.handle_load, sender=worker)
        signals.ignore_load.disconnect(self.handle_ignore, sender=worker)
        signals.lazy_load.disconnect(self.handle_lazy, sender=worker)

    def teardown(self) -> None:
        """Disconnect signal handlers."""
        self.cleanup()

    def handle_load(
        self,
        caller: Any,
        args: tuple[Any, ...] | None = None,
        kwargs: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
        ret: Any = None,
        parser: Any = None,
    ) -> None:
        """Record instances loaded by bulk queries."""
        instances = parser(args, kwargs, context, ret)
        self.loaded.update(instances)

    def handle_ignore(
        self,
        caller: Any,
        args: tuple[Any, ...] | None = None,
        kwargs: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
        ret: Any = None,
        parser: Any = None,
    ) -> None:
        """Record instances to ignore (single-record queries)."""
        instances = parser(args, kwargs, context, ret)
        self.ignored.update(instances)

    def handle_lazy(
        self,
        caller: Any,
        args: tuple[Any, ...] | None = None,
        kwargs: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
        ret: Any = None,
        parser: Any = None,
    ) -> None:
        """Detect lazy loads on previously bulk-loaded instances."""
        model, instance, field = parser(args, kwargs, context)
        if instance in self.loaded and instance not in self.ignored:
            frame = get_caller()
            message = LazyLoadMessage(model, field, caller=frame)
            self.parent.notify(message)


class EagerListener(Listener):
    """Detects unnecessary eager loads.

    Tracks eager-loaded relations and flags ones that are never accessed.
    """

    def setup(self) -> None:
        """Connect to eager_load signal."""
        worker = signals.get_worker()
        signals.eager_load.connect(self.handle_eager, sender=worker, weak=False)
        self.tracker = EagerTracker()
        self.touched: list[tuple[type, str, list[str]] | None] = []

    def cleanup(self) -> None:
        """Disconnect signal handlers without reporting."""
        worker = signals.get_worker()
        signals.eager_load.disconnect(self.handle_eager, sender=worker)
        signals.touch.disconnect(self.handle_touch, sender=worker)

    def teardown(self) -> None:
        """Report unused eager loads and disconnect signals."""
        self.log_eager()
        self.cleanup()

    def handle_eager(
        self,
        caller: Any,
        args: tuple[Any, ...] | None = None,
        kwargs: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
        ret: Any = None,
        parser: Any = None,
    ) -> None:
        """Track eager-loaded relations with their registration site."""
        model, field, instances, key = parser(args, kwargs, context)
        frame = get_caller()
        self.tracker.track(model, field, instances, key, caller=frame)
        signals.touch.connect(
            self.handle_touch, sender=signals.get_worker(), weak=False
        )

    def handle_touch(
        self,
        caller: Any,
        args: tuple[Any, ...] | None = None,
        kwargs: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
        ret: Any = None,
        parser: Any = None,
    ) -> None:
        """Record attribute access on eager-loaded instances."""
        self.touched.append(parser(args, kwargs, context))

    def log_eager(self) -> None:
        """Report unused eager loads to the parent notifier."""
        self.tracker.prune([each for each in self.touched if each])
        for model, field in self.tracker.unused:
            frame = self.tracker.callers.get((model, field))
            message = EagerLoadMessage(model, field, caller=frame)
            self.parent.notify(message)


class DebugListener(Listener):
    """Logs all signal activity for debugging.

    Enable via ``NPLUSONE_DEBUG = True`` in Django settings or by
    passing ``debug=True`` to the Profiler.

    Output goes to the ``nplusone.debug`` logger at DEBUG level.
    """

    def setup(self) -> None:
        """Connect to all detection signals."""
        worker = signals.get_worker()
        signals.load.connect(self._on_load, sender=worker, weak=False)
        signals.ignore_load.connect(self._on_ignore_load, sender=worker, weak=False)
        signals.lazy_load.connect(self._on_lazy_load, sender=worker, weak=False)
        signals.eager_load.connect(self._on_eager_load, sender=worker, weak=False)
        signals.touch.connect(self._on_touch, sender=worker, weak=False)

    def cleanup(self) -> None:
        """Disconnect all signal handlers."""
        worker = signals.get_worker()
        signals.load.disconnect(self._on_load, sender=worker)
        signals.ignore_load.disconnect(self._on_ignore_load, sender=worker)
        signals.lazy_load.disconnect(self._on_lazy_load, sender=worker)
        signals.eager_load.disconnect(self._on_eager_load, sender=worker)
        signals.touch.disconnect(self._on_touch, sender=worker)

    def teardown(self) -> None:
        """Disconnect signal handlers."""
        self.cleanup()

    def _on_load(self, sender: Any, **kw: Any) -> None:
        parser = kw.get("parser")
        if parser:
            instances = parser(
                kw.get("args"), kw.get("kwargs"), kw.get("context"), kw.get("ret")
            )
            _debug_logger.debug("LOAD: %d instances", len(instances))

    def _on_ignore_load(self, sender: Any, **kw: Any) -> None:
        parser = kw.get("parser")
        if parser:
            instances = parser(
                kw.get("args"), kw.get("kwargs"), kw.get("context"), kw.get("ret")
            )
            _debug_logger.debug("IGNORE_LOAD: %d instances", len(instances))

    def _on_lazy_load(self, sender: Any, **kw: Any) -> None:
        parser = kw.get("parser")
        if parser:
            model, instance_key, field = parser(
                kw.get("args"), kw.get("kwargs"), kw.get("context")
            )
            frame = get_caller()
            loc = _format_caller(frame)
            _debug_logger.debug(
                "LAZY_LOAD: %s.%s (instance %s) at %s",
                model.__name__,
                field,
                instance_key,
                loc,
            )

    def _on_eager_load(self, sender: Any, **kw: Any) -> None:
        parser = kw.get("parser")
        if parser:
            model, field, instances, _key = parser(
                kw.get("args"), kw.get("kwargs"), kw.get("context")
            )
            frame = get_caller()
            loc = _format_caller(frame)
            _debug_logger.debug(
                "EAGER_REGISTER: %s.%s (%d instances) at %s",
                model.__name__,
                field,
                len(instances),
                loc,
            )

    def _on_touch(self, sender: Any, **kw: Any) -> None:
        parser = kw.get("parser")
        if parser:
            result = parser(kw.get("args"), kw.get("kwargs"), kw.get("context"))
            if result:
                model, field, instances = result
                frame = get_caller()
                loc = _format_caller(frame)
                _debug_logger.debug(
                    "EAGER_ACCESS: %s.%s (%d instances) at %s",
                    model.__name__,
                    field,
                    len(instances),
                    loc,
                )


def _format_caller(frame: inspect.FrameInfo | None) -> str:
    """Format a FrameInfo as a concise location string."""
    if not frame:
        return "<unknown>"
    return f"{frame.filename}:{frame.lineno} in {frame.function}"


def _extract_pk(instance_key: str) -> str:
    """Extract PK portion from an instance key like ``ModelName:pk``."""
    return instance_key.split(":", 1)[1] if ":" in instance_key else instance_key


class EagerTracker:
    """Tracks eager-loaded and subsequently touched related rows.

    Stores a mapping of (model, field) associations to nested dicts
    mapping query keys to instance sets.

    Handles multi-table inheritance (MTI) by matching across parent/child
    models when fields match and models are related by inheritance.
    """

    def __init__(self) -> None:
        self.data: defaultdict[tuple[type, str], defaultdict[int, set[str]]] = (
            defaultdict(lambda: defaultdict(set))
        )
        self.callers: dict[tuple[type, str], inspect.FrameInfo | None] = {}

    def track(
        self,
        model: type,
        field: str,
        instances: list[str],
        key: int,
        caller: inspect.FrameInfo | None = None,
    ) -> None:
        """Record an eager-loaded relation."""
        self.data[(model, field)][key].update(instances)
        if caller and (model, field) not in self.callers:
            self.callers[(model, field)] = caller

    def prune(self, touched: list[tuple[type, str, list[str]]]) -> None:
        """Remove eager-loaded relations that were accessed.

        For MTI (multi-table inheritance), a touch on a child model also
        prunes entries for the parent model (and vice versa) when the field
        name matches and models share an inheritance chain. PK-only comparison
        is used for cross-model matching since ``Vehicle:1`` and ``Car:1``
        refer to the same row.
        """
        for touch_model, field, touch_instances in touched:
            if not touch_instances:
                continue
            touch_pks = {_extract_pk(k) for k in touch_instances}

            for (tracked_model, tracked_field), group in list(self.data.items()):
                if tracked_field != field:
                    continue
                if tracked_model is touch_model or _models_related(
                    touch_model, tracked_model
                ):
                    # Compare by PK — within the same (model, field) group,
                    # different model prefixes (e.g., BaseCredential:1 vs
                    # PersonalCredential:1) may refer to the same DB row
                    # due to MTI or polymorphic downcasts.
                    for key, fetch_instances in list(group.items()):
                        fetch_pks = {_extract_pk(k) for k in fetch_instances}
                        if fetch_pks.intersection(touch_pks):
                            group.pop(key, None)

    @property
    def unused(self) -> list[tuple[type, str]]:
        """Return eager-loaded relations that were never accessed."""
        return [(model, field) for (model, field), group in self.data.items() if group]


def _models_related(model_a: type, model_b: type) -> bool:
    """Check if two models share an inheritance chain (parent/child)."""
    try:
        return issubclass(model_a, model_b) or issubclass(model_b, model_a)
    except TypeError:
        return False


listeners: dict[str, type[Listener]] = {
    "lazy_load": LazyListener,
    "eager_load": EagerListener,
}
