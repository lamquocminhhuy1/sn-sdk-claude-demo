import mimetypes
import posixpath
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from .forms import ItemForm
from .models import Item


@login_required
def item_list(request):
    items = Item.objects.filter(owner=request.user)

    kind = request.GET.get("kind", "")
    if kind in Item.Kind.values:
        items = items.filter(kind=kind)

    query = request.GET.get("q", "").strip()
    if query:
        items = items.filter(
            Q(title__icontains=query)
            | Q(note__icontains=query)
            | Q(content__icontains=query)
        )

    paginator = Paginator(items, 12)
    page = paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "vault/item_list.html",
        {
            "page": page,
            "kind": kind,
            "query": query,
            "kinds": Item.Kind.choices,
        },
    )


@login_required
def item_create(request):
    if request.method == "POST":
        form = ItemForm(request.POST, request.FILES)
        if form.is_valid():
            item = form.save(commit=False)
            item.owner = request.user
            item.save()
            messages.success(request, "Saved: " + item.title)
            if "save_and_add" in request.POST:
                return redirect("item_create")
            return redirect(item.get_absolute_url())
    else:
        initial = {}
        kind = request.GET.get("kind", "")
        if kind in Item.Kind.values:
            initial["kind"] = kind
        form = ItemForm(initial=initial)
    return render(request, "vault/item_form.html", {"form": form, "is_edit": False})


@login_required
def item_edit(request, pk):
    item = get_object_or_404(Item, pk=pk, owner=request.user)
    if request.method == "POST":
        form = ItemForm(request.POST, request.FILES, instance=item)
        if form.is_valid():
            form.save()
            messages.success(request, "Updated: " + item.title)
            return redirect(item.get_absolute_url())
    else:
        form = ItemForm(instance=item)
    return render(
        request, "vault/item_form.html", {"form": form, "is_edit": True, "item": item}
    )


@login_required
def item_detail(request, pk):
    item = get_object_or_404(Item, pk=pk, owner=request.user)
    return render(request, "vault/item_detail.html", {"item": item})


@login_required
def item_delete(request, pk):
    item = get_object_or_404(Item, pk=pk, owner=request.user)
    if request.method == "POST":
        title = item.title
        item.delete()
        messages.success(request, "Deleted: " + title)
        return redirect("item_list")
    return render(request, "vault/item_confirm_delete.html", {"item": item})


@login_required
def item_raw(request, pk):
    """Plain-text view of the content — handy for select-all + copy."""
    item = get_object_or_404(Item, pk=pk, owner=request.user)
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
