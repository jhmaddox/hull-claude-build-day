"""Alert routing: match an incident to a RoutingRule within its org.

``route`` must be safe when ``incident.org`` is None and must NEVER return a
rule from another org.
"""

from __future__ import annotations

# Lower rank == more severe. Used so a rule with min_severity=sev2 also matches
# a (more severe) sev1 incident.
_SEV_RANK = {"sev1": 1, "sev2": 2, "sev3": 3}


def _rank(sev):
    return _SEV_RANK.get((sev or "").lower(), 99)


def route(incident):
    """Return the first matching :class:`oncall.models.RoutingRule`, or None.

    Matching, in priority/order:
      * scoped to ``incident.org`` (never cross-org);
      * the incident's severity is at least as severe as ``min_severity``;
      * the rule's optional ``project`` filter is empty or equals the
        incident's project.
    Never raises.
    """
    try:
        from oncall.models import RoutingRule

        org = getattr(incident, "org", None)
        inc_rank = _rank(getattr(incident, "severity", None))
        inc_project_id = getattr(incident, "project_id", None)

        qs = RoutingRule.objects.all()
        # Strict org scoping. When the incident has no org, only consider
        # org-less rules so we never leak another tenant's routing.
        qs = qs.filter(org=org)
        qs = qs.order_by("priority", "id")

        for rule in qs:
            if _rank(rule.min_severity) < inc_rank:
                # Rule only handles things at least as severe as min_severity;
                # incident is less severe than the rule's floor -> skip.
                continue
            if rule.project_id and rule.project_id != inc_project_id:
                continue
            return rule
        return None
    except Exception as exc:  # pragma: no cover - defensive
        print(f"[helm-oncall] routing.route failed: {exc}")
        return None


def first_oncall_user(incident):
    """Resolve the first on-call user for an incident via its routed policy.

    rule -> policy -> first step -> target schedule -> current_oncall.user.
    Returns ``None`` if anything is missing. Never raises.
    """
    try:
        rule = route(incident)
        if rule is None or rule.policy_id is None:
            return None
        steps = rule.policy.ordered_steps()
        if not steps:
            return None
        schedule = steps[0].target_schedule
        if schedule is None:
            return None
        member = schedule.current_oncall()
        return getattr(member, "user", None) if member else None
    except Exception as exc:  # pragma: no cover
        print(f"[helm-oncall] routing.first_oncall_user failed: {exc}")
        return None
