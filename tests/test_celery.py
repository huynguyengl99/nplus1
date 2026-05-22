"""Tests for Celery integration and imperative setup()/teardown() API."""

from typing import Any

import pytest
from celery import Celery
from celery.signals import task_postrun, task_prerun
from nplusone.core import signals
from nplusone.core.exceptions import NPlusOneError
from nplusone.core.profiler import _state, setup, teardown
from nplusone.ext.celery import NPlusOneCelery


def _simulate_n_plus_one() -> None:
    """Simulate a lazy load on a bulk-loaded instance (N+1 pattern).

    Sends load + lazy_load signals with matching instance keys,
    which triggers detection if a LazyListener is active.
    """
    model = type("User", (), {"__name__": "User"})

    def load_parser(args: Any, kwargs: Any, context: Any, ret: Any) -> list[str]:
        return ["User:1", "User:2"]

    signals.load.send(
        signals.get_worker(),
        args=(),
        kwargs={},
        context={},
        ret=None,
        parser=load_parser,
    )

    def lazy_parser(args: Any, kwargs: Any, context: Any) -> tuple[type, str, str]:
        return model, "User:1", "addresses"

    signals.lazy_load.send(
        signals.get_worker(),
        args=(),
        kwargs={},
        context={},
        parser=lazy_parser,
    )


@pytest.fixture(autouse=True)
def _cleanup_state() -> Any:
    """Ensure clean state before/after each test."""
    _state.session = None
    yield
    _state.session = None
    teardown()


class TestNPlusOneCelery:
    """Tests for the NPlusOneCelery auto-integration.

    Uses direct signal dispatch (task_prerun.send / task_postrun.send)
    since Celery's eager mode doesn't reliably fire task signals.
    """

    def test_prerun_activates_postrun_deactivates(self) -> None:
        """Session is active between prerun and postrun signals."""
        app = Celery("test")
        ext = NPlusOneCelery(app, config={"NPLUSONE_LOG": True})  # noqa: F841

        assert getattr(_state, "session", None) is None
        task_prerun.send(sender=None, task_id="t1", task=None)
        assert getattr(_state, "session", None) is not None
        task_postrun.send(sender=None, task_id="t1", task=None)
        assert getattr(_state, "session", None) is None

    def test_disabled_config_no_session(self) -> None:
        """NPLUSONE_ENABLED=False means no session is created."""
        app = Celery("test")
        ext = NPlusOneCelery(app, config={"NPLUSONE_ENABLED": False})  # noqa: F841

        task_prerun.send(sender=None, task_id="t2", task=None)
        assert getattr(_state, "session", None) is None

    def test_raise_on_n_plus_one(self) -> None:
        """NPLUSONE_RAISE=True raises NPlusOneError on detection."""
        app = Celery("test")
        ext = NPlusOneCelery(  # noqa: F841
            app, config={"NPLUSONE_RAISE": True}
        )

        task_prerun.send(sender=None, task_id="t3", task=None)
        with pytest.raises(NPlusOneError, match="User.addresses"):
            _simulate_n_plus_one()
        task_postrun.send(sender=None, task_id="t3", task=None)

    def test_log_on_n_plus_one(self) -> None:
        """NPLUSONE_LOG=True logs but does not raise on detection."""
        notified: list[Any] = []
        app = Celery("test")
        ext = NPlusOneCelery(  # noqa: F841
            app, config={"NPLUSONE_LOG": True, "NPLUSONE_RAISE": False}
        )

        task_prerun.send(sender=None, task_id="t4", task=None)
        session = getattr(_state, "session", None)
        assert session is not None
        session.notify = notified.append  # type: ignore[method-assign]

        _simulate_n_plus_one()

        assert len(notified) == 1
        assert "User.addresses" in notified[0].message
        task_postrun.send(sender=None, task_id="t4", task=None)

    def test_deferred_init_app(self) -> None:
        """init_app can be called after construction."""
        ext = NPlusOneCelery(config={"NPLUSONE_RAISE": True})
        app = Celery("test")
        ext.init_app(app)

        task_prerun.send(sender=None, task_id="t5", task=None)
        with pytest.raises(NPlusOneError):
            _simulate_n_plus_one()
        task_postrun.send(sender=None, task_id="t5", task=None)


class TestManualSetupTeardown:
    """Tests for manual setup()/teardown() — Celery, cron, management commands."""

    def test_raise_on_n_plus_one(self) -> None:
        """setup() with NPLUSONE_RAISE=True raises on detection."""
        setup(config={"NPLUSONE_RAISE": True})
        with pytest.raises(NPlusOneError, match="User.addresses"):
            _simulate_n_plus_one()
        teardown()

    def test_log_on_n_plus_one(self) -> None:
        """setup() with NPLUSONE_LOG=True logs on detection."""
        notified: list[Any] = []
        setup(config={"NPLUSONE_LOG": True, "NPLUSONE_RAISE": False})
        session = getattr(_state, "session", None)
        assert session is not None
        session.notify = notified.append  # type: ignore[method-assign]

        _simulate_n_plus_one()

        assert len(notified) == 1
        assert "User.addresses" in notified[0].message
        teardown()

    def test_no_detection_without_setup(self) -> None:
        """Without setup(), N+1 signals are not captured (no error)."""
        _simulate_n_plus_one()  # should not raise

    def test_teardown_without_setup_is_safe(self) -> None:
        """teardown() without setup() is a no-op."""
        teardown()

    def test_disabled_is_noop(self) -> None:
        """NPLUSONE_ENABLED=False means setup() does nothing."""
        setup(config={"NPLUSONE_ENABLED": False})
        assert getattr(_state, "session", None) is None
        _simulate_n_plus_one()  # should not raise

    def test_whitelist_suppresses(self) -> None:
        """Whitelisted models are not flagged."""
        setup(
            config={
                "NPLUSONE_RAISE": True,
                "NPLUSONE_WHITELIST": [{"model": "User"}],
            }
        )
        _simulate_n_plus_one()  # should NOT raise — User is whitelisted
        teardown()
