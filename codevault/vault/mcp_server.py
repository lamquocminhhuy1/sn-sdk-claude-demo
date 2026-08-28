"""A remote MCP server, reachable at /mcp/<token>/, for claude.ai's
"Add custom connector" (Settings -> Connectors -> Add custom connector ->
Remote MCP server URL). This is a second front door onto the exact same
operations as api.py's HTTP API - see op_* in that module - just speaking
MCP's JSON-RPC shape instead of plain REST.

Auth: the token is the URL path segment itself (matched against
ApiToken.key), because claude.ai's custom-connector dialog offers no field
for a custom header - only a URL (and optional OAuth, which this doesn't
implement). Treat this URL exactly like a password: whoever has it has
full read/write access to that user's CodeVault. Regenerate the token from
/api-access/ if it leaks; that immediately invalidates the old URL.

This implements the MCP Streamable HTTP transport in "stateless, JSON
response" mode: no Mcp-Session-Id is issued or required, and every
response is returned as a single direct JSON body rather than an SSE
stream. This instance's tools are quick DB reads/writes with no
server-initiated messages, so no session state or push channel is needed.
"""

import json

from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .api import ApiError, authenticate_token, op_create_project, op_get_item, op_list_items, op_list_projects, op_push_item

SERVER_INFO = {"name": "codevault-mcp-remote", "version": "1.0.0"}
SUPPORTED_PROTOCOL_VERSIONS = ["2025-06-18", "2025-03-26", "2024-11-05"]
DEFAULT_PROTOCOL_VERSION = "2025-06-18"

TOOLS = [
    {
        "name": "list_projects",
        "description": "List all projects (repos) stored in this user's CodeVault instance.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "create_project",
        "description": (
            "Create a new project in CodeVault, or return the existing one if a project "
            "with this name already exists (safe to call before pushing code without "
            "checking first)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "minLength": 1, "description": "Project name, e.g. 'Incident Auto-Assignment'"},
                "description": {"type": "string"},
                "scope_type": {
                    "type": "string",
                    "enum": ["global", "scoped_app"],
                    "description": "Where the ServiceNow code lives. Defaults to 'global'.",
                },
                "scope_name": {
                    "type": "string",
                    "description": "Scoped app identifier, e.g. x_renin_ccr. Required when scope_type is 'scoped_app'.",
                },
            },
            "required": ["name"],
            "additionalProperties": False,
        },
    },
    {
        "name": "list_items",
        "description": "List the scripts/files stored in one CodeVault project, optionally filtered by a search query.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_slug": {"type": "string", "minLength": 1, "description": "The project's slug, e.g. 'incident-auto-assignment'"},
                "q": {"type": "string", "description": "Filter by title or identifier substring"},
            },
            "required": ["project_slug"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_item",
        "description": "Fetch one item's full source code and metadata by its uid (get code back out of CodeVault).",
        "inputSchema": {
            "type": "object",
            "properties": {"uid": {"type": "string", "minLength": 1, "description": "The item's uid, from list_items"}},
            "required": ["uid"],
            "additionalProperties": False,
        },
    },
    {
        "name": "push_item",
        "description": (
            "Create or update a script/file in a CodeVault project (push code). Matches an "
            "existing item to update by 'uid', then by 'identifier', then by (kind + title) "
            "- so pushing the same script again updates it in place instead of creating a "
            "duplicate. Screenshots are not supported here."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_slug": {"type": "string", "minLength": 1, "description": "The project's slug to push into"},
                "kind": {"type": "string", "enum": ["code", "xml"], "default": "code"},
                "title": {"type": "string", "minLength": 1, "description": "Item title, e.g. the Script Include's class name"},
                "uid": {"type": "string", "description": "Update this exact item instead of matching by identifier/title"},
                "identifier": {"type": "string", "description": "API name other scripts call this by, e.g. a Script Include class name"},
                "script_type": {
                    "type": "string",
                    "enum": [
                        "script_include", "business_rule", "client_script", "ui_page",
                        "ui_action", "ui_macro", "scheduled_job", "fix_script",
                        "rest_api", "widget", "other",
                    ],
                },
                "language": {"type": "string", "description": "e.g. javascript, xml, html, css"},
                "content": {"type": "string", "description": "Main source code / XML content"},
                "html_content": {"type": "string", "description": "HTML part, for UI Pages / Widgets"},
                "client_content": {"type": "string", "description": "Client script part, for UI Pages / Widgets"},
                "css_content": {"type": "string"},
                "note": {"type": "string", "description": "Context or instructions for whoever reads this later"},
                "table_name": {"type": "string"},
                "field_name": {"type": "string"},
                "br_order": {"type": "integer"},
                "operations": {"type": "string"},
                "condition": {"type": "string"},
                "client_callable": {"type": "boolean"},
                "api_endpoint": {"type": "string"},
                "sub_type": {"type": "string"},
            },
            "required": ["project_slug", "title"],
            "additionalProperties": False,
        },
    },
]


def call_tool(user, name, arguments):
    arguments = arguments or {}
    if name == "list_projects":
        return op_list_projects(user)
    if name == "create_project":
        return op_create_project(user, arguments)
    if name == "list_items":
        return op_list_items(user, arguments.get("project_slug") or "", arguments.get("q", ""))
    if name == "get_item":
        return op_get_item(user, arguments.get("uid") or "")
    if name == "push_item":
        slug = arguments.get("project_slug") or ""
        payload = dict((k, v) for k, v in arguments.items() if k != "project_slug")
        return op_push_item(user, slug, payload)
    raise ApiError(404, "Unknown tool '{0}'.".format(name))


def rpc_result(msg_id, result):
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def rpc_error(msg_id, code, message):
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def handle_message(user, message):
    """Returns a JSON-RPC response dict, or None if the message needs no reply
    (a notification, or a message we silently ignore)."""
    if not isinstance(message, dict) or "method" not in message:
        return None
    method = message.get("method")
    msg_id = message.get("id")
    is_request = "id" in message

    try:
        if method == "initialize":
            params = message.get("params") or {}
            client_version = params.get("protocolVersion")
            version = client_version if client_version in SUPPORTED_PROTOCOL_VERSIONS else DEFAULT_PROTOCOL_VERSION
            result = {
                "protocolVersion": version,
                "capabilities": {"tools": {}},
                "serverInfo": SERVER_INFO,
            }
        elif method in ("notifications/initialized", "notifications/cancelled"):
            return None
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            params = message.get("params") or {}
            try:
                data = call_tool(user, params.get("name"), params.get("arguments") or {})
                result = {"content": [{"type": "text", "text": json.dumps(data, indent=2)}], "isError": False}
            except ApiError as exc:
                result = {"content": [{"type": "text", "text": "Error: " + exc.message}], "isError": True}
        elif not is_request:
            return None
        else:
            return rpc_error(msg_id, -32601, "Method not found: " + str(method))
    except Exception as exc:  # a tool/handler bug must not 500 the whole batch
        if not is_request:
            return None
        return rpc_error(msg_id, -32603, "Internal error: " + str(exc))

    if not is_request:
        return None
    return rpc_result(msg_id, result)


@csrf_exempt
def mcp_endpoint(request, token):
    if request.method != "POST":
        return JsonResponse(
            rpc_error(None, -32000, "Method not allowed - this endpoint only accepts POST."),
            status=405,
        )

    try:
        user = authenticate_token(token)
    except ApiError as exc:
        return JsonResponse(rpc_error(None, -32001, exc.message), status=exc.status)

    try:
        body = json.loads(request.body.decode("utf-8")) if request.body else None
    except (ValueError, UnicodeDecodeError):
        return JsonResponse(rpc_error(None, -32700, "Parse error: invalid JSON"), status=400)

    if body is None:
        return JsonResponse(rpc_error(None, -32600, "Invalid Request: empty body"), status=400)

    messages = body if isinstance(body, list) else [body]
    responses = [r for r in (handle_message(user, m) for m in messages) if r is not None]

    if not responses:
        return HttpResponse(status=202)
    if isinstance(body, list):
        return JsonResponse(responses, safe=False)
    return JsonResponse(responses[0])
