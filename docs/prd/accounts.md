# PRD — Accounts & User Management ("helm" / Hull)

Owner: Section PM — Accounts & User Management
Sprint: 1 (Build-out, iteration 2)
Section owns: `accounts/` (extend the existing skeleton — do **not** modify `accounts/models.py`,
`accounts/scoping.py`, or `accounts/middleware.py`; those are the Mayor-owned tenancy contract).

---

## 0. Current state (what the previous sprint already shipped)

The accounts section is **not** a greenfield. The prior iteration shipped and is `check`-clean
(`python manage.py check` → 0 issues; `makemigrations accounts --check` → no changes):

- Auth: `signup`, `login`, `logout`, `onboarding` (creates first org + OWNER membership).
- Members: `/accounts/members/` roster (org-scoped), `change_role`, `remove_member`, with a
  **last-owner guard** and an "admins cannot touch owners" guard, RBAC-gated by `require_org_admin`.
- Invitations: `/accounts/invitations/` create + list (pending/accepted) + `revoke_invite`;
  token accept at `/accounts/invite/<token>/` (idempotent, respects `unique_together(org,user)`).
- Org settings: `/accounts/org/` (rename, slug read-only). Profile: `/accounts/profile/`
  (name/email + password change).
- Org switcher partial `accounts/_org_switcher.html`, wired into the **accounts pages only** via
  `_account_base.html` `{% block actions %}`; `switch_org` view exists.
- RBAC helpers `accounts/permissions.py` (`is_org_admin`, `require_org_admin`), server-side gated.

So the old rubric (R1–R20) is satisfied. **This PRD targets the next-highest-impact layer**, not
a re-build. Builders MUST keep all existing routes/behaviour green (Section 9 regression rubric)
and only add on top.

## 1. Problem (remaining gaps for an enterprise org/user surface)

1. **The org switcher is not actually global.** It only renders on `/accounts/*` pages because each
   section fills its own `{% block actions %}` and accounts cannot edit `base.html` or other apps'
   templates. A multi-org operator on the dashboard, Projects, Incidents, etc. has **no way to
   switch tenants** — the explicit "reachable from every authenticated page" goal is half-met.
2. **`switch_org` has an open-redirect / fragile redirect.** It redirects to raw
   `request.META['HTTP_REFERER']` with no allow-list, and a member can attempt to switch to an org
   they don't belong to only being saved by `get_object_or_404` (404, not a clean message).
3. **No self-service membership.** A member cannot **leave** an org they belong to; everything is
   admin-driven. There is also no **transfer-ownership** affordance beyond manually promoting then
   demoting — risky around the last-owner guard.
4. **Membership changes are invisible.** Role changes, removals, invites, and accepts emit nothing
   to the activity feed, so the demo's "narrate everything" story skips all tenant administration.
5. **Members page doesn't surface pending invites or counts**, so admins jump between two pages to
   understand "who's in / who's coming".
6. **Profile is thin** — no display name shown back in the UI (the switcher/member rows always show
   `username`), and no "your role in each org" overview.

These are all request-path, additive concerns. None touch the tenancy contract or the autonomous
incident→fix loop (which runs with no request and `org=None`).

## 2. Goals / Non-goals

**Goals (this iteration)**
- Make the org switcher reachable from **every** authenticated page, using only files `accounts`
  owns (an `accounts` context processor + a reusable, self-contained partial) — no edits to
  `base.html`, `helm/settings.py`, `helm/urls.py`, or other apps.
- Harden `switch_org`: only switch to orgs the user belongs to; safe same-host redirect; clear
  message; works for GET (link) so it can live in the switcher menu.
- Self-service: a member can **leave** an org (blocked for the last owner); an owner can **transfer
  ownership** to another member in one action (atomic, last-owner-safe).
- Emit `core.Event.log(...)` activity-feed entries for the meaningful tenant actions (invite
  created, invite accepted, role changed, member removed, member left, ownership transferred, org
  renamed) — wrapped so a logging failure never breaks the action.
- Members page shows the pending-invite count and a compact pending list inline.
- Profile shows display name + a read-only "your organizations & roles" list.

**Non-goals (explicitly deferred)**
- SSO / SAML / OIDC, real email/SMTP delivery of invites (link is surfaced in-app), 2FA, password
  reset email flow.
- Billing, seat limits, custom roles or granular per-resource permissions beyond the 4 roles.
- Audit log persistence model (Enterprise section owns that) — we only emit to the existing
  `core.Event` feed, additively.
- Org deletion, cross-org resource sharing, editing any tenancy-contract file or any other app.

## 3. Users & user stories

- **Operator (any role), anywhere in Hull** — "From any page I can see which org I'm acting in and
  switch to another org I belong to; the whole app re-scopes."
- **Owner** — "I can hand the org to a teammate in one click (transfer ownership) without risking
  locking myself out, and I see tenant changes show up in the activity feed."
- **Member / Viewer** — "I can leave an org I no longer need; I cannot leave one where I'm the last
  owner."
- **Admin** — "On the members page I see who's pending so I don't bounce between tabs."
- **Auditor / demo viewer** — "Tenant administration (invites, role changes, ownership transfer)
  appears in the activity feed so the system narrates itself."

## 4. Scope-in (MVP feature set this iteration)

1. **Global org switcher** — add `accounts/context_processors.py:account_nav(request)` exposing
   `account_memberships` (the user's memberships) and `current_org` for templates. Refactor
   `_org_switcher.html` to be fully self-contained (no dependency on accounts-only context) so any
   section *can* `{% include "accounts/_org_switcher.html" %}`. Provide an always-reachable
   **account menu page** `/accounts/` (org switcher + links) as the guaranteed entry point from the
   topbar/sidebar that does not require editing base.html. The switcher highlights the active org.
   > Note: because `accounts` cannot edit `base.html` or register a context processor in
   > `settings.py` itself, the builder MUST coordinate the single context-processor registration
   > with the integrator/enterprise owner (one line), OR fall back to the self-contained partial +
   > `/accounts/` hub. Either path satisfies the rubric; pick the one that keeps `check` green.
2. **Harden `switch_org`** — accept GET; only switch to an org where the user has a `Membership`
   (else `messages.error` + redirect, **no 404/500**); redirect only to a **safe same-host** URL
   (use `django.utils.http.url_has_allowed_host_and_scheme`) falling back to `core:dashboard`.
3. **Leave org** — `POST /accounts/leave/` removes `request.user`'s membership in `request.org`;
   **blocked if they are the last owner** (`messages.error`, no-op); on success, switch the active
   org to another membership (or onboarding if none) and emit an Event. Self-removal only; does not
   touch other members.
4. **Transfer ownership** — `POST /accounts/members/<id>/transfer/` (owner-only): promote target to
   OWNER and demote the acting owner to ADMIN **atomically** (`transaction.atomic`), so the org
   never has zero owners at any point. Rejected for non-owners server-side.
5. **Activity-feed emission** — at each meaningful action (invite created, invite accepted, role
   changed, member removed, member left, ownership transferred, org renamed) call
   `core.models.Event.log(verb, actor=<username>, level=..., icon="agent"/"check"/...)`. Wrap in a
   `try/except` so a feed failure never breaks the tenant action. Import lazily to avoid load-order
   issues.
6. **Members page enrichment** — show the count of pending invitations and a compact inline list of
   pending invites (email + role + revoke) on `/accounts/members/` for admins, and a "Transfer
   ownership" / "Leave org" control where applicable, all RBAC-gated.
7. **Profile enrichment** — render the user's display name (first+last, falling back to username)
   and a read-only "Your organizations" table (org name + your role badge), each linking to
   `switch_org`.

All new request paths use the contract: `@org_required` / `login_required`,
`Membership.objects.filter(org=request.org)` (or `.for_org`), operate on `request.org`. **No new
model is introduced.** If any helper model were ever needed it must subclass
`accounts.models.OrgScopedModel` and keep `org` nullable — but this iteration adds none.

## 5. Scope-out (this iteration)

- Email/SMTP delivery, invite expiry/resend cadence, bulk invite, invite-by-link-without-account.
- SSO, 2FA, password-reset email, custom roles/granular permissions, per-resource ACLs.
- Org deletion; multi-step ownership transfer with confirmation emails.
- A persisted audit-log model (Enterprise owns it) — we only emit to `core.Event`.
- Editing the tenancy contract, `base.html`, `helm/urls.py`, `helm/settings.py`, or any other app's
  files (the one context-processor registration line, if used, is coordinated with the integrator).

## 6. Design / constraints

- Every page `{% extends "base.html" %}` (or `accounts/_account_base.html` → base) and uses only
  `static/css/helm.css` classes (card, badge, btn, list-row, table, field, grid-*, empty, toast,
  pill). Dark premium look. The switcher's tiny vanilla-JS toggle is allowed (already present); **no
  new CSS/JS framework or external UI `<link>`/`<script>`**.
- All write actions are POST + `{% csrf_token %}` and **server-side RBAC-gated** (not just hidden).
- Keep everything **additive**: do not change existing route names, signatures, or behaviour that
  the old rubric (Section 9) locks in. The autonomous loop contracts
  (`deploys/observability/orchestration/agents` services) are untouched; `org` stays nullable; no
  service-layer call is made to require a request.
- `core.Event.log` calls are best-effort (`try/except`) and lazily imported.
- Validate with `python manage.py check`; you MAY run `python manage.py makemigrations accounts`
  but must **not** run `migrate`. Smoke-test on port 8011+ and kill it.

---

## 7. Machine-checkable rubric (pass/fail) — this iteration

Each item is independently verifiable. "Authed admin" = logged-in user whose membership in the
active org is owner/admin. "Authed viewer" = role member/viewer. Use Django test client / shell.

N1. `accounts/context_processors.py` defines a callable (e.g. `account_nav(request)`) that returns a
    dict including the current user's memberships (org names reachable) and the current org; it does
    not raise for an anonymous request (returns an empty/default dict).
N2. `accounts/_org_switcher.html` is self-contained: it renders the list of the user's memberships
    and an active-org indicator using only `request`/context it provides, such that an arbitrary
    template can `{% include "accounts/_org_switcher.html" %}` without extra view context. (Check:
    the include references no variable that only an accounts view sets.)
N3. There is an always-reachable account hub at `GET /accounts/` (HTTP 200 for an authed user) that
    contains the org switcher and links to members/invitations/org settings/profile.
N4. `switch_org` accepts a **GET** request and, for an org the user is a member of, sets
    `request.session['org_id']` to that org and redirects (302). (No 404/405 on the documented path.)
N5. `switch_org` to an org the user is **not** a member of does **not** change the session org and
    does **not** 500; it returns a redirect with a user-facing error message (or 302/200 no-op).
N6. `switch_org`'s post-switch redirect target is validated as same-host (rejects an external
    `next`/referer host), falling back to a safe internal URL (e.g. `core:dashboard`).
N7. `POST /accounts/leave/` by a non-last-owner member removes exactly that user's `Membership` in
    `request.org` (DB row gone), leaves other members untouched, and redirects (302).
N8. `POST /accounts/leave/` by the **last owner** of the org is rejected: the membership still
    exists afterward, owner count is unchanged, and a user-facing error is shown (no 500).
N9. `POST /accounts/members/<id>/transfer/` by an **owner** promotes the target to OWNER and demotes
    the acting owner to ADMIN; afterward the org has **≥ 1 owner** and the target's role is owner
    (verify in DB). The operation is atomic (on any failure, neither role changes).
N10. The transfer action is RBAC-gated: an authed admin/viewer/member POSTing it is rejected
     server-side (role unchanged, redirect/error, no 500).
N11. `core.models.Event.log` is invoked for at least: invite created, invite accepted, role changed,
     member removed, member left, ownership transferred, and org renamed. (Check: each action path
     calls `Event.log`; verify a new `Event` row appears after performing one such action via the
     test client.)
N12. Every `Event.log` call site is wrapped so that if logging raises, the underlying tenant action
     still completes successfully (simulate by asserting the action's DB effect persists even if
     `Event.log` is monkeypatched to raise).
N13. `GET /accounts/members/` for an authed admin shows the **pending invitation count** and a
     pending-invite list (each with email + role); the data shown is scoped to `request.org` only.
N14. The members page exposes a "Transfer ownership" control only to owners and a "Leave org"
     control to the current user, and both controls are absent for users without the right (template
     gating) **and** rejected server-side if POSTed directly (defense in depth — see N10/N8).
N15. `GET /accounts/profile/` renders the user's display name (first+last or username fallback) and
     a "Your organizations" list showing each org the user belongs to with their role badge; each
     entry links to `accounts:switch_org` for that org id.
N16. New write routes (`leave`, `transfer`) require auth: an unauthenticated POST redirects to login
     (302 to `LOGIN_URL`); org-scoped ones with no active org redirect to `accounts:onboarding`.
N17. All new/edited templates `{% extends %}` base (directly or via `_account_base.html`) and add
     **no** external CSS/JS framework (`<link>`/`<script>` to UI libs) beyond what base.html loads.
N18. `python manage.py check` exits 0 with the changes applied, and `makemigrations accounts
     --check` reports **no missing migrations** (this iteration adds no model; if a context
     processor is registered, it does not break `check`).
N19. The autonomous-loop contracts are untouched: no edits to `deploys/services.py`,
     `observability/services.py`, `orchestration/service.py`, `agents/services.py`,
     `accounts/models.py`, `accounts/scoping.py`, or `accounts/middleware.py`; `org` stays nullable
     and no accounts code requires a request in a service-layer call.
N20. Directly POSTing any management action (role change / remove / invite create / revoke / rename
     / transfer / another user's leave) as an unauthorized role is rejected **server-side**, not
     merely hidden in the template.

## 8. Builder ticket list (this iteration)

See the structured ticket list returned with this PRD (ACC2-1 … ACC2-7). Build order:
ACC2-1 (switch_org hardening + context processor + `/accounts/` hub) →
ACC2-2 (self-contained global switcher partial) →
ACC2-3 (leave org) → ACC2-4 (transfer ownership) →
ACC2-5 (activity-feed emission, best-effort) →
ACC2-6 (members page enrichment) → ACC2-7 (profile enrichment + polish + check/makemigrations).

## 9. Regression rubric — DO NOT REGRESS (prior iteration, must stay green)

G1. `GET /accounts/members/` returns 200 and lists exactly `request.org`'s memberships (no
    cross-org rows).
G2. Role change / remove are RBAC-gated and enforce the **last-owner guard** (cannot demote/remove
    the final owner; user-facing error, no 500).
G3. `POST /accounts/invitations/` (admin) creates an `Invitation` scoped to `request.org` with a
    unique non-empty token and null `accepted_at`; the accept URL is surfaced in-app.
G4. `GET /accounts/invite/<token>/` creates the membership idempotently (no duplicate, no
    `IntegrityError`/500 if already a member) and sets `accepted_at`.
G5. `GET /accounts/org/` rename is admin-gated and changes only `request.org.name` (slug unchanged).
G6. `GET /accounts/profile/` updates name/email and changes password (new password authenticates).
G7. `accounts/models.py`, `scoping.py`, `middleware.py` remain byte-for-byte the contract.
