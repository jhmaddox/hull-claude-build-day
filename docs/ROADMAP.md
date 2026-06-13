# Hull — product roadmap (the Chief PM's source of truth)

Hull is an enterprise-grade, multi-tenant, AI-native software operating system:
one control plane, operated by a crew of Claude agents, that unifies version
control, CI/CD, deployments, observability, incident response, work tracking,
and documentation. Small elite teams run a production stack from one place while
autonomous agents do the operational work.

**Non-negotiable:** the autonomous **incident → agent fix → PR → CI → merge →
redeploy → resolved** loop must keep working through every change. It is the
crown jewel and a hard QA gate every sprint.

**Stack:** Django 5 + HTMX (minimal JS), Temporal (threaded fallback), Postgres,
Docker, gunicorn + Caddy, Claude Opus 4.8 headless agents. Internal package
codename `helm`. Live: https://hull.dev-reservclaims.com (apps at
`*.apps.dev-reservclaims.com`).

## Sections & target bars

1. **Accounts & Tenancy** (foundation) — Orgs, users, roles/RBAC, invitations,
   login/signup, org switching; every record org-scoped; SSO-ready. Enterprise.
2. **Projects & Environments** — Complex apps via **Docker Compose** per env
   (web + Postgres + worker + Redis), per-env config & secrets, build pipeline.
3. **Domains & Deployments** — **Custom domain per project/env** (real hostname,
   not a path), Caddy on-demand TLS, deploy history, rollbacks.
4. **Observability (Datadog-level)** — Structured logs with search/filter,
   metrics (req rate, error rate, p50/p95/p99 latency), live dashboards,
   monitors/alerts, per-deployment health.
5. **Incidents (PagerDuty-level)** — Severities, on-call schedules, escalation
   policies, incident timeline, ack/resolve, postmortems, alert routing; wired
   to the autonomous remediation loop.
6. **Issues (Jira)** — Projects/boards, tickets, sprints, statuses, assignees,
   labels, links to PRs/incidents/commits. **The agent backlog lives here** — PM
   agents file tickets, builder agents pick them up.
7. **Docs / Wiki** — Spaces, hierarchical pages (markdown), search, knowledge
   vault, linking to code/PRs/incidents.
8. **Agents & Orchestration** — The agent org surfaced in-product: PM/builder/QA
   agents, sprint/workflow runs, live agent output.
9. **Enterprise polish** — Audit log, API keys, RBAC enforcement, settings,
   billing stub.

## Sprint plan

- **Sprint 0 — Foundation** (cross-cutting; mostly sequential): Accounts &
  Tenancy + Postgres + Docker-Compose deploy substrate + custom domains. Gate:
  login works, data is org-scoped, an env deploys as a compose stack on a custom
  hostname, and the autonomous loop still resolves an incident.
- **Sprint 1 — Work & Knowledge** (fan out): Issues (Jira) + Docs/Wiki.
- **Sprint 2 — Operations** (fan out): Observability v2 + Incidents v2.
- **Sprint 3 — Enterprise & polish**: RBAC, audit, API keys, agent org UI,
  dashboards, demo hardening.

Each sprint: section PMs write/refresh `docs/prd/<section>.md` (requirements +
**machine-checkable rubric** + ticket list), builders implement, adversarial QA
verifies against the rubric and loops until green, integrator merges + migrates +
tests + boots + redeploys. The Mayor (human + lead) steers between sprints.
