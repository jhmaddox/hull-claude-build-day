# issues backlog — Issues (Jira) section (`issues/` app)

PM-owned build backlog toward the ROADMAP "Issues (Jira)" bar and the PRD refresh
(`docs/prd/issues.md`). Crown jewel: the autonomous incident→fix loop must mint and
drive a ticket — additive + best-effort, never breaking the loop.

Reconciled 2026-06-13 against current code. Foundation + the entire Sprint-1
refresh (T1–T7) are shipped and green: `manage.py check` clean, 27 issues tests
pass, `makemigrations issues --check` reports no changes.

## Done (reconciled — do not rebuild)

- [x] ISSUES-1: Foundation — models/services/views/board/backlog/detail/sprints —
  Board/Sprint/Label/Ticket/Comment/Activity subclass OrgScopedModel (nullable org);
  services `file_ticket`/`pick_ticket`/`link_ticket`/`set_status`/`add_comment`/
  `log_activity`/`next_ticket_key`/`get_or_create_default_board`. (acceptance:
  models org-scoped + nullable org; core services request-free) (done: issues/models.py,
  issues/services.py; tests test_file_ticket_no_org_returns_ticket_org_none, R13/R15)
- [x] ISSUES-2 (T1 CROWN JEWEL): `ticket_for_incident(incident, *, status, pull_request,
  agent_run, org)` — idempotent one-ticket-per-incident, loop-safe (swallows all
  exceptions → None). (acceptance: 2 calls → exactly 1 ticket; forced failure → None,
  no propagation) (done: issues/services.py:277; tests test_idempotent_single_ticket,
  test_loop_safe_returns_none_on_failure, test_bad_incident_returns_none)
- [x] ISSUES-3 (T1): Wire loop into backlog at 3 narration points — incident detected
  (status=todo), agent/PR (in_progress + links), resolved (done) — each try/except
  wrapped via `_issue_hook`. (acceptance: every issues call inside try/except; loop
  resolves with Issues raising) (done: orchestration/service.py:508,552,618,663; tests
  test_issue_hook_failure_does_not_change_resolution, test_orchestration_imports_issues_hook,
  test_status_and_link_progression)
- [x] ISSUES-4 (T2): Backlog filtering — GET status/type/priority/assignee/label/q,
  org-scoped, filter bar round-trips. (acceptance: ?status=done → only org done tickets;
  selected values preserved) (done: issues/views.py:62, backlog.html; tests
  test_filter_by_status_scoped, test_filter_by_type_and_q, test_filter_bar_round_trips)
- [x] ISSUES-5 (T3): Board + sprint write actions — board_new, sprint_new,
  sprint_action (start/complete), ticket_sprint (add/remove + Activity). (acceptance:
  board/sprint created scoped; status transitions; add-to-sprint logs Activity) (done:
  issues/views.py:346,390,414,433; tests test_board_new_creates_scoped_board,
  test_sprint_new_start_complete, test_add_ticket_to_sprint_logs_activity)
- [x] ISSUES-6 (T4): Labels UI — label_new + ticket_labels attach/detach, chips render.
  (acceptance: label created scoped, attached to ticket, chip renders) (done:
  issues/views.py:466,480; test test_label_new_and_attach)
- [x] ISSUES-7 (T5): Agent-backlog view `/issues/agents/` — agent-filed tickets newest
  first with incident/PR/agent-run cross-links, org-scoped. (acceptance: 200, lists
  agent ticket of org, omits other org) (done: issues/views.py:500, agent_backlog.html;
  test test_agent_backlog_lists_agent_ticket_only)
- [x] ISSUES-8 (T6): Cross-link rendering hardening — `_safe_url`/`_agent_run_url`/
  `_ticket_links` guard every reverse so a missing one never 500s; ticket.html renders
  incident/PR/agent-run links. (acceptance: ticket detail renders guarded cross-links)
  (done: issues/views.py:147-176, ticket.html)
- [x] ISSUES-9 (T7): Tests + migrations + check — 27 tests pass, `check` clean,
  `makemigrations issues --check` reports no changes; all templates extend base.html +
  use helm.css. (done: issues/tests.py; verified 2026-06-13)

## Open (next increments — beyond the shipped MVP)

- [x] ISSUES-10: "Work this ticket" action on ticket detail — button creates a worktree
  + `agents.services.launch_agent(project, kind="feature", title=ticket.title,
  prompt=title+description, dispatch=True)`, sets status in_progress, links the AgentRun
  to the ticket. Best-effort + org-scoped; degrade gracefully if project/agents missing.
  (acceptance: clicking "Work this ticket" creates an AgentRun linked to the ticket and
  flips status to in_progress; no 500 when the ticket has no project) (done: views.ticket_work
  + _ticket_project resolve board.project or sole org project; pick_ticket→in_progress +
  link_ticket(agent_run); whole body try/except → flash, no 500; URL issues:ticket_work;
  "Work this ticket" button in ticket.html actions)
- [x] ISSUES-11: Auto-advance ticket on linked-PR merge — when a ticket's `pull_request`
  merges, move the ticket to done and log Activity; surface PR `ci_status` live on ticket
  detail. Hook additively off the existing vcs merge path (best-effort, never blocks merge).
  (acceptance: merging a ticket's linked PR moves the ticket to done; ticket detail shows
  the PR ci_status badge) (done: services.advance_tickets_for_merged_pr(pr) — idempotent,
  loop-safe, finds tickets by pull_request FK → set_status DONE + Activity, never raises;
  ticket.html Links card now renders the PR ci_status badge. WIRING: integrator adds one
  fail-soft call in vcs.services.merge_pull_request after merge succeeds — see wiring_notes)
  REOPENED (QA 2026-06-13): the ci_status-badge half is verified good, but the auto-advance
  acceptance does NOT hold end-to-end. `advance_tickets_for_merged_pr` has ZERO call sites —
  it is verified correct + idempotent + never-raises in isolation, but nothing invokes it.
  The real merge entry points (`vcs.services.merge_pull_request`, and the manual-merge view
  `vcs.views.pr_merge` at vcs/views.py:217) never call it and no post_save signal does, so
  merging a ticket's linked PR through the UI leaves the ticket un-advanced. (The autonomous
  loop's own incident ticket is moved to done via orchestration `_issue_hook(status="done")`,
  a separate path — so the crown-jewel loop is unaffected.) FIX HINT: the integrator must add
  the documented fail-soft call after merge succeeds (e.g. in vcs.views.pr_merge after `ok`,
  or in vcs.services.merge_pull_request before `return True`):
  `try: from issues.services import advance_tickets_for_merged_pr; advance_tickets_for_merged_pr(pr)
  except Exception: pass`. Until a caller exists, the acceptance is unmet.
  RESOLVED (rework round 2, 2026-06-13): added the missing CALL SITE entirely from within the
  issues app — no cross-app edit needed. New issues/signals.py registers a guarded post_save
  receiver on vcs.PullRequest (IssuesConfig.ready() → signals.connect(), dispatch_uid
  "issues_advance_tickets_on_pr_merge"); when a PR is saved with status=="merged" it calls
  advance_tickets_for_merged_pr(instance). BOTH real merge paths
  (vcs.services.merge_pull_request and the manual-merge view vcs.views.pr_merge) finish by
  calling pr.save(...) with status=merged, so the ticket now flips to Done + logs Activity
  end-to-end through the UI. Fail-soft: connect() and the handler swallow everything; the
  service still guards status!='merged' and the already-Done case (idempotent). Verified:
  3 new tests (AutoAdvanceOnMergeTests: advances on merge, no-op while open, idempotent on
  re-save) → 30 issues tests pass, manage.py check clean, signal confirmed connected at
  runtime. Integrator no longer needs to touch vcs (the documented vcs-side call would still
  be redundant-safe but is unnecessary).
- [x] ISSUES-12: HTMX inline status on board cards — drag-free move via a per-card status
  select that POSTs to `set_status` and swaps the card in place (reuse `_status_control`).
  (acceptance: changing a card's status on the board updates without full page reload;
  org-scoped; activity logged) (done: views.card_status reuses services.set_status (Activity
  logged) and returns the new _board_card.html fragment; _board_card.html wraps _ticket_card
  with an id'd container + HTMX status <select> (hx-swap outerHTML); board.html includes
  _board_card; URL issues:card_status)
- [x] ISSUES-13: Backlog saved-filter URLs + count chips — show per-status counts as
  filter chips that deep-link the backlog filter; "clear filters" resets. (acceptance:
  clicking a status chip applies ?status=<s> and the count matches the rendered rows)
  (done: backlog view annotates org-scoped per-status Count → status_chips + total_count;
  backlog.html renders chips linking to ?status=<s> ("All" clears, active chip highlighted))
- [x] ISSUES-14: Ticket ↔ commit links — render commits referencing a ticket key
  (HULL-<n>) from linked PR diffs/agent runs on ticket detail. (acceptance: a ticket whose
  PR mentions its key lists that PR/commit as a cross-link) (done: views._ticket_mentions
  scans org-scoped vcs.PullRequest (title/description/diff) and agents.AgentRun
  (title/prompt/output) for ticket.key, excluding the directly-linked PR/run; ticket.html
  "Mentions <key>" card renders guarded cross-links; missing app/reverse never 500s)
- [x] ISSUES-15: Sprint burndown summary on sprint detail — done/total + a simple progress
  bar per sprint and on the sprints list (reuse existing done/total counts). (acceptance:
  sprint detail and sprints list each render a progress bar reflecting done/total) (done:
  sprint_detail.html adds a burndown progress bar (width = done|pct:total); sprints.html
  adds a per-row progress bar; reuses existing done/total + the pct filter, no view change)
