# Helm — demo script

Two cuts: a **60-second** version for the submission video, and a **3-minute**
version for the live stage round. Both show the same money shot: a production
error fixed autonomously by a Claude agent.

Pre-flight (off camera):
```bash
source .venv/bin/activate
# control plane with autonomous remediation on:
HELM_AUTO_REMEDIATE=1 HELM_AUTO_MERGE=1 python manage.py runserver 0.0.0.0:8000 --noreload
```
Have two browser tabs open: **Mission Control** (`/`) and the **PocketShop prod**
URL. Keep a terminal visible.

---

## 60-second cut (submission video)

> "This is Helm — one control plane that runs your whole stack with a crew of
> Claude agents. GitHub, Vercel, PagerDuty and Datadog, mashed together and run
> autonomously."

1. **(0:00–0:10) Import + deploy.** On Mission Control, click **Import project**
   → PocketShop. Watch the activity feed: *imported → deployed staging → deployed
   prod*. Click the **prod** URL — a real storefront loads. *"I pointed Helm at a
   legacy Django app; it imported it and stood up staging and prod with live
   URLs."*
2. **(0:10–0:20) Break prod.** In the storefront, add an item, apply promo
   **BOGO** at checkout → **500**. *"Now a real production bug."*
3. **(0:20–0:50) Autonomous fix.** Cut to Mission Control. Narrate the feed as it
   writes itself: *🚨 PagerDuty INC-1 → claude-sre triaging → spun a worktree →
   wrote the fix + a regression test → opened PR #1 → CI green → merged →
   redeployed prod → **RESOLVED**.* Open the **incident page** to show the
   FIRING→REMEDIATING→RESOLVED stepper and the linked PR; open the **PR diff** to
   show the guard added to `_bogo_discount` and the new test.
4. **(0:50–0:60) Proof.** Reload the storefront checkout with BOGO → **200**.
   *"No human touched it. The agent read the traceback, fixed the root cause,
   proved it with a test, and shipped it."*

## 3-minute cut (stage)

Everything above, plus:

- **Contracts + parallel build (orchestration).** Show `CONTRACTS.md` and
  `workflows/build_helm.workflow.js`: *"Helm itself was built by four Claude
  agents in parallel against a frozen set of service contracts, then graded
  against `rubric.md`."*
- **Feature flow.** `/agents/new/` → "Add a free-shipping banner" → watch the
  agent stream live in the terminal-style view → PR #2 → **Run CI** → **Merge** →
  staging redeploys → reload staging, banner is there. *"Same machinery, used
  proactively for features, not just incidents."*
- **Verifiability.** *"'Done' is checkable by the model: a responding URL, a green
  CI suite, and an incident that reaches resolved with a merged PR. The whole run
  is one command:"*
  ```bash
  python manage.py helm_demo --break
  ```
  and it's graded by `rubric.md`. *"Another team could rerun this tomorrow on a
  new repo."*

## The "it caught its own failure" beat (judges love this)

During the build, an agent's first deploys failed because the managed app
inherited Helm's own `DJANGO_SETTINGS_MODULE`; the agent diagnosed it from the
child process error and added `_clean_env()` to strip it. The integrator caught
the same class of bug in CI and in the proxy's `Set-Cookie` handling. Show the
commit messages — the system found and fixed its own failures.

## Fallbacks if something misbehaves live

- Incident didn't auto-fire? Open the incident page and click **Remediate now**.
- Want a guaranteed clean run? `python manage.py helm_demo --break --reset`
  end-to-end, then narrate the feed.
- Agent slow? The PR + CI are already deterministic; cut to the resolved state.
