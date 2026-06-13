# PRD — Pull Requests (multitenant + UX) · Sprint 2

Section owner: PM for `vcs/`
Sprint: 2 (Operations / human-in-the-loop build-out)
Status: Ready for builder
Owns: `vcs/` only.

> Sprint 1 shipped and is green: `PullRequest` is org-scoped, the review surface
> has per-file diff, live CI polling, mergeability gating, conflict detection, and
> a copy-permalink control (see git history + `vcs/tests.py`). **Do not regress
> any of it.** This document is the Sprint-2 increment layered on top.

## Problem

Pull Requests in Hull can today only be **born from the autonomous loop**:
`vcs.services.open_pull_request(worktree, ...)` is called by `agents/services.py`
after a Claude agent finishes work. There is no way for a **human org member** to
participate in the PR workflow beyond merging:

1. **No manual PR creation.** A member who pushed a branch (or wants to propose a
   change between two existing branches) cannot open a PR from the UI. Every PR
   requires an `agents.Worktree`, which only the agent crew produces. This blocks
   the "real teams operate the stack from one place" roadmap bar.
2. **No close / reopen.** The model has a `CLOSED` status but nothing in the UI or
   services can reach it. A PR that should be abandoned stays `OPEN` forever; the
   list never clears.
3. **No human review trail.** Everything is `author="claude-agent"`, and merge /
   close record *what* happened but not *who* did it. There is no place to leave a
   review note, so the human decision context is lost.
4. **List has no triage affordances.** No status filter and no call-to-action to
   open a PR — discoverability of the new manual flow is zero without it.

All of this must land **without touching the autonomous incident → fix → PR → CI →
merge loop**, which still opens and merges PRs with no request and `org=None`.

## Goals

- A human org member can open a PR from the UI by choosing a project (org-scoped)
  and a head + base branch, with the diff computed from real git.
- A member can **close** an open PR and **reopen** a closed one, with the action
  attributed to them.
- A member can leave **review comments** on a PR; merge/close capture the acting
  user so the decision trail is auditable.
- The list lets a member **filter by status** and has a visible **New PR** CTA.
- The autonomous loop is byte-for-byte behaviorally unchanged and all Sprint-1
  rubric items still pass.

## Non-goals (scope-out, this sprint)

- Approvals / required-reviewer / branch-protection / CODEOWNERS workflows.
- Inline (per-line) diff comments or threaded replies — comments are PR-level only.
- Real GitHub/GitLab sync, webhooks, or pushing branches to a remote.
- Editing an existing PR's title/description/branches after creation.
- Creating branches from the UI (you can only open a PR between branches that
  already exist in the repo).
- Cross-org PR transfer; deleting PRs.

## User stories

- As an **org member**, I click "New PR", pick one of my org's projects and a head
  and base branch, and Hull opens a real PR with the computed diff — scoped to my
  org and attributed to me.
- As a **reviewer**, I close an open PR I've decided against, and later reopen it if
  I change my mind; the activity feed records who did it.
- As a **reviewer**, I leave a comment on a PR explaining my decision, and see the
  thread of comments (agent + human) in chronological order on the detail page.
- As a **reviewer**, when I merge or close a PR while logged in, the PR records that
  *I* performed the action (not the generic agent author).
- As a **member triaging**, I filter the PR list to `open` / `merged` / `closed` and
  see only those, and I can always reach the New PR form from the list.
- As the **autonomous loop**, I open and merge PRs with no request, no acting user,
  and `org=None`, exactly as before — nothing I rely on changed.

## Current state → target

| Capability | Current (Sprint 1) | Target (Sprint 2) |
|---|---|---|
| PR creation | agent loop only (`open_pull_request(worktree,…)`) | + manual `open_manual_pull_request(project, head, base, …)` via `/vcs/pr/new/` |
| Branch discovery | n/a (worktree carries branch) | `list_branches(project)` git helper feeds the New-PR form |
| Status transitions | OPEN → MERGED | + OPEN ⇄ CLOSED (close / reopen) |
| Actor attribution | `author="claude-agent"`; merge/close anonymous | manual PR `author` = user; `merged_by` / `closed_by` recorded |
| Review notes | none | `PullRequestComment` (org-scoped), shown + addable on detail |
| List triage | flat open / other | status filter (`?status=`) + "New PR" CTA |
| Org scoping | enforced (Sprint 1) | preserved on every new view/action (404 cross-org) |
| Autonomous loop | works `org=None` | unchanged |

## Scope-in (MVP for this sprint)

### A. Manual PR creation
- New service `open_manual_pull_request(project, *, title, head_branch,
  base_branch=None, description="", author="", org=None)` in `vcs/services.py`.
  It reuses the existing `_compute_diff(repo, base, head)` and
  `next_pr_number(project)`, sets `worktree=None`, and persists `org` from the
  passed `org` (defaulting to `getattr(project, "org", None)`). Returns the PR,
  or `None` if there is no diff (same contract as `open_pull_request`). Emits the
  same `Event` (`icon="pr"`).
- Existing `open_pull_request(worktree, …)` keeps its exact signature/behavior
  (loop unaffected). The new function is **additive** and may share private
  helpers but must not change the old one's params.
- New git helper `list_branches(project)` in `vcs/services.py` returns the repo's
  local branch names (best-effort; returns `[]` on any git error / missing
  `local_path` — never raises).
- New view `pr_new(request)` at `vcs:pr_new` (`/vcs/pr/new/`), `@org_required`:
  - GET renders a form listing the current org's projects (scoped via
    `accounts.scoping`) and, for a chosen/first project, its branches.
  - POST validates project ∈ org, calls `open_manual_pull_request(project,
    title=…, head_branch=…, base_branch=…, description=…,
    author=request.user.get_username(), org=request.org)`, then redirects to the
    new PR's detail (or re-renders with an error message if no diff / invalid).
  - A project not in `request.org` → 404 / form error (never opens a PR for
    another tenant).

### B. Close / reopen
- New services `close_pull_request(pr, *, actor="")` and
  `reopen_pull_request(pr, *, actor="")` in `vcs/services.py`. Close: only from
  `OPEN`; sets `status=CLOSED`, `closed_at`, `closed_by`; emits an `Event`
  (`icon="pr"`, level warning). Reopen: only from `CLOSED`; back to `OPEN`,
  clears `closed_at`. Both are idempotent-safe (no-op + return False if the
  transition is invalid) and never raise.
- New views `pr_close` / `pr_reopen` (`@org_required`, org-scoped queryset, POST,
  CSRF), wired in `vcs/urls.py`, attributing the acting user.
- Detail page shows a **Close** button on open PRs and a **Reopen** button on
  closed PRs (design-system `.btn`).

### C. Lightweight human review trail
- New model `PullRequestComment(OrgScopedModel)`: `pull_request` FK
  (`related_name="comments"`), `author` (char), `body` (text),
  `created_at`. Org nullable (loop safety), inherits `OrgManager`. Additive
  migration only.
- New fields on `PullRequest` (additive, all nullable/blank): `merged_by`,
  `closed_by` (char), `closed_at` (datetime null). `merge_pull_request` gains an
  **optional keyword** `actor=""` that, when supplied, fills `merged_by` — its
  existing positional signature `merge_pull_request(pr)` must keep working so the
  loop call site is unchanged.
- New view `pr_comment` (`@org_required`, POST, CSRF, org-scoped): creates a
  `PullRequestComment` with `author=request.user.get_username()`,
  `org=request.org`, then redirects back to detail. Empty body → no-op + message.
- Detail page renders comments newest-or-oldest in a clear order with author +
  relative time, plus a textarea + submit using design-system classes.

### D. List triage
- `pr_list` accepts `?status=open|merged|closed` (default: open emphasised, all
  others shown) and filters the org-scoped queryset accordingly; invalid/empty
  value falls back to the current behavior.
- The list header shows a **New PR** button linking to `vcs:pr_new`.

## Constraints / contracts to honor

- Edit only files under `vcs/`. Do NOT modify `accounts/models.py`,
  `helm/urls.py`, `helm/settings.py`, `templates/base.html`, or other apps' files.
- Keep these `vcs/services.py` signatures stable (loop + Sprint-1 callers):
  `next_pr_number(project)`, `open_pull_request(worktree, *, title, …)`,
  `refresh_diff(pr)`, `merge_pull_request(pr)` (the `actor` addition must be an
  optional keyword so `merge_pull_request(pr)` still works).
- New tenant model `PullRequestComment` subclasses
  `accounts.models.OrgScopedModel`; org stays nullable. New `PullRequest` fields
  are additive and nullable/blank.
- All new views are `@org_required` and operate on an org-scoped queryset
  (reuse/extend the existing `_scoped_prs(request)` helper) so cross-org access
  → 404, including the new create/close/reopen/comment paths.
- Templates `{% extends "base.html" %}` only; use existing `helm.css` classes
  (`card`, `badge`, `btn`, `btn-success`, `btn-sm`, `diff`, `grid`, `stat`,
  `list-row`, `mono`, `muted`, `row`, `between`). Load `{% load helm_extras %}`.
  No new external CSS/JS framework, no npm dependency.
- All changes additive with fallbacks; the autonomous loop must pass unchanged.
- `python manage.py makemigrations vcs` only — do NOT run `migrate`. Validate with
  `python manage.py check`.
- Preserve every Sprint-1 behavior + its rubric (org isolation, per-file diff,
  live CI, mergeability, permalink). Existing `vcs/tests.py` must still pass.

## Rubric (numbered, machine-checkable pass/fail)

1. `python manage.py check` exits 0 with no errors.
2. `accounts/models.py`, `helm/urls.py`, `helm/settings.py`, `templates/base.html`
   are byte-for-byte unchanged from HEAD (`git diff --quiet HEAD -- <path>` for
   each). Only files under `vcs/` (and `docs/prd/vcs.md`) are modified.
3. `python manage.py makemigrations vcs --check --dry-run` reports **no missing
   migrations** (i.e. the builder committed the additive migration); a new
   migration file exists under `vcs/migrations/`.
4. `vcs/services.py` still defines `next_pr_number`, `open_pull_request`,
   `refresh_diff`, `merge_pull_request`; `merge_pull_request(pr)` is still callable
   with a single positional arg (no required new params). Importing `vcs.services`
   raises no error.
5. The autonomous-loop path is intact: a test opens a PR via
   `open_pull_request(worktree, title=…)` with `worktree.project.org=None` and
   merges it via `merge_pull_request(pr)` (single positional) → `status=='merged'`,
   `org is None`, no exception. (Sprint-1 loop test still passes.)
6. New service `open_manual_pull_request` exists in `vcs/services.py` and, given a
   project whose repo has a head branch diffing from base, creates a `PullRequest`
   with `worktree is None`, the passed `author`, the passed/derived `org`, a
   non-empty `diff`, and correct `files_changed/additions/deletions`. Returns
   `None` when there is no diff between the two branches.
7. `open_manual_pull_request` sets `pr.org` to the explicitly passed `org`, and
   when `org` is omitted falls back to `getattr(project, "org", None)` without
   raising for an org-less project.
8. `list_branches(project)` exists, returns a list of branch-name strings for a
   real repo (containing at least the repo's branches), and returns `[]` (no
   exception) when `project.local_path` is empty/invalid.
9. A `vcs:pr_new` URL exists (`/vcs/pr/new/`). GET as an authenticated org member
   returns 200 and the form lists only the current org's projects (a project from
   another org does NOT appear in the response). Anonymous GET does not return 200
   with the form (redirects via `org_required`).
10. POST to `vcs:pr_new` with a valid in-org project + head/base branches that
    diff creates a PR scoped to `request.org` with `author` derived from the user,
    and redirects to that PR's detail (302 → `/vcs/pr/<pk>/`). The created PR is
    visible to that member and 404s for a member of another org.
11. POST to `vcs:pr_new` referencing a project that belongs to a **different** org
    does not create a PR for the requester and does not leak/modify the other
    org's data (form error or 404; no `PullRequest` created with the other org's
    project under `request.org`).
12. `PullRequest` has additive fields `closed_at` (nullable datetime),
    `closed_by` (char/blank) and `merged_by` (char/blank); none is required at the
    DB level (existing rows / loop creates remain valid with them unset).
13. `close_pull_request(pr, actor=…)` exists: on an OPEN pr it sets
    `status=='closed'`, populates `closed_at` and `closed_by`, emits a
    `core.models.Event`, and returns truthy; on a non-open pr it is a no-op
    returning falsey and never raises.
14. `reopen_pull_request(pr, actor=…)` exists: on a CLOSED pr it sets
    `status=='open'`, clears `closed_at`, emits an Event, returns truthy; on a
    non-closed pr no-ops + returns falsey, never raises.
15. `vcs:pr_close` and `vcs:pr_reopen` URLs exist, are `@org_required`, accept POST
    with CSRF, are org-scoped (cross-org POST → 404), and set
    `closed_by`/`merged-by`-style attribution from the acting user. A member can
    close their own org's open PR (status becomes `closed`) and reopen it.
16. Detail page renders a **Close** action for an open PR and a **Reopen** action
    for a closed PR (response HTML contains a form posting to `vcs:pr_close` for an
    open PR and to `vcs:pr_reopen` for a closed PR).
17. New model `PullRequestComment` subclasses `accounts.models.OrgScopedModel`,
    has a `pull_request` FK with `related_name="comments"`, an `author`, a `body`,
    and a `created_at`, and a nullable `org` FK (loop safety).
18. `vcs:pr_comment` URL exists (`@org_required`, POST, CSRF, org-scoped): posting a
    non-empty body as an in-org member creates a `PullRequestComment` linked to the
    PR with `author` from the user and `org==request.org`, then redirects to detail;
    an empty body creates no comment. Cross-org POST → 404.
18b. The PR detail page renders existing comments (author + body + relative time)
    and a comment form (textarea posting to `vcs:pr_comment`).
19. `merge_pull_request` accepts an optional keyword `actor` that, when provided,
    fills `merged_by`; called from `pr_merge` it records the acting user, and called
    as `merge_pull_request(pr)` (loop) it still merges with `merged_by` blank/None.
20. `pr_list` honors `?status=open|merged|closed`: a request with
    `?status=closed` shows closed PRs and not open ones (and vice-versa), all still
    org-scoped; the list header contains a link/button to `vcs:pr_new` ("New PR").
21. Org isolation preserved across ALL new views: for `pr_new` (POST), `pr_close`,
    `pr_reopen`, `pr_comment`, a request acting on a PR/project from another org
    returns 404 (or equivalently refuses + creates nothing), never 200-with-effect.
22. Sprint-1 behavior preserved: per-file diff cards, the `vcs:pr_ci_status`
    fragment + HTMX `every`-trigger poll, mergeability gating (disabled Merge button
    + reason), read-only conflict detection (repo unchanged after rendering detail),
    and the copyable absolute permalink all still render on the detail page.
23. Activity-feed integrity: opening (manual or loop) emits an `Event` with
    `icon='pr'`; merging emits `icon='merge'`; closing emits an `Event`. No existing
    Event emission removed.
24. All `vcs/` templates `{% extends "base.html" %}` and add no `<link>`/`<script>`
    to an external CSS/JS framework or npm dependency. Any copy/clipboard JS stays
    minimal vanilla.
25. `python manage.py test vcs` passes, including new tests for manual creation,
    close/reopen, and comments, and **no Sprint-1 `vcs` test regresses**.

## Open questions / risks

- `request.user.get_username()` is the attribution source; if a builder prefers
  `request.user.email`, either is acceptable as long as attribution is non-empty
  and stable. Loop path passes no actor → fields stay blank/None.
- `list_branches` reads the project repo with git; on a bare/missing repo it must
  degrade to `[]` so the New-PR form still renders (member simply has no branches
  to pick — show an inline "no branches found" hint).
- A manual PR points `worktree=None`; `merge_pull_request` already guards
  `if pr.worktree_id:` before touching a worktree, so merging a manual PR is safe —
  the builder must NOT introduce an unguarded `pr.worktree` access.
- Keep the conflict dry-run / mergeability logic exactly as Sprint 1 (always
  `git merge --abort`); manual PRs flow through the same `_mergeability` path.
