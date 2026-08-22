import re

from django import forms

from .models import Item, Project

ALLOWED_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")
ALLOWED_XML_EXTENSIONS = (".xml", ".xsd", ".xsl", ".xslt", ".wsdl")

SCOPE_NAME_RE = re.compile(r"^x_[a-z0-9]+_[a-z0-9_]+$")


class ProjectForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = ["name", "description", "scope_type", "scope_name"]
        widgets = {
            "name": forms.TextInput(
                attrs={"autofocus": "autofocus", "placeholder": "e.g. Incident auto-assignment"}
            ),
            "description": forms.Textarea(
                attrs={"rows": 3, "placeholder": "What is this project about?"}
            ),
            "scope_name": forms.TextInput(attrs={"placeholder": "e.g. x_renin_ccr"}),
        }

    def clean(self):
        cleaned = super().clean()
        scope_type = cleaned.get("scope_type")
        scope_name = (cleaned.get("scope_name") or "").strip().lower()

        if scope_type == Project.ScopeType.SCOPED_APP:
            if not scope_name:
                raise forms.ValidationError(
                    "Enter the scoped app name (e.g. x_renin_ccr) for a Scoped App project."
                )
            if not SCOPE_NAME_RE.match(scope_name):
                raise forms.ValidationError(
                    "Scope name should look like x_<vendor>_<app>, e.g. x_renin_ccr "
                    "(lowercase letters, digits, and underscores only)."
                )
            cleaned["scope_name"] = scope_name
        else:
            # Global scope has no app namespace - drop anything typed before switching.
            cleaned["scope_name"] = ""

        return cleaned


class ItemForm(forms.ModelForm):
    class Meta:
        model = Item
        fields = [
            "kind",
            "script_type",
            "title",
            "identifier",
            "identifier_is_manual",
            "related_to",
            "language",
            "content",
            "html_content",
            "client_content",
            "css_content",
            "sub_type",
            "table_name",
            "field_name",
            "br_order",
            "operations",
            "condition",
            "client_callable",
            "api_endpoint",
            "upload",
            "note",
        ]
        widgets = {
            "content": forms.Textarea(
                attrs={
                    "rows": 16,
                    "spellcheck": "false",
                    "placeholder": "Paste your code / XML here...",
                    "class": "code-area",
                    "data-mode": "main",
                }
            ),
            "html_content": forms.Textarea(
                attrs={"rows": 10, "spellcheck": "false", "class": "code-area", "data-mode": "html"}
            ),
            "client_content": forms.Textarea(
                attrs={"rows": 10, "spellcheck": "false", "class": "code-area", "data-mode": "javascript"}
            ),
            "css_content": forms.Textarea(
                attrs={"rows": 8, "spellcheck": "false", "class": "code-area", "data-mode": "css"}
            ),
            "condition": forms.Textarea(
                attrs={"rows": 2, "placeholder": "e.g. current.priority == 1"}
            ),
            "table_name": forms.TextInput(attrs={"placeholder": "e.g. incident"}),
            "field_name": forms.TextInput(attrs={"placeholder": "e.g. assignment_group"}),
            "operations": forms.TextInput(attrs={"placeholder": "e.g. insert, update"}),
            "br_order": forms.NumberInput(attrs={"placeholder": "100"}),
            "api_endpoint": forms.TextInput(attrs={"placeholder": "GET /api/x_scope/v1/things"}),
            "note": forms.Textarea(
                attrs={"rows": 3, "placeholder": "Optional note or prompt for Claude..."}
            ),
            "title": forms.TextInput(attrs={"autofocus": "autofocus"}),
            "identifier": forms.TextInput(
                attrs={"placeholder": "e.g. CalcUtils (auto-detected if empty)"}
            ),
        }

    def __init__(self, *args, **kwargs):
        self.project = kwargs.pop("project", None)
        super().__init__(*args, **kwargs)
        # ServiceNow context: default new code items to JavaScript.
        if not self.instance.pk and not self.initial.get("language"):
            self.initial["language"] = "javascript"
        # Screenshots attach to a script in the same project.
        scripts = Item.objects.none()
        if self.project:
            scripts = self.project.items.exclude(kind=Item.Kind.IMAGE)
            if self.instance and self.instance.pk:
                scripts = scripts.exclude(pk=self.instance.pk)
        self.fields["related_to"].queryset = scripts
        self.fields["related_to"].label = "Attach to script"
        self.fields["related_to"].help_text = (
            "For screenshots: which script in this project it belongs to."
        )

    def clean(self):
        cleaned = super().clean()
        # Unchecked manual box means auto-detect: discard any typed identifier.
        if not cleaned.get("identifier_is_manual"):
            cleaned["identifier"] = ""
        kind = cleaned.get("kind")
        content = (cleaned.get("content") or "").strip()
        upload = cleaned.get("upload")

        if kind == Item.Kind.IMAGE:
            if not upload and not (self.instance and self.instance.upload):
                raise forms.ValidationError(
                    "A screenshot upload is required for image items. "
                    "Choose a file or paste an image from the clipboard."
                )
            if upload and not upload.name.lower().endswith(ALLOWED_IMAGE_EXTENSIONS):
                raise forms.ValidationError(
                    "Unsupported image type. Allowed: "
                    + ", ".join(ALLOWED_IMAGE_EXTENSIONS)
                )
        elif kind == Item.Kind.XML:
            if not content and not upload and not (self.instance and self.instance.upload):
                raise forms.ValidationError(
                    "Provide the XML either as pasted text or as an uploaded file."
                )
            if upload and not upload.name.lower().endswith(ALLOWED_XML_EXTENSIONS):
                raise forms.ValidationError(
                    "Unsupported file type. Allowed: "
                    + ", ".join(ALLOWED_XML_EXTENSIONS)
                )
        elif kind == Item.Kind.CODE:
            has_any_code = (
                content
                or (cleaned.get("html_content") or "").strip()
                or (cleaned.get("client_content") or "").strip()
                or (cleaned.get("css_content") or "").strip()
            )
            if not has_any_code:
                raise forms.ValidationError(
                    "Paste the code into at least one script field."
                )

        return cleaned
