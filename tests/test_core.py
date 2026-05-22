"""Tests for the core detection modules."""

import inspect
from typing import Any
from unittest import mock

import pytest
from nplusone.core import exceptions, signals
from nplusone.core.listeners import (
    DebugListener,
    EagerListener,
    EagerLoadMessage,
    EagerTracker,
    LazyListener,
    LazyLoadMessage,
    Rule,
)
from nplusone.core.notifiers import ErrorNotifier, LogNotifier, init
from nplusone.core.profiler import (
    Profiler,
    _ImperativeSession,
)


class TestRule:
    """Tests for the Rule matching class."""

    def test_compare_label(self) -> None:
        rule = Rule(label="n_plus_one")
        assert rule.compare("n_plus_one", type("Model", (), {}), "field")
        assert not rule.compare("unused_eager_load", type("Model", (), {}), "field")

    def test_compare_model_class(self) -> None:
        model = type("User", (), {})
        rule = Rule(model=model)
        assert rule.compare("n_plus_one", model, "field")
        assert not rule.compare("n_plus_one", type("Other", (), {}), "field")

    def test_compare_model_string(self) -> None:
        rule = Rule(model="User")
        model = type("User", (), {})
        assert rule.compare("n_plus_one", model, "field")

    def test_compare_model_wildcard(self) -> None:
        rule = Rule(model="U*r")
        model = type("User", (), {})
        assert rule.compare("n_plus_one", model, "field")
        other = type("Admin", (), {})
        assert not rule.compare("n_plus_one", other, "field")

    def test_compare_field(self) -> None:
        rule = Rule(field="addresses")
        model = type("User", (), {})
        assert rule.compare("n_plus_one", model, "addresses")
        assert not rule.compare("n_plus_one", model, "other")

    def test_compare_empty_rule(self) -> None:
        rule = Rule()
        model = type("User", (), {})
        assert not rule.compare("n_plus_one", model, "field")


class TestMessage:
    """Tests for detection messages."""

    def test_lazy_load_message(self) -> None:
        model = type("User", (), {})
        msg = LazyLoadMessage(model, "addresses")
        assert msg.label == "n_plus_one"
        assert "User.addresses" in msg.message
        assert "n+1 query" in msg.message

    def test_eager_load_message(self) -> None:
        model = type("User", (), {})
        msg = EagerLoadMessage(model, "addresses")
        assert msg.label == "unused_eager_load"
        assert "User.addresses" in msg.message
        assert "unnecessary eager load" in msg.message

    def test_message_match(self) -> None:
        model = type("User", (), {})
        msg = LazyLoadMessage(model, "addresses")
        rules = [Rule(model="User")]
        assert msg.match(rules)

    def test_message_no_match(self) -> None:
        model = type("User", (), {})
        msg = LazyLoadMessage(model, "addresses")
        rules = [Rule(model="Admin")]
        assert not msg.match(rules)


class TestLazyListener:
    """Tests for the LazyListener."""

    def test_detects_lazy_load(self) -> None:
        parent = mock.Mock()
        listener = LazyListener(parent)
        listener.setup()

        model = type("User", (), {})

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

        parent.notify.assert_called_once()
        msg = parent.notify.call_args[0][0]
        assert isinstance(msg, LazyLoadMessage)
        assert "User.addresses" in msg.message
        listener.teardown()

    def test_ignores_single_record_load(self) -> None:
        parent = mock.Mock()
        listener = LazyListener(parent)
        listener.setup()

        model = type("User", (), {})

        def ignore_parser(args: Any, kwargs: Any, context: Any, ret: Any) -> list[str]:
            return ["User:1"]

        signals.ignore_load.send(
            signals.get_worker(),
            args=(),
            kwargs={},
            context={},
            ret=None,
            parser=ignore_parser,
        )

        def load_parser(args: Any, kwargs: Any, context: Any, ret: Any) -> list[str]:
            return ["User:1"]

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

        parent.notify.assert_not_called()
        listener.teardown()

    def test_no_detect_when_not_loaded(self) -> None:
        parent = mock.Mock()
        listener = LazyListener(parent)
        listener.setup()

        model = type("User", (), {})

        def lazy_parser(args: Any, kwargs: Any, context: Any) -> tuple[type, str, str]:
            return model, "User:99", "addresses"

        signals.lazy_load.send(
            signals.get_worker(),
            args=(),
            kwargs={},
            context={},
            parser=lazy_parser,
        )

        parent.notify.assert_not_called()
        listener.teardown()


class TestEagerTracker:
    """Tests for the EagerTracker data structure."""

    def test_track_and_unused(self) -> None:
        model = type("User", (), {})
        tracker = EagerTracker()
        tracker.track(model, "hobbies", ["User:1", "User:2"], 1)
        assert tracker.unused == [(model, "hobbies")]

    def test_prune_removes_touched(self) -> None:
        model = type("User", (), {})
        tracker = EagerTracker()
        tracker.track(model, "hobbies", ["User:1"], 1)
        tracker.prune([(model, "hobbies", ["User:1"])])
        assert tracker.unused == []

    def test_prune_leaves_untouched(self) -> None:
        model = type("User", (), {})
        tracker = EagerTracker()
        tracker.track(model, "hobbies", ["User:1"], 1)
        tracker.prune([(model, "hobbies", ["User:99"])])
        assert tracker.unused == [(model, "hobbies")]

    def test_prune_mti_child_touches_parent_tracker(self) -> None:
        """MTI: touch on child model prunes parent tracker by PK."""
        Parent = type("Vehicle", (), {})
        Child = type("Car", (Parent,), {})
        tracker = EagerTracker()
        tracker.track(Parent, "manufacturer", ["Vehicle:1", "Vehicle:2"], 1)
        tracker.prune([(Child, "manufacturer", ["Car:1", "Car:2"])])
        assert tracker.unused == []

    def test_prune_mti_parent_touches_child_tracker(self) -> None:
        """MTI: touch on parent model prunes child tracker by PK."""
        Parent = type("Vehicle", (), {})
        Child = type("Car", (Parent,), {})
        tracker = EagerTracker()
        tracker.track(Child, "manufacturer", ["Car:1"], 1)
        tracker.prune([(Parent, "manufacturer", ["Vehicle:1"])])
        assert tracker.unused == []

    def test_prune_mti_no_false_match_unrelated(self) -> None:
        """MTI: unrelated models do NOT cross-match even with same PK."""
        ModelA = type("Vehicle", (), {})
        ModelB = type("Order", (), {})
        tracker = EagerTracker()
        tracker.track(ModelA, "manufacturer", ["Vehicle:1"], 1)
        tracker.prune([(ModelB, "manufacturer", ["Order:1"])])
        assert tracker.unused == [(ModelA, "manufacturer")]

    def test_prune_mti_different_field_no_match(self) -> None:
        """MTI: same hierarchy but different field name → no prune."""
        Parent = type("Vehicle", (), {})
        Child = type("Car", (Parent,), {})
        tracker = EagerTracker()
        tracker.track(Parent, "manufacturer", ["Vehicle:1"], 1)
        tracker.prune([(Child, "engine", ["Car:1"])])
        assert tracker.unused == [(Parent, "manufacturer")]

    def test_prune_mti_multi_level_inheritance(self) -> None:
        """MTI: multi-level inheritance (grandchild → grandparent)."""
        Base = type("Vehicle", (), {})
        Mid = type("Car", (Base,), {})
        Leaf = type("ElectricCar", (Mid,), {})
        tracker = EagerTracker()
        tracker.track(Base, "manufacturer", ["Vehicle:1"], 1)
        tracker.prune([(Leaf, "manufacturer", ["ElectricCar:1"])])
        assert tracker.unused == []

    def test_prune_mti_partial_overlap(self) -> None:
        """MTI: only overlapping query groups are pruned."""
        Parent = type("Vehicle", (), {})
        Child = type("Car", (Parent,), {})
        tracker = EagerTracker()
        tracker.track(Parent, "manufacturer", ["Vehicle:1"], 1)
        tracker.track(Parent, "manufacturer", ["Vehicle:2"], 2)
        tracker.prune([(Child, "manufacturer", ["Car:1"])])
        # Group 1 (Vehicle:1) pruned, Group 2 (Vehicle:2) remains
        assert tracker.unused == [(Parent, "manufacturer")]

    def test_prune_polymorphic_downcast(self) -> None:
        """Polymorphic: base + child keys in same (model, field) group.

        BaseCredential.objects.select_related("provider") tracks
        "BaseCredential:1". After downcast, touch comes as
        "PersonalCredential:1". Both are in the (BaseCredential, "provider")
        group, so PK-only comparison must match them.
        """
        base = type("BaseCredential", (), {})
        type("PersonalCredential", (base,), {})  # register subclass
        tracker = EagerTracker()
        # Base query tracks under base model name
        tracker.track(base, "provider", ["BaseCredential:1", "BaseCredential:2"], 1)
        # Child refetch also tracks under base model
        tracker.track(base, "provider", ["PersonalCredential:1"], 2)
        # Touch comes with child model prefix but same (base, "provider") key
        touch_keys = ["PersonalCredential:1", "PersonalCredential:2"]
        tracker.prune([(base, "provider", touch_keys)])
        assert tracker.unused == []


class TestEagerListener:
    """Tests for the EagerListener."""

    def test_detects_unused_eager_load(self) -> None:
        parent = mock.Mock()
        listener = EagerListener(parent)
        listener.setup()

        model = type("User", (), {})

        def eager_parser(
            args: Any, kwargs: Any, context: Any
        ) -> tuple[type, str, list[str], int]:
            return model, "hobbies", ["User:1"], 1

        signals.eager_load.send(
            signals.get_worker(),
            args=(),
            kwargs={},
            context={},
            parser=eager_parser,
        )

        listener.teardown()
        parent.notify.assert_called_once()
        msg = parent.notify.call_args[0][0]
        assert isinstance(msg, EagerLoadMessage)
        assert "User.hobbies" in msg.message

    def test_no_detect_when_touched(self) -> None:
        parent = mock.Mock()
        listener = EagerListener(parent)
        listener.setup()

        model = type("User", (), {})

        def eager_parser(
            args: Any, kwargs: Any, context: Any
        ) -> tuple[type, str, list[str], int]:
            return model, "hobbies", ["User:1"], 1

        signals.eager_load.send(
            signals.get_worker(),
            args=(),
            kwargs={},
            context={},
            parser=eager_parser,
        )

        def touch_parser(
            args: Any, kwargs: Any, context: Any
        ) -> tuple[type, str, list[str]]:
            return model, "hobbies", ["User:1"]

        signals.touch.send(
            signals.get_worker(),
            args=(),
            kwargs={},
            context={},
            parser=touch_parser,
        )

        listener.teardown()
        parent.notify.assert_not_called()

    def test_cleanup_without_report(self) -> None:
        parent = mock.Mock()
        listener = EagerListener(parent)
        listener.setup()

        model = type("User", (), {})

        def eager_parser(
            args: Any, kwargs: Any, context: Any
        ) -> tuple[type, str, list[str], int]:
            return model, "hobbies", ["User:1"], 1

        signals.eager_load.send(
            signals.get_worker(),
            args=(),
            kwargs={},
            context={},
            parser=eager_parser,
        )

        listener.cleanup()
        parent.notify.assert_not_called()


class TestNotifiers:
    """Tests for the notification backends."""

    def test_log_notifier_enabled_by_default(self) -> None:
        notifier_list = init({})
        assert len(notifier_list) == 1
        assert isinstance(notifier_list[0], LogNotifier)

    def test_error_notifier_enabled_explicitly(self) -> None:
        notifier_list = init({"NPLUSONE_RAISE": True})
        assert any(isinstance(n, ErrorNotifier) for n in notifier_list)

    def test_log_notifier_logs(self) -> None:
        logger = mock.Mock()
        notifier = LogNotifier({"NPLUSONE_LOGGER": logger})
        model = type("User", (), {})
        msg = LazyLoadMessage(model, "addresses")
        notifier.notify(msg)
        logger.log.assert_called_once()

    def test_error_notifier_raises(self) -> None:
        notifier = ErrorNotifier({})
        model = type("User", (), {})
        msg = LazyLoadMessage(model, "addresses")
        with pytest.raises(exceptions.NPlusOneError):
            notifier.notify(msg)

    def test_error_notifier_custom_error(self) -> None:
        class CustomError(Exception):
            pass

        notifier = ErrorNotifier({"NPLUSONE_ERROR": CustomError})
        model = type("User", (), {})
        msg = LazyLoadMessage(model, "addresses")
        with pytest.raises(CustomError):
            notifier.notify(msg)


class TestProfiler:
    """Tests for the Profiler context manager."""

    def test_profiler_raises_on_lazy_load(self) -> None:
        model = type("User", (), {})

        with pytest.raises(exceptions.NPlusOneError):
            with Profiler():

                def load_parser(
                    args: Any, kwargs: Any, context: Any, ret: Any
                ) -> list[str]:
                    return ["User:1"]

                signals.load.send(
                    signals.get_worker(),
                    args=(),
                    kwargs={},
                    context={},
                    ret=None,
                    parser=load_parser,
                )

                def lazy_parser(
                    args: Any, kwargs: Any, context: Any
                ) -> tuple[type, str, str]:
                    return model, "User:1", "addresses"

                signals.lazy_load.send(
                    signals.get_worker(),
                    args=(),
                    kwargs={},
                    context={},
                    parser=lazy_parser,
                )

    def test_profiler_whitelist(self) -> None:
        model = type("User", (), {})

        with Profiler(whitelist=[{"model": "User"}]):

            def load_parser(
                args: Any, kwargs: Any, context: Any, ret: Any
            ) -> list[str]:
                return ["User:1"]

            signals.load.send(
                signals.get_worker(),
                args=(),
                kwargs={},
                context={},
                ret=None,
                parser=load_parser,
            )

            def lazy_parser(
                args: Any, kwargs: Any, context: Any
            ) -> tuple[type, str, str]:
                return model, "User:1", "addresses"

            signals.lazy_load.send(
                signals.get_worker(),
                args=(),
                kwargs={},
                context={},
                parser=lazy_parser,
            )


class TestSignals:
    """Tests for the signal utilities."""

    def test_signalify(self) -> None:
        called: list[bool] = []
        signal = signals.lazy_load

        def parser(args: Any, kwargs: Any, context: Any) -> tuple[str, str, str]:
            return "model", "key", "field"

        def subscriber(sender: Any, **kw: Any) -> None:
            called.append(True)

        signal.connect(subscriber, sender=signals.get_worker())

        def original(x: int) -> int:
            return x + 1

        wrapped = signals.signalify(signal, original, parser=parser)
        result = wrapped(1)
        assert result == 2
        assert len(called) == 1

    def test_designalify(self) -> None:
        called: list[bool] = []
        signal = signals.lazy_load

        def subscriber(sender: Any, **kw: Any) -> None:
            called.append(True)

        signal.connect(subscriber, sender=signals.get_worker())

        def original() -> int:
            signal.send(signals.get_worker())
            return 1

        wrapped = signals.designalify(signal, original)
        result = wrapped()
        assert result == 1
        assert len(called) == 0

    def test_ignore_context_manager(self) -> None:
        called: list[bool] = []
        signal = signals.lazy_load

        def subscriber(sender: Any, **kw: Any) -> None:
            called.append(True)

        signal.connect(subscriber, sender=signals.get_worker())

        with signals.ignore(signal):
            signal.send(signals.get_worker())

        assert len(called) == 0

        signal.send(signals.get_worker())
        assert len(called) == 1


class TestImperativeSession:
    """Tests for _ImperativeSession internals."""

    def test_session_raise_on_detection(self) -> None:
        """_ImperativeSession with NPLUSONE_RAISE raises NPlusOneError."""
        session = _ImperativeSession(config={"NPLUSONE_RAISE": True})
        model = type("Admin", (), {"__name__": "Admin"})
        msg = LazyLoadMessage(model, "roles")
        with pytest.raises(exceptions.NPlusOneError, match="Admin.roles"):
            session.notify(msg)

    def test_session_whitelist_suppresses_raise(self) -> None:
        """_ImperativeSession whitelist prevents raise."""
        session = _ImperativeSession(
            config={
                "NPLUSONE_RAISE": True,
                "NPLUSONE_WHITELIST": [{"model": "User"}],
            }
        )
        model = type("User", (), {"__name__": "User"})
        msg = LazyLoadMessage(model, "addresses")
        session.notify(msg)  # should NOT raise

    def test_session_log_on_detection(self) -> None:
        """_ImperativeSession with NPLUSONE_LOG logs the message."""
        logger = mock.Mock()
        session = _ImperativeSession(
            config={"NPLUSONE_LOG": True, "NPLUSONE_LOGGER": logger}
        )
        model = type("Admin", (), {"__name__": "Admin"})
        msg = LazyLoadMessage(model, "roles")
        session.notify(msg)
        logger.log.assert_called_once()
        assert "Admin.roles" in logger.log.call_args[0][1]


class TestDebugListener:
    """Tests for the DebugListener signal logger."""

    def test_debug_listener_logs_signals(self) -> None:
        """DebugListener logs eager_load and touch signals."""

        parent = mock.Mock()
        listener = DebugListener(parent)
        listener.setup()

        model = type("User", (), {"__name__": "User"})

        def eager_parser(
            args: Any, kwargs: Any, context: Any
        ) -> tuple[type, str, list[str], int]:
            return model, "hobbies", ["User:1"], 1

        with mock.patch("nplusone.core.listeners._debug_logger") as dbg:
            signals.eager_load.send(
                signals.get_worker(),
                args=(),
                kwargs={},
                context={},
                parser=eager_parser,
            )
            assert dbg.debug.called
            logged = dbg.debug.call_args[0]
            assert "EAGER_REGISTER" in logged[0]
            assert "User" in str(logged)

        listener.teardown()

    def test_debug_listener_logs_lazy_load(self) -> None:
        """DebugListener logs lazy_load signals."""
        parent = mock.Mock()
        listener = DebugListener(parent)
        listener.setup()

        model = type("User", (), {"__name__": "User"})

        def lazy_parser(args: Any, kwargs: Any, context: Any) -> tuple[type, str, str]:
            return model, "User:1", "addresses"

        with mock.patch("nplusone.core.listeners._debug_logger") as dbg:
            signals.lazy_load.send(
                signals.get_worker(),
                args=(),
                kwargs={},
                context={},
                parser=lazy_parser,
            )
            assert dbg.debug.called

        listener.teardown()

    def test_debug_listener_logs_load(self) -> None:
        """DebugListener logs load signals."""
        parent = mock.Mock()
        listener = DebugListener(parent)
        listener.setup()

        def load_parser(args: Any, kwargs: Any, context: Any, ret: Any) -> list[str]:
            return ["User:1"]

        with mock.patch("nplusone.core.listeners._debug_logger") as dbg:
            signals.load.send(
                signals.get_worker(),
                args=(),
                kwargs={},
                context={},
                ret=None,
                parser=load_parser,
            )
            assert dbg.debug.called

        listener.teardown()

    def test_debug_listener_cleanup(self) -> None:
        """DebugListener.cleanup() disconnects without errors."""
        parent = mock.Mock()
        listener = DebugListener(parent)
        listener.setup()
        listener.cleanup()


class TestMessageWithCaller:
    """Tests for stack trace in detection messages."""

    def test_eager_load_message_includes_caller(self) -> None:
        """EagerLoadMessage includes caller info when provided."""

        frame = inspect.stack()[0]
        model = type("User", (), {"__name__": "User"})
        msg = EagerLoadMessage(model, "hobbies", caller=frame)
        assert "Registered at:" in msg.message
        assert "test_core.py" in msg.message

    def test_message_without_caller(self) -> None:
        """Message without caller omits the registration line."""
        model = type("User", (), {"__name__": "User"})
        msg = EagerLoadMessage(model, "hobbies")
        assert "Registered at:" not in msg.message
