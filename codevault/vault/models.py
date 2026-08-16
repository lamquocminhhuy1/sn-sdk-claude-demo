import os

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils.text import slugify


class Project(models.Model):
    """A GitHub-repo-like container: one folder per project."""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="projects"
    )
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=120, blank=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        constraints = [
            models.UniqueConstraint(fields=["owner", "slug"], name="unique_owner_slug")
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name) or "project"
            slug = base
            n = 2
            while (
                Project.objects.filter(owner=self.owner, slug=slug)
                .exclude(pk=self.pk)
                .exists()
            ):
                slug = "{0}-{1}".format(base, n)
                n += 1
            self.slug = slug
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("project_detail", args=[self.slug])


def upload_path(instance, filename):
    """Store uploads under media/<kind>/<yyyy-mm>/<filename>."""
    from django.utils import timezone

    folder = "images" if instance.kind == Item.Kind.IMAGE else "files"
    return "{0}/{1}/{2}".format(
        folder, timezone.now().strftime("%Y-%m"), filename
    )


class Item(models.Model):
    class Kind(models.TextChoices):
        CODE = "code", "Source code"
        IMAGE = "image", "Screenshot"
        XML = "xml", "XML file"

    class ScriptType(models.TextChoices):
        SCRIPT_INCLUDE = "script_include", "Script Include"
        BUSINESS_RULE = "business_rule", "Business Rule"
        CLIENT_SCRIPT = "client_script", "Client Script"
        UI_PAGE = "ui_page", "UI Page"
        UI_ACTION = "ui_action", "UI Action"
        UI_MACRO = "ui_macro", "UI Macro"
        SCHEDULED_JOB = "scheduled_job", "Scheduled Job"
        FIX_SCRIPT = "fix_script", "Fix Script"
        REST_API = "rest_api", "Scripted REST API"
        WIDGET = "widget", "Widget"
        OTHER = "other", "Other"

    LANGUAGE_CHOICES = [
        ("javascript", "JavaScript"),
        ("python", "Python"),
        ("java", "Java"),
        ("csharp", "C#"),
        ("sql", "SQL"),
        ("html", "HTML"),
        ("css", "CSS"),
        ("xml", "XML"),
        ("json", "JSON"),
        ("shell", "Shell"),
        ("powershell", "PowerShell"),
        ("text", "Plain text"),
        ("other", "Other"),
    ]

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="items"
    )
    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name="items"
    )
    kind = models.CharField(max_length=10, choices=Kind.choices)
    script_type = models.CharField(
        max_length=20, choices=ScriptType.choices, default=ScriptType.OTHER, blank=True
    )
    title = models.CharField(max_length=200)
    identifier = models.CharField(
        max_length=100,
        blank=True,
        help_text=(
            "API name other scripts use to call this one (e.g. the Script Include "
            "class name). Auto-detected from the code when left blank; used for "
            "dependency detection."
        ),
    )
    identifier_is_manual = models.BooleanField(
        default=False,
        help_text="When set, the identifier was typed by the user and is never overwritten by auto-detection.",
    )
    related_to = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="attachments",
        help_text="For screenshots: the script this screenshot belongs to.",
    )
    note = models.TextField(
        blank=True, help_text="Optional context: what this is, what to ask Claude, etc."
    )
    language = models.CharField(
        max_length=20, choices=LANGUAGE_CHOICES, default="text", blank=True
    )
    content = models.TextField(
        blank=True, help_text="Pasted source code or XML content."
    )
    upload = models.FileField(upload_to=upload_path, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return "[{0}] {1}".format(self.get_kind_display(), self.title)

    def get_absolute_url(self):
        return reverse("item_detail", args=[self.pk])

    @property
    def filename(self):
        if self.upload:
            return os.path.basename(self.upload.name)
        return ""

    @property
    def is_image(self):
        return self.kind == self.Kind.IMAGE

    @property
    def has_text(self):
        return bool(self.content)

    @property
    def screenshots(self):
        return self.attachments.filter(kind=self.Kind.IMAGE)

    def depends_on(self):
        return [d.to_item for d in self.dependencies_out.select_related("to_item")]

    def used_by(self):
        return [d.from_item for d in self.dependencies_in.select_related("from_item")]

    def delete(self, *args, **kwargs):
        # Remove the file from disk as well, to protect the disk quota.
        stored_file = self.upload
        super().delete(*args, **kwargs)
        if stored_file:
            stored_file.delete(save=False)


class Dependency(models.Model):
    """from_item calls / uses to_item (auto-detected from the code)."""

    from_item = models.ForeignKey(
        Item, on_delete=models.CASCADE, related_name="dependencies_out"
    )
    to_item = models.ForeignKey(
        Item, on_delete=models.CASCADE, related_name="dependencies_in"
    )
    detected_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["from_item", "to_item"], name="unique_dependency_edge"
            )
        ]
        verbose_name_plural = "dependencies"

    def __str__(self):
        return "{0} -> {1}".format(self.from_item.title, self.to_item.title)
