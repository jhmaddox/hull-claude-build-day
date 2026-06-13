# PRD — Projects (multitenant)

**Section owner:** Projects PM
**Sprint:** 1 (Build-out: org-scope every section + ship features in parallel)
**App:** `projects/`
**Status:** Tenancy foundation SHIPPED (locked as regression gate); this sprint
ships the multi-project UX layer on top.

---

## 1. Problem

Hull is multi-tenant: every user belongs to one or more `accounts.Org`, the
active org is on `request.org` (set by `CurrentOrgMiddleware`), and the product
is org-scoped.

**Part A — tenancy (DONE, now a regression invariant).** `projects.Project`
already subclasses `accounts.models.OrgScopedModel`, list/detail/deploy views
are `@org_required` + scoped to `request.org`, imports stamp the acting org,
slugs are unique per `(org, slug)`, and a migration exists. These behaviors
**must not regress** (rubric R1–R10 below). Do not re-do them; protect them.

**Part B — multi-project UX (the gap THIS sprint closes).** An org running a
real stack has 5–30 projects. Today `/projects/` is a flat unscoped-feeling card
grid with **no way to find or triage at scale**:

- **No search / no filter.** With more than a handful of projects you scroll and
  eyeball. There is no name/repo search and no "show me only what's broken /
  importing / not-yet-deployed" filter.
- **No portfolio health.** A member can't answer "how many of my projects are
  live? how many failed import? how many have an open incident?" without opening
  each one. There's no summary the way the rest of Hull (deploys/obs) has stat
  strips.
- **Thin per-card health.** A card shows env count + "live" pills but not a
  single at-a-glance health verdict (healthy / degraded / down / never
  deployed), and nothing about open incidents on the project.
- **Detail page has no health rollup.** The detail header shows framework +
  branch + import status but not a deployment-health summary, so the operator
  still has to read the table to know if prod is up.

All of this must stay **org-scoped** (a filter/search must never widen beyond
`request.org`) and **loop-safe** (the autonomous incident→fix loop runs with no
request/org; nothing here may touch `projects.services.import_project`,
`orchestration.service.*`, or other service signatures except additively).

---

## 2. User stories

Tenancy (regression — keep working):
- As a member of an org, `/projects/` shows only my org's projects; opening
  another org's project 404s; imports auto-tag my active org; another org and I
  can both have an `api` project.
- As a user with no active org, projects pages send me to onboarding, never the
  global list. As the autonomous loop, `import_project(...)` with no org still
  produces a project with `org is None`.

Multi-project UX (this sprint):
- **As a member with many projects**, I can type in a search box and the list
  narrows to projects whose name or repo/path matches — within my org only.
- **As a member triaging**, I can click a status filter (All / Ready / Importing
  / Failed) and see only matching projects, scoped to my org.
- **As a member**, the top of `/projects/` shows a portfolio strip: total
  projects, # live, # with a failed import, and # with open incidents — for my
  org only.
- **As a member scanning cards**, each project card shows a single health verdict
  badge (Live / Degraded / Down / Never deployed) and an open-incident count if
  any, so I can triage without opening it.
- **As a member on a project page**, the detail header shows a health rollup
  (e.g. "prod live · staging down") so I know the state before reading the table.
- **As a member**, an empty search/filter result shows a clear "no projects match"
  state (distinct from "no projects yet"), with a one-click reset.

---

## 3. Scope — IN (this sprint, MVP)

All work is in `projects/` only; additive; reuses `helm.css`; no new CSS files,
no JS framework (HTMX already in `base.html`; plain GET form is also fine).

1. **Org-scoped search + status filter on the list.** `project_list` reads
   `?q=` (name/repo/path substring, case-insensitive) and `?status=` (one of
   `ready|importing|failed`, else all). Filtering is applied **after**
   `Project.objects.for_org(request.org)` so it can never cross tenants. The
   list template renders a search input + status segмented control (links/GET);
   current `q`/`status` are preserved/echoed. No new URL route required (same
   `/projects/`, querystring only).
2. **Portfolio health summary strip** at the top of `/projects/`, computed from
   the org-scoped queryset: total projects, # live (≥1 env's current deployment
   `status == 'live'`), # failed import (`status == 'failed'`), # with ≥1 open
   incident (incident `status != 'resolved'`). Uses `.stat` / `grid-auto` /
   `badge-*` classes. Counts reflect the **unfiltered** org set (so the strip is
   a stable portfolio view) — filtering affects only the card grid below.
3. **Per-card health verdict + incident count.** Each card shows one health
   badge derived from its environments' current deployments:
   `Live` (badge-success) if any env live and none unhealthy/down;
   `Degraded` (badge-warn) if some live and some not / unhealthy;
   `Down` (badge-danger) if it has deployed envs but none live;
   `Never deployed` (badge-neutral) if no deployments. Plus an
   `N open incident(s)` badge when > 0. Verdict logic lives in a small helper
   (model method/property or a template-tag/util in `projects/`) so it's testable
   and reusable on the detail page.
4. **Detail-page health rollup** in the project header: a compact per-env state
   summary (e.g. `prod ● live`, `staging ○ down`) and the open-incident count,
   reusing the same verdict helper. Additive to the existing header row.
5. **Distinct empty states.** The list distinguishes "this org has no projects
   yet" (existing import CTA) from "no projects match your search/filter" (shows
   the active query + a "Clear" link back to `/projects/`).
6. **Tests** in `projects/tests.py` covering: search narrows within org and never
   leaks cross-tenant; status filter restricts correctly; summary counts are
   org-scoped and correct; health verdict helper returns the right verdict for
   live / mixed / down / never-deployed; empty-filter state. Plus the existing
   tenancy tests must still pass.

## 3b. Scope — OUT (explicitly deferred)

- Pagination / infinite scroll (counts are small for the demo; filter suffices).
- Sorting controls, saved views, favorites/pinning.
- Moving/transferring a project between orgs; archive/delete/rename/settings.
- Per-project RBAC (accounts/RBAC owns who-can-deploy).
- Org-scoping `deploys.Environment` / `agents` / `vcs` / `observability` models
  (each section PM owns its own; Projects reads related objects through the
  already project-scoped FKs).
- Backfilling existing org-less projects to an org (they stay `org=None`,
  loop-visible, hidden from org-scoped lists — acceptable).
- **Any** modification to `accounts/`, `helm/settings.py`, `helm/urls.py`,
  `templates/base.html`, `static/css/helm.css`, or other apps' files.
- **Any** change to `projects.services` / `orchestration.service` signatures
  beyond what already exists (no changes expected this sprint).

---

## 4. Implementation notes / contract adherence

- **Scope first, then filter.** Always start from
  `Project.objects.for_org(request.org)` (or `scoped(Project, request)`); apply
  `q`/`status` with `.filter(...)` on that queryset. Never build a query from
  bare `Project.objects.all()` in a request path. Sanitize `status` against the
  `Project.Status` values; ignore unknown values (fall back to "all").
- **Health verdict helper is the single source of truth.** Implement one helper
  (e.g. `Project.health_verdict()` returning a small struct/string + the live/
  down/incident counts, or a `projects/health.py` util) and use it in both the
  card and the detail rollup. Compute from `env.current_deployment` and
  `project.incidents` via existing FKs/related names; prefetch envs +
  current deployments to avoid N+1 (extend the existing
  `prefetch_related("environments")`).
- **Loop safety.** No edits to `projects.services.import_project`,
  `orchestration.service.*`, `deploys.services`, `observability.services`,
  `agents.services`. The helper only *reads* related objects and must tolerate
  projects with `org=None` and zero environments without raising.
- **No migration needed** for this sprint's UX work (no model fields added). If a
  field is somehow introduced, run `makemigrations projects` only — never
  `migrate`. Run `python manage.py check` (must stay clean).
- **UI:** `{% extends "base.html" %}`; reuse `helm.css` classes
  (`stat`, `grid-auto`, `grid-3/4`, `card`, `badge-*`, `dot`, `dot-live`,
  `empty`, `field`, `btn`, `link`, `muted`, `mono`); `{% load helm_extras %}` for
  `status_badge`/`pct`. No new CSS file, no JS framework. base.html & helm.css
  stay byte-for-byte unchanged.
- Keep emitting `core.models.Event.log(...)` on import exactly as today.

---

## 5. Machine-checkable rubric (pass/fail)

Each item is objectively verifiable by grep / AST / Django shell / `manage.py
test projects`. Builder is DONE only when all pass.

### Tenancy regression invariants (must remain true)

1. **R1 — Project is org-scoped.** `projects/models.py` has
   `class Project(OrgScopedModel)` importing `OrgScopedModel` from
   `accounts.models`; `Project._meta.get_field("org")` is a FK to `accounts.Org`
   with `null=True`.
   *Check:* `python -c "..."; f=Project._meta.get_field('org'); print(f.null, f.related_model.__name__)"` → `True Org`.

2. **R2 — Per-org slug uniqueness.** `Project._meta.get_field('slug').unique is
   False` AND a `UniqueConstraint`/`unique_together` covers `("org","slug")`.
   *Check:* assert both via Django shell or grep of `models.py`/migration.

3. **R3 — List/detail/deploy guarded & scoped.** `project_list`,
   `project_detail`, `project_deploy` are each decorated `@org_required` and
   resolve projects via `for_org(request.org)` / `scoped(Project, request)` —
   never bare `Project.objects.all()` / bare `get_object_or_404(Project, ...)`.
   *Check:* grep shows `@org_required` above all three and an org-filtered query
   in each; no unscoped `Project.objects.all()` or `get_object_or_404(Project,`
   in a request path.

4. **R4 — Cross-tenant isolation (list).** Org A has P_A, org B has P_B; a user
   in org B GET `/projects/` sees P_B, not P_A.
   *Check:* test passes.

5. **R5 — Cross-tenant isolation (detail = 404).** A user in org B GET
   `/projects/<P_A.slug>/` → HTTP 404.
   *Check:* test passes.

6. **R6 — Import tags active org; loop-safe.** UI/service import with org=B
   yields `Project.org_id == B.id`; calling
   `projects.services.import_project(name, repo_url)` with **no** org yields
   `project.org is None` and does not raise; the `org` param is keyword-only with
   default `None` (no new required params).
   *Check:* tests pass; `inspect.signature(...)` confirms keyword-only/default.

7. **R7 — Per-org slug reuse.** Projects named "api" in org A and org B both get
   slug `api` (no forced suffix across orgs); `services._unique_slug` is
   org-aware.
   *Check:* test passes.

8. **R8 — No anonymous/global leak.** Anon GET `/projects/` → 302 to login;
   authenticated user with no membership → 302 to `accounts:onboarding`.
   *Check:* test passes.

9. **R9 — accounts (and shared files) unmodified.** `git diff --name-only`
   contains **no** path under `accounts/`, and no change to `helm/settings.py`,
   `helm/urls.py`, `templates/base.html`, `static/css/helm.css`, or other apps'
   dirs.
   *Check:* `git diff --name-only` lists only paths under `projects/` and
   `docs/`.

10. **R10 — System check clean & loop services untouched.** `python manage.py
    check` exits 0; `git diff` shows **no** changes to `projects/services.py`,
    `orchestration/service.py`, `deploys/services.py`,
    `observability/services.py`, `agents/services.py` (loop intact).
    *Check:* check exits 0; diff of those files is empty.

### New multi-project UX (this sprint)

11. **R11 — Search is org-scoped.** `project_list` reads `?q=` and filters the
    **org-scoped** queryset by case-insensitive name OR repo_url/local_path
    substring. A user in org B searching a term that matches org A's project
    name returns **zero** results (never the other org's project).
    *Check:* test: org A has project "Zephyr"; user in org B GET
    `/projects/?q=Zephyr` → `len(response.context["projects"]) == 0`. And a
    positive test: user in B searching their own project's name returns it.

12. **R12 — Status filter is org-scoped & validated.** `?status=failed` (resp.
    `ready`, `importing`) returns only the org's projects with that status;
    an unknown/empty `status` returns all of the org's projects (no error).
    *Check:* test seeds org B with one `ready` and one `failed` project;
    `?status=failed` returns only the failed one; `?status=bogus` returns both.

13. **R13 — Portfolio summary strip present & org-scoped.** `project_list`'s
    context exposes summary counts (e.g. `summary` with `total`, `live`,
    `failed`, `incidents` — or equivalently named keys) computed from the
    org-scoped set, and `list.html` renders them in a `.stat`/`grid` strip. The
    counts reflect only `request.org` and are correct for a seeded fixture.
    *Check:* test asserts the context counts equal the expected values for a
    seeded org (e.g. total=3, failed=1) and that another org's projects don't
    affect them; grep shows `class="stat"` (or stat usage) in `list.html`.

14. **R14 — Health verdict helper exists & is correct.** A single reusable
    helper (model method/property `health_verdict`/`health` on `Project`, or a
    util in `projects/`) returns the correct verdict for: never-deployed →
    "never deployed"/neutral; at least one env live, none down → "live"; mixed
    live+down → "degraded"; has deployments but none live → "down". It does not
    raise for a project with `org=None` or zero environments.
    *Check:* unit test constructs each case and asserts the verdict string/enum;
    a no-env project returns the never-deployed verdict without error.

15. **R15 — Cards show health verdict + incident count.** `list.html` renders the
    verdict badge for each project (one of the four states) and, when a project
    has ≥1 unresolved incident, an open-incident count badge.
    *Check:* grep shows the verdict/health rendering in `list.html`; a test with
    a project that has an open incident asserts the rendered HTML contains the
    incident-count indicator (e.g. "1 open incident") for that org's user.

16. **R16 — Detail health rollup.** `detail.html` header renders a per-env health
    rollup (live/down per env) and the open-incident count, using the same
    verdict helper. `project_detail` context provides what the template needs.
    *Check:* grep shows the rollup markup in `detail.html`; the detail view for a
    project with a live env renders that env's "live" state in the header region
    (test asserts substring) — or, if sibling-app migration state blocks a full
    render in unit tests, the helper is asserted at the object level (mirroring
    the existing `test_detail_resolves_own_project_in_scope` pattern).

17. **R17 — Distinct empty states.** With a non-matching `?q=`, the list renders a
    "no projects match" state that includes a reset link back to `/projects/`;
    with zero projects in the org (and no query), it renders the original
    "import one" CTA. The two states are distinguishable in the HTML.
    *Check:* test: org with one project, GET `/projects/?q=zzzznomatch` →
    response contains the "no match"/"Clear" affordance and NOT the
    zero-projects import-CTA copy; org with zero projects, GET `/projects/` →
    contains the import-CTA copy.

18. **R18 — No N+1 regression / efficient list.** The list view prefetches
    environments (and their current deployments) and incidents used by the
    summary/verdict so rendering N projects does not issue O(N) extra queries for
    those relations.
    *Check:* grep shows `prefetch_related(` covering `environments` (and a
    deployment/incident prefetch or annotation) in `project_list`; (optional)
    `assertNumQueries` test stays constant as project count grows.

19. **R19 — UI contract honored.** `list.html` and `detail.html` still
    `{% extends "base.html" %}`, use only `helm.css` classes (no new CSS file, no
    JS framework), and the search/filter is a plain GET form or HTMX `hx-get`
    (no custom JS). `base.html` and `helm.css` are byte-for-byte unchanged.
    *Check:* grep `{% extends "base.html" %}` in both; `git diff` empty for
    base.html/helm.css; no `<script>` adding a framework and no new `.css` file
    under `static/`.

20. **R20 — Full projects test suite green.** `python manage.py test projects`
    passes (all tenancy + new UX tests), and `python manage.py check` exits 0.
    *Check:* both commands exit 0.

---

## 6. Definition of done

R1–R10 (tenancy regression invariants) still hold, and R11–R20 (multi-project
UX) are implemented and tested: org-scoped search + status filter, a portfolio
health strip, per-card and detail health verdicts, an open-incident indicator,
and distinct empty states — all org-scoped, loop-safe, dark-UI-consistent, with
`accounts/` and shared files untouched and the autonomous incident→fix loop
provably intact.
