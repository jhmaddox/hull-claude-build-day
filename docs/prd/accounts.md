# PRD — Accounts & User Management ("helm" / Hull)

Owner: Section PM — Accounts & User Management
Sprint: 1 (Build-out)
Section owns: `accounts/` (extend the existing skeleton — do **not** modify `accounts/models.py`,
`accounts/scoping.py`, or `accounts/middleware.py`; those are the Mayor-owned tenancy contract).

---

## 1. Problem

Hull already has the tenancy *plumbing* — `Org`, `Membership`, `Invitation` models, a
`CurrentOrgMiddleware` that sets `request.org`, and an `org_required` decorator. But there is
**no enterprise-facing surface** to operate a tenant:

- An owner cannot see who is in their org, cannot change anyone's role, cannot remove anyone.
- There is no way to invite a teammate — `Invitation` exists in the DB but nothing creates or
  accepts one. Onboarding a colleague today requires hitting the Django admin.
- A user who belongs to multiple orgs has a `switch_org` view but **no UI** to reach it — they
  are silently pinned to whatever the middleware picked.
- There is no org-settings page (rename org, see the slug) and no profile page (change your own
  name / email / password).
- RBAC roles exist as data but are never *enforced* in the UI — a viewer sees the same write
  controls as an owner.

For an "enterprise org/user management" section this is the table-stakes gap. This sprint closes
it without touching the tenancy contract and without ever risking the autonomous
incident→fix loop (the loop runs with no request, `org=None`; all our changes are request-path
only and additive).

## 2. Goals / Non-goals

**Goals (this sprint)**
- A real members management surface: list members, change roles, remove members — RBAC-gated.
- Invitations: an admin/owner can create an invite; an invitee can accept it via a token link
  and become a member.
- Org settings (rename) and a personal profile page (name/email/password).
- An org switcher reachable from every authenticated page (top-nav actions slot).

**Non-goals (explicitly deferred)**
- SSO / SAML / OIDC, email delivery of invites (we surface the link in-app instead).
- Billing, seat limits, custom roles/permissions beyond the 4 existing roles.
- Audit log (owned by the Enterprise section), API keys.
- Editing the tenancy contract files or adding cross-org sharing.

## 3. Users & user stories

- **Owner** — "I can rename my org, invite teammates with a chosen role, promote/demote members,
  and remove people. I can never be locked out (cannot remove/demote the last owner)."
- **Admin** — "I can manage members and invitations like an owner, but I cannot remove an owner
  or delete the org."
- **Member / Viewer** — "I can see the member roster and my profile, switch between orgs I belong
  to, but I do not see management controls."
- **Invitee** — "I follow an invite link, sign in or sign up, accept, and land in the org."
- **Multi-org user** — "I switch the active org from the top nav and every section re-scopes."

## 4. Scope-in (MVP feature set)

1. **Members list** at `/accounts/members/` — roster of the current org (`request.org`) with
   username/email, role badge, joined date. Org-scoped: only the current org's memberships.
2. **Role management** — owner/admin can change a member's role via a POST; protected so the
   **last owner cannot be demoted** and a non-owner cannot create/elevate to a role above their
   own authority (admins cannot touch owners).
3. **Remove member** — owner/admin can remove a member via POST; the **last owner cannot be
   removed**; users may also remove (leave) handled as removing self is out of MVP — removal is
   admin-driven only.
4. **Invitations** — create at `/accounts/invitations/` (email + role), generating a unique
   `token`; list pending/accepted invites for the org; **revoke** a pending invite. The accept
   link `/accounts/invite/<token>/` is shown in-app (copyable) since email is out of scope.
5. **Accept invite** — visiting `/accounts/invite/<token>/`: if logged-out, send through
   login/signup then back; on accept, create a `Membership` for the invite's org+role, mark the
   invite `accepted_at`, set it as the active org, redirect to dashboard. Idempotent: an
   already-accepted or already-member token does not create duplicates (unique_together on
   `(org,user)` is respected, no 500).
6. **Org settings** at `/accounts/org/` — owner/admin can rename the org; slug shown read-only.
7. **Profile** at `/accounts/profile/` — any authenticated user edits first/last name + email and
   changes password (Django `set_password`, re-login not required).
8. **Org switcher** — a control rendered in the top-nav `actions` block on accounts pages (and
   reusable include) listing the user's memberships; selecting one calls the existing
   `accounts:switch_org` and re-scopes. Shows the active org name.
9. **RBAC gating helper** — a small in-app permission check (e.g. `request.membership.can_admin`,
   which the contract already exposes) used to hide/disable management controls for
   member/viewer and to 403/redirect on direct POSTs.

All new request paths use the contract: `@org_required` / `login_required`,
`Membership.objects.filter(org=request.org)` (or `for_org`), and operate on `request.org`.
No new model is required (the three tenancy models already exist); if any helper model is
added it must subclass `accounts.models.OrgScopedModel` and keep `org` nullable.

## 5. Scope-out (this sprint)

- Email/SMTP delivery, invite expiry/resend cadence, bulk invite.
- SSO, 2FA, password reset email flow (profile password change only).
- Custom roles/granular permissions, per-resource ACLs.
- Org deletion, transfer ownership flow beyond promote-to-owner.
- Audit log entries (Enterprise section) — though emitting `core.Event.log` is encouraged where
  natural and is not penalized.

## 6. Design / constraints

- Every page `{% extends "base.html" %}`; use only `static/css/helm.css` classes (cards, badge,
  btn, list-row, table, field, grid-*). Dark premium look. Do **not** edit `base.html`,
  `helm/urls.py`, or `helm/settings.py`.
- Org switcher must live in the `{% block actions %}` topbar slot (base.html has no nav slot for
  it) and/or a reusable `{% include %}` partial so other sections can drop it in.
- Keep all changes **additive**; never break or modify the autonomous loop contracts
  (`deploys/observability/orchestration/agents` services). The loop runs with `org=None`.
- Validate with `python manage.py check`; you MAY run `python manage.py makemigrations accounts`
  but must **not** run `migrate` (integrator owns the shared DB). Smoke-test on port 8011+.

---

## 7. Machine-checkable rubric (pass/fail)

Each item is independently verifiable. "Authed admin" = a logged-in user whose membership in the
active org has role owner or admin. "Authed viewer" = role member or viewer.

R1. `accounts/urls.py` registers named routes: `members`, `org_settings`, `profile`,
    `invitations`, and an invite-accept route taking a token (e.g. `accept_invite`). Each
    reverses without error.
R2. `GET /accounts/members/` returns HTTP 200 for an authed user with an org and lists exactly the
    `Membership` rows of `request.org` (no rows from any other org appear).
R3. The members list renders each member's role using a `badge` class and shows username/email and
    a joined/created date.
R4. `accounts/models.py`, `accounts/scoping.py`, and `accounts/middleware.py` are **unchanged**
    from the contract (byte-for-byte identical to the skeleton; no edits in the diff).
R5. A POST to change a member's role succeeds (302/200 + DB role updated) when performed by an
    authed admin/owner, and is rejected (403, redirect, or no-op with the role unchanged) when
    performed by an authed viewer/member.
R6. Demoting or removing the **last remaining owner** of an org is prevented: the operation does
    not reduce the org's owner count to zero (role/membership unchanged) and returns a
    user-facing error message rather than a 500.
R7. `GET /accounts/invitations/` (authed admin) returns 200 and a POST with an email + role
    creates an `Invitation` row scoped to `request.org` with a non-empty unique `token` and
    `accepted_at` null.
R8. The invitations page surfaces the accept URL for each pending invite (a link/text containing
    the token) so it can be copied (email delivery is out of scope).
R9. `GET /accounts/invite/<token>/` for a logged-in user whose email/account is not yet a member
    creates a `Membership` for the invite's org and role, sets the invite's `accepted_at`, and
    redirects into the app (302). A second visit to the same token does not create a duplicate
    membership and does not 500 (idempotent).
R10. Invite acceptance respects the contract uniqueness: no `IntegrityError`/500 if the user is
     already a member of that org.
R11. `GET /accounts/org/` (authed admin) returns 200; a POST renaming the org updates `Org.name`
     for `request.org` only; the slug field is displayed but not changed by the rename.
R12. Org settings write actions (rename) are RBAC-gated: an authed viewer/member cannot change the
     org name (403/redirect/no-op, name unchanged).
R13. `GET /accounts/profile/` returns 200 for any authed user; a POST updating first/last name and
     email persists to the `User`; a POST changing the password results in the new password
     authenticating (and the old one not).
R14. An org switcher UI is reachable from authenticated accounts pages: it lists the current
     user's memberships (org names) and each option links to / posts to `accounts:switch_org`
     with the corresponding org id. The active org is visually indicated.
R15. Switching org via `accounts:switch_org` changes `request.session['org_id']` and subsequently
     `request.org`, so an org-scoped list (e.g. members) reflects the newly active org.
R16. Every new view is access-controlled: unauthenticated `GET` of `members`, `invitations`,
     `org`, `profile` redirects to login (302 to `LOGIN_URL`); org-required views redirect a
     user with no org to `accounts:onboarding`.
R17. All new templates `{% extends "base.html" %}` and introduce **no** new CSS/JS framework
     (no `<link>`/`<script>` to external UI libs beyond what base.html already loads).
R18. `python manage.py check` exits 0 with the changes applied, and `makemigrations accounts
     --check` reports no missing migrations (any model/help additions are migrated).
R19. The autonomous loop contracts are untouched: no edits to `deploys/services.py`,
     `observability/services.py`, `orchestration/service.py`, `agents/services.py`, and no
     accounts code makes `org` non-nullable or requires a request for service-layer calls.
R20. RBAC controls are not merely hidden: directly POSTing a management action
     (role change / remove / rename / invite create / revoke) as an authed viewer/member is
     rejected server-side (not just hidden in the template).

---

## 8. Builder ticket list

See the structured ticket list returned with this PRD (ACC-1 … ACC-9). Build order:
ACC-1 (RBAC helpers + base nav include) → ACC-2 (members) → ACC-3 (roles/remove) →
ACC-4 (invitations create/list/revoke) → ACC-5 (accept) → ACC-6 (org settings) →
ACC-7 (profile) → ACC-8 (org switcher) → ACC-9 (polish + makemigrations + check).
