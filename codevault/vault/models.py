import os

from django.conf import settings
from django.db import models
from django.urls import reverse


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
    kind = models.CharField(max_length=10, choices=Kind.choices)
    title = models.CharField(max_length=200)
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

    def delete(self, *args, **kwargs):
        # Remove the file from disk as well, to protect the disk quota.
        stored_file = self.upload
        super().delete(*args, **kwargs)
        if stored_file:
            stored_file.delete(save=False)
