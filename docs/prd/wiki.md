# PRD — Docs / Wiki (`wiki/` app)

Sprint 1 (build-out, refreshed) · Section PM: Docs/Wiki · Status: **partially shipped — closing gaps**

> The `wiki/` app already exists, is migrated, org-scoped, and committed (commit
> `838d287`). Spaces, hierarchical markdown pages, history/revisions, search,
> `[[wikilink]]` backlinks, and a safe self-contained markdown renderer are all
> **DONE**. This refresh records the verified current state and scopes the
> remaining high-impact gaps a builder picks up THIS sprint. Everything stays
> additive; the autonomous incident→fix loop is never touched.

---

## 1. Problem

Hull crews (human + agent) generate operational knowledge constantly — runbooks,
architecture notes, postmortems, onboarding guides, decision records — but it
lives in scattered Slack threads, README files, and agent transcripts. Hull's
roadmap bar for this section is a **Confluence-grade wiki** that is multitenant,
hierarchical, markdown-native, searchable, versioned, and — critically —
**linked to the work it documents** (code/projects, PRs, incidents).

The wiki shell is built. Two roadmap-defining capabilities are still missing:

1. **Linking to code/PRs/incidents.** The roadmap names this explicitly
   ("linking to code/PRs/incidents") and it is the seam that weaves Docs into the
   autonomous loop's artifacts. Today `wiki.PageLink` only models page→page
   `[[wikilinks]]`; `Page.project` exists as a FK but is never rendered, and
   there is no way to attach a PR or Incident to a page. **Gap.**
2. **Activity-feed narration.** Every other Hull section emits
   `core.models.Event.log(...)` so the demo narrates itself. Wiki emits nothing
   on page create/edit. **Gap.**

This refresh closes both, keeping `org` nullable so any non-request
(agent/service) path keeps working.

---

## 2. User stories

Shipped (verified) — kept for completeness:

1. As a **member**, I create a **Space** so docs are grouped by area. ✅
2. As a **member**, I create a **markdown page** under a Space and optional
   **parent page** (tree). ✅
3. As a **member**, I view a page with markdown rendered to safe HTML, a tree
   sidebar, and breadcrumbs. ✅
4. As a **member**, I edit a page (full-page or HTMX edit-in-place); the prior
   content is snapshotted as a **revision**. ✅
5. As a **member**, I open a page's **history**, view a revision, and **restore**
   it. ✅
6. As a **member**, I **search** my org's pages by title/body. ✅
7. As a **member**, I write `[[Another Page]]` wikilinks; resolved links render
   as hyperlinks, unresolved ones as red links, and "Linked from" backlinks show
   on the target. ✅
8. As **Org A**, I never see Org B's spaces/pages/revisions/search/links. ✅
9. As an **agent/service** (no request, no org), wiki code never crashes the loop
   (`org=None`). ✅

To build THIS refresh:

10. As a **member**, on a page I **attach a link to a Project, a PR, or an
    Incident**, and the page detail renders those targets as deep links into the
    Projects / VCS / Observability sections — so a runbook points at the code,
    the PR that changed it, and the incident it resolved.
11. As an **operator watching the demo**, when someone **creates or edits a wiki
    page**, an entry appears in Hull's **activity feed** so the wiki narrates
    itself like every other section.

---

## 3. Current state vs target

| Capability | Current state | Target (this refresh) |
|---|---|---|
| Spaces (CRUD-ish: list/create/view) | DONE | unchanged |
| Hierarchical markdown pages (tree, parent FK) | DONE | unchanged |
| Safe markdown render + lib-optional fallback | DONE | unchanged |
| Page history / revisions / restore | DONE | unchanged |
| Search (org-scoped `icontains`) | DONE | unchanged |
| `[[wikilink]]` page→page links + backlinks | DONE | unchanged |
| Tenant isolation (`@org_required` + `scoped`) | DONE (verified: no unscoped `.objects` in views) | unchanged |
| Migrations / `manage.py check` clean | DONE (verified) | stays clean |
| **Link page → Project / PR / Incident** | **MISSING** (`PageLink` is page-only; `Page.project` unrendered; no PR/Incident link) | **BUILD**: typed external link + render as deep links on page detail |
| **Activity-feed emission on create/edit** | **MISSING** (no `Event.log` anywhere in `wiki/`) | **BUILD**: best-effort `Event.log` on page create + edit |
| Revision **diff** between two versions | MISSING (history shows whole revisions only) | **STRETCH** (scope-out unless time remains) |

---

## 4. Scope

### Scope-in (build THIS refresh)

1. **External page links (Project / PR / Incident).** Extend the page→external
   linking story. Two acceptable implementations (builder picks the lower-risk
   one that keeps the existing `PageLink` page→page semantics intact):
   - **Preferred:** a new model `PageRef(OrgScopedModel)` with `page` FK and
     nullable FKs `project` (→ `projects.Project`), `pull_request`
     (→ `vcs.PullRequest`), `incident` (→ `observability.Incident`), plus an
     optional free-text `label`. Keeps `PageLink` untouched (still page→page).
   - **Alternative:** extend `PageLink` with a `kind` choice
     (`page`/`project`/`pr`/`incident`) + nullable target FKs. Must not regress
     the existing `[[wikilink]]` / backlinks behavior or rubric items for them.
   - All target FKs are **nullable** and resolved **defensively**: a missing or
     foreign-org target must never raise on the page view — it degrades to plain
     text or is hidden.
2. **Attach-link UI on page detail** (and/or page form): a small form (HTMX POST)
   to add a ref by selecting a Project / PR / Incident from the current org, and
   to remove a ref. A "References" / "Related work" card on the page view lists
   refs, each a hyperlink to the target's own URL
   (`project.get_absolute_url()` or `/projects/<slug>/`,
   `pull_request.get_absolute_url()` → `/vcs/pr/<pk>/`,
   `incident.get_absolute_url()` → `/obs/incidents/<pk>/`). Targets are scoped to
   `request.org`.
3. **Activity-feed emission.** On page **create** and **edit/save** (full-page,
   HTMX inline, and restore paths), call
   `core.models.Event.log(verb=..., actor=request.user, level="info"|"success",
   icon="log", url=page.get_absolute_url())`, **wrapped in try/except** so an
   Event failure can never break the save or the loop. Pass `project=page.project`
   when set. Use a verb like `created doc` / `edited doc`.
4. **Keep it tenant-safe + loop-safe.** New model subclasses `OrgScopedModel`
   (`org` nullable); new views use `@org_required` + `scoped(...)`; nothing in
   `wiki/` is imported by `deploys/observability/orchestration/agents` services;
   `Event.log` import is best-effort.
5. **Migrations + check.** `makemigrations wiki` produces a clean migration; do
   NOT run `migrate`; `manage.py check` stays green.
6. **UI parity.** New templates/fragments `{% extends "base.html" %}` (or are
   HTMX fragments) and use helm.css classes (`card`, `list-row`, `btn`, `badge`).

### Scope-out (explicitly NOT this refresh)

- Revision **diff** view (whole-revision view + restore already ship). Stretch
  only.
- Real-time collaborative editing / presence; WYSIWYG editor.
- Comments / reactions / mentions on pages.
- Page-level RBAC beyond org membership; attachments / image uploads.
- Full-text ranked / fuzzy search, Postgres `SearchVector`.
- Backlinks **graph** visualization (refs are stored + listed, no graph).
- AI auto-generated docs from incidents (future loop integration).
- Auto-creating refs by parsing `#123` / `INC-4` tokens out of body text
  (explicit attach UI only this refresh).

---

## 5. Non-negotiables / guardrails (carry into every ticket)

- **Do NOT** edit `accounts/models.py`, `helm/urls.py`, `helm/settings.py`,
  `templates/base.html`, or any other app's files. All work stays in `wiki/`.
- New models subclass `accounts.models.OrgScopedModel`; `org` stays **nullable**.
- Request paths use `accounts.scoping.org_required` + `scoped(Model, request)` /
  `Model.objects.for_org(request.org)`. Cross-org access returns **404**.
- **Never break the autonomous loop:** nothing in `wiki/` is imported by
  `deploys/observability/orchestration/agents` services; cross-app FKs
  (Project/PR/Incident) are nullable + additive; `Event.log` is best-effort.
- Do NOT regress any currently-passing rubric item (spaces, pages, history,
  search, wikilinks, isolation, markdown safety).
- `python manage.py check` passes; `makemigrations wiki` only (no `migrate`).
- Markdown render stays safe + lib-optional (already shipped; don't weaken it).

---

## 6. Machine-checkable rubric (pass/fail)

Each item is independently verifiable. "PASS" = the stated check succeeds. Items
1–18 assert the **already-shipped** baseline must not regress; 19–26 cover the
**new** work this refresh.

1. **App exists**: `wiki/` contains `models.py`, `views.py`, `urls.py` (with
   `app_name = "wiki"`), `admin.py`, `apps.py`, `markdown.py`.
2. **Models org-scoped**: `Space`, `Page`, `PageRevision`, `PageLink` each
   `issubclass(..., accounts.models.OrgScopedModel)` (each has an `org` FK).
3. **org nullable**: `Space._meta.get_field("org").null is True` and likewise for
   `Page`.
4. **Hierarchy field**: `Page._meta.get_field("parent").related_model is Page`
   and `.null is True`.
5. **Page ↔ Space**: `Page` has FK `space` to `Space`.
6. **Revision model**: `PageRevision` has FK `page` to `Page` and a `body` text
   field; `Page.snapshot_revision(user)` creates one with an incrementing
   `number`.
7. **Wikilink model**: `PageLink` has FK `source` to `Page`, nullable FK `target`
   to `Page`, and `target_title`; `PageLink.is_resolved` reflects whether
   `target` is set.
8. **accounts not modified**: `accounts/models.py` is byte-for-byte the contract.
9. **Forbidden files untouched**: `helm/urls.py`, `helm/settings.py`,
   `templates/base.html` unchanged by the wiki workstream.
10. **Migrations present & clean**: `python manage.py makemigrations wiki
    --check --dry-run` reports **no** missing migrations after the work.
11. **System check clean**: `python manage.py check` exits 0.
12. **URLs resolve**: reversing `wiki:index`, `wiki:space`, `wiki:space_new`,
    `wiki:page`, `wiki:page_new`, `wiki:page_edit`, `wiki:page_history`,
    `wiki:revision`, `wiki:search` all succeed (no `NoReverseMatch`).
13. **Landing renders**: authed request with an active org to `/wiki/` returns 200.
14. **Create space**: POST to `wiki:space_new` with a name creates exactly one
    `Space` with `org == request.org`.
15. **Create page + revision**: POST to `wiki:page_new` with title + body + space
    creates a `Page` in that space (`org == request.org`) and ≥1 `PageRevision`.
16. **Markdown renders**: a page body `# Hello` produces output containing `<h1>`
    (rendered, not raw).
17. **Markdown sanitized**: a body containing `<script>alert(1)</script>` renders
    WITHOUT an executable `<script>` tag (escaped/stripped); render helper is
    lib-optional (calling it with `markdown` absent does not raise).
18. **Tenant isolation (baseline)**: a page in Org B returns **404** for Org A;
    Org B's pages do not appear in Org A's search; no view uses an unscoped
    `Page.objects.all()` / `Space.objects.all()` reaching a template
    (grep + test client with two orgs).
19. **External-ref model exists**: a model ties a `Page` to at least one of
    `projects.Project`, `vcs.PullRequest`, `observability.Incident` via **nullable**
    FKs, subclasses `OrgScopedModel`, and its `org` field is nullable (either new
    `PageRef`, or extended `PageLink` with `kind` + target FKs). CHECK:
    introspect `_meta`; each target FK `.null is True`.
20. **Attach a ref**: POSTing the attach-ref view with a page + a Project (or PR /
    Incident) in `request.org` creates exactly one ref row whose
    `org == request.org` and whose target id matches.
21. **Refs render as deep links**: the page detail view for a page with a Project
    ref returns 200 and the response contains a hyperlink to that target's URL
    (e.g. the project's `get_absolute_url()` / `/projects/<slug>/`, or for a PR
    `/vcs/pr/<pk>/`, or an incident `/obs/incidents/<pk>/`).
22. **Refs are org-scoped & defensive**: the attach-ref view only offers / accepts
    targets in `request.org` (a foreign-org target id is rejected or ignored), and
    rendering a page whose ref target was deleted/foreign does **not** raise (page
    view still 200s).
23. **Activity feed on create**: creating a page via `wiki:page_new` increases
    `core.models.Event` row count by ≥1 (a doc-create event).
24. **Activity feed on edit**: saving an edit (full-page `wiki:page_edit` OR HTMX
    `wiki:page_edit_inline`) increases `core.models.Event` row count by ≥1.
25. **Event emission is best-effort**: if `core.models.Event.log` is monkeypatched
    to raise, creating/saving a page still succeeds (the page is persisted; no
    500). CHECK: the `Event.log` call site is wrapped in try/except.
26. **Loop intact**: `python manage.py check` passes and `grep` shows no
    `import wiki` / `from wiki` in `deploys/services.py`,
    `observability/services.py`, `orchestration/service.py`,
    `agents/services.py`; importing those modules still succeeds with no wiki
    records present.

---

## 7. Acceptance gate (definition of done)

All 26 rubric items PASS. `python manage.py check` is clean, `makemigrations
wiki` yields a committed migration (no `migrate` run by this workstream), and an
end-to-end manual pass works: open an existing page → attach a Project + a PR +
an Incident → confirm each renders as a working deep link → edit the page and see
both a new revision AND a new activity-feed entry → confirm Org B still cannot see
the page or its refs. The autonomous incident→fix loop still runs green
(unchanged — wiki is not imported by any loop service).
