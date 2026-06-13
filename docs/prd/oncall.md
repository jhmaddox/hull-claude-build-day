# PRD — Incidents v2 (PagerDuty-level) · `oncall/` app

Owner: Incidents v2 PM workstream
Sprint: 1 (Build-out)
New app: `oncall/` (org-scoped, multitenant)
Status: ready for builder

---

## 1. Problem

Hull already auto-detects production errors and runs the crown-jewel autonomous
loop (`observability` → `orchestration.remediate`): an error opens an
`observability.Incident`, a Claude SRE agent fixes the root cause, opens a PR,
CI runs, and on green it merges + redeploys + resolves. That loop is great at the
*machine* half of incident response.

What is missing is the *human + process* half that PagerDuty provides, and which
enterprises require even when remediation is automated:

- **Who owns this right now?** There is no concept of on-call. No schedules, no
  rotations, no "page the right human."
- **What happens when the robot can't fix it?** Today, if CI fails or no PR is
  produced, the incident silently sits in `firing`/`remediating`. There is no
  escalation policy that pages a human after N minutes.
- **What actually happened, in order?** The incident detail page reconstructs a
  rough timeline by string-matching the Event feed. There is no first-class,
  durable, ordered incident timeline that records every ack, assignment,
  escalation, note, severity change, and the autonomous loop's own steps.
- **Was it acknowledged / resolved by a human?** There is no human ack/resolve
  with attribution, and no record of who.
- **What did we learn?** No postmortems. No blameless writeup, no action items.
- **Why did this page fire?** No alert-routing rules a team can configure
  (e.g. "sev1 from project X → page the platform schedule immediately").
- **None of it is org-scoped.** The existing `observability.Incident` has no
  `org` FK, so in a multitenant world incidents leak across tenants.

This is the PagerDuty-shaped layer: **severities, on-call schedules, escalation
policies, a real incident timeline, human ack/resolve, postmortems, and alert
routing — wired into (never replacing) the autonomous remediation loop.**

### Hard constraint (non-negotiable)
The autonomous `incident → fix → PR → CI → merge → redeploy → resolved` loop is
the crown jewel and a hard QA gate. **Every change in this section is additive
and guarded by fallbacks.** `oncall` hooks the loop through optional, exception-
swallowing calls; if every `oncall` model/table/import were deleted, the loop
must still resolve an incident exactly as it does today.

---

## 2. Users & user stories

- **SRE / on-call engineer**
  - As on-call, I want to be paged when a sev1/sev2 fires so I know to look.
  - As on-call, I want to **acknowledge** an incident so others know I have it.
  - As on-call, I want to add **timeline notes** so the response is documented.
  - As on-call, I want to **manually resolve** an incident the robot couldn't.
- **Engineering manager / team lead**
  - As a lead, I want to define **on-call schedules** (who is on-call this week)
    so paging is unambiguous.
  - As a lead, I want **escalation policies** (page on-call; if not acked in
    N minutes, escalate to the next level) so nothing is dropped.
  - As a lead, I want **alert-routing rules** (which incidents page which
    schedule) so the right team is engaged.
  - As a lead, I want a **postmortem** per resolved sev1/sev2 with action items
    so we actually learn.
- **Everyone (tenant isolation)**
  - As a member of org A, I must only ever see org A's incidents, schedules,
    policies, and postmortems.
- **The autonomous loop (non-human actor)**
  - As the remediation pipeline, I want every step I take (ack, agent dispatch,
    PR opened, CI result, merge, redeploy, resolve) appended to the incident
    timeline so humans can follow along — without my pipeline ever breaking if
    that logging fails.

---

## 3. Scope

### Scope IN (this sprint — the MVP)

1. **`oncall/` Django app, org-scoped.** All new models subclass
   `accounts.models.OrgScopedModel`. Request paths scoped via
   `accounts.scoping` (`org_required`, `scoped`, or `.for_org(request.org)`).
   `org` stays nullable so the loop works request-less (`org=None`).
2. **Org backfill for `observability.Incident`.** Add a nullable `org` FK to the
   existing Incident model by subclassing `OrgScopedModel` (allowed by the
   contract — "existing models add org by subclassing OrgScopedModel"). Populate
   it best-effort from `incident.project` when an incident is opened. Do NOT
   rename or remove any existing Incident field.
3. **Severities (config + display).** A canonical severity ladder (sev1/sev2/
   sev3, matching the existing `Incident.Severity`) surfaced with colored badges
   and human labels, plus a per-org default-severity mapping used by routing.
4. **On-call schedules.** `Schedule` (name, org, timezone) with ordered
   `ScheduleMember` rotation entries (user + order). A
   `schedule.current_oncall(at=now)` helper resolves the active on-call user by
   weekly rotation. Read/write UI to create a schedule and order its members.
5. **Escalation policies.** `EscalationPolicy` with ordered `EscalationStep`s
   (target schedule + `after_minutes`). A pure function
   `escalation.next_step(policy, minutes_elapsed)` returns the step that should
   be active. (Time-based auto-paging is driven by a tick endpoint; see #8.)
6. **Alert routing.** `RoutingRule` (org, optional project filter, min severity,
   target escalation policy, priority/order). `routing.route(incident)` selects
   the first matching rule for the incident's org and returns its policy +
   first on-call user. Wired so that when an incident opens, a page is recorded
   on the timeline (additive, best-effort).
7. **First-class incident timeline.** `TimelineEntry` (incident FK, org, kind,
   message, actor, optional user, created_at). Kinds at least: `opened`,
   `paged`, `acknowledged`, `assigned`, `escalated`, `note`, `severity_changed`,
   `agent`, `pr`, `ci`, `merge`, `deploy`, `resolved`, `reopened`. A helper
   `timeline.record(incident, kind, message, actor=, user=)` that is
   exception-safe. The autonomous loop calls this at each step via best-effort
   hooks; it also seeds an `opened` entry when an incident is created.
8. **Human ack / resolve / assign / note / escalate actions** (HTMX POST views,
   org-scoped, login + membership required): acknowledge (sets
   `observability.Incident.status=acknowledged` + `acknowledged_at`, records
   timeline + assigns actor), resolve (sets `status=resolved` + `resolved_at`,
   records timeline), assign to a user, add a note, manual "escalate now". Plus
   a **tick** endpoint `/oncall/incidents/<pk>/tick/` (idempotent) that, given
   elapsed time since open and the routed policy, records an `escalated` timeline
   entry / re-page when the current step's `after_minutes` has passed and the
   incident is still unacked. (Drives time-based escalation without a cron.)
9. **Postmortems.** `Postmortem` (incident OneToOne, org, summary, root_cause,
   impact, resolution, lessons, markdown body, author, created_at) with
   ordered `ActionItem`s (title, owner, done). Create/edit UI reachable from a
   resolved incident. Auto-stub a postmortem skeleton when a sev1/sev2 resolves.
10. **Incident center UI** at `/oncall/`: open-incidents board (org-scoped),
    incident detail with the real timeline + ack/resolve/assign/note controls,
    schedules page, escalation-policies page, routing-rules page, postmortem
    view/edit. All `{% extends "base.html" %}`, dark design system classes only.
11. **Event feed integration.** Human actions emit `core.models.Event.log(...)`
    with appropriate verbs/icons (`incident`, `alert`, `fix`, `check`) so the
    activity feed narrates the human side too.
12. **Migrations** for `oncall` and the additive `observability` org field
    (`makemigrations` only — never run `migrate`).

### Scope OUT (explicitly not this sprint)

- Real external paging (SMS / phone / push / email / Slack). "Paging" =
  selecting the on-call user + recording a timeline `paged` entry + an Event.
  (Push/email integrations are deferred; `PushNotification` MCP is out of scope.)
- Calendar-grade schedules (overrides, layers, gaps, sub-day shifts, holidays).
  MVP = simple weekly round-robin rotation by member order.
- A background scheduler/cron daemon for escalation. We expose an idempotent
  tick endpoint instead of standing up Celery/Temporal timers this sprint.
- Editing/altering the autonomous remediation pipeline's control flow. We only
  *observe* it via additive timeline hooks.
- Renaming, removing, or changing the type of any existing
  `observability.Incident` field, or modifying `accounts/models.py`.
- SLA/MTTA/MTTR analytics dashboards, incident merging/duplicates UI,
  multi-responder chat, status pages.

---

## 4. Integration & safety notes (for the builder)

- **Never edit** `accounts/models.py`, `helm/urls.py`, `helm/settings.py`,
  `templates/base.html`, or other apps' files **except** the single allowed
  additive change: adding a nullable `org` FK to `observability.Incident` by
  making it subclass `OrgScopedModel` and best-effort populating it. The
  integrator wires `path("oncall/", include("oncall.urls"))` into root urls.
- **Loop safety pattern:** all hooks into `observability.services` /
  `orchestration.service` must be additive and wrapped so a failure is swallowed
  (`try/except Exception: pass`, log to stdout). Importing `oncall` from those
  modules must be lazy (inside the function) so a broken/missing `oncall` never
  prevents an incident from opening or being remediated.
- **Org may be None.** The loop runs without a request (`request.org` absent).
  Services must accept `org=None` and degrade: timeline/routing still record
  what they can; no exception is raised on missing org.
- Use `Model.objects.for_org(request.org)` / `accounts.scoping.scoped(...)` in
  every request view; never return cross-org rows.
- Match `static/css/helm.css` (cards, badges, btn, list-row, grid-*, feed) and
  the existing dark incident UI in `observability/templates/observability/`.

---

## 5. Machine-checkable rubric (pass/fail)

Each item is objectively verifiable by reading files, running `manage.py check`,
running tests, or hitting a URL. "the app" = the Hull Django project from repo
root with `source .venv/bin/activate`.

1. **App exists & installed.** `oncall/` is a Django app with `apps.py`,
   `models.py`, `views.py`, `urls.py` (with `app_name = "oncall"`), `services.py`,
   and a `migrations/` package; and `oncall` (or `oncall.apps.*Config`) is in
   `INSTALLED_APPS` (verify via `django.apps.apps.is_installed("oncall")`).
2. **`manage.py check` passes** with `oncall` installed (exit code 0).
3. **Migrations exist and are current.** `python manage.py makemigrations
   --check --dry-run oncall observability` reports no missing migrations (exit 0)
   after the builder has generated them.
4. **Org-scoped models.** Every concrete model in `oncall.models`
   (`Schedule`, `ScheduleMember`, `EscalationPolicy`, `EscalationStep`,
   `RoutingRule`, `TimelineEntry`, `Postmortem`, `ActionItem`) is a subclass of
   `accounts.models.OrgScopedModel` (verify via `issubclass`), so each has an
   `org` field and `objects` is an `OrgManager`/`OrgScopedQuerySet`.
5. **Incident gains nullable org.** `observability.models.Incident` has a field
   named `org` that is a `ForeignKey` to `accounts.Org` with `null=True`
   (verify via `Incident._meta.get_field("org").null is True` and it points to
   `accounts.Org`). No existing Incident field was removed/renamed (the fields
   listed in CONTRACTS.md §Data model still exist).
6. **Loop still resolves with oncall present (CROWN JEWEL).** With
   `HELM_AUTO_REMEDIATE=1`, calling
   `observability.services.open_or_update_incident(...)` (or the orchestration
   remediate path) on a project with a planted-bug deployment drives an incident
   to `status == "resolved"` with a non-null `remediation_pr` (same behavior as
   before oncall existed). The existing observability/orchestration loop tests
   still pass.
7. **Loop survives oncall failure (FALLBACK).** Monkeypatching/forcing the
   `oncall` timeline/routing hook to raise inside
   `open_or_update_incident` / the remediate pipeline does NOT prevent the
   incident from being created or from reaching `resolved`. (Test: patch
   `oncall.services.timeline.record` to raise; the loop test still goes green.)
8. **Org=None safe.** `oncall.services.timeline.record(incident, "note", "x")`
   and `oncall.services.routing.route(incident)` run without raising when the
   incident's `org` is `None` (request-less path).
9. **Schedule rotation.** `Schedule.current_oncall(at=...)` returns the
   correct rotating member for a schedule with ≥2 ordered members across two
   different weeks (deterministic by ISO week index modulo member count), and
   returns `None` for an empty schedule.
10. **Escalation ordering.** `oncall.services.escalation.next_step(policy, m)`
    returns the highest-order step whose `after_minutes <= m` (or the first step
    for `m=0`), and is monotonic as `m` increases. Steps are stored ordered.
11. **Routing selection.** `oncall.services.routing.route(incident)` returns the
    first `RoutingRule` (by priority/order) in the incident's org whose
    `min_severity` and optional project filter match, and `None` when no rule
    matches; it never returns a rule from a different org.
12. **Timeline is first-class & ordered.** Opening an incident creates a
    `TimelineEntry` with kind `opened`; `TimelineEntry` rows for an incident are
    retrievable in chronological order; the helper
    `oncall.services.timeline.record(...)` persists a row with the given kind &
    message.
13. **Human ack action.** POST to `/oncall/incidents/<pk>/ack/` while logged in
    as a member of the incident's org sets the underlying
    `observability.Incident.status` to `acknowledged`, sets `acknowledged_at`,
    and records an `acknowledged` `TimelineEntry` attributed to the user.
14. **Human resolve action.** POST to `/oncall/incidents/<pk>/resolve/` sets
    `status="resolved"`, sets `resolved_at`, and records a `resolved`
    `TimelineEntry`.
15. **Note & assign actions.** POST to `/oncall/incidents/<pk>/note/` records a
    `note` entry with the submitted text; POST to
    `/oncall/incidents/<pk>/assign/` records an `assigned` entry referencing the
    chosen user.
16. **Tick escalation.** POST to `/oncall/incidents/<pk>/tick/` on an unacked
    incident whose routed policy's current step `after_minutes` has elapsed
    records an `escalated` `TimelineEntry`; calling tick again before the next
    threshold does NOT add a duplicate `escalated` entry for the same step
    (idempotent).
17. **Postmortem.** A `Postmortem` can be created for a resolved incident via
    `/oncall/incidents/<pk>/postmortem/` (OneToOne to the incident), supports
    ordered `ActionItem`s, and a sev1/sev2 incident reaching `resolved` results
    in a stub postmortem existing (auto-created, best-effort).
18. **Tenant isolation in views.** A logged-in member of org A requesting
    `/oncall/` (incident board), a schedule, policy, routing rule, or incident
    detail belonging to org B receives no org-B data (404/redirect or empty
    list); request views use `request.org` scoping. (Test with two orgs.)
19. **Auth required.** `/oncall/` and all `oncall` action endpoints redirect
    anonymous users to login (use `org_required`/`login_required`).
20. **Design system & base template.** Every `oncall` template begins with
    `{% extends "base.html" %}`, uses helm.css classes (`card`, `badge*`,
    `btn*`, `list-row`, `grid-*`, `feed`), defines no inline `<style>` blocks of
    its own beyond design-token usage, and does not modify `base.html`.
21. **Event feed narration.** A human ack and a human resolve each emit a
    `core.models.Event` (verify a new `Event` row with a matching verb/icon is
    created), so the activity feed reflects human incident actions.
22. **Tests present & green.** `oncall/tests.py` exists and
    `python manage.py test oncall` passes (exit 0), covering at minimum:
    rotation (item 9), escalation ordering (10), routing (11), timeline record
    (12), ack+resolve (13–14), tick idempotency (16), tenant isolation (18),
    and the loop-survives-oncall-failure fallback (7).

---

## 6. Out-of-band assumptions

- Integrator adds `path("oncall/", include("oncall.urls"))` to `helm/urls.py`
  and runs `migrate`. Builder runs only `makemigrations oncall observability`.
- Builder does not bind port 8000; smoke-test on 8011+ and kill after.
