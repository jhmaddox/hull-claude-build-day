# PRD — Enterprise (RBAC, Audit, API keys, Org Settings)

Section owner: PM (enterprise). App: `enterprise/` (NEW Django app).
Sprint: Build-out (org-scoped, parallel). Status: MVP scope locked.

---

## 1. Problem

Hull is a multi-tenant control plane that runs a customer's entire production
stack. Today, tenancy exists (Org / Membership / Role via `accounts`) but the
**enforcement, accountability, and programmatic-access** layer that makes a
multi-tenant product safe for real teams is missing:

- **No RBAC enforcement.** `Membership.role` (owner/admin/member/viewer) exists,
  but nothing in the product checks it. A viewer can mutate, a member can change
  billing-grade settings. There are no reusable helpers, so every other
  workstream would re-invent (inconsistent, leaky) permission checks.
- **No audit trail.** When an org member merges a PR, rotates a key, deploys, or
  changes a setting, there is no durable, org-scoped record of *who did what,
  when*. Enterprise buyers require this; incident forensics require it.
- **No programmatic access.** Everything is session/cookie auth. There is no way
  for CI, scripts, or external systems to call Hull on behalf of an org with a
  scoped, revocable credential.
- **No org settings home.** There is nowhere to view/manage org-level
  configuration (org profile, security posture, the above features).

**Constraint that dominates the design:** the autonomous incident→fix loop runs
**without a request and without a user** (`org` defaults to `None`, no
`request.org`, no `request.user`). RBAC and audit must be **additive with
fallbacks**: when there is no user/request (the agent loop, management commands,
Temporal workers), permission checks must *pass-through* (never block) and audit
logging must degrade gracefully (record `actor="system"`, `org=None`) — never
raise. The loop is the crown jewel and a hard QA gate.

---

## 2. User stories

- As an **org owner**, I see a Settings area with my org profile and the
  enterprise controls (members' roles summary, API keys, audit log).
- As an **owner/admin**, I create a named API key, see it **once** in plaintext
  at creation, and can revoke it later; the stored value is hashed.
- As a **developer/CI**, I authenticate a programmatic request with
  `Authorization: Bearer hull_<token>` and the request resolves to the key's org
  (org scoping applies) without a session.
- As an **owner/admin**, I browse a filterable **audit log** of org actions
  (actor, action, target, timestamp) so I can answer "who did this?".
- As a **viewer**, I am blocked (HTTP 403 / hidden controls) from mutating
  actions; as a **member** I can do normal work but not admin-only actions.
- As **any builder workstream**, I wrap a view with `@role_required("admin")` or
  call `audit(request, "pr.merged", target=pr)` in one line and get consistent
  enforcement + logging.
- As the **autonomous loop**, my agent-driven merges/deploys still succeed
  (no user, no request) and are recorded in the audit log as `system` actions.

---

## 3. Scope

### Scope IN (this sprint — the MVP)

1. **New `enterprise` app**, org-scoped, wired like other apps (own `urls.py`
   with `app_name="enterprise"`, templates under `enterprise/templates/enterprise/`,
   extends `base.html`, uses `helm.css` classes). Importing the app and its
   `services` is always safe (no import-time errors, no `NotImplementedError`
   on the audit/RBAC happy paths).

2. **RBAC enforcement helpers** (`enterprise/rbac.py`) keyed off
   `accounts.models.Membership.role`:
   - `ROLE_RANK` ordering: `viewer < member < admin < owner`.
   - `has_role(request, minimum)` → bool. Returns `True` (fail-open) when there
     is no authenticated user / no `request.org` / no membership context
     (so the autonomous loop and anonymous internal calls are never blocked).
   - `role_required(minimum)` view decorator: composes with `org_required`;
     returns **HTTP 403** (rendered with base.html) when an authenticated
     in-org user's role is below `minimum`; passes through when there is no
     request-bound user (defensive) — but for browser requests an authenticated
     user is always present, so this is real enforcement.
   - A template helper (context processor **inside the enterprise app only**, or
     a `{% load %}` tag in `enterprise/templatetags/`) `can(role)` so templates
     can hide controls the user may not use. (MUST NOT edit `base.html` or global
     settings to register it; provide it as an app-local template tag.)

3. **Audit log** (`enterprise.models.AuditLog`, subclasses
   `accounts.models.OrgScopedModel`):
   - Fields: `actor` (string, e.g. username or "system"), `actor_user` (FK to
     user, nullable), `action` (string verb, e.g. `apikey.created`),
     `target_type` / `target_id` / `target_repr` (string), `metadata` (JSON),
     `ip` (nullable), `created_at` (indexed).
   - `enterprise/services.py::record_audit(action, *, org=None, actor="system",
     actor_user=None, target=None, metadata=None, ip=None, request=None)` — the
     single write path. If `request` is given, it derives org/actor/user/ip from
     it. **Never raises** on bad input (wraps in try/except, returns the row or
     `None`). Defaults make it callable with `org=None` from the loop.
   - `enterprise/services.py::audit(request, action, **kw)` thin convenience
     wrapper for request paths.
   - Audit log **view** at `/enterprise/audit/` (owner/admin only) listing the
     org's entries newest-first, with a simple `?action=` / `?actor=` filter.

4. **API keys** (`enterprise.models.ApiKey`, subclasses `OrgScopedModel`):
   - Fields: `name`, `prefix` (first 8 chars, shown in UI), `hashed_key`
     (sha-256 hex of the full token; raw token NEVER stored), `created_by` (FK
     user, nullable), `last_used_at` (nullable), `revoked_at` (nullable),
     `created_at`. `is_active` property = not revoked.
   - `services.create_api_key(org, name, created_by=None)` → returns
     `(ApiKey, raw_token)` where `raw_token` looks like `hull_<43 url-safe chars>`
     and is shown to the user exactly once.
   - `services.verify_api_key(raw_token)` → returns the active `ApiKey` (and
     updates `last_used_at`) or `None`. Constant-time-ish compare via hash lookup.
   - `services.revoke_api_key(api_key)` → sets `revoked_at`.
   - **API-key auth path**: `enterprise/auth.py::resolve_api_key(request)` reads
     `Authorization: Bearer hull_...` (or `X-Api-Key`) and returns the `ApiKey`
     or `None`. Provide a `@api_key_required` decorator for a demo JSON endpoint
     `GET /enterprise/api/whoami/` that returns the org name + key name as JSON
     when a valid key is presented, else 401. (This proves programmatic,
     org-scoped, session-less access end-to-end.)
   - API keys management **view** at `/enterprise/keys/` (owner/admin only):
     list active/revoked keys (prefix + name + last used), create form (shows raw
     token once via a flash/toast), revoke button. Creating/revoking writes an
     audit entry.

5. **Org settings** home at `/enterprise/settings/` (owner/admin to edit; all
   members may view): edit org `name` (slug is immutable — unique contract),
   show org metadata (created date, member count by role), and link out to
   Members (accounts), API Keys, and Audit Log. Editing the name writes an audit
   entry. (MUST NOT modify `accounts/models.py`; only update existing `Org`
   instance fields it already has: `name`.)

6. **Navigation/discoverability without editing base.html:** since `base.html`
   is off-limits, the enterprise pages are reachable via a settings landing page
   linked from a URL we control and cross-linked among the four sub-pages
   (settings ⇄ keys ⇄ audit). (Builder MAY also add a `DesignSync`-style nav only
   if a sanctioned extension point exists; default is in-app cross-links.)

7. **Cross-workstream audit hooks (lightweight, additive):** expose
   `record_audit` / `audit` as the public, documented write path so other
   workstreams (vcs merge, deploys, accounts member changes) can log actions in
   one line. Provide an example call documented in `enterprise/services.py`.
   (Wiring other apps is *their* job; enterprise only ships the API + docs.)

### Scope OUT (explicitly deferred)

- Billing / plans / usage metering (roadmap "billing stub" — not this sprint).
- SSO / SAML / SCIM / external IdP.
- Per-object / per-resource ACLs or custom roles beyond the 4 built-in roles.
- API-key *scopes/permissions* (keys are org-wide read for the demo endpoint;
  fine-grained key scopes are future work).
- A full public REST API surface (only the `whoami` proof endpoint ships).
- Editing/registering global context processors, middleware, or `base.html`
  topbar — anything requiring edits to files owned by others.
- Modifying `accounts/models.py`, `helm/settings.py`, `helm/urls.py`,
  `templates/base.html`, or any other app's files.
- Email delivery of invitations (owned by accounts).
- Retention/export of audit logs (CSV export is a nice-to-have, not required).

---

## 4. Non-negotiables (autonomous loop safety)

- The enterprise app MUST NOT import or alter `deploys.services`,
  `observability.services`, `orchestration.service`, or `agents.services` in a
  way that changes their behavior. Any audit hook is additive and wrapped so a
  failure to log NEVER propagates.
- `record_audit(...)` and `has_role(...)` MUST be safe to call with `org=None`
  and with no `request`/`user`, and MUST NOT raise in that mode.
- All enterprise models keep `org` nullable (inherited from `OrgScopedModel`),
  so loop-time / system writes succeed without an org.
- `python manage.py check` passes; `makemigrations enterprise` produces a clean
  migration. Do NOT run `migrate`.

---

## 5. Machine-checkable rubric (pass/fail)

Each item is a binary assertion an adversarial QA agent can verify. Paths are
relative to repo root. "import-safe" = can be imported in a Django shell after
`django.setup()` without raising.

1. **App exists & configured.** `enterprise/` exists with `__init__.py`,
   `apps.py` (an `AppConfig` named `enterprise`), `models.py`, `services.py`,
   `rbac.py`, `auth.py`, `views.py`, `urls.py` (with `app_name = "enterprise"`),
   and `templates/enterprise/`. CHECK: files exist; `urls.py` defines `app_name`.

2. **Migrations clean.** `python manage.py makemigrations enterprise --check
   --dry-run` reports no missing migrations after the builder commits the
   generated migration (i.e., a migration file exists in
   `enterprise/migrations/` and models match it). CHECK: a non-`__init__`
   migration file exists; `--check --dry-run` exits 0.

3. **System check passes.** `python manage.py check` exits 0 with `enterprise`
   in `INSTALLED_APPS` (integrator wires settings; builder documents the needed
   line). CHECK: exit code 0.

4. **AuditLog is org-scoped.** `enterprise.models.AuditLog` subclasses
   `accounts.models.OrgScopedModel`; has fields `actor`, `action`,
   `target_type`, `target_id`, `target_repr`, `metadata`, `created_at`; `org`
   is nullable. CHECK: `issubclass(AuditLog, OrgScopedModel)` and
   `AuditLog._meta.get_field("org").null is True`.

5. **ApiKey is org-scoped & never stores raw token.** `enterprise.models.ApiKey`
   subclasses `OrgScopedModel`; has `name`, `prefix`, `hashed_key`,
   `revoked_at`; there is **no** field named `key`, `raw_key`, `token`, or
   `secret` that stores the plaintext. CHECK: field set includes the hashed
   field and excludes a plaintext field.

6. **record_audit is loop-safe.** Calling
   `enterprise.services.record_audit("loop.test")` (no org, no request, no
   user) returns without raising and creates an `AuditLog` row with
   `actor == "system"` (or documented default) and `org is None`. CHECK: row
   created, no exception.

7. **record_audit writes the org from a request.** Given a fake request with
   `.org` set and `.user` authenticated,
   `record_audit("x.y", request=request, target=obj)` creates a row with that
   org and `actor` derived from the user. CHECK: row's `org` matches
   `request.org`.

8. **record_audit never raises on bad input.** `record_audit(None)` or
   `record_audit("a", target=object())` does not raise (returns row or `None`).
   CHECK: no exception.

9. **RBAC ranking correct.** `enterprise.rbac.ROLE_RANK` (or equivalent) orders
   `viewer < member < admin < owner`. CHECK:
   rank("owner") > rank("admin") > rank("member") > rank("viewer").

10. **has_role fails open with no user/org.** For a request with no
    authenticated user (or `request.org is None`), `has_role(request, "admin")`
    returns `True` (does not block internal/loop calls). CHECK: returns truthy.

11. **role_required blocks under-privileged users.** A logged-in user whose
    membership role is `viewer` requesting a view wrapped in
    `role_required("admin")` receives **HTTP 403**; a user with role `owner`
    receives **HTTP 200**. CHECK: status codes via test client.

12. **API key create returns a one-time raw token, stores only a hash.**
    `create_api_key(org, "ci")` returns `(ApiKey, raw)` where `raw` starts with
    `hull_`, `len(raw) > 20`, the saved `ApiKey.hashed_key ==
    sha256(raw).hexdigest()`, and `raw` is not equal to any stored field.
    CHECK: prefix + hash relationship hold.

13. **verify_api_key round-trips and rejects bad/revoked.**
    `verify_api_key(raw)` returns the same key for a valid token; returns
    `None` for a garbage token and for a revoked key (after
    `revoke_api_key`). CHECK: three assertions.

14. **API-key endpoint enforces auth.** `GET /enterprise/api/whoami/` with no
    credential returns **401**; with `Authorization: Bearer <raw>` of a valid
    key returns **200** and JSON containing the org name. CHECK: status codes +
    body.

15. **API-key auth is session-less & org-scoped.** The whoami response derives
    the org from the key (not from any session), proving programmatic
    org-scoped access. CHECK: response org equals the key's org for a request
    with no session cookie.

16. **Settings/keys/audit views are RBAC-gated.** `/enterprise/settings/`,
    `/enterprise/keys/`, `/enterprise/audit/` return 200 for an owner and 403
    (or redirect to login/onboarding) for an out-of-org / anonymous user;
    mutating actions (create/revoke key, edit org name) reject a `viewer` with
    403. CHECK: status codes by role.

17. **Mutations write audit entries.** Creating an API key, revoking a key, and
    editing the org name each create a corresponding `AuditLog` row scoped to
    the acting org (actions e.g. `apikey.created`, `apikey.revoked`,
    `org.updated`). CHECK: row count increases with expected `action` values.

18. **Org-scoping isolation.** `AuditLog.objects.for_org(orgA)` and the audit
    view for a user in `orgA` never return `orgB`'s rows; same for `ApiKey`.
    CHECK: cross-org query returns none of the other org's rows.

19. **Templates extend base & use design system.** Every enterprise template
    starts with `{% extends "base.html" %}` and uses helm.css classes (`card`,
    `btn`, `badge`, `table`/`list-row`, etc.); no new CSS file is added and
    `static/css/helm.css`, `templates/base.html` are unmodified. CHECK: grep
    `extends "base.html"`; git shows those two files unchanged.

20. **Contract files untouched.** `git diff` shows NO changes to
    `accounts/models.py`, `accounts/scoping.py`, `accounts/middleware.py`,
    `helm/settings.py`, `helm/urls.py`, `templates/base.html`,
    `static/css/helm.css`, or any of `deploys/services.py`,
    `observability/services.py`, `orchestration/service.py`,
    `agents/services.py`. CHECK: those paths are absent from the diff.

21. **Loop smoke (regression gate).** With the enterprise app installed,
    importing `deploys.services`, `observability.services`,
    `orchestration.service`, `agents.services` still succeeds and their public
    function signatures are unchanged. CHECK: imports succeed; signatures match
    CONTRACTS.md.

22. **No import-time explosions.** `import enterprise.services`,
    `enterprise.rbac`, `enterprise.auth`, `enterprise.views` after
    `django.setup()` all succeed. CHECK: no exception on import.

---

## 6. Builder ticket list

See structured `tickets` output. Summary:

- ENT-1: Scaffold the `enterprise` app (apps.py, urls, templates dir, AppConfig,
  doc the `INSTALLED_APPS` + root-url line for the integrator).
- ENT-2: `AuditLog` + `ApiKey` models (OrgScopedModel) + admin + migration.
- ENT-3: `services.py` — `record_audit`/`audit`, `create_api_key`,
  `verify_api_key`, `revoke_api_key` (loop-safe, no raises).
- ENT-4: `rbac.py` — `ROLE_RANK`, `has_role`, `role_required` (fail-open) +
  app-local template tag `can`.
- ENT-5: `auth.py` — `resolve_api_key`, `api_key_required`, `whoami` JSON
  endpoint.
- ENT-6: Views + templates — settings, keys (create/revoke), audit log
  (filterable), all RBAC-gated, cross-linked; emit audit + `core.Event` entries.
- ENT-7: Tests under `tests/` covering rubric items 6–18, plus the loop
  regression import test (item 21).
