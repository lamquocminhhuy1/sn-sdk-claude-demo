import base64
import hashlib
import json
import re
import tempfile
from urllib.parse import parse_qs, urlencode, urlparse

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import ApiToken, Dependency, Item, Project
from .services import build_dependency_tree, rebuild_project_dependencies

# 1x1 transparent PNG
TINY_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xfa\xcf"
    b"\xf0\xbf\x1e\x00\x06\x83\x02\x7f\x94\xad\xd0\xeb\x00\x00\x00\x00IEND"
    b"\xaeB`\x82"
)


class BaseTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("huy", password="secret123")
        self.other = User.objects.create_user("other", password="secret123")
        self.project = Project.objects.create(owner=self.user, name="Demo Project")

    def login(self):
        self.client.login(username="huy", password="secret123")


class ProjectTests(BaseTestCase):
    def test_list_requires_login(self):
        response = self.client.get(reverse("project_list"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_create_project_generates_slug(self):
        self.login()
        response = self.client.post(
            reverse("project_create"),
            {"name": "Incident Auto Assignment", "description": "test", "scope_type": "global"},
        )
        self.assertEqual(response.status_code, 302)
        project = Project.objects.get(name="Incident Auto Assignment")
        self.assertEqual(project.slug, "incident-auto-assignment")
        self.assertEqual(project.scope_type, "global")
        self.assertFalse(project.is_scoped_app)

    def test_create_scoped_app_project_requires_scope_name(self):
        self.login()
        response = self.client.post(
            reverse("project_create"),
            {"name": "CCR Verification", "scope_type": "scoped_app", "scope_name": ""},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Project.objects.filter(name="CCR Verification").exists())

    def test_create_scoped_app_project_validates_name_format(self):
        self.login()
        response = self.client.post(
            reverse("project_create"),
            {"name": "CCR Verification", "scope_type": "scoped_app", "scope_name": "not a scope name!"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Project.objects.filter(name="CCR Verification").exists())

    def test_create_scoped_app_project_saves_and_lowercases_scope_name(self):
        self.login()
        response = self.client.post(
            reverse("project_create"),
            {"name": "CCR Verification", "scope_type": "scoped_app", "scope_name": "X_Renin_CCR"},
        )
        self.assertEqual(response.status_code, 302)
        project = Project.objects.get(name="CCR Verification")
        self.assertTrue(project.is_scoped_app)
        self.assertEqual(project.scope_name, "x_renin_ccr")

    def test_switching_back_to_global_clears_scope_name(self):
        self.login()
        project = Project.objects.create(
            owner=self.user, name="Was Scoped",
            scope_type="scoped_app", scope_name="x_renin_ccr",
        )
        response = self.client.post(
            reverse("project_edit", args=[project.slug]),
            {"name": "Was Scoped", "scope_type": "global", "scope_name": "x_renin_ccr"},
        )
        self.assertEqual(response.status_code, 302)
        project.refresh_from_db()
        self.assertFalse(project.is_scoped_app)
        self.assertEqual(project.scope_name, "")

    def test_duplicate_names_get_unique_slugs(self):
        p1 = Project.objects.create(owner=self.user, name="Same Name")
        p2 = Project.objects.create(owner=self.user, name="Same Name")
        self.assertNotEqual(p1.slug, p2.slug)

    def test_cannot_see_other_users_project(self):
        self.login()
        theirs = Project.objects.create(owner=self.other, name="Theirs")
        response = self.client.get(reverse("project_detail", args=[theirs.slug]))
        self.assertEqual(response.status_code, 404)

    def test_delete_project_removes_items(self):
        self.login()
        Item.objects.create(
            owner=self.user, project=self.project, kind="code",
            title="X", content="var x;",
        )
        response = self.client.post(
            reverse("project_delete", args=[self.project.slug])
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Project.objects.filter(pk=self.project.pk).exists())
        self.assertFalse(Item.objects.exists())


class ItemTests(BaseTestCase):
    def test_create_code_item_in_project(self):
        self.login()
        response = self.client.post(
            reverse("item_create", args=[self.project.slug]),
            {
                "kind": "code",
                "script_type": "business_rule",
                "title": "BR test",
                "identifier": "",
                "language": "javascript",
                "content": "var x = 1;",
                "note": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        item = Item.objects.get(title="BR test")
        self.assertEqual(item.project, self.project)

    def test_code_item_requires_content(self):
        self.login()
        response = self.client.post(
            reverse("item_create", args=[self.project.slug]),
            {"kind": "code", "script_type": "other", "title": "Empty",
             "language": "text", "content": ""},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Item.objects.filter(title="Empty").exists())

    def test_identifier_auto_detected_from_class_create(self):
        self.login()
        self.client.post(
            reverse("item_create", args=[self.project.slug]),
            {
                "kind": "code",
                "script_type": "script_include",
                "title": "My Utils Script Include",
                "identifier": "",
                "language": "javascript",
                "content": "var CalcUtils = Class.create();\nCalcUtils.prototype = {};",
            },
        )
        item = Item.objects.get(title="My Utils Script Include")
        self.assertEqual(item.identifier, "CalcUtils")

    def test_manual_identifier_is_kept(self):
        self.login()
        self.client.post(
            reverse("item_create", args=[self.project.slug]),
            {
                "kind": "code", "script_type": "script_include",
                "title": "Custom named", "identifier": "MySpecialName",
                "identifier_is_manual": "on", "language": "javascript",
                "content": "var CalcUtils = Class.create();",
            },
        )
        item = Item.objects.get(title="Custom named")
        self.assertEqual(item.identifier, "MySpecialName")
        self.assertTrue(item.identifier_is_manual)

    def test_typed_identifier_discarded_when_manual_unchecked(self):
        self.login()
        self.client.post(
            reverse("item_create", args=[self.project.slug]),
            {
                "kind": "code", "script_type": "script_include",
                "title": "Auto detect wins", "identifier": "TypedButNotManual",
                "language": "javascript",
                "content": "var CalcUtils = Class.create();",
            },
        )
        item = Item.objects.get(title="Auto detect wins")
        self.assertEqual(item.identifier, "CalcUtils")
        self.assertFalse(item.identifier_is_manual)

    def test_auto_identifier_recomputed_on_edit(self):
        self.login()
        item = Item.objects.create(
            owner=self.user, project=self.project, kind="code",
            title="SI", content="var OldName = Class.create();",
            identifier="OldName",
        )
        self.client.post(
            reverse("item_edit", args=[item.uid]),
            {
                "kind": "code", "script_type": "script_include",
                "title": "SI", "identifier": "OldName",
                "language": "javascript",
                "content": "var NewName = Class.create();",
            },
        )
        item.refresh_from_db()
        self.assertEqual(item.identifier, "NewName")

    def test_filter_by_script_type(self):
        self.login()
        Item.objects.create(
            owner=self.user, project=self.project, kind="code",
            title="The BR", content="var a;", script_type="business_rule",
        )
        Item.objects.create(
            owner=self.user, project=self.project, kind="code",
            title="The SI", content="var b;", script_type="script_include",
        )
        response = self.client.get(
            reverse("project_detail", args=[self.project.slug]),
            {"stype": "business_rule"},
        )
        self.assertContains(response, "The BR")
        self.assertNotContains(response, "The SI")

    def test_client_script_captures_servicenow_fields(self):
        self.login()
        self.client.post(
            reverse("item_create", args=[self.project.slug]),
            {
                "kind": "code", "script_type": "client_script",
                "title": "Validate form", "language": "javascript",
                "content": "function onChange(control, oldValue, newValue) {}",
                "sub_type": "onchange", "table_name": "incident",
                "field_name": "assignment_group",
            },
        )
        item = Item.objects.get(title="Validate form")
        self.assertEqual(item.sub_type, "onchange")
        self.assertEqual(item.table_name, "incident")
        self.assertEqual(item.field_name, "assignment_group")

    def test_ui_page_multi_part_code(self):
        self.login()
        self.client.post(
            reverse("item_create", args=[self.project.slug]),
            {
                "kind": "code", "script_type": "ui_page",
                "title": "Report page", "language": "javascript",
                "content": "",
                "html_content": "<j:jelly>hello</j:jelly>",
                "client_content": "var x = 1;",
            },
        )
        item = Item.objects.get(title="Report page")
        self.assertTrue(item.has_text)
        labels = [p[1] for p in item.code_parts()]
        self.assertEqual(labels, ["HTML (Jelly)", "Client Script"])

    def test_dependency_detected_in_client_content(self):
        si = Item.objects.create(
            owner=self.user, project=self.project, kind="code",
            script_type="script_include", title="CalcUtils SI",
            content="var CalcUtils = Class.create();", identifier="CalcUtils",
        )
        page = Item.objects.create(
            owner=self.user, project=self.project, kind="code",
            script_type="ui_page", title="Page",
            client_content="var u = new CalcUtils();",
        )
        rebuild_project_dependencies(self.project)
        self.assertEqual(page.depends_on(), [si])

    def test_usage_direction_puts_script_include_at_root(self):
        si = Item.objects.create(
            owner=self.user, project=self.project, kind="code",
            title="SI", content="var CalcUtils = Class.create();",
            identifier="CalcUtils",
        )
        br = Item.objects.create(
            owner=self.user, project=self.project, kind="code",
            title="BR", content="new CalcUtils().run();",
        )
        rebuild_project_dependencies(self.project)
        roots, _ = build_dependency_tree(self.project, direction="usage")
        self.assertEqual([r["item"] for r in roots], [si])
        self.assertEqual([c["item"] for c in roots[0]["children"]], [br])

    def test_long_content_and_metadata_fields_save(self):
        # Real ServiceNow scripts (esp. widgets with server+client+HTML+CSS
        # combined) routinely exceed 10k characters; content/html_content/
        # client_content/css_content/note/condition are TextField (already
        # unbounded), and title/identifier/table_name/field_name/operations/
        # api_endpoint were widened from small CharFields to max_length=10000.
        self.login()
        long_code = "var x = 1; // padding\n" * 600  # ~13,800 chars
        long_title = "T" * 9000
        long_identifier = "I" * 9000
        response = self.client.post(
            reverse("item_create", args=[self.project.slug]),
            {
                "kind": "code", "script_type": "script_include",
                "title": long_title,
                "identifier": long_identifier, "identifier_is_manual": "on",
                "language": "javascript", "content": long_code,
            },
        )
        self.assertEqual(response.status_code, 302)
        item = Item.objects.get(identifier=long_identifier)
        self.assertEqual(len(item.title), 9000)
        # Django's form CharField strips leading/trailing whitespace, so
        # compare against the stripped value rather than the raw padding.
        self.assertEqual(item.content, long_code.strip())
        self.assertGreater(len(item.content), 10000)

    def test_raw_view(self):
        self.login()
        item = Item.objects.create(
            owner=self.user, project=self.project, kind="xml",
            title="Update set", content="<xml/>",
        )
        response = self.client.get(reverse("item_raw", args=[item.uid]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"<xml/>")

    def test_screenshot_attaches_to_script(self):
        self.login()
        script = Item.objects.create(
            owner=self.user, project=self.project, kind="code",
            title="Script", content="var a;",
        )
        with override_settings(MEDIA_ROOT=tempfile.mkdtemp()):
            upload = SimpleUploadedFile("shot.png", TINY_PNG, content_type="image/png")
            response = self.client.post(
                reverse("item_create", args=[self.project.slug]),
                {"kind": "image", "script_type": "other", "title": "Shot",
                 "related_to": script.pk, "upload": upload,
                 "language": "text", "content": "", "note": ""},
            )
            self.assertEqual(response.status_code, 302)
            shot = Item.objects.get(title="Shot")
            self.assertEqual(shot.related_to, script)
            self.assertIn(shot, list(script.screenshots))

    def test_protected_media(self):
        self.login()
        with override_settings(MEDIA_ROOT=tempfile.mkdtemp()):
            upload = SimpleUploadedFile("shot.png", TINY_PNG, content_type="image/png")
            self.client.post(
                reverse("item_create", args=[self.project.slug]),
                {"kind": "image", "script_type": "other", "title": "Screenshot",
                 "upload": upload, "language": "text", "content": "", "note": ""},
            )
            item = Item.objects.get(title="Screenshot")

            response = self.client.get(reverse("serve_media", args=[item.upload.name]))
            self.assertEqual(response.status_code, 200)

            self.client.login(username="other", password="secret123")
            response = self.client.get(reverse("serve_media", args=[item.upload.name]))
            self.assertEqual(response.status_code, 404)

            self.client.logout()
            response = self.client.get(reverse("serve_media", args=[item.upload.name]))
            self.assertEqual(response.status_code, 302)


class DependencyTests(BaseTestCase):
    def make_script(self, title, content, identifier="", script_type="other"):
        return Item.objects.create(
            owner=self.user, project=self.project, kind="code",
            title=title, content=content, identifier=identifier,
            script_type=script_type,
        )

    def test_detects_script_include_usage(self):
        si = self.make_script(
            "CalcUtils SI", "var CalcUtils = Class.create();",
            identifier="CalcUtils", script_type="script_include",
        )
        br = self.make_script(
            "Assignment BR", "var u = new CalcUtils().getOpenIncidents(dept);",
            script_type="business_rule",
        )
        page = self.make_script(
            "Report UI Page", "var data = new CalcUtils().getOpenIncidents('IT');",
            script_type="ui_page",
        )
        unrelated = self.make_script("Other", "gs.info('hello');")

        rebuild_project_dependencies(self.project)

        self.assertEqual(set(si.used_by()), {br, page})
        self.assertEqual(br.depends_on(), [si])
        self.assertEqual(unrelated.depends_on(), [])

    def test_no_false_match_on_substring(self):
        si = self.make_script("SI", "var Calc = Class.create();", identifier="Calc")
        other = self.make_script("Other", "var x = CalcUtilsHelper.run();")
        rebuild_project_dependencies(self.project)
        self.assertEqual(other.depends_on(), [])
        self.assertEqual(si.used_by(), [])

    def test_dependencies_rebuilt_on_save_through_view(self):
        self.login()
        si = self.make_script(
            "SI", "var CalcUtils = Class.create();", identifier="CalcUtils"
        )
        self.client.post(
            reverse("item_create", args=[self.project.slug]),
            {"kind": "code", "script_type": "business_rule", "title": "BR",
             "identifier": "", "language": "javascript",
             "content": "new CalcUtils().run();"},
        )
        br = Item.objects.get(title="BR")
        self.assertEqual(br.depends_on(), [si])

    def test_tree_roots_and_standalone(self):
        si = self.make_script(
            "SI", "var CalcUtils = Class.create();", identifier="CalcUtils"
        )
        br = self.make_script("BR", "new CalcUtils().run();")
        lonely = self.make_script("Lonely", "gs.info('x');")
        rebuild_project_dependencies(self.project)

        roots, standalone = build_dependency_tree(self.project)
        self.assertEqual([r["item"] for r in roots], [br])
        self.assertEqual([c["item"] for c in roots[0]["children"]], [si])
        self.assertEqual(standalone, [lonely])

    def test_cycle_does_not_crash(self):
        a = self.make_script("A", "B_Helper.run(); var A_Helper = {};", identifier="A_Helper")
        b = self.make_script("B", "A_Helper.run(); var B_Helper = {};", identifier="B_Helper")
        rebuild_project_dependencies(self.project)
        roots, standalone = build_dependency_tree(self.project)
        rendered = [r["item"] for r in roots]
        self.assertTrue(a in rendered or b in rendered)

    def test_deps_page_renders(self):
        self.login()
        self.make_script(
            "SI", "var CalcUtils = Class.create();", identifier="CalcUtils"
        )
        self.make_script("BR", "new CalcUtils().run();")
        rebuild_project_dependencies(self.project)
        response = self.client.get(
            reverse("project_dependencies", args=[self.project.slug])
        )
        self.assertContains(response, "Dependency tree")
        self.assertContains(response, "CalcUtils")

    def test_deleting_item_removes_edges(self):
        self.login()
        si = self.make_script(
            "SI", "var CalcUtils = Class.create();", identifier="CalcUtils"
        )
        self.make_script("BR", "new CalcUtils().run();")
        rebuild_project_dependencies(self.project)
        self.assertEqual(Dependency.objects.count(), 1)
        self.client.post(reverse("item_delete", args=[si.uid]))
        self.assertEqual(Dependency.objects.count(), 0)


class ApiTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.token = ApiToken.objects.create(owner=self.user)
        self.auth = {"HTTP_AUTHORIZATION": "Bearer " + self.token.key}

    def post_json(self, url, data, **extra):
        extra.update(self.auth)
        return self.client.post(
            url, data=json.dumps(data), content_type="application/json", **extra
        )

    # --- auth -------------------------------------------------------

    def test_missing_token_returns_401(self):
        response = self.client.get(reverse("api_projects"))
        self.assertEqual(response.status_code, 401)

    def test_wrong_token_returns_401(self):
        response = self.client.get(
            reverse("api_projects"), HTTP_AUTHORIZATION="Bearer not-a-real-token"
        )
        self.assertEqual(response.status_code, 401)

    def test_token_only_sees_its_owners_projects(self):
        Project.objects.create(owner=self.other, name="Not Mine")
        response = self.client.get(reverse("api_projects"), **self.auth)
        names = [p["name"] for p in response.json()["projects"]]
        self.assertIn("Demo Project", names)
        self.assertNotIn("Not Mine", names)

    # --- projects -----------------------------------------------------

    def test_create_project_via_api(self):
        response = self.post_json(
            reverse("api_projects"),
            {"name": "API Project", "scope_type": "scoped_app", "scope_name": "X_Renin_CCR"},
        )
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertTrue(body["created"])
        self.assertEqual(body["project"]["scope_name"], "x_renin_ccr")
        self.assertTrue(Project.objects.filter(owner=self.user, name="API Project").exists())

    def test_create_project_is_idempotent_by_name(self):
        response1 = self.post_json(reverse("api_projects"), {"name": "Repeat"})
        response2 = self.post_json(reverse("api_projects"), {"name": "Repeat"})
        self.assertEqual(response1.status_code, 201)
        self.assertEqual(response2.status_code, 200)
        self.assertFalse(response2.json()["created"])
        self.assertEqual(Project.objects.filter(owner=self.user, name="Repeat").count(), 1)

    def test_create_project_without_name_fails(self):
        response = self.post_json(reverse("api_projects"), {})
        self.assertEqual(response.status_code, 400)

    # --- items: push (create + upsert) ---------------------------------

    def test_push_creates_item(self):
        response = self.post_json(
            reverse("api_items", args=[self.project.slug]),
            {
                "kind": "code",
                "script_type": "script_include",
                "title": "CalcUtils",
                "identifier": "CalcUtils",
                "content": "var CalcUtils = Class.create();",
            },
        )
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertTrue(body["created"])
        self.assertEqual(body["item"]["identifier"], "CalcUtils")
        item = Item.objects.get(project=self.project, title="CalcUtils")
        self.assertEqual(item.content, "var CalcUtils = Class.create();")
        self.assertTrue(item.identifier_is_manual)

    def test_pushing_same_identifier_updates_instead_of_duplicating(self):
        self.post_json(
            reverse("api_items", args=[self.project.slug]),
            {"kind": "code", "title": "CalcUtils", "identifier": "CalcUtils", "content": "v1"},
        )
        response = self.post_json(
            reverse("api_items", args=[self.project.slug]),
            {"kind": "code", "title": "CalcUtils", "identifier": "CalcUtils", "content": "v2"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["created"])
        self.assertEqual(Item.objects.filter(project=self.project, identifier="CalcUtils").count(), 1)
        self.assertEqual(
            Item.objects.get(project=self.project, identifier="CalcUtils").content, "v2"
        )

    def test_push_rebuilds_dependencies(self):
        self.post_json(
            reverse("api_items", args=[self.project.slug]),
            {"kind": "code", "title": "CalcUtils SI", "identifier": "CalcUtils", "content": "var CalcUtils = Class.create();"},
        )
        self.post_json(
            reverse("api_items", args=[self.project.slug]),
            {"kind": "code", "title": "Assignment BR", "content": "new CalcUtils().run();"},
        )
        self.assertEqual(Dependency.objects.filter(from_item__project=self.project).count(), 1)

    def test_push_without_title_fails(self):
        response = self.post_json(
            reverse("api_items", args=[self.project.slug]), {"kind": "code"}
        )
        self.assertEqual(response.status_code, 400)

    def test_push_image_kind_rejected(self):
        response = self.post_json(
            reverse("api_items", args=[self.project.slug]),
            {"kind": "image", "title": "Screenshot"},
        )
        self.assertEqual(response.status_code, 400)

    def test_push_to_unknown_project_returns_404(self):
        response = self.post_json(
            reverse("api_items", args=["no-such-project"]), {"kind": "code", "title": "X"}
        )
        self.assertEqual(response.status_code, 404)

    # --- items: read -----------------------------------------------------

    def test_list_items_and_get_detail(self):
        item = Item.objects.create(
            owner=self.user, project=self.project, kind="code",
            title="Helper", content="var x = 1;",
        )
        list_response = self.client.get(
            reverse("api_items", args=[self.project.slug]), **self.auth
        )
        self.assertEqual(list_response.status_code, 200)
        uids = [i["uid"] for i in list_response.json()["items"]]
        self.assertIn(str(item.uid), uids)

        detail_response = self.client.get(
            reverse("api_item_detail", args=[item.uid]), **self.auth
        )
        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(detail_response.json()["item"]["content"], "var x = 1;")

    def test_cannot_read_another_users_item(self):
        item = Item.objects.create(
            owner=self.other,
            project=Project.objects.create(owner=self.other, name="Other Project"),
            kind="code", title="Secret", content="x",
        )
        response = self.client.get(reverse("api_item_detail", args=[item.uid]), **self.auth)
        self.assertEqual(response.status_code, 404)

    # --- token management page ------------------------------------------

    def test_api_access_page_requires_login(self):
        response = self.client.get(reverse("api_access"))
        self.assertEqual(response.status_code, 302)

    def test_api_access_page_shows_token(self):
        self.login()
        response = self.client.get(reverse("api_access"))
        self.assertContains(response, self.token.key)

    def test_regenerate_token_changes_key(self):
        self.login()
        old_key = self.token.key
        self.client.post(reverse("api_token_regenerate"))
        self.token.refresh_from_db()
        self.assertNotEqual(self.token.key, old_key)
        # the old key must stop working immediately
        response = self.client.get(
            reverse("api_projects"), HTTP_AUTHORIZATION="Bearer " + old_key
        )
        self.assertEqual(response.status_code, 401)


def pkce_pair():
    verifier = base64.urlsafe_b64encode(b"x" * 40).rstrip(b"=").decode("ascii")
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
    return verifier, challenge


MCP_ACCEPT = "application/json, text/event-stream"


class RemoteMcpTests(BaseTestCase):
    """The library-based stack (django-mcp-server + django-oauth-toolkit)
    serving /mcp/ for claude.ai's custom connector. Covers the discovery
    metadata, the full OAuth 2.0 + PKCE + dynamic client registration
    dance (mirroring exactly what claude.ai's connector does), and the
    tool calls themselves - plus the two production bugs already found
    and patched by hand once (GET/DELETE must not require auth; a shared
    "oauth2_provider" namespace across two include()s breaks reverse())."""

    REDIRECT_URI = "https://claude.ai/api/mcp/auth_callback"

    # -------------------------------------------------------------- setup

    def register_client(self, **extra):
        # token_endpoint_auth_method: "none" is what makes this a public,
        # PKCE-only client (no client_secret) - the whole point of this
        # flow. Passed explicitly here so most tests exercise a known-clean
        # public client regardless of the server's own default; see
        # test_register_without_auth_method_defaults_to_public for what
        # actually happens when a client omits it, as claude.ai's connector
        # does in production (CodeVaultDCRView in vault/dcr_views.py).
        payload = dict(
            {"client_name": "claude.ai", "redirect_uris": [self.REDIRECT_URI], "token_endpoint_auth_method": "none"},
            **extra,
        )
        response = self.client.post(
            reverse("oauth2_provider:dcr-register"), data=json.dumps(payload), content_type="application/json"
        )
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()

    def _get_code(self, client, challenge, state="xyz"):
        self.login()
        params = {
            "response_type": "code",
            "client_id": client["client_id"],
            "redirect_uri": self.REDIRECT_URI,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "scope": "codevault",
        }
        get_response = self.client.get(reverse("oauth2_provider:authorize"), params)
        self.assertEqual(get_response.status_code, 200, get_response.content)
        # Submit exactly the hidden fields the rendered consent form carries
        # (redirect_uri, scope, client_id, state, response_type, code_challenge,
        # code_challenge_method...), like a real browser submission would,
        # rather than reconstructing our own copy of them.
        hidden = dict(re.findall(r'name="(\w+)"\s+value="([^"]*)"', get_response.content.decode()))
        response = self.client.post(
            reverse("oauth2_provider:authorize"), dict(hidden, allow="Authorize"), follow=False
        )
        self.assertEqual(response.status_code, 302, response.content)
        qs = parse_qs(urlparse(response.url).query)
        self.assertEqual(qs["state"][0], state)
        return qs["code"][0]

    def post_token(self, data):
        # oauthlib's request-body parsing (behind TokenView) only handles
        # application/x-www-form-urlencoded, per OAuth 2.0's own spec for
        # this endpoint - Django's test Client.post() defaults a plain dict
        # to multipart/form-data, which oauthlib can't parse (client_id
        # etc. arrive empty, so a valid client 401s as "invalid_client").
        # A real client (curl, requests, claude.ai) sends urlencoded form
        # data by default, so this only matters for the test client.
        return self.client.post(
            reverse("oauth2_provider:token"), urlencode(data), content_type="application/x-www-form-urlencoded"
        )

    def get_access_token(self, client=None, verifier=None, challenge=None):
        if client is None:
            client = self.register_client()
        if verifier is None:
            verifier, challenge = pkce_pair()
        code = self._get_code(client, challenge)
        response = self.post_token(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.REDIRECT_URI,
                "client_id": client["client_id"],
                "code_verifier": verifier,
            }
        )
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def rpc(self, method, params=None, msg_id=1, token=None):
        body = {"jsonrpc": "2.0", "method": method}
        if msg_id is not None:
            body["id"] = msg_id
        if params is not None:
            body["params"] = params
        headers = {"HTTP_ACCEPT": MCP_ACCEPT}
        if token:
            headers["HTTP_AUTHORIZATION"] = "Bearer " + token
        return self.client.post(
            reverse("mcp_server_streamable_http_endpoint"),
            data=json.dumps(body),
            content_type="application/json",
            **headers,
        )

    def call_tool(self, name, arguments, token):
        response = self.rpc("tools/call", {"name": name, "arguments": arguments}, token=token)
        body = response.json()
        self.assertNotIn("error", body, body)
        return response, json.loads(body["result"]["content"][0]["text"])

    # ------------------------------------------------------ metadata / CORS

    def test_protected_resource_metadata_points_at_mcp(self):
        response = self.client.get("/.well-known/oauth-protected-resource")
        body = response.json()
        self.assertTrue(body["resource"].endswith("/mcp/"))
        self.assertEqual(len(body["authorization_servers"]), 1)

    def test_authorization_server_metadata_has_all_endpoints(self):
        # Regression test: mounting oauth2_provider's urls at two prefixes
        # under the same namespace made reverse() silently drop these.
        response = self.client.get("/.well-known/oauth-authorization-server")
        body = response.json()
        for key in ["authorization_endpoint", "token_endpoint", "registration_endpoint"]:
            self.assertIn(key, body, body)
        self.assertIn("S256", body["code_challenge_methods_supported"])
        self.assertIn("none", body["token_endpoint_auth_methods_supported"])

    def test_protected_resource_metadata_also_served_at_mcp_suffixed_path(self):
        # RFC 9728 path-insertion (and claude.ai's client, observed live)
        # derives /.well-known/oauth-protected-resource/mcp from the
        # resource path (/mcp/) instead of using the WWW-Authenticate hint.
        response = self.client.get("/.well-known/oauth-protected-resource/mcp")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["resource"].endswith("/mcp/"))

    def test_authorization_server_metadata_also_served_at_mcp_suffixed_path(self):
        response = self.client.get("/.well-known/oauth-authorization-server/mcp")
        self.assertEqual(response.status_code, 200)
        self.assertIn("token_endpoint", response.json())

    def test_metadata_advertises_https_behind_a_tls_terminating_proxy(self):
        # Regression test for a real production failure: PythonAnywhere
        # terminates TLS at its proxy and forwards plain HTTP with the
        # original scheme in X-Forwarded-Proto. Without
        # SECURE_PROXY_SSL_HEADER, build_absolute_uri() advertises http://
        # endpoints in both discovery documents, and claude.ai's connector
        # refuses to run an authorization code flow against a non-HTTPS
        # authorization server.
        proxied = {"HTTP_X_FORWARDED_PROTO": "https"}

        resource = self.client.get("/.well-known/oauth-protected-resource", **proxied).json()
        self.assertTrue(resource["resource"].startswith("https://"), resource)
        for server in resource["authorization_servers"]:
            self.assertTrue(server.startswith("https://"), resource)

        server_metadata = self.client.get("/.well-known/oauth-authorization-server", **proxied).json()
        for key in ["issuer", "authorization_endpoint", "token_endpoint", "registration_endpoint"]:
            self.assertTrue(server_metadata[key].startswith("https://"), server_metadata)

    def test_registration_response_uses_https_behind_a_tls_terminating_proxy(self):
        response = self.client.post(
            reverse("oauth2_provider:dcr-register"),
            data=json.dumps({"client_name": "claude.ai", "redirect_uris": [self.REDIRECT_URI]}),
            content_type="application/json",
            HTTP_X_FORWARDED_PROTO="https",
        )
        self.assertTrue(response.json()["registration_client_uri"].startswith("https://"), response.content)

    def test_token_response_carries_no_store_cache_headers(self):
        token = self.get_access_token()
        response = self.post_token(
            {"grant_type": "refresh_token", "refresh_token": token["refresh_token"], "client_id": "bogus"}
        )
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertEqual(response["Pragma"], "no-cache")

    # ------------------------------------------------ dynamic registration

    def test_register_requires_redirect_uris(self):
        response = self.client.post(
            reverse("oauth2_provider:dcr-register"),
            data=json.dumps({"client_name": "x"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    def test_register_with_auth_method_none_creates_public_client(self):
        data = self.register_client(token_endpoint_auth_method="none")
        self.assertEqual(data["token_endpoint_auth_method"], "none")
        self.assertNotIn("client_secret", data)

    def test_register_without_auth_method_defaults_to_public(self):
        # Regression test for a real production failure: claude.ai's
        # connector registers without token_endpoint_auth_method at all.
        # django-oauth-toolkit's stock DynamicClientRegistrationView
        # defaults an omitted field to "client_secret_basic" (confidential),
        # and claude.ai never sends the resulting client_secret back at the
        # token endpoint - every token exchange 401s with invalid_client
        # even though registration, login and consent all succeed.
        # CodeVaultDCRView (vault/dcr_views.py) defaults omitted requests to
        # "none" (public, PKCE-only) instead.
        response = self.client.post(
            reverse("oauth2_provider:dcr-register"),
            data=json.dumps({"client_name": "claude.ai", "redirect_uris": [self.REDIRECT_URI]}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        data = response.json()
        self.assertEqual(data["token_endpoint_auth_method"], "none")
        self.assertNotIn("client_secret", data)

        # And the resulting client can actually complete a token exchange
        # with nothing but PKCE, exactly like claude.ai's connector does.
        verifier, challenge = pkce_pair()
        code = self._get_code(data, challenge)
        token_response = self.post_token(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.REDIRECT_URI,
                "client_id": data["client_id"],
                "code_verifier": verifier,
            }
        )
        self.assertEqual(token_response.status_code, 200, token_response.content)

    # ---------------------------------------------------------- authorize

    def test_authorize_without_login_redirects_to_login(self):
        client = self.register_client()
        _, challenge = pkce_pair()
        response = self.client.get(
            reverse("oauth2_provider:authorize"),
            {
                "response_type": "code",
                "client_id": client["client_id"],
                "redirect_uri": self.REDIRECT_URI,
                "state": "xyz",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_authorize_rejects_unregistered_redirect_uri(self):
        client = self.register_client()
        self.login()
        _, challenge = pkce_pair()
        response = self.client.get(
            reverse("oauth2_provider:authorize"),
            {
                "response_type": "code",
                "client_id": client["client_id"],
                "redirect_uri": "https://evil.example.com/callback",
                "state": "xyz",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
        )
        self.assertEqual(response.status_code, 400)

    # --------------------------------------------------- full token dance

    def test_full_pkce_flow_then_calls_mcp(self):
        tokens = self.get_access_token()
        self.assertEqual(tokens["token_type"], "Bearer")

        response = self.rpc("tools/list", token=tokens["access_token"])
        self.assertEqual(response.status_code, 200)
        names = [t["name"] for t in response.json()["result"]["tools"]]
        for expected in ["list_projects", "create_project", "list_items", "get_item", "push_item"]:
            self.assertIn(expected, names)

    def test_code_is_single_use(self):
        client = self.register_client()
        verifier, challenge = pkce_pair()
        code = self._get_code(client, challenge)
        args = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.REDIRECT_URI,
            "client_id": client["client_id"],
            "code_verifier": verifier,
        }
        first = self.post_token(args)
        second = self.post_token(args)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 400)

    def test_wrong_code_verifier_rejected(self):
        client = self.register_client()
        _, challenge = pkce_pair()
        code = self._get_code(client, challenge)
        response = self.post_token(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.REDIRECT_URI,
                "client_id": client["client_id"],
                "code_verifier": "wrong-verifier",
            }
        )
        self.assertEqual(response.status_code, 400)

    def test_refresh_token_flow(self):
        client = self.register_client()
        first = self.get_access_token(client=client)
        refreshed = self.post_token(
            {"grant_type": "refresh_token", "refresh_token": first["refresh_token"], "client_id": client["client_id"]}
        )
        self.assertEqual(refreshed.status_code, 200)
        self.assertNotEqual(refreshed.json()["access_token"], first["access_token"])

    # -------------------------------------------------------- /mcp/ itself

    def test_post_without_token_401s_with_www_authenticate(self):
        response = self.rpc("tools/list")
        self.assertEqual(response.status_code, 401)
        self.assertIn("WWW-Authenticate", response)

    def test_post_with_garbage_token_401s(self):
        response = self.rpc("tools/list", token="not-a-real-token")
        self.assertEqual(response.status_code, 401)

    def test_get_without_auth_is_not_blocked_by_permissions(self):
        # claude.ai's connector opens the GET SSE stream without the Bearer
        # token it just obtained via OAuth - GET must never depend on auth.
        # Deliberately NOT sending the "text/event-stream" Accept header a
        # real SSE-capable client would: with it, the underlying mcp SDK
        # actually opens a live stream and blocks waiting for the far end
        # to disconnect, which Django's synchronous test client can never
        # do - it would hang this test forever. Without it, the SDK's
        # Accept-header check rejects fast (406) before reaching that
        # code path - still enough to prove the permission check (401)
        # isn't what's blocking the request.
        response = self.client.get(reverse("mcp_server_streamable_http_endpoint"))
        self.assertNotEqual(response.status_code, 401)

    def test_delete_without_auth_is_not_blocked_by_permissions(self):
        response = self.client.delete(reverse("mcp_server_streamable_http_endpoint"))
        self.assertNotEqual(response.status_code, 401)

    def test_api_token_also_authenticates_mcp(self):
        # Claude Code / Desktop's local MCP client authenticates with a
        # plain ApiToken instead of doing the OAuth dance.
        token = ApiToken.objects.create(owner=self.user)
        response = self.rpc("tools/list", token=token.key)
        self.assertEqual(response.status_code, 200)
        names = [t["name"] for t in response.json()["result"]["tools"]]
        self.assertIn("list_projects", names)

    # --------------------------------------------------------------- tools

    def test_call_list_projects(self):
        token = self.get_access_token()["access_token"]
        _, data = self.call_tool("list_projects", {}, token)
        names = [p["name"] for p in data["projects"]]
        self.assertIn("Demo Project", names)

    def test_call_create_project_then_push_and_get_item(self):
        token = self.get_access_token()["access_token"]
        _, created = self.call_tool(
            "create_project",
            {"name": "MCP Remote Project", "scope_type": "scoped_app", "scope_name": "x_mcp_remote"},
            token,
        )
        self.assertTrue(created["created"])
        slug = created["project"]["slug"]

        _, pushed = self.call_tool(
            "push_item",
            {
                "project_slug": slug,
                "kind": "code",
                "script_type": "script_include",
                "title": "RemoteUtils",
                "identifier": "RemoteUtils",
                "content": "var RemoteUtils = Class.create();",
            },
            token,
        )
        self.assertTrue(pushed["created"])
        uid = pushed["item"]["uid"]

        _, fetched = self.call_tool("get_item", {"uid": uid}, token)
        self.assertEqual(fetched["item"]["content"], "var RemoteUtils = Class.create();")

        # pushing again with the same identifier updates instead of duplicating
        _, pushed_again = self.call_tool(
            "push_item",
            {"project_slug": slug, "title": "RemoteUtils", "identifier": "RemoteUtils", "content": "v2"},
            token,
        )
        self.assertFalse(pushed_again["created"])
        self.assertEqual(Item.objects.filter(project__slug=slug, identifier="RemoteUtils").count(), 1)

    def test_push_item_omitted_field_does_not_clear_existing_value(self):
        token = self.get_access_token()["access_token"]
        self.call_tool(
            "create_project", {"name": "Partial Update Project"}, token
        )
        self.call_tool(
            "push_item",
            {
                "project_slug": "partial-update-project",
                "title": "PartialUtils",
                "identifier": "PartialUtils",
                "content": "var PartialUtils = Class.create();",
                "note": "original note",
            },
            token,
        )
        _, updated = self.call_tool(
            "push_item",
            {"project_slug": "partial-update-project", "title": "PartialUtils", "identifier": "PartialUtils", "content": "v2"},
            token,
        )
        self.assertEqual(updated["item"]["content"], "v2")
        self.assertEqual(updated["item"]["note"], "original note")

    def test_call_unknown_tool_is_isError_not_transport_error(self):
        token = self.get_access_token()["access_token"]
        response = self.rpc("tools/call", {"name": "no_such_tool", "arguments": {}}, token=token)
        body = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(body["result"]["isError"])

    def test_cross_user_isolation(self):
        Project.objects.create(owner=self.other, name="Not Mine")
        token = self.get_access_token()["access_token"]
        _, data = self.call_tool("list_projects", {}, token)
        names = [p["name"] for p in data["projects"]]
        self.assertNotIn("Not Mine", names)
