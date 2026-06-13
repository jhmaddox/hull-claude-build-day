"""Issues service layer — the agent backlog API.

These functions are the ONLY supported way for agents (and other slices) to put
work into Issues. They run **without a request** (no ``request.org``), so they
default ``org=None`` and never assume a current org. Every meaningful step is
mirrored to both a per-ticket :class:`issues.models.Activity` and the global
:class:`core.models.Event` feed.

HARD RULE: nothing here may raise into the autonomous incident -> fix loop.
Cross-app links are additive + nullable; ``core.Event.log`` is wrapped so a
feed failure can never propagate.
"""

from __future__ import annotations

from .models import Activity, Board, Comment, Sprint, Ticket


# --------------------------------------------------------------------------- #
# Feed / activity helpers
# --------------------------------------------------------------------------- #
def _emit_event(verb, *, actor="helm", level="info", icon="dot", url="", project=None):
    """Best-effort write to the global activity feed. Never raises."""
    try:
        from core.models import Event

        Event.log(
            verb, actor=actor, level=level, icon=icon, url=url, project=project
        )
    except Exception:
        # The feed is narration only — a failure must never break callers
        # (especially the autonomous loop).
        pass


def log_activity(ticket, verb, *, actor="helm", level="info", icon="dot", emit_event=True):
    """Record a per-ticket Activity row (and optionally mirror to the feed).

    Returns the created :class:`Activity`. Safe to call from the loop.
    """
    activity = Activity.objects.create(
        org=getattr(ticket, "org", None),
        ticket=ticket,
        actor=actor,
        verb=verb,
    )
    if emit_event:
        url = ""
        try:
            url = ticket.get_absolute_url()
        except Exception:
            url = ""
        project = getattr(getattr(ticket, "board", None), "project", None)
        _emit_event(
            f"{ticket.key or 'ticket'}: {verb}",
            actor=actor,
            level=level,
            icon=icon,
            url=url,
            project=project,
        )
    return activity


# --------------------------------------------------------------------------- #
# Keys
# --------------------------------------------------------------------------- #
def next_ticket_key(org=None, board=None):
    """Return the next ticket key as a ``str`` (e.g. ``"HULL-7"``).

    Numbering is per (org, prefix). ``board`` supplies the prefix; defaults to
    ``HULL``. Always returns a string, never raises.
    """
    prefix = "HULL"
    if board is not None and getattr(board, "key", ""):
        prefix = board.key
    qs = Ticket.objects.filter(key__startswith=f"{prefix}-")
    if org is not None:
        qs = qs.filter(org=org)
    n = 0
    for existing in qs.values_list("key", flat=True):
        tail = existing.rsplit("-", 1)[-1]
        if tail.isdigit():
            n = max(n, int(tail))
    return f"{prefix}-{n + 1}"


# --------------------------------------------------------------------------- #
# Filing tickets (used by PM agents)
# --------------------------------------------------------------------------- #
def file_ticket(
    title,
    *,
    org=None,
    description="",
    type=Ticket.Type.TASK,
    priority=Ticket.Priority.MEDIUM,
    status=Ticket.Status.BACKLOG,
    board=None,
    sprint=None,
    reporter=None,
    reporter_name="pm-agent",
    incident=None,
    pull_request=None,
    agent_run=None,
    labels=None,
):
    """File a new ticket into the backlog. Agent-callable, no request needed.

    Defaults ``org=None`` so the autonomous loop can file tickets without a
    tenant context. Returns the created :class:`Ticket`.
    """
    ticket = Ticket.objects.create(
        org=org,
        title=title,
        description=description,
        type=type,
        priority=priority,
        status=status,
        board=board,
        sprint=sprint,
        reporter=reporter,
        reporter_name=reporter_name or "",
        incident=incident,
        pull_request=pull_request,
        agent_run=agent_run,
    )
    # Mint a key now that we have a pk / board prefix.
    ticket.key = next_ticket_key(org=org, board=board)
    ticket.save(update_fields=["key"])

    if labels:
        try:
            ticket.labels.set(labels)
        except Exception:
            pass

    log_activity(
        ticket,
        f"filed by {reporter_name or 'helm'}",
        actor=reporter_name or "helm",
        level="info",
        icon="agent",
    )
    return ticket


# --------------------------------------------------------------------------- #
# Picking up work (used by builder agents)
# --------------------------------------------------------------------------- #
def pick_ticket(ticket, *, assignee=None, assignee_name="builder-agent"):
    """Mark a ticket as picked up: status -> in_progress + assignee + Activity."""
    ticket.status = Ticket.Status.IN_PROGRESS
    if assignee is not None:
        ticket.assignee = assignee
    if assignee_name:
        ticket.assignee_name = assignee_name
    ticket.save(update_fields=["status", "assignee", "assignee_name", "updated_at"])

    who = assignee_name or (assignee.get_username() if assignee else "helm")
    log_activity(
        ticket,
        f"picked up by {who} → In Progress",
        actor=who,
        level="info",
        icon="agent",
    )
    return ticket


# --------------------------------------------------------------------------- #
# Comments
# --------------------------------------------------------------------------- #
def add_comment(ticket, body, *, author=None, author_name="helm"):
    """Persist a Comment on a ticket and log Activity. Returns the Comment."""
    comment = Comment.objects.create(
        org=getattr(ticket, "org", None),
        ticket=ticket,
        author=author,
        author_name=author_name or "",
        body=body,
    )
    who = author_name or (author.get_username() if author else "helm")
    log_activity(
        ticket,
        f"{who} commented",
        actor=who,
        level="info",
        icon="dot",
        emit_event=False,
    )
    return comment


# --------------------------------------------------------------------------- #
# Status transitions
# --------------------------------------------------------------------------- #
def set_status(ticket, status, *, actor="helm"):
    """Change a ticket's status and log Activity. Returns the ticket."""
    old = ticket.get_status_display()
    ticket.status = status
    ticket.save(update_fields=["status", "updated_at"])
    new = ticket.get_status_display()
    level = "success" if status == Ticket.Status.DONE else "info"
    icon = "check" if status == Ticket.Status.DONE else "dot"
    log_activity(
        ticket, f"status {old} → {new}", actor=actor, level=level, icon=icon
    )
    return ticket


# --------------------------------------------------------------------------- #
# Cross-app links (additive; safe with all-None)
# --------------------------------------------------------------------------- #
def link_ticket(
    ticket, *, incident=None, pull_request=None, agent_run=None, actor="helm"
):
    """Attach additive FKs (incident / PR / agent_run) to a ticket + log.

    Only sets links that are provided; passing all ``None`` is a no-op that
    never raises. Returns the ticket.
    """
    fields = []
    bits = []
    if incident is not None:
        ticket.incident = incident
        fields.append("incident")
        bits.append(f"incident #{getattr(incident, 'number', incident)}")
    if pull_request is not None:
        ticket.pull_request = pull_request
        fields.append("pull_request")
        bits.append(f"PR #{getattr(pull_request, 'number', pull_request)}")
    if agent_run is not None:
        ticket.agent_run = agent_run
        fields.append("agent_run")
        bits.append(f"agent run #{getattr(agent_run, 'pk', agent_run)}")

    if not fields:
        return ticket

    ticket.save(update_fields=fields + ["updated_at"])
    log_activity(
        ticket,
        "linked " + ", ".join(bits),
        actor=actor,
        level="info",
        icon="merge",
    )
    return ticket


# --------------------------------------------------------------------------- #
# Convenience: ensure a default board/sprint exist for an org
# --------------------------------------------------------------------------- #
def get_or_create_default_board(org=None, *, name="Backlog", key="HULL"):
    """Return (board, created) for an org's default board."""
    return Board.objects.get_or_create(
        org=org, name=name, defaults={"key": key}
    )


def advance_tickets_for_merged_pr(pull_request, *, actor="helm"):
    """When ``pull_request`` merges, move every linked ticket to Done + log.

    Idempotent and loop-safe: finds all tickets whose ``pull_request`` FK points
    at this PR and, for each not already Done, sets status=Done and logs an
    Activity. Returns the list of tickets advanced (possibly empty). NEVER raises
    — it is intended to be called additively off the vcs merge path and must not
    block a merge or the autonomous incident -> fix loop.
    """
    advanced = []
    try:
        if pull_request is None:
            return advanced
        # Only act on a genuinely merged PR; guard the attr so a stub/None status
        # is a safe no-op.
        status = getattr(pull_request, "status", None)
        if status is not None and status != "merged":
            return advanced
        tickets = Ticket.objects.filter(pull_request=pull_request)
        for ticket in tickets:
            try:
                if ticket.status == Ticket.Status.DONE:
                    continue
                set_status(ticket, Ticket.Status.DONE, actor=actor)
                advanced.append(ticket)
            except Exception:  # noqa: BLE001 — one bad ticket can't break the rest
                continue
    except Exception:  # noqa: BLE001 — MUST NEVER raise into the merge path.
        return advanced
    return advanced


def create_ticket(org, title, **kwargs):
    """Thin alias so agents/other slices can call ``issues.services.create_ticket``.

    Mirrors :func:`file_ticket` but takes ``org`` positionally (matching the
    brief's ``create_ticket(org, ...)``). Never raises into the loop.
    """
    try:
        return file_ticket(title, org=org, **kwargs)
    except Exception:  # noqa: BLE001 — agent backlog must never break a caller
        return None


# --------------------------------------------------------------------------- #
# CROWN JEWEL: wire the autonomous loop into the agent backlog
# --------------------------------------------------------------------------- #
def ticket_for_incident(
    incident, *, status=None, pull_request=None, agent_run=None, org=None
):
    """Find-or-create exactly ONE Ticket linked to ``incident`` and update it.

    The ticket is keyed on the ``incident`` FK (``type=incident``) so calling
    this repeatedly for the same incident is **idempotent** — it always leaves
    exactly one linked ticket. Optionally updates ``status`` and attaches a
    ``pull_request`` / ``agent_run``. Logs an :class:`Activity` row and a
    best-effort :class:`core.models.Event`.

    LOOP-SAFE: the entire body is wrapped in try/except. Any error (including a
    forced failure in ticket creation or a bad incident) returns ``None`` and is
    **never** propagated into the autonomous remediation loop.
    """
    try:
        if incident is None:
            return None

        # Resolve org best-effort: explicit arg wins, else the incident's
        # project org (kept nullable so the request-less loop still works).
        if org is None:
            org = getattr(getattr(incident, "project", None), "org", None)

        # Idempotent find-or-create keyed on the incident FK. ``.objects`` is the
        # unscoped manager (no request here) so we always see the existing one.
        ticket = Ticket.objects.filter(incident=incident).order_by("pk").first()
        created = False
        if ticket is None:
            number = getattr(incident, "number", incident.pk)
            title = getattr(incident, "title", "") or f"Incident {number}"
            ticket = Ticket.objects.create(
                org=org,
                title=f"INC-{number}: {title}"[:300],
                description=(
                    getattr(incident, "error_message", "") or ""
                ),
                type=Ticket.Type.INCIDENT,
                priority=Ticket.Priority.HIGH,
                status=status or Ticket.Status.TODO,
                incident=incident,
                pull_request=pull_request,
                agent_run=agent_run,
                reporter_name="claude-sre",
            )
            ticket.key = next_ticket_key(org=org)
            ticket.save(update_fields=["key"])
            created = True
            log_activity(
                ticket,
                f"filed for INC-{number} by autonomous loop",
                actor="claude-sre",
                level="info",
                icon="incident",
            )

        # Update mutable fields/links on the existing-or-new ticket.
        update_fields = []
        bits = []
        if pull_request is not None and ticket.pull_request_id != getattr(
            pull_request, "pk", None
        ):
            ticket.pull_request = pull_request
            update_fields.append("pull_request")
            bits.append(f"PR #{getattr(pull_request, 'number', pull_request)}")
        if agent_run is not None and ticket.agent_run_id != getattr(
            agent_run, "pk", None
        ):
            ticket.agent_run = agent_run
            update_fields.append("agent_run")
            bits.append(f"agent run #{getattr(agent_run, 'pk', agent_run)}")
        if status is not None and ticket.status != status:
            ticket.status = status
            update_fields.append("status")

        if update_fields:
            update_fields.append("updated_at")
            ticket.save(update_fields=update_fields)
            verb = []
            if bits:
                verb.append("linked " + ", ".join(bits))
            if status is not None and "status" in update_fields:
                verb.append(f"status → {ticket.get_status_display()}")
            if verb:
                level = (
                    "success" if status == Ticket.Status.DONE else "info"
                )
                icon = "check" if status == Ticket.Status.DONE else "merge"
                log_activity(
                    ticket,
                    "; ".join(verb),
                    actor="claude-sre",
                    level=level,
                    icon=icon,
                )
        return ticket
    except Exception:  # noqa: BLE001 — MUST NEVER raise into the loop.
        return None
