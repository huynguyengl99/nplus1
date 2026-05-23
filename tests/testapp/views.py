"""Django views for the nplusone test application."""

from django.http import HttpResponse
from django.template import Context, Template

from tests.testapp import models


def one_to_one(request):
    """View that triggers N+1 on Occupation.user."""
    occupations = list(models.Occupation.objects.all())
    return HttpResponse(occupations[0].user.id)


def one_to_one_first(request):
    """View using .first() - should not trigger N+1."""
    occupation = models.Occupation.objects.first()
    return HttpResponse(occupation.user.id)


def one_to_many(request):
    """View with prefetch_related - should not trigger N+1."""
    users = models.User.objects.all().prefetch_related("addresses")
    return HttpResponse(users[0].addresses.all())


def many_to_many(request):
    """View that triggers N+1 on User.hobbies."""
    users = list(models.User.objects.all())
    return HttpResponse(users[0].hobbies.all())


def many_to_many_get(request):
    """View using .get() - should not trigger N+1."""
    user = models.User.objects.first()
    return HttpResponse(user.hobbies.all())


def prefetch_one_to_one(request):
    """View with select_related on OneToOne."""
    users = models.User.objects.all().select_related("occupation")
    return HttpResponse(users[0].occupation)


def prefetch_one_to_one_unused(request):
    """View with unused prefetch_related on OneToOne."""
    users = models.User.objects.all().prefetch_related("occupation")
    return HttpResponse(users[0])


def prefetch_many_to_many(request):
    """View with prefetch_related on ManyToMany."""
    users = list(models.User.objects.all().prefetch_related("hobbies"))
    # Touch class-level descriptors to exercise `None` instance checks
    print(models.Occupation.user)
    print(models.User.occupation)
    return HttpResponse(list(user.hobbies.all()) for user in users)


def many_to_many_impossible(request):
    """View using .first() then .all() - should not trigger N+1."""
    user = models.User.objects.first()
    list(models.User.objects.all())
    return HttpResponse(user.hobbies.all())


def many_to_many_impossible_one(request):
    """View using .get() then .all() - should not trigger N+1."""
    user = models.User.objects.first()
    list(models.User.objects.all())
    return HttpResponse(user.hobbies.all())


def prefetch_many_to_many_render(request):
    """View rendering prefetched M2M in template."""
    users = models.User.objects.all().prefetch_related("hobbies")
    template = """
    {% for user in users %}
        {% for hobby in user.hobbies.all %}
            {{ hobby.id }}
        {% endfor %}
    {% endfor %}
    """
    resp = Template(template).render(Context({"users": users}))
    return HttpResponse(resp)


def prefetch_many_to_many_unused(request):
    """View with unused prefetch_related on M2M."""
    users = models.User.objects.all().prefetch_related("hobbies")
    return HttpResponse(users[0])


def prefetch_many_to_many_single(request):
    """View indexing into prefetched M2M."""
    hobbies = models.Hobby.objects.all().prefetch_related("users")
    return HttpResponse(hobbies[0].users.all()[0])


def prefetch_many_to_many_no_related(request):
    """View with prefetch_related on auto-generated name."""
    pets = models.Pet.objects.all().prefetch_related("allergy_set")
    return HttpResponse(pets[0].allergy_set.all()[0])


def select_one_to_one(request):
    """View with select_related on OneToOne - used."""
    users = models.User.objects.all().select_related("occupation")
    return HttpResponse(users[0].occupation)


def select_one_to_one_unused(request):
    """View with select_related on OneToOne - unused."""
    users = models.User.objects.all().select_related("occupation")
    return HttpResponse(users[0])


def select_many_to_one(request):
    """View with select_related on FK - used."""
    pets = list(models.Pet.objects.all().select_related("user"))
    return HttpResponse(pets[0].user if pets else None)


def select_many_to_one_unused(request):
    """View with select_related on FK - unused."""
    pets = list(models.Pet.objects.all().select_related("user"))
    return HttpResponse(pets[0])


def prefetch_nested(request):
    """View with nested prefetch_related - used."""
    pets = list(models.Pet.objects.all().prefetch_related("user__occupation"))
    return HttpResponse(pets[0].user.occupation)


def prefetch_nested_unused(request):
    """View with nested prefetch_related - unused."""
    pets = list(models.Pet.objects.all().prefetch_related("user__occupation"))
    return HttpResponse(pets[0])


def select_nested(request):
    """View with nested select_related - used."""
    pets = list(models.Pet.objects.all().select_related("user__occupation"))
    return HttpResponse(pets[0].user.occupation)


def select_nested_unused(request):
    """View with nested select_related - unused."""
    pets = list(models.Pet.objects.all().select_related("user__occupation"))
    return HttpResponse(pets[0])


def error_with_eager_load(request):
    """View that returns 400 with eager-loaded data."""
    list(models.User.objects.all().select_related("occupation"))
    return HttpResponse(status=400)


def select_nullable_fk_null(request):
    """View with select_related on nullable FK where value is NULL."""
    items = list(models.NullableFKModel.objects.select_related("user"))
    return HttpResponse(str(len(items)))


def select_nullable_fk_populated_unused(request):
    """View with select_related on nullable FK, populated but unused."""
    items = list(models.NullableFKModel.objects.select_related("user"))
    return HttpResponse(str(items[0].id))


def select_nullable_fk_populated_used(request):
    """View with select_related on nullable FK, populated and used."""
    items = list(models.NullableFKModel.objects.select_related("user"))
    return HttpResponse(str(items[0].user))


def select_inherited_fk_used(request):
    """View with select_related on inherited FK (MTI) - used."""
    posts = list(models.CommunityPost.objects.select_related("author"))
    return HttpResponse(str(posts[0].author.id))


def select_inherited_fk_unused(request):
    """View with select_related on inherited FK (MTI) - unused."""
    posts = list(models.CommunityPost.objects.select_related("author"))
    return HttpResponse(str(posts[0].id))


# --- DRF-like create pattern views ---
# These simulate the patterns that trigger false positives in a real
# DRF+ModelViewSet codebase.


def create_attachment_with_queryset(request):
    """Simulates DRF ModelViewSet create flow.

    Pattern:
    1. get_queryset() runs (for permissions/filtering) with select_related
    2. perform_create() creates the instance via .create(workspace=ws_obj)
    3. Response returns the created instance (only uses .id and .name)

    In a real DRF viewset, get_queryset() is called even for create actions.
    The select_related in get_queryset() is for list/retrieve, but it also
    runs on create. The created instance has workspace cached from Python
    setattr, and the queryset loaded workspace via JOIN.
    """
    workspace = models.Workspace.objects.get(pk=request.GET["workspace_id"])

    # Step 1: Simulate get_queryset() with filtering (runs on every action)
    _qs = list(
        models.Attachment.objects.filter(workspace=workspace).select_related(
            "workspace"
        )
    )

    # Step 2: Create new instance (like perform_create)
    attachment = models.Attachment.objects.create(workspace=workspace, name="test.pdf")

    # Step 3: Response only uses id and name (not workspace object)
    return HttpResponse(f"{attachment.id}:{attachment.name}")


def create_message_with_conversation_lookup(request):
    """Simulates message create where conversation is fetched without
    select_related, but workspace somehow appears as eager load.

    Pattern:
    1. Utility function fetches conversation: Conversation.objects.get(pk=...)
       (no select_related)
    2. Create message with conversation FK
    3. Response returns message content

    The question: where does workspace get flagged? The conversation.get()
    doesn't select_related workspace. But workspace might be loaded via:
    - A filter: .filter(conversation__workspace=workspace) triggers a JOIN
    - Permission check: accessing conversation.workspace_id (column, not object)
    """
    conversation = models.Conversation.objects.get(pk=request.GET["conversation_id"])

    # Create message (like DRF's perform_create)
    message = models.Message.objects.create(conversation=conversation, content="hello")

    return HttpResponse(f"{message.id}:{message.content}")


# --- GenericRelation views ---


def prefetch_generic_relation(request):
    """View with prefetch_related on GenericRelation - used."""
    articles = list(models.Article.objects.prefetch_related("tags").all())
    for article in articles:
        list(article.tags.all())
    return HttpResponse("ok")


def prefetch_generic_relation_unused(request):
    """View with prefetch_related on GenericRelation - unused."""
    articles = list(models.Article.objects.prefetch_related("tags").all())
    return HttpResponse(str(articles[0].title))


def create_message_with_workspace_filter(request):
    """Simulates message create where the queryset filters through workspace.

    This is the likely cause: get_queryset() does:
      Message.objects.filter(
          conversation__workspace__members__user=user
      )
    This JOIN traverses conversation→workspace but only for filtering.
    The workspace object is loaded into the JOIN result but never accessed.
    """
    workspace_id = request.GET["workspace_id"]
    conversation_id = request.GET["conversation_id"]

    # Simulate get_queryset() with a filter that JOINs through workspace
    _qs = list(
        models.Message.objects.filter(
            conversation_id=conversation_id,
            conversation__workspace_id=workspace_id,
        ).select_related("conversation")
    )

    # Create message
    message = models.Message.objects.create(
        conversation_id=conversation_id, content="hello"
    )

    return HttpResponse(f"{message.id}:{message.content}")
