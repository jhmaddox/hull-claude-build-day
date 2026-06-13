"""Issues views — kanban board, backlog, ticket detail, sprints.

All tenant views go through ``accounts.scoping`` (``org_required`` +
``scoped`` / ``visible(Model, request)``) so there is never a
cross-org leak. HTMX powers in-place status changes + comment reloads.
"""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from accounts.scoping import org_required, visible

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
        visible(Ticket, request)
        .select_related("board", "sprint", "assignee", "incident", "pull_request")
        .prefetch_related("labels")
    )
    boards = visible(Board, request)
    ctx = {
        "columns": _columns(tickets),
        "boards": boards,
        "ticket_count": len(tickets) if isinstance(tickets, list) else tickets.count(),
    }
    return render(request, "issues/board.html", ctx)


@org_required
def backlog(request):
    tickets = (
        visible(Ticket, request)
        .select_related("board", "sprint", "assignee")
        .prefetch_related("labels")
    )

    # --- Filter bar (simple GET form; empty param = no filter) ------------- #
    f_status = (request.GET.get("status") or "").strip()
    f_type = (request.GET.get("type") or "").strip()
    f_priority = (request.GET.get("priority") or "").strip()
    f_assignee = (request.GET.get("assignee") or "").strip()
    f_label = (request.GET.get("label") or "").strip()
    f_q = (request.GET.get("q") or "").strip()

    valid_status = {s for s, _ in Ticket.Status.choices}
    valid_type = {t for t, _ in Ticket.Type.choices}
    valid_priority = {p for p, _ in Ticket.Priority.choices}

    if f_status in valid_status:
        tickets = tickets.filter(status=f_status)
    if f_type in valid_type:
        tickets = tickets.filter(type=f_type)
    if f_priority in valid_priority:
        tickets = tickets.filter(priority=f_priority)
    if f_assignee:
        if f_assignee == "unassigned":
            tickets = tickets.filter(assignee__isnull=True)
        else:
            tickets = tickets.filter(assignee_id=f_assignee)
    if f_label:
        tickets = tickets.filter(labels__id=f_label)
    if f_q:
        tickets = tickets.filter(title__icontains=f_q)

    tickets = tickets.order_by("status", "order", "-created_at").distinct()

    # Assignee options: users that report/assigned within this org's tickets.
    assignee_ids = (
        visible(Ticket, request)
        .exclude(assignee__isnull=True)
        .values_list("assignee_id", flat=True)
        .distinct()
    )
    assignees = User.objects.filter(pk__in=list(assignee_ids))

    # --- Per-status count chips (deep-link the status filter) -------------- #
    from django.db.models import Count

    raw_counts = dict(
        visible(Ticket, request)
        .values_list("status")
        .annotate(n=Count("id"))
    )
    status_labels = dict(Ticket.Status.choices)
    status_chips = [
        {
            "value": s,
            "label": status_labels.get(s, s),
            "count": raw_counts.get(s, 0),
            "active": f_status == s,
        }
        for s, _ in Ticket.Status.choices
    ]
    total_count = sum(c["count"] for c in status_chips)

    ctx = {
        "tickets": tickets,
        "labels": visible(Label, request),
        "assignees": assignees,
        "status_chips": status_chips,
        "total_count": total_count,
        "status_choices": Ticket.Status.choices,
        "type_choices": Ticket.Type.choices,
        "priority_choices": Ticket.Priority.choices,
        "f": {
            "status": f_status,
            "type": f_type,
            "priority": f_priority,
            "assignee": f_assignee,
            "label": f_label,
            "q": f_q,
        },
    }
    return render(request, "issues/backlog.html", ctx)


# --------------------------------------------------------------------------- #
# Ticket detail
# --------------------------------------------------------------------------- #
@org_required
def ticket(request, pk):
    t = get_object_or_404(visible(Ticket, request), pk=pk)
    attached_label_ids = set(t.labels.values_list("id", flat=True))
    ctx = {
        "ticket": t,
        "comments": t.comments.select_related("author").all(),
        "activities": t.activities.all(),
        "status_choices": Ticket.Status.choices,
        "sprints": visible(Sprint, request),
        "all_labels": visible(Label, request),
        "attached_label_ids": attached_label_ids,
        "links": _ticket_links(t),
        "mentions": _ticket_mentions(t, request),
    }
    return render(request, "issues/ticket.html", ctx)


def _ticket_mentions(t, request):
    """Find org PRs / agent runs that reference this ticket's key (HULL-<n>).

    Returns a list of {"label", "url"} cross-links for PRs whose
    title/description/diff mentions the key, and agent runs whose
    title/prompt/output mentions it. Best-effort: a missing app or reverse never
    500s — it just yields fewer rows.
    """
    key = (t.key or "").strip()
    out = []
    if not key:
        return out

    # PRs that mention the key (excluding the directly-linked PR, already shown).
    try:
        from django.db.models import Q

        from vcs.models import PullRequest

        prs = (
            visible(PullRequest, request)
            .filter(
                Q(title__icontains=key)
                | Q(description__icontains=key)
                | Q(diff__icontains=key)
            )
            .exclude(pk=getattr(t.pull_request, "pk", None) or 0)
            .distinct()[:20]
        )
        for pr in prs:
            out.append(
                {
                    "kind": "pr",
                    "label": f"PR #{pr.number} · {pr.title}",
                    "url": _safe_url(pr),
                }
            )
    except Exception:  # noqa: BLE001
        pass

    # Agent runs that mention the key (excluding the directly-linked run).
    try:
        from django.db.models import Q

        from agents.models import AgentRun

        runs = (
            visible(AgentRun, request)
            .filter(
                Q(title__icontains=key)
                | Q(prompt__icontains=key)
                | Q(output__icontains=key)
            )
            .exclude(pk=getattr(t.agent_run, "pk", None) or 0)
            .distinct()[:20]
        )
        for r in runs:
            out.append(
                {
                    "kind": "agent",
                    "label": f"Agent run #{r.pk} · {r.title}",
                    "url": _agent_run_url(r),
                }
            )
    except Exception:  # noqa: BLE001
        pass

    return out


def _safe_url(obj):
    """Best-effort absolute URL for a cross-linked object; '' on any failure."""
    if obj is None:
        return ""
    try:
        return obj.get_absolute_url()
    except Exception:  # noqa: BLE001 — a missing reverse must never 500.
        return ""


def _agent_run_url(agent_run):
    """Best-effort URL to an agent run detail page; '' if reverse fails."""
    if agent_run is None:
        return ""
    try:
        return reverse("agents:detail", args=[agent_run.pk])
    except Exception:  # noqa: BLE001
        try:
            return agent_run.get_absolute_url()
        except Exception:  # noqa: BLE001
            return ""


def _ticket_links(t):
    """Pre-resolve cross-link URLs so templates degrade gracefully (no 500)."""
    return {
        "incident_url": _safe_url(getattr(t, "incident", None)),
        "pull_request_url": _safe_url(getattr(t, "pull_request", None)),
        "agent_run_url": _agent_run_url(getattr(t, "agent_run", None)),
    }


@org_required
def add_comment(request, pk):
    t = get_object_or_404(visible(Ticket, request), pk=pk)
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
    t = get_object_or_404(visible(Ticket, request), pk=pk)
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
def card_status(request, pk):
    """Inline board-card status move: POST status → set_status → swap the card.

    Reuses ``services.set_status`` (org-scoped + Activity logged) and returns the
    re-rendered board card fragment for an in-place HTMX swap (no full reload).
    """
    t = get_object_or_404(visible(Ticket, request), pk=pk)
    if request.method == "POST":
        new = request.POST.get("status")
        valid = {s for s, _ in Ticket.Status.choices}
        if new in valid and new != t.status:
            services.set_status(t, new, actor=request.user.get_username())
            t.refresh_from_db()
    return render(
        request,
        "issues/_board_card.html",
        {"ticket": t, "status_choices": Ticket.Status.choices},
    )


@org_required
def assign(request, pk):
    t = get_object_or_404(visible(Ticket, request), pk=pk)
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
    boards = visible(Board, request)
    sprints = visible(Sprint, request)
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
    t = get_object_or_404(visible(Ticket, request), pk=pk)
    boards = visible(Board, request)
    sprints = visible(Sprint, request)
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
    sprint_qs = visible(Sprint, request).select_related("board")
    rows = []
    for s in sprint_qs:
        ts = visible(Ticket, request).filter(sprint=s)
        total = ts.count()
        done = ts.filter(status=Ticket.Status.DONE).count()
        rows.append({"sprint": s, "total": total, "done": done})
    return render(request, "issues/sprints.html", {"rows": rows})


@org_required
def sprint_detail(request, pk):
    s = get_object_or_404(visible(Sprint, request), pk=pk)
    tickets = (
        visible(Ticket, request)
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


# --------------------------------------------------------------------------- #
# Board management (create)
# --------------------------------------------------------------------------- #
@org_required
def board_new(request):
    if request.method == "POST":
        name = (request.POST.get("name") or "").strip()
        key = (request.POST.get("key") or "HULL").strip().upper()[:12] or "HULL"
        if not name:
            messages.error(request, "Board name is required.")
            return redirect("issues:board")
        project = None
        pid = request.POST.get("project")
        if pid:
            try:
                from projects.models import Project

                project = visible(Project, request).filter(pk=pid).first()
            except Exception:  # noqa: BLE001
                project = None
        Board.objects.create(
            org=request.org, name=name, key=key, project=project
        )
        messages.success(request, f"Created board {key}.")
    return redirect("issues:board")


# --------------------------------------------------------------------------- #
# Sprint management (create / start / complete / add-remove ticket)
# --------------------------------------------------------------------------- #
def _parse_dt(value):
    if not value:
        return None
    from django.utils.dateparse import parse_datetime, parse_date

    dt = parse_datetime(value)
    if dt is None:
        d = parse_date(value)
        if d is not None:
            from datetime import datetime, time

            dt = datetime.combine(d, time.min)
    if dt is not None and timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.get_current_timezone())
    return dt


@org_required
def sprint_new(request):
    if request.method == "POST":
        name = (request.POST.get("name") or "").strip()
        if not name:
            messages.error(request, "Sprint name is required.")
            return redirect("issues:sprints")
        board_obj = None
        bid = request.POST.get("board")
        if bid:
            board_obj = visible(Board, request).filter(pk=bid).first()
        s = Sprint.objects.create(
            org=request.org,
            name=name,
            goal=request.POST.get("goal", ""),
            board=board_obj,
            starts_at=_parse_dt(request.POST.get("starts_at")),
            ends_at=_parse_dt(request.POST.get("ends_at")),
        )
        messages.success(request, f"Created sprint {s.name}.")
        return redirect("issues:sprint", pk=s.pk)
    return redirect("issues:sprints")


@org_required
def sprint_action(request, pk):
    """Start (-> active) or complete (-> completed) a sprint."""
    s = get_object_or_404(visible(Sprint, request), pk=pk)
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "start":
            s.status = Sprint.Status.ACTIVE
            if not s.starts_at:
                s.starts_at = timezone.now()
            s.save(update_fields=["status", "starts_at"])
        elif action == "complete":
            s.status = Sprint.Status.COMPLETED
            if not s.ends_at:
                s.ends_at = timezone.now()
            s.save(update_fields=["status", "ends_at"])
    return redirect("issues:sprint", pk=s.pk)


@org_required
def ticket_sprint(request, pk):
    """Add/remove a ticket to/from a sprint from the ticket detail page."""
    t = get_object_or_404(visible(Ticket, request), pk=pk)
    if request.method == "POST":
        sid = (request.POST.get("sprint") or "").strip()
        if sid:
            sprint_obj = visible(Sprint, request).filter(pk=sid).first()
            if sprint_obj is not None:
                t.sprint = sprint_obj
                t.save(update_fields=["sprint", "updated_at"])
                services.log_activity(
                    t,
                    f"added to sprint {sprint_obj.name}",
                    actor=request.user.get_username(),
                    icon="merge",
                )
        else:
            if t.sprint_id:
                old = t.sprint.name
                t.sprint = None
                t.save(update_fields=["sprint", "updated_at"])
                services.log_activity(
                    t,
                    f"removed from sprint {old}",
                    actor=request.user.get_username(),
                )
    return redirect("issues:ticket", pk=t.pk)


# --------------------------------------------------------------------------- #
# Labels (create / attach / detach)
# --------------------------------------------------------------------------- #
@org_required
def label_new(request):
    if request.method == "POST":
        name = (request.POST.get("name") or "").strip()
        color = (request.POST.get("color") or "badge-neutral").strip()
        if name:
            Label.objects.create(org=request.org, name=name, color=color)
            messages.success(request, f"Created label {name}.")
    nxt = request.POST.get("next") or request.GET.get("next")
    if nxt:
        return redirect(nxt)
    return redirect("issues:backlog")


@org_required
def ticket_labels(request, pk):
    """Set the labels on a ticket from a multi-value POST (org-scoped)."""
    t = get_object_or_404(visible(Ticket, request), pk=pk)
    if request.method == "POST":
        ids = request.POST.getlist("labels")
        org_labels = visible(Label, request).filter(pk__in=ids)
        t.labels.set(org_labels)
        services.log_activity(
            t,
            "updated labels: "
            + (", ".join(label.name for label in org_labels) or "none"),
            actor=request.user.get_username(),
        )
    return redirect("issues:ticket", pk=t.pk)


# --------------------------------------------------------------------------- #
# Work this ticket — spawn a builder agent in a fresh worktree (best-effort)
# --------------------------------------------------------------------------- #
def _ticket_project(ticket, request):
    """Best-effort resolve the Project a ticket belongs to (board → project).

    Returns a Project or ``None``. Never raises so the action degrades
    gracefully when projects/agents aren't wired or the ticket has no board.
    """
    project = getattr(getattr(ticket, "board", None), "project", None)
    if project is not None:
        return project
    # Fall back to any single org-scoped project so a board-less ticket can
    # still be worked when the org owns exactly one project.
    try:
        from projects.models import Project

        qs = visible(Project, request)
        if qs.count() == 1:
            return qs.first()
    except Exception:  # noqa: BLE001
        return None
    return None


@org_required
def ticket_work(request, pk):
    """Spawn a builder agent for this ticket: worktree + launch_agent + link.

    Best-effort and org-scoped. On success flips status to in_progress and
    links the AgentRun to the ticket. Degrades gracefully (a flash message, no
    500) when the ticket has no project or agents/projects aren't available.
    """
    t = get_object_or_404(visible(Ticket, request), pk=pk)
    if request.method != "POST":
        return redirect("issues:ticket", pk=t.pk)

    project = _ticket_project(t, request)
    if project is None:
        messages.error(
            request,
            "No project linked to this ticket — set the board's project first.",
        )
        return redirect("issues:ticket", pk=t.pk)

    try:
        from agents.services import launch_agent

        prompt = t.title
        if t.description:
            prompt = f"{t.title}\n\n{t.description}"
        agent_run = launch_agent(
            project,
            kind="feature",
            title=t.title,
            prompt=prompt,
            dispatch=True,
        )
        services.pick_ticket(
            t, assignee=request.user, assignee_name=request.user.get_username()
        )
        services.link_ticket(
            t, agent_run=agent_run, actor=request.user.get_username()
        )
        messages.success(
            request, f"Launched builder agent for {t.key}."
        )
    except Exception:  # noqa: BLE001 — never 500; the loop/UX must degrade.
        messages.error(
            request, "Could not launch an agent for this ticket right now."
        )
    return redirect("issues:ticket", pk=t.pk)


# --------------------------------------------------------------------------- #
# Agent backlog — surface agent-filed tickets with cross-links
# --------------------------------------------------------------------------- #
@org_required
def agent_backlog(request):
    from django.db.models import Q

    tickets = (
        visible(Ticket, request)
        .select_related("incident", "pull_request", "agent_run", "assignee")
        .prefetch_related("labels")
        .filter(
            Q(incident__isnull=False)
            | Q(pull_request__isnull=False)
            | Q(agent_run__isnull=False)
            | Q(reporter__isnull=True, reporter_name__gt="")
        )
        .order_by("-created_at")
        .distinct()
    )
    rows = []
    for t in tickets:
        rows.append({"ticket": t, "links": _ticket_links(t)})
    return render(request, "issues/agent_backlog.html", {"rows": rows})
