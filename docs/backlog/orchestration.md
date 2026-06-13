# Orchestration — build backlog

Section owner: orchestration/ (the durable, observable workflow engine + the
agent-org/workflow UI). PM-maintained checklist of build tickets toward the
ROADMAP vision (esp. §8 "Agents & Orchestration": the agent org surfaced
in-product — PM/builder/QA agents, sprint/workflow runs, live agent output —
plus Sprint-3 demo hardening) and the non-negotiable crown jewel: the
autonomous **incident → fix → PR → CI → merge → redeploy → resolved** loop.

HARD RULES (carried into every ticket):
- Never break the request-less autonomous loop. `service._run` stays the single
  WorkflowRun chokepoint; the 6 entry points (`import_project`, `deploy`,
  `run_feature_agent`, `run_ci`, `remediate`, `is_remediating`) keep stable
  signatures with **no new required args**. `org` stays nullable.
- Additive only, with fallbacks. All cross-app reads via ORM/services wrapped in
  try/except; a missing/renamed dependency degrades, never 500s.
- Request paths: `@org_required` + `for_org(request.org)`/`scoped(...)`. Tenant
  isolation is absolute (no cross-org links/output).
- Templates `{% extends "base.html" %}` + `static/css/helm.css` classes only; no
  external CSS/JS. Do NOT edit `helm/urls.py`, `helm/settings.py`,
  `templates/base.html`, `accounts/models.py`, or other apps' files.
- Do NOT migrate/makemigrations-apply or git commit (integrator owns those). Any
  truly required field must be nullable + additive + migration generated only.

Legend: `[x]` done (reconciled against current code), `[ ]` open.
(Folds in the Sprint-3 stub's ORCH-1/ORCH-2 as ORCHESTRATION-19/20.)

---

## A. Crown-jewel loop + durable engine (foundation — keep green)

- [x] ORCHESTRATION-1: Single dispatch chokepoint `_run` — Create one
  WorkflowRun per top-level call (import/deploy/agent/ci/remediate), run work on
  a daemon thread, record DONE/FAILED + a core.Event, return fast. (acceptance:
  `s._run('t', lambda:'ok')` returns a RUNNING WorkflowRun that reaches a
  terminal state) (done: service.py `_run`/`_body`, lines 40-198; tests.py
  `test_run_creates_and_completes_workflow`/`test_run_records_failure`)
- [x] ORCHESTRATION-2: The STAR — autonomous remediate pipeline — ack → worktree
  off prod branch → strict remediation prompt → run agent inline → CI → on green
  merge + redeploy → incident RESOLVED, each step emitting Events. (acceptance:
  happy-path test drives incident to RESOLVED with a remediation PR) (done:
  service.py `remediate`/`_remediate_pipeline`, lines 461-671; tests.py
  `test_happy_path_resolves_incident`)
- [x] ORCHESTRATION-3: Remediation re-entrancy guard — a per-incident lock so
  two concurrent triggers can't double-remediate. (acceptance: second
  `remediate(id)` while one runs returns None) (done:
  `_REMEDIATING_INCIDENTS`/`_REMEDIATE_LOCK` + `is_remediating`, lines 452-494)
- [x] ORCHESTRATION-4: CI runner — locate the PR worktree (app_subdir aware),
  pick django-test vs pytest, run with a clean child env (Hull's
  DJANGO_SETTINGS/venv stripped), set PR.ci_status, log events. (acceptance:
  `_run_ci_inline` returns pass/fail and stamps PR.ci_status) (done: service.py
  `run_ci`/`_run_ci_inline`/`_ci_command`/`_clean_subprocess_env`, lines 294-446)
- [x] ORCHESTRATION-5: SQLite write-lock resilience — background WorkflowRun
  saves retry with capped backoff+jitter so a successful run is never
  mis-recorded as stuck/FAILED under daemon-thread contention. (acceptance:
  full suite green with many concurrent runs) (done: `_save_wf`, lines 88-111)
- [x] ORCHESTRATION-6: Org stamping on every run (additive, fallback-safe) —
  resolve org from project else `get_current_org()` else None; request-less runs
  record org=None and never raise. (acceptance: request-less `_run` -> org is
  None) (done: `_run` org block, lines 59-69; models WorkflowRun.org nullable)
- [x] ORCHESTRATION-7: Loop bridges to Issues + on-call timeline (additive, never
  raises) — remediation files/updates the linked Ticket and mirrors each step
  into the oncall timeline + auto-stub postmortem, all wrapped so any failure
  leaves the loop unchanged. (done: `_issue_hook`/`ev` + oncall hooks in
  `_remediate_pipeline`, lines 508-671)

## B. Temporal durability (durable execution; threaded fallback)

- [x] ORCHESTRATION-8: Temporal-or-thread dispatch — when HELM_USE_TEMPORAL=1 and
  the server is reachable, start the workflow on the cluster and await; else fall
  back to the thread body. Never block the product on Temporal. (acceptance:
  `_temporal_available()` gates dispatch; failure falls back to `_body`) (done:
  `_temporal_available`/`_temporal_body`, lines 24-37, 150-198)
- [x] ORCHESTRATION-9: Workflow/activity definitions for deploy/ci/remediate/agent
  wrapping the SAME inline service logic; module stays importable without
  temporalio installed. (acceptance: WORKFLOWS/ACTIVITIES export; stub shim when
  temporalio missing) (done: temporal_workflows.py)
- [x] ORCHESTRATION-10: Worker management command — `manage.py run_worker` serves
  the queue; errors cleanly if temporalio absent. (done:
  management/commands/run_worker.py)
- [x] ORCHESTRATION-11: Temporal Cloud client — API-key + TLS via settings,
  shared by worker and dispatcher; human-readable connection label, no secrets.
  (done: temporal_client.py `connect`/`connection_label`)
- [x] ORCHESTRATION-12: Wire `remediate()` to Temporal dispatch — `remediate`
  currently never passes a `temporal=` tuple, so the STAR loop never runs on the
  cluster (deploy/ci/agent already do). Add `temporal=("RemediateWorkflow",
  [incident_id])` so the crown-jewel loop is durable + visible in Temporal
  Cloud when enabled, with the existing thread fallback unchanged. (acceptance:
  with HELM_USE_TEMPORAL=1 + reachable server a remediation appears in Temporal;
  with it off/unreachable the threaded loop still drives an incident to RESOLVED
  — `python manage.py test orchestration` stays green) (done: service.py
  `remediate` now passes `temporal=("RemediateWorkflow",[incident_id])`; added
  `_run(on_done=...)` callback fired on BOTH threaded + Temporal-success paths so
  the per-incident re-entrancy lock is released even when the durable path runs
  `_remediate_pipeline` in a remote worker (no lock leak); 8/8 orchestration
  tests green)

## C. Per-tenant legibility of a single run (Sprint-2 PRD — SHIPPED)

- [x] ORCHESTRATION-13: Org-scoped, fallback-safe ref resolver — map
  `(ref_type, ref_id)` → Link(object/url/label/kind) for incident/PR/agent_run/
  environment, project fallback; unknown/missing/cross-org → None, never raises.
  (acceptance: PRD R1–R4) (done: refs.py `resolve` + `_resolve_*`; WorkflowRun
  `linked*`/`kind`)
- [x] ORCHESTRATION-14: Workflow detail = step timeline + linked-entity panel —
  real `<a>` + kind badge with plain-text fallback; `detail` parsed into
  feed-class timeline tolerant of empty. (acceptance: PRD R5–R6) (done:
  views `_parse_steps`/`_detail_context`/`workflow_detail`; templates
  workflow_detail.html + _workflow_detail_panel.html)
- [x] ORCHESTRATION-15: Inline live agent output on detail — org-scoped
  most-recent/running AgentRun tail via `for_org`, omitted + safe when none.
  (acceptance: PRD R7) (done: views `_inline_agent`)
- [x] ORCHESTRATION-16: Run list/table filters by kind + status (server-side,
  HTMX, org-scoped) — applied AFTER for_org; no-match -> `.empty`; fragment
  honors same params. (acceptance: PRD R8–R9) (done: views `_apply_filters`;
  workflow_list.html + _workflow_table.html)
- [x] ORCHESTRATION-17: Cross-link table + activity rows to entities — `→ label`
  affordance for resolvable refs; rows without a ref keep working. (acceptance:
  PRD R10) (done: views `_decorate`; _workflow_table.html, _activity_panel.html)
- [x] ORCHESTRATION-18: Live activity surface + all request paths org-scoped —
  running workflows + running AgentRuns, HTMX-polled; every view `@org_required`,
  queries via `for_org`/`scoped`; cross-org pk -> 404; no-org -> 302.
  (acceptance: PRD R13) (done: views `activity`/`activity_panel`/
  `_activity_context`; activity.html + _activity_panel.html; tests_smoke.py)

## D. Sprint-3: the agent org surfaced in-product (ROADMAP §8) — OPEN

- [x] ORCHESTRATION-19: Agent-org dashboard (`/orchestration/agents/`) — a live,
  org-scoped view of the autonomous crew: ALL recent + running AgentRuns with
  kind, title, status, cost_usd, num_turns, project, last action; running ones
  pulse; swarm summary tiles (running/queued/done counts + total cost_usd).
  HTMX-polled (~2s). Surfaces "what is the swarm doing right now" for the demo.
  (folds Sprint-3 stub ORCH-1 + ORCH-2.) (acceptance: new `@org_required` view +
  template extends base.html, lists multiple AgentRuns for request.org only with
  correct tile counts, auto-refreshes, returns 200; a nav affordance links to it)
  (done: views `agents_dashboard`/`agents_panel`/`_agents_context` (AgentRun via
  `for_org`, tiles from org-wide counts + summed cost_usd, running-first then
  recent); templates agents.html + _agents_panel.html (extends base.html, stat
  tiles, running rows pulse via dot-live, HTMX every-2s); urls `agents/` +
  `agents/panel/`; nav affordance "Agent org →" added to workflow_list.html)
- [x] ORCHESTRATION-20: Loop-health / crown-jewel widget — an org-scoped panel on
  the orchestration index showing autonomous-loop KPIs: incidents auto-resolved,
  mean time-to-resolve (acknowledged→resolved), remediation success rate
  (resolved vs CI-failed/no-PR), and count currently remediating
  (`is_remediating`). Tells the money-shot story at a glance. (acceptance: panel
  computes the four metrics from org-scoped Incident/WorkflowRun data, degrades
  to zeros if a table is missing, returns 200) (done: views `_loop_health`
  (org-scoped `Incident.objects.filter(org=...)`: auto_resolved, MTTR over
  acknowledged→resolved, success_rate=resolved/acknowledged-attempts,
  remediating_now from REMEDIATING status ∪ `service.is_remediating`) wrapped to
  degrade to zeros/"—"; "Autonomous loop health" grid-4 panel on
  workflow_list.html)
- [x] ORCHESTRATION-21: Manual remediation trigger from orchestration (HTMX POST)
  — an org-scoped, CSRF-protected affordance that calls
  `service.remediate(incident_id)` for an incident in `request.org`, honoring the
  re-entrancy guard, then redirects to the new run. Lets the demo driver kick the
  loop from the orchestration surface. (acceptance: POST by an org member for an
  in-org firing incident returns 302 to the WorkflowRun and a remediation starts;
  cross-org incident -> 404; double-click -> single run via `is_remediating`)
  (done: view `remediate_incident` (`@org_required` + `@require_POST`;
  `Incident.objects.filter(org=request.org)` → cross-org 404; calls
  `service.remediate`, 302→workflow_detail of the new run; when guard returns
  None redirects to the existing in-org run for that incident so a double-click
  yields a single remediation); url `remediate/<int:incident_id>/`; CSRF-token
  "⚡ Remediate now" form on workflow_detail.html for firing/acknowledged
  incident-linked runs)
- [x] ORCHESTRATION-22: Workflow detail polling stops on terminal state — the
  detail/agent panel should stop HTMX polling once status is done/failed (swap to
  a static render) to cut needless requests during a long demo. (acceptance:
  terminal-state detail panel emits no `hx-trigger="every"`; running state does)
  (done: moved the polling wrapper INTO `_workflow_detail_panel.html` (id
  `wf-detail-panel`, `hx-swap="outerHTML"` self-replace) so the `hx-trigger` is
  emitted only while `run.status == 'running'`; on a terminal render the swapped
  markup carries no trigger and HTMX stops; workflow_detail.html just includes
  the fragment)
- [x] ORCHESTRATION-23: Sprint/batch run grouping — when a sprint kicks off many
  feature agents, group their WorkflowRuns under a parent "sprint" label so the
  UI shows one collapsible batch instead of N flat rows (derive grouping from
  name/ref, no schema change preferred). (acceptance: runs sharing a sprint tag
  render under one group header in the list; ungrouped runs unaffected) (done:
  views `_sprint_tag` (regex `[sprint:tag]`/`[batch:tag]` on run.name, no schema
  change) + `_group_runs` (collapses tagged runs under a header dict with
  per-status counts at the batch's first-run position; ungrouped stay flat);
  passed as `groups` from workflow_list + workflow_table; templates rewired —
  `_workflow_table.html` renders headers + child rows via new shared
  `_workflow_row.html`, falling back to flat `runs` when no groups)

## E. Hardening & polish — OPEN

- [ ] ORCHESTRATION-24: Stuck-run reaper — a best-effort sweep that marks
  WorkflowRuns RUNNING beyond a generous timeout as FAILED with a clear detail,
  so a crashed worker/thread doesn't leave the UI showing a phantom "running"
  forever. Idempotent, org-agnostic, never touches a genuinely-live run.
  (acceptance: a RUNNING run older than the threshold with no live thread is
  reaped to FAILED on next sweep; fresh/running ones untouched)
- [ ] ORCHESTRATION-25: Per-run structured timeline from Events (optional, only
  if §D needs it) — instead of re-parsing `detail` text, build the timeline from
  existing core.Event rows (project/actor/url) scoped to the run's window, so it
  is robust to format drift; fall back to `_parse_steps` when none. Prefer no new
  schema. (acceptance: detail timeline can be built from Event rows for the run's
  project/window with no new required schema; empty -> falls back gracefully)
- [ ] ORCHESTRATION-26: Expand orchestration UI-contract test coverage — assert
  org isolation of detail/inline-agent (org A never sees org B output), filter
  correctness (`?kind=incident`/`?status=failed`), and ref-resolution fallback
  (bogus ref -> 200 plain text). (acceptance: new tests pass;
  `python manage.py test orchestration` stays green)
- [ ] ORCHESTRATION-27: Demo-mode seeding hook — an idempotent management command
  / service helper that fabricates a realistic finished remediation WorkflowRun
  (multi-step detail + linked incident/PR) for an org, so the UI has narrative
  content during a cold-start demo without firing a real incident. (acceptance:
  command creates org-scoped sample runs; re-running doesn't duplicate; loop code
  untouched)
