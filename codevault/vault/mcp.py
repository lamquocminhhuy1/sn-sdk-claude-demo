"""MCP tools exposed at /mcp/ (django-mcp-server auto-discovers this module
from every INSTALLED_APPS app - see McpServerConfig.ready()). Each method
below becomes one MCP tool; the method's type hints become its JSON Schema
and its docstring becomes the tool description shown to Claude.

All the actual logic lives in api.py's op_* functions (the same ones the
GET/POST REST API in api.py calls) - this class is just the MCP-shaped
front door onto them, scoped to whichever user authenticated the request
(self.request.user, set by DJANGO_MCP_AUTHENTICATION_CLASSES).
"""

from mcp_server import MCPToolset

from .api import op_create_project, op_get_item, op_list_items, op_list_projects, op_push_item


class CodeVaultTools(MCPToolset):
    def list_projects(self) -> dict:
        """List all projects (repos) stored in this user's CodeVault instance."""
        return op_list_projects(self.request.user)

    def create_project(
        self,
        name: str,
        description: str = "",
        scope_type: str = "global",
        scope_name: str = "",
    ) -> dict:
        """Create a new project in CodeVault, or return the existing one if a
        project with this name already exists (safe to call before pushing
        code without checking first). scope_type is "global" or
        "scoped_app"; scope_name (e.g. x_renin_ccr) is required when
        scope_type is "scoped_app"."""
        return op_create_project(
            self.request.user,
            {"name": name, "description": description, "scope_type": scope_type, "scope_name": scope_name},
        )

    def list_items(self, project_slug: str, q: str = "") -> dict:
        """List the scripts/files stored in one CodeVault project, optionally
        filtered by a search query (matches title or identifier)."""
        return op_list_items(self.request.user, project_slug, q)

    def get_item(self, uid: str) -> dict:
        """Fetch one item's full source code and metadata by its uid (get
        code back out of CodeVault). uid comes from list_items."""
        return op_get_item(self.request.user, uid)

    def push_item(
        self,
        project_slug: str,
        title: str,
        kind: str = "code",
        uid: str | None = None,
        identifier: str | None = None,
        script_type: str | None = None,
        language: str | None = None,
        content: str | None = None,
        html_content: str | None = None,
        client_content: str | None = None,
        css_content: str | None = None,
        note: str | None = None,
        table_name: str | None = None,
        field_name: str | None = None,
        br_order: int | None = None,
        operations: str | None = None,
        condition: str | None = None,
        client_callable: bool | None = None,
        api_endpoint: str | None = None,
        sub_type: str | None = None,
    ) -> dict:
        """Create or update a script/file in a CodeVault project (push code).
        Matches an existing item to update by uid, then by identifier, then
        by (kind + title) - so pushing the same script again updates it in
        place instead of creating a duplicate. kind is "code" or "xml";
        screenshots aren't supported here. script_type is one of
        script_include, business_rule, client_script, ui_page, ui_action,
        ui_macro, scheduled_job, fix_script, rest_api, widget, other.

        Only pass the fields you actually want to set - any field left as
        null keeps the existing item's value untouched (e.g. updating just
        `content` on an existing item leaves its `note` alone). To clear a
        field, pass an empty string for it explicitly."""
        payload = {
            "identifier": identifier,
            "script_type": script_type,
            "language": language,
            "content": content,
            "html_content": html_content,
            "client_content": client_content,
            "css_content": css_content,
            "note": note,
            "table_name": table_name,
            "field_name": field_name,
            "operations": operations,
            "br_order": br_order,
            "condition": condition,
            "client_callable": client_callable,
            "api_endpoint": api_endpoint,
            "sub_type": sub_type,
        }
        payload = {k: v for k, v in payload.items() if v is not None}
        payload["kind"] = kind
        payload["title"] = title
        if uid:
            payload["uid"] = uid
        return op_push_item(self.request.user, project_slug, payload)
