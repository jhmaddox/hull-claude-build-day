"""Single source of truth for a project's operational health verdict.

Derives a small, render-ready struct describing a Project's health by reading
its environments' current deployments and its open incidents. This is the one
place that defines what "live / degraded / down / never deployed" means so the
list cards and the detail header agree.

N+1 safety: reads ``env.deployments.all()`` and ``project.incidents.all()`` so
that, when the view prefetches those relations, no extra per-project queries are
issued. It never calls ``env.current_deployment`` (which would issue a fresh
query per env) — it derives the current deployment from the prefetched list.

Tolerates ``org=None`` projects and zero environments / zero deployments
without raising. Adds no model fields (no migration).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Tuple

NEVER_DEPLOYED = "never_deployed"
LIVE = "live"
DEGRADED = "degraded"
DOWN = "down"

_VERDICT_META = {
    NEVER_DEPLOYED: ("Never deployed", "badge-neutral"),
    LIVE: ("Live", "badge-success"),
    DEGRADED: ("Degraded", "badge-warn"),
    DOWN: ("Down", "badge-danger"),
}

_LIVE_STATUS = "live"
_STOPPED_STATUS = "stopped"
_RESOLVED_STATUS = "resolved"


@dataclass
class HealthVerdict:
    """Render-ready health summary for one project."""

    verdict: str = NEVER_DEPLOYED
    live_count: int = 0
    down_count: int = 0
    open_incident_count: int = 0
    envs: List[Tuple[str, str]] = field(default_factory=list)

    @property
    def label(self) -> str:
        return _VERDICT_META[self.verdict][0]

    @property
    def badge_class(self) -> str:
        return _VERDICT_META[self.verdict][1]

    @property
    def has_open_incidents(self) -> bool:
        return self.open_incident_count > 0


def _current_deployment(env):
    """Newest non-stopped deployment from the prefetched ``deployments``
    relation, or ``None``. Reading ``env.deployments.all()`` hits the prefetch
    cache so this stays O(1) per env with no extra query."""
    current = None
    for dep in env.deployments.all():
        if getattr(dep, "status", None) == _STOPPED_STATUS:
            continue
        created = getattr(dep, "created_at", None)
        if current is None:
            current = dep
            continue
        cur_created = getattr(current, "created_at", None)
        if created is not None and cur_created is not None and created > cur_created:
            current = dep
    return current


def health_verdict(project) -> HealthVerdict:
    """Compute the :class:`HealthVerdict` for ``project``.

    Rules:
      * no deployments anywhere            -> never_deployed
      * >=1 env live and none down         -> live
      * mixed live + down                  -> degraded
      * has deployed envs but none live    -> down

    Tolerates zero environments and ``org=None`` defensively: never raises.
    """
    result = HealthVerdict()

    try:
        environments = list(project.environments.all())
    except Exception:  # noqa: BLE001
        environments = []

    deployed_any = False
    for env in environments:
        dep = _current_deployment(env)
        if dep is None:
            continue
        deployed_any = True
        if getattr(dep, "status", None) == _LIVE_STATUS:
            result.live_count += 1
            result.envs.append((env.name, "live"))
        else:
            result.down_count += 1
            result.envs.append((env.name, "down"))

    try:
        result.open_incident_count = sum(
            1
            for inc in project.incidents.all()
            if getattr(inc, "status", None) != _RESOLVED_STATUS
        )
    except Exception:  # noqa: BLE001
        result.open_incident_count = 0

    if not deployed_any:
        result.verdict = NEVER_DEPLOYED
    elif result.live_count and not result.down_count:
        result.verdict = LIVE
    elif result.live_count and result.down_count:
        result.verdict = DEGRADED
    else:
        result.verdict = DOWN

    return result
