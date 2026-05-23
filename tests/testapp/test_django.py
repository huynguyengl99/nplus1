"""Tests for Django integration."""

import contextvars
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from unittest import mock

import pytest
from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.http.request import HttpRequest
from django.http.response import HttpResponse
from nplusone.core import signals
from nplusone.ext.django.middleware import NPlusOneMiddleware
from nplusone.ext.django.patch import nplus1_context, setup_state

from tests.testapp import models


@pytest.fixture(scope="module", autouse=True)
def _setup() -> None:
    setup_state()


@pytest.fixture()
def objects(db: Any) -> dict[str, Any]:
    """Populate the database with test data."""
    user = models.User.objects.create()
    user2 = models.User.objects.create()
    pet = models.Pet.objects.create(user=user)
    models.Pet.objects.create(user=user2)
    allergy = models.Allergy.objects.create()
    allergy.pets.add(pet)
    occupation = models.Occupation.objects.create(user=user)
    address = models.Address.objects.create(user=user)
    hobby = models.Hobby.objects.create()
    user.hobbies.add(hobby)
    return {
        "user": user,
        "user2": user2,
        "pet": pet,
        "allergy": allergy,
        "occupation": occupation,
        "address": address,
        "hobby": hobby,
    }


@pytest.mark.django_db()
class TestOneToOne:
    """Tests for OneToOne relationship detection."""

    def test_one_to_one(self, objects: Any, calls: Any) -> None:
        occupation = models.Occupation.objects.first()
        occupation.user
        assert len(calls) == 1
        call = calls[0]
        assert call.objects == (
            models.Occupation,
            f"Occupation:{occupation.pk}",
            "user",
        )

    def test_one_to_one_select(self, objects: Any, calls: Any) -> None:
        occupation = models.Occupation.objects.select_related("user").first()
        occupation.user
        assert len(calls) == 0

    def test_one_to_one_prefetch(self, objects: Any, calls: Any) -> None:
        occupation = models.Occupation.objects.prefetch_related("user").first()
        occupation.user
        assert len(calls) == 0

    def test_one_to_one_reverse(self, objects: Any, calls: Any) -> None:
        user = models.User.objects.first()
        user.occupation
        assert len(calls) == 1
        call = calls[0]
        assert call.objects == (models.User, f"User:{user.pk}", "occupation")


@pytest.mark.django_db()
class TestManyToOne:
    """Tests for ManyToOne relationship detection."""

    def test_many_to_one(self, objects: Any, calls: Any) -> None:
        address = models.Address.objects.first()
        address.user
        assert len(calls) == 1
        call = calls[0]
        assert call.objects == (models.Address, f"Address:{address.pk}", "user")

    def test_many_to_one_select(self, objects: Any, calls: Any) -> None:
        address = list(models.Address.objects.select_related("user").all())
        address[0].user
        assert len(calls) == 0

    def test_many_to_one_prefetch(self, objects: Any, calls: Any) -> None:
        address = list(models.Address.objects.prefetch_related("user").all())
        address[0].user
        assert len(calls) == 0

    def test_many_to_one_reverse(self, objects: Any, calls: Any) -> None:
        user = models.User.objects.first()
        user.addresses.first()
        assert len(calls) == 1
        call = calls[0]
        assert call.objects == (models.User, f"User:{user.pk}", "addresses")

    def test_many_to_one_reverse_no_related_name(
        self, objects: Any, calls: Any
    ) -> None:
        user = models.User.objects.first()
        user.pet_set.first()
        assert len(calls) == 1
        call = calls[0]
        assert call.objects == (models.User, f"User:{user.pk}", "pet_set")


@pytest.mark.django_db()
class TestManyToMany:
    """Tests for ManyToMany relationship detection."""

    def test_many_to_many(self, objects: Any, calls: Any) -> None:
        users = models.User.objects.all()
        user = users[0]
        list(user.hobbies.all())
        assert len(calls) == 1
        call = calls[0]
        assert call.objects == (models.User, f"User:{user.pk}", "hobbies")

    def test_many_to_many_prefetch(self, objects: Any, calls: Any) -> None:
        users = models.User.objects.all().prefetch_related("hobbies")
        list(users[0].hobbies.all())
        assert len(calls) == 0

    def test_many_to_many_reverse(self, objects: Any, calls: Any) -> None:
        hobbies = models.Hobby.objects.all()
        hobby = hobbies[0]
        list(hobby.users.all())
        assert len(calls) == 1
        call = calls[0]
        assert call.objects == (models.Hobby, f"Hobby:{hobby.pk}", "users")

    def test_many_to_many_reverse_prefetch(self, objects: Any, calls: Any) -> None:
        hobbies = models.Hobby.objects.all().prefetch_related("users")
        list(hobbies[0].users.all())
        assert len(calls) == 0


@pytest.fixture()
def logger(monkeypatch: pytest.MonkeyPatch) -> mock.Mock:
    """Create a mock logger and patch it into settings."""
    mock_logger = mock.Mock()
    monkeypatch.setattr(settings, "NPLUSONE_LOGGER", mock_logger)
    return mock_logger


@pytest.mark.django_db()
class TestIntegration:
    """Integration tests using Django test client."""

    def test_one_to_one(self, objects: Any, client: Any, logger: mock.Mock) -> None:
        client.get("/one_to_one/")
        assert len(logger.log.call_args_list) == 1
        args = logger.log.call_args[0]
        assert "Occupation.user" in args[1]

    def test_one_to_one_first(
        self, objects: Any, client: Any, logger: mock.Mock
    ) -> None:
        client.get("/one_to_one_first/")
        assert not logger.log.called

    def test_one_to_many(self, objects: Any, client: Any, logger: mock.Mock) -> None:
        client.get("/one_to_many/")
        assert not logger.log.called

    def test_many_to_many(self, objects: Any, client: Any, logger: mock.Mock) -> None:
        client.get("/many_to_many/")
        assert len(logger.log.call_args_list) == 1
        args = logger.log.call_args[0]
        assert "User.hobbies" in args[1]

    def test_many_to_many_get(
        self, objects: Any, client: Any, logger: mock.Mock
    ) -> None:
        client.get("/many_to_many_get/")
        assert len(logger.log.call_args_list) == 0

    def test_many_to_many_reverse_no_related_name(
        self, objects: Any, calls: Any
    ) -> None:
        pet = models.Pet.objects.first()
        pet.allergy_set.first()
        assert len(calls) == 1
        call = calls[0]
        assert call.objects == (models.Pet, f"Pet:{pet.pk}", "allergy_set")

    def test_prefetch_one_to_one(
        self, objects: Any, client: Any, logger: mock.Mock
    ) -> None:
        client.get("/prefetch_one_to_one/")
        assert not logger.log.called

    def test_prefetch_one_to_one_unused(
        self, objects: Any, client: Any, logger: mock.Mock
    ) -> None:
        client.get("/prefetch_one_to_one_unused/")
        assert len(logger.log.call_args_list) == 1
        args = logger.log.call_args[0]
        assert "User.occupation" in args[1]

    def test_prefetch_many_to_many(
        self, objects: Any, client: Any, logger: mock.Mock
    ) -> None:
        client.get("/prefetch_many_to_many/")
        assert not logger.log.called

    def test_many_to_many_impossible(
        self, objects: Any, client: Any, logger: mock.Mock
    ) -> None:
        client.get("/many_to_many_impossible/")
        assert not logger.log.called

    def test_many_to_many_impossible_one(
        self, objects: Any, client: Any, logger: mock.Mock
    ) -> None:
        client.get("/many_to_many_impossible_one/")
        assert not logger.log.called

    def test_prefetch_many_to_many_render(
        self, objects: Any, client: Any, logger: mock.Mock
    ) -> None:
        client.get("/prefetch_many_to_many_render/")
        assert not logger.log.called

    def test_prefetch_many_to_many_empty(
        self, objects: Any, client: Any, logger: mock.Mock
    ) -> None:
        models.User.objects.all().delete()
        client.get("/prefetch_many_to_many/")
        assert not logger.log.called

    def test_prefetch_many_to_many_render_empty(
        self, objects: Any, client: Any, logger: mock.Mock
    ) -> None:
        models.User.objects.all().delete()
        client.get("/prefetch_many_to_many_render/")
        assert not logger.log.called

    def test_prefetch_many_to_many_unused(
        self, objects: Any, client: Any, logger: mock.Mock
    ) -> None:
        client.get("/prefetch_many_to_many_unused/")
        assert len(logger.log.call_args_list) == 1
        args = logger.log.call_args[0]
        assert "User.hobbies" in args[1]

    def test_prefetch_many_to_many_single(
        self, objects: Any, client: Any, logger: mock.Mock
    ) -> None:
        client.get("/prefetch_many_to_many_single/")
        assert not logger.log.called

    def test_prefetch_many_to_many_no_related_name(
        self, objects: Any, client: Any, logger: mock.Mock
    ) -> None:
        client.get("/prefetch_many_to_many_no_related/")
        assert not logger.log.called

    def test_select_one_to_one(
        self, objects: Any, client: Any, logger: mock.Mock
    ) -> None:
        client.get("/select_one_to_one/")
        assert not logger.log.called

    def test_select_one_to_one_unused(
        self, objects: Any, client: Any, logger: mock.Mock
    ) -> None:
        client.get("/select_one_to_one_unused/")
        assert len(logger.log.call_args_list) == 1
        args = logger.log.call_args[0]
        assert "User.occupation" in args[1]

    def test_select_many_to_one(
        self, objects: Any, client: Any, logger: mock.Mock
    ) -> None:
        client.get("/select_many_to_one/")
        assert not logger.log.called

    def test_select_many_to_one_empty(
        self, objects: Any, client: Any, logger: mock.Mock
    ) -> None:
        models.Pet.objects.all().delete()
        client.get("/select_many_to_one/")
        assert not logger.log.called

    def test_select_many_to_one_unused(
        self, objects: Any, client: Any, logger: mock.Mock
    ) -> None:
        client.get("/select_many_to_one_unused/")
        assert len(logger.log.call_args_list) == 1
        args = logger.log.call_args[0]
        assert "Pet.user" in args[1]

    def test_prefetch_nested(
        self, objects: Any, client: Any, logger: mock.Mock
    ) -> None:
        client.get("/prefetch_nested/")
        assert not logger.log.called

    def test_prefetch_nested_unused(
        self, objects: Any, client: Any, logger: mock.Mock
    ) -> None:
        client.get("/prefetch_nested_unused/")
        assert len(logger.log.call_args_list) == 2
        all_calls = [call[0] for call in logger.log.call_args_list]
        assert any("Pet.user" in call[1] for call in all_calls)
        assert any("User.occupation" in call[1] for call in all_calls)

    def test_select_nested(self, objects: Any, client: Any, logger: mock.Mock) -> None:
        client.get("/select_nested/")
        assert not logger.log.called

    def test_select_nested_unused(
        self, objects: Any, client: Any, logger: mock.Mock
    ) -> None:
        client.get("/select_nested_unused/")
        assert len(logger.log.call_args_list) == 2
        all_calls = [call[0] for call in logger.log.call_args_list]
        assert any("Pet.user" in call[1] for call in all_calls)
        assert any("User.occupation" in call[1] for call in all_calls)

    def test_many_to_many_whitelist(
        self, objects: Any, client: Any, logger: mock.Mock
    ) -> None:
        settings.NPLUSONE_WHITELIST = [{"model": "testapp.User"}]
        client.get("/many_to_many/")
        assert not logger.log.called

    def test_many_to_many_whitelist_wildcard(
        self, objects: Any, client: Any, logger: mock.Mock
    ) -> None:
        settings.NPLUSONE_WHITELIST = [{"model": "testapp.*"}]
        client.get("/many_to_many/")
        assert not logger.log.called


@pytest.mark.django_db()
class TestNullableFK:
    """Tests for nullable FK eager load detection."""

    @pytest.fixture()
    def nullable_objects(self, objects: Any) -> None:
        """Create NullableFKModel instances."""
        user = models.User.objects.first()
        models.NullableFKModel.objects.create(user=None)
        models.NullableFKModel.objects.create(user=user)

    def test_nullable_fk_null_not_flagged(
        self, nullable_objects: Any, client: Any, logger: mock.Mock
    ) -> None:
        """Nullable FK with NULL value should not be flagged."""
        # Only create NULL instance
        models.NullableFKModel.objects.all().delete()
        models.NullableFKModel.objects.create(user=None)
        client.get("/select_nullable_fk_null/")
        assert not logger.log.called

    def test_nullable_fk_populated_unused_not_flagged(
        self, nullable_objects: Any, client: Any, logger: mock.Mock
    ) -> None:
        """Nullable FK with populated value, unused — still not flagged.

        select_related on a nullable FK is always a valid optimization.
        """
        client.get("/select_nullable_fk_populated_unused/")
        assert not logger.log.called

    def test_nullable_fk_populated_used_not_flagged(
        self, nullable_objects: Any, client: Any, logger: mock.Mock
    ) -> None:
        """Nullable FK with populated value, accessed — no flag."""
        client.get("/select_nullable_fk_populated_used/")
        assert not logger.log.called


@pytest.mark.django_db()
class TestErrorResponseSkip:
    """Tests for error response eager load skipping."""

    def test_error_response_skips_eager_check(
        self, objects: Any, client: Any, logger: mock.Mock
    ) -> None:
        """Default: eager loads not flagged on error responses (>= 400)."""
        client.get("/error_with_eager_load/")
        assert not logger.log.called

    @pytest.mark.xdist_group("settings_mutation")
    def test_custom_skip_callable_skips(
        self, objects: Any, client: Any, logger: mock.Mock
    ) -> None:
        """Custom callable that returns True → skip eager check."""
        settings.NPLUSONE_EAGER_LOAD_SKIP = lambda req, resp: resp.status_code == 400
        try:
            client.get("/error_with_eager_load/")
            assert not logger.log.called
        finally:
            del settings.NPLUSONE_EAGER_LOAD_SKIP

    @pytest.mark.xdist_group("settings_mutation")
    def test_custom_skip_callable_does_not_skip(
        self, objects: Any, client: Any, logger: mock.Mock
    ) -> None:
        """Custom callable that returns False → eager check runs."""
        settings.NPLUSONE_EAGER_LOAD_SKIP = lambda req, resp: resp.status_code >= 500
        try:
            client.get("/error_with_eager_load/")
            # 400 < 500, so callable returns False → eager check runs → flag
            assert logger.log.called
        finally:
            del settings.NPLUSONE_EAGER_LOAD_SKIP

    @pytest.mark.xdist_group("settings_mutation")
    def test_custom_skip_overrides_boolean(
        self, objects: Any, client: Any, logger: mock.Mock
    ) -> None:
        """Custom callable takes precedence over boolean setting."""
        settings.NPLUSONE_EAGER_LOAD_SKIP = lambda req, resp: False
        try:
            client.get("/error_with_eager_load/")
            # Callable returns False → skip is disabled → flag raised
            assert logger.log.called
        finally:
            del settings.NPLUSONE_EAGER_LOAD_SKIP


@pytest.mark.django_db()
class TestInheritedFK:
    """Tests for FK defined on parent model (MTI)."""

    @pytest.fixture()
    def inherited_objects(self, objects: Any) -> None:
        """Create CommunityPost instances."""
        user = models.User.objects.first()
        models.CommunityPost.objects.create(author=user)

    def test_inherited_fk_used_no_flag(
        self, inherited_objects: Any, client: Any, logger: mock.Mock
    ) -> None:
        """select_related on inherited FK, accessed — no flag."""
        client.get("/select_inherited_fk_used/")
        assert not logger.log.called

    @pytest.mark.xdist_group("settings_mutation")
    def test_inherited_fk_unused_correct_model(
        self, inherited_objects: Any, client: Any, logger: mock.Mock
    ) -> None:
        """select_related on inherited FK, unused — flags correct model.

        Should flag as CommunityPost.author (the forward FK), NOT as
        User.posts (the reverse relation). This was a bug where
        parse_eager_select used != instead of issubclass.
        """
        client.get("/select_inherited_fk_unused/")
        assert logger.log.called
        msg = logger.log.call_args[0][1]
        # Must be the forward relation, not the reverse
        assert "CommunityPost.author" in msg or "BasePost.author" in msg
        assert "User.posts" not in msg


@pytest.mark.django_db()
@pytest.mark.xdist_group("settings_mutation")
class TestSkipEmptyPrefetch:
    """Tests for NPLUSONE_SKIP_EMPTY_PREFETCH setting."""

    def test_empty_prefetch_flagged_by_default(
        self, objects: Any, client: Any, logger: mock.Mock
    ) -> None:
        """By default, empty prefetch results ARE flagged."""
        # prefetch_many_to_many_unused prefetches hobbies but doesn't access them
        client.get("/prefetch_many_to_many_unused/")
        assert logger.log.called

    def test_empty_prefetch_skipped_when_enabled(
        self, objects: Any, client: Any, logger: mock.Mock
    ) -> None:
        """When NPLUSONE_SKIP_EMPTY_PREFETCH=True, empty prefetch not flagged."""
        # Delete all hobbies so prefetch returns empty
        models.Hobby.objects.all().delete()
        settings.NPLUSONE_SKIP_EMPTY_PREFETCH = True
        try:
            client.get("/prefetch_many_to_many/")
            assert not logger.log.called
        finally:
            del settings.NPLUSONE_SKIP_EMPTY_PREFETCH

    def test_nonempty_prefetch_still_flagged_when_enabled(
        self, objects: Any, client: Any, logger: mock.Mock
    ) -> None:
        """Even with setting enabled, non-empty unused prefetch IS flagged."""
        settings.NPLUSONE_SKIP_EMPTY_PREFETCH = True
        try:
            # hobbies exist, prefetch returns data, but not accessed
            client.get("/prefetch_many_to_many_unused/")
            assert logger.log.called
        finally:
            del settings.NPLUSONE_SKIP_EMPTY_PREFETCH


@pytest.mark.django_db()
@pytest.mark.xdist_group("settings_mutation")
class TestDebugMode:
    """Tests for NPLUSONE_DEBUG middleware mode."""

    def test_debug_mode_logs_signals(
        self, objects: Any, client: Any, logger: mock.Mock
    ) -> None:
        """Debug mode logs request start/end and signal activity."""
        settings.NPLUSONE_DEBUG = True
        try:
            with mock.patch("nplusone.ext.django.middleware._debug_logger") as dbg:
                client.get("/many_to_many/")
                debug_calls = [c[0][0] for c in dbg.debug.call_args_list]
                assert any("REQUEST START" in c for c in debug_calls)
                assert any("REQUEST END" in c for c in debug_calls)
        finally:
            del settings.NPLUSONE_DEBUG


@pytest.mark.django_db()
@pytest.mark.xdist_group("settings_mutation")
class TestBatchReporting:
    """Tests for NPLUSONE_REPORT_MODE = 'batch' middleware mode."""

    def test_batch_mode_collects_and_reports(
        self, objects: Any, client: Any, logger: mock.Mock
    ) -> None:
        """Batch mode reports all detections at end of request."""
        settings.NPLUSONE_REPORT_MODE = "batch"
        try:
            client.get("/select_one_to_one_unused/")
            # In batch mode, logger gets a summary header + numbered items
            assert logger.log.called
        finally:
            del settings.NPLUSONE_REPORT_MODE


@pytest.mark.django_db()
def test_values(objects: Any, lazy_listener: Any) -> None:
    """Values queries should not cause errors."""
    list(models.User.objects.values("id"))


def test_middleware_no_process_request() -> None:
    """Middleware should handle missing process_request gracefully."""
    middleware = NPlusOneMiddleware(lambda r: HttpResponse())
    req, resp = HttpRequest(), HttpResponse()
    processed = middleware.process_response(req, resp)
    assert processed is resp


# --- Investigation: DRF-like create patterns ---
# These tests reproduce false positives found in a real DRF codebase.
# The goal is to determine whether nplus1 correctly handles these patterns.


@pytest.fixture()
def workspace_objects(db: Any) -> dict[str, Any]:
    """Create workspace/conversation/attachment test data."""
    workspace = models.Workspace.objects.create(name="test-ws")
    conversation = models.Conversation.objects.create(
        workspace=workspace, name="test-conv"
    )
    # Create some existing attachments (for get_queryset to find)
    attachment = models.Attachment.objects.create(
        workspace=workspace, name="existing.pdf"
    )
    return {
        "workspace": workspace,
        "conversation": conversation,
        "attachment": attachment,
    }


@pytest.mark.django_db()
class TestCreatePatternInvestigation:
    """Investigate false positives from DRF-like create patterns.

    In a real DRF ModelViewSet:
    1. get_queryset() runs on EVERY action (list, create, update, destroy)
    2. get_queryset() may have select_related for list/retrieve serialization
    3. On create, the queryset result is evaluated (for filtering/permissions)
       but the created instance comes from .create(), not from the queryset
    4. nplus1 sees the queryset's select_related as "loaded" but the created
       instance's FK was set via Python, not accessed from the queryset

    Question: does nplus1 correctly flag only the queryset's unused
    select_related, or does it also incorrectly flag the .create() FK?
    """

    def test_create_with_queryset_select_related(
        self, workspace_objects: Any, client: Any, logger: mock.Mock
    ) -> None:
        """Queryset has select_related("workspace"), create doesn't use it.

        Expected behavior: flag the QUERYSET's select_related("workspace")
        as unused (it was evaluated but workspace was never accessed on the
        queryset results). Do NOT flag the .create(workspace=ws) FK cache.
        """
        ws = workspace_objects["workspace"]
        client.get(f"/create_attachment_with_queryset/?workspace_id={ws.pk}")
        # Check what was flagged
        if logger.log.called:
            for call in logger.log.call_args_list:
                flagged_msg = call[0][1]
                # If flagged, it should be about Attachment.workspace from
                # the queryset, not from the .create() call
                assert "Attachment" in flagged_msg or "Workspace" in flagged_msg, (
                    f"Unexpected flag: {flagged_msg}"
                )

    def test_create_message_no_select_related(
        self, workspace_objects: Any, client: Any, logger: mock.Mock
    ) -> None:
        """Conversation fetched via .get() without select_related.

        No select_related("workspace") anywhere in the flow. If
        Conversation.workspace is flagged, it's a false positive.
        """
        conv = workspace_objects["conversation"]
        client.get(
            f"/create_message_with_conversation_lookup/?conversation_id={conv.pk}"
        )
        # Should NOT flag Conversation.workspace — it was never select_related
        if logger.log.called:
            for call in logger.log.call_args_list:
                flagged_msg = call[0][1]
                assert "Conversation.workspace" not in flagged_msg, (
                    f"False positive: {flagged_msg} — workspace was never "
                    f"select_related on the conversation query"
                )

    def test_create_message_with_workspace_filter(
        self, workspace_objects: Any, client: Any, logger: mock.Mock
    ) -> None:
        """Queryset filters through workspace FK but select_related("conversation").

        The filter .filter(conversation__workspace_id=X) creates a JOIN but
        only for WHERE clause. select_related("conversation") loads the
        conversation object. workspace is NOT select_related.

        If Conversation.workspace is flagged, trace whether the filter JOIN
        causes nplus1 to track workspace as "eager loaded."
        """
        ws = workspace_objects["workspace"]
        conv = workspace_objects["conversation"]
        client.get(
            f"/create_message_with_workspace_filter/"
            f"?workspace_id={ws.pk}&conversation_id={conv.pk}"
        )
        if logger.log.called:
            for call in logger.log.call_args_list:
                flagged_msg = call[0][1]
                # Conversation.workspace should NOT be flagged — it's a
                # filter JOIN, not select_related
                if "Conversation.workspace" in flagged_msg:
                    pytest.fail(
                        f"False positive: {flagged_msg} — workspace was only "
                        f"in a WHERE filter, not select_related"
                    )


@pytest.mark.django_db()
class TestASGIThreadBoundary:
    """Tests for contextvars-based worker ID across sync_to_async boundaries.

    Django ASGI runs middleware on the main async thread but dispatches
    views to a thread pool via sync_to_async. contextvars propagation
    ensures the same worker ID is visible across both threads.
    """

    def test_contextvars_overrides_thread_id(self) -> None:
        """When context var is set, get_worker returns it instead of thread ident."""
        from nplusone.ext.django.patch import get_worker

        token = nplus1_context.set("test-worker")
        try:
            assert get_worker() == "test-worker"
        finally:
            nplus1_context.reset(token)

    def test_contextvars_fallback_to_thread_id(self) -> None:
        """Without context var set, get_worker falls back to thread ident."""
        from nplusone.ext.django.patch import get_worker

        # Run in a fresh thread where no context var has been set
        result: list[tuple[str, str]] = []

        def check() -> None:
            result.append((get_worker(), str(threading.current_thread().ident)))

        t = threading.Thread(target=check)
        t.start()
        t.join()
        assert result[0][0] == result[0][1]

    def test_middleware_sets_context_var(self, objects: Any) -> None:
        """process_request sets the contextvars-based worker ID."""
        middleware = NPlusOneMiddleware(lambda req: HttpResponse("ok"))
        request = HttpRequest()
        request.method = "GET"
        request.path = "/test/"
        middleware.process_request(request)
        try:
            assert nplus1_context.get() == str(id(request))
        finally:
            middleware.process_response(request, HttpResponse("ok"))

    def test_eager_load_across_threads_no_false_positive(
        self, objects: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Eager load used in a worker thread should NOT produce false positive.

        Simulates ASGI flow by emitting signals directly:
        1. Main thread: middleware.process_request() sets up listeners
        2. Worker thread: emit eager_load + touch signals (contextvars propagated)
        3. Main thread: middleware.process_response() tears down

        Uses direct signal emission to avoid SQLite cross-thread locking.
        """
        mock_logger = mock.Mock()
        monkeypatch.setattr(settings, "NPLUSONE_LOGGER", mock_logger)

        middleware = NPlusOneMiddleware(lambda req: HttpResponse("ok"))
        request = HttpRequest()
        request.method = "GET"
        request.path = "/test-asgi/"

        # Step 1: Main thread — set up listeners
        middleware.process_request(request)

        # Step 2: Worker thread — emit signals with contextvars propagated
        ctx = contextvars.copy_context()
        instances = ["User:1", "User:2"]

        def eager_parser(*_args: Any) -> tuple[type, str, list[str], int]:
            return (models.User, "addresses", instances, id(instances))

        def touch_parser(*_args: Any) -> tuple[type, str, list[str]]:
            return (models.User, "addresses", instances)

        def worker() -> None:
            worker_id = signals.get_worker()
            signals.eager_load.send(worker_id, parser=eager_parser)
            signals.touch.send(worker_id, parser=touch_parser)

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(ctx.run, worker)
            future.result()

        # Step 3: Main thread — tear down listeners
        response = HttpResponse("ok")
        middleware.process_response(request, response)

        # Should NOT report false positive for unused eager load
        for call in mock_logger.log.call_args_list:
            msg = call[0][1] if len(call[0]) > 1 else ""
            assert "unnecessary eager load" not in msg.lower(), (
                f"False positive eager load detected across thread boundary: {msg}"
            )

    def test_eager_load_across_threads_false_positive_without_contextvars(
        self, objects: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Without contextvars, cross-thread signals would be invisible.

        Verifies that when signals are emitted with a different sender
        (simulating the old thread-ident behavior), the listener misses
        them and reports a false positive.
        """
        mock_logger = mock.Mock()
        monkeypatch.setattr(settings, "NPLUSONE_LOGGER", mock_logger)

        middleware = NPlusOneMiddleware(lambda req: HttpResponse("ok"))
        request = HttpRequest()
        request.method = "GET"
        request.path = "/test-no-ctx/"

        # Step 1: Main thread — set up listeners
        middleware.process_request(request)

        instances = ["User:1"]

        def eager_parser(*_args: Any) -> tuple[type, str, list[str], int]:
            return (models.User, "addresses", instances, id(instances))

        def touch_parser(*_args: Any) -> tuple[type, str, list[str]]:
            return (models.User, "addresses", instances)

        # Emit with a DIFFERENT sender (simulating old thread-ident behavior)
        wrong_worker = "wrong-thread-id"
        signals.eager_load.send(wrong_worker, parser=eager_parser)
        signals.touch.send(wrong_worker, parser=touch_parser)

        # Step 3: Main thread — tear down listeners
        response = HttpResponse("ok")
        middleware.process_response(request, response)

        # Listener never saw the signals → no eager load tracked, no report
        # (This confirms that sender-based scoping matters)
        eager_related = [
            c for c in mock_logger.log.call_args_list
            if len(c[0]) > 1 and "eager load" in c[0][1].lower()
        ]
        assert len(eager_related) == 0

    def test_lazy_load_across_threads_detected(
        self, objects: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Lazy load (N+1) in a worker thread should still be detected.

        Simulates ASGI flow by emitting signals directly with
        contextvars propagation to a worker thread.
        """
        mock_logger = mock.Mock()
        monkeypatch.setattr(settings, "NPLUSONE_LOGGER", mock_logger)

        middleware = NPlusOneMiddleware(lambda req: HttpResponse("ok"))
        request = HttpRequest()
        request.method = "GET"
        request.path = "/test-asgi-lazy/"

        # Step 1: Main thread — set up listeners
        middleware.process_request(request)

        # Step 2: Worker thread — emit load + lazy_load signals
        ctx = contextvars.copy_context()

        def load_parser(*_args: Any) -> set[str]:
            return {"Occupation:1", "Occupation:2"}

        def lazy_parser(*_args: Any) -> tuple[type, str, str]:
            return (models.Occupation, "Occupation:1", "user")

        def worker() -> None:
            worker_id = signals.get_worker()
            signals.load.send(worker_id, parser=load_parser)
            signals.lazy_load.send(worker_id, parser=lazy_parser)

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(ctx.run, worker)
            future.result()

        # Step 3: Main thread — tear down listeners
        response = HttpResponse("ok")
        middleware.process_response(request, response)

        # Should detect the N+1 lazy load
        assert mock_logger.log.called, (
            "N+1 lazy load across thread boundary was not detected"
        )
        logged_msg = mock_logger.log.call_args[0][1]
        assert "Occupation.user" in logged_msg


@pytest.mark.django_db()
class TestGenericRelation:
    """Tests for GenericRelation (contenttypes) eager load tracking."""

    @pytest.fixture()
    def articles(self, db: Any) -> dict[str, Any]:
        """Create Article + Tag test data."""
        from django.contrib.contenttypes.models import ContentType

        article = models.Article.objects.create(title="Test")
        ct = ContentType.objects.get_for_model(models.Article)
        tag = models.Tag.objects.create(
            content_type=ct, object_id=article.pk, name="python"
        )
        return {"article": article, "tag": tag}

    def test_prefetch_generic_relation_used(
        self, articles: Any, client: Any, logger: mock.Mock
    ) -> None:
        """prefetch_related on GenericRelation should NOT false-positive when accessed."""
        client.get("/prefetch_generic_relation/")
        for call in logger.log.call_args_list:
            msg = call[0][1] if len(call[0]) > 1 else ""
            assert "unnecessary eager load" not in msg.lower(), (
                f"False positive on GenericRelation: {msg}"
            )

    def test_prefetch_generic_relation_unused(
        self, articles: Any, client: Any, logger: mock.Mock
    ) -> None:
        """prefetch_related on GenericRelation SHOULD flag when NOT accessed."""
        client.get("/prefetch_generic_relation_unused/")
        assert logger.log.called, "Unused GenericRelation prefetch was not detected"
        logged_msg = logger.log.call_args[0][1]
        assert "Article.tags" in logged_msg
