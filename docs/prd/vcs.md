# PRD — Pull Requests (multitenant + UX)

Section owner: PM for `vcs/`
Sprint: 1 (Build-out)
Status: Ready for builder

## Problem

Hull's Pull Requests section (`vcs/`) is the review surface where the autonomous
crew's work becomes mergeable change. Today it has three structural gaps:

1. **Not org-scoped.** `vcs.PullRequest` has no `org` field and the list/detail
   views (`vcs/views.py`) query `PullRequest.objects.all()` with no tenant
   filter. In a multitenant deployment every org sees every other org's PRs and
   can open their diffs and merge them. This violates the Sprint-1 tenancy
   contract.
2. **Thin review UX.** The detail page renders a single flat diff blob, a CI
   badge, and a merge button. Reviewers cannot see CI as anything but a static
   label, cannot see a per-file breakdown, cannot tell at a glance whether a PR
   is safe to merge (CI passing? already merged? conflicting?), and the merge
   button does not reflect mergeability.
3. **Weak cross-linking.** The PR is the hub of the incident -> fix -> PR -> CI ->
   merge story, but the list view doesn't surface CI/age, the detail view's links
   are partial, and there is no copyable deep link for sharing a PR in chat/docs.

We must close these gaps **without breaking the autonomous incident -> fix loop**,
which opens PRs and merges them with **no request and no org** (`org=None`).

## Goals

- Every PR belongs to an org; request paths only ever show/act on the current
  org's PRs.
- The autonomous loop keeps working unchanged: `open_pull_request`,
  `refresh_diff`, `merge_pull_request` run org-agnostically and default `org=None`.
- A reviewer can, on one screen: read the diff per-file, see live CI status,
  understand mergeability, merge, and grab a shareable link.

## Non-goals (scope-out, this sprint)

- Inline line comments / review threads / approvals workflow.
- Real GitHub/GitLab sync or webhooks.
- Branch-protection rules, required reviewers, CODEOWNERS.
- Conflict resolution UI (we only *detect & display* conflicts; resolution stays
  manual via the agent).
- Editing PR metadata (title/description) from the UI.
- Cross-org PR transfer.

## User stories

- As an **org member**, I open `/vcs/` and see only my org's PRs, so other
  tenants' work is invisible to me.
- As a **reviewer**, I open a PR and see the diff split by file with per-file
  add/del counts, so I can review large changes file by file.
- As a **reviewer**, I click "Run CI" and watch the CI badge update from
  pending -> running -> passed/failed without a full reload (HTMX poll), so I know
  when it's safe to merge.
- As a **reviewer**, I see whether a PR is mergeable (open + no conflicts) and the
  Merge button is disabled with a reason when it isn't, so I don't attempt invalid
  merges.
- As a **teammate**, I copy a PR's permalink from the detail page to paste into an
  incident/doc, so others can jump straight to the review.
- As the **autonomous loop**, I open and merge PRs with no request context and it
  still works end to end.

## Scope-in (MVP for this sprint)

### A. Org-scoping (tenancy contract)
- `vcs.PullRequest` subclasses `accounts.models.OrgScopedModel` (adds nullable
  `org` FK + `OrgManager`). Migration is additive; existing rows get `org=NULL`.
- `open_pull_request(...)` sets `pr.org = worktree.project.org` **if that attr
  exists and is set**, else leaves `org=None`. Must not raise if `Project` has no
  `org` yet (projects PM may land org-scoping in parallel) — use `getattr`.
- `pr_list` and `pr_detail` (and all action views: CI, merge) are guarded by
  `accounts.scoping.org_required` and filter by the current org using
  `PullRequest.objects.for_org(request.org)` / `scoped(...)`. A PR whose `org`
  differs from `request.org` returns **404** from detail/CI/merge.
- Backward-compat fallback: PRs with `org=NULL` (legacy + autonomous-loop rows)
  remain visible to a member whose org matches the PR's `project.org`, OR (if the
  project has no org either) are shown to any authenticated org member. This keeps
  the demo's autonomously-created PRs visible. (Implement via a queryset helper
  in `vcs/services.py` or the view; documented and tested.)

### B. Review UX
- **Per-file diff:** `vcs/diffrender.py` gains a function that splits a unified
  diff into a list of `{path, additions, deletions, html}` files; detail template
  renders each file in its own collapsible `.card` with a per-file header showing
  path and `+/-`. The existing `render_diff(diff_text)` signature stays (so the
  autonomous loop / any caller is unaffected) — the new function is additive.
- **Live CI:** a new HTMX fragment view `vcs:pr_ci_status` returns just the CI
  badge; the detail page polls it (`hx-trigger="every 2s"`) while
  `ci_status in (pending, running)` and stops polling otherwise. "Run CI" keeps
  the existing fallback behavior (orchestration first, threaded fallback that
  marks passed) — additive, no contract change.
- **Mergeability:** detail view computes a `mergeable` boolean + `merge_blocked_reason`
  (not open / already merged / git reports conflicts) and the Merge button is
  disabled with the reason shown. Detecting conflicts uses a dry-run
  `git merge --no-commit --no-ff` that is always aborted (read-only effect);
  failures degrade gracefully to "mergeable unknown" (button enabled) so the loop
  is never blocked.
- **Copy permalink:** detail page shows the absolute PR URL
  (`HELM_BASE_URL + pr.get_absolute_url()`) with a one-click copy button (minimal
  vanilla JS, no framework).

### C. List polish
- List rows show CI badge (already present) plus relative age (`created_at`) and
  remain scoped + clickable.

## Constraints / contracts to honor
- Do NOT modify `accounts/models.py`, `helm/urls.py`, `helm/settings.py`,
  `templates/base.html`, or other apps' files. Only edit files under `vcs/`.
- Keep `vcs/services.py` function signatures stable: `next_pr_number`,
  `open_pull_request`, `refresh_diff`, `merge_pull_request`.
- Templates `{% extends "base.html" %}` only and use existing `helm.css` classes
  (`card`, `badge`, `btn`, `diff`, `grid`, `stat`, `list-row`, `mono`, `muted`).
  Load `{% load helm_extras %}` for `status_badge`.
- All changes additive with fallbacks; the autonomous loop must pass unchanged.
- `makemigrations vcs` only — do NOT run `migrate`. Validate with `manage.py check`.

## Rubric (numbered, machine-checkable pass/fail)

1. `vcs.PullRequest` subclasses `accounts.models.OrgScopedModel`.
   CHECK: `issubclass(__import__('vcs.models', fromlist=['PullRequest']).PullRequest, __import__('accounts.models', fromlist=['OrgScopedModel']).OrgScopedModel)` is `True`.
2. `PullRequest` has a nullable `org` ForeignKey to `accounts.Org`.
   CHECK: `PullRequest._meta.get_field('org')` is a `ForeignKey` to `accounts.Org` with `null=True`.
3. A new additive migration exists under `vcs/migrations/` adding the `org` field; `python manage.py makemigrations vcs --check --dry-run` reports no missing migrations.
4. `python manage.py check` exits 0 with no errors.
5. `accounts/models.py` is byte-for-byte unchanged from HEAD (`git diff --quiet HEAD -- accounts/models.py`). Likewise `helm/urls.py`, `helm/settings.py`, `templates/base.html` unchanged.
6. `vcs/services.py` still defines `next_pr_number`, `open_pull_request`, `refresh_diff`, `merge_pull_request` with their existing call signatures (params unchanged); importing `vcs.services` raises no error.
7. `open_pull_request` sets `pr.org` from `worktree.project.org` when present and does NOT raise when the project has no `org` attribute or it is `None` (uses `getattr` with default). Verified by a test where `project.org` is unset/None -> PR created with `org=None`, no exception.
8. `open_pull_request` and `merge_pull_request` work with `org=None` end to end (autonomous-loop path): a test opens a PR from a worktree with no org and merges it successfully (status becomes `merged`).
9. `pr_list` view is wrapped by `accounts.scoping.org_required` (or otherwise redirects unauthenticated/orgless users) — an anonymous GET to `/vcs/` does not return 200 with another org's PRs.
10. Org isolation: given PRs in org A and org B, a request authenticated as an org-A member sees org-A PRs in the `/vcs/` list and does NOT see org-B PRs. Verified by a Django test client test (response contains A's PR title, not B's).
11. Cross-org detail access is blocked: GET `/vcs/pr/<pk>/` for a PR belonging to a different org returns 404 (not 200). Same for the CI and merge action POSTs.
12. Legacy/loop fallback: a PR with `org=NULL` whose `project.org` matches the member's org (or whose project also has no org) is visible to that member's list/detail. Verified by test.
13. `vcs/diffrender.py` exposes a new additive function (e.g. `split_diff(diff_text)` or `render_files(diff_text)`) returning per-file structures each with `path`, `additions`, `deletions`, and rendered HTML; the original `render_diff(diff_text)` still exists and returns safe HTML for a non-empty diff.
14. The PR detail page renders a per-file diff: for a multi-file PR the response HTML contains a distinct file header/section per changed file (e.g. one `.card`/file-head per file path), not a single flat blob.
15. A CI-status fragment endpoint exists (named url under `app_name='vcs'`, e.g. `vcs:pr_ci_status`) and returns just a CI badge for the given PR; it is org-scoped (404 for cross-org).
16. The detail template wires HTMX polling of the CI fragment that is active only while `ci_status` is `pending`/`running` (template contains `hx-get` to the fragment with an `every`-based `hx-trigger`).
17. Mergeability gating: the detail template renders the Merge button `disabled` when the PR is not open (status != `open`), and the view/context exposes a `mergeable` boolean and a human-readable block reason.
18. Conflict detection is read-only: the mergeability check never leaves the repo in a merged/dirty state (any dry-run merge is aborted) and never raises out of the view; a test verifies the repo HEAD/working tree is unchanged after rendering detail for a conflicting PR, and the page still loads (200).
19. The detail page shows a copyable absolute permalink to the PR (string containing `pr.get_absolute_url()` value, full URL using `HELM_BASE_URL`) with a copy control; copy uses minimal vanilla JS only (no new JS framework / no npm dependency added).
20. Activity feed integrity: opening and merging a PR still emit `core.models.Event` entries with `icon='pr'` (open) and `icon='merge'` (merge) as before (events not removed).
21. All `vcs/` templates extend `base.html` (`{% extends "base.html" %}`) and add no `<link>`/`<script>` to external CSS/JS frameworks.
22. Test suite: `python manage.py test vcs` passes (new tests included), and no existing test in the repo regresses.

## Open questions / risks
- `Project.org` may or may not land this sprint (projects PM owns it). Mitigation:
  all org derivation uses `getattr(project, 'org', None)` and tolerates absence.
- Conflict dry-run mutates the working tree transiently; must run on the project
  repo carefully and always `git merge --abort`. If the repo is in a detached or
  dirty state, skip detection and report "unknown" (button enabled) rather than
  blocking the loop.
