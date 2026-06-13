# PRD — Agents (multitenant + UX)

Owner: PM for `agents/` · Sprint 1 (Build-out) · Date: 2026-06-13

> Section goal: org-scope every agent run and worktree, and ship a great
> **live agent console** plus an **agent roster / types** surface — all on top
> of the `accounts` tenancy contract, **without ever breaking the autonomous
> incident -> fix loop**.

---

## 1. Problem

Hull's crown jewel is the autonomous **incident -> agent fix -> PR -> CI ->
merge -> redeploy** loop. The agent layer (`agents/`) is the visible face of
that crew, but today it has two gaps:

1. **Not multitenant.** `agents/views.py` queries `AgentRun.objects.all()` and
   `Project.objects.all()` with no org filter. Any logged-in user in any org can
   see and launch agents against every other org's projects. `AgentRun` and
   `Worktree` have no `org` field, so there is no way to filter by tenant at the
   data layer. This violates the Sprint-0 multitenancy contract that every
   record is org-scoped.

2. **Weak operator UX.** The agent console is a single self-polling log block.
   There is no roster view of the crew, no filtering of runs (by status / kind /
   project), no at-a-glance health of "who is working right now," and the live
   stream re-renders the whole block (losing scroll, flashing) instead of
   appending. For a product whose pitch is "a crew of Claude agents operates
   your stack," the agent surface must feel alive and trustworthy.

The hard constraint: the autonomous loop runs **without a request** (org is
`None`). Every change must stay additive with a `None`-org fallback so the loop
keeps resolving incidents.

---

## 2. Users & user stories

- **Org operator (member/admin)** — "I open Agents and see only my org's runs.
  I can filter to just the running remediation agents and watch one fix an
  incident live, line by line, without the page flashing."
- **Org operator launching work** — "When I launch a feature agent, I can only
  pick projects in my current org; the run is automatically tagged to my org."
- **Team lead** — "I see a roster of agent types (PM / Builder / QA / Remediation)
  with how many runs each has done, success rate, and total spend, scoped to my
  org."
- **The autonomous loop (no user)** — "I keep launching remediation agents with
  `org=None` and they keep running; nothing I do requires a `request.org`."
- **Org admin** — "A user in Org B cannot open `/agents/<pk>/` for a run that
  belongs to Org A (404), and cannot launch an agent against Org A's project."

---

## 3. Scope — IN (MVP this sprint)

### 3.1 Multitenancy (data + request paths)
- `AgentRun` and `Worktree` subclass `accounts.models.OrgScopedModel` (adds a
  nullable `org` FK + `OrgManager`). `org` stays **nullable** (loop safety).
- `agents/services.py` stamps `org` on every `Worktree` and `AgentRun` it
  creates, **derived from `project.org`** (falls back to `None` when the project
  has no org — e.g. autonomous loop). No new required args; signatures unchanged.
- All request-path views in `agents/views.py` filter to `request.org`:
  - list view shows only `org`-scoped runs,
  - detail / stream return 404 for out-of-org runs,
  - the "new agent" form only offers in-org projects,
  - launching is rejected if the chosen project is not in `request.org`.
- Views use `@org_required` + `accounts.scoping` helpers (`scoped`,
  `Model.objects.for_org(request.org)`).

### 3.2 Live agent console (UX)
- **Incremental log append**: the stream fragment appends new output instead of
  replacing the full block, preserving scroll-to-bottom and avoiding flashing.
- Live header shows status badge, turns, cost, and a "tailing" pill while
  running; stops polling cleanly on done/failed.
- A compact **timeline / phase** indicator (queued -> running -> committed ->
  PR -> done) on the detail page derived from existing fields
  (`status`, `pull_request`, commit lines).

### 3.3 Agent roster / types
- A **roster** view (`/agents/roster/`) listing agent **kinds**
  (Feature / Remediation / CI / Review / Chore) with per-kind counts for the
  current org: total runs, running now, done, failed, and total spend.
- The roster is org-scoped and links each kind to a filtered run list.

### 3.4 Run list filtering
- The Agents list supports filtering by `status`, `kind`, and `project` via
  querystring (HTMX-friendly), all within the current org.

### 3.5 Design system
- All templates `{% extends "base.html" %}` and use only `helm.css` classes
  (card, badge, btn, list-row, logs, stat, grid-*, pill, dot, spinner). Dark UI.

---

## 4. Scope — OUT (explicitly not this sprint)

- Editing `accounts/models.py` or any other app's files (forbidden by contract).
- Changing service **signatures** in `deploys/`, `observability/`,
  `orchestration/`, or `agents/launch_agent`/`run_agent` (additive only).
- Pausing/stopping a running agent, retries, or re-dispatch UI.
- Cross-org sharing, per-user RBAC beyond org membership, agent permissions.
- WebSocket streaming (keep HTMX polling; no heavy JS).
- Persisting a separate "AgentType" model — roster is derived from `Kind`.
- Backfilling `org` on historical rows beyond a best-effort data migration.
- Modifying `helm/urls.py`, `helm/settings.py`, or `templates/base.html`.

---

## 5. Machine-checkable rubric (pass/fail)

Each item is independently verifiable by grep / `manage.py check` /
`manage.py shell` / a request test. "check" describes the exact probe.

1. **AgentRun is org-scoped.** `agents.models.AgentRun` subclasses
   `accounts.models.OrgScopedModel`. CHECK: `AgentRun` MRO includes
   `OrgScopedModel`; `AgentRun._meta.get_field('org')` exists and is a FK to
   `accounts.Org`.
2. **Worktree is org-scoped.** `agents.models.Worktree` subclasses
   `OrgScopedModel`. CHECK: same probe on `Worktree`.
3. **org is nullable on both.** CHECK: `AgentRun._meta.get_field('org').null is
   True` and `Worktree._meta.get_field('org').null is True`.
4. **OrgManager present.** CHECK: `AgentRun.objects` is an instance of
   `accounts.models.OrgManager` and `AgentRun.objects.for_org` is callable.
5. **Migration exists and check passes.** CHECK: `python manage.py makemigrations
   agents --check --dry-run` reports no missing migrations after the migration
   file is committed; `python manage.py check` exits 0.
6. **Services stamp org from project.** CHECK: `agents.services.launch_agent`
   creates the `AgentRun` (and `create_worktree` creates the `Worktree`) with
   `org=getattr(project, "org", None)`. Grep `agents/services.py` for `org=` in
   the `AgentRun.objects.create(` and `Worktree.objects.create(` calls.
7. **Loop safety: org=None tolerated.** Creating an `AgentRun`/`Worktree` with a
   project whose `org` is `None` succeeds (no exception). CHECK: shell-create an
   AgentRun via the same path with a project that has `org=None`; it saves.
8. **`launch_agent`/`run_agent`/`create_worktree` signatures unchanged.** CHECK:
   `inspect.signature` of each matches the CONTRACTS.md signature (no new
   required positional/keyword params).
9. **List view is org-scoped.** `agent_list` filters runs to `request.org`
   (uses `scoped(...)` or `.for_org(request.org)`), not `AgentRun.objects.all()`.
   CHECK: grep `agents/views.py` shows no bare `AgentRun.objects.all()` /
   `[:100]` without an org filter in `agent_list`; uses `request.org` or
   `scoped`/`for_org`.
10. **Detail view 404s cross-org.** `agent_detail` scopes the lookup to
    `request.org`. CHECK: a request from a user in Org B for an Org-A run returns
    HTTP 404 (request test), and grep shows the `get_object_or_404` is scoped
    (`for_org(request.org)` / `scoped`).
11. **Stream view 404s cross-org.** Same scoping applied to `agent_stream`.
    CHECK: grep shows org filter in `agent_stream`; cross-org GET -> 404.
12. **New-agent form is org-scoped.** `agent_new` offers only projects in
    `request.org`. CHECK: grep shows projects queried via `scoped`/`for_org`/
    `request.org`, not `Project.objects.all()`.
13. **Launch rejects out-of-org project.** POST to `agents:new` with a project
    not in `request.org` does NOT create an AgentRun (404 or re-render with
    error). CHECK: request test — AgentRun count unchanged.
14. **Views require org.** `agent_list`, `agent_new`, `agent_detail`,
    `agent_stream` are guarded by `@org_required` (or equivalent
    login+org check). CHECK: grep `@org_required` above each view; anonymous GET
    redirects to login/onboarding.
15. **Roster route exists and is org-scoped.** A URL named `agents:roster`
    resolves and the view aggregates run counts per `Kind` filtered to
    `request.org`. CHECK: `reverse('agents:roster')` works; response 200 for an
    org user; counts reflect only that org's runs.
16. **Roster shows all five kinds.** The roster lists Feature, Remediation, CI,
    Review, Chore with a count each (zero allowed). CHECK: response contains each
    kind's display label.
17. **Run list filtering works.** `agent_list` honors `?status=`, `?kind=`, and
    `?project=` querystring filters, each still org-scoped. CHECK: request test —
    a filtered list returns only matching, in-org runs.
18. **Incremental stream (no full flash).** `_stream.html` appends new log lines
    (e.g. via `hx-swap="beforeend"` targeting the log body, or an out-of-band
    append) rather than replacing the whole `#stream` block every poll, and
    stops polling when status is done/failed. CHECK: grep `_stream.html` for an
    append-style swap / oob on the log body; polling attrs absent when status in
    (done, failed).
19. **Timeline indicator present.** `detail.html` renders a phase/timeline
    element derived from existing fields (queued/running/committed/PR/done).
    CHECK: grep `detail.html` for a timeline/phase block referencing run status
    and `pull_request`.
20. **Design-system compliance.** Every agents template starts with
    `{% extends "base.html" %}` and uses only documented `helm.css` classes; no
    inline `<style>` blocks adding new component CSS, no new JS framework.
    CHECK: grep each template for the extends tag; grep for absence of
    `<link rel="stylesheet"` to non-helm CSS and absence of new `<script src=`
    framework tags.
21. **Autonomous loop intact.** `orchestration.service.remediate` ->
    `launch_agent(..., incident=...)` path still imports and runs without a
    `request` (org defaults to project's org or None). CHECK: import
    `orchestration.service` and `agents.services` succeed; `remediate` still
    calls `launch_agent` with no new required args (grep + import test).
22. **No cross-app file edits.** Only files under `agents/` (plus
    `docs/prd/agents.md`) are modified. CHECK: `git diff --name-only` touches
    only `agents/...` and the PRD.
23. **Data migration backfills org best-effort.** The agents migration backfills
    existing `AgentRun`/`Worktree.org` from `project.org` where available (rows
    with no project-org stay `None`). CHECK: migration file contains a
    `RunPython` (or equivalent) that sets `org` from related project; reversible
    or no-op reverse.

---

## 6. Notes for the builder

- Import the contract: `from accounts.models import OrgScopedModel` in
  `agents/models.py`; subclass it on `Worktree` and `AgentRun` (replace
  `models.Model`). Keep all existing fields and `Meta.ordering`.
- Run `python manage.py makemigrations agents` (do NOT `migrate`). Add a
  `RunPython` step that backfills `org` from `project.org`.
- In `services.py`, set `org=getattr(project, "org", None)` in both
  `Worktree.objects.create(...)` and `AgentRun.objects.create(...)`. Do not add
  params to public functions.
- In `views.py`, add `@org_required` and replace `.all()` queries with
  `scoped(Model, request)` / `Model.objects.for_org(request.org)`. For detail/
  stream use `get_object_or_404(AgentRun.objects.for_org(request.org), pk=pk)`.
- Roster: aggregate `for_org(request.org)` runs grouped by `kind` (a dict in the
  view is fine; no new model).
- Stream UX: target the log `<div>` with `hx-swap="beforeend"` or out-of-band
  append; keep the 1.5s poll only while `status in (queued, running)`.
- Match the look in `static/css/helm.css`; extend `base.html` via `{% extends %}`
  only. Add roster + filter links to the existing list page.
- Remember: `projects.Project` may not yet have an `org` field this sprint —
  hence `getattr(project, "org", None)` (do not hard-import a Project.org).
