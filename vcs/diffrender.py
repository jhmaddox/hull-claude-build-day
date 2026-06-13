"""Render a unified git diff into safe HTML using the Helm `.diff` component."""

from __future__ import annotations

from django.utils.html import escape
from django.utils.safestring import mark_safe


def render_diff(diff_text: str) -> str:
    """Convert a unified diff into HTML lines with add/del/hunk/file-head classes."""
    if not diff_text or not diff_text.strip():
        return mark_safe('<div class="empty small">No changes.</div>')

    out: list[str] = ['<div class="diff">']
    for raw in diff_text.splitlines():
        line = escape(raw)
        if raw.startswith("diff --git") or raw.startswith("index "):
            out.append(f'<span class="line file-head">{line}</span>')
        elif raw.startswith("--- ") or raw.startswith("+++ "):
            out.append(f'<span class="line file-head">{line}</span>')
        elif raw.startswith("@@"):
            out.append(f'<span class="line hunk">{line}</span>')
        elif raw.startswith("+"):
            out.append(f'<span class="line add">{line}</span>')
        elif raw.startswith("-"):
            out.append(f'<span class="line del">{line}</span>')
        else:
            out.append(f'<span class="line">{line}</span>')
    out.append("</div>")
    return mark_safe("\n".join(out))
