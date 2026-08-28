"""GET/POST JSON API so external clients (Claude, an MCP server, CI, ...)
can read and push code without a browser session.

Auth: `Authorization: Bearer <token>` header, matched against ApiToken.key.
Every view below is scoped to that token's owner - no cross-user access.

Endpoints:
    GET/POST /api/v1/projects/
    GET/POST /api/v1/projects/<slug>/items/
    GET      /api/v1/items/<uid>/

The `op_*` functions below hold the actual logic and are plain Python
(request-agnostic: given a user + payload, return a dict or raise
ApiError) so they can be reused by both these HTTP views and the MCP
server in mcp_server.py, which speaks JSON-RPC rather than this HTTP
shape but wraps the exact same operations.
"""

import json

from django.db.models import Count
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods

from .models import ApiToken, Item, Project
from .services import fill_identifier, rebuild_project_dependencies

ITEM_TEXT_FIELDS = [
    "script_type",
    "identifier",
    "language",
    "content",
    "html_content",
    "client_content",
    "css_content",
    "note",
    "sub_type",
    "table_name",
    "field_name",
    "operations",
    "condition",
    "api_endpoint",
]


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def authenticate_token(key):
    """Returns the User owning this API key, or raises ApiError(401)."""
    try:
        token = ApiToken.objects.select_related("owner").get(key=key)
    except ApiToken.DoesNotExist:
        raise ApiError(401, "Invalid API token.")
    ApiToken.objects.filter(pk=token.pk).update(last_used_at=timezone.now())
    return token.owner


def authenticate(request):
    """Returns the ApiToken's owning User, or raises ApiError(401)."""
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        raise ApiError(401, "Missing 'Authorization: Bearer <token>' header.")
    return authenticate_token(header[len("Bearer "):].strip())


def serialize_project(project, item_count):
    return {
        "slug": project.slug,
        "name": project.name,
        "description": project.description,
        "scope_type": project.scope_type,
        "scope_name": project.scope_name,
        "item_count": item_count,
        "created_at": project.created_at.isoformat(),
        "updated_at": project.updated_at.isoformat(),
    }


def serialize_item_summary(item):
    return {
        "uid": str(item.uid),
        "title": item.title,
        "kind": item.kind,
        "script_type": item.script_type,
        "identifier": item.identifier,
        "language": item.language,
        "updated_at": item.updated_at.isoformat(),
    }


def serialize_item_detail(item):
    data = serialize_item_summary(item)
    data["project"] = item.project.slug
    data["identifier_is_manual"] = item.identifier_is_manual
    data["br_order"] = item.br_order
    data["client_callable"] = item.client_callable
    data["created_at"] = item.created_at.isoformat()
    for field in [
        "note",
        "content",
        "html_content",
        "client_content",
        "css_content",
        "sub_type",
        "table_name",
        "field_name",
        "operations",
        "condition",
        "api_endpoint",
    ]:
        data[field] = getattr(item, field)
    return data


# ------------------------------------------------------------ operations

def op_list_projects(user):
    projects = Project.objects.filter(owner=user).annotate(item_count=Count("items"))
    return {"projects": [serialize_project(p, p.item_count) for p in projects]}


def op_create_project(user, payload):
    name = (payload.get("name") or "").strip()
    if not name:
        raise ApiError(400, "'name' is required.")

    existing = Project.objects.filter(owner=user, name=name).first()
    if existing:
        return {"project": serialize_project(existing, existing.items.count()), "created": False}

    scope_type = payload.get("scope_type") or Project.ScopeType.GLOBAL
    if scope_type not in Project.ScopeType.values:
        raise ApiError(400, "'scope_type' must be 'global' or 'scoped_app'.")
    project = Project(
        owner=user,
        name=name,
        description=payload.get("description") or "",
        scope_type=scope_type,
        scope_name=(payload.get("scope_name") or "").strip().lower(),
    )
    project.save()
    return {"project": serialize_project(project, 0), "created": True}


def _get_project(user, slug):
    try:
        return Project.objects.get(owner=user, slug=slug)
    except Project.DoesNotExist:
        raise ApiError(404, "No project with slug '{0}'.".format(slug))


def op_list_items(user, slug, query=""):
    project = _get_project(user, slug)
    items = project.items.all()
    query = (query or "").strip()
    if query:
        items = items.filter(title__icontains=query) | items.filter(identifier__icontains=query)
    return {
        "project": serialize_project(project, project.items.count()),
        "items": [serialize_item_summary(i) for i in items],
    }


def op_push_item(user, slug, payload):
    """Create a new item, or update an existing one if it can be matched.

    Match order: explicit 'uid' -> same identifier in this project -> same
    (kind, title) in this project. Lets a client push the same script
    repeatedly without creating duplicates.
    """
    project = _get_project(user, slug)

    kind = payload.get("kind") or Item.Kind.CODE
    if kind not in (Item.Kind.CODE, Item.Kind.XML):
        raise ApiError(
            400, "'kind' must be 'code' or 'xml' (screenshots aren't supported via the API)."
        )

    title = (payload.get("title") or "").strip()
    identifier = (payload.get("identifier") or "").strip()
    uid = (payload.get("uid") or "").strip()

    item = None
    created = False
    if uid:
        try:
            item = Item.objects.get(owner=user, project=project, uid=uid)
        except Item.DoesNotExist:
            raise ApiError(404, "No item with uid '{0}' in this project.".format(uid))
    else:
        candidates = project.items.exclude(kind=Item.Kind.IMAGE)
        if identifier:
            item = candidates.filter(identifier=identifier).first()
        if item is None and title:
            item = candidates.filter(kind=kind, title=title).first()
        if item is None:
            if not title:
                raise ApiError(400, "'title' is required when creating a new item.")
            item = Item(owner=user, project=project, kind=kind)
            created = True

    item.title = title or item.title
    item.kind = kind
    for field in ITEM_TEXT_FIELDS:
        if field in payload:
            setattr(item, field, payload[field] or "")
    if "br_order" in payload:
        item.br_order = payload["br_order"]
    if "client_callable" in payload:
        item.client_callable = bool(payload["client_callable"])
    if identifier:
        item.identifier = identifier
        item.identifier_is_manual = True
    elif created:
        item.identifier_is_manual = False

    if not item.title:
        raise ApiError(400, "'title' is required.")

    fill_identifier(item)
    item.save()
    rebuild_project_dependencies(project)

    return {"item": serialize_item_detail(item), "created": created}


def op_get_item(user, uid):
    try:
        item = Item.objects.select_related("project").get(owner=user, uid=uid)
    except Item.DoesNotExist:
        raise ApiError(404, "No item with uid '{0}'.".format(uid))
    return {"item": serialize_item_detail(item)}


# ----------------------------------------------------------------- views

def parse_json_body(request):
    if request.body:
        try:
            payload = json.loads(request.body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise ApiError(400, "Request body must be valid JSON.")
    else:
        payload = {}
    if not isinstance(payload, dict):
        raise ApiError(400, "Request body must be a JSON object.")
    return payload


def api_view(view_func):
    """Handles auth, JSON body parsing on POST, and ApiError -> JSON response."""

    def wrapped(request, *args, **kwargs):
        try:
            user = authenticate(request)
            payload = parse_json_body(request) if request.method == "POST" else None
            return view_func(request, user, payload, *args, **kwargs)
        except ApiError as exc:
            return JsonResponse({"error": exc.message}, status=exc.status)

    return wrapped


@csrf_exempt
@require_http_methods(["GET", "POST"])
@api_view
def projects_collection(request, user, payload):
    if request.method == "GET":
        return JsonResponse(op_list_projects(user))
    result = op_create_project(user, payload)
    return JsonResponse(result, status=201 if result["created"] else 200)


@csrf_exempt
@require_http_methods(["GET", "POST"])
@api_view
def items_collection(request, user, payload, slug=None):
    if request.method == "GET":
        return JsonResponse(op_list_items(user, slug, request.GET.get("q", "")))
    result = op_push_item(user, slug, payload)
    return JsonResponse(result, status=201 if result["created"] else 200)


@csrf_exempt
@require_GET
@api_view
def item_detail(request, user, payload, uid=None):
    return JsonResponse(op_get_item(user, uid))
