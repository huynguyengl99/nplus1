"""Django models for the nplusone test application."""

from django.db import models


class User(models.Model):
    """Test user model."""

    hobbies = models.ManyToManyField("Hobby", related_name="users")

    class Meta:
        app_label = "testapp"


class Pet(models.Model):
    """Test pet model with FK to User."""

    user = models.ForeignKey("User", on_delete=models.CASCADE)

    class Meta:
        app_label = "testapp"


class Allergy(models.Model):
    """Test allergy model with M2M to Pet."""

    pets = models.ManyToManyField("Pet")

    class Meta:
        app_label = "testapp"


class Occupation(models.Model):
    """Test occupation model with OneToOne to User."""

    user = models.OneToOneField(
        "User", on_delete=models.CASCADE, related_name="occupation"
    )

    class Meta:
        app_label = "testapp"


class Address(models.Model):
    """Test address model with FK to User."""

    user = models.ForeignKey("User", on_delete=models.CASCADE, related_name="addresses")

    class Meta:
        app_label = "testapp"


class Hobby(models.Model):
    """Test hobby model."""

    class Meta:
        app_label = "testapp"


class NullableFKModel(models.Model):
    """Test model with a nullable FK."""

    user = models.ForeignKey("User", on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        app_label = "testapp"


# --- MTI / Inheritance test models ---


class BasePost(models.Model):
    """Base post model (MTI parent) with FK to User."""

    author = models.ForeignKey("User", on_delete=models.CASCADE, related_name="posts")

    class Meta:
        app_label = "testapp"


class CommunityPost(BasePost):
    """Child post model (MTI child) inheriting author FK from BasePost."""

    class Meta:
        app_label = "testapp"


# --- DRF-like create pattern test models ---


class Workspace(models.Model):
    """Simulates a workspace/tenant model."""

    name = models.CharField(max_length=100, default="")

    class Meta:
        app_label = "testapp"


class Attachment(models.Model):
    """Simulates WorkspaceAttachment — FK to workspace, created via API.

    Reproduces: after create, the workspace FK object is cached on the
    instance via Python setattr. If a queryset elsewhere in the request
    select_related("workspace"), nplus1 may flag it.
    """

    workspace = models.ForeignKey(
        Workspace, on_delete=models.CASCADE, related_name="attachments"
    )
    name = models.CharField(max_length=100, default="")

    class Meta:
        app_label = "testapp"


class Conversation(models.Model):
    """Simulates Conversation — FK to workspace.

    Reproduces: a utility function fetches conversation without
    select_related("workspace"), but something in the request flow
    causes workspace to appear as an eager load.
    """

    workspace = models.ForeignKey(
        Workspace, on_delete=models.CASCADE, related_name="conversations"
    )
    name = models.CharField(max_length=100, default="")

    class Meta:
        app_label = "testapp"


class Message(models.Model):
    """Simulates a message created within a conversation."""

    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="messages"
    )
    content = models.TextField(default="")

    class Meta:
        app_label = "testapp"
