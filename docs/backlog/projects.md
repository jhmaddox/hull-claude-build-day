# projects backlog — Sprint 3: import → (verify) → deploy, with a live progress UI

SIMPLIFIED for demo speed + reliability: no AI Dockerfile generation. Hull
supports importing a repo that already declares how to run: a `docker-compose.yml`,
a `Procfile` (web: ...), or a Django `manage.py`. The star of this workstream is a
polished, live IMPORT PROGRESS display. Keep the autonomous incident→fix loop
untouched (additive, fallbacks).

- [ ] PROJ-1: Supported-runtime detection + clear gate — `detect_runtime` returns
  framework "compose" (docker-compose.yml present), "procfile" (Procfile web:
  line), or "django" (manage.py); for compose, parse the web service + port. If a
  repo declares NONE of these, `import_project` marks the project FAILED with a
  friendly message ("Hull needs a docker-compose.yml, a Procfile, or a Django
  manage.py to deploy this repo."). NO AI generation. (acceptance: unit tests for
  compose/procfile/django/none; the none-case yields FAILED + the message.)
- [ ] PROJ-2: ⭐ Live import progress display — model the import as ordered STEPS
  and render them live. Steps: Clone → Detect runtime → Verify environment
  (install deps / build) → Provision domain → Deploy staging → Deploy prod, each
  with state (pending / running / done / failed) + a short detail line, shown as a
  styled stepper on the project page (and/or the new-project flow), HTMX-polled
  (~1.5s) so it animates as the import runs. Back it with a small ImportStep model
  (or structured ImportLog) the import flow updates at each phase. (acceptance:
  importing shows steps transition pending→running→done in real time; a failed
  step shows red with the error; page 200; org-scoped.)
- [ ] PROJ-3: Run import+deploy through orchestration/Temporal — so it's durable +
  shows a WorkflowRun; threaded fallback intact (HELM_USE_TEMPORAL=0).
  (acceptance: importing creates a WorkflowRun; works on threads.)
- [ ] PROJ-4: Compose deploy path wired to the steps — when framework=compose and
  Docker is available, deploy via the compose runtime (web+db+worker+redis as the
  compose declares); the Verify + Deploy steps reflect compose build/up; process
  path stays the Django fallback. (acceptance: a compose repo deploys via compose
  when Docker present, surfacing build output in the Verify step.)
- [ ] PROJ-5: Generality proof — importing the Node/Express sample
  (sample_apps/nodeshop, which ships a Procfile + compose) runs the full progress
  display and yields a LIVE deployment returning HTTP 200. (acceptance: a
  script/test imports nodeshop and asserts live 200; also verified by the mayor on
  the Docker-enabled EC2 box.)
