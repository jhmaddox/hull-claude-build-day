"""Docs / Wiki service helpers.

Two concerns live here:

1. **Best-effort activity feed** (``page_created`` / ``page_edited``) — emit a
   ``core.models.Event`` for the dashboard narration. These are wrapped so a
   broken/raising ``Event.log`` can NEVER stop a page from being saved (R25).

2. **Cross-app "related work" refs** (``attach_ref``) — org-scoped, defensive
   attaching of a wiki ``Page`` to a Project / PullRequest / Incident. The target
   must belong to the same org as the page (foreign targets are rejected, R22).

Everything is additive and tolerant of missing apps/columns so a parallel
workstream's half-built model can never take the wiki down.
"""

from __future__ import annotations

from .models import Page, PageRef


# --------------------------------------------------------------------------- #
# Best-effort activity feed (never raises)
# --------------------------------------------------------------------------- #
def _safe_log(verb, **kwargs):
    """Call ``core.models.Event.log`` but swallow ANY error (R25).

    The wiki must keep working even if the core Event model is unavailable,
    mis-migrated, or its ``log`` classmethod raises.
    """
    try:
        from core.models import Event

        Event.log(verb, **kwargs)
    except Exception:  # noqa: BLE001 — feed is decorative; never block a save
        return None


def page_created(page, actor="helm"):
    """Emit a feed Event for a newly created page (best-effort)."""
    try:
        url = page.get_absolute_url()
    except Exception:  # noqa: BLE001
        url = ""
    _safe_log(
        f"created doc “{page.title}”",
        project=_page_project(page),
        actor=_actor_name(actor),
        level="info",
        icon="log",
        url=url,
    )


def page_edited(page, actor="helm"):
    """Emit a feed Event for an edited page (best-effort)."""
    try:
        url = page.get_absolute_url()
    except Exception:  # noqa: BLE001
        url = ""
    _safe_log(
        f"edited doc “{page.title}”",
        project=_page_project(page),
        actor=_actor_name(actor),
        level="info",
        icon="log",
        url=url,
    )


def _page_project(page):
    try:
        return page.project
    except Exception:  # noqa: BLE001
        return None


def _actor_name(actor):
    if actor is None:
        return "helm"
    getter = getattr(actor, "get_username", None)
    if callable(getter):
        try:
            return actor.get_username()
        except Exception:  # noqa: BLE001
            return "helm"
    return str(actor) or "helm"


# --------------------------------------------------------------------------- #
# Cross-app references (org-scoped + defensive)
# --------------------------------------------------------------------------- #
def attach_ref(page, kind, target_pk, org=None, note=""):
    """Attach a related-work ref from ``page`` to a target, scoped to ``org``.

    ``kind`` is one of ``project`` / ``pr`` / ``incident``. The target is looked
    up **within the same org** as the page (``page.org``) so a foreign-org target
    is silently rejected (returns ``None``) — never leaking across tenants (R22).

    Returns the created :class:`~wiki.models.PageRef`, or ``None`` if the target
    can't be found / is foreign / the target app is unavailable.
    """
    page_org = page.org if getattr(page, "org_id", None) else org
    target = _resolve_target(kind, target_pk, page_org)
    if target is None:
        return None

    ref = PageRef(page=page, org=page_org, note=(note or "")[:300])
    if kind == PageRef.KIND_PROJECT:
        ref.project = target
    elif kind == PageRef.KIND_PR:
        ref.pull_request = target
    elif kind == PageRef.KIND_INCIDENT:
        ref.incident = target
    else:
        return None
    ref.save()
    return ref


def _resolve_target(kind, target_pk, org):
    """Fetch the target object, filtered to ``org`` (defensive)."""
    try:
        qs = _target_queryset(kind)
    except Exception:  # noqa: BLE001 — app/model not importable
        return None
    if qs is None:
        return None
    try:
        return qs.filter(org=org).filter(pk=target_pk).first()
    except Exception:  # noqa: BLE001 — broken/foreign migration, stay up
        return None


def _target_queryset(kind):
    if kind == PageRef.KIND_PROJECT:
        from projects.models import Project

        return Project.objects.all()
    if kind == PageRef.KIND_PR:
        from vcs.models import PullRequest

        return PullRequest.objects.all()
    if kind == PageRef.KIND_INCIDENT:
        from observability.models import Incident

        return Incident.objects.all()
    return None


def ref_target_choices(org):
    """Return ``{"projects": [...], "prs": [...], "incidents": [...]}`` of
    candidate targets in ``org`` for the attach UI. Each entry is defensive: a
    broken/unmigrated target app yields an empty list instead of a crash."""
    return {
        "projects": _safe_targets(PageRef.KIND_PROJECT, org),
        "prs": _safe_targets(PageRef.KIND_PR, org),
        "incidents": _safe_targets(PageRef.KIND_INCIDENT, org),
    }


def _safe_targets(kind, org):
    """List candidate targets of ``kind`` in ``org``; never raises (R17/R22).

    A parallel app may be half-migrated (model fields with no DB column); the
    blanket except keeps the wiki page-detail/attach UI alive in that case.
    """
    try:
        qs = _target_queryset(kind)
        if qs is None:
            return []
        return list(qs.filter(org=org)[:50])
    except Exception:  # noqa: BLE001
        return []
