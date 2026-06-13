# PRD — Agents (multitenant + UX)

Owner: PM for `agents/` · Sprint (Build-out, increment 2) · Date: 2026-06-13

> Section goal: the agent layer (`agents/`) is the visible face of Hull's crew of
> Claude agents. Sprint-1 made it multitenant and shipped the live console,
> roster, run filtering, and a per-run timeline. **This increment adds operator
> CONTROL and richer launch + at-a-glance visibility** — the things an operator
> needs to actually trust running an autonomous crew in production — **without
> ever breaking the autonomous incident -> fix loop** and **without editing any
> file outside `agents/`**.

---

## 1. Problem

The agent surface is live and org-scoped, but it is **read-only at runtime** and
**under-controlled**:

1. **No way to stop a running agent.** Once launched, an `AgentRun` runs to
   completion. If a brief is wrong, an agent loops, or cost runs away, the
   operator has no in-product kill switch. For a product whose pitch is "a crew
   of Claude agents operates your stack," a missing stop button is a trust and
   cost-safety gap. The process is spawned via `subprocess.Popen` but its **PID
   is never persisted**, so nothing can terminate it later.

2. **Launch is bare.** The "new agent" form only exposes project / kind / title /
   prompt. The underlying `launch_agent` already supports `base_branch` and
   `open_pr`, but operators can't choose them — every run forks `main` and always
   tries to open a PR, even for a throwaway chore. There's also no inline
   guidance on what each kind means.

3. **No embeddable "who's working now" surface.** The roster and list exist, but
   there's no compact, org-scoped, self-refreshing **active-agents fragment** an
   operator (or another page) can glance at to see the crew in motion. The
   dashboard lives in `core/` (which this section cannot edit), so we must
   **expose** a reusable fragment endpoint rather than wiring it into core.

The hard constraint is unchanged: the autonomous loop runs **without a request**
(org is `None`, no UI session). Every change stays additive with a `None`-org and
no-PID fallback so the loop keeps resolving incidents.

---

## 2. Users & user stories

- **Org operator (cost-aware)** — "An agent is looping or the brief was wrong. I
  hit **Stop** on the run page, the process is killed, and the run is marked
  *cancelled* with its partial output preserved — no orphaned process, no runaway
  spend."
- **Org operator launching work** — "When I launch an agent I can pick the base
  branch and decide whether it should open a PR (e.g. off for a quick chore), and
  I see a one-line description of each kind so I choose correctly."
- **Team lead** — "I drop the **active-agents** strip on a page (or just open
  `/agents/active/`) and watch, org-scoped and auto-refreshing, exactly which
  agents are queued/running right now with live turn + spend counters."
- **The autonomous loop (no user)** — "I keep launching remediation agents with
  `org=None` and no UI; stop/PID handling is best-effort and never required for
  me to run or resolve an incident."
- **Org admin (isolation)** — "A user in Org B cannot stop, view, or stream a run
  that belongs to Org A (404); the stop action is POST + CSRF + org-scoped."

---

## 3. Current state vs target

| Capability | Sprint-1 (current) | This increment (target) |
|---|---|---|
| Org scoping (data + views) | DONE — `AgentRun`/`Worktree` subclass `OrgScopedModel`; views use `for_org`/`scoped` | unchanged (regression-guarded) |
| Live console (incremental stream, timeline) | DONE | unchanged (regression-guarded) |
| Roster + run filtering | DONE | unchanged (regression-guarded) |
| **Stop / cancel a run** | MISSING | **Stop button + POST action; PID persisted on launch; process-group kill; `cancelled` status** |
| **Launch options (base branch, open-PR, kind help)** | MISSING | **Form exposes `base_branch` + `open_pr` (wired to existing kwargs) + per-kind hint** |
| **Embeddable active-agents fragment** | MISSING | **`/agents/active/` org-scoped, self-refreshing fragment** |
| Autonomous loop | INTACT | **still intact (additive, PID/stop optional)** |

---

## 4. Scope — IN (MVP this increment)

### 4.1 Stop / cancel a running agent
- Add a **`CANCELLED`** status to `AgentRun.Status` (additive choice; existing
  rows untouched).
- Persist the agent process PID: add a nullable `pid` (IntegerField) to
  `AgentRun`. In `run_agent`, after `Popen`, store `proc.pid` (best-effort
  `update`); the loop tolerates failure to store it.
- Spawn the agent in its **own process group** (`start_new_session=True` on
  `Popen`) so a stop kills the whole `claude` subprocess tree, not just the
  parent.
- New service `stop_agent(agent_run)`: if the run is queued/running, terminate
  the process group by PID (best-effort — `os.killpg` with `SIGTERM`, swallow
  `ProcessLookupError`/`PermissionError`), set status `cancelled`, set
  `ended_at`, append a `"✗ stopped by operator"` line, and emit an `Event`
  (`level="warning"`, `icon="x"`). Returns the run. **No exception escapes if the
  process is already gone** (loop safety — a finished run can be "stopped" as a
  no-op).
- New view `agent_stop(request, pk)`: **POST only**, `@org_required`, org-scoped
  `get_object_or_404`, calls `services.stop_agent`, redirects back to the detail
  page with a message. New URL `agents:stop` (`<int:pk>/stop/`).
- Detail + list show a **Stop** button only while status in (queued, running).
- The run-already-finished case is a safe no-op (idempotent).

### 4.2 Richer launch form
- The "new agent" form exposes two existing-but-unwired options, passed straight
  through to `launch_agent` (no signature change):
  - **Base branch** (text input, optional; blank -> `launch_agent` default).
  - **Open a PR when done** (checkbox, default checked -> `open_pr`).
- The form shows a short **one-line description per kind** (Feature / Remediation
  / CI / Review / Chore) so operators pick correctly.
- `agent_new` reads `base_branch` and `open_pr` from POST and forwards them; the
  out-of-org-project rejection from Sprint 1 stays.

### 4.3 Embeddable active-agents fragment
- New view `agent_active(request)` + URL `agents:active` (`active/`): an
  **org-scoped** fragment listing runs with status in (queued, running),
  newest-first, with live turn + spend + age, each linking to its detail page.
- The fragment **self-refreshes** via HTMX (`hx-get` on a timer) and renders
  standalone (its own minimal template) so it can be embedded or visited directly
  at `/agents/active/`.
- Empty state ("No agents working right now") when none are active.

### 4.4 Non-regression of Sprint-1 surface
- All Sprint-1 behaviors (org scoping, live console, roster, filtering, timeline,
  design-system compliance, loop safety) remain true. They are re-asserted in the
  rubric so QA catches any regression introduced by this increment.

### 4.5 Design system
- All templates `{% extends "base.html" %}` and use only `helm.css` classes
  (card, badge, btn / btn-danger / btn-sm, list-row, logs, stat, grid-*, pill,
  dot, spinner, toast). Dark UI. No new CSS components, no JS framework.

---

## 5. Scope — OUT (explicitly not this increment)

- Editing `accounts/models.py`, `core/`, or **any** file outside `agents/`
  (forbidden by contract). The active-agents fragment is *exposed* for embedding,
  not wired into `core` by us.
- Pause/resume, retry, or re-dispatch of a stopped run (stop is terminal).
- Killing agents across hosts / via Temporal (best-effort local PID kill only;
  works for the threaded fallback path which the demo uses).
- Real-time WebSockets (keep HTMX polling; minimal vanilla JS only).
- A separate persisted "AgentType"/assignee model — roster stays derived from
  `Kind`.
- Changing any service **signature** in `deploys/`, `observability/`,
  `orchestration/`, or `agents.launch_agent`/`run_agent`/`create_worktree`
  (additive only; `stop_agent` is a NEW function).
- RBAC beyond org membership (who-may-stop is org-scoped, not role-gated yet).

---

## 6. Machine-checkable rubric (pass/fail)

Each item is independently verifiable by grep / `manage.py check` /
`manage.py shell` / a request test. "CHECK" describes the exact probe.

### Stop / cancel
1. **`cancelled` status exists.** CHECK: `"cancelled"` is a value in
   `AgentRun.Status.values`.
2. **`pid` field exists and is nullable.** CHECK:
   `AgentRun._meta.get_field("pid")` exists, is an `IntegerField`, and
   `.null is True`.
3. **Migration present + check clean.** CHECK: `python manage.py makemigrations
   agents --check --dry-run` reports no missing migrations after the new
   migration is committed; `python manage.py check` exits 0.
4. **`stop_agent` exists with stable shape.** CHECK:
   `callable(agents.services.stop_agent)` and
   `inspect.signature(stop_agent)` takes a single positional arg (the run); no
   other required params.
5. **PID stored on launch.** CHECK: grep `agents/services.py` shows `proc.pid`
   written to the `AgentRun` (an `update(...pid=...)` or equivalent) after
   `Popen`, inside `run_agent`.
6. **Own process group.** CHECK: grep `agents/services.py` shows the agent
   `Popen(...)` call passes `start_new_session=True` (or `preexec_fn=os.setsid`).
7. **Stop is best-effort / loop-safe.** Calling `stop_agent` on a run whose
   process is already gone (e.g. `pid=None` or a dead pid) does **not** raise.
   CHECK: shell — create a `done`/`queued` AgentRun with `pid=None`, call
   `stop_agent(run)`; it returns without exception and the run's status is
   `cancelled` (for queued/running) or unchanged-terminal (for done/failed).
8. **Stop sets terminal state.** After `stop_agent` on a running run, the run's
   `status == "cancelled"` and `ended_at` is set. CHECK: shell/request test.
9. **Stop view is POST + org-scoped + guarded.** CHECK: grep `agents/views.py`
   shows `agent_stop` decorated `@org_required`, looks the run up via
   `for_org(request.org)` / `scoped`, and rejects non-POST (e.g.
   `require_POST` or a method check). A cross-org POST returns 404.
10. **Stop URL routes.** CHECK: `reverse("agents:stop", args=[1])` resolves to a
    path ending `/1/stop/`.
11. **Stop button gated by status.** CHECK: grep `detail.html` (and/or
    `list.html`) shows a Stop control rendered only when status in
    (queued, running) — i.e. inside a conditional on `run.status`.

### Launch options
12. **Form exposes base branch + open-PR.** CHECK: grep `new.html` shows an input
    named `base_branch` and a checkbox named `open_pr`.
13. **View forwards options to `launch_agent`.** CHECK: grep `agents/views.py`
    `agent_new` reads `base_branch` and `open_pr` from `request.POST` and passes
    them into `services.launch_agent(...)` (kwargs `base_branch=`/`open_pr=`).
14. **`launch_agent` signature unchanged.** CHECK: `inspect.signature(launch_agent)`
    still matches CONTRACTS.md (`base_branch` and `open_pr` were already kwargs;
    no NEW required params added).
15. **Per-kind guidance present.** CHECK: `new.html` renders a hint/description
    for the agent kinds (grep for kind labels or a help string near the kind
    select).

### Active-agents fragment
16. **`agents:active` route exists + org-scoped.** CHECK: `reverse("agents:active")`
    resolves; the view filters runs to `request.org` via
    `for_org(request.org)`/`scoped`, status in (queued, running). A 200 response
    for an org user shows only that org's active runs.
17. **Fragment self-refreshes.** CHECK: grep the active-agents template for an
    `hx-get`/`hx-trigger="every ..."` that re-fetches `agents:active`.
18. **Fragment org isolation.** CHECK: request test — an Org-B user's
    `/agents/active/` does NOT list an Org-A running run.
19. **Empty state.** CHECK: when no active runs, the fragment renders a non-empty
    "no agents" message (grep template for an empty branch).

### Non-regression (Sprint-1 guarantees still hold)
20. **AgentRun & Worktree still org-scoped & nullable.** CHECK: both subclass
    `accounts.models.OrgScopedModel`; `org` field exists and `.null is True` on
    both; `AgentRun.objects` is an `OrgManager` with a callable `for_org`.
21. **Services still stamp org from project.** CHECK: grep `agents/services.py`
    shows `org=getattr(project, "org", None)` in both the `Worktree.objects.create`
    and `AgentRun.objects.create` calls.
22. **List/detail/stream still org-scoped + `@org_required`.** CHECK: grep
    `agents/views.py` — `agent_list`, `agent_detail`, `agent_stream`, `agent_new`
    each `@org_required` and use `for_org(request.org)`/`scoped`; no bare
    `AgentRun.objects.all()` in request paths; cross-org detail/stream GET -> 404.
23. **Roster route still org-scoped, all five kinds.** CHECK: `reverse("agents:roster")`
    works; response lists Feature, Remediation, CI, Review, Chore labels; counts
    reflect only `request.org`.
24. **Run-list filtering still works.** CHECK: request test — `?status=`,
    `?kind=`, `?project=` each return only matching, in-org runs.
25. **Incremental stream + timeline intact.** CHECK: `_stream.html` still appends
    via out-of-band/`beforeend` swap and stops polling when status terminal
    (now also `cancelled`); `detail.html` still renders the phase/timeline block.
26. **Stream/timeline treat `cancelled` as terminal.** CHECK: grep `_stream.html`
    — polling attrs are emitted only for non-terminal status (i.e. NOT for done /
    failed / cancelled), so a stopped run stops polling.
27. **Autonomous loop intact.** CHECK: import `orchestration.service` and
    `agents.services` succeed; `remediate` still calls `launch_agent` with no new
    required args; launching/running a run with a project whose `org` is `None`
    and no PID-stop still works (shell create + status transitions).
28. **Design-system compliance.** CHECK: every agents template starts with
    `{% extends "base.html" %}`; no `<link rel="stylesheet"` to non-helm CSS, no
    new `<script src=` framework tag; only documented `helm.css` classes used.
29. **No cross-app file edits.** CHECK: `git diff --name-only` touches only files
    under `agents/` plus `docs/prd/agents.md`.

---

## 7. Notes for the builder

- **Models:** add `CANCELLED = "cancelled", "Cancelled"` to `AgentRun.Status` and
  `pid = models.IntegerField(null=True, blank=True)`. Keep every existing field
  and `Meta.ordering`. Run `python manage.py makemigrations agents` (do NOT
  `migrate`). No data backfill needed (both additions default to null/absent).
- **Services:**
  - In `run_agent`, change the agent `Popen(...)` to pass
    `start_new_session=True`, then immediately
    `AgentRun.objects.filter(pk=...).update(pid=proc.pid)` (best-effort; wrap so a
    failure never aborts the run).
  - Add `def stop_agent(agent_run):` — only act if status in
    (`QUEUED`, `RUNNING`); resolve pid, `os.killpg(os.getpgid(pid), SIGTERM)`
    inside a try that swallows `ProcessLookupError`/`PermissionError`/`OSError`;
    set status `CANCELLED` + `ended_at`; `_append(run, "✗ stopped by operator")`;
    `Event.log(... level="warning", icon="x")`. For terminal-status runs, return
    unchanged (no-op). Never raise.
- **Views:**
  - `agent_stop`: `@org_required` + `@require_POST`; org-scoped lookup; call
    `services.stop_agent`; `messages.*`; redirect to `agents:detail`.
  - `agent_new`: also read `request.POST.get("base_branch")` (treat blank as
    `None`) and `open_pr = request.POST.get("open_pr") == "on"` (or a sensible
    default), forward as kwargs. Keep the out-of-org-project `get_object_or_404`.
  - `agent_active`: org-scoped queued/running runs; render the new fragment.
- **URLs:** add `path("<int:pk>/stop/", views.agent_stop, name="stop")` and
  `path("active/", views.agent_active, name="active")`.
- **Templates:** add the Stop `<button class="btn btn-danger btn-sm">` (inside a
  small POST form with `{% csrf_token %}`) on `detail.html` and `list.html`,
  gated on status. Add `base_branch` input + `open_pr` checkbox + kind hints to
  `new.html`. Create `agents/_active.html` (the self-refreshing fragment) for
  `agent_active`. Treat `cancelled` as a terminal status in `_stream.html`'s poll
  condition and in `detail.html`'s timeline.
- **Loop safety:** every new behavior must be a no-op-able, exception-swallowing
  addition. The autonomous `remediate -> launch_agent(... incident=...)` path
  must not require a pid, a request, or an org. Use `getattr(project, "org",
  None)` patterns already established.
- Match `static/css/helm.css`; extend `base.html` via `{% extends %}` only.
</content>
</invoke>
