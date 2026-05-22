"""Tests for Django integration."""

from typing import Any
from unittest import mock

import pytest
from django.conf import settings
from django.http.request import HttpRequest
from django.http.response import HttpResponse
from nplusone.ext.django.middleware import NPlusOneMiddleware
from nplusone.ext.django.patch import setup_state

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
