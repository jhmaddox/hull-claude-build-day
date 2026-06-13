# Hull — Claude Build Day submission

**Live:** https://hull.dev-reservclaims.com  (demo login: `demo` / `demo12345`, org "Acme Inc")
**Repo:** https://github.com/jhmaddox/hull-claude-build-day
**Brief:** [brief.md](brief.md) · **Rubric:** [rubric.md](rubric.md) · **Build contracts:** [CONTRACTS.md](CONTRACTS.md)
**Session log:** [transcript/session-log.md](transcript/session-log.md) — the Claude Code session that built & operated Hull.

---

## Project description

**Hull is one control plane that unifies version control, CI/CD, deployments,
observability, and incident response — and operates it autonomously with a crew
of Claude Opus 4.8 agents.** It's GitHub + Vercel + PagerDuty + Datadog fused
into a single product and run by agents instead of by you.

You import a repo once. Hull detects its runtime, stands up **staging + prod**
with real public URLs (Docker Compose or a managed-process runtime, host-based
routing + Caddy on-demand TLS), and watches it. You ship features by handing a
ticket to an agent, which works in an isolated **git worktree**, opens a **pull
request** in Hull's own diff UI, and runs **CI** — then spins a **preview
environment** so you can test the change before merge.

The autonomous loop: when production throws an error, Hull detects it from the
live logs, opens a **PagerDuty-style incident**, spawns a Claude agent in a fresh
worktree that reproduces the bug, fixes the root cause, **adds a regression
test**, opens a PR, runs CI green, and — after a human approves the merge
(HITL by default; `HELM_AUTO_MERGE=1` closes the loop fully) — redeploys and
resolves the incident. The human reads the timeline after it's handled.

Built solo at Claude Build Day, SF, June 13 2026. Django 5.1 + HTMX (minimal JS),
SQLite, Temporal Cloud for durable orchestration (with a threaded fallback),
multi-tenant and auth'd, deployed live on a single EC2 box.

---

## How Opus 4.8 was used

Opus 4.8 is used **two ways**, and the first is the product itself:

**1. As the runtime engine of the product.** Hull's agents *are* Opus 4.8
(`HELM_AGENT_MODEL=claude-opus-4-8`, run headless via the `claude` CLI in
stream-json mode, each in its own git worktree). Opus does the actual
engineering work the product automates:
- **Feature agents** — take a ticket, write the code + tests, open a PR.
- **Remediation agents** — the autonomous incident→fix loop: read the traceback
  + failing logs, locate the suspect file/line, reproduce, fix the root cause,
  add a regression test, open a PR, and pass CI.
- Their reasoning streams live into the UI (cost, turns, linked PR/incident), so
  the agent's work is observable, not a black box.

**2. As the builder of the product.** The entire codebase was built by Opus 4.8
through Claude Code, orchestrated with the multi-agent Workflow scripts below —
contract-first parallel slices, adversarial QA, and a loop that grades the
running system against a machine-checkable rubric until it passes.

---

## How I orchestrated Claude's work

The strategy was **"the Mayor and the build org"**: I (in the main Claude Code
thread) acted as the chief PM/Mayor — shaping the brief, the rubric, and the
roadmap — and dispatched fleets of subagents through deterministic **Workflow
scripts** that encode the control flow (fan-out, verify, loop, synthesize). The
governing idea throughout: **make "done" verifiable by a model with no human in
the loop** — a responding URL plus a green rubric — and let agents loop against
that.

**Custom scaffolding (the contracts the fan-out depends on):**
- [`brief.md`](brief.md) — the vision/spec every agent reads first.
- [`rubric.md`](rubric.md) — a **100-point machine-checkable rubric** (Impact 35
  / Demo 35 / Opus Use 15 / Orchestration 15), written as pass/fail HTTP/DB
  assertions a grader agent runs against the *live* system. This is the loop's
  termination condition.
- [`CONTRACTS.md`](CONTRACTS.md) — the build contract: stack conventions, the
  frozen data model + service-function signatures, the routing map, and the hard
  rules that make parallel agents safe (own disjoint dirs; never touch shared
  wiring; never break the autonomous loop). Cross-slice calls go through stub
  service functions only, so slices depend on *contracts*, never on each other's
  code.
- [`docs/prd/`](docs/prd) (per-section PRDs) and [`docs/backlog/`](docs/backlog)
  (per-section checkbox backlogs) — the durable, idempotent source of truth for
  what's built and what's left.

**The Workflow scripts (multi-agent pipelines) — in [`workflows/`](workflows):**
- [`build_helm.workflow.js`](workflows/build_helm.workflow.js) — the initial
  build. **Foundation** agent lays schema + service contracts + UI shell → **4
  disjoint vertical slices** built in parallel (fan-out) → **integrator** wires
  shared files, migrates, boots → **grader** runs `rubric.md` against the live
  system and loops failures back as fix tasks until green.
- [`sprint.workflow.js`](workflows/sprint.workflow.js) — the "Gastown" build org
  for feature sprints: **section-PM agents** write PRD + rubric + tickets
  (generate-and-filter to an MVP) → **builder agents** implement in parallel
  (cross-cutting workstreams sequenced first) → **adversarial QA agent** tries to
  break each build against its rubric and re-dispatches the builder on failure
  (adversarial verification + loop-until-done) → **integrator** synthesizes
  (fan-out & synthesize).
- [`backlog.workflow.js`](workflows/backlog.workflow.js) — an **idempotent**,
  backlog-driven sprint: each section runs **Refine** (reconcile the checkbox
  backlog with the actual code, ticking off anything already satisfied so work is
  never redone) → **Build** the next N open tickets → **adversarial QA** (reopen
  any ticket that doesn't hold) → one **Integrate** agent that migrates, tests,
  boots, and regression-gates the autonomous loop. Re-running is safe by design.
- [`name_product.workflow.js`](workflows/name_product.workflow.js) — a small
  generate-and-filter workflow that picked the product name.

**The orchestration patterns I leaned on (and why):**
- **Contract-first fan-out** — freeze the schema + service signatures up front so
  N agents build disjoint slices in parallel without coordinating.
- **Generate-and-filter** — PM agents propose many tickets, then filter to the
  sprint MVP.
- **Adversarial verification** — a separate QA agent's job is to *break* each
  build against its rubric, not confirm it (a hard lesson: don't trust agent
  self-reports). Failures loop back as fix tasks.
- **Loop-until-done / loop-until-rubric-green** — termination is the
  machine-checkable rubric passing against the running system, not an agent
  saying "done."
- **Fan-out & synthesize** — a single integrator owns all shared wiring
  (settings, root URLs, migrations, base nav) so parallel builders never collide.
- **Idempotent backlogs** — durable per-section state means re-runs continue
  rather than redo, which kept long multi-sprint builds cheap and safe.

The product's own autonomous incident→fix loop is, fittingly, the same idea
turned into a feature: a deterministic orchestration (Temporal workflow, with a
threaded fallback) that dispatches an Opus agent, verifies its work through CI,
and gates the merge — orchestrating Claude exactly the way I orchestrated Claude
to build Hull.

---

## Run it locally

```bash
uv venv .venv && source .venv/bin/activate && uv pip install -r requirements.txt
python manage.py migrate
python manage.py runserver --noreload          # http://localhost:8000
# Agents need a key in the environment:  export ANTHROPIC_API_KEY=sk-ant-...
```
