# PRD — Docker-Compose Deploys + Custom Domains (`deploys/`)

**Section owner:** Deploys PM
**Sprint:** 1 (Build-out — make every section org-scoped, ship features in parallel on top of the accounts tenancy contract)
**Status:** Draft for builders + adversarial QA

---

## 1. Problem

Hull today deploys an environment as a **single subprocess** on an allocated
port, exposed publicly only at the path-based URL `{{HELM_BASE_URL}}/d/<env_pk>/`
via the in-process reverse proxy (`deploys/views.py::proxy`). That is enough for
the autonomous incident→fix demo, but it does not match how real teams ship
production apps:

1. **Complex apps need a stack, not one process.** A real service is
   `web + Postgres + worker + Redis`. There is no way to model or run a
   multi-service app, so anything beyond a toy single-process app cannot deploy.
2. **No per-environment configuration.** There is no place to store env-vars or
   secrets per environment; apps that need `DATABASE_URL`, API keys, etc. cannot
   be configured without editing code.
3. **No real domains.** Apps are only reachable at an opaque `/d/<pk>/` *path*.
   Enterprise users expect a **real hostname per project/env**
   (`shop.acme.com`), with automatic TLS.
4. **No tenancy.** `Environment` and `Deployment` are global rows with no `org`
   FK, so two orgs see each other's deployments — violating the Sprint-1
   multitenancy contract.
5. **History/rollback is implicit.** Deployments are listed, but there is no
   first-class "roll back to deployment N" action with a guaranteed, recorded
   outcome.

We must add all of this **additively**, without ever breaking the autonomous
loop (`deploys.services.deploy(environment, ...)` is called with no request and
no org).

---

## 2. Goal & non-negotiables

Ship, this sprint, the highest-impact slice of compose-stack deploys, per-env
config/secrets, custom domains with on-demand TLS, and history/rollback — all
**org-scoped** — while keeping the legacy subprocess runtime and the autonomous
incident→fix loop fully working as a fallback.

**Hard rules (inherited):**
- Never break the autonomous loop. `deploys.services.deploy / stop / restart /
  health_check / allocate_port` keep their signatures; `org` defaults to `None`
  so service calls without a request still work.
- Import the tenancy contract from `accounts/`; **do not** modify
  `accounts/models.py`. Existing models get `org` by subclassing
  `OrgScopedModel`; new models subclass `OrgScopedModel`. `org` stays nullable.
- Additive only + fallbacks: a project with no compose config still deploys via
  the existing subprocess runtime. A deployment with no custom domain still
  serves at `/d/<env_pk>/`.
- Extend `base.html` via `{% extends %}`; match `static/css/helm.css` design
  system. App templates live in `deploys/templates/deploys/`.
- Do not edit `helm/urls.py`, `helm/settings.py`, `templates/base.html`, or
  another app's files. Do not run `migrate` (only `makemigrations deploys`).
  Smoke-test on ports 8011+, never 8000.

---

## 3. User stories

- **As an operator**, I define an environment as a Docker Compose stack
  (web + Postgres + worker + Redis) so a complex app runs the way it does in
  prod, and I can deploy it with one click.
- **As an operator**, I set per-environment env-vars and secrets (e.g.
  `DATABASE_URL`, `STRIPE_KEY`) in the UI; secrets are write-only/masked and are
  injected into the stack at deploy time, never rendered back in plaintext.
- **As an operator**, I attach a custom hostname (e.g. `shop.acme.com`) to a
  project/environment, and Hull serves it over HTTPS with on-demand TLS, so the
  app is reachable at a real domain — not a `/d/<pk>/` path.
- **As an operator**, I view deploy history for an environment and **roll back**
  to any prior successful deployment in one click, with the rollback recorded as
  a new deployment.
- **As a member of Org A**, I only ever see Org A's environments, deployments,
  env-vars, and domains — never Org B's.
- **As the autonomous loop (no request, no org)**, I keep deploying and
  redeploying environments exactly as before; nothing I rely on changes
  signature or behavior.

---

## 4. Scope

### 4.1 Scope-IN (MVP this sprint)

**A. Org-scoping (foundation for everything below)**
- `Environment` and `Deployment` become org-scoped by subclassing
  `accounts.models.OrgScopedModel` (nullable `org` FK). Existing field names are
  unchanged (contract). `Deployment.org` is denormalized from its environment.
- Request-path views (`deploy_list`, `deploy_rows`, `deploy_detail`, and all new
  views) filter by `request.org` using `accounts.scoping` helpers. The `proxy`
  view and `health_check`/tailer paths remain **unscoped** (they run for the
  autonomous loop / public traffic).
- `deploys.services.deploy(...)` sets the new deployment's `org` from
  `environment.org` (which may be `None`).

**B. Compose-stack runtime (additive second runtime)**
- A `runtime` field on `Environment` selecting `process` (legacy default) or
  `compose`.
- A dependency-free **compose builder** (`deploys/compose/builder.py`,
  no PyYAML) that, for a compose environment, emits a docker-compose file +
  Dockerfile for a four-service stack: `web` (built from repo Dockerfile if
  present, else generated for the detected framework), `db` (postgres),
  `worker` (web image running the worker/run command), `redis`. `web` publishes
  `<host_port>:<container_port>` where `host_port` comes from `allocate_port()`,
  so the existing `/d/<env_pk>/` proxy and `health_check` keep working unchanged.
  `DATABASE_URL` and `REDIS_URL` are injected pointing at the in-stack services.
- `deploys.services.deploy(...)` branches on `environment.runtime`: if
  `compose` **and** Docker is available, run the compose stack; otherwise fall
  back to the existing subprocess runtime (so nothing breaks where Docker is
  absent — e.g. CI / the autonomous loop box). Compose runtime sets the same
  `Deployment` fields (`status`, `health`, `port`, `live_at`, `log_path`,
  `build_log`) so the rest of Hull is unaffected.

**C. Per-env env-vars & secrets**
- New `EnvVar` model (org-scoped): `environment` FK, `key`, `value`,
  `is_secret` bool. Secret values are **masked** in all read responses
  (list/detail/HTMX), shown as e.g. `••••••`. UI to add/edit/delete env-vars per
  environment.
- Env-vars are injected into the deployed app at deploy time: as the child
  process environment in the subprocess runtime, and into the `web`/`worker`
  services (env_file / environment) in the compose runtime.

**D. Custom domains + on-demand TLS**
- New `Domain` model (org-scoped): `environment` FK, `hostname` (unique),
  `status` (pending/active/error), `verified_at`. UI to add/remove a domain on
  an environment.
- The reverse-proxy `proxy` view resolves the target environment **either** by
  `env_pk` (existing `/d/<pk>/` path) **or** by inbound `Host` header matching a
  `Domain.hostname` (host-based routing), so a request to `shop.acme.com/`
  proxies to that env's live deployment.
- A Caddy **on-demand TLS authorization endpoint** at
  `deploys.views.tls_ask(request)` (e.g. `GET /deploys/tls/ask?domain=<host>`)
  that returns HTTP 200 iff `<host>` matches a known active `Domain`, else 404 —
  the contract Caddy's `on_demand_tls { ask <url> }` uses to decide whether to
  issue a certificate. (Caddyfile wiring lives in `deploy/` and is out of this
  app's code-scope, but the ask endpoint and its semantics are in-scope.)

**E. Deploy history + rollback**
- Per-environment history view listing deployments with status/health/commit/age.
- A `rollback(environment, to_deployment)` service + view that deploys the
  `commit_sha`/`source_path` of a prior **successful** deployment as a **new**
  Deployment (history is append-only; we never mutate the old row), emits an
  `Event.log`, and is org-scoped in the request path.

### 4.2 Scope-OUT (explicitly not this sprint)

- Kubernetes / Nomad / swarm; multi-host scheduling; autoscaling.
- DNS record management / domain registrar integration / automatic CNAME setup
  (operator points DNS themselves; Hull only validates + serves + issues TLS).
- Real ACME certificate issuance inside unit tests (we test the **ask** decision
  logic, not Let's Encrypt round-trips).
- Per-service health checks / dependency ordering beyond compose's own
  `depends_on`; blue-green / canary traffic splitting.
- Secret encryption-at-rest with a KMS (secrets are masked in the UI and stored
  in the DB this sprint; KMS is a later enterprise ticket).
- Editing compose YAML by hand in the UI (builder-generated only this sprint).
- Build pipeline / image registry push (compose builds locally on deploy).

---

## 5. Machine-checkable rubric (pass/fail)

Each item is independently verifiable by a script or `python manage.py shell`.
Paths are relative to repo root. "imports cleanly" = `python manage.py check`
exits 0. Org defaults to `None` everywhere unless a request supplies one.

1. **PRD exists.** `docs/prd/deploys.md` exists and contains the headings
   `## 1. Problem`, `## 3. User stories`, `## 4. Scope`, and
   `## 5. Machine-checkable rubric`.

2. **Org-scoped Environment.** `deploys.models.Environment` is a subclass of
   `accounts.models.OrgScopedModel`
   (`issubclass(Environment, OrgScopedModel) is True`) and instances have an
   `org` attribute that is nullable (an `Environment(...)` built without `org`
   has `org_id is None`).

3. **Org-scoped Deployment.** `deploys.models.Deployment` is a subclass of
   `OrgScopedModel`; `org` is nullable.

4. **Field-name contract preserved.** `Environment` still has fields
   `project, name, kind, branch, port, worktree, auto_deploy` and `Deployment`
   still has `environment, commit_sha, commit_message, status, health, port,
   pid, source_path, log_path, build_log, error, created_at, live_at,
   stopped_at`. (No contract field renamed/removed.)

5. **accounts not modified.** `git diff --name-only` (or equivalent) shows **no**
   changes to `accounts/models.py`. `deploys` imports tenancy from `accounts`
   (`grep -q "from accounts" deploys/models.py` and/or `deploys/views.py`).

6. **Migrations present & valid.** `python manage.py makemigrations deploys
   --check --dry-run` reports **no missing migrations** (i.e. a migration adding
   `org`/`runtime`/`EnvVar`/`Domain` has been committed), and
   `python manage.py check` exits 0.

7. **deploy() signature stable.** `inspect.signature(deploys.services.deploy)`
   is `(environment, *, commit_sha=None, source_path=None)` (unchanged), and
   `stop`, `restart`, `health_check`, `allocate_port` still import and keep their
   existing signatures.

8. **deploy() sets org from environment.** Calling `deploys.services.deploy` (or
   inspecting its code) results in the created `Deployment.org_id ==
   environment.org_id` (including `None == None`). Verifiable by code inspection
   + a shell test with a fake/None-org environment.

9. **Runtime selector exists with safe default.** `Environment` has a `runtime`
   field whose choices include `"process"` and `"compose"`, defaulting to
   `"process"`. Existing/legacy environments therefore keep the subprocess
   runtime.

10. **Compose fallback never crashes.** `deploys.services.deploy` for a
    `runtime="compose"` environment, when Docker is **unavailable**, falls back
    to the process runtime (or fails the deployment gracefully with a recorded
    `error`) and **never raises out of** `deploy()` — the function always returns
    a `Deployment`. (Verifiable by forcing the docker-availability check to
    `False` and asserting a `Deployment` is returned, not an exception.)

11. **Compose builder is dependency-free & complete.**
    `deploys/compose/builder.py` exists, imports without requiring PyYAML, and
    exposes a function (e.g. `build_compose(environment, source_path, ...)`)
    that returns a compose spec string containing all four service names:
    `web`, `db`, `redis`, and a worker service, and references `postgres` and
    `redis` images. The `web` service publishes a host port mapping
    (`"<host_port>:<container_port>"`). Verifiable by string assertions on the
    returned spec.

12. **Compose injects DATABASE_URL & REDIS_URL.** The generated compose spec for
    the `web` (and `worker`) service contains `DATABASE_URL` referencing the
    in-stack `db` service and `REDIS_URL` referencing the `redis` service.

13. **EnvVar model exists & org-scoped.** `deploys.models.EnvVar` is an
    `OrgScopedModel` with fields `environment` (FK to Environment), `key`,
    `value`, `is_secret` (BooleanField). A reverse accessor exists from
    Environment (e.g. `environment.env_vars`).

14. **Secrets are masked on read.** There is a method/property/template path
    that returns a masked representation for `is_secret=True` rows (the raw value
    does **not** appear in any list/detail HTTP response body). Verifiable: a GET
    of the env-var management fragment for an env with a secret returns 200 and
    the response body does **not** contain the secret's raw value but **does**
    contain a mask token (e.g. `••` or `*`).

15. **Env-vars injected at deploy.** `deploys.services` reads an environment's
    `EnvVar` rows and injects them into the deployed app (child-process env in
    process runtime; env in compose runtime). Verifiable by code inspection
    (`EnvVar`/`env_vars` referenced in `services.py`) plus a process-runtime
    smoke test where an injected var is visible to the app.

16. **Domain model exists & org-scoped.** `deploys.models.Domain` is an
    `OrgScopedModel` with fields `environment` (FK), `hostname`
    (unique CharField) and a `status` field; reverse accessor from Environment
    (e.g. `environment.domains`).

17. **Host-based proxy routing.** `deploys.views.proxy` (or the request flow it
    sits in) resolves the target environment by matching the inbound `Host`
    header against an active `Domain.hostname` when the path is not the
    `/d/<env_pk>/` form — and still serves `/d/<env_pk>/` for the legacy path.
    Verifiable: a request with `Host: <known-domain>` is routed to that env's
    deployment (or returns the standard "no live deployment" 502 page if none),
    while an unknown host yields a 404/“not found” page — not a 500.

18. **On-demand TLS ask endpoint.** A view `deploys.views.tls_ask` exists and is
    routed (e.g. `deploys/tls/ask`). `GET ...?domain=<known active hostname>`
    returns HTTP **200**; `GET ...?domain=<unknown hostname>` (and missing
    `domain`) returns HTTP **404** (or non-200). No exception is raised.

19. **Rollback service exists & is append-only.** `deploys.services.rollback`
    (or a clearly-named equivalent) takes an environment and a target prior
    deployment, deploys that prior `commit_sha`/source as a **new** Deployment
    (the prior Deployment row's `pk` and `status` are unchanged), and emits a
    `core.models.Event.log` entry. Verifiable by code inspection + a shell test
    asserting a new Deployment row is created referencing the old commit.

20. **Rollback is org-scoped in the request path.** The rollback view rejects /
    cannot act on a deployment belonging to another org (uses
    `accounts.scoping` / `request.org`). Verifiable: the view is decorated with
    `org_required` (or filters by `request.org`) — `grep` for
    `org_required`/`request.org`/`for_org`/`scoped(` in the rollback view.

21. **Deploy list/detail are org-scoped.** `deploy_list`, `deploy_rows`,
    `deploy_detail` filter their querysets by `request.org` (via
    `scoped(...)`/`for_org(request.org)`/`org_required`). Verifiable by `grep`
    in `deploys/views.py` that these views reference org scoping, AND a
    two-org shell/integration check: Org A's deploy list does not include Org
    B's deployments.

22. **Autonomous loop intact (smoke).** `orchestration.service.deploy` and the
    `deploys.services.deploy/stop/restart/health_check` chain still import and
    run for an environment with `org=None` and `runtime="process"`, producing a
    `Deployment` (no NotImplementedError, no org/scoping AttributeError).
    `python manage.py check` exits 0 and the existing deploy smoke path works on
    a port ≥ 8011.

23. **UI extends base + design system.** Every new/edited template under
    `deploys/templates/deploys/` begins with `{% extends "base.html" %}` and uses
    existing helm.css classes (`card`, `btn`, `badge`/`pill`, `list-row`,
    `grid-*`, etc.). No new CSS framework or inline `<style>` blocks (other than
    the pre-existing proxy error page) are introduced.

24. **Env management & domains reachable in UI.** There are routes (in
    `deploys/urls.py`) and templates for: managing an environment's env-vars,
    managing its domains, viewing its deploy history, and triggering rollback.
    Each new page returns 200 for an authenticated user of the owning org.

25. **No 500s on the happy paths.** With a seeded org + project + environment, a
    logged-in user can load: deploy list, deploy detail, env-var management,
    domain management, and deploy-history pages without a 500. (Verifiable via
    Django test client / smoke script.)

---

## 6. Builder notes / sequencing

1. **Ticket DEP-1 first** (org-scoping + migration) — it unblocks everything and
   is the riskiest for the autonomous loop. Land it with the
   `deploy()` `org` defaulting + the `process` runtime default so the loop is
   green before anything else changes.
2. **DEP-2 / DEP-3 / DEP-4 / DEP-5** can fan out in parallel after DEP-1.
3. Keep one migration file (`0002_*`) adding `org` + `runtime` to both models and
   creating `EnvVar` + `Domain`. Coordinate with the integrator (single shared
   migration history) — only `makemigrations deploys`, never `migrate`.
4. Reuse the existing compiled compose builder design (`deploys/compose/`,
   dependency-free, four services) — restore/author the `.py` source to match
   rubric items 11–12.
