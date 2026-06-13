# PRD — Observability v2 (Datadog-level)

Owner: Observability PM · App: `observability/`
Status: ready for build (depth sprint — additive on top of the shipped MVP)

---

## 0. Where we are (current state — already shipped & green)

The Sprint-1 build-out for Observability is **already implemented, migrated, and
passing** (`python manage.py check` is clean, `makemigrations observability
--check` reports no changes, the traceback→incident regression tests pass):

- **Org scoping (done).** `LogLine`, `MetricPoint`, `Incident` each carry a
  nullable `org` FK; `Monitor` subclasses `OrgScopedModel`. All `/obs/` request
  views are `@org_required` and filter by `request.org`. Services resolve org
  from `deployment.environment.project.org` with a `None` fallback (loop-safe).
- **Structured log search (done).** `/obs/deployment/<pk>/logs/` with server-side
  `q` / `level` / `status` (exact or `5xx` class) / `method` / `path` filters,
  paginated, HTMX fragment.
- **Metric rollups (done).** `services.rollups(deployment, window_minutes=5)`
  returns `req_rate`, `error_rate` (percent, clamped 0–100), `throughput`, and
  nearest-rank `p50/p95/p99` (None when no samples).
- **Live dashboard (done).** `/obs/deployment/<pk>/` golden-signal stat tiles +
  SVG sparklines, auto-refreshing via the `/obs/deployment/<pk>/metrics/` HTMX
  poll fragment (`hx-trigger="every 5s"`).
- **Monitors → incident (done).** `Monitor` model (metric / comparator /
  threshold / window / severity / enabled) with full CRUD UI; `evaluate_monitors`
  is called additively at the end of `ingest_line` inside a try/except and opens
  an incident through the existing `open_or_update_incident` path (feeds the
  autonomous remediation loop).

So this sprint is **NOT** a rebuild. It is a **depth pass** that closes the gaps
that keep Observability short of a credible Datadog/Grafana feel — done strictly
additively so the crown-jewel incident→fix loop and every frozen service
signature stay byte-compatible.

## 1. Problem (what's still missing)

1. **Monitors are one-shot — they never recover.** A breach opens an incident,
   but when the metric returns to healthy nothing closes it and there is no "OK"
   state. The monitor list shows a static `enabled/disabled` pill, never the live
   **OK / Alerting** status. Operators can't trust monitors that don't clear.
2. **No time-window control on the dashboard.** `window_minutes` is hard-coded to
   5 everywhere; the metrics fragment ignores any window param. You can't look at
   1m / 15m / 1h, which is table stakes for a metrics UI.
3. **No org-level fleet view.** The overview is a wall of per-deployment cards;
   there is no single aggregated "is my org healthy right now?" summary
   (total req rate, total errors, worst p95, count of firing monitors).
4. **Monitors can't be muted.** During a known-bad deploy or maintenance there's
   no way to snooze a monitor without deleting it, so it spams the loop.
5. **Thin test coverage on the new surface.** Only the legacy ingestion/traceback
   path is tested; rollups, percentiles, monitor breach/recovery, and org
   isolation have no regression guard.

## 2. Users & user stories

- **As an SRE** I want a monitor to **auto-resolve** its incident when the metric
  recovers (and to show a live **OK / Alerting** status) so I can trust it and so
  recovered alerts stop feeding the fix loop.
- **As an operator** I want to switch the dashboard between **1m / 5m / 15m / 60m**
  windows so I can zoom from "right now" to "last hour" without leaving the page.
- **As an org admin** I want a **fleet summary** at `/obs/` — total request rate,
  total errors, worst p95, firing-monitor count across all my org's live
  deployments — so I can see overall health at a glance, scoped to my org only.
- **As an on-call engineer** I want to **mute/snooze a monitor** for N minutes
  during a known issue so it stops paging, then auto-un-mute.
- **As the autonomous loop (no request/no user)** I must keep ingesting,
  recording metrics, and opening traceback incidents exactly as today; monitor
  recovery/auto-resolve must NEVER touch traceback-based incidents and must never
  raise into `ingest_line`.

## 3. Scope — IN (this sprint)

1. **Monitor recovery + auto-resolve (additive).** Give `Monitor` a derived live
   status (OK / Alerting / Muted). When `evaluate_monitors` runs and a monitor
   that previously opened an incident is now **back inside threshold for a full
   evaluation**, auto-resolve *that monitor's* open incident (set
   `status=resolved`, `resolved_at`, emit a `core.Event` icon `check`). It must
   only ever resolve incidents whose `error_type == "MonitorBreach"` and whose
   signature matches that monitor — never a traceback incident. All wrapped so it
   cannot break ingestion.
2. **Monitor mute/snooze.** Add a nullable `muted_until` datetime to `Monitor`. A
   muted monitor is skipped by `evaluate_monitors` (opens nothing). UI: a
   "Mute 30m / 2h" action on the monitor list + a visible **Muted** badge; mute
   clears automatically once `muted_until` passes. Live status pill on the list:
   **OK** (green) / **Alerting** (red) / **Muted** (grey) / **Disabled**.
3. **Dashboard time-window selector.** Add a window control (1 / 5 / 15 / 60 min)
   to the dashboard; the `window` query param flows through the dashboard view
   and the `/obs/deployment/<pk>/metrics/` poll fragment so rollups recompute for
   the chosen window. Default stays 5 (backward compatible).
4. **Org fleet summary.** Add an aggregate summary block to `/obs/` (or a new
   `/obs/summary/` fragment) computing, across the org's live deployments: total
   req rate, total throughput, total 5xx, worst p95, and counts of
   firing/alerting monitors and open incidents — strictly `request.org`-scoped.
5. **Regression tests.** Add `observability/tests.py` coverage for: rollups
   percentile correctness + error-rate math; monitor breach opens exactly one
   incident; monitor recovery auto-resolves *only* its own MonitorBreach
   incident (and leaves a traceback incident untouched); muted monitor opens
   nothing; org isolation of monitors/logs.
6. **Design + integration safety.** All new/changed templates `{% extends
   "base.html" %}` and use `helm.css` classes. Zero changes to
   `accounts/models.py`, `helm/urls.py`, `helm/settings.py`, `templates/base.html`,
   or any app dir other than `observability/` and `docs/`. Frozen service
   signatures (`ingest_line`, `record_metric`, `open_or_update_incident`,
   `next_incident_number`, `ingest_line_lookup`, `rollups`, `evaluate_monitors`)
   stay call-compatible; `ingest_line(deployment, raw)` still returns a `LogLine`.

## 4. Scope — OUT (explicitly deferred)

- Full Datadog query language / log facets / saved views / custom user-built
  dashboards.
- Distributed tracing / spans / flame graphs / APM.
- Notification channels (Slack/email/PagerDuty) — Monitors still only open
  in-product incidents; routing/paging is owned by Incidents v2 (`oncall/`).
- Long-term metric retention / downsampling / external TSDB; anomaly detection /
  forecasting / ML monitors.
- Editing the traceback-based incident detector (frozen — additive only).
- Changing how orchestration/oncall resolve *traceback* incidents.

## 5. Design / technical notes (for the builder)

- **Do NOT modify `accounts/models.py`.** `Monitor` already subclasses
  `OrgScopedModel`. Add `muted_until` (and any derived helpers) to `Monitor`
  only. Run `python manage.py makemigrations observability`; **do NOT** run
  `migrate` (integrator owns the shared DB). Keep `org` nullable.
- **Auto-resolve must be surgical.** Only resolve an `Incident` where
  `error_type == "MonitorBreach"` AND its `signature` equals the signature this
  monitor would produce (derive it the same way `open_or_update_incident` does:
  signature of `error_type:error_message` where `error_message` is the stable
  `monitor:<pk> …` string already emitted by `evaluate_monitors`). NEVER touch
  incidents with a `suspect_file` / traceback. Add a regression test proving a
  traceback incident is left firing when a monitor recovers.
- **Loop safety (hard rule).** Recovery/auto-resolve and mute logic run inside
  `evaluate_monitors`, which `ingest_line` already calls wrapped in try/except.
  Keep every new branch defensive (per-monitor try/except) so one bad monitor
  can't abort the pass, and never change `ingest_line`'s signature or return
  value. `evaluate_monitors(deployment)` must remain callable and return a list.
- **Status is derived, not a stored column** (avoids migrations churn and stale
  state): `Monitor.live_status(deployment=None)` → `"muted"` if
  `muted_until and muted_until > now`, else `"disabled"` if not `enabled`, else
  `"alerting"` if an unresolved MonitorBreach incident matches its signature,
  else `"ok"`. Surface it on the list template as a pill.
- **Window plumbing.** Read `window` from `request.GET`, clamp to one of
  `{1,5,15,60}` (default 5), pass to `rollups(...)`, and reflect it in the
  fragment's `hx-get` URL so the poll preserves the selected window.
- **Fleet summary** must reuse `rollups()` per live deployment and the existing
  `_org_deployments(request)` / `_org_incidents(request)` helpers; do not add a
  new cross-org query. Empty org → zeros, never a crash.
- New URLs go in `observability/urls.py` only. Emit `core.models.Event.log(...)`
  on monitor auto-resolve (icon `check`, level `success`) and on mute (icon
  `alert`, level `info`) so the activity feed narrates it.
- Match `static/css/helm.css` (`card`, `stat`, `badge`, `pill`, `grid-*`,
  `logs`, `btn`); no new CSS/JS frameworks; minimal vanilla JS / HTMX only.

## 6. Machine-checkable rubric (pass/fail)

Each item is independently verifiable. Commands assume repo root with `.venv`
active; Python snippets use `python manage.py shell -c "..."`.

1. **PRD exists & is complete.** `docs/prd/observability.md` exists and contains
   Problem, user stories, scope-in, scope-out, current-state, and this numbered
   rubric.
2. **System check passes.** `python manage.py check` exits 0.
3. **Migration generated, not applied by builder.** `observability/migrations/`
   contains a new migration (≥ `0003`) and `python manage.py makemigrations
   observability --check --dry-run` reports **no further** changes pending.
4. **`muted_until` field added.** `observability.models.Monitor._meta.get_field(
   "muted_until")` exists, is a `DateTimeField`, and is nullable (`null=True`).
5. **Crown-jewel regression — traceback incident unchanged.** Feeding the 8-line
   `ZeroDivisionError` traceback (see existing `tests.py`) through `ingest_line`
   still opens exactly one `Incident` with `error_type="ZeroDivisionError"` and
   `suspect_file="shop/cart.py"`, `suspect_line=88`. (Existing tests still pass.)
6. **Frozen signatures intact.** `inspect.signature` of `ingest_line`,
   `record_metric`, `open_or_update_incident`, `next_incident_number`,
   `ingest_line_lookup`, `rollups`, and `evaluate_monitors` is unchanged
   (params/defaults match prior contract); `ingest_line(deployment, raw)` returns
   a `LogLine`; `evaluate_monitors(deployment)` returns a `list`.
7. **Ingest still loop-safe with no org.** With a project whose `org=None`,
   `ingest_line(dep, '[13/Jun/2026 16:00:00] "GET / HTTP/1.1" 200 12')` returns a
   `LogLine` without raising and stores it with `org=None`.
8. **`rollups` keys + percentile monotonicity.** With `latency_ms` points
   `[10,20,…,100]` recorded in-window, `rollups(dep)` returns a dict with keys
   `req_rate, error_rate, throughput, p50, p95, p99` and `p50 ≤ p95 ≤ p99` with
   `p95 ≈ 100` (nearest-rank).
9. **Error-rate math.** With 10 `requests` and 2 `errors` in-window,
   `rollups(dep)["error_rate"]` is ~20 (percent), non-negative and ≤ 100.
10. **Window param honored.** `rollups(dep, window_minutes=1)` and
    `rollups(dep, window_minutes=60)` both return valid dicts; the dashboard view
    `GET /obs/deployment/<pk>/?window=15` returns 200 and the metrics fragment
    `GET /obs/deployment/<pk>/metrics/?window=15` returns 200 and its `hx-get`
    URL carries `window=15` (poll preserves the window).
11. **Window clamped/safe.** A bogus window (`?window=abc` or `?window=9999`)
    does not 500; the view falls back to a valid window from `{1,5,15,60}`.
12. **`Monitor.live_status` exists.** A `Monitor` instance exposes a
    `live_status` method/property returning one of
    `{"ok","alerting","muted","disabled"}`; a disabled monitor → `"disabled"`,
    a monitor with `muted_until` in the future → `"muted"`.
13. **Monitor list shows live status pill.** `GET /obs/monitors/` (org member)
    returns 200 and the rendered HTML contains a status pill/badge reflecting
    OK / Alerting / Muted / Disabled (not just the old enabled/disabled text).
14. **Mute action works + scoped.** A POST mute endpoint (e.g.
    `/obs/monitors/<pk>/mute/`) sets `muted_until` to a future datetime for a
    monitor in `request.org`; afterwards `live_status == "muted"`. Muting a
    monitor that belongs to another org 404s.
15. **Muted monitor opens nothing.** A monitor whose threshold is breached but
    with `muted_until` in the future opens **no** incident when
    `evaluate_monitors(dep)` runs.
16. **Monitor breach opens exactly one incident.** A non-muted, enabled monitor
    whose metric breaches threshold opens/updates exactly one `Incident` via
    `open_or_update_incident` (error_type `"MonitorBreach"`) and emits a
    `core.Event` (icon `alert`); calling `evaluate_monitors` again while still
    breached does not create a second incident (dedupe holds).
17. **Monitor auto-resolves on recovery.** After a monitor has opened a
    MonitorBreach incident, when the metric returns within threshold and
    `evaluate_monitors(dep)` runs, that monitor's incident becomes
    `status="resolved"` with `resolved_at` set, and a `core.Event` (icon `check`,
    level `success`) is emitted.
18. **Auto-resolve is surgical (crown-jewel guard).** If a deployment has BOTH a
    firing traceback incident (e.g. `ZeroDivisionError`) and a recovered monitor,
    running `evaluate_monitors(dep)` resolves only the `MonitorBreach` incident;
    the traceback incident remains unresolved (`status != "resolved"`).
19. **Auto-resolve cannot break ingestion.** With monitors present (including a
    recovering one), `ingest_line(dep, raw)` still returns a `LogLine` and
    propagates no exception (monitor eval remains fully try/except-wrapped).
20. **Fleet summary renders & is scoped.** `GET /obs/` (org member) returns 200
    and shows an aggregate summary (total req rate / total errors / worst p95 /
    firing-monitor or open-incident count) across the org's live deployments; an
    org with no deployments renders zeros without a 500.
21. **Org isolation holds.** A `Monitor` created under org A is **not** listed at
    `/obs/monitors/` for a member of org B, and org B cannot mute/edit/delete it
    (404). Logs/dashboard for a deployment in org A 404 for org B.
22. **Auth/org gate.** Hitting `/obs/`, `/obs/monitors/`, the dashboard, and the
    log view while unauthenticated redirects to login/onboarding (not a 500).
23. **New tests pass.** `python manage.py test observability` exits 0 and includes
    new tests covering rollups percentiles, error-rate, monitor breach,
    monitor recovery auto-resolve (incl. the traceback-untouched guard), and
    muted-monitor-opens-nothing.
24. **No forbidden files modified.** `git status --porcelain` shows changes only
    under `observability/` and `docs/`; no diff to `accounts/models.py`,
    `helm/urls.py`, `helm/settings.py`, `templates/base.html`, or any other app.
25. **Design system respected.** Every new/changed template under
    `observability/templates/` starts with `{% extends "base.html" %}` and uses
    `helm.css` classes (`card`, `stat`, `badge`, `pill`, `grid-*`, `logs`,
    `btn`); no new external CSS/JS frameworks are added.

## 7. Ticket list (for the builder)

See the structured ticket output accompanying this PRD (OBS-9 … OBS-14). They
build strictly on the shipped MVP and are ordered so the crown-jewel-adjacent
work (monitor recovery) lands behind its regression guard.
