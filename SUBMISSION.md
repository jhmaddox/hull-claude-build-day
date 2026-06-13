# Hull — Claude Build Day submission

**Hull — the autonomous software operating system.** One control plane,
operated by a crew of Claude Opus 4.8 agents, that unifies version control,
CI/CD, deployments, observability, and incident response — GitHub + Vercel +
PagerDuty + Datadog, mashed together and run autonomously.

- **Live URL:** https://54.185.134.217.sslip.io
- **Repo:** <add public GitHub URL on push>
- **Built:** entirely during Build Day, from an empty folder.

## The problem & who it's for
Small, elite engineering teams shouldn't need a platform org to operate a
production stack. Today they stitch together GitHub, Vercel, PagerDuty, and
Datadog by hand. Hull unifies all of it into one pane and lets autonomous Claude
agents do the operational work — so one engineer can import a legacy repo, stand
up staging + prod, ship features, and have production incidents fixed without a
human in the loop.

## What we built during the hackathon (all of it)
A Django 5 + HTMX control plane (minimal JS) + Temporal orchestration, with:
- **Import** any git repo + runtime detection
- **Deployments**: managed processes for staging/prod behind a reverse proxy
  with public URLs + health checks
- **Agents**: headless `claude -p` sessions in isolated git worktrees, streamed
  live to the UI
- **In-app VCS**: git-backed pull requests, diffs, merge
- **CI**: runs the project's real test suite per PR
- **Observability**: log/metric ingestion, traceback→incident detection
- **Autonomous remediation**: incident → agent fixes root cause + adds a
  regression test → PR → CI → merge → redeploy → resolved
- **PocketShop**, a sample legacy storefront with a deterministic planted bug
- Provisioned to AWS EC2 (Caddy TLS) with public URLs

## The demo (what the video shows)
A production error fixed autonomously, end to end:
1. Import PocketShop → staging + prod deploy with live URLs
2. A shopper applies promo `BOGO` at checkout → **500** in production
3. Hull detects it from live logs → opens **INC-1** (PagerDuty-style)
4. A Claude agent spins a worktree, fixes `_bogo_discount` in `store/promos.py`,
   **adds a regression test**, opens **PR #1**
5. **CI** runs the suite → green → **merge** → **redeploy**
6. Incident **RESOLVED**; reloading checkout with BOGO now returns **200**

Reproducible with one command: `python manage.py helm_demo --break`.

## How we directed Claude (orchestration)
- A **foundation** locked the data model + per-app **service contracts**
  (`CONTRACTS.md`); then **four Claude agents built disjoint slices in
  parallel** against those frozen contracts.
- "Done" is **model-verifiable**: `rubric.md` is a 100-point pass/fail checklist
  (HTTP/DB assertions), backed by a green pytest suite and the one-command demo.
- The build harness is captured in `workflows/build_helm.workflow.js`; the
  product name was chosen by a **generate-and-filter** workflow
  (`workflows/name_product.workflow.js`).
- **The model caught and fixed its own failures**: a deploy agent diagnosed that
  managed apps were inheriting Hull's `DJANGO_SETTINGS_MODULE` and added
  `_clean_env()`; integration caught the same class of bug in CI and a proxy
  `Set-Cookie` bug. See the git history.

## Stack
Django 5, HTMX (no heavy JS), Temporal (threaded fallback), SQLite, gunicorn +
Caddy, Claude Opus 4.8 headless agents. Internal Django package codename:
`helm`.

## Run it
```bash
uv venv .venv && source .venv/bin/activate && uv pip install -r requirements.txt
python manage.py migrate
HELM_AUTO_REMEDIATE=1 HELM_AUTO_MERGE=1 python manage.py runserver --noreload
python manage.py helm_demo --break        # the whole loop, one command
pytest -q                                  # tests
```
