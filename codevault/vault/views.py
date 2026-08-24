import mimetypes
import posixpath
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from .forms import ItemForm, ProjectForm
from .models import ApiToken, Item, Project
from .services import build_dependency_tree, fill_identifier, rebuild_project_dependencies


# ---------------------------------------------------------------- projects

@login_required
def project_list(request):
    projects = Project.objects.filter(owner=request.user).annotate(
        item_count=Count("items"),
        script_count=Count("items", filter=~Q(items__kind=Item.Kind.IMAGE)),
        image_count=Count("items", filter=Q(items__kind=Item.Kind.IMAGE)),
    )
    query = request.GET.get("q", "").strip()
    if query:
        projects = projects.filter(
            Q(name__icontains=query) | Q(description__icontains=query)
        )
    return render(
        request,
        "vault/project_list.html",
        {"projects": projects, "query": query},
    )


@login_required
def project_create(request):
    if request.method == "POST":
        form = ProjectForm(request.POST)
        if form.is_valid():
            project = form.save(commit=False)
            project.owner = request.user
            project.save()
            messages.success(request, "Project created: " + project.name)
            return redirect(project.get_absolute_url())
    else:
        form = ProjectForm()
    return render(request, "vault/project_form.html", {"form": form, "is_edit": False})


@login_required
def project_edit(request, slug):
    project = get_object_or_404(Project, slug=slug, owner=request.user)
    if request.method == "POST":
        form = ProjectForm(request.POST, instance=project)
        if form.is_valid():
            form.save()
            messages.success(request, "Project updated.")
            return redirect(project.get_absolute_url())
    else:
        form = ProjectForm(instance=project)
    return render(
        request,
        "vault/project_form.html",
        {"form": form, "is_edit": True, "project": project},
    )


@login_required
def project_delete(request, slug):
    project = get_object_or_404(Project, slug=slug, owner=request.user)
    if request.method == "POST":
        name = project.name
        for item in project.items.all():
            item.delete()  # per-item delete removes files from disk
        project.delete()
        messages.success(request, "Deleted project: " + name)
        return redirect("project_list")
    return render(request, "vault/project_confirm_delete.html", {"project": project})


@login_required
def project_detail(request, slug):
    project = get_object_or_404(Project, slug=slug, owner=request.user)
    items = project.items.all()

    kind = request.GET.get("kind", "")
    if kind in Item.Kind.values:
        items = items.filter(kind=kind)

    stype = request.GET.get("stype", "")
    if stype in Item.ScriptType.values:
        items = items.filter(script_type=stype)

    query = request.GET.get("q", "").strip()
    if query:
        items = items.filter(
            Q(title__icontains=query)
            | Q(note__icontains=query)
            | Q(content__icontains=query)
            | Q(html_content__icontains=query)
            | Q(client_content__icontains=query)
            | Q(identifier__icontains=query)
            | Q(table_name__icontains=query)
        )

    paginator = Paginator(items, 12)
    page = paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "vault/project_detail.html",
        {
            "project": project,
            "page": page,
            "kind": kind,
            "stype": stype,
            "query": query,
            "kinds": Item.Kind.choices,
            "script_types": Item.ScriptType.choices,
        },
    )


@login_required
def project_dependencies(request, slug):
    project = get_object_or_404(Project, slug=slug, owner=request.user)
    if request.method == "POST":  # manual "Rescan" button
        count = rebuild_project_dependencies(project)
        messages.success(
            request, "Rescanned project: " + str(count) + " dependency link(s) found."
        )
        return redirect("project_dependencies", slug=project.slug)
    direction = "usage" if request.GET.get("view") == "usage" else "deps"
    roots, standalone = build_dependency_tree(project, direction=direction)
    return render(
        request,
        "vault/project_deps.html",
        {
            "project": project,
            "roots": roots,
            "standalone": standalone,
            "direction": direction,
        },
    )


# --------------------------------------------------------------- api access

@login_required
def api_access(request):
    token, _ = ApiToken.objects.get_or_create(owner=request.user)
    return render(
        request,
        "vault/api_access.html",
        {"token": token, "base_url": request.build_absolute_uri("/")[:-1]},
    )


@login_required
def api_token_regenerate(request):
    if request.method == "POST":
        token, _ = ApiToken.objects.get_or_create(owner=request.user)
        token.regenerate()
        messages.success(request, "API token regenerated. Update any client using the old one.")
    return redirect("api_access")


# ------------------------------------------------------------------- items

@login_required
def item_create(request, slug):
    project = get_object_or_404(Project, slug=slug, owner=request.user)
    if request.method == "POST":
        form = ItemForm(request.POST, request.FILES, project=project)
        if form.is_valid():
            item = form.save(commit=False)
            item.owner = request.user
            item.project = project
            fill_identifier(item)
            item.save()
            rebuild_project_dependencies(project)
            messages.success(request, "Saved: " + item.title)
            if "save_and_add" in request.POST:
                return redirect("item_create", slug=project.slug)
            return redirect(item.get_absolute_url())
    else:
        initial = {}
        kind = request.GET.get("kind", "")
        if kind in Item.Kind.values:
            initial["kind"] = kind
        related = request.GET.get("related_to", "")
        if related.isdigit():
            initial["related_to"] = related
            initial.setdefault("kind", Item.Kind.IMAGE)
        form = ItemForm(initial=initial, project=project)
    return render(
        request,
        "vault/item_form.html",
        {"form": form, "is_edit": False, "project": project},
    )


@login_required
def item_edit(request, uid):
    item = get_object_or_404(Item, uid=uid, owner=request.user)
    project = item.project
    if request.method == "POST":
        form = ItemForm(request.POST, request.FILES, instance=item, project=project)
        if form.is_valid():
            item = form.save(commit=False)
            fill_identifier(item)
            item.save()
            rebuild_project_dependencies(project)
            messages.success(request, "Updated: " + item.title)
            return redirect(item.get_absolute_url())
    else:
        form = ItemForm(instance=item, project=project)
    return render(
        request,
        "vault/item_form.html",
        {"form": form, "is_edit": True, "item": item, "project": project},
    )


@login_required
def item_detail(request, uid):
    item = get_object_or_404(
        Item.objects.select_related("project", "related_to"), uid=uid, owner=request.user
    )
    return render(
        request,
        "vault/item_detail.html",
        {
            "item": item,
            "project": item.project,
            "depends_on": item.depends_on(),
            "used_by": item.used_by(),
            "screenshots": item.screenshots,
        },
    )


@login_required
def item_delete(request, uid):
    item = get_object_or_404(Item, uid=uid, owner=request.user)
    project = item.project
    if request.method == "POST":
        title = item.title
        item.delete()
        rebuild_project_dependencies(project)
        messages.success(request, "Deleted: " + title)
        return redirect(project.get_absolute_url())
    return render(request, "vault/item_confirm_delete.html", {"item": item})


@login_required
def item_raw(request, uid):
    """Plain-text view of the content — handy for select-all + copy."""
    item = get_object_or_404(Item, uid=uid, owner=request.user)
    if not item.content:
        raise Http404("This item has no text content.")
    return HttpResponse(item.content, content_type="text/plain; charset=utf-8")


@login_required
def serve_media(request, path):
    """Serve uploaded files behind login.

    Media is intentionally NOT exposed as a public static mapping on
    PythonAnywhere; every download goes through this authenticated view.
    """
    # Normalise and reject any path that tries to escape MEDIA_ROOT.
    clean = posixpath.normpath(path).lstrip("/")
    if clean != path or clean.startswith(".."):
        raise Http404
    media_root = Path(settings.MEDIA_ROOT)
    full_path = (media_root / clean).resolve()
    try:
        full_path.relative_to(media_root.resolve())
    except ValueError:
        raise Http404
    if not full_path.is_file():
        raise Http404

    # Only serve files that belong to the requesting user.
    if not Item.objects.filter(owner=request.user, upload=clean).exists():
        raise Http404

    content_type = mimetypes.guess_type(str(full_path))[0] or "application/octet-stream"
    response = FileResponse(open(full_path, "rb"), content_type=content_type)
    if request.GET.get("download"):
        response["Content-Disposition"] = (
            'attachment; filename="' + full_path.name + '"'
        )
    return response
