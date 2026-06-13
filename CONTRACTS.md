# Helm — Build Contracts (read this first)

**Helm** is an all-in-one autonomous software operating system: version control,
CI/CD, deployments, observability, and incident response — operated by a crew of
Claude agents. One control plane (this Django app) that mashes together GitHub +
Vercel + PagerDuty + Datadog, run autonomously.

**The money-shot demo:** a production app throws an error → Helm detects it →
opens an incident (PagerDuty-style) → spawns a Claude agent in an isolated git
worktree → the agent fixes the root cause + adds a regression test → opens a PR
in Helm's own PR/diff UI → CI runs → green → merge → redeploy. Autonomously.

## Stack & conventions
- Django 5.1, SQLite, server-rendered templates + **HTMX** (CDN already in base.html).
  **No heavy JS frameworks.** Minimal vanilla JS only.
- Venv: `source .venv/bin/activate`. Run from repo root.
- 7 apps: `core` (done — base UI, dashboard, Event feed), `projects`, `deploys`,
  `agents`, `vcs`, `observability`, `orchestration`.
- Every page `{% extends "base.html" %}` and uses the design-system classes in
  `static/css/helm.css` (cards, badges, btn, list-row, logs, diff, feed, stat,
  grid-2/3/4). Match the existing dark premium look. Load `{% load helm_extras %}`
  for `feed_icon`, `status_badge`, `pct` filters.
- App templates go in `<app>/templates/<app>/...`. Each app owns its `urls.py`
  (already stubbed with `app_name`). **Never edit `helm/urls.py`, `helm/settings.py`,
  `templates/base.html`, or another app's files.**
- Use `core.models.Event.log(verb, project=, actor=, level=, icon=, url=)` to emit
  activity-feed entries at every meaningful step — this is how the demo narrates
  itself. levels: info/success/warning/error. icons: rocket, check, x, deploy,
  agent, pr, incident, fix, alert, test, git, merge, log.
- **Do NOT run `python manage.py migrate`** (single shared sqlite — integrator
  runs it). You MAY run `python manage.py makemigrations <yourapp>`. Validate with
  `python manage.py check`. Do NOT bind port 8000 (integrator owns it) — use 8011+
  for any smoke test and kill it after.

## Settings you can rely on (helm/settings.py)
`HELM_DATA_DIR`, `HELM_REPOS_DIR`, `HELM_WORKTREES_DIR`, `HELM_LOGS_DIR` (all exist
on disk), `HELM_PORT_START`=9101 / `HELM_PORT_END`=9199, `HELM_BASE_URL`,
`HELM_CLAUDE_BIN`="claude", `HELM_AGENT_MODEL`="claude-opus-4-8",
`HELM_USE_TEMPORAL`, `HELM_TEMPORAL_HOST`, `HELM_TEMPORAL_TASK_QUEUE`="helm".

## Data model (already defined & migrated — DO NOT change field names)
- `projects.Project`: name, slug, repo_url, local_path, default_branch, framework,
  run_command, install_command, app_subdir, status(importing/ready/failed),
  description, import_log. `.environments`, `.worktrees`, `.agent_runs`,
  `.pull_requests`, `.incidents`, `.events`.
- `deploys.Environment`: project, name, kind(staging/prod/preview), branch, port,
  worktree(FK nullable), auto_deploy. `.current_deployment`, `.public_url`
  (=`{HELM_BASE_URL}/d/<pk>/`), `.deployments`.
- `deploys.Deployment`: environment, commit_sha, commit_message,
  status(queued/building/live/failed/stopped), health(unknown/healthy/unhealthy),
  port, pid, source_path, log_path, build_log, error, created_at/live_at/stopped_at.
  `.project`, `.public_url`, `.is_running`, `.logs`, `.metrics`, `.incidents`.
- `agents.Worktree`: project, name, branch, base_branch, base_commit, path,
  status(creating/active/merged/archived). `.agent_runs`, `.pull_requests`.
- `agents.AgentRun`: project, worktree, kind(feature/remediation/ci/review/chore),
  title, prompt, status(queued/running/done/failed), output(streamed text),
  result_summary, num_turns, cost_usd, error, pull_request(FK), incident(FK),
  created_at/started_at/ended_at. `.append_output(text)`.
- `vcs.PullRequest`: project, worktree, number, title, description, base_branch,
  head_branch, head_commit, status(open/merged/closed),
  ci_status(none/pending/running/passed/failed), diff, files_changed, additions,
  deletions, author. `.get_absolute_url()` -> /vcs/pr/<pk>/. `.agent_runs`, `.incidents`.
- `observability.LogLine`: deployment, ts, level(debug/info/warning/error),
  message, method, path, status_code, latency_ms.
- `observability.MetricPoint`: deployment, ts, name, value.
- `observability.Incident`: project, deployment, number, title,
  severity(sev1/sev2/sev3), status(firing/acknowledged/remediating/resolved),
  signature, error_type, error_message, traceback, suspect_file, suspect_line,
  occurrences, remediation_pr(FK). `.get_absolute_url()` -> /obs/incidents/<pk>/.

## Service contracts (implement the stubs; keep signatures stable)
These already exist as stub files with detailed docstrings — read them:
- `projects/services.py`: `detect_runtime(path)`, `import_project(name, repo_url, description="")`
- `deploys/services.py`: `allocate_port()`, `deploy(environment, commit_sha=None, source_path=None)`,
  `stop(deployment)`, `restart(deployment)`, `health_check(deployment)`
- `agents/services.py`: `create_worktree(project, name, base_branch=None)`,
  `launch_agent(project, kind, title, prompt, worktree=None, incident=None, base_branch=None, open_pr=True, dispatch=True)`,
  `run_agent(agent_run)`
- `vcs/services.py`: `next_pr_number(project)`, `open_pull_request(worktree, title, description="", base_branch=None, agent_run=None)`,
  `refresh_diff(pr)`, `merge_pull_request(pr)`
- `observability/services.py`: `ingest_line(deployment, raw)`, `record_metric(deployment, name, value)`,
  `next_incident_number(project)`, `open_or_update_incident(deployment, error_type, error_message, traceback="", suspect_file="", suspect_line=None, severity="sev2")`
- `orchestration/service.py`: `import_project(...)`, `deploy(environment_id, commit_sha=None)`,
  `run_feature_agent(agent_run_id)`, `run_ci(pull_request_id)`, `remediate(incident_id)`

Cross-slice calls go through these functions only. At build time stubs raise
`NotImplementedError`, so importing them is always safe.

## Routing map (each agent builds its own)
- `/` core dashboard (done), `/feed/` (done)
- `/projects/`, `/projects/new/`, `/projects/<slug>/`
- `/deploys/`, `/deploys/<pk>/`, plus the reverse-proxy `/d/<env_pk>/...` (see note)
- `/agents/`, `/agents/<pk>/` (+ `/agents/<pk>/stream/` HTMX tail), `/agents/new/`
- `/vcs/`, `/vcs/pr/<pk>/`, merge/CI actions
- `/obs/`, `/obs/incidents/`, `/obs/incidents/<pk>/`, log/metric fragments
- `/orchestration/` workflow runs list

**Reverse-proxy note (Slice A):** the proxy route `/d/<env_pk>/<path>` must be
reachable at the site root, but each app is included under its prefix. Put the
proxy view in `deploys/views.py` and expose it by also adding a root-level path —
since you can't edit `helm/urls.py`, instead register it in `deploys/urls.py` as
`path("d/<int:env_pk>/", ...)` is NOT root. SOLUTION: the integrator will add one
line to root urls for `/d/`. Just implement `deploys.views.proxy(request, env_pk, path="")`
and `deploys.proxy_urlpatterns = [path("d/<int:env_pk>/", proxy), path("d/<int:env_pk>/<path:path>", proxy)]`.
