"""Issues views — kanban board, backlog, ticket detail, sprints.

All tenant views go through ``accounts.scoping`` (``org_required`` +
``scoped`` / ``Model.objects.for_org(request.org)``) so there is never a
cross-org leak. HTMX powers in-place status changes + comment reloads.
"""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404, redirect, render

from accounts.scoping import org_required, scoped

from . import services
from .models import Board, Label, Sprint, Ticket

User = get_user_model()

# Column order for the kanban board / sprint grouping.
STATUS_COLUMNS = [
    Ticket.Status.BACKLOG,
    Ticket.Status.TODO,
    Ticket.Status.IN_PROGRESS,
    Ticket.Status.IN_REVIEW,
    Ticket.Status.DONE,
]


def _columns(tickets):
    """Group a ticket iterable into ordered (status_value, label, tickets)."""
    buckets = {s: [] for s in STATUS_COLUMNS}
    for t in tickets:
        buckets.setdefault(t.status, []).append(t)
    labels = dict(Ticket.Status.choices)
    return [(s, labels.get(s, s), buckets.get(s, [])) for s in STATUS_COLUMNS]


# --------------------------------------------------------------------------- #
# Board (kanban)
# --------------------------------------------------------------------------- #
@org_required
def board(request):
    tickets = (
        scoped(Ticket, request)
        .select_related("board", "sprint", "assignee", "incident", "pull_request")
        .prefetch_related("labels")
    )
    boards = scoped(Board, request)
    ctx = {
        "columns": _columns(tickets),
        "boards": boards,
        "ticket_count": len(tickets) if isinstance(tickets, list) else tickets.count(),
    }
    return render(request, "issues/board.html", ctx)


@org_required
def backlog(request):
    tickets = (
        scoped(Ticket, request)
        .select_related("board", "sprint", "assignee")
        .prefetch_related("labels")
        .order_by("status", "order", "-created_at")
    )
    return render(request, "issues/backlog.html", {"tickets": tickets})


# --------------------------------------------------------------------------- #
# Ticket detail
# --------------------------------------------------------------------------- #
@org_required
def ticket(request, pk):
    t = get_object_or_404(scoped(Ticket, request), pk=pk)
    ctx = {
        "ticket": t,
        "comments": t.comments.select_related("author").all(),
        "activities": t.activities.all(),
        "status_choices": Ticket.Status.choices,
    }
    return render(request, "issues/ticket.html", ctx)


@org_required
def add_comment(request, pk):
    t = get_object_or_404(scoped(Ticket, request), pk=pk)
    if request.method == "POST":
        body = (request.POST.get("body") or "").strip()
        if body:
            services.add_comment(
                t, body, author=request.user, author_name=request.user.get_username()
            )
    # Re-render the detail page (HTMX swaps content, full nav for non-HTMX).
    return redirect("issues:ticket", pk=t.pk)


@org_required
def set_status(request, pk):
    t = get_object_or_404(scoped(Ticket, request), pk=pk)
    if request.method == "POST":
        new = request.POST.get("status")
        valid = {s for s, _ in Ticket.Status.choices}
        if new in valid:
            services.set_status(t, new, actor=request.user.get_username())
    if request.headers.get("HX-Request"):
        t.refresh_from_db()
        return render(
            request,
            "issues/_status_control.html",
            {"ticket": t, "status_choices": Ticket.Status.choices},
        )
    return redirect("issues:ticket", pk=t.pk)


@org_required
def assign(request, pk):
    t = get_object_or_404(scoped(Ticket, request), pk=pk)
    if request.method == "POST":
        uid = request.POST.get("assignee")
        if uid == "me":
            t.assignee = request.user
            t.assignee_name = request.user.get_username()
        elif uid == "":
            t.assignee = None
            t.assignee_name = ""
        else:
            try:
                t.assignee = User.objects.get(pk=uid)
                t.assignee_name = t.assignee.get_username()
            except (User.DoesNotExist, ValueError):
                pass
        t.save(update_fields=["assignee", "assignee_name", "updated_at"])
        services.log_activity(
            t,
            f"assigned to {t.assignee_name or 'nobody'}",
            actor=request.user.get_username(),
        )
    return redirect("issues:ticket", pk=t.pk)


# --------------------------------------------------------------------------- #
# Create / edit
# --------------------------------------------------------------------------- #
@org_required
def ticket_new(request):
    boards = scoped(Board, request)
    sprints = scoped(Sprint, request)
    if request.method == "POST":
        title = (request.POST.get("title") or "").strip()
        if not title:
            messages.error(request, "Title is required.")
        else:
            board_obj = None
            bid = request.POST.get("board")
            if bid:
                board_obj = boards.filter(pk=bid).first()
            sprint_obj = None
            sid = request.POST.get("sprint")
            if sid:
                sprint_obj = sprints.filter(pk=sid).first()
            t = services.file_ticket(
                title,
                org=request.org,
                description=request.POST.get("description", ""),
                type=request.POST.get("type", Ticket.Type.TASK),
                priority=request.POST.get("priority", Ticket.Priority.MEDIUM),
                status=request.POST.get("status", Ticket.Status.BACKLOG),
                board=board_obj,
                sprint=sprint_obj,
                reporter=request.user,
                reporter_name=request.user.get_username(),
            )
            messages.success(request, f"Created {t.key}.")
            return redirect("issues:ticket", pk=t.pk)
    ctx = {
        "boards": boards,
        "sprints": sprints,
        "type_choices": Ticket.Type.choices,
        "status_choices": Ticket.Status.choices,
        "priority_choices": Ticket.Priority.choices,
    }
    return render(request, "issues/ticket_form.html", ctx)


@org_required
def ticket_edit(request, pk):
    t = get_object_or_404(scoped(Ticket, request), pk=pk)
    boards = scoped(Board, request)
    sprints = scoped(Sprint, request)
    if request.method == "POST":
        t.title = (request.POST.get("title") or t.title).strip()
        t.description = request.POST.get("description", t.description)
        t.type = request.POST.get("type", t.type)
        t.priority = request.POST.get("priority", t.priority)
        bid = request.POST.get("board")
        t.board = boards.filter(pk=bid).first() if bid else None
        sid = request.POST.get("sprint")
        t.sprint = sprints.filter(pk=sid).first() if sid else None
        t.save()
        services.log_activity(t, "edited", actor=request.user.get_username())
        messages.success(request, f"Updated {t.key}.")
        return redirect("issues:ticket", pk=t.pk)
    ctx = {
        "ticket": t,
        "boards": boards,
        "sprints": sprints,
        "type_choices": Ticket.Type.choices,
        "status_choices": Ticket.Status.choices,
        "priority_choices": Ticket.Priority.choices,
    }
    return render(request, "issues/ticket_form.html", ctx)


# --------------------------------------------------------------------------- #
# Sprints
# --------------------------------------------------------------------------- #
@org_required
def sprints(request):
    sprint_qs = scoped(Sprint, request).select_related("board")
    rows = []
    for s in sprint_qs:
        ts = scoped(Ticket, request).filter(sprint=s)
        total = ts.count()
        done = ts.filter(status=Ticket.Status.DONE).count()
        rows.append({"sprint": s, "total": total, "done": done})
    return render(request, "issues/sprints.html", {"rows": rows})


@org_required
def sprint_detail(request, pk):
    s = get_object_or_404(scoped(Sprint, request), pk=pk)
    tickets = (
        scoped(Ticket, request)
        .filter(sprint=s)
        .select_related("assignee")
        .prefetch_related("labels")
    )
    ctx = {
        "sprint": s,
        "columns": _columns(tickets),
        "total": len(tickets) if isinstance(tickets, list) else tickets.count(),
        "done": sum(1 for t in tickets if t.status == Ticket.Status.DONE),
    }
    return render(request, "issues/sprint_detail.html", ctx)
