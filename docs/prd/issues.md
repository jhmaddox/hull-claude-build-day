# PRD — Issues (Jira) section (`issues/` app)

Owner: PM agent (Issues section). Sprint 1 ("Build-out"), **refresh**. Target bar
from ROADMAP: *Projects/boards, tickets, sprints, statuses, assignees, labels,
links to PRs/incidents/commits. The agent backlog lives here — PM agents file
tickets, builder agents pick them up.*

> **State of the world (read before building).** The Issues foundation already
> shipped and is green: `issues/` is a registered app (in INSTALLED_APPS, URL
> include `/issues/`, nav entry in `base.html`); `models.py` has `Board`,
> `Sprint`, `Label`, `Ticket`, `Comment`, `Activity` all subclassing
> `accounts.models.OrgScopedModel`; `services.py` exposes `file_ticket`,
> `pick_ticket`, `link_ticket`, `set_status`, `add_comment`, `log_activity`,
> `next_ticket_key`, `get_or_create_default_board`; views cover board / backlog /
> ticket detail (comments + activity) / create / edit / status / assign /
> sprints; 13 tests pass; `manage.py check` is clean. **Do not rebuild this.**
> This refresh layers the highest-impact increments on top — most importantly the
> crown-jewel integration: the autonomous loop must mint and drive a ticket.

---

## 1. Problem

Hull unifies the whole software lifecycle, but the Issues section today is an
**island**. It has a board and a working agent-backlog service API, yet nothing
in the product actually *files* a ticket: the autonomous incident → agent fix →
PR loop — Hull's crown jewel — runs end to end without ever creating the backlog
item the roadmap says "lives here." A human watching the demo sees an incident
resolve, but the board stays empty. That breaks the core narrative ("PM agents
file tickets, builder agents pick them up, the work is traceable to the PRs and
incidents that resolved it").

Secondary gaps: the backlog cannot be **filtered** (so it does not scale past a
handful of tickets), **boards and sprints are read-only** (you cannot create a
board, start/complete a sprint, or move a ticket into a sprint from the UI), and
**labels exist in the model but have no UI** (cannot be created or attached). The
seam between humans and the agent crew is therefore not yet usable as a real
work-tracking surface.

This refresh closes that seam: wire the loop into the backlog (additive,
best-effort, never blocking), make the backlog filterable, and make boards /
sprints / labels manageable — all org-scoped, all without touching the
autonomous-loop contracts.

## 2. Users & user stories

- **The platform (autonomous loop):** As Hull, when an incident fires and I spawn
  a remediation agent, I want a ticket automatically filed and linked to the
  incident, then linked to the resulting PR/agent-run and moved to In Progress →
  Done as the loop progresses, so the board narrates the autonomous work — but
  this must be **best-effort and additive**: if Issues is absent or throws, the
  loop still resolves the incident.
- **Human operator:** As an operator I want to filter the backlog by status,
  type, priority, assignee, and label, so I can find work in a large list.
- **Operator:** As an operator I want to create a board and create / start /
  complete a sprint and add tickets to it, so I can scope and run a delivery
  cycle from the UI, not just the shell.
- **Operator:** As an operator I want to create labels and attach/detach them on
  a ticket, so I can categorize work (bug, infra, agent, customer).
- **Operator / builder agent:** As anyone viewing a ticket I want the linked
  incident, PR, and agent-run rendered as live cross-links, so I can jump to the
  context that produced or resolved the work.
- **Operator:** As an operator I want a single "Agent backlog" view that surfaces
  tickets filed by agents (vs. humans) with their linked incident/PR, so I can
  see at a glance what the crew is doing.

## 3. Scope — IN (this refresh, highest-impact MVP)

> Build order is the ticket order (T1 is the crown-jewel win; do it first).

1. **Autonomous-loop ticket integration (CROWN JEWEL, additive only).** A single
   helper — `issues.services.ticket_for_incident(incident, *, status=None,
   pull_request=None, agent_run=None, org=None)` — that, given an
   `observability.Incident`, finds-or-creates exactly one `Ticket` linked to that
   incident (`type=incident`, idempotent: never two tickets for one incident),
   updates its status/links if provided, and logs Activity + Event. It MUST be
   wrapped so any exception is swallowed and returns `None` (the loop never
   breaks). Then call it from the loop's existing narration points
   (`orchestration/service.py` remediation pipeline) at: incident detected (file
   ticket, link incident), agent spawned / PR opened (link PR + agent-run, move
   to In Progress), incident resolved (move ticket to Done) — each call
   try/except-wrapped and best-effort. **Idempotency** is via the existing
   `Ticket.incident` FK (one ticket per incident).
2. **Backlog filtering.** `backlog` view accepts GET params `status`, `type`,
   `priority`, `assignee`, `label`, `q` (title contains) and filters the scoped
   queryset; the template renders a filter bar (selects + text search) that
   round-trips the current selection. Empty params = no filter. All filtering
   stays within `request.org`.
3. **Board & sprint management (write actions).**
   - Create a board: `issues:board_new` (name, key, optional project).
   - Create a sprint: `issues:sprint_new` (name, goal, board, dates).
   - Start / complete a sprint: actions that set `Sprint.status` active/completed
     and log Activity on affected tickets (or the sprint), best-effort.
   - Add/remove a ticket to/from a sprint from the ticket detail (a select that
     POSTs; logs Activity).
4. **Labels UI.** Create labels (`issues:label_new`: name + color class) and
   attach/detach labels on the ticket form / ticket detail (checkbox or
   multi-select); the board and backlog already render label chips — ensure they
   show. All label ops org-scoped.
5. **Agent-backlog view.** `issues:agent_backlog` (`/issues/agents/`): list
   tickets that were agent-filed (heuristic: `reporter is None and reporter_name`
   set, or any of `incident`/`agent_run`/`pull_request` linked), newest first,
   each row showing the linked incident/PR/agent-run as cross-links. Org-scoped.
6. **Cross-link rendering hardening.** Ticket detail renders `incident`,
   `pull_request`, and `agent_run` as `<a>` links to their
   `get_absolute_url()` (incident, PR) / agents detail, each guarded so a missing
   reverse never 500s.
7. **Keep it all org-scoped & loop-safe.** Every new view is `@org_required` and
   filters via `scoped(...)` / `.for_org(request.org)`; every new service path
   defaults `org=None` and is import-safe; every loop touch-point is
   try/except-wrapped. New cross-app references stay nullable + additive.
8. **Tests + migrations + check.** Add tests for each new behavior (rubric below);
   `makemigrations issues` clean if the model changes (this refresh should need
   **no schema change** — reuse existing fields); `manage.py check` passes;
   existing 13 tests stay green.

## 4. Scope — OUT (explicitly deferred)

- Drag-and-drop board reordering with persistence (`order` field exists; use
  status select to move; DnD deferred).
- Burndown / velocity / capacity charts.
- Sub-tasks / epic→story hierarchy, custom fields, custom workflows.
- Saved filters / JQL query language (this refresh ships simple GET-param
  filters only).
- Watchers, @-mentions, notifications, email.
- Bulk edit, CSV import/export, per-board roles.
- Making the autonomous loop **depend** on a ticket — linkage stays additive +
  best-effort; the loop must still resolve incidents with Issues uninstalled or
  throwing.
- Two-way edit-back from ticket to PR/incident (one-way links only).

## 5. Non-negotiables / guardrails

- **Never modify** `accounts/models.py`, `helm/urls.py`, `helm/settings.py`,
  `templates/base.html`. The integrator already wired INSTALLED_APPS + URL
  include + nav; do not duplicate.
- **Never break the autonomous loop.** The only edits outside `issues/` are the
  additive, try/except-wrapped call sites inside `orchestration/service.py`
  remediation pipeline (T1). Do **not** edit `deploys.services`,
  `observability.services`, `agents.services`, or change any existing
  orchestration signature. Each loop touch-point must be wrapped so an Issues
  failure is swallowed; the incident must still resolve with Issues disabled.
- `ticket_for_incident` and all services accept `org=None` and run request-free
  (thread-free); they never raise into the loop.
- Idempotency: one ticket per incident (keyed on `Ticket.incident`).
- Do not run `migrate`; only `makemigrations issues` (and only if a field is
  truly added — prefer reusing existing fields). Do not bind port 8000 (use
  8011+ for smoke tests, kill after).
- Every template `{% extends "base.html" %}`, `{% load helm_extras %}`, uses
  helm.css classes; HTMX for in-place actions; minimal vanilla JS.

---

## 6. Machine-checkable rubric (pass/fail)

Each item is independently verifiable. "imports cleanly" = no exception on
`import`. All paths relative to repo root. Items R1–R12 are the **refresh**
acceptance gate; the foundation (already shipped) is re-asserted in R13–R18 to
guard against regressions.

1. **`ticket_for_incident` exists & is callable:** `issues.services` defines a
   callable `ticket_for_incident`. CHECK: `hasattr(issues.services,
   "ticket_for_incident") and callable(...)`.
2. **One ticket per incident (idempotent):** calling `ticket_for_incident(inc)`
   twice for the same incident returns/leaves exactly **one** `Ticket` with
   `incident_id == inc.pk`. CHECK: shell — `Ticket.objects.filter(incident=inc).count() == 1`
   after two calls.
3. **`ticket_for_incident` is loop-safe (swallows errors, returns None):** if
   ticket creation is forced to raise (e.g. monkeypatch `Ticket.objects.create`
   to raise, or pass a bad incident), the call returns `None` and does **not**
   propagate. CHECK: shell — wrapped call returns `None`, no exception.
4. **Loop still resolves with Issues failing:** the orchestration remediation
   pipeline calls into Issues inside try/except; simulating an Issues exception
   at every Issues call site does not change the incident's terminal resolution.
   CHECK: code review of `orchestration/service.py` (every `issues`/
   `ticket_for_incident` call is inside a `try`/`except`) **and** the loop's
   own tests/pipeline still pass with Issues monkeypatched to raise.
5. **Loop links incident→ticket→PR/agent-run:** after a remediation run (or a
   direct simulation that calls the same touch-points), the incident's ticket has
   `incident_id` set and, when a PR/agent-run is produced, `pull_request_id` /
   `agent_run_id` set, and a terminal status of `done` when the incident
   resolves. CHECK: shell/test asserting the linked ticket's fields.
6. **Backlog filtering by status works & is org-scoped:** GET
   `issues:backlog?status=done` returns 200 and only `done` tickets of
   `request.org`; a different-org ticket never appears. CHECK: test client with
   two orgs.
7. **Backlog filter bar round-trips:** the backlog template renders a filter
   control for status, type, priority, assignee, and a text query `q`; submitting
   preserves the selected values in the rendered form. CHECK: test client
   assertContains the selected option marked selected (or grep template for the
   filter form + selects).
8. **Board create works:** POST to `issues:board_new` with a name+key creates a
   `Board` scoped to `request.org` and redirects/200; the new board appears on
   the board/boards UI. CHECK: test client.
9. **Sprint create + start/complete works:** POST to `issues:sprint_new` creates
   a `Sprint` for `request.org`; a start action sets its status to `active` and a
   complete action sets `completed`. CHECK: test client — status transitions.
10. **Add-to-sprint from ticket works & logs Activity:** POSTing a sprint
    selection on a ticket sets `Ticket.sprint` and appends an `Activity` row.
    CHECK: test client.
11. **Label create + attach works:** POST to `issues:label_new` creates a `Label`
    for `request.org`; attaching it to a ticket (via the form/detail action) adds
    it to `Ticket.labels`, and the chip renders on the ticket/backlog. CHECK:
    test client — `t.labels.filter(pk=label.pk).exists()` and assertContains.
12. **Agent-backlog view 200 & shows agent tickets only-for-org:** GET
    `issues:agent_backlog` returns 200, lists an agent-filed ticket of
    `request.org` (with its incident/PR cross-link rendered), and omits a
    different-org ticket. CHECK: test client with two orgs.
13. **(Regression) Models org-scoped & nullable org:** `Ticket`, `Board`,
    `Sprint`, `Label`, `Comment`, `Activity` each subclass
    `accounts.models.OrgScopedModel` and `org` is nullable. CHECK: introspect
    `_meta` + `issubclass`.
14. **(Regression) Additive cross-app links nullable:** `Ticket.incident`,
    `Ticket.pull_request`, `Ticket.agent_run` each have `.null is True`. CHECK:
    field introspection.
15. **(Regression) Core services stable & request-free:** `file_ticket`,
    `pick_ticket`, `link_ticket`, `next_ticket_key`, `add_comment`,
    `set_status`, `log_activity` exist and `file_ticket(title="x")` (no org)
    returns a saved `Ticket` with `org is None`. CHECK: shell.
16. **(Regression) Every view org-scoped:** every view in `issues/views.py` that
    lists/reads tenant data is `@org_required` and filters via `scoped` /
    `.for_org`; no cross-org leak (re-run the two-org detail/board tests). CHECK:
    code review + tests R6/R12 + the existing cross-org test.
17. **(Regression) Templates extend base & use design system:** every template
    under `issues/templates/issues/` contains `{% extends "base.html" %}` and at
    least one helm.css class (`card`/`badge`/`btn`/`list-row`/`grid-`). CHECK:
    grep.
18. **(Regression) Loop import-safe & check passes:** `python manage.py check`
    passes; importing `deploys.services`, `observability.services`,
    `orchestration.service`, `agents.services` still succeeds; `makemigrations
    issues` reports no changes (or a clean additive migration). CHECK: run
    commands. All previously-passing Issues tests stay green.

---

## 7. Ticket list for the builder

See the returned `tickets` array. **Build order = ticket order.** T1 (the
autonomous-loop ticket integration) is the crown-jewel demo win and the single
highest-impact item — do it first and guard rubric R3/R4 (loop-safety) the whole
way. T2–T5 make the backlog/boards/sprints/labels usable; T6 adds the
agent-backlog surface; T7 hardens cross-links, tests, and the regression gate.
