"""Shared pytest fixtures for nplusone tests."""

import collections
from typing import Any
from unittest import mock

import pytest
from nplusone.core import listeners, signals, stack

Call = collections.namedtuple("Call", ["objects", "frame"])
PATTERNS = [
    "site-packages",
    "pytest",
    "nplusone/core",
    "nplusone/ext",
    "nplusone/tests/conftest",
    "tests/conftest",
]


@pytest.fixture()
def calls() -> Any:
    """Collect lazy_load signals with stack frames."""
    collected: list[Call] = []

    def subscriber(
        sender: Any,
        args: Any = None,
        kwargs: Any = None,
        context: Any = None,
        ret: Any = None,
        parser: Any = None,
    ) -> None:
        collected.append(
            Call(
                parser(args, kwargs, context),
                stack.get_caller(patterns=PATTERNS),
            )
        )

    worker = signals.get_worker()
    signals.lazy_load.connect(subscriber, sender=worker)
    yield collected
    signals.lazy_load.disconnect(subscriber, sender=worker)


@pytest.fixture()
def lazy_listener() -> Any:
    """Set up a LazyListener with a mock parent."""
    mock_parent = mock.Mock()
    listener = listeners.LazyListener(mock_parent)
    listener.setup()
    try:
        yield listener
    finally:
        listener.teardown()
