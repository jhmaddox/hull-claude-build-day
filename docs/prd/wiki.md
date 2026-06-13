# PRD — Docs / Wiki (`wiki/` app)

Sprint 1 · Section PM: Docs/Wiki · Status: ready for build

---

## 1. Problem

Hull crews (human + agent) generate operational knowledge constantly —
runbooks, architecture notes, postmortems, onboarding guides, decision records —
but it lives in scattered Slack threads, README files, and agent transcripts.
There is no org-scoped, searchable place inside Hull to write and find that
knowledge, and no way to link a doc to the code, PR, or incident it describes.

We need a **Confluence-grade wiki** that is:

- **Multitenant** — every Space and Page belongs to exactly one Org and is never
  visible across tenants.
- **Hierarchical** — pages nest under a Space and under parent pages (a tree).
- **Markdown-native** — write in markdown, render safely to HTML.
- **Searchable** — find a page by title or body across the org's spaces.
- **Versioned** — every save snapshots history; you can view prior revisions.
- **Linked to the work** — a page can reference Projects, PRs, and Incidents so
  the wiki is woven into the autonomous loop's artifacts.

**Hard constraint:** the autonomous incident → fix loop must keep working
untouched. Wiki is purely additive; `org` is nullable everywhere so any
non-request (agent/service) code path keeps functioning.

---

## 2. User stories

1. As a **member**, I create a **Space** ("Engineering", "Runbooks") so docs are
   grouped by area.
2. As a **member**, I create a **markdown page** inside a Space, optionally under
   a **parent page**, so knowledge is organized as a tree.
3. As a **member**, I view a page with its markdown rendered to clean HTML and a
   sidebar/breadcrumb showing where it sits in the tree.
4. As a **member**, I edit a page; the previous content is saved as a **revision**
   so nothing is lost.
5. As a **member**, I open a page's **history** and view any prior revision.
6. As a **member**, I **search** across all my org's pages by title/body and jump
   to a result.
7. As a **member**, I **link a page to a Project, PR, or Incident** so the doc is
   discoverable from / connected to the work it documents.
8. As a user of **Org A**, I never see Org B's spaces, pages, revisions, or search
   results (tenant isolation).
9. As an **agent/service** (no request, no org), wiki code never crashes the
   autonomous loop — services accept `org=None`.

---

## 3. Scope

### Scope-in (MVP — build THIS sprint)

- **Models** (all org-scoped via `accounts.models.OrgScopedModel`):
  - `Space`: name, slug (unique per org), description, icon/emoji, timestamps.
  - `Page`: space (FK), parent (self-FK, nullable), title, slug, markdown body,
    rendered HTML cache, author, position/order, timestamps.
  - `PageRevision`: page (FK), body snapshot, author, created_at, revision number.
  - `PageLink`: page (FK) + a typed link to a Project / PullRequest / Incident
    (store target kind + target id; resolve defensively so a missing/foreign
    target never errors).
- **Spaces**: list, create, view (lists root pages as a tree).
- **Pages**: create (under space, optional parent), view (rendered markdown +
  breadcrumb + child list), edit, delete (cascades children or reparents — pick
  cascade for MVP).
- **Markdown rendering**: server-side markdown → HTML, **sanitized** (no raw
  script injection). Use the `markdown` lib if available; otherwise a safe
  built-in fallback (never crash if the lib is missing).
- **History**: every page save creates a `PageRevision`; history list + view a
  single revision (read-only).
- **Search**: one search box; case-insensitive `icontains` over title + body,
  scoped to `request.org`; results page.
- **Linking**: from a page, attach links to Project / PR / Incident; render them
  on the page view with deep links to those sections.
- **Navigation**: a "Docs" entry reachable; wiki landing at `/wiki/`.
- **UI**: every template `{% extends "base.html" %}`, uses helm.css classes
  (`card`, `list-row`, `btn`, `badge`, `crumbs`, etc.), matches the dark theme.
- **Events**: emit `core.models.Event.log(...)` on page create/edit (icon e.g.
  `log` or `git`) so the activity feed narrates wiki activity.
- **Org scoping enforced**: all views use `@org_required` + `scoped(...)` /
  `.for_org(request.org)`; cross-org access returns 404, not another org's data.

### Scope-out (explicitly NOT this sprint)

- Real-time collaborative editing / presence.
- WYSIWYG rich-text editor (markdown textarea only).
- Comments / reactions / mentions.
- Page-level permissions beyond org membership (RBAC roles on pages).
- Attachments / image uploads / file storage.
- Full-text ranked search, fuzzy search, or Postgres `SearchVector`
  (plain `icontains` is enough for MVP).
- Diff view between two revisions (history is "view a revision", not a diff).
- Export (PDF/HTML), templates gallery, page moving via drag-and-drop.
- Backlinks graph / "knowledge vault" visualization (links are stored + shown,
  but no graph view).
- AI auto-generated docs from incidents (future loop integration).

---

## 4. Non-negotiables / guardrails (carry into every ticket)

- **Do NOT** edit `accounts/models.py`, `helm/urls.py`, `helm/settings.py`,
  `templates/base.html`, or any other app's files. New app lives entirely in
  `wiki/`. (Integrator registers the app + URL include.)
- New models subclass `accounts.models.OrgScopedModel`; `org` stays **nullable**.
- Request paths use `accounts.scoping.org_required` + `scoped(Model, request)` or
  `Model.objects.for_org(request.org)`.
- Keep the autonomous loop intact: nothing in `wiki/` is imported by
  `deploys/observability/orchestration/agents` services; no signals that touch
  those paths.
- `python manage.py check` passes; run `makemigrations wiki` (do NOT `migrate`).
- Markdown rendering must be **safe** (sanitized) and must **never** raise if the
  markdown library is absent — fall back gracefully.

---

## 5. Machine-checkable rubric (pass/fail)

Each item is independently verifiable. "PASS" = the stated check succeeds.

1. **App exists**: directory `wiki/` contains `models.py`, `views.py`,
   `urls.py` (with `app_name = "wiki"`), `admin.py`, and an `apps.py`.
2. **Models org-scoped**: `wiki.models.Space` and `wiki.models.Page` are
   subclasses of `accounts.models.OrgScopedModel`
   (`issubclass(Space, OrgScopedModel) and issubclass(Page, OrgScopedModel)` is
   True), so each has an `org` FK.
3. **org nullable**: the `org` field on both `Space` and `Page` has
   `null=True` (introspect `_meta.get_field("org").null is True`).
4. **Hierarchy field**: `Page` has a self-referential nullable `parent` FK to
   `Page` (`Page._meta.get_field("parent").related_model is Page` and
   `.null is True`).
5. **Page ↔ Space**: `Page` has a FK named `space` to `Space`.
6. **Revision model**: `wiki.models.PageRevision` exists with a FK `page` to
   `Page` and a text/body field holding the snapshot.
7. **Link model**: `wiki.models.PageLink` exists with a FK `page` to `Page` and
   fields identifying a target among Project / PR / Incident (e.g. a
   `target_kind` choice field + `target_id`, or nullable FKs).
8. **accounts not modified**: `accounts/models.py` is byte-for-byte unchanged
   from the contract (no edits committed by the wiki workstream).
9. **Forbidden files untouched**: `helm/urls.py`, `helm/settings.py`,
   `templates/base.html` are unchanged by the wiki workstream.
10. **Migrations present**: `wiki/migrations/` contains an initial migration
    creating Space, Page, PageRevision, PageLink; `manage.py makemigrations
    wiki --check --dry-run` reports no missing migrations.
11. **System check clean**: `python manage.py check` exits 0.
12. **URLs resolve**: reversing `wiki:home` (or the documented landing name),
    `wiki:space_list`, `wiki:page_detail`, `wiki:page_new`, `wiki:page_edit`,
    `wiki:page_history`, and `wiki:search` all succeed (no `NoReverseMatch`).
13. **Landing renders**: an authenticated request with an active org to `/wiki/`
    returns HTTP 200.
14. **Create space**: POST to the space-create view with a name creates exactly
    one `Space` whose `org == request.org`.
15. **Create page**: POST to the page-create view with title + body + space
    creates a `Page` in that space with `org == request.org` and one initial
    `PageRevision`.
16. **Markdown renders to HTML**: viewing a page whose body is `# Hello` produces
    output containing `<h1>` (rendered) — i.e. body is markdown-rendered, not
    shown raw.
17. **Markdown sanitized**: a page body containing
    `<script>alert(1)</script>` renders WITHOUT an executable
    `<script>alert(1)</script>` tag in the page view output (escaped or stripped).
18. **Markdown fallback safe**: importing/calling the render helper with the
    markdown lib unavailable does not raise (returns escaped/plain HTML).
19. **History captured**: editing a page (changing its body) increases its
    `PageRevision` count by at least 1; the previous body is retrievable from a
    revision.
20. **History view**: `wiki:page_history` for a page returns HTTP 200 and lists
    its revisions.
21. **Search works**: with a page titled/containing a unique token in
    `request.org`, GETting the search view with that token returns HTTP 200 and
    the response contains a link to that page.
22. **Search is org-scoped**: a page in Org B does NOT appear in Org A's search
    results for a shared token (cross-tenant isolation).
23. **Detail org-scoped**: requesting a page belonging to a different org returns
    HTTP 404 (not the foreign page's content).
24. **Linking**: a `PageLink` can be created tying a page to a Project (or PR /
    Incident); the page detail view renders the linked target with a hyperlink to
    that section's URL.
25. **Org filtering in views**: every wiki list/detail view filters by
    `request.org` (uses `scoped(...)` or `.for_org(request.org)`); no view
    returns objects across orgs. (grep: no unscoped `Page.objects.all()` /
    `Space.objects.all()` reaches a template context.)
26. **Decorator applied**: wiki views are guarded by `accounts.scoping`
    (`org_required`); an unauthenticated / org-less request is redirected (not a
    500). (grep for `org_required` usage on views.)
27. **Templates extend base**: every template under
    `wiki/templates/wiki/` starts from `{% extends "base.html" %}` and references
    helm.css classes (no standalone `<html>` docs).
28. **Activity feed wired**: creating or editing a page emits a
    `core.models.Event` row (Event count increases after a page create).
29. **Autonomous loop intact**: `wiki/` is NOT imported by `deploys.services`,
    `observability.services`, `orchestration.service`, or `agents.services`
    (grep: those modules contain no `import wiki` / `from wiki`).
30. **No raw template injection**: rendered page HTML is inserted via a method
    that is sanitized server-side (the view/template does not `|safe` raw
    unsanitized user body — only the sanitized rendered HTML is marked safe).

---

## 6. Acceptance gate (sprint definition of done)

All 30 rubric items PASS, `python manage.py check` is clean, `makemigrations
wiki` produces a committed migration, and an end-to-end manual pass works:
create space → create nested page (markdown) → edit it (history grows) →
search finds it → link it to a Project/PR/Incident → confirm Org B cannot see it.
The autonomous incident→fix loop still runs green (unchanged).
</content>
</invoke>
