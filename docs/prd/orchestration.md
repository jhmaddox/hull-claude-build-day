# PRD — Agent Org & Orchestration UI (`orchestration/`)

Section owner (PM): james@reserv.com
Sprint: 1 — Build-out (make every section org-scoped + ship features in parallel)
Status: ready for builder

---

## 1. Problem

Hull's crown jewel is the autonomous **incident → agent fix → PR → CI → merge →
redeploy → resolved** loop. Today that work happens, but it is barely *visible*:
the `orchestration/` section renders a single flat, **org-blind** table of
`WorkflowRun` rows shared across all tenants. There is:

- **No multitenancy.** `WorkflowRun` has no `org` field and the views do no
  scoping, so every org sees every other org's workflows. This violates the
  Sprint-1 multitenancy contract and is an enterprise data-isolation bug.
- **No agent-org story.** The roadmap promises "the agent org surfaced
  in-product: PM/builder/QA agents, sprint/workflow runs, **live agent
  output**." Right now there is no live agent-activity view, no roll-up of what
  the autonomous crew is doing, and no narrative of the autonomous-build loop.
- **Weak observability of the loop itself.** When a remediation is in flight,
  an operator cannot glance at one page and see "N workflows running, the
  remediation pipeline is on step X, agent #Y is writing the fix."

We must make the agent org legible **per tenant** without ever breaking the
autonomous loop (which runs with **no request and no org**).

## 2. Goals / Non-goals

**Goals (this sprint)**
- Org-scope `WorkflowRun` per the accounts tenancy contract, keeping `org`
  nullable so the request-less autonomous loop keeps writing rows.
- Scope all orchestration request paths to `request.org`.
- Ship a live **Agent Activity** surface (the agent org: running workflows +
  running agent runs) and an **autonomous-build overview** (stat roll-up that
  tells the loop's story), org-scoped and HTMX-live.
- Keep every change **additive with fallbacks**; the loop is a hard QA gate.

**Non-goals (scope-out, see §6)**
- Editing `accounts/models.py`, `helm/urls.py`, `helm/settings.py`,
  `templates/base.html`, or other apps' files.
- Adding `org` to `agents.AgentRun` / `agents.Worktree` (owned by the agents
  slice). Orchestration reads them read-only and derives org via `project`.
- New Temporal workflow types, cancellation/retry controls, or sprint-planning
  CRUD. Surfacing only.

## 3. Users & user stories

- **Org operator / SRE** — "When an incident fires in *my* org, I open
  Orchestration and watch the remediation pipeline run live, and I never see
  another tenant's runs."
- **Eng leader** — "I want a one-glance overview of the autonomous crew: how
  many workflows ran, how many succeeded, how many incidents were auto-resolved."
- **Demo driver (the Mayor)** — "During the money-shot demo, the Agent Activity
  page should visibly light up as the agent writes the fix, CI runs, and the PR
  merges."

## 4. Existing contract (must not break)

- `orchestration.service` public entry points stay signature-stable:
  `import_project`, `deploy`, `run_feature_agent`, `run_ci`, `remediate`,
  `is_remediating`, plus internal `_run`, `_run_ci_inline`,
  `_remediate_pipeline`. The loop calls these **without a request**.
- `_run(...)` creates the `WorkflowRun`. This is the single chokepoint where
  `org` must be assigned — additively, defaulting to `None`.

## 5. Scope-in (MVP features)

### 5.1 Org-scope the `WorkflowRun` model
- `WorkflowRun` subclasses `accounts.models.OrgScopedModel` (gives `org` FK +
  `OrgManager`) **or** adds the contract-standard nullable `org` FK. `org` MUST
  be `null=True, blank=True` so request-less creation works.
- A new migration `orchestration/0002_*.py` is generated with
  `makemigrations orchestration` (NOT migrated by the builder).

### 5.2 Stamp `org` on every `WorkflowRun` (additive, fallback-safe)
- In `service._run`, set `org` best-effort: prefer `project.org` when the
  project carries one; else `accounts.models.get_current_org()`; else `None`.
- All resolution is wrapped so any failure (missing attr, import error)
  degrades to `org=None` and the workflow still runs. The autonomous loop path
  must continue to create runs and complete.

### 5.3 Scope orchestration views to the current org
- `workflow_list`, `workflow_table`, `workflow_detail` filter to `request.org`
  via `accounts.scoping` (`scoped(...)` / `WorkflowRun.objects.for_org(request.org)`).
- Views are guarded with `@org_required` (redirects to onboarding when no org).
- A user in org A gets **404** for org B's `workflow_detail`.

### 5.4 Agent Activity surface (the agent org, live)
- New view + template at `/orchestration/activity/` showing, **scoped to
  request.org**: currently-running `WorkflowRun`s and currently-running
  `agents.AgentRun`s (joined to org via `project__org` / project ownership),
  using the existing dark design-system classes.
- HTMX live-refreshing fragment (`hx-trigger="every Ns"`), matching the
  existing `/orchestration/table/` polling pattern.
- Empty state uses the `.empty` class when the org has no live activity.

### 5.5 Autonomous-build overview (stat roll-up)
- The orchestration index (`/orchestration/`) gains an org-scoped stat strip
  (`.stat` / `.grid-*`): total runs, running, succeeded, failed, and
  auto-resolved incidents — all filtered to `request.org`.
- Tells the autonomous-build story at a glance; numbers reflect only the
  current org.

## 6. Scope-out (explicitly not this sprint)
- Cross-org/admin "all tenants" view.
- Workflow cancel/retry/pause controls.
- Adding org to agents models or any cross-app schema change.
- Sprint/board CRUD (lives in Issues section).
- New Temporal workflow definitions.

## 7. Design / implementation notes
- Extend `base.html` via `{% extends %}` only; reuse `static/css/helm.css`
  classes (`card`, `badge`, `stat`, `grid-*`, `empty`, `pill`, `logs`); load
  `{% load helm_extras %}` for `status_badge` etc.
- Keep new URLs inside `orchestration/urls.py` (it owns `app_name`). Do not edit
  `helm/urls.py`.
- Use `core.models.Event.log(...)` for any new meaningful step (optional here;
  the service layer already logs).
- All AgentRun access is read-only; derive org through `project` (do not assume
  AgentRun has an `org` column).
- Validate with `python manage.py check`; you MAY run
  `makemigrations orchestration`; do NOT run `migrate`; do NOT bind port 8000
  (use 8011+ for smoke tests and kill after).

## 8. Machine-checkable rubric (pass/fail)

Each item is independently verifiable. "ROOT" = repo root
`/Users/james/dev/claude-hackathon`.

1. **R1 — org field exists.** `WorkflowRun` has an `org` ForeignKey to
   `accounts.Org`. Check:
   `python manage.py shell -c "from orchestration.models import WorkflowRun; f=WorkflowRun._meta.get_field('org'); print(f.is_relation and f.related_model._meta.label=='accounts.Org')"`
   prints `True`.

2. **R2 — org is nullable.** The `org` field has `null=True` and `blank=True`.
   Check:
   `python manage.py shell -c "from orchestration.models import WorkflowRun; f=WorkflowRun._meta.get_field('org'); print(f.null and f.blank)"`
   prints `True`.

3. **R3 — migration present, none missing.**
   `python manage.py makemigrations orchestration --check --dry-run` exits 0
   (no un-generated changes), and a migration file other than `0001_initial.py`
   exists under `orchestration/migrations/`.

4. **R4 — request-less creation still works (loop safety).** Calling the
   service chokepoint without a request creates a `RUNNING` `WorkflowRun` with
   `org is None` and does not raise. Check (after migrate by integrator):
   `python manage.py shell -c "from orchestration import service as s; wf=s._run('rubric-test', lambda: 'ok'); print(wf.pk is not None and wf.org is None)"`
   prints `True`.

5. **R5 — service entry-point signatures unchanged.** `import_project`,
   `deploy`, `run_feature_agent`, `run_ci`, `remediate`, `is_remediating`
   are all present and callable in `orchestration.service` with their original
   parameters (no required new args). Check:
   `python manage.py shell -c "import inspect,orchestration.service as s; print(all(callable(getattr(s,n)) for n in ['import_project','deploy','run_feature_agent','run_ci','remediate','is_remediating']))"`
   prints `True`.

6. **R6 — list view is org-scoped.** `workflow_list`/`workflow_table` querysets
   filter by `request.org`. Static check:
   `grep -E "for_org|scoped\(" orchestration/views.py` matches, AND a request
   from org A does not include a `WorkflowRun` belonging to org B in the
   rendered list (functional check via two orgs).

7. **R7 — views require an org.** `workflow_list`, `workflow_table`,
   `workflow_detail`, and the new activity view are wrapped with `org_required`
   (or equivalent redirect-to-onboarding when `request.org is None`). Check:
   `grep -E "org_required" orchestration/views.py` matches and an
   unauthenticated/no-org GET to `/orchestration/` redirects (302) to
   onboarding/login.

8. **R8 — detail is cross-org safe.** `workflow_detail` for a run belonging to
   another org returns HTTP 404 (not 200) for a user whose `request.org` differs.

9. **R9 — Agent Activity route exists.** A URL named within
   `orchestration/urls.py` serves the live agent-activity surface; e.g.
   `GET /orchestration/activity/` returns 200 for an authenticated user with an
   org and the template `{% extends "base.html" %}`.

10. **R10 — Agent Activity is live + org-scoped.** The activity template
    contains an HTMX live-refresh trigger (`hx-trigger="every`) and its context
    querysets are scoped to `request.org` (running WorkflowRuns and running
    AgentRuns via `project` org). Org A's activity page never shows org B's
    running agent runs.

11. **R11 — Autonomous-build overview present + scoped.** `/orchestration/`
    renders org-scoped stats (at minimum: total, running, succeeded/failed
    counts) using `.stat`/`.grid-*` classes; counts are computed from
    `request.org`-filtered querysets (changing org changes the numbers).

12. **R12 — design-system compliance.** All new/changed templates
    `{% extends "base.html" %}`, introduce no external CSS/JS frameworks, and
    use only `static/css/helm.css` classes. Check: new templates contain
    `{% extends "base.html" %}` and no `<link rel="stylesheet"` / `<script src=`
    to non-helm assets.

13. **R13 — `manage.py check` clean.** `python manage.py check` exits 0 with no
    errors introduced by orchestration.

14. **R14 — autonomous loop end-to-end still green.** The integrator's
    incident→fix smoke (`orchestration/tests_smoke.py` and/or the project's
    end-to-end loop test) passes unchanged: an incident drives
    `remediate(...)` to a resolved state and a `WorkflowRun` is recorded.
    Check: `python manage.py test orchestration` exits 0.

15. **R15 — no forbidden edits.** `git diff --name-only` shows changes ONLY
    under `orchestration/` and `docs/prd/orchestration.md`; `accounts/models.py`,
    `helm/urls.py`, `helm/settings.py`, `templates/base.html`, and other apps'
    files are untouched.

## 9. Out-of-band acceptance for the demo
- During a live remediation, `/orchestration/activity/` visibly shows the
  running remediation workflow and the running remediation agent for the org,
  refreshing without a full page reload.

## 10. Implementation status (builder)
Shipped, all in `orchestration/`:
- `models.py`: nullable `org` FK to `accounts.Org` + `OrgManager`
  (`WorkflowRun.objects.for_org(...)`). [R1, R2]
- `migrations/0002_workflowrun_org.py`: AddField for `org`. [R3]
- `service.py` `_run`: best-effort org resolution (`project.org` →
  `get_current_org()` → `None`) in a try/except that degrades to `org=None`;
  no entry-point signatures changed. [R4, R5]
- `views.py`: `@org_required` + `for_org(request.org)` on `workflow_list`,
  `workflow_table`, `workflow_detail` (foreign-org pk → 404). New `activity` +
  `activity_panel` views, org-scoped to running workflows and running agents
  (`AgentRun ... project__org=request.org`, read-only). [R6, R7, R8, R9, R10]
- `templates/`: `activity.html` + `_activity_panel.html` (HTMX `every 2s`,
  empty state); `workflow_list.html` stat strip (`.stat`/`.grid-4`) + activity
  nav link. All extend base.html, helm.css only. [R11, R12]

Verification: `python manage.py check` clean [R13]; `orchestration.tests`
(autonomous incident→fix loop) 6/6 green with the full parallel migration set
applied [R14]. The pre-existing `tests_smoke.py` (observability-owned) now sees
`/orchestration/` 302 → onboarding when unauthenticated/orgless — expected under
tenancy (R7); integrator/observability should update it to log in + set an org.
