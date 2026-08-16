import tempfile

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import Item

# 1x1 transparent PNG
TINY_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xfa\xcf"
    b"\xf0\xbf\x1e\x00\x06\x83\x02\x7f\x94\xad\xd0\xeb\x00\x00\x00\x00IEND"
    b"\xaeB`\x82"
)


class VaultTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("huy", password="secret123")
        self.other = User.objects.create_user("other", password="secret123")

    def login(self):
        self.client.login(username="huy", password="secret123")

    def test_list_requires_login(self):
        response = self.client.get(reverse("item_list"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_create_code_item(self):
        self.login()
        response = self.client.post(
            reverse("item_create"),
            {
                "kind": "code",
                "title": "Business rule",
                "language": "javascript",
                "content": "var x = 1;",
                "note": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        item = Item.objects.get(title="Business rule")
        self.assertEqual(item.owner, self.user)

    def test_code_item_requires_content(self):
        self.login()
        response = self.client.post(
            reverse("item_create"),
            {"kind": "code", "title": "Empty", "language": "text", "content": ""},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Item.objects.filter(title="Empty").exists())

    def test_raw_view(self):
        self.login()
        item = Item.objects.create(
            owner=self.user, kind="xml", title="Update set", content="<xml/>"
        )
        response = self.client.get(reverse("item_raw", args=[item.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"<xml/>")
        self.assertIn("text/plain", response["Content-Type"])

    def test_cannot_see_other_users_item(self):
        self.login()
        item = Item.objects.create(
            owner=self.other, kind="code", title="Secret", content="var y;"
        )
        response = self.client.get(reverse("item_detail", args=[item.pk]))
        self.assertEqual(response.status_code, 404)

    def test_search_and_filter(self):
        self.login()
        Item.objects.create(owner=self.user, kind="code", title="Alpha", content="aaa")
        Item.objects.create(owner=self.user, kind="xml", title="Beta", content="bbb")
        response = self.client.get(reverse("item_list"), {"kind": "xml"})
        self.assertContains(response, "Beta")
        self.assertNotContains(response, "Alpha")
        response = self.client.get(reverse("item_list"), {"q": "aaa"})
        self.assertContains(response, "Alpha")

    def test_image_upload_and_protected_media(self):
        self.login()
        with override_settings(MEDIA_ROOT=tempfile.mkdtemp()):
            upload = SimpleUploadedFile("shot.png", TINY_PNG, content_type="image/png")
            response = self.client.post(
                reverse("item_create"),
                {"kind": "image", "title": "Screenshot", "upload": upload,
                 "language": "text", "content": "", "note": ""},
            )
            self.assertEqual(response.status_code, 302)
            item = Item.objects.get(title="Screenshot")

            # Owner can fetch the file through the protected view.
            response = self.client.get(reverse("serve_media", args=[item.upload.name]))
            self.assertEqual(response.status_code, 200)

            # Another user cannot.
            self.client.login(username="other", password="secret123")
            response = self.client.get(reverse("serve_media", args=[item.upload.name]))
            self.assertEqual(response.status_code, 404)

            # Anonymous users get redirected to login.
            self.client.logout()
            response = self.client.get(reverse("serve_media", args=[item.upload.name]))
            self.assertEqual(response.status_code, 302)

    def test_delete_removes_item(self):
        self.login()
        item = Item.objects.create(
            owner=self.user, kind="code", title="Doomed", content="var z;"
        )
        response = self.client.post(reverse("item_delete", args=[item.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Item.objects.filter(pk=item.pk).exists())
