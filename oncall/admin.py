from django.contrib import admin

from .models import (
    ActionItem,
    EscalationPolicy,
    EscalationStep,
    Postmortem,
    RoutingRule,
    Schedule,
    ScheduleMember,
    TimelineEntry,
)

for _m in (
    Schedule,
    ScheduleMember,
    EscalationPolicy,
    EscalationStep,
    RoutingRule,
    TimelineEntry,
    Postmortem,
    ActionItem,
):
    try:
        admin.site.register(_m)
    except admin.sites.AlreadyRegistered:
        pass
