# Observability backlog (`observability/`)

PM-owned build backlog toward the ROADMAP "Datadog-level" bar: structured log
search/filter, golden-signal metrics (req rate, error rate, p50/p95/p99), live
dashboards, monitors/alerts, per-deployment health — all org-scoped, with the
autonomous incident→fix loop kept intact (additive, nullable `org`, frozen
service signatures).

Reconciled against the code on 2026-06-13. Done tickets carry `(done: …)`
evidence and must not be rebuilt. Open tickets are reprioritized most-valuable
first.

## Done (shipped MVP + depth pass — reconciled against current code)

- [x] OBS-2: Log ingestion + traceback→Incident detector — `ingest_line` parses
  Django/gunicorn request lines, assembles multi-line tracebacks via a locked
  per-deployment buffer, extracts error_type/message + deepest in-source frame,
  opens/updates an Incident (acceptance: 8-line ZeroDivisionError opens one
  incident with suspect_file/line)
  (done: `services.ingest_line` + `_finalize_traceback`; `tests.py::test_assembles_traceback_and_opens_incident`).
- [x] OBS-3: Metric recording + golden-signal rollups — `record_metric` plus
  `rollups(deployment, window_minutes=5)` returning req_rate, error_rate
  (percent, clamped 0–100), throughput, nearest-rank p50/p95/p99
  (acceptance: keys present, p50≤p95≤p99, error-rate math correct)
  (done: `services.rollups` + `_percentile`; `tests.py::test_percentile_keys_and_monotonicity`, `test_error_rate_math`).
- [x] OBS-4: Structured log search/filter UI — `/obs/deployment/<pk>/logs/` with
  server-side q/level/status(5xx class)/method/path filters, paginated, HTMX
  fragment, org-scoped (acceptance: filters apply, fragment polls)
  (done: `views.deployment_logs` + `_filter_logs`; templates `logs.html`/`_logs.html`).
- [x] OBS-5: Live golden-signal dashboard — `/obs/deployment/<pk>/` stat tiles +
  SVG sparklines, auto-refresh via `/metrics/` HTMX poll fragment
  (acceptance: dashboard 200, fragment 200)
  (done: `views.deployment_dashboard`/`deployment_metrics`; templates `dashboard.html`/`_metrics.html`).
- [x] OBS-5b: Dashboard time-window selector (1/5/15/60m) — `window` param flows
  through dashboard + metrics fragment; bogus values clamp, never 500; default 5
  (acceptance: `?window=15` 200, `?window=abc` no 500)
  (done: `views._clamp_window` + `_ALLOWED_WINDOWS`; `tests.py::test_window_param_views`).
- [x] OBS-6: Monitors CRUD — `Monitor` model (metric/comparator/threshold/window/
  severity/enabled) with full new/edit/delete UI, org-scoped
  (acceptance: create/edit/delete works, org-isolated)
  (done: `views.monitor_*`; templates `monitor_list/form/confirm_delete.html`).
- [x] OBS-7: Monitor breach → Incident — `evaluate_monitors` computes the metric
  via rollups, on breach opens exactly one MonitorBreach incident (dedup by
  stable monitor-identity signature) + emits `core.Event` icon `alert`; called
  additively from `ingest_line` inside try/except (acceptance: one incident,
  dedupe holds, ingestion never breaks)
  (done: `services.evaluate_monitors`; `tests.py::test_breach_opens_exactly_one_incident_and_dedupes`).
- [x] OBS-7b: Monitor recovery + auto-resolve — recovered monitor surgically
  resolves ONLY its own MonitorBreach incident (never a traceback incident),
  sets resolved_at + emits `core.Event` icon `check` (acceptance: own incident
  resolves, traceback incident untouched, ingest stays safe)
  (done: `services._recover_monitor`; `tests.py::test_recovery_auto_resolves_only_its_own_incident`).
- [x] OBS-7c: Monitor mute/snooze + live status — nullable `muted_until`; muted
  monitor opens/recovers nothing and auto-expires; `Monitor.live_status()`
  derives OK/Alerting/Muted/Disabled with a status pill on the list; POST
  `/obs/monitors/<pk>/mute/` org-scoped (acceptance: muted opens nothing, pill
  shows, cross-org mute 404s)
  (done: `models.Monitor.muted_until`/`live_status`, `views.monitor_mute`; migration `0003`; `tests.py::test_muted_monitor_opens_nothing`, `test_owner_can_mute`).
- [x] OBS-8: Org scoping + auth gate — `LogLine`/`MetricPoint`/`Incident` carry a
  nullable `org` FK; `Monitor` subclasses `OrgScopedModel`; all `/obs/` views are
  `@org_required` and filter by `request.org`; services resolve org from the
  deployment with a `None` fallback (loop-safe) (acceptance: cross-org 404s,
  unauth redirects, orgless ingest returns LogLine with org=None)
  (done: `views._org_deployments/_org_incidents`, `services._resolve_org`; migration `0002`; `tests.py::test_other_org_dashboard_and_logs_404`, `test_unauthenticated_redirects`, `test_ingest_orgless_returns_logline_org_none`).
- [x] OBS-8b: Org fleet summary at `/obs/` — aggregate total req rate, total
  throughput, total errors, worst p95, firing-monitor + open-incident counts
  across the org's live deployments, request.org-scoped, empty→zeros
  (acceptance: summary renders 200, empty org no 500)
  (done: `views.overview` summary block; `tests.py::test_overview_fleet_summary_scoped`, `test_empty_org_overview_no_500`).
- [x] OBS-8c: Incident detail + manual remediate + status poll — `/obs/incidents/`,
  detail page with timeline events, `incident_status` HTMX poll, manual
  `incident_remediate` dispatch (acceptance: detail 200, remediate dispatches)
  (done: `views.incident_detail/incident_status/incident_remediate`; templates `incident_detail.html`/`_incident_status.html`).

## Open (reprioritized — most valuable first)

- [x] OBS-1: Manual "Declare incident" — button + form on `/obs/incidents/`
  (fields: project, severity, title, message) creating an Incident
  (status=firing, org=request.org) via a NEW
  `observability.services.create_manual_incident(project, severity, title,
  message, declared_by=None)` that reuses `next_incident_number`, emits the
  pagerduty-style `core.Event`, and fires the on-call hook
  (`oncall.services.loop.on_incident_opened`) exactly like auto-detected
  incidents — so it shows a timeline and (if auto-remediate is on) can kick the
  loop. Add nullable `Incident.source` (auto/manual) + nullable `declared_by`
  via an additive migration; do NOT touch `ingest_line`/`open_or_update_incident`
  signatures the loop depends on (acceptance: declaring an incident creates one
  that appears in `/obs/incidents/` and its detail page with a timeline entry;
  org-scoped; loop contracts unchanged; `manage.py check` clean).
  (done: `services.create_manual_incident` reuses `next_incident_number` + emits
  pagerduty Event + fires `oncall.loop.on_incident_opened` + honours
  `HELM_AUTO_REMEDIATE`; `views.incident_declare`/`_org_projects` org-scoped 404;
  `Incident.source`/`declared_by` via additive migration `0004`; declare form on
  `incident_list.html`; `ingest_line`/`open_or_update_incident` untouched.)

- [x] OBS-9: Inline monitor enable/disable + mute presets on the list — a POST
  toggle (`/obs/monitors/<pk>/toggle/`) to flip `enabled` and one-click
  "Mute 30m / 2h" + "Unmute" buttons rendered against the live-status pill,
  without opening the edit form; org-scoped, narrated via `core.Event`
  (acceptance: toggling flips `enabled` and the pill updates; mute presets POST
  to `monitor_mute`; cross-org 404; no change to `evaluate_monitors`).
  (done: `views.monitor_toggle` flips `enabled` + Event, `for_org` cross-org 404;
  inline Enable/Disable + existing Mute 30m/2h/Unmute presets on
  `monitor_list.html`; `evaluate_monitors` untouched.)

- [x] OBS-10: Incident ack/resolve from the UI — POST actions on incident detail
  (and inline on `/obs/incidents/`) to acknowledge (status=acknowledged,
  acknowledged_at) and manually resolve (status=resolved, resolved_at), each
  emitting a timeline `core.Event`; org-scoped; must NOT auto-resolve via the
  monitor path (acceptance: ack sets acknowledged_at + event; resolve sets
  resolved_at + event; both visible in the timeline; cross-org 404).
  (done: `views.incident_ack`/`incident_resolve` set acknowledged_at/resolved_at
  + emit `INC-<n>` Events the detail timeline filter picks up; `_next_url`
  supports inline-on-list `?next=`; `_org_incidents` cross-org 404; never uses
  `_recover_monitor`. Buttons on `incident_detail.html` + inline on
  `incident_list.html`.)

- [x] OBS-11: Saved log views / quick-filter chips — persist a few named filter
  presets (e.g. "5xx only", "errors", "slow >500ms") as clickable chips on the
  log search page that set the q/level/status/path params; reuse `_filter_logs`
  (acceptance: clicking a chip applies the matching filter and the URL carries
  the params; no new heavy JS — HTMX/links only).
  (done: plain-link chips on `logs.html` — All / 5xx only / 4xx / Errors /
  Warnings / Tracebacks — each setting status/level/q GET params consumed by the
  existing `_filter_logs`; no new JS.)

- [x] OBS-12: Per-monitor incident history panel — on the monitor list (or a
  `/obs/monitors/<pk>/` detail), show that monitor's recent MonitorBreach
  incidents (open + resolved) by `breach_signature`, with timestamps and current
  status, so an operator can see flap history (acceptance: panel lists this
  monitor's MonitorBreach incidents only, org-scoped, never shows traceback
  incidents).
  (done: `views.monitor_detail` at `/obs/monitors/<pk>/` filters
  `error_type='MonitorBreach', signature=monitor.breach_signature()` only;
  `for_org` 404; `monitor_detail.html` breach-history table; monitor name on the
  list links to it.)

- [x] OBS-13: Log export (CSV) for a filtered view — `/obs/deployment/<pk>/logs/export/`
  streaming the currently-filtered `_filter_logs` queryset as CSV
  (ts, level, method, path, status_code, latency_ms, message), org-scoped + capped
  row count (acceptance: export returns text/csv 200 honoring the same q/level/
  status/method/path params; cross-org 404).
  (done: `views.deployment_logs_export` StreamingHttpResponse text/csv via
  `_filter_logs`, capped at `_LOG_EXPORT_CAP`=10000 rows, `_get_org_deployment`
  404; "Export CSV" button on `logs.html` carries the active querystring.)

- [x] OBS-14: Dashboard p95/error-rate threshold banner — when a live
  deployment's current `rollups` p95 or error_rate exceeds a soft default (or any
  matching enabled monitor's threshold), show a coloured health banner on the
  deployment dashboard reusing existing `helm.css` badge/stat classes; purely
  presentational, no new incidents (acceptance: banner appears red when
  error_rate/p95 is over threshold, normal otherwise; no change to services).
  (done: `views._health_banner` compares current `rollups` error_rate/p95 vs the
  tightest matching enabled-monitor threshold or soft defaults
  `_SOFT_ERROR_RATE`=5%/`_SOFT_P95_MS`=1000; rendered in `_metrics.html` so it
  refreshes with the poll; reads services only, opens nothing.)
