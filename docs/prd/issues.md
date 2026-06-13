# PRD — Issues (Jira) section (`issues/` app)

Owner: PM agent (Issues section). Sprint 1 ("Build-out"). Target bar from
ROADMAP: *Projects/boards, tickets, sprints, statuses, assignees, labels, links
to PRs/incidents/commits. The agent backlog lives here — PM agents file tickets,
builder agents pick them up.*

---

## 1. Problem

Hull unifies the whole software lifecycle, but there is no place to track *work*.
Today the autonomous loop turns an incident directly into an `agents.AgentRun`
and a PR; humans and agents have no shared backlog, no board to see what is in
flight, no sprint to scope a release, and no durable record linking a unit of
work to the PRs/incidents/commits that resolved it.

This is the seam between humans and the agent crew. A PM agent needs somewhere to
**file tickets**; a builder agent needs somewhere to **pick them up**; a human
needs a **board** to see the org's work at a glance. Every record must be
org-scoped (multitenant) like the rest of Hull, and nothing here may break the
crown-jewel autonomous incident→fix loop.

## 2. Users & user stories

- **Human operator (Member/Admin):** As an operator I want a Kanban board per
  project so I can see every ticket grouped by status and drag-free move it
  through the workflow, so I always know what is in flight.
- **PM agent:** As a PM agent I want to file a ticket via a stable service
  function (title, type, priority, description, labels) so the work I plan
  becomes a first-class backlog item, not just an ad-hoc agent run.
- **Builder agent / operator:** As a builder I want to open a ticket, read its
  description + comments + activity, and see the PRs/incidents/commits linked to
  it, so I have full context to implement it.
- **Operator:** As an operator I want to create a sprint, add tickets to it, and
  see the sprint's tickets grouped by status, so I can scope and track a unit of
  delivery.
- **Anyone:** As a viewer I want to comment on a ticket and have every state
  change (status, assignee, sprint, links) recorded in an activity log, so the
  ticket is a durable, auditable record.
- **Integration:** As the platform I want an incident or a PR to be linkable to a
  ticket so the autonomous loop's output is traceable back to planned work — but
  this linkage is **additive** and never required for the loop to run.

## 3. Scope — IN (MVP, this sprint)

1. **Models (all org-scoped via `accounts.models.OrgScopedModel`)** in
   `issues/models.py`:
   - `Board` — one or more boards, optionally tied to a `projects.Project`.
   - `Sprint` — name, goal, start/end dates, state (planned/active/completed),
     belongs to a board.
   - `Ticket` — the core unit: human key (e.g. `ENG-12`), title, description,
     `type` (story/bug/task/epic), `status` (backlog/todo/in_progress/in_review/
     done), `priority` (low/medium/high/urgent), `assignee` (user, nullable),
     `reporter`, board FK, sprint FK (nullable), `order` for board ranking,
     timestamps. Optional additive links: `incident` FK
     (`observability.Incident`), `pull_request` FK (`vcs.PullRequest`),
     `agent_run` FK (`agents.AgentRun`), `project` FK.
   - `Label` — name + color, org-scoped; M2M to `Ticket`.
   - `Comment` — ticket FK, author, body, created_at.
   - `Activity` — ticket FK, verb/description, actor, created_at (status changes,
     assignment, link events).
2. **Board view** (`/issues/` and `/issues/boards/<pk>/`): columns per status,
   ticket cards showing key, title, type/priority badges, assignee, labels.
   Org-scoped to `request.org`.
3. **Ticket list / backlog view** with filtering by status, type, priority,
   assignee, and label.
4. **Ticket detail** (`/issues/t/<pk>/`): full fields, comments thread (add
   comment via HTMX POST), activity log, and the linked PR/incident/commit/agent
   run rendered as cross-links.
5. **Create / edit ticket** (`/issues/new/`, `/issues/t/<pk>/edit/`): set type,
   status, priority, assignee, labels, sprint, board.
6. **Status / assignee change** actions that move a ticket and append an
   `Activity` row (HTMX-friendly).
7. **Sprint view** (`/issues/sprints/`, `/issues/sprints/<pk>/`): list sprints,
   show one sprint's tickets grouped by status, start/complete a sprint.
8. **Agent-backlog service contract** in `issues/services.py` (stable signatures,
   `org=None` default so the autonomous loop works request-free):
   - `file_ticket(title, *, type="task", priority="medium", description="",
     board=None, project=None, labels=None, reporter=None, incident=None,
     pull_request=None, agent_run=None, org=None) -> Ticket`
   - `pick_ticket(ticket, assignee=None) -> Ticket` (moves to in_progress, logs)
   - `link_ticket(ticket, *, incident=None, pull_request=None, agent_run=None)`
   - `next_ticket_key(board) -> str`
   - `add_comment(ticket, author, body) -> Comment`
   - `log_activity(ticket, verb, actor=None, detail="")`
9. **Org scoping everywhere:** every model subclasses `OrgScopedModel`; every
   view uses `@org_required` + `scoped(Model, request)` /
   `Model.objects.for_org(request.org)`; `org` stays nullable so services default
   `org=None`.
10. **Event-feed integration:** filing/picking/closing a ticket emits a
    `core.models.Event.log(...)` so the demo narrates itself (best-effort, wrapped
    so a failure never breaks the action).
11. **UI:** every template `{% extends "base.html" %}`, uses helm.css classes
    (card, badge, btn, list-row, grid-*, stat), matches the dark theme. HTMX for
    comment add and status change; minimal vanilla JS.
12. **Migrations:** `makemigrations issues` runs clean; `manage.py check` passes.

## 4. Scope — OUT (explicitly deferred)

- Drag-and-drop board reordering with persistence (use buttons / select to move
  status this sprint; `order` field exists for future DnD).
- Sub-tasks / epic→story hierarchy beyond a `type=epic` label.
- Burndown charts, velocity, capacity planning.
- Custom fields, custom workflows / configurable statuses.
- Saved filters / JQL-style query language.
- Ticket watchers, @-mentions, notifications, email.
- Bulk edit, CSV import/export.
- Permissions beyond org membership (per-board roles).
- Automatic two-way sync that makes the autonomous loop *depend* on a ticket
  existing (linkage stays additive + best-effort only).

## 5. Non-negotiables / guardrails

- **Never modify** `accounts/models.py`, `helm/urls.py`, `helm/settings.py`,
  `templates/base.html`, or other apps' files. The integrator adds `issues` to
  INSTALLED_APPS and wires the root URL include.
- **Never break the autonomous loop:** no edits to `deploys.services`,
  `observability.services`, `orchestration.service`, `agents.services`. Any
  cross-app reference (Incident/PR/AgentRun FK) is nullable + additive; the loop
  must still run with no Issues records present.
- Services accept `org=None` and run without a request (thread-free).
- Do not run `migrate`; only `makemigrations issues`. Do not bind port 8000.

---

## 6. Machine-checkable rubric (pass/fail)

Each item is independently verifiable. "imports cleanly" = no exception on
`import`. All paths relative to repo root.

1. **App exists & registered-ready:** `issues/` is a Django app with
   `apps.py` (an `AppConfig`), `models.py`, `views.py`, `urls.py` (with
   `app_name = "issues"`), and a `services.py`. CHECK: files exist.
2. **No forbidden edits:** `accounts/models.py`, `helm/urls.py`,
   `helm/settings.py`, `templates/base.html` are unchanged by this work, and no
   file under `deploys/`, `observability/`, `orchestration/`, `agents/`,
   `vcs/`, `projects/` is modified except additive migrations. CHECK: git diff
   touches only `issues/`, `docs/prd/issues.md` (+ integrator-owned wiring).
3. **Models are org-scoped:** `Ticket`, `Board`, `Sprint`, `Label`, `Comment`,
   `Activity` each subclass `accounts.models.OrgScopedModel` (so each has an
   `org` FK that is nullable). CHECK:
   `Ticket._meta.get_field("org").null is True` and
   `issubclass(Ticket, accounts.models.OrgScopedModel)` for all six.
4. **Ticket core fields exist with choices:** `Ticket` has fields `title`,
   `description`, `type`, `status`, `priority`, `assignee`, `reporter`, `board`,
   `sprint`, and a human key field. `type`, `status`, `priority` use
   `TextChoices`. CHECK: introspect `Ticket._meta` fields + `.choices`.
5. **Additive cross-app links are nullable:** `Ticket` has nullable FKs
   `incident` (→ observability.Incident), `pull_request` (→ vcs.PullRequest),
   `agent_run` (→ agents.AgentRun). CHECK: each field `.null is True`.
6. **Labels are M2M:** `Ticket.labels` is a ManyToMany to `Label`. CHECK:
   `Ticket._meta.get_field("labels").many_to_many is True`.
7. **Service `file_ticket` works request-free with org=None:** calling
   `issues.services.file_ticket(title="x")` (no request, no org) returns a saved
   `Ticket` with a pk and `org is None`. CHECK: run in `manage.py shell`.
8. **Service signatures stable:** `issues.services` defines callables
   `file_ticket`, `pick_ticket`, `link_ticket`, `next_ticket_key`,
   `add_comment`, `log_activity`. CHECK: `hasattr` + `callable`.
9. **`pick_ticket` advances status & logs activity:** after
   `pick_ticket(t)` the ticket's status is `in_progress` and a new `Activity`
   row exists for that ticket. CHECK: shell assertion.
10. **`add_comment` persists:** `add_comment(t, author, "hi")` creates a
    `Comment` linked to `t` whose body is `"hi"`. CHECK: shell assertion.
11. **`link_ticket` is additive:** `link_ticket(t, pull_request=pr)` sets
    `t.pull_request_id == pr.pk` and creates an `Activity`; passing all-None does
    not error. CHECK: shell assertion.
12. **Ticket key generated:** a ticket created via `file_ticket` has a non-empty
    `key`-style field, and `next_ticket_key(board)` returns a string. CHECK:
    `bool(t.<keyfield>)` and `isinstance(next_ticket_key(b), str)`.
13. **URLs resolve:** reversing `issues:board` (or board list), `issues:ticket`
    (with a pk), `issues:ticket_new`, `issues:sprints` succeeds. CHECK:
    `django.urls.reverse` for each named route.
14. **Board view is org-scoped & 200:** an authenticated request to the board
    list URL returns HTTP 200 and only renders tickets for `request.org` (a
    ticket in another org is absent from context/response). CHECK: Django test
    client with two orgs.
15. **Ticket detail renders comments + activity + links:** GET ticket detail for
    a ticket with a comment, an activity row, and a linked PR returns 200 and the
    response contains the comment body, the activity text, and a link to the PR's
    `get_absolute_url()`. CHECK: test client assertContains.
16. **Add-comment view works:** POST to the add-comment URL for a ticket creates
    a `Comment` and returns 200/redirect; the new comment appears on reload.
    CHECK: test client.
17. **Status-change action logs activity:** POSTing a status change to a ticket
    updates `status` and appends an `Activity`. CHECK: test client.
18. **Sprint grouping:** the sprint detail view groups its tickets by status and
    returns 200; a ticket added to the sprint appears under its status column.
    CHECK: test client.
19. **Templates extend base & use design system:** every template under
    `issues/templates/issues/` contains `{% extends "base.html" %}` and uses at
    least one helm.css class (`card`/`badge`/`btn`/`list-row`/`grid-`). CHECK:
    grep over templates.
20. **Loop intact:** `python manage.py check` passes and importing
    `deploys.services`, `observability.services`, `orchestration.service`,
    `agents.services` still succeeds with no Issues records present (Issues code
    is import-safe and never invoked by the loop). CHECK: `manage.py check` +
    import test.
21. **Migrations clean:** `python manage.py makemigrations issues` produces a
    migration with no errors and `manage.py check` reports no model issues.
    CHECK: run command.
22. **Org scoping in views enforced:** every view function in `issues/views.py`
    that lists/reads tenant data is wrapped with `@org_required` (or otherwise
    filters via `scoped(...)`/`.for_org(request.org)`), and no view returns
    cross-org records. CHECK: code review + test 14.
23. **Event feed emission (best-effort):** `file_ticket` attempts
    `core.models.Event.log(...)`, wrapped so an Event failure does not raise out
    of `file_ticket`. CHECK: code review + shell call still returns a Ticket if
    Event logging is monkeypatched to raise.

---

## 7. Ticket list for the builder

See the returned `tickets` array. Build order: T1 (models) → T2 (services) →
T3 (board/list) → T4 (detail+comments+activity) → T5 (create/edit + actions) →
T6 (sprints) → T7 (links + event feed + polish) → T8 (migrations + check + smoke
tests). T1 and T2 are the critical path for the rubric; the autonomous-loop
guardrail (rubric 20) must hold throughout.
