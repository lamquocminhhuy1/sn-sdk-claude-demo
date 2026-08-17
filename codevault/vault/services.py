"""Dependency detection and tree building for a project.

How detection works:
- Every script item gets an ``identifier`` — the API name other scripts use to
  call it (e.g. a Script Include class name). If left blank, we auto-detect it
  from the code (``var X = Class.create()`` / ``Class.create('X')``) or fall
  back to a single-word title.
- After any item in a project changes, we rescan the project: if item A's code
  contains item B's identifier as a whole word, we record "A depends on B".
"""

import re

from .models import Dependency, Item

CLASS_CREATE_RE = re.compile(
    r"var\s+([A-Za-z_$][\w$]*)\s*=\s*Class\.create\s*\("
)
CLASS_CREATE_ARG_RE = re.compile(r"Class\.create\s*\(\s*['\"]([\w$]+)['\"]")
SINGLE_WORD_RE = re.compile(r"^[A-Za-z_$][\w$]*$")

# Identifiers this short/common would produce bogus edges.
MIN_IDENTIFIER_LENGTH = 3
IGNORED_IDENTIFIERS = frozenset(
    ["var", "the", "for", "new", "get", "set", "run", "current", "previous"]
)


def guess_identifier_from_content(item):
    """Detect the API name from the code/title, ignoring any stored value."""
    if item.has_text:
        match = CLASS_CREATE_RE.search(item.content)
        if match:
            return match.group(1)
        match = CLASS_CREATE_ARG_RE.search(item.content)
        if match:
            return match.group(1)
    title = item.title.strip()
    if SINGLE_WORD_RE.match(title):
        return title
    return ""


def guess_identifier(item):
    """Best-effort API name for an item, used for dependency matching."""
    if item.identifier:
        return item.identifier.strip()
    return guess_identifier_from_content(item)


def fill_identifier(item):
    """Keep the identifier in sync with the code.

    Manual identifiers are left untouched. Auto identifiers are recomputed on
    every save so renaming a class in the code updates the identifier too.
    """
    if item.identifier_is_manual and item.identifier.strip():
        return item
    if item.kind != Item.Kind.IMAGE:
        item.identifier = guess_identifier_from_content(item)
    return item


def rebuild_project_dependencies(project):
    """Rescan every script in the project and rebuild the dependency edges.

    All code parts are scanned (script, HTML, client script, CSS), so e.g. a
    UI Page whose client script calls a Script Include is detected too.
    """
    items = [
        item
        for item in project.items.exclude(kind=Item.Kind.IMAGE)
        if item.all_code
    ]
    Dependency.objects.filter(from_item__project=project).delete()

    edges = []
    for target in items:
        ident = guess_identifier(target)
        if (
            not ident
            or len(ident) < MIN_IDENTIFIER_LENGTH
            or ident.lower() in IGNORED_IDENTIFIERS
        ):
            continue
        pattern = re.compile(r"\b" + re.escape(ident) + r"\b")
        for source in items:
            if source.pk == target.pk:
                continue
            if pattern.search(source.all_code):
                edges.append(Dependency(from_item=source, to_item=target))
    Dependency.objects.bulk_create(edges, ignore_conflicts=True)
    return len(edges)


def build_dependency_tree(project, direction="deps"):
    """Nested structure for rendering the project's dependency tree.

    direction="deps" (call tree): roots are entry points nothing else calls;
    each node's children are the scripts it depends on.
    direction="usage" (impact tree): the graph is flipped - roots are shared
    scripts that call nothing themselves (e.g. Script Includes); each node's
    children are the scripts that USE it, answering "what breaks if I change
    this?".
    Returns (roots, standalone) where each node is
    {"item": Item, "children": [...], "cycle": bool}.
    """
    items = list(project.items.exclude(kind=Item.Kind.IMAGE))
    by_pk = dict((i.pk, i) for i in items)
    edges = Dependency.objects.filter(from_item__project=project)
    children_map = {}
    has_incoming = set()
    in_any_edge = set()
    for edge in edges:
        if direction == "usage":
            parent_id, child_id = edge.to_item_id, edge.from_item_id
        else:
            parent_id, child_id = edge.from_item_id, edge.to_item_id
        children_map.setdefault(parent_id, []).append(child_id)
        has_incoming.add(child_id)
        in_any_edge.add(parent_id)
        in_any_edge.add(child_id)

    def node_for(pk, path):
        children = []
        for child_pk in sorted(
            children_map.get(pk, []),
            key=lambda p: by_pk[p].title.lower() if p in by_pk else "",
        ):
            if child_pk not in by_pk:
                continue
            if child_pk in path:
                children.append(
                    {"item": by_pk[child_pk], "children": [], "cycle": True}
                )
            else:
                children.append(node_for(child_pk, path | {child_pk}))
        return {"item": by_pk[pk], "children": children, "cycle": False}

    root_pks = [
        item.pk
        for item in sorted(items, key=lambda i: i.title.lower())
        if item.pk in in_any_edge and item.pk not in has_incoming
    ]
    # Pure cycles (A <-> B) have no incoming-free node; surface them anyway.
    covered = set()

    def collect(pks):
        for pk in pks:
            if pk in covered:
                continue
            covered.add(pk)
            collect(children_map.get(pk, []))

    collect(root_pks)
    for item in sorted(items, key=lambda i: i.title.lower()):
        if item.pk in in_any_edge and item.pk not in covered:
            root_pks.append(item.pk)
            collect([item.pk])

    roots = [node_for(pk, {pk}) for pk in root_pks]
    standalone = [
        item
        for item in sorted(items, key=lambda i: i.title.lower())
        if item.pk not in in_any_edge
    ]
    return roots, standalone
