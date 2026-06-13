"""Server-side markdown rendering for the wiki.

Self-contained so the app adds **no new dependency** (the project does not ship
``markdown``/``bleach``). If the ``markdown`` package is ever installed we prefer
it; otherwise we fall back to a small, safe, HTML-escaping renderer that covers
the common subset: headings, bold/italic/code, fenced + inline code, links,
images, blockquotes, unordered/ordered lists, horizontal rules, ``[[wiki links]]``
and paragraphs.

Everything is HTML-escaped first, so user content can never inject markup — the
output is safe to mark ``|safe`` in templates.
"""

from __future__ import annotations

import html
import re

WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")


def extract_wikilinks(body: str):
    """Return the distinct ``[[Target]]`` titles referenced in ``body``."""
    seen, out = set(), []
    for m in WIKILINK_RE.finditer(body or ""):
        title = m.group(1).split("|")[0].strip()
        if title and title.lower() not in seen:
            seen.add(title.lower())
            out.append(title)
    return out


def render_markdown(body: str, wikilink_resolver=None) -> str:
    """Render markdown ``body`` to a safe HTML string.

    ``wikilink_resolver`` (optional) maps a ``[[Title]]`` to a URL or ``None``.
    """
    if not body:
        return ""
    try:  # prefer a real library if present, but keep it optional
        import markdown as _md  # type: ignore

        html_out = _md.markdown(
            body, extensions=["fenced_code", "tables", "toc"], output_format="html5"
        )
        return _apply_wikilinks(html_out, wikilink_resolver, already_html=True)
    except Exception:  # noqa: BLE001 — any import/render issue -> fallback
        return _fallback_render(body, wikilink_resolver)


# --------------------------------------------------------------------------- #
# Fallback renderer (no external deps).
# --------------------------------------------------------------------------- #
_INLINE_CODE = re.compile(r"`([^`]+)`")
_BOLD = re.compile(r"\*\*([^*]+)\*\*")
_ITALIC = re.compile(r"(?<!\*)\*([^*]+)\*(?!\*)")
_IMG = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)\)")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")


def _inline(text: str, wikilink_resolver=None) -> str:
    # text is already HTML-escaped. Apply inline markdown.
    # Pull out inline code first so we don't format inside it.
    placeholders = {}

    def _stash(m):
        key = f"\x00{len(placeholders)}\x00"
        placeholders[key] = f"<code>{m.group(1)}</code>"
        return key

    text = _INLINE_CODE.sub(_stash, text)

    text = _IMG.sub(
        lambda m: f'<img alt="{m.group(1)}" src="{m.group(2)}">', text
    )
    text = _LINK.sub(
        lambda m: f'<a href="{m.group(2)}" rel="noopener">{m.group(1)}</a>', text
    )
    text = _BOLD.sub(r"<strong>\1</strong>", text)
    text = _ITALIC.sub(r"<em>\1</em>", text)
    text = _wikilinks_inline(text, wikilink_resolver)

    for key, val in placeholders.items():
        text = text.replace(key, val)
    return text


def _wikilinks_inline(text: str, resolver=None) -> str:
    def repl(m):
        raw = m.group(1)
        title, _, label = raw.partition("|")
        title, label = title.strip(), (label.strip() or title.strip())
        url = resolver(title) if resolver else None
        if url:
            return f'<a class="wikilink" href="{url}">{label}</a>'
        return f'<span class="wikilink wikilink-missing">{label}</span>'

    return WIKILINK_RE.sub(repl, text)


def _fallback_render(body: str, wikilink_resolver=None) -> str:
    lines = body.replace("\r\n", "\n").split("\n")
    out: list[str] = []
    i, n = 0, len(lines)
    list_stack: list[str] = []  # 'ul' / 'ol'

    def close_lists():
        while list_stack:
            out.append(f"</{list_stack.pop()}>")

    while i < n:
        line = lines[i]
        stripped = line.strip()

        # Fenced code block
        if stripped.startswith("```"):
            close_lists()
            i += 1
            buf = []
            while i < n and not lines[i].strip().startswith("```"):
                buf.append(html.escape(lines[i]))
                i += 1
            i += 1  # skip closing fence
            out.append("<pre class=\"code\"><code>" + "\n".join(buf) + "</code></pre>")
            continue

        # Blank line
        if not stripped:
            close_lists()
            i += 1
            continue

        esc = html.escape(line)
        esc_stripped = esc.strip()

        # Horizontal rule
        if re.fullmatch(r"(\*\s*){3,}|(-\s*){3,}|(_\s*){3,}", stripped):
            close_lists()
            out.append("<hr>")
            i += 1
            continue

        # Headings
        h = re.match(r"(#{1,6})\s+(.*)", esc_stripped)
        if h:
            close_lists()
            level = len(h.group(1))
            out.append(f"<h{level}>{_inline(h.group(2), wikilink_resolver)}</h{level}>")
            i += 1
            continue

        # Blockquote
        if esc_stripped.startswith("&gt; ") or esc_stripped == "&gt;":
            close_lists()
            content = re.sub(r"^&gt;\s?", "", esc_stripped)
            out.append(f"<blockquote>{_inline(content, wikilink_resolver)}</blockquote>")
            i += 1
            continue

        # Unordered list
        ul = re.match(r"[-*+]\s+(.*)", esc_stripped)
        if ul:
            if "ul" not in list_stack:
                close_lists()
                list_stack.append("ul")
                out.append("<ul>")
            out.append(f"<li>{_inline(ul.group(1), wikilink_resolver)}</li>")
            i += 1
            continue

        # Ordered list
        ol = re.match(r"\d+\.\s+(.*)", esc_stripped)
        if ol:
            if "ol" not in list_stack:
                close_lists()
                list_stack.append("ol")
                out.append("<ol>")
            out.append(f"<li>{_inline(ol.group(1), wikilink_resolver)}</li>")
            i += 1
            continue

        # Paragraph (gather consecutive non-blank, non-special lines)
        close_lists()
        para = [esc_stripped]
        i += 1
        while i < n and lines[i].strip() and not _is_block_start(lines[i].strip()):
            para.append(html.escape(lines[i].strip()))
            i += 1
        out.append("<p>" + _inline("<br>".join(para), wikilink_resolver) + "</p>")

    close_lists()
    return "\n".join(out)


def _is_block_start(stripped: str) -> bool:
    return bool(
        stripped.startswith("#")
        or stripped.startswith("```")
        or stripped.startswith(">")
        or re.match(r"[-*+]\s+", stripped)
        or re.match(r"\d+\.\s+", stripped)
        or re.fullmatch(r"(\*\s*){3,}|(-\s*){3,}|(_\s*){3,}", stripped)
    )


def _apply_wikilinks(html_out: str, resolver, already_html=False) -> str:
    return _wikilinks_inline(html_out, resolver)
