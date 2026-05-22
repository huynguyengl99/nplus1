"""Signal-based event system for N+1 detection.

Uses blinker signals to decouple ORM event emission from detection logic.
"""

import contextlib
import functools
from collections.abc import Callable, Generator
from typing import Any

import blinker

load = blinker.Signal()
ignore_load = blinker.Signal()
lazy_load = blinker.Signal()
eager_load = blinker.Signal()
touch = blinker.Signal()


def get_worker(*args: Any, **kwargs: Any) -> Any:
    """Get the current worker identifier.

    Overridden by framework integrations (Django, Flask) to return
    a request- or thread-specific sender for signal scoping.
    """
    return blinker.ANY


def signalify(
    signal: blinker.Signal,
    func: Callable[..., Any],
    parser: Callable[..., Any] | None = None,
    **context: Any,
) -> Callable[..., Any]:
    """Wrap a function to emit a signal after execution."""

    @functools.wraps(func)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        ret = func(*args, **kwargs)
        signal.send(
            get_worker(),
            args=args,
            kwargs=kwargs,
            ret=ret,
            context=context,
            parser=parser,
        )
        return ret

    return wrapped


def designalify(
    signal: blinker.Signal,
    func: Callable[..., Any],
) -> Callable[..., Any]:
    """Wrap a function to suppress signal emission during execution."""

    @functools.wraps(func)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        with ignore(signal):
            return func(*args, **kwargs)

    return wrapped


@contextlib.contextmanager
def ignore(
    signal: blinker.Signal,
    sender: Any | None = None,
) -> Generator[None]:
    """Context manager to temporarily disconnect signal receivers."""
    sender = sender or get_worker()
    receivers = list(signal.receivers_for(sender))
    for receiver in receivers:
        signal.disconnect(receiver, sender=sender)
    try:
        yield
    finally:
        for receiver in receivers:
            signal.connect(receiver, sender=sender)
