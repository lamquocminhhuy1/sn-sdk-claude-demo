import tempfile

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import Dependency, Item, Project
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
            {"name": "Incident Auto Assignment", "description": "test"},
        )
        self.assertEqual(response.status_code, 302)
        project = Project.objects.get(name="Incident Auto Assignment")
        self.assertEqual(project.slug, "incident-auto-assignment")

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
