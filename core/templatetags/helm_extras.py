from django import template
from django.utils.safestring import mark_safe

register = template.Library()

_ICONS = {
    "dot": "•",
    "project": "▤",
    "deploy": "▲",
    "agent": "✦",
    "pr": "⑂",
    "incident": "⚠",
    "merge": "⑃",
    "rocket": "🚀",
    "check": "✓",
    "x": "✕",
    "git": "⑂",
    "fix": "🔧",
    "alert": "🚨",
    "log": "▤",
    "test": "🧪",
}


@register.filter
def feed_icon(name):
    return _ICONS.get(name, "•")


@register.filter
def status_badge(status):
    """Return a badge CSS class for a status string."""
    s = (status or "").lower()
    if s in ("live", "ready", "passed", "done", "healthy", "merged", "success", "resolved"):
        return "badge-success"
    if s in ("failed", "firing", "unhealthy", "error", "closed", "sev1"):
        return "badge-danger"
    if s in ("building", "queued", "running", "pending", "remediating", "importing", "creating", "acknowledged", "sev2"):
        return "badge-warn"
    return "badge-neutral"


@register.filter
def pct(value, total):
    try:
        return round(100.0 * float(value) / float(total), 1)
    except (ValueError, ZeroDivisionError, TypeError):
        return 0
