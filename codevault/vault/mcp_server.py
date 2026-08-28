"""A remote MCP server for claude.ai's "Add custom connector" (Settings ->
Connectors -> Add custom connector -> Remote MCP server URL). Both entry
points below are a second front door onto the exact same operations as
api.py's HTTP API - see op_* in that module - just speaking MCP's
JSON-RPC shape instead of plain REST.

Two front doors, two auth styles:
  - /mcp/<token>/  (mcp_endpoint): the token is the URL path segment
    itself, matched against ApiToken.key. Simple, works with curl or a
    stdio client, but NOT what claude.ai's custom-connector dialog uses -
    that flow always attempts OAuth first.
  - /mcp/         (mcp_endpoint_oauth): requires `Authorization: Bearer
    <access_token>` where the token came from the OAuth flow in oauth.py.
    This is the URL to paste into claude.ai's connector dialog.

Both implement the MCP Streamable HTTP transport in "stateless, JSON
response" mode: no Mcp-Session-Id is issued or required, and every
response is returned as a single direct JSON body rather than an SSE
stream. This instance's tools are quick DB reads/writes with no
server-initiated messages, so no session state or push channel is needed.
"""

import hashlib
import json

from django.http import HttpResponse, JsonResponse
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from .models import OAuthToken

from .api import ApiError, authenticate_token, op_create_project, op_get_item, op_list_items, op_list_projects, op_push_item


def fingerprint(value):
    """Short, non-secret stand-in for a token/key in logs - lets you match
    a log line to a specific DB row without ever printing the real secret."""
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()[:12]

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


def _process_jsonrpc_body(request, user):
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


def _empty_sse_response():
    """GET opens the *optional* standalone SSE stream for server-initiated
    messages (MCP Streamable HTTP transport). We never push anything
    server-side (every tool here is a synchronous request/response), so a
    well-formed but immediately-closed stream is the correct reply - not
    a 405. Some clients (claude.ai's connector included) treat a 405 here
    as a fatal connection error instead of "this server has no push
    channel", so this must succeed rather than be rejected."""
    return HttpResponse(b"", content_type="text/event-stream")


def _no_content_response():
    """DELETE explicitly ends a session. We're stateless (no session to
    end), so acknowledge it as a no-op rather than rejecting it."""
    return HttpResponse(status=204)


@csrf_exempt
def mcp_endpoint(request, token):
    """The simple token-in-URL front door (see the module docstring in
    api.py) - for stdio clients, curl, or anything not doing OAuth."""
    try:
        user = authenticate_token(token)
    except ApiError as exc:
        return JsonResponse(rpc_error(None, -32001, exc.message), status=exc.status)

    if request.method == "GET":
        return _empty_sse_response()
    if request.method == "DELETE":
        return _no_content_response()
    if request.method != "POST":
        return JsonResponse(
            rpc_error(None, -32000, "Method not allowed."), status=405, headers={"Allow": "GET, POST, DELETE"}
        )
    return _process_jsonrpc_body(request, user)


def _resource_metadata_url(request):
    return request.build_absolute_uri("/")[:-1] + reverse("oauth_protected_resource_metadata")


def _authenticate_oauth_bearer(request):
    """Returns (user, None) on success, or (None, error_response) on failure."""
    header = request.headers.get("Authorization", "")
    access_token = header[len("Bearer "):].strip() if header.startswith("Bearer ") else ""
    challenge = 'Bearer resource_metadata="{0}"'.format(_resource_metadata_url(request))

    if not access_token:
        print("[mcp-auth] {0} {1}: no Authorization header at all".format(request.method, request.path))
        response = JsonResponse(rpc_error(None, -32001, "Missing bearer token."), status=401)
        response["WWW-Authenticate"] = challenge
        return None, response

    try:
        oauth_token = OAuthToken.objects.select_related("user").get(access_token=access_token)
    except OAuthToken.DoesNotExist:
        print(
            "[mcp-auth] {0} {1}: token fingerprint={2} not found (known tokens: {3})".format(
                request.method,
                request.path,
                fingerprint(access_token),
                [fingerprint(t) for t in OAuthToken.objects.values_list("access_token", flat=True)],
            )
        )
        response = JsonResponse(rpc_error(None, -32001, "Invalid or expired access token."), status=401)
        response["WWW-Authenticate"] = challenge
        return None, response

    if oauth_token.is_expired:
        print(
            "[mcp-auth] {0} {1}: token fingerprint={2} expired at {3} (now {4})".format(
                request.method, request.path, fingerprint(access_token), oauth_token.expires_at, timezone.now()
            )
        )
        oauth_token.delete()
        response = JsonResponse(rpc_error(None, -32001, "Invalid or expired access token."), status=401)
        response["WWW-Authenticate"] = challenge
        return None, response

    return oauth_token.user, None


@csrf_exempt
def mcp_endpoint_oauth(request):
    """The OAuth-protected front door claude.ai's custom connector uses -
    see oauth.py for the full authorization flow this expects clients to
    go through before they show up here with a Bearer access token."""
    user, error_response = _authenticate_oauth_bearer(request)
    if error_response is not None:
        return error_response

    if request.method == "GET":
        return _empty_sse_response()
    if request.method == "DELETE":
        return _no_content_response()
    if request.method != "POST":
        return JsonResponse(
            rpc_error(None, -32000, "Method not allowed."), status=405, headers={"Allow": "GET, POST, DELETE"}
        )
    return _process_jsonrpc_body(request, user)
