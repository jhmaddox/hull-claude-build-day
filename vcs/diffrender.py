"""Render a unified git diff into safe HTML using the Hull `.diff` component."""

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


def _render_file_block(lines: list[str]) -> str:
    """Render one file's diff lines (no surrounding container) into HTML."""
    out: list[str] = []
    for raw in lines:
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
    return "\n".join(out)


def _file_path_from_header(line: str) -> str:
    """Extract the b-path (new path) from a ``diff --git a/x b/y`` header."""
    parts = line.split(" b/", 1)
    if len(parts) == 2:
        return parts[1].strip()
    # Fallback: strip the ``diff --git `` prefix.
    return line[len("diff --git ") :].strip()


def split_diff(diff_text: str) -> list[dict]:
    """Split a unified diff into per-file entries (additive helper).

    Returns a list of dicts: ``{"path", "additions", "deletions", "html"}``.
    ``html`` is a safe string ready to drop into a ``.diff`` container. The
    original :func:`render_diff` is intentionally left untouched.
    """
    if not diff_text or not diff_text.strip():
        return []

    files: list[dict] = []
    current_path: str | None = None
    current_lines: list[str] = []

    def _flush():
        if current_path is None and not current_lines:
            return
        additions = sum(
            1
            for line in current_lines
            if line.startswith("+") and not line.startswith("+++")
        )
        deletions = sum(
            1
            for line in current_lines
            if line.startswith("-") and not line.startswith("---")
        )
        files.append(
            {
                "path": current_path or "(unknown)",
                "additions": additions,
                "deletions": deletions,
                "html": mark_safe(_render_file_block(current_lines)),
            }
        )

    for raw in diff_text.splitlines():
        if raw.startswith("diff --git"):
            _flush()
            current_path = _file_path_from_header(raw)
            current_lines = [raw]
        else:
            current_lines.append(raw)
    _flush()

    # Diff with no ``diff --git`` markers (rare) — keep it as a single block.
    if not files:
        files.append(
            {
                "path": "(diff)",
                "additions": sum(
                    1
                    for line in diff_text.splitlines()
                    if line.startswith("+") and not line.startswith("+++")
                ),
                "deletions": sum(
                    1
                    for line in diff_text.splitlines()
                    if line.startswith("-") and not line.startswith("---")
                ),
                "html": mark_safe(_render_file_block(diff_text.splitlines())),
            }
        )
    return files
