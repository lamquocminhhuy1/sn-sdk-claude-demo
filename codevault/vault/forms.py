from django import forms

from .models import Item, Project

ALLOWED_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")
ALLOWED_XML_EXTENSIONS = (".xml", ".xsd", ".xsl", ".xslt", ".wsdl")


class ProjectForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = ["name", "description"]
        widgets = {
            "name": forms.TextInput(
                attrs={"autofocus": "autofocus", "placeholder": "e.g. Incident auto-assignment"}
            ),
            "description": forms.Textarea(
                attrs={"rows": 3, "placeholder": "What is this project about?"}
            ),
        }


class ItemForm(forms.ModelForm):
    class Meta:
        model = Item
        fields = [
            "kind",
            "script_type",
            "title",
            "identifier",
            "related_to",
            "language",
            "content",
            "upload",
            "note",
        ]
        widgets = {
            "content": forms.Textarea(
                attrs={
                    "rows": 16,
                    "spellcheck": "false",
                    "placeholder": "Paste your code / XML here...",
                }
            ),
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
            if not content:
                raise forms.ValidationError("Paste the source code into the content field.")

        return cleaned
