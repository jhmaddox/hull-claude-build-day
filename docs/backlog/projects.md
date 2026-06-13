# projects backlog — Sprint 3: import → (verify) → deploy, with a live progress UI

SIMPLIFIED for demo speed + reliability: no AI Dockerfile generation. Hull
supports importing a repo that already declares how to run: a `docker-compose.yml`,
a `Procfile` (web: ...), or a Django `manage.py`. The star of this workstream is a
polished, live IMPORT PROGRESS display. Keep the autonomous incident→fix loop
untouched (additive, fallbacks).

> Reconciled 2026-06-13 against `projects/` + `deploys/compose/` + `orchestration/`.
> Sprint-1 multi-project UX (org-scoped search/filter, portfolio summary strip,
> per-card + detail health verdicts via `projects/health.py`, distinct empty
> states) is fully SHIPPED and green — `python manage.py test projects` → 30
> passing. Those are regression invariants, not open work. The open Sprint-3 work
> below is the import→verify→deploy pipeline + live progress UI + a non-Django
> generality proof.

- [x] PROJECTS-1: Supported-runtime detection + clear gate — `detect_runtime` returns
  framework "compose" (docker-compose.yml present), "procfile" (Procfile web:
  line), or "django" (manage.py); for compose, parse the web service + port. If a
  repo declares NONE of these, `import_project` marks the project FAILED with a
  friendly message ("Hull needs a docker-compose.yml, a Procfile, or a Django
  manage.py to deploy this repo."). NO AI generation. (acceptance: unit tests for
  compose/procfile/django/none; the none-case yields FAILED + the message.)
  (done: added a `compose` branch to `detect_runtime` (finds
  docker-compose.yml/.yaml + compose.yml/.yaml, returns `web_service`+`web_port`
  via a new `_parse_compose_web` that prefers PyYAML but falls back to a
  dependency-free indentation parser since the app venv has no PyYAML; compose
  process-fallback run_command comes from the Procfile `web:` line, else
  Django/static). Generic fallback replaced by framework `none` +
  `UNSUPPORTED_RUNTIME_MESSAGE`; `import_project` gates `none` -> FAILED with the
  message and creates NO environments. New tests:
  `projects.tests.DetectRuntimeTests` (compose/procfile/django/none +
  compose-wins-over-procfile) and `UnsupportedRepoGateTests`. NO AI generation.)
- [x] PROJECTS-2: ⭐ Live import progress display — model the import as ordered STEPS
  and render them live. Steps: Clone → Detect runtime → Verify environment
  (install deps / build) → Provision domain → Deploy staging → Deploy prod, each
  with state (pending / running / done / failed) + a short detail line, shown as a
  styled stepper on the project page (and/or the new-project flow), HTMX-polled
  (~1.5s) so it animates as the import runs. Back it with a small ImportStep model
  (or structured ImportLog) the import flow updates at each phase. (acceptance:
  importing shows steps transition pending→running→done in real time; a failed
  step shows red with the error; page 200; org-scoped.)
  (done: new `projects.models.ImportStep` (project FK, key/label/order, state
  pending/running/done/failed, detail, started/ended) seeded from the canonical
  `IMPORT_STEPS` list. `import_project` flips clone/detect/verify/provision live
  (best-effort, swallows errors so it never breaks the autonomous loop); the
  new projects-owned `deploy_environment` wrapper advances deploy_staging/
  deploy_prod while wrapping `deploys.services.deploy` additively (views use it
  in the fallback import loop + manual deploy). Stepper template
  `_import_steps.html` (helm.css classes: card/list/dot/spinner/badge) self-polls
  via HTMX at 1.5s while active and stops once settled; rendered on detail.html;
  served org-scoped at `/projects/<slug>/import-steps/`
  (`views.import_steps_fragment`). NEEDS MIGRATION (see wiring notes).)
- [x] PROJECTS-3: Compose deploy path wired to the steps — when framework=compose and
  Docker is available, deploy via the compose runtime (web+db+worker+redis as the
  compose declares); the Verify + Deploy steps reflect compose build/up; process
  path stays the Django fallback. Projects-side wiring: `import_project` sets each
  Environment's `runtime=COMPOSE` when `framework=="compose"` so
  `deploys.services.deploy` takes the existing compose branch. (acceptance: a
  compose repo deploys via compose when Docker present, surfacing build output in
  the Verify step.)
  (done: `import_project` stamps `Environment.runtime=COMPOSE` for both staging
  and prod when `framework=="compose"` (else PROCESS), so
  `deploys.services.deploy` takes the existing compose branch. The deploy step
  detail line surfaces the deployment status+port. Verified end-to-end on this
  Docker-enabled box: the Node sample (PROJECTS-4) built + upped a
  web+db+redis+worker compose stack and went LIVE on the allocated port.)
- [x] PROJECTS-4: Node/Express generality proof — importing a non-Django sample that
  ships a `Procfile` + `docker-compose.yml` (web on the app port, $PORT-aware)
  runs the full progress display and yields a LIVE deployment returning HTTP 200.
  Sample lives under `sample_apps/` with an inner git repo on `main`. (acceptance:
  a script/test imports the Node sample and asserts a live 200; also verified by
  the mayor on the Docker-enabled EC2 box.)
  (done: new `sample_apps/widgetcart/` — a tiny Node app (server.js using only
  Node's built-in `http`, ZERO npm deps so it deploys with no install/build),
  with `Procfile` (`web: node server.js`), `docker-compose.yml` (web service,
  $PORT-aware), `Dockerfile`, and README. Tracked as plain files like
  pocketshop; the import flow's `_ensure_local_git_repo` creates the inner repo
  on `main` at import time. Script `import_widgetcart.py` imports it
  (framework=compose) + deploys staging via `deploy_environment` + asserts a
  live HTTP 200. VERIFIED here on the Docker-enabled box: imported, compose-built
  web+db+redis+worker, went LIVE, `curl :9103` -> 200 (`PASS: live 200`).)
- [x] PROJECTS-5: Run import+deploy through orchestration/Temporal — so it's durable +
  shows a WorkflowRun; threaded fallback intact (HELM_USE_TEMPORAL=0).
  (acceptance: importing creates a WorkflowRun; works on threads.)
  (done: `projects.views._import_in_background` calls
  `orchestration.service.import_project`, which wraps the work in `_run_workflow`
  → creates a `orchestration.models.WorkflowRun` (org-stamped best-effort) and
  uses Temporal when enabled with a daemon-thread fallback; `project_deploy`
  routes through `orchestration.service.deploy` with the same fallback. Autonomous
  loop path unchanged: signatures stay additive with `NotImplementedError`/`Type
  Error` fallbacks to `deploys.services.deploy`.)
