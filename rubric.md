# Hull — model-gradeable rubric

A checklist a model can grade against the **running system** with no human in the
loop. Every item is a pass/fail assertion plus how to check it. Let
`{base}` = the control plane base URL (e.g. `http://localhost:8000`). API/HTML
checks are plain HTTP GETs; "DB" checks can be read via Django shell or the
relevant detail page.

Total: **100 points** — Impact 35 / Demo 35 / Opus 4.8 Use 15 / Orchestration 15.

---

## Impact (35) — does it unify the ops stack and remove human toil?

- [ ] **(5) Single control plane is up.** `GET {base}/` returns **200** and
  renders the Hull dashboard (not an error page).
- [ ] **(5) Projects are real.** `GET {base}/projects/` returns 200 and lists
  **≥ 1** project whose `status = ready` (the imported PocketShop app).
- [ ] **(5) Deployments exist for two environment kinds.** The project has both a
  `staging` and a `prod` `Environment`; each has a `Deployment` with
  `status = live`. Check `GET {base}/deploys/` lists both, or query
  `Environment.objects.filter(project=..., kind__in=["staging","prod"])`.
- [ ] **(5) Prod serves live traffic.** `GET {base}/d/<prod_env_pk>/` returns
  **200** and the body contains the storefront (e.g. the string
  `PocketShop`).
- [ ] **(5) Observability is wired.** The prod deployment has **≥ 1**
  `observability.LogLine` and the incident view shows ingested error data;
  `GET {base}/obs/` returns 200.
- [ ] **(5) Incident response is unified in-product.** `GET {base}/obs/incidents/`
  returns 200 and lists the BOGO incident; its detail page links the remediation
  PR (no external PagerDuty/GitHub needed).
- [ ] **(5) End-to-end toil removed.** The BOGO incident reached `resolved`
  **without any human commit** — the only author on the remediation branch is an
  agent (PR `author` is the agent, not a human user).

## Demo (35) — does the money-shot loop actually run end to end?

- [ ] **(4) Import works.** PocketShop project exists with `framework` detected
  (django), `local_path` populated, and `status = ready`.
- [ ] **(4) Staging + prod deploy succeeded.** Both environments' latest
  `Deployment.status = live` and `health = healthy`.
- [ ] **(4) Feature agent ran.** An `agents.AgentRun` with `kind = feature` and
  `status = done` exists, with non-empty streamed `output`.
- [ ] **(4) Feature PR landed.** A `vcs.PullRequest` exists with
  `ci_status = passed` and `status = merged`, linked to the feature AgentRun.
- [ ] **(4) Prod error is triggerable on command.** `GET {base}/d/<prod_env_pk>/`
  `checkout/?promo=BOGO` (with an item in cart) returns **500** *before*
  remediation — the bug is demo-controlled, not random.
- [ ] **(4) Incident opened automatically.** Hitting the BOGO error creates an
  `observability.Incident` with `error_type` set and `suspect_file` containing
  `promos.py` (and ideally `suspect_line` near `_bogo_discount`).
- [ ] **(4) Remediation agent ran.** An `AgentRun` with `kind = remediation`,
  `status = done`, linked to that Incident (`incident` FK set).
- [ ] **(4) Remediation PR merged on green CI.** The incident's
  `remediation_pr` has `ci_status = passed` and `status = merged`.
- [ ] **(3) Incident resolved + verified.** The Incident reaches
  `status = resolved`, and after redeploy
  `GET {base}/d/<prod_env_pk>/checkout/?promo=BOGO` returns **200** (no longer
  500).

## Opus 4.8 Use (15) — are agents doing real engineering with Claude?

- [ ] **(4) Real model in the loop.** Agent runs use `claude-opus-4-8` (config
  `HELM_AGENT_MODEL`); AgentRuns record `num_turns > 0` and a non-zero
  `cost_usd`, proving live calls (not mocked).
- [ ] **(4) The fix is correct and targeted.** The remediation PR `diff` modifies
  the buggy function **`_bogo_discount` in `store/promos.py`** and adds a guard
  for the empty-qualifying-items case (so it no longer calls `min()` /
  divides / indexes an empty list).
- [ ] **(4) The agent added a regression test.** The remediation PR `diff` adds a
  test (e.g. in `store/tests.py`) that applies `BOGO` to a non-qualifying cart
  and asserts a non-500 response; `files_changed` includes a test file.
- [ ] **(3) The agent's reasoning is visible.** The remediation AgentRun's
  streamed `output` references the traceback / `promos.py` and the chosen fix
  (evidence of genuine root-cause reasoning, not a blind patch).

## Orchestration (15) — is the run durable and repeatable?

- [ ] **(4) Workflow-driven.** `GET {base}/orchestration/` returns 200 and lists
  workflow runs for import, deploy, feature, and remediation (Temporal-backed).
- [ ] **(4) Stable service contracts.** The flow goes through
  `orchestration/service.py` (`import_project`, `deploy`, `run_feature_agent`,
  `run_ci`, `remediate`) — each step is one call, not ad-hoc glue.
- [ ] **(4) Repeatable.** Re-running the demo sequence produces the same outcome:
  a fresh `BOGO` trigger again opens an incident that reaches `resolved` with a
  merged remediation PR (the trigger is deterministic).
- [ ] **(3) Self-narrating.** `GET {base}/feed/` returns 200 and the activity feed
  contains ordered events covering deploy → incident → agent → pr → merge →
  resolved, so the run explains itself.

---

### How to grade quickly

1. `curl -s -o /dev/null -w "%{http_code}" {base}/` → expect 200.
2. From the project page, read the prod `env_pk`; `curl {base}/d/<env_pk>/` →
   200 + contains `PocketShop`.
3. `curl "{base}/d/<env_pk>/checkout/?promo=BOGO"` (after adding an item) →
   500 pre-fix, 200 post-fix.
4. Open `{base}/obs/incidents/` → find the BOGO incident → confirm
   `status = resolved` and follow its remediation PR link.
5. On the PR page, read the `diff` → confirm it touches `store/promos.py`
   `_bogo_discount` **and** adds a test, with `ci_status = passed`,
   `status = merged`.
6. Open the remediation AgentRun → confirm `kind = remediation`,
   model = `claude-opus-4-8`, `num_turns > 0`, and output references the
   traceback.
