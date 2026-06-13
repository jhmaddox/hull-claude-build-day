# PRD — Projects (multitenant)

**Section owner:** Projects PM
**Sprint:** 1 (Build-out: make every section org-scoped + ship features in parallel)
**App:** `projects/`
**Status:** Ready for build

---

## 1. Problem

Hull is now multi-tenant: every user belongs to one or more `accounts.Org`, the
active org is on `request.org` (set by `CurrentOrgMiddleware`), and the whole
product is supposed to be org-scoped. But `projects/` predates tenancy:

- `projects.Project` has **no `org` field** at all. Every project is global.
- `projects.views` query `Project.objects.all()` and `get_object_or_404(Project, slug=...)`
  with **no org filter**, so any logged-in user from any org sees and can open
  **every** project in the entire install. This is a cross-tenant data leak.
- `import_project` (UI + `orchestration.service`) never associates the created
  project (or its environments) with an org.
- `Project.slug` is **globally unique**, so two orgs can never have a project
  with the same slug (e.g. both want "api"). Tenancy demands per-org slug space.
- The multi-project UX is thin: a flat card grid with no per-org framing, no
  empty-state that explains the active org, and no quick at-a-glance health.

**Hard constraint:** the autonomous incident -> fix loop runs with **no HTTP
request** (no `request.org`). It calls `projects.services.import_project(...)`,
`orchestration.service.*`, etc. Those paths must keep working with `org=None`.
All changes must be **additive with fallbacks**; never break the loop.

---

## 2. User stories

- **As a member of an org**, when I open `/projects/` I see only my org's
  projects — never another org's.
- **As a member of an org**, when I import a project it is automatically tagged
  to my current org, and immediately appears in my list (and nobody else's).
- **As a member of an org**, I cannot open, deploy, or otherwise act on a
  project that belongs to a different org (I get a 404, not someone else's data).
- **As a user with no active org**, hitting projects pages redirects me to
  onboarding instead of leaking the global list.
- **As an org with the same naming taste as another org**, I can use a project
  slug (e.g. `api`) that another org already uses, without collision.
- **As an operator**, the autonomous loop and any service-level
  `import_project` call still succeed when there is no request/org (org=None),
  so the crown-jewel demo never regresses.
- **As a member juggling several projects**, the list shows which org I'm in,
  a count, per-project framework + live-env health, and a clean empty state.

---

## 3. Scope — IN (this sprint, MVP)

1. **`Project` becomes org-scoped** by subclassing
   `accounts.models.OrgScopedModel` (adds nullable `org` FK + `OrgManager`).
   Org stays **nullable** (loop safety). Generate a migration via
   `makemigrations projects` (do NOT run `migrate`).
2. **Per-org slug uniqueness.** Drop the global `unique=True` on `slug`; enforce
   uniqueness per `(org, slug)` instead (via `Meta.constraints` /
   `unique_together`), and make `services._unique_slug` org-aware so generated
   slugs are unique **within the org**.
3. **List view scoped** to `request.org` using the tenancy contract
   (`org_required` + `Project.objects.for_org(request.org)` or
   `scoped(Project, request)`). No project from another org is ever rendered.
4. **Detail / deploy views scoped.** Project lookup is constrained to
   `request.org`; a project from another org returns **404**. Apply
   `org_required`.
5. **Import stamps the org.** The UI import path passes the current org so the
   created `Project` (and its `Environment`s, if they become org-scoped by their
   own section) is tagged to `request.org`. The service signature change is
   **additive** (`org=None` default) so existing/loop callers are unaffected.
6. **Multi-project UX polish** on `/projects/` and `/projects/new/`: show the
   active org name in the header, a project count, per-card framework + live-env
   badges (reuse existing), and an org-aware empty state. Extend `base.html` via
   `{% extends %}`; reuse `helm.css` classes only.
7. **Tests** in `projects/tests.py` proving cross-tenant isolation
   (list/detail), import tagging, org=None loop safety, and per-org slug reuse.

## 3b. Scope — OUT (explicitly deferred)

- Moving/transferring a project between orgs.
- Per-project RBAC (who within an org can deploy/delete) — accounts/RBAC owns it.
- Project archival/delete, rename, settings page.
- Org-scoping `deploys.Environment` / `agents` / `vcs` / `observability` models —
  each is owned by its own section PM this sprint; Projects only scopes
  `Project` and reads related objects through the (already project-scoped) FKs.
- Backfilling existing global projects to a specific org (org stays null; they
  remain loop-visible, hidden from org-scoped list views — acceptable for MVP).
- Modifying `accounts/` in any way (contract is frozen).

---

## 4. Implementation notes / contract adherence

- **Import the contract, do not reinvent it.** Use
  `from accounts.models import OrgScopedModel`,
  `from accounts.scoping import org_required, scoped`.
- **Do NOT modify `accounts/models.py`** or any other app's files.
- **Loop safety pattern:** services accept `org=None`; when called from a view,
  pass `request.org`; when called from the loop/orchestration with no org, the
  default keeps behavior identical to today. `OrgScopedQuerySet.for_org(None)`
  returns the full queryset, and `scoped()` returns `.none()` for anonymous —
  use `org_required` so request paths always have an org.
- **`orchestration.service.import_project`** must keep its current public
  signature working; if Projects extends it, the new org param is keyword-only
  with default `None` and the UI fallback in `projects/views._import_in_background`
  stays additive.
- Run `python manage.py check` and `makemigrations projects`; never `migrate`.
- Match dark UI in `static/css/helm.css`; `{% extends "base.html" %}` only;
  `{% load helm_extras %}` for `status_badge` / `pct`.
- Emit `core.models.Event.log(...)` on import as today (keep `project=` kwarg).

---

## 5. Machine-checkable rubric (pass/fail)

Each item is objectively verifiable by grep/AST/Django shell/test run.

1. **R1 — Project is org-scoped model.** `projects/models.py` has
   `class Project(OrgScopedModel)` and imports `OrgScopedModel` from
   `accounts.models`. `Project._meta.get_field("org")` exists, is a FK to
   `accounts.Org`, and `null=True`.
   *Check:* `python -c "import django,os; os.environ.setdefault('DJANGO_SETTINGS_MODULE','helm.settings'); django.setup(); from projects.models import Project; f=Project._meta.get_field('org'); print(f.null, f.related_model.__name__)"` -> `True Org`.

2. **R2 — accounts is not modified.** `git diff --name-only` (or equivalent)
   shows **no** changes under `accounts/`.
   *Check:* `git diff --stat` contains no path starting with `accounts/`.

3. **R3 — Slug not globally unique; unique per org.** The `slug` field is no
   longer `unique=True`; uniqueness is enforced on `(org, slug)` via a
   `UniqueConstraint`/`unique_together`.
   *Check:* `Project._meta.get_field('slug').unique is False` AND a constraint
   covering `("org","slug")` exists in `Project._meta.constraints` or
   `Project._meta.unique_together`.

4. **R4 — Migration generated, not applied.** A new migration file exists under
   `projects/migrations/` adding the `org` field (and slug constraint change),
   and `python manage.py makemigrations projects --check --dry-run` reports **no
   pending model changes** afterwards. `migrate` was NOT run by the builder.
   *Check:* new file present in `projects/migrations/`; `--check --dry-run`
   exits 0.

5. **R5 — List view is org-scoped & guarded.** `projects.views.project_list`
   is decorated with `org_required` and queries via `for_org(request.org)` /
   `scoped(Project, request)` (NOT bare `Project.objects.all()`).
   *Check:* grep shows `@org_required` above `project_list` and the query uses
   `for_org(` or `scoped(`; no `Project.objects.all()` in `project_list`.

6. **R6 — Detail view is org-scoped & guarded.** `project_detail` is decorated
   with `org_required` and the project lookup is constrained to `request.org`
   (e.g. `get_object_or_404(Project.objects.for_org(request.org), slug=slug)`).
   *Check:* grep shows `@org_required` above `project_detail` and the lookup
   passes an org-filtered queryset/manager, not bare `Project`.

7. **R7 — Deploy view is org-scoped & guarded.** `project_deploy` is decorated
   with `org_required` and resolves the project scoped to `request.org`.
   *Check:* grep shows `@org_required` above `project_deploy` and an
   org-filtered lookup.

8. **R8 — Cross-tenant isolation (list).** Test: org A has project P_A, org B
   has project P_B; a user in org B requesting `/projects/` gets a response
   whose context/HTML contains P_B and NOT P_A.
   *Check:* test in `projects/tests.py` asserts this and passes.

9. **R9 — Cross-tenant isolation (detail = 404).** Test: a user in org B
   requesting `/projects/<P_A.slug>/` receives **HTTP 404**.
   *Check:* test asserts `status_code == 404` and passes.

10. **R10 — Import tags the active org.** Test: a logged-in user in org B
    triggers the import code path with `request.org = org_B`; the resulting
    `Project.org_id == org_B.id`. (May call the service directly with the org
    arg, mirroring the view, to avoid network clone in tests.)
    *Check:* test asserts created project's `org` equals the acting org; passes.

11. **R11 — Loop safety: org=None still works.** Calling
    `projects.services.import_project(name, repo_url)` (no org) and
    `orchestration.service.import_project(name, repo_url)` (no org) must NOT
    raise a TypeError/signature error and must produce a `Project` with
    `org is None`. The autonomous loop entry points are unchanged in signature
    (org param, if added, is keyword-only with default None).
    *Check:* `inspect.signature(projects.services.import_project)` has no new
    *required* params; a test creates a project via the service with no org and
    asserts `project.org is None`.

12. **R12 — Per-org slug reuse.** Test: importing/creating a project named
    "api" in org A and another named "api" in org B yields two projects, both
    slug `api` (no `-2` suffix forced across orgs), each with the correct org.
    *Check:* test asserts both `slug == "api"` and distinct orgs; passes.
    (`services._unique_slug` is org-aware.)

13. **R13 — No anonymous/global leak.** An unauthenticated request to
    `/projects/` redirects (302) to login; an authenticated user with **no**
    membership/org is redirected to `accounts:onboarding` (never shown the
    global list).
    *Check:* test asserts 302 to login for anon and 302 to onboarding for
    org-less user; passes.

14. **R14 — System check clean.** `python manage.py check` exits 0 with no
    errors introduced by projects.
    *Check:* command exits 0.

15. **R15 — UI contract honored.** `projects/templates/projects/list.html`
    still `{% extends "base.html" %}` and shows the active org name and a
    project count in the header; only `helm.css` classes are used (no new CSS
    files, no heavy JS). `base.html` and `helm.css` are unmodified.
    *Check:* grep shows `{% extends "base.html" %}` and a reference to the org
    (e.g. `request.org` / `org`) in the list header; `git diff` shows no change
    to `templates/base.html` or `static/css/helm.css`.

16. **R16 — Autonomous loop intact (regression gate).** The end-to-end
    incident -> fix loop test/path still passes (no change to
    `deploys.services`, `observability.services`, `orchestration.service`
    public signatures beyond additive keyword-only org defaults; no removed
    functions).
    *Check:* existing loop test passes; `git diff` of those service files shows
    only additive changes (new optional kwargs / new lines), no signature
    breaks or deletions.

---

## 6. Definition of done

All R1–R16 pass. `projects/` is fully org-scoped, the multi-project list/detail
honor `request.org`, imports tag the active org, per-org slugs work, the dark UI
is preserved, and the autonomous incident -> fix loop is provably unbroken.
