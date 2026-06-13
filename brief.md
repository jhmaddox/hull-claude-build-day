# Hull — the autonomous software operating system

## The problem

Shipping and *operating* a production web app today means stitching together a
pile of disconnected SaaS: GitHub for code and PRs, Vercel/Render for deploys,
PagerDuty/Opsgenie for on-call, Datadog/Sentry for logs and errors, plus the
human glue that ties them together at 3am. Elite individual developers and small
teams pay this "operations tax" disproportionately — they have production
responsibilities but no platform team. When prod breaks, a human has to notice
the alert, find the error, reproduce it, write the fix, open a PR, wait for CI,
merge, and redeploy. Every one of those steps is a place to lose hours.

## The vision

**Hull is one control plane that unifies version control, CI/CD, deployments,
observability, and incident response — and runs it autonomously with a crew of
Claude Opus 4.8 agents.** You import a repo once. Hull deploys it to staging and
prod, watches it, and when production throws an error, Hull doesn't page a
human — it opens an incident, spawns a Claude agent in an isolated git worktree,
fixes the root cause, adds a regression test, opens a PR in its own diff UI, runs
CI, merges on green, and redeploys. The human reads the incident timeline after
it's already resolved.

It's GitHub + Vercel + PagerDuty + Datadog, fused into a single product and
operated by agents instead of by you.

## Who it's for

Solo founders, indie hackers, and small high-leverage teams who run real
production traffic but can't afford (or don't want) a dedicated platform/SRE
function — and who would rather supervise an autonomous system than babysit five
dashboards.

## The stack

- **Django 5.1** server-rendered control plane, **HTMX** for live updates
  (streaming agent output, log tails, incident state) — no heavy JS frameworks.
- **SQLite** state, a built-in deploy runtime + reverse proxy that serves each
  environment at `{base}/d/<env_pk>/`.
- **Temporal** for durable, repeatable orchestration of the long-running
  workflows (import, deploy, feature, CI, remediation).
- **Claude Opus 4.8 headless agents** (`claude` CLI) do the real engineering
  work — feature development and autonomous remediation — each in its own git
  worktree, streaming their reasoning into the UI.

## The demo (end to end)

A scripted, repeatable run that the audience watches happen live:

1. **Import a legacy app.** Point Hull at `sample_apps/pocketshop` (a real,
   polished Django storefront). Hull detects the runtime, clones it, and marks
   the project *ready*.
2. **Deploy to staging + prod.** Hull builds and boots both environments; their
   public URLs (`/d/<env_pk>/`) return 200 and show the live storefront.
3. **Spin up a feature agent.** Hull creates an isolated worktree and launches a
   Claude Opus 4.8 agent with a feature task. Its reasoning streams into the UI.
4. **PR → CI → deploy.** The agent opens a PR in Hull's diff UI; CI runs green;
   the change deploys.
5. **Trigger a production error.** We hit the storefront's checkout with the
   promo code `BOGO` (`/checkout/?promo=BOGO`) — a latent bug throws an uncaught
   500 in `store/promos.py`.
6. **Incident + autonomous fix.** Hull ingests the error, opens an **Incident**
   (PagerDuty-style), and spawns a **remediation** Claude agent in a fresh
   worktree. The agent reads the traceback, fixes the root cause in the buggy
   function, and **adds a regression test**.
7. **PR → CI → redeploy → resolved.** The agent opens a remediation PR; CI runs
   green; Hull merges and redeploys prod; the incident transitions to
   **resolved** — all without a human touching code.

The whole loop is narrated by Hull's own activity feed, so the system explains
itself as it runs.

## What DONE looks like (model-verifiable)

DONE is not a vibe — it's a set of assertions a model can check against the
running system (see `rubric.md` for the full pass/fail checklist):

- The control plane root (`GET /`) returns 200 and lists ≥1 imported project.
- The **prod** deployment URL (`{base}/d/<prod_env_pk>/`) returns 200 and serves
  the storefront home page.
- A feature **PR** exists with `ci_status=passed` and is merged.
- Triggering `BOGO` creates an **Incident** that reaches `status=resolved`.
- The incident has a **linked, merged remediation PR** whose diff modifies the
  buggy function (`_bogo_discount` in `store/promos.py`) **and adds a test**.
- The remediation branch's **test suite passes** (CI green on the fix).
- After remediation, `GET /checkout/?promo=BOGO` against prod no longer 500s.

## Why the orchestration is repeatable

Every step above is a Temporal-driven service call with a stable signature
(`orchestration/service.py`: `import_project`, `deploy`, `run_feature_agent`,
`run_ci`, `remediate`). The demo is one ordered sequence of those calls against a
deterministic, demo-controlled bug (the `BOGO` trigger fires on command, never by
accident), so the entire end-to-end run can be replayed identically — for the
judges, for a retry, or for a CI smoke test of the platform itself.
