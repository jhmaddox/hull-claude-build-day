# ⎈ Hull — the AI-native control plane for software teams

> One control plane for your entire stack — version control, CI/CD, deployments,
> observability, and incident response — **operated by a crew of Claude Opus 4.8
> agents.** GitHub + Vercel + PagerDuty + Datadog, mashed together and run
> autonomously.

Built at **Claude Build Day**, San Francisco — June 13, 2026.

Small, elite engineering teams shouldn't need a platform org to run a
production-grade stack. Hull lets one engineer **import a legacy repo, stand up
staging + prod, ship features through agents, and have production incidents
fixed autonomously** — all from a single pane of glass.

## The autonomous loop 🎯

A production app throws an error → Hull detects it from the live logs → opens a
PagerDuty-style **incident** → spawns a **Claude agent in an isolated git
worktree** → the agent reproduces it, fixes the root cause, **adds a regression
test** → opens a **pull request** in Hull's own PR/diff UI → **CI runs** → green
→ a human **reviews & merges** → Hull redeploys → incident **resolved**.

Everything up to the merge is autonomous; the merge is a human-in-the-loop gate
by default (you review the agent's fix before it ships). Flip
`HELM_AUTO_MERGE=1` and the loop closes itself — no human in the loop at all.

## What it does

| Capability | Plays the role of | How |
|---|---|---|
| Import any repo, detect runtime | — | clone + framework detection |
| Staging & prod deployments w/ public URLs | Vercel | managed processes behind a reverse proxy |
| Spin a worktree → run a Claude agent on a feature | the IDE + the engineer | `claude -p` headless in a git worktree |
| In-app pull requests, diffs, merges | GitHub | real git branches, server-rendered diff UI |
| CI on every PR | GitHub Actions | runs the project's test suite in the worktree |
| Logs, metrics, error detection | Datadog | tails deployment output, parses requests + tracebacks |
| Incidents + autonomous remediation | PagerDuty + an on-call SRE | the loop above |
| Durable, observable orchestration | — | Temporal workflows (with a threaded fallback) |

## Architecture

A single **Django 5 + HTMX** control plane (minimal JS), **Temporal** for durable
orchestration, **SQLite** for state, and **Claude Opus 4.8** as the headless
agent that does the engineering work.

> The Django project package and `HELM_*` settings keep the original build
> codename `helm`; the product is **Hull**.

```
helm/                control plane (Django project)
├── core/            dashboard, activity feed, design system, demo command
├── projects/        import a repo, detect runtime
├── deploys/         process manager, health checks, reverse-proxy URLs
├── agents/          worktrees + headless Claude agents (streamed live)
├── vcs/             git-backed pull requests, diffs, merge
├── observability/   log/metric ingestion, error detection, incidents
├── orchestration/   Temporal workflows + dispatcher (threaded fallback)
sample_apps/pocketshop/   the "legacy" storefront we import & operate (has a planted bug)
workflows/          dynamic-workflow scripts used to build & operate Hull
brief.md  rubric.md  CONTRACTS.md
```

Everything cross-app goes through small **service contracts** (`*/services.py`),
which is how four agents built this in parallel without stepping on each other —
see [`CONTRACTS.md`](CONTRACTS.md).

## Run it locally

```bash
asdf install        # python 3.11.8 (see .tool-versions)
uv venv .venv && source .venv/bin/activate
uv pip install -r requirements.txt
python manage.py migrate
python manage.py runserver         # http://localhost:8000

# one command runs the whole demo end-to-end:
python manage.py helm_demo
```

`helm_demo` imports PocketShop, deploys staging + prod, then (with `--break`)
triggers the production bug so you can watch Hull detect, diagnose, and fix it
live on the dashboard.

## How "done" is verified by the model

Hull's orchestration is designed so the model can check its own work without a
human — see [`rubric.md`](rubric.md). Concretely: deployment health is an HTTP
200 from a responding URL; a feature/fix is "done" only when its **CI suite is
green**; an incident is "resolved" only when a **merged remediation PR** ships
and the prod URL stops erroring. These are all machine-checkable assertions.

---

Built with Claude Opus 4.8. The orchestration that built it lives in
[`workflows/`](workflows/) and the parallel-build contracts in `CONTRACTS.md`.
