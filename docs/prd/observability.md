# PRD — Observability v2 (Datadog-level)

Owner: Observability PM · Sprint 1 (Build-out) · App: `observability/`
Status: ready for build

---

## 1. Problem

Hull already ingests deployment logs, derives a few metrics, and auto-opens
incidents from tracebacks. But the observability surface is a read-only "wall of
recent errors": there is no way to **search/filter logs**, the metrics are raw
single-name counters with no **rollups** (no rate, no percentiles), there is no
**live dashboard** of the golden signals, and there is no concept of a
user-defined **Monitor** that turns a threshold breach into an incident. It is
also **not yet org-scoped** — `LogLine`, `MetricPoint`, and `Incident` have no
`org` field, so a multi-tenant Hull would leak one tenant's telemetry to another.

The autonomous incident → fix loop (the crown jewel) currently fires incidents
only from *parsed tracebacks*. We want to add a second, additive trigger
(threshold Monitors) **without touching** the existing traceback path or any of
the `deploys/observability/orchestration/agents` service contracts.

This sprint makes Observability tenant-safe and brings it to a credible
"Datadog-level" MVP: structured log search/filter, metric rollups (req rate,
error rate, p50/p95/p99, throughput), a live golden-signals dashboard, and
threshold Monitors that open incidents through the existing pipeline.

## 2. Users & user stories

- **As an operator (org member)** I want to search and filter a deployment's logs
  by free text, level, HTTP status, method, and path so I can debug an issue fast.
- **As an operator** I want a live dashboard showing request rate, error rate,
  and p50/p95/p99 latency per deployment so I can see health at a glance, and
  have it refresh without a full page reload (HTMX poll).
- **As an SRE** I want to define a **Monitor** ("error rate > 5% for 5 min",
  "p95 latency > 800ms") that automatically opens an incident when breached, so
  problems that aren't crashes still page us — and feed the autonomous fix loop.
- **As an org admin** I want all logs, metrics, monitors, and incidents scoped to
  my org so I never see another tenant's data.
- **As the autonomous loop (no request/no user)** I must keep ingesting logs,
  recording metrics, and opening traceback incidents exactly as before, even when
  there is no `request.org` (services default `org=None`).

## 3. Scope — IN (this sprint)

1. **Org scoping (additive).** Add a nullable `org` FK to `LogLine`,
   `MetricPoint`, and `Incident` (and the new `Monitor`). Populate it from the
   deployment's project at write time when an org is resolvable; default `None`
   otherwise. All `/obs/` request-path views filter by `request.org`.
2. **Structured log search/filter.** A per-deployment log view with server-side
   filters: free-text `q` (matches message/path), `level`, `status` (exact or
   class like `5xx`), `method`, and `path` substring. HTMX fragment, paginated.
3. **Metric rollups.** A rollup helper that, from raw `MetricPoint`s, computes
   over a time window: request rate (req/min), error rate (% of 5xx),
   throughput (total requests), and latency **p50/p95/p99** from `latency_ms`
   samples. Exposed in the dashboard and reused by Monitors.
4. **Live dashboard.** A golden-signals dashboard per live deployment showing
   req rate, error rate, p50/p95/p99, and throughput as stat tiles + sparklines,
   auto-refreshing via an HTMX poll fragment (no full reload).
5. **Monitors (threshold → incident).** A `Monitor` model (metric, comparator,
   threshold, window, severity, enabled) with list/create/edit/delete UI scoped
   to the org, and an **evaluation function** that, when a monitor is breached,
   opens/updates an incident via the existing `open_or_update_incident` path
   (additive trigger; reuses dedupe + auto-remediation).
6. **Design + integration safety.** All new templates `{% extends "base.html" %}`
   and use `helm.css` classes. Zero changes to `accounts/models.py`,
   `helm/urls.py`, `helm/settings.py`, `templates/base.html`. Existing service
   signatures (`ingest_line`, `record_metric`, `open_or_update_incident`,
   `next_incident_number`, `ingest_line_lookup`) remain byte-compatible.

## 4. Scope — OUT (explicitly deferred)

- Full Datadog query language / log facets / saved views.
- Distributed tracing / spans / flame graphs / APM.
- Cross-deployment aggregate dashboards or custom user-built dashboards.
- Notification channels (Slack/email/PagerDuty integrations) — Monitors only
  open in-product incidents this sprint (Incidents v2 owns routing).
- Long-term metric retention / downsampling / external TSDB.
- Anomaly detection / forecasting / ML monitors.
- Editing the traceback-based incident detection (frozen — additive only).

## 5. Design / technical notes (for the builder)

- **Do NOT modify `accounts/models.py`.** Import the contract:
  `from accounts.models import OrgScopedModel` for the new `Monitor` model.
  For existing models (`LogLine`, `MetricPoint`, `Incident`) add the `org` FK by
  subclassing `OrgScopedModel` **or** adding the field directly per the contract
  (`org = ForeignKey('accounts.Org', null=True, blank=True, on_delete=CASCADE,
  related_name='+')`). Keep it **nullable**.
- **Request paths** use `accounts.scoping` (`org_required` decorator + `scoped()`
  or `Model.objects.for_org(request.org)`). Anonymous / org-less requests must
  not crash.
- **Autonomous loop safety:** `ingest_line`, `record_metric`,
  `open_or_update_incident`, and `evaluate_monitors` run with **no request**.
  They must resolve org from `deployment.environment.project.org` when present,
  else `org=None`, and must never raise if org is unavailable. Wrap org
  resolution in a try/except that falls back to `None`.
- Reuse existing helpers (`_spark`, `_deployment_metric_series`) where possible;
  add a `rollups(deployment, window_minutes=...)` function in
  `observability/services.py` (additive, new name).
- Percentiles computed in Python from `latency_ms` samples (nearest-rank);
  return `None` when there are no samples (template shows `—`).
- Monitor evaluation is invoked **additively**: call `evaluate_monitors(deployment)`
  at the end of `ingest_line` (after metrics are recorded), inside a try/except
  so a monitor bug can never break ingestion. Do not change `ingest_line`'s
  signature or return value.
- New URLs go in `observability/urls.py` only (own the app's `urls.py`).
- Run `python manage.py makemigrations observability` and `python manage.py
  check`. **Do NOT run `migrate`** (integrator owns the shared DB).
- Emit `core.models.Event.log(...)` when a Monitor opens an incident (icon
  `alert`, level `warning`/`error`) so the activity feed narrates it.

## 6. Machine-checkable rubric (pass/fail)

Each item is independently verifiable. "Run check" commands assume repo root with
`.venv` active. All Python snippets use `python manage.py shell -c "..."`.

1. **PRD exists.** `docs/prd/observability.md` exists and contains the sections
   Problem, user stories, scope-in, scope-out, and this rubric.
2. **System check passes.** `python manage.py check` exits 0.
3. **Migration generated, not applied by builder.** `observability/migrations/`
   contains a new migration (≥ `0002`) and `python manage.py makemigrations
   observability --check --dry-run` reports no further changes pending.
4. **`org` field on LogLine.** `LogLine._meta.get_field("org")` exists, is a
   ForeignKey to `accounts.Org`, and `null=True`.
5. **`org` field on MetricPoint.** Same as #4 for `MetricPoint`.
6. **`org` field on Incident.** Same as #4 for `Incident`.
7. **`Monitor` model exists & is org-scoped.** `observability.models.Monitor`
   imports; has fields `deployment` (FK, nullable OK), `metric`, `comparator`,
   `threshold` (float), `window_minutes` (int), `severity`, `enabled` (bool),
   and an `org` FK to `accounts.Org` with `null=True`.
8. **Autonomous ingest still works with no org.** Creating a `Deployment` whose
   project has `org=None`, then calling
   `observability.services.ingest_line(dep, '[13/Jun/2026 16:00:00] "GET / HTTP/1.1" 200 12')`
   returns a `LogLine` without raising; the line is recorded with `org=None`.
9. **Traceback incident path unchanged.** Feeding a multi-line Python traceback
   through `ingest_line` (Traceback header … `ValueError: boom`) opens exactly one
   `Incident` with `error_type="ValueError"`, as before. (Regression guard on the
   crown-jewel detector.)
10. **Service signatures intact.** `inspect.signature` of `ingest_line`,
    `record_metric`, `open_or_update_incident`, `next_incident_number`, and
    `ingest_line_lookup` is unchanged from the contract (params/defaults match);
    `ingest_line(deployment, raw)` still returns a `LogLine`.
11. **`rollups()` helper.** `observability.services.rollups(deployment)` returns a
    dict containing keys `req_rate`, `error_rate`, `throughput`, `p50`, `p95`,
    `p99` (latency values may be `None` when no samples).
12. **Percentiles are correct.** Given recorded `latency_ms` MetricPoints
    `[10,20,30,40,50,60,70,80,90,100]` for a deployment, `rollups(dep)` returns
    `p50≈50` or `60`, `p95≈100` (nearest-rank, monotonic: `p50 ≤ p95 ≤ p99`).
13. **Error rate correct.** With 10 `requests` and 2 `errors` recorded in-window,
    `rollups(dep)["error_rate"]` is ~20 (percent) or ~0.2 (fraction) — documented
    and consistent; non-negative and ≤ 100 (or ≤ 1 for fraction).
14. **Log search filters by level.** `GET /obs/deployment/<pk>/logs/?level=error`
    (authenticated, org member) returns 200 and the rendered fragment contains
    only error-level lines (no `l-info`/`l-warn` rows for non-error logs).
15. **Log search filters by free text.** `GET
    /obs/deployment/<pk>/logs/?q=checkout` returns 200 and every shown line's
    message or path contains `checkout` (case-insensitive).
16. **Log search filters by status class.** `GET
    /obs/deployment/<pk>/logs/?status=5xx` returns 200 and shows only lines with
    `status_code >= 500` (or none).
17. **Dashboard route exists & renders.** A dashboard view is reachable under
    `/obs/` (e.g. `/obs/deployment/<pk>/` or `/obs/dashboard/<pk>/`), returns 200
    for an org member, and the page shows req rate, error rate, and p50/p95/p99
    labels.
18. **Dashboard live-refresh fragment.** There is an HTMX poll fragment endpoint
    (e.g. `/obs/deployment/<pk>/metrics/`) that returns 200 and a partial (not a
    full `<html>` doc), referenced via `hx-get`/`hx-trigger` in the dashboard
    template.
19. **Monitor CRUD UI.** `GET /obs/monitors/` returns 200 for an org member and
    lists monitors; a create endpoint (`/obs/monitors/new/`) exists and POSTing a
    valid monitor creates a `Monitor` row scoped to `request.org`.
20. **Monitor scoping enforced.** A monitor created under org A is **not** listed
    when requesting `/obs/monitors/` as a member of org B (filtered by
    `request.org`). Same isolation holds for the log/dashboard views.
21. **Monitor breach opens an incident additively.** Calling
    `observability.services.evaluate_monitors(dep)` (or the documented eval entry
    point) when a monitor's metric breaches its threshold opens/updates an
    `Incident` via `open_or_update_incident` and emits a `core.Event`
    (icon `alert`). A non-breaching monitor opens nothing.
22. **Monitor eval cannot break ingestion.** With a monitor configured to raise
    (or with monitors present), `ingest_line(dep, raw)` still returns a `LogLine`
    and does not propagate exceptions (monitor eval is wrapped in try/except).
23. **Auth/org gate on views.** Hitting `/obs/`, `/obs/monitors/`, and the log
    view while unauthenticated redirects to login (or onboarding), not a 500.
24. **No forbidden files modified.** `git status --porcelain` shows no changes to
    `accounts/models.py`, `helm/urls.py`, `helm/settings.py`, `templates/base.html`,
    or any app dir other than `observability/` and `docs/`.
25. **Design system respected.** Every new template under
    `observability/templates/` starts with `{% extends "base.html" %}` and uses
    `helm.css` classes (e.g. `card`, `stat`, `badge`, `grid-*`, `logs`); no new
    external CSS/JS frameworks are added.

## 7. Ticket list (for the builder)

See the structured ticket output accompanying this PRD (OBS-1 … OBS-8).
