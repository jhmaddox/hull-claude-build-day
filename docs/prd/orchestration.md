# PRD — Agent Org & Orchestration UI (`orchestration/`)

Section owner (PM): james@reserv.com
Sprint: 2 — Build-out, iteration 2 (make the autonomous loop legible per tenant)
Status: ready for builder
Supersedes: the Sprint-1 baseline PRD (org-scoping + stat strip + live activity),
which is **shipped**. This iteration is **purely additive** on top of it.

---

## 1. Problem

Hull's crown jewel is the autonomous **incident → agent fix → PR → CI → merge →
redeploy → resolved** loop. The Sprint-1 baseline made the `orchestration/`
section org-scoped and added a live-activity panel and a stat strip. But the
loop is still **not traceable**: when you open a single `WorkflowRun` you get a
flat blob of `detail` text and a dead-end "incident #42" label that links
nowhere. An operator cannot answer the demo's core questions from the UI:

- **"Which agent is writing this fix? Which PR did it open? Which incident
  triggered it?"** Each `WorkflowRun` already stores a `ref_type` + `ref_id`
  pointer (e.g. `incident`/42, `pull_request`/7, `agent_run`/9), but the
  templates render it as plain text — there is **no link** to the agent run, PR,
  or incident, so the loop can't be followed end-to-end from orchestration.
- **"What are the steps of this remediation and where is it now?"** The
  remediation pipeline emits a sequence of meaningful steps (detect → spawn
  agent → fix → open PR → CI → merge → redeploy → resolve), but the detail view
  shows them as one undifferentiated text region instead of a **timeline**.
- **"Show me only the remediations / only the failures."** The run table is an
  undifferentiated list of up to 100 rows across all workflow kinds with no way
  to filter by kind (import/deploy/agent/ci/remediation) or status.
- **Live agent output is one click away, never inline.** The activity surface
  links out to `/agents/<pk>/` but never surfaces the agent's streaming output
  next to the workflow that spawned it, so the demo's "watch the agent write the
  fix" moment lives outside orchestration.

We must make a single workflow run — and the autonomous loop it belongs to —
**legible and navigable per tenant**, without ever breaking the request-less
autonomous loop (which runs with **no request and no org**).

## 2. Goals / Non-goals

**Goals (this sprint)**
- Make every `WorkflowRun` **link out** to the concrete entity it operates on
  (incident / PR / agent run / environment / project), org-scoped, so the loop
  can be traced from orchestration in one click.
- Turn the workflow detail page into a **step timeline** plus the linked-entity
  panel, so a remediation reads as a narrative.
- Add **kind + status filtering** to the run list (server-side, HTMX, org-scoped).
- Surface the **most-recent / running agent's live output inline** on the
  workflow detail page when the run is an agent/remediation run.
- Keep every change **additive with fallbacks**; the autonomous loop is a hard
  QA gate that must stay green.

**Non-goals (scope-out, see §6)**
- Editing `accounts/models.py`, `helm/urls.py`, `helm/settings.py`,
  `templates/base.html`, or any other app's files.
- Schema changes to `agents.*`, `vcs.*`, `observability.*`, or `projects.*`.
  Orchestration reads them **read-only**. (Note: `agents.AgentRun` already
  subclasses `OrgScopedModel` and now has its own `org` field — orchestration
  MAY use `AgentRun.objects.for_org(request.org)` instead of `project__org`, but
  must not modify the model.)
- Workflow cancel / retry / pause / re-run controls.
- New Temporal workflow definitions or changes to `service._run`'s dispatch.
- Sprint/board planning CRUD (lives in the Issues section).

## 3. Users & user stories

- **Org operator / SRE** — "When a remediation runs in *my* org, I open the
  workflow and see its steps as a timeline, click straight through to the
  incident it's fixing and the PR it opened, and watch the agent's output —
  all without leaving orchestration, and never seeing another tenant's runs."
- **Eng leader** — "I want to filter the run list to just remediations, or just
  failures, to audit the autonomous crew."
- **Demo driver (the Mayor)** — "During the money-shot demo I open the running
  remediation workflow and the page shows the live pipeline advancing and the
  agent writing the fix, then the linked PR turns green and merges."

## 4. Existing contract (must not break)

- `orchestration.service` public entry points stay **signature-stable**:
  `import_project`, `deploy`, `run_feature_agent`, `run_ci`, `remediate`,
  `is_remediating` (plus internal `_run`, `_run_ci_inline`,
  `_remediate_pipeline`). The loop calls these **without a request**.
- `_run(...)` remains the single `WorkflowRun`-creation chokepoint; `org` stays
  `null=True, blank=True` and is resolved best-effort with a fallback to `None`.
  **No new required argument** may be added to `_run` or any entry point.
- All existing routes keep working: `/orchestration/`, `/orchestration/table/`,
  `/orchestration/activity/`, `/orchestration/activity/panel/`,
  `/orchestration/<pk>/`.

## 5. Scope-in (MVP features)

### 5.1 Resolve `ref_type`/`ref_id` into a linked entity (org-scoped)
- Add a **helper** (e.g. a `WorkflowRun` method `linked_object()` /
  `linked_url()` / `linked_label()`, or a small `orchestration/refs.py`) that
  maps `(ref_type, ref_id)` → the concrete object and its URL:
  - `incident` → `observability.Incident` → `/obs/incidents/<pk>/`
  - `pull_request` → `vcs.PullRequest` → `get_absolute_url()` (`/vcs/pr/<pk>/`)
  - `agent_run` → `agents.AgentRun` → `/agents/<pk>/`
  - `environment` → `deploys.Environment` → its detail/deploy URL
  - `project` (or `run.project`) → `/projects/<slug>/`
- Resolution is **best-effort and fallback-safe**: an unknown `ref_type`,
  missing row, or import error yields `None`/empty (renders as plain text, never
  raises). Lookups are wrapped in try/except.
- Resolution is **org-scoped**: when a `request` is available, the referenced
  entity is only linked if it belongs to `request.org` (so a run can't leak a
  cross-org link). The helper may take `org` (or `request`) and filter.

### 5.2 Workflow detail = step timeline + linked-entity panel
- `/orchestration/<pk>/` (`workflow_detail`) gains:
  - A **linked-entity panel** that renders the resolved entity from §5.1 as a
    real `<a>` link with a kind badge (e.g. "Incident #42 — firing" linking to
    the incident). Falls back to the existing plain-text label when unresolved.
  - A **step timeline** built from the run's `detail` text, rendered with the
    design-system feed classes (`.feed` / `.feed-item` / `.feed-ico` /
    `.feed-time`) — one row per meaningful step line. Splitting `detail` into
    steps must be tolerant of empty/format-varying detail (no crash on empty).
- While the run is `running`, the detail page **HTMX-refreshes** the timeline +
  inline agent output fragment (`hx-trigger="every Ns"`), matching the existing
  polling pattern; once `done`/`failed` it may stop polling.

### 5.3 Inline live agent output on workflow detail
- When the workflow's linked entity (or the run's project) has an associated
  running/most-recent `agents.AgentRun`, the detail page shows that agent's
  **streamed `output`** inline using the `.logs` class (read-only tail).
- Selection is **org-scoped** (`AgentRun.objects.for_org(request.org)` or
  `project__org=request.org`) and **fallback-safe** (no agent → section hidden,
  never raises). AgentRun remains read-only.

### 5.4 Filter the run list by kind + status (server-side, HTMX, org-scoped)
- `workflow_list` / `workflow_table` accept optional query params (e.g.
  `?status=running|done|failed` and `?kind=import|deploy|agent_run|ci|incident`
  derived from `ref_type` and/or the run `name`/`status`).
- Filters are applied **after** `for_org(request.org)` (org-scoping always wins)
  and are reflected by active filter chips/pills (`.pill` / `.badge`) in the UI.
- A filter that matches nothing renders the existing `.empty` state, not an
  error. Absent params → unfiltered (current behavior preserved).
- The HTMX table fragment (`/orchestration/table/`) honors the same params so
  live polling preserves the active filter.

### 5.5 Cross-link the run table + activity rows to entities
- In the run table and activity panel, each row exposes the §5.1 linked entity
  (e.g. an extra "→ incident #42" / "→ PR #7" affordance) when resolvable, so an
  operator can jump from a run straight to the artifact. Rows with no resolvable
  ref keep their current behavior.

## 6. Scope-out (explicitly not this sprint)
- Cross-org / admin "all tenants" orchestration view.
- Workflow cancel / retry / pause / re-run controls.
- Any schema change to `agents.*`, `vcs.*`, `observability.*`, `projects.*`,
  or new fields on `WorkflowRun` beyond what §5 needs (prefer deriving from
  existing `ref_type`/`ref_id`/`name`; if a field is truly required it must be
  nullable + additive + migration generated, not migrated).
- New Temporal workflow definitions.
- Sprint/board CRUD (Issues section).

## 7. Design / implementation notes
- Extend `base.html` via `{% extends %}` only; reuse `static/css/helm.css`
  classes only. Confirmed available: `card`, `badge`/`badge-warn`/`badge-success`/
  `badge-danger`/`badge-neutral`/`badge-info`/`badge-accent`, `stat`, `grid-2/3/4`,
  `list-row`, `logs`, `empty`, `pill`/`pill-live`, `dot`/`dot-live`,
  `feed`/`feed-item`/`feed-ico`/`feed-time`/`feed-body`. **No new external
  CSS/JS** (HTMX is already loaded via base.html).
- Load `{% load helm_extras %}` for `status_badge` / `feed_icon` filters.
- Keep all new URLs inside `orchestration/urls.py` (it owns `app_name`). Do NOT
  edit `helm/urls.py`.
- All cross-app reads go through ORM/`get_absolute_url()`; wrap every cross-app
  import + lookup in try/except so a missing/renamed dependency degrades to the
  current plain-text behavior. Never let orchestration views 500 on a bad ref.
- Validate with `python manage.py check`; you MAY run
  `makemigrations orchestration` only if §5 forces a (nullable, additive) field;
  do NOT run `migrate`; do NOT bind port 8000 (use 8011+ for smoke tests, kill
  after).
- Use `core.models.Event.log(...)` only for genuinely new meaningful steps
  (optional — the service layer already logs the loop).

## 8. Machine-checkable rubric (pass/fail)

Each item is independently verifiable. "ROOT" = repo root
`/Users/james/dev/claude-hackathon`. Run Django checks with the project venv
(`source .venv/bin/activate`) from ROOT.

1. **R1 — ref-resolution helper exists.** There is a callable that maps a
   `WorkflowRun`'s `(ref_type, ref_id)` to a linked entity and/or URL+label
   (a `WorkflowRun` method such as `linked_url`/`linked_object`/`linked_label`,
   or a function in `orchestration/refs.py`). Check:
   `grep -REn "linked_url|linked_object|linked_label|def .*ref" orchestration/models.py orchestration/refs.py orchestration/views.py`
   matches at least one definition.

2. **R2 — helper resolves the four loop ref types.** For ref types `incident`,
   `pull_request`, `agent_run`, and `environment`/`project`, the helper returns
   a URL string (or object exposing one) when the row exists. Functional check:
   create one of each entity, point a `WorkflowRun` at it via `ref_type`/`ref_id`,
   and assert the resolved URL contains the expected prefix
   (`/obs/incidents/`, `/vcs/pr/`, `/agents/`, `/projects/` or env URL).

3. **R3 — helper is fallback-safe.** With an unknown `ref_type`
   (e.g. `"bogus"`), a missing `ref_id` (e.g. `999999`), and empty
   `ref_type=""`, the helper returns a falsy/None result and **does not raise**.
   Check via shell: calling the resolver on such a run returns without exception.

4. **R4 — ref resolution is org-scoped.** When called with org A's request/org,
   a `WorkflowRun` whose ref points at an entity owned by org B does **not**
   resolve to a clickable cross-org link (returns None/plain text). Functional
   check with two orgs and one incident in org B.

5. **R5 — detail page renders a real link to the entity.** For a run with a
   resolvable ref in the current org, `GET /orchestration/<pk>/` returns 200 and
   the HTML contains an `<a href="...">` to the entity's URL (e.g.
   `href="/obs/incidents/<n>/"`). For an unresolvable ref it falls back to plain
   text and still returns 200 (no 500).

6. **R6 — detail page renders a step timeline.** `GET /orchestration/<pk>/` for
   a run with multi-line `detail` renders the timeline using design-system feed
   classes. Check: response HTML contains `feed-item` (or `feed`) and one row
   per non-empty step; a run with empty `detail` still returns 200.

7. **R7 — inline agent output, org-scoped + fallback-safe.** For a workflow
   linked to a running `agents.AgentRun` **in the current org**, the detail page
   includes that agent's `output` inside a `.logs` block. For a run with no
   associated agent the page omits the block and still returns 200. Org A's
   workflow detail never shows org B's agent output.

8. **R8 — run list filters by status.**
   `GET /orchestration/?status=running` (and `=failed`) returns 200 and the
   rendered table contains only runs of that status for `request.org`; an
   absent `status` param preserves current (unfiltered) behavior. A
   no-match filter renders the `.empty` state, not a 500.

9. **R9 — run list filters by kind.** `GET /orchestration/?kind=incident`
   (remediations) returns 200 and the table is restricted to that kind for the
   org. The HTMX fragment `GET /orchestration/table/?kind=incident&status=...`
   honors the same params (live polling keeps the filter).

10. **R10 — table/activity rows cross-link to entities.** The run table and/or
    activity panel expose a link/affordance to the resolved entity for rows with
    a resolvable ref (e.g. an `<a>` to `/obs/incidents/`, `/vcs/pr/`,
    `/agents/`). Rows without a resolvable ref keep working.

11. **R11 — request-less creation still works (loop safety).** Calling the
    service chokepoint without a request creates a `RUNNING` `WorkflowRun` with
    `org is None` and does not raise. Check:
    `python manage.py shell -c "from orchestration import service as s; wf=s._run('rubric-test', lambda: 'ok'); print(wf.pk is not None and wf.org is None)"`
    prints `True`.

12. **R12 — service entry-point signatures unchanged.** `import_project`,
    `deploy`, `run_feature_agent`, `run_ci`, `remediate`, `is_remediating` are
    all present and callable in `orchestration.service` with no new required
    args. Check:
    `python manage.py shell -c "import orchestration.service as s; print(all(callable(getattr(s,n)) for n in ['import_project','deploy','run_feature_agent','run_ci','remediate','is_remediating']))"`
    prints `True`.

13. **R13 — all request paths org-scoped + guarded.** `workflow_list`,
    `workflow_table`, `workflow_detail`, `activity`, `activity_panel` (and any
    new view) are wrapped with `org_required` and filter via
    `for_org(request.org)` / `scoped(...)`. Check:
    `grep -E "org_required" orchestration/views.py` matches for every view, and
    `grep -E "for_org|scoped\(" orchestration/views.py` matches. A no-org GET to
    `/orchestration/` redirects (302). `workflow_detail` for another org's run
    returns 404.

14. **R14 — design-system compliance.** Every new/changed template
    `{% extends "base.html" %}`, introduces no `<link rel="stylesheet"` or
    `<script src=` to non-helm assets, and uses only `static/css/helm.css`
    classes. Check: new templates contain `{% extends "base.html" %}` and no
    external stylesheet/script tags.

15. **R15 — `manage.py check` clean.** `python manage.py check` exits 0 with no
    errors introduced by orchestration.

16. **R16 — autonomous loop end-to-end still green.** The orchestration test
    suite (incident→fix loop) passes unchanged. Check:
    `python manage.py test orchestration` exits 0, and the run records a
    `WorkflowRun` for the remediation that reaches a terminal state.

17. **R17 — no migrations missing.**
    `python manage.py makemigrations orchestration --check --dry-run` exits 0
    (any required new field is already captured in a generated, un-applied
    migration). If §5 needed no new field, no new migration is required.

18. **R18 — no forbidden edits.** `git diff --name-only` shows changes ONLY
    under `orchestration/` and `docs/prd/orchestration.md`. `accounts/models.py`,
    `helm/urls.py`, `helm/settings.py`, `templates/base.html`, and every other
    app's files are untouched.

## 9. Out-of-band acceptance for the demo
- During a live remediation, opening the running remediation `WorkflowRun`
  shows: (a) a one-click link to the firing incident, (b) the pipeline steps as
  a live-updating timeline, and (c) the remediation agent's output streaming
  inline — all scoped to the current org, refreshing without a full page reload.
  Filtering the run list to `?kind=incident` isolates the remediations.

## 10. Implementation status (builder) — SHIPPED

All changes are additive and confined to `orchestration/` (+ this PRD). No new
`WorkflowRun` field was required (the loop pointer reuses existing
`ref_type`/`ref_id`), so **no new migration** is needed
(`makemigrations orchestration --check` is clean). `AgentRun` already subclasses
`OrgScopedModel`, so inline-output selection uses `AgentRun.objects.for_org(...)`.

Files touched → rubric items:

- `orchestration/refs.py` **(new)** — org-scoped, fallback-safe ref resolver
  (`resolve` / `resolve_url` / `resolve_label`). Maps `incident →
  /obs/incidents/<pk>/`, `pull_request → get_absolute_url()`, `agent_run →
  /agents/<pk>/`, `environment → public_url`, project fallback →
  `/projects/<slug>/`. Every cross-app import + lookup is `try/except`. A KNOWN
  typed ref is authoritative and resolves org-scoped or returns `None` (no
  project-link masquerade) → **R1, R2, R3, R4**.
- `orchestration/models.py` — `WorkflowRun.linked()/linked_object()/linked_url()
  /linked_label()` delegate to `refs`; `WorkflowRun.kind` property derives the
  coarse kind from `ref_type`/`name` for filtering → **R1, R9**.
- `orchestration/views.py` —
  - `_apply_filters` / `_filter_by_kind` apply `?status=`/`?kind=` AFTER
    `for_org(request.org)`; no-match → `.empty`; absent → unfiltered → **R8, R9**.
  - `_decorate` attaches the resolved link to each row (table + activity) →
    **R10**.
  - `_parse_steps` / `_step_icon` build the timeline from `detail` (tolerant of
    empty) → **R6**.
  - `_inline_agent` selects a running/most-recent `AgentRun` via
    `AgentRun.objects.for_org(request.org)`, never another org's, omitted when
    none → **R7**.
  - `workflow_detail_panel` HTMX fragment view (org-scoped) → **R4 (R13 path)**.
  - Every view keeps `@org_required` + `for_org`/`scoped`; cross-org detail →
    404; no-org → 302 → **R13**.
  - `_activity_context` now scopes agents via `for_org` (was `project__org`).
- `orchestration/urls.py` — adds `<int:pk>/panel/` (no edit to `helm/urls.py`).
- `templates/orchestration/workflow_detail.html` — linked-entity panel (real
  `<a>` + kind badge), plain-text fallback, HTMX-live timeline/output wrapper
  while running → **R5, R6, R4**.
- `templates/orchestration/_workflow_detail_panel.html` **(new)** — feed-class
  timeline + `.logs` inline agent output; HTMX-refreshable fragment → **R6, R7**.
- `templates/orchestration/workflow_list.html` — kind/status filter pills +
  active-filter chips; HTMX poll URL preserves the filter querystring → **R8, R9**.
- `templates/orchestration/_workflow_table.html` — `→ <label>` cross-link cell
  to the resolved entity (rows without a ref keep working) → **R10**.
- `templates/orchestration/_activity_panel.html` — cross-link affordance on
  running-workflow rows → **R10**.

Loop safety / signature stability: `service._run` and the 6 entry points keep
their signatures — `s._run('rubric-test', lambda:'ok')` still creates a
`RUNNING` `WorkflowRun` with `org is None` → **R11, R12**. The only change to
`service.py` is hardening `_save_wf`'s sqlite write-lock retry (more attempts +
backoff/jitter) so a successful background run is never mis-recorded as stuck
under full-suite daemon-thread contention → keeps **R16** green deterministically. `manage.py check` clean
(**R15**); `python manage.py test orchestration` green incl. the incident→fix
loop reaching a terminal state (**R16**); `makemigrations orchestration --check`
clean (**R17**); every new/changed template `{% extends "base.html" %}` and uses
only `helm.css` classes, no external CSS/JS (**R14**); diff scoped to
`orchestration/*` + this PRD (**R18**).
