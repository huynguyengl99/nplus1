"""URL configuration for the nplusone test application."""

from django.urls import path

from tests.testapp import views

urlpatterns = [
    path("one_to_one/", views.one_to_one),
    path("one_to_one_first/", views.one_to_one_first),
    path("one_to_many/", views.one_to_many),
    path("many_to_many/", views.many_to_many),
    path("many_to_many_get/", views.many_to_many_get),
    path("prefetch_one_to_one/", views.prefetch_one_to_one),
    path("prefetch_one_to_one_unused/", views.prefetch_one_to_one_unused),
    path("prefetch_many_to_many/", views.prefetch_many_to_many),
    path("many_to_many_impossible/", views.many_to_many_impossible),
    path("many_to_many_impossible_one/", views.many_to_many_impossible_one),
    path("prefetch_many_to_many_render/", views.prefetch_many_to_many_render),
    path("prefetch_many_to_many_unused/", views.prefetch_many_to_many_unused),
    path("prefetch_many_to_many_single/", views.prefetch_many_to_many_single),
    path(
        "prefetch_many_to_many_no_related/",
        views.prefetch_many_to_many_no_related,
    ),
    path("select_one_to_one/", views.select_one_to_one),
    path("select_one_to_one_unused/", views.select_one_to_one_unused),
    path("select_many_to_one/", views.select_many_to_one),
    path("select_many_to_one_unused/", views.select_many_to_one_unused),
    path("prefetch_nested/", views.prefetch_nested),
    path("prefetch_nested_unused/", views.prefetch_nested_unused),
    path("select_nested/", views.select_nested),
    path("select_nested_unused/", views.select_nested_unused),
    path("error_with_eager_load/", views.error_with_eager_load),
    path("select_nullable_fk_null/", views.select_nullable_fk_null),
    path(
        "select_nullable_fk_populated_unused/",
        views.select_nullable_fk_populated_unused,
    ),
    path(
        "select_nullable_fk_populated_used/",
        views.select_nullable_fk_populated_used,
    ),
    path("select_inherited_fk_used/", views.select_inherited_fk_used),
    path("select_inherited_fk_unused/", views.select_inherited_fk_unused),
    # Investigation: create patterns
    path(
        "create_attachment_with_queryset/",
        views.create_attachment_with_queryset,
    ),
    path(
        "create_message_with_conversation_lookup/",
        views.create_message_with_conversation_lookup,
    ),
    path(
        "create_message_with_workspace_filter/",
        views.create_message_with_workspace_filter,
    ),
]
