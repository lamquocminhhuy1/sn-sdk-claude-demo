import os
import secrets
import uuid

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify


class Project(models.Model):
    """A GitHub-repo-like container: one folder per project."""

    class ScopeType(models.TextChoices):
        GLOBAL = "global", "Global Scope"
        SCOPED_APP = "scoped_app", "Scoped App"

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="projects"
    )
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=120, blank=True)
    description = models.TextField(blank=True)
    scope_type = models.CharField(
        max_length=20, choices=ScopeType.choices, default=ScopeType.GLOBAL,
        help_text="Where this project's ServiceNow code lives on the instance.",
    )
    scope_name = models.CharField(
        max_length=100, blank=True,
        help_text="Scoped app identifier, e.g. x_renin_ccr. Required when Scope is Scoped App.",
    )
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

    @property
    def is_scoped_app(self):
        return self.scope_type == self.ScopeType.SCOPED_APP


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

    class SubType(models.TextChoices):
        # Client Script types
        ONLOAD = "onload", "onLoad"
        ONCHANGE = "onchange", "onChange"
        ONSUBMIT = "onsubmit", "onSubmit"
        ONCELLEDIT = "oncelledit", "onCellEdit"
        # Business Rule "when"
        BEFORE = "before", "Before"
        AFTER = "after", "After"
        ASYNC = "async", "Async"
        DISPLAY = "display", "Display"

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

    uid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
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
    title = models.CharField(max_length=10000)
    identifier = models.CharField(
        max_length=10000,
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
    # ServiceNow per-component metadata (all optional; the form shows only
    # the ones relevant to the selected script type).
    sub_type = models.CharField(
        max_length=20, choices=SubType.choices, blank=True,
        help_text="Client Script type (onLoad...) or Business Rule 'when' (before...).",
    )
    table_name = models.CharField(
        max_length=10000, blank=True,
        help_text="Table the script runs on (e.g. incident).",
    )
    field_name = models.CharField(
        max_length=10000, blank=True,
        help_text="Field an onChange Client Script watches.",
    )
    br_order = models.IntegerField(
        null=True, blank=True, help_text="Business Rule execution order."
    )
    operations = models.CharField(
        max_length=10000, blank=True,
        help_text="Operations the Business Rule runs on (e.g. insert, update).",
    )
    condition = models.TextField(
        blank=True, help_text="Condition / filter (Business Rule, UI Action).",
    )
    client_callable = models.BooleanField(
        default=False, help_text="Script Include is client callable (GlideAjax)."
    )
    api_endpoint = models.CharField(
        max_length=10000, blank=True,
        help_text="Scripted REST endpoint, e.g. GET /api/x_scope/v1/things.",
    )
    # Extra code parts for multi-script components (UI Page, Widget).
    html_content = models.TextField(blank=True)
    client_content = models.TextField(blank=True)
    css_content = models.TextField(blank=True)
    upload = models.FileField(upload_to=upload_path, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return "[{0}] {1}".format(self.get_kind_display(), self.title)

    def get_absolute_url(self):
        return reverse("item_detail", args=[self.uid])

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
        return bool(
            self.content or self.html_content or self.client_content or self.css_content
        )

    @property
    def all_code(self):
        """Every code part joined — what dependency detection scans."""
        return "\n".join(
            part for part in
            [self.content, self.html_content, self.client_content, self.css_content]
            if part
        )

    def code_parts(self):
        """(dom_id, label, text, language) for each non-empty code part,
        labelled for the component type - drives the detail-page viewers."""
        st = self.script_type
        if st == self.ScriptType.UI_PAGE:
            main_label = "Processing Script"
        elif st == self.ScriptType.WIDGET:
            main_label = "Server Script"
        elif st == self.ScriptType.REST_API:
            main_label = "Operation Script"
        else:
            main_label = "Source Code"
        html_label = "HTML Template" if st == self.ScriptType.WIDGET else "HTML (Jelly)"
        client_label = (
            "Client Controller" if st == self.ScriptType.WIDGET else "Client Script"
        )
        main_language = "xml" if self.kind == self.Kind.XML else self.language
        parts = [
            ("part-html", html_label, self.html_content, "html"),
            ("part-client", client_label, self.client_content, "javascript"),
            ("part-css", "CSS", self.css_content, "css"),
            ("item-content", main_label, self.content, main_language),
        ]
        return [p for p in parts if p[2]]

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


def generate_api_key():
    return secrets.token_hex(32)


class ApiToken(models.Model):
    """One bearer token per user, used by external clients (e.g. Claude) to
    call the GET/POST API instead of logging in with a session."""

    owner = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="api_token"
    )
    key = models.CharField(max_length=64, unique=True, default=generate_api_key, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return "API token for {0}".format(self.owner.username)

    def regenerate(self):
        self.key = generate_api_key()
        self.save(update_fields=["key"])


# OAuth 2.0 for claude.ai's remote MCP connector (client registration,
# authorization codes, access/refresh tokens) is handled by
# django-oauth-toolkit's own models (oauth2_provider.models.Application /
# Grant / AccessToken / RefreshToken) - see config/settings.py's
# OAUTH2_PROVIDER config and vault/mcp.py. This app used to hand-roll that
# with OAuthClient/OAuthAuthorizationCode/OAuthToken models here; migration
# 0012 drops those tables now that django-oauth-toolkit's own tables cover
# the same job. The four generator/expiry functions below are dead code by
# themselves - kept only because migration 0011 (already applied wherever
# this app is deployed) references them as field defaults by direct
# function reference, and Django re-imports every migration on each run to
# build the migration graph, not just the ones still pending. Removing
# these would break `manage.py migrate` on any database that has already
# applied 0011, including production - never delete them.


def generate_oauth_id():
    return secrets.token_urlsafe(24)


def generate_oauth_secret():
    return secrets.token_urlsafe(48)


def code_expiry():
    from datetime import timedelta

    return timezone.now() + timedelta(minutes=10)


def access_token_expiry():
    from datetime import timedelta

    return timezone.now() + timedelta(hours=1)

# End of migration-0011-compatibility shims; the OAuthClient/
# OAuthAuthorizationCode/OAuthToken model classes that used them are gone,
# the same job.
