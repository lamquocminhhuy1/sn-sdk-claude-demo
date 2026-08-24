"""GET/POST JSON API so external clients (Claude, an MCP server, CI, ...)
can read and push code without a browser session.

Auth: `Authorization: Bearer <token>` header, matched against ApiToken.key.
Every view below is scoped to that token's owner - no cross-user access.

Endpoints:
    GET/POST /api/v1/projects/
    GET/POST /api/v1/projects/<slug>/items/
    GET      /api/v1/items/<uid>/
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


def authenticate(request):
    """Returns the ApiToken's owning User, or raises ApiError(401)."""
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        raise ApiError(401, "Missing 'Authorization: Bearer <token>' header.")
    key = header[len("Bearer "):].strip()
    try:
        token = ApiToken.objects.select_related("owner").get(key=key)
    except ApiToken.DoesNotExist:
        raise ApiError(401, "Invalid API token.")
    ApiToken.objects.filter(pk=token.pk).update(last_used_at=timezone.now())
    return token.owner


def api_view(view_func):
    """Handles auth, JSON body parsing on POST, and ApiError -> JSON response."""

    def wrapped(request, *args, **kwargs):
        try:
            user = authenticate(request)
            if request.method == "POST":
                if request.body:
                    try:
                        payload = json.loads(request.body.decode("utf-8"))
                    except (ValueError, UnicodeDecodeError):
                        raise ApiError(400, "Request body must be valid JSON.")
                else:
                    payload = {}
                if not isinstance(payload, dict):
                    raise ApiError(400, "Request body must be a JSON object.")
                return view_func(request, user, payload, *args, **kwargs)
            return view_func(request, user, *args, **kwargs)
        except ApiError as exc:
            return JsonResponse({"error": exc.message}, status=exc.status)

    return wrapped


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


@csrf_exempt
@require_http_methods(["GET", "POST"])
@api_view
def projects_collection(request, user, payload=None):
    if request.method == "GET":
        projects = Project.objects.filter(owner=user).annotate(item_count=Count("items"))
        return JsonResponse(
            {"projects": [serialize_project(p, p.item_count) for p in projects]}
        )

    name = (payload.get("name") or "").strip()
    if not name:
        raise ApiError(400, "'name' is required.")

    existing = Project.objects.filter(owner=user, name=name).first()
    if existing:
        return JsonResponse(
            {"project": serialize_project(existing, existing.items.count()), "created": False}
        )

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
    return JsonResponse({"project": serialize_project(project, 0), "created": True}, status=201)


@csrf_exempt
@require_http_methods(["GET", "POST"])
@api_view
def items_collection(request, user, payload=None, slug=None):
    try:
        project = Project.objects.get(owner=user, slug=slug)
    except Project.DoesNotExist:
        raise ApiError(404, "No project with slug '{0}'.".format(slug))

    if request.method == "GET":
        items = project.items.all()
        query = request.GET.get("q", "").strip()
        if query:
            items = items.filter(title__icontains=query) | items.filter(
                identifier__icontains=query
            )
        return JsonResponse(
            {
                "project": serialize_project(project, project.items.count()),
                "items": [serialize_item_summary(i) for i in items],
            }
        )

    return _push_item(user, project, payload)


def _push_item(user, project, payload):
    """Create a new item, or update an existing one if it can be matched.

    Match order: explicit 'uid' -> same identifier in this project -> same
    (kind, title) in this project. Lets a client push the same script
    repeatedly without creating duplicates.
    """
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

    return JsonResponse(
        {"item": serialize_item_detail(item), "created": created},
        status=201 if created else 200,
    )


@csrf_exempt
@require_GET
@api_view
def item_detail(request, user, uid):
    try:
        item = Item.objects.select_related("project").get(owner=user, uid=uid)
    except Item.DoesNotExist:
        raise ApiError(404, "No item with uid '{0}'.".format(uid))
    return JsonResponse({"item": serialize_item_detail(item)})
