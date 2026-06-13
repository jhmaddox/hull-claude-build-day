"""Docs / Wiki views — all org-scoped via ``request.org``.

Every read path filters with ``accounts.scoping.scoped`` / ``for_org`` so a page
that belongs to another org returns 404 (rubric R5). Writes always stamp the
current org from the request.
"""

from __future__ import annotations

from django.contrib import messages
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.text import slugify

from accounts.scoping import org_required, scoped

from .markdown import extract_wikilinks
from .models import Page, PageLink, PageRevision, Space


# --------------------------------------------------------------------------- #
# scoping helpers
# --------------------------------------------------------------------------- #
def _spaces(request):
    return scoped(Space, request)


def _pages(request):
    return scoped(Page, request)


def _get_page(request, pk):
    """Fetch a page within the current org, else 404 (R5)."""
    return get_object_or_404(_pages(request).select_related("space", "parent"), pk=pk)


def _get_space(request, slug):
    return get_object_or_404(_spaces(request), slug=slug)


def _page_tree(pages):
    """Build a nested [(page, [children...])] tree from a flat page list."""
    by_parent: dict = {}
    for p in pages:
        by_parent.setdefault(p.parent_id, []).append(p)

    def build(parent_id):
        return [
            {"page": p, "children": build(p.pk)}
            for p in by_parent.get(parent_id, [])
        ]

    return build(None)


# --------------------------------------------------------------------------- #
# index / spaces
# --------------------------------------------------------------------------- #
@org_required
def index(request):
    spaces = list(_spaces(request).annotate(num_pages=Count("pages")))
    recent = list(
        _pages(request).select_related("space").order_by("-updated_at")[:8]
    )
    total_pages = _pages(request).count()
    return render(
        request,
        "wiki/index.html",
        {
            "spaces": spaces,
            "recent": recent,
            "total_pages": total_pages,
        },
    )


@org_required
def space_new(request):
    if request.method == "POST":
        name = (request.POST.get("name") or "").strip()
        if not name:
            messages.error(request, "Space name is required.")
            return render(request, "wiki/space_form.html", {})
        space = Space(
            org=request.org,
            name=name,
            description=(request.POST.get("description") or "").strip(),
            icon=(request.POST.get("icon") or "📚").strip()[:8] or "📚",
        )
        space.save()
        messages.success(request, f"Created space “{space.name}”.")
        return redirect(space.get_absolute_url())
    return render(request, "wiki/space_form.html", {})


@org_required
def space_detail(request, slug):
    space = _get_space(request, slug)
    pages = list(
        _pages(request).filter(space=space).select_related("parent")
    )
    return render(
        request,
        "wiki/space.html",
        {
            "space": space,
            "tree": _page_tree(pages),
            "page_count": len(pages),
        },
    )


# --------------------------------------------------------------------------- #
# pages — view / create / edit / delete
# --------------------------------------------------------------------------- #
@org_required
def page_detail(request, pk):
    page = _get_page(request, pk)
    siblings = list(
        _pages(request).filter(space=page.space).select_related("parent")
    )
    children = list(_pages(request).filter(parent=page))
    backlinks = [
        link
        for link in scoped(PageLink, request)
        .filter(target=page)
        .select_related("source")
    ]
    return render(
        request,
        "wiki/page.html",
        {
            "page": page,
            "tree": _page_tree(siblings),
            "children": children,
            "backlinks": backlinks,
            "rendered": _render(request, page.body),
        },
    )


@org_required
def page_new(request):
    space_slug = request.GET.get("space") or request.POST.get("space")
    parent_pk = request.GET.get("parent") or request.POST.get("parent")

    space = None
    if space_slug:
        space = _spaces(request).filter(slug=space_slug).first()
    parent = None
    if parent_pk:
        parent = _pages(request).filter(pk=parent_pk).first()
        if parent and not space:
            space = parent.space

    if request.method == "POST":
        title = (request.POST.get("title") or "").strip()
        if not title:
            messages.error(request, "Title is required.")
        elif space is None:
            messages.error(request, "Pick a space for this page.")
        else:
            page = Page(
                org=request.org,
                space=space,
                parent=parent,
                title=title,
                body=request.POST.get("body") or "",
                created_by=request.user,
                updated_by=request.user,
            )
            page.save()
            page.snapshot_revision(request.user)
            _sync_links(request, page)
            messages.success(request, f"Created “{page.title}”.")
            return redirect(page.get_absolute_url())

    return render(
        request,
        "wiki/page_form.html",
        {
            "spaces": list(_spaces(request)),
            "space": space,
            "parent": parent,
            "page": None,
        },
    )


@org_required
def page_edit(request, pk):
    """Full-page editor (non-HTMX fallback)."""
    page = _get_page(request, pk)
    if request.method == "POST":
        return _save_page(request, page, redirect_to=page.get_absolute_url())
    return render(
        request,
        "wiki/page_form.html",
        {
            "spaces": list(_spaces(request)),
            "space": page.space,
            "parent": page.parent,
            "page": page,
        },
    )


@org_required
def page_delete(request, pk):
    page = _get_page(request, pk)
    if request.method == "POST":
        space = page.space
        title = page.title
        page.delete()
        messages.success(request, f"Deleted “{title}”.")
        if space:
            return redirect(space.get_absolute_url())
        return redirect(reverse("wiki:index"))
    return render(request, "wiki/page_confirm_delete.html", {"page": page})


# --------------------------------------------------------------------------- #
# HTMX edit-in-place
# --------------------------------------------------------------------------- #
@org_required
def page_edit_inline(request, pk):
    """Return the inline edit form fragment (GET) or save + return the rendered
    body fragment (POST). Powers HTMX edit-in-place."""
    page = _get_page(request, pk)
    if request.method == "POST":
        page.snapshot_revision(request.user)  # snapshot the pre-edit state
        page.title = (request.POST.get("title") or page.title).strip() or page.title
        page.body = request.POST.get("body") or ""
        page.updated_by = request.user
        page.save()
        _sync_links(request, page)
        messages.success(request, "Saved.")
        return render(
            request,
            "wiki/_page_body.html",
            {"page": page, "rendered": _render(request, page.body)},
        )
    return render(request, "wiki/_page_edit_form.html", {"page": page})


@org_required
def page_body(request, pk):
    """Read-only body fragment (used to cancel an inline edit)."""
    page = _get_page(request, pk)
    return render(
        request,
        "wiki/_page_body.html",
        {"page": page, "rendered": _render(request, page.body)},
    )


# --------------------------------------------------------------------------- #
# history
# --------------------------------------------------------------------------- #
@org_required
def page_history(request, pk):
    page = _get_page(request, pk)
    revisions = list(
        scoped(PageRevision, request)
        .filter(page=page)
        .select_related("edited_by")
    )
    return render(
        request,
        "wiki/history.html",
        {"page": page, "revisions": revisions},
    )


@org_required
def revision_detail(request, pk, number):
    page = _get_page(request, pk)
    revision = get_object_or_404(
        scoped(PageRevision, request).filter(page=page), number=number
    )
    return render(
        request,
        "wiki/revision.html",
        {
            "page": page,
            "revision": revision,
            "rendered": _render(request, revision.body),
        },
    )


@org_required
def revision_restore(request, pk, number):
    page = _get_page(request, pk)
    revision = get_object_or_404(
        scoped(PageRevision, request).filter(page=page), number=number
    )
    if request.method == "POST":
        page.snapshot_revision(request.user)  # snapshot current before restoring
        page.title = revision.title
        page.body = revision.body
        page.updated_by = request.user
        page.save()
        _sync_links(request, page)
        messages.success(request, f"Restored to v{revision.number}.")
    return redirect(page.get_absolute_url())


# --------------------------------------------------------------------------- #
# search (org-scoped — R5)
# --------------------------------------------------------------------------- #
@org_required
def search(request):
    q = (request.GET.get("q") or "").strip()
    results = []
    if q:
        results = list(
            _pages(request)
            .filter(Q(title__icontains=q) | Q(body__icontains=q))
            .select_related("space")
            .order_by("-updated_at")[:50]
        )
    template = (
        "wiki/_search_results.html"
        if request.headers.get("HX-Request")
        else "wiki/search.html"
    )
    return render(request, template, {"q": q, "results": results})


# --------------------------------------------------------------------------- #
# internals
# --------------------------------------------------------------------------- #
def _save_page(request, page, redirect_to):
    title = (request.POST.get("title") or "").strip()
    if not title:
        messages.error(request, "Title is required.")
        return render(
            request,
            "wiki/page_form.html",
            {
                "spaces": list(_spaces(request)),
                "space": page.space,
                "parent": page.parent,
                "page": page,
            },
        )
    page.snapshot_revision(request.user)
    page.title = title
    page.body = request.POST.get("body") or ""
    space_slug = request.POST.get("space")
    if space_slug:
        new_space = _spaces(request).filter(slug=space_slug).first()
        if new_space:
            page.space = new_space
    page.updated_by = request.user
    page.save()
    _sync_links(request, page)
    messages.success(request, f"Saved “{page.title}”.")
    return redirect(redirect_to)


def _resolver(request):
    """Return a [[Title]] -> URL resolver scoped to the request's org."""

    def resolve(title):
        match = (
            _pages(request)
            .filter(Q(title__iexact=title) | Q(slug=slugify(title)))
            .first()
        )
        return match.get_absolute_url() if match else None

    return resolve


def _render(request, body):
    from .markdown import render_markdown

    return render_markdown(body, wikilink_resolver=_resolver(request))


def _sync_links(request, page):
    """Recompute ``PageLink`` rows for ``page`` from its ``[[wikilinks]]`` (R6)."""
    page.outgoing_links.all().delete()
    for title in extract_wikilinks(page.body):
        target = (
            _pages(request)
            .filter(Q(title__iexact=title) | Q(slug=slugify(title)))
            .exclude(pk=page.pk)
            .first()
        )
        PageLink.objects.create(
            org=page.org,
            source=page,
            target=target,
            target_title=title,
        )
