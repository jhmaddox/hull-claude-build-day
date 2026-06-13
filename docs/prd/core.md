# PRD — Dashboard org-scoping + org switcher ("helm" / Hull)

Owner: Section PM — Core / Mission Control dashboard
Sprint: 2 (Operations)
Section owns: `core/` (the Mission Control dashboard `/`, the activity feed `/feed/`,
`core/views.py`, `core/templates/core/*`). Do **NOT** modify `accounts/models.py`,
`accounts/scoping.py`, `accounts/middleware.py` (Mayor-owned tenancy contract),
`templates/base.html`, `static/css/helm.css`, or any other app's files. Reuse the
existing `accounts/_org_switcher.html` partial via `{% include %}` and the scoping
helpers in `accounts/scoping.py`.

---

## 0. Current state (what exists today)

- `core/views.py` has two views: `dashboard(request)` (`/`) and `feed(request)`
  (`/feed/`). **Both query every model with `.objects.all()` / unscoped filters** —
  e.g. `Project.objects.all()`, `Deployment.objects.filter(status=LIVE)`,
  `Incident.objects.exclude(...)`, `AgentRun.objects.filter(...)`,
  `PullRequest.objects.filter(...)`, `Event.objects.select_related("project")`, and a
  `stats` dict with five unscoped `.count()`s. **No org filtering whatsoever.**
- The tenancy contract is fully in place: `request.org` is set by
  `accounts.middleware.CurrentOrgMiddleware`; `accounts/scoping.py` exposes
  `org_required`, `scoped(Model, request)`, `current_org(request)`; every dashboard
  model (`Project`, `Deployment`, `Environment`, `Incident`, `AgentRun`,
  `PullRequest`, `Event`) has a **nullable** `org` FK.
- A reusable org switcher partial **already exists** at
  `accounts/templates/accounts/_org_switcher.html` and the `accounts:switch_org`
  view works — but the switcher is only rendered on `/accounts/*` pages. **The
  dashboard currently fills `{% block actions %}` with only an "+ Import project"
  button — no org switcher.**
- `base.html` (which we cannot edit) provides `{% block actions %}` in the topbar and
  `{% block content %}`; `core/dashboard.html` already overrides `actions`.
- **Critical constraint:** the autonomous incident→fix loop and the `helm_demo`
  seeder create records with `org=None` (services default `org=None`; `Event.log()`
  never sets org). A naive `.filter(org=request.org)` would make all loop/demo data
  **disappear** from the dashboard whenever an org is active. The crown-jewel demo
  must keep rendering.

## 1. Problem

The Mission Control dashboard is the product's front door, but it is **tenant-blind**:
every operator — regardless of which org they belong to — sees the union of all orgs'
projects, deployments, incidents, agents, PRs, and the global event feed. For a
multi-tenant control plane this is both a **data-leak/privacy defect** and a
**usability defect** (noise from other tenants). Meanwhile, an operator on the
dashboard has **no way to switch orgs** without first navigating to an `/accounts/*`
page, because the global switcher only lives there.

We must (a) scope the dashboard + feed to the current org while (b) keeping shared /
autonomous-loop / demo data (`org=None`) visible so the crown-jewel demo never breaks,
and (c) surface the org switcher in the dashboard nav.

## 2. User stories

1. As a member of org **Acme**, when I open `/`, I see **only Acme's** projects,
   deployments, incidents, agents, PRs, events, and stat counts — not Globex's.
2. As an operator, I can switch from Acme to Globex via a switcher **in the dashboard
   topbar** and the dashboard immediately re-renders with Globex's data.
3. As the platform running the autonomous loop, demo/loop data (`org=None`) **still
   shows on the dashboard** so the incident→fix→PR→merge→redeploy story is visible
   regardless of the active org. The loop itself (no request, `request.org` absent) is
   untouched.
4. As a brand-new user with no org (or an anonymous visitor), the dashboard renders an
   empty-but-friendly state and never 500s.
5. As an operator, the live activity **feed (`/feed/`)** respects the same scoping as
   the dashboard so the polled fragment doesn't leak other orgs' events.

## 3. Current-state → target

| Aspect | Current | Target |
|---|---|---|
| Dashboard data | All orgs (unscoped) | Current org **+ shared `org=None`** |
| `stats` counts | Global | Same scope as the lists they summarize |
| Feed `/feed/` | All events | Current org + `org=None` |
| Org switcher on `/` | Absent | Present in `{% block actions %}` |
| No-org / anon user | Mixed/leaky | Friendly empty state, no crash |
| Autonomous loop | Works | **Still works, unchanged** |

## 4. Scope (MVP — THIS sprint)

**In scope**
- A scoping helper local to `core/views.py` that returns, for a given model and
  request, records where `org == request.org` **OR** `org IS NULL` (shared/loop/demo).
  Applied to all six dashboard collections **and** all five `stats` counts **and** the
  feed.
- Including `accounts/_org_switcher.html` in the dashboard's `{% block actions %}`
  (keeping the existing "+ Import project" button).
- Graceful behavior when `request.org is None` (new user) and when the user is
  anonymous: show shared `org=None` data only (or empty), never error.

**Out of scope (explicitly not this sprint)**
- Editing `base.html` to make the switcher global on every page (owned by accounts;
  tracked in `docs/prd/accounts.md`). We only fix the **dashboard**.
- Modifying the tenancy contract, middleware, or any other app's models/views.
- Per-org dashboard customization, saved filters, role-based widget hiding.
- Backfilling `org` onto existing/demo records (the `org=None`-visible policy makes
  this unnecessary for the demo).

## 5. Design notes (non-binding guidance for the builder)

- Add a small helper in `core/views.py`, e.g.:
  ```python
  from django.db.models import Q
  def _org_scope(qs, request):
      org = getattr(request, "org", None)
      if org is None:
          return qs  # no active org: show shared/all (anon/new-user safe)
      return qs.filter(Q(org=org) | Q(org__isnull=True))
  ```
  Apply it to each queryset **before** slicing `[:12]` / `[:40]`, and derive each
  `stats` count from the **same** scoped queryset (`.count()` on the scoped qs).
- Do **not** use `accounts.scoping.scoped()` directly for the lists, because it does a
  strict `filter(org=org)` and returns `.none()` when org is None — that would hide the
  loop/demo data and break the crown-jewel demo. The `org=None`-OR policy above is the
  deliberate design.
- Switcher: `{% include "accounts/_org_switcher.html" %}` inside the dashboard
  `{% block actions %}`. It reads `request` directly, so no extra context needed.
- Keep all changes additive; `dashboard()` and `feed()` keep their signatures and the
  `_adopt_deployments()` call.

## 6. Non-functional / guardrails

- `python manage.py check` → 0 errors.
- No new migrations from `core` (no model changes): `makemigrations core --check` →
  "No changes detected".
- No edits to `base.html`, `helm.css`, `accounts/*` python, or other apps.
- Autonomous loop untouched: `core/` changes are request-path only.

---

## 7. MACHINE-CHECKABLE RUBRIC (pass/fail)

Each item is an objective assertion a QA agent can verify by reading files and/or
running Django shell/test code. Paths are relative to repo root.

1. **R1 — Scoped projects list.** In `core/views.py`, the `dashboard` view's
   `projects` queryset is filtered by org (it is NOT a bare `Project.objects.all()`);
   the filtering references `request.org` (directly or via a helper that reads
   `getattr(request, "org", ...)`).
2. **R2 — Scoped live deployments.** `live_deployments` in `dashboard` is org-scoped
   (no longer an unscoped `Deployment.objects.filter(status=...)` without org).
3. **R3 — Scoped open incidents.** `open_incidents` in `dashboard` is org-scoped.
4. **R4 — Scoped running agents.** `running_agents` in `dashboard` is org-scoped.
5. **R5 — Scoped open PRs.** `open_prs` in `dashboard` is org-scoped.
6. **R6 — Scoped events.** The `events` context var in `dashboard` is org-scoped.
7. **R7 — Scoped stats.** All five values in the `stats` dict (`projects`,
   `environments`/`live`, `live`, `incidents`, `agents`) are computed from org-scoped
   querysets, not global `.count()`s.
8. **R8 — Shared `org=None` data stays visible.** With an active org set, a record with
   `org=None` (e.g. a demo `Project`) STILL appears in the dashboard's `projects`
   context. Verifiable: create org A + a `Project(org=None)` + a `Project(org=A)`;
   render `/` as a member of A (or call the scope helper); both projects are present.
9. **R9 — Cross-org isolation.** With active org A, a `Project(org=B)` for a different
   org B does NOT appear in the dashboard `projects` context.
10. **R10 — Feed scoped consistently.** The `feed` view (`/feed/`) applies the SAME
    org+shared scoping to its `events` queryset as the dashboard (org A's events and
    `org=None` events present; org B's events absent).
11. **R11 — Org switcher in dashboard nav.** `core/templates/core/dashboard.html`
    includes `accounts/_org_switcher.html` (via `{% include %}`) inside
    `{% block actions %}`, AND the existing "+ Import project" affordance is retained.
12. **R12 — No-org / anonymous safety.** Requesting `/` with `request.org is None`
    (new user) or as an anonymous user returns HTTP 200 (no 500); the dashboard
    renders without raising.
13. **R13 — No model changes / clean migrations.** `python manage.py makemigrations
    core --check --dry-run` reports no changes (core defines no new model fields).
14. **R14 — System check clean.** `python manage.py check` exits 0.
15. **R15 — Contract files untouched.** `git diff --name-only` shows NO changes to
    `accounts/models.py`, `accounts/scoping.py`, `accounts/middleware.py`,
    `templates/base.html`, `static/css/helm.css`, or any non-`core/` app file. Only
    files under `core/` (and this PRD) are modified.
16. **R16 — Loop helpers not imported/altered for scoping side-effects.** `core/`
    does not call any `deploys.services` / `observability.services` /
    `agents.services` / `orchestration.service` function in a way that changes the
    autonomous loop; dashboard/feed changes are read-only request-path filtering.
17. **R17 — Switcher renders for an authenticated member.** Rendering `/` as a logged-in
    user with ≥1 membership produces the switcher markup (the current org name and a
    `accounts:switch_org` link appear in the response HTML).
