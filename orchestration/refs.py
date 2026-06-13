"""Org-scoped, fallback-safe ref resolution for WorkflowRun. [ORC-1]

A WorkflowRun carries a loose pointer to the entity it operates on via
``(ref_type, ref_id)`` (kept as plain strings/ints to avoid hard FKs across
slices). This module maps that pointer back to the concrete entity, a URL, a
human label and a kind badge - so the orchestration UI can cross-link rows and
detail pages to incidents / PRs / agent runs / environments.

Two hard requirements drive the design:

* **Fallback-safe** - the autonomous loop and live polling must never 500 on a
  stale/unknown/empty ref. Every cross-app import and DB lookup is wrapped in
  ``try/except`` and returns ``None``/falsy on any problem (unknown ref_type,
  missing ref_id, deleted row, un-migrated table, ...).
* **Org-scoped** - a run owned by org A must not produce a *clickable* link to
  an entity owned by org B. When an ``org`` is supplied we resolve the entity
  through its ``OrgManager.for_org(org)`` (or ``project__org``) so a cross-org
  ref yields no object/URL.

Public surface::

    from orchestration import refs
    link = refs.resolve(run, request_or_org)   # -> Link | None
    link.url, link.label, link.kind, link.object

WorkflowRun also exposes thin wrappers (``run.linked(request)`` /
``run.linked_url()`` / ``run.linked_object()`` / ``run.linked_label()``) that
delegate here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class Link:
    """A resolved cross-link target. Truthy only when it has a URL."""

    object: Any = None
    url: str = ""
    label: str = ""
    kind: str = ""

    def __bool__(self) -> bool:  # falsy when unresolvable -> templates fall back
        return bool(self.url)


def _org_from(request_or_org):
    """Accept a request, an Org, or None and return an Org (or None)."""
    if request_or_org is None:
        return None
    # A request object carries .org (set by CurrentOrgMiddleware).
    return getattr(request_or_org, "org", request_or_org)


def _org_pk(org):
    return getattr(org, "pk", org)


def _scoped_get(model, pk, org):
    """Fetch ``model`` row ``pk`` constrained to ``org`` when one is given.

    Prefers the model's OrgManager.for_org; falls back to project__org for
    models scoped indirectly. Returns the instance or None - never raises.
    """
    try:
        if org is not None:
            # Direct org scoping via OrgManager (AgentRun/WorkflowRun/...).
            mgr = getattr(model, "objects", None)
            if mgr is not None and hasattr(mgr, "for_org"):
                try:
                    obj = mgr.for_org(org).filter(pk=pk).first()
                    if obj is not None:
                        return obj
                except Exception:  # noqa: BLE001 - may lack its own org field
                    pass
            # Indirect scoping via the related project's org.
            try:
                return model.objects.filter(project__org=org).filter(pk=pk).first()
            except Exception:  # noqa: BLE001
                return None
            return None
        # No org supplied -> unscoped best-effort lookup.
        return model.objects.filter(pk=pk).first()
    except Exception:  # noqa: BLE001 - missing row / un-migrated table / etc.
        return None


def _resolve_incident(ref_id, org) -> Optional[Link]:
    from observability.models import Incident

    inc = _scoped_get(Incident, ref_id, org)
    if inc is None:
        return None
    try:
        url = inc.get_absolute_url()
    except Exception:  # noqa: BLE001
        url = f"/obs/incidents/{inc.pk}/"
    status = getattr(inc, "status", "") or ""
    return Link(
        object=inc,
        url=url,
        kind="Incident",
        label=f"Incident #{getattr(inc, 'number', inc.pk)}"
        + (f" - {status}" if status else ""),
    )


def _resolve_pull_request(ref_id, org) -> Optional[Link]:
    from vcs.models import PullRequest

    pr = _scoped_get(PullRequest, ref_id, org)
    if pr is None:
        return None
    try:
        url = pr.get_absolute_url()
    except Exception:  # noqa: BLE001
        url = f"/vcs/pr/{pr.pk}/"
    return Link(
        object=pr, url=url, kind="PR", label=f"PR #{getattr(pr, 'number', pr.pk)}"
    )


def _resolve_agent_run(ref_id, org) -> Optional[Link]:
    from agents.models import AgentRun

    run = _scoped_get(AgentRun, ref_id, org)
    if run is None:
        return None
    return Link(object=run, url=f"/agents/{run.pk}/", kind="Agent",
                label=f"Agent #{run.pk}")


def _resolve_environment(ref_id, org) -> Optional[Link]:
    from deploys.models import Environment

    env = _scoped_get(Environment, ref_id, org)
    if env is None:
        return None
    try:
        url = env.public_url
    except Exception:  # noqa: BLE001
        url = f"/d/{env.pk}/"
    return Link(object=env, url=url or f"/d/{env.pk}/", kind="Env",
                label=f"{getattr(env, 'name', 'env')}")


# Map the four loop ref types to a resolver.
_RESOLVERS = {
    "incident": _resolve_incident,
    "pull_request": _resolve_pull_request,
    "agent_run": _resolve_agent_run,
    "environment": _resolve_environment,
}


def _resolve_project(run, org) -> Optional[Link]:
    """Fallback: link to the run's own project when no typed ref resolves."""
    try:
        project = getattr(run, "project", None)
        if project is None:
            return None
        # Org-scope: only link if the project belongs to the org (when given).
        if org is not None and getattr(project, "org_id", None) != _org_pk(org):
            return None
        slug = getattr(project, "slug", None)
        if not slug:
            return None
        return Link(object=project, url=f"/projects/{slug}/", kind="Project",
                    label=getattr(project, "name", slug))
    except Exception:  # noqa: BLE001
        return None


def resolve(run, request_or_org=None) -> Optional[Link]:
    """Resolve ``run``'s (ref_type, ref_id) to a :class:`Link`, or None.

    Org-scoped when ``request_or_org`` (a request or an Org) is supplied: a
    cross-org ref will not produce a URL. Always fallback-safe: unknown
    ref_type, missing ref_id, empty ref_type, deleted rows -> None, never raises.
    """
    try:
        org = _org_from(request_or_org)
        ref_type = (getattr(run, "ref_type", "") or "").strip()
        ref_id = getattr(run, "ref_id", None)

        if ref_type and ref_id is not None:
            resolver = _RESOLVERS.get(ref_type)
            if resolver is not None:
                link = resolver(ref_id, org)
                if link:
                    return link
        # Fall back to the run's own project (loop-safe default).
        return _resolve_project(run, org)
    except Exception:  # noqa: BLE001 - resolution must never raise
        return None
