"""Signal-based event system for N+1 detection.

Uses blinker signals to decouple ORM event emission from detection logic.
Blinker's bookkeeping is not thread-safe under per-request connect/disconnect,
so all (dis)connects go through the lock-serialized connect()/disconnect()
helpers, which also prune stale per-request bookkeeping. Sends stay lock-free.
"""

import contextlib
import functools
import threading
from collections.abc import Callable, Generator
from typing import Any

import blinker
from blinker.base import ANY_ID

load = blinker.Signal()
ignore_load = blinker.Signal()
lazy_load = blinker.Signal()
eager_load = blinker.Signal()
touch = blinker.Signal()

# Pre-create the ANY buckets so lock-free sends never insert into _by_sender.
for _signal in (load, ignore_load, lazy_load, eager_load, touch):
    _signal._by_sender.setdefault(  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
        ANY_ID, set()
    )

_bookkeeping_lock = threading.Lock()


def connect(signal: blinker.Signal, receiver: Callable[..., Any], sender: Any) -> None:
    """Connect a strong (GC-safe) sender-scoped receiver, thread-safely."""
    with _bookkeeping_lock:
        signal.connect(receiver, sender=sender, weak=False)


def disconnect(signal: blinker.Signal, receiver: Callable[..., Any]) -> None:
    """Disconnect from all senders — blinker only drops strong receivers then."""
    with _bookkeeping_lock:
        signal.disconnect(receiver)
        _prune_bookkeeping(signal)


def _prune_bookkeeping(signal: blinker.Signal) -> None:
    """Drop empty non-ANY bookkeeping buckets; call with the lock held."""
    private = (
        signal._by_sender,  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
        signal._by_receiver,  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
    )
    for mapping in private:
        for ident, bucket in list(mapping.items()):
            if not bucket and ident != ANY_ID:
                mapping.pop(ident, None)


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
    """Temporarily disconnect receivers, restoring their original strength."""
    sender = sender or get_worker()
    with _bookkeeping_lock:
        receivers = list(signal.receivers_for(sender))
        # Strong receivers are stored as-is; weak ones as weakrefs.
        strong_ids = {
            id(receiver)
            for receiver in receivers
            if any(stored is receiver for stored in signal.receivers.values())
        }
        for receiver in receivers:
            signal.disconnect(receiver, sender=sender)
    try:
        yield
    finally:
        with _bookkeeping_lock:
            for receiver in receivers:
                signal.connect(
                    receiver, sender=sender, weak=id(receiver) not in strong_ids
                )
