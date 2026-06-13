# projects backlog — Sprint 3: agentic import → configure → deploy

The gold-demo centerpiece. Import any standard web repo; an agent configures it
for deployment (Dockerfile + compose) and Hull deploys it. Keep the autonomous
incident→fix loop untouched (additive, fallbacks).

- [ ] PROJ-1: Broaden runtime detection — in `detect_runtime`, detect Rails
  (`Gemfile`), Node (`package.json`), Go (`go.mod`), and Python
  (`pyproject.toml`/`requirements.txt`) in addition to Django (`manage.py`) and
  Procfile. Return a sensible framework + run/install commands for each.
  (acceptance: detect_runtime returns framework "rails"/"node"/"go"/"django" for
  fixtures of each; add unit tests in tests/.)
- [ ] PROJ-2: Agentic deploy-config generation — in `import_project`, after clone
  + detect, if the repo has NO Dockerfile and NO docker-compose, launch a
  configure agent via `agents.services.launch_agent(project, kind="chore",
  dispatch=False, open_pr=False, ...)` with a strict prompt: inspect the repo and
  write a WORKING `Dockerfile` + `docker-compose.yml` (web + db/redis/worker as
  the framework needs), then commit them to the project's repo. Run inline so the
  files exist before deploy. (acceptance: importing a repo lacking a Dockerfile
  yields a committed Dockerfile + compose; an AgentRun kind="chore" is recorded
  on the project; the autonomous loop is untouched.)
- [ ] PROJ-3: Route through Temporal/orchestration — run import+configure+deploy
  via `orchestration.service` so it's durable + shows a WorkflowRun in the
  orchestration UI; threaded fallback intact when Temporal is off.
  (acceptance: importing creates a WorkflowRun; works with HELM_USE_TEMPORAL=0.)
- [ ] PROJ-4: Deploy-failure auto-fix — if the first deploy of a freshly-imported
  project FAILS, launch one fix agent with the build/deploy logs to repair the
  Dockerfile/compose, then redeploy once. (acceptance: a broken config triggers
  exactly one fix AgentRun + a redeploy attempt; bounded, no infinite loop.)
- [ ] PROJ-5: Generality proof — importing the Node/Express sample (built by the
  sample-app workstream at sample_apps/nodeshop) produces a committed
  Dockerfile/compose AND, when Docker is available, a LIVE deployment returning
  HTTP 200. (acceptance: a script/test imports nodeshop and asserts a committed
  Dockerfile + a deployment that serves 200; this beat is also verified by the
  mayor post-sprint on the Docker-enabled EC2 box.)
