# Hull — Target ("Gold Star") Demo

The end-to-end story Hull must tell live. One operator, one control plane, a crew
of Claude agents doing the engineering. Live at https://hull.dev-reservclaims.com.

## The narrative (in order)
1. **Import a project** — paste a repo URL. A **live progress display** animates:
   Clone → Detect runtime → Verify environment → Provision domain → Deploy
   **staging** → Deploy **prod**. (Import requires a `docker-compose.yml`, a
   `Procfile`, or a Django `manage.py` — no guessing.)
2. **Check out the deployed product** — click Open → it loads at a real custom
   domain `https://<project>-<env>.apps.dev-reservclaims.com/` (TLS).
3. **Start a feature** — **create a Ticket** (Issues/Jira), hit **"Work this
   ticket"** → Hull spins a worktree + launches an autonomous **agent session**.
4. **Launch a few more** agents; watch the **agent observability dashboard** —
   the swarm working live (status, cost, turns, current action).
5. **PRs** — agents open PRs; **review the diff, see CI pass, merge**.
6. **Deploy** — merge auto-redeploys; **check it in production**.
7. **Trigger an error** in prod (or **Declare an incident**).
8. **Incidents/agents** — see Hull is **already remediating**: an agent is fixing
   it in a worktree.
9. **Review that fix PR**, see CI green, **merge**.
10. **Check the deploy** — the fix shipped; **prod works now**.
11. **Throughout**, show **logging** (search, levels), **on-call** (schedules,
    timeline, postmortems), and **analytics** (req rate, error rate, p50/95/99,
    monitors).

## What makes it land
- **Two proactive agent moments** (import progress; ticket→agent swarm) +
  **one reactive** (autonomous incident→fix) — the crown jewel.
- **Real infra**: custom domains w/ on-demand TLS, multitenant orgs, Temporal-
  visible workflows, Docker-Compose deploys.
- **Warm, polished UI** — cohesive warm-dark palette, every input styled.

## Build status → see the sprint backlog
Closing gaps in `docs/backlog/`:
- `projects` — import + **live progress display** (simplified: require Procfile/
  compose/Django)
- `sample-app` — NodeShop (Node/Express, ships Procfile+compose) to prove
  "import any repo" beyond Django
- `issues` — **Work this ticket** → agent + PR linkback
- `orchestration` — **agent observability dashboard** (the swarm view)
- `observability` — manual **Declare incident**
- `design` — **warmer palette** + bulletproof input styling

Plus mayor-owned demo-readiness: install Docker on EC2, verify the loop live,
seed clean demo data, rehearse `docs/DEMO_SCRIPT.md`.

## Already solid (the back half)
Custom-domain deploys, multitenant auth/orgs, PR/diff/CI/merge, merge→redeploy,
the autonomous incident→fix→ship loop, Datadog-grade observability, PagerDuty-
grade on-call. All built; verified live.
