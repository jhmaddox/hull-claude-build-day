/**
 * build_helm.workflow.js — the dynamic Claude Code workflow that builds Helm.
 *
 * This is the orchestration that produced this repo, captured so another team
 * can rerun it tomorrow on a new problem. The shape is:
 *
 *   1. One agent lays a FOUNDATION (schema + service contracts + UI shell).
 *      Everything downstream depends only on the *contracts*, never on each
 *      other's code — that is what makes the fan-out safe.
 *   2. Four agents build disjoint vertical SLICES in parallel (own app dirs).
 *   3. An integrator wires them, runs migrations, and boots the stack.
 *   4. A grader runs the machine-checkable rubric (rubric.md) against the live
 *      system and loops back any failures as fix tasks until the rubric passes.
 *
 * "Done" is verifiable by the model with no human: a responding URL + a green
 * rubric. Run with:  Workflow({ scriptPath: "workflows/build_helm.workflow.js" })
 */

export const meta = {
  name: 'build-helm',
  description: 'Build the Helm control plane via contract-first parallel slices, then grade against the rubric',
  phases: [
    { title: 'Foundation', detail: 'schema, service contracts, UI shell' },
    { title: 'Slices', detail: '4 disjoint vertical slices in parallel' },
    { title: 'Integrate', detail: 'wire, migrate, boot, smoke-test' },
    { title: 'Grade', detail: 'run rubric.md against the live system; loop fixes' },
  ],
}

const RUBRIC = 'rubric.md'

const SLICES = [
  { key: 'A', dirs: 'projects/ deploys/',          goal: 'import a repo, detect runtime, process-managed deployments behind a reverse proxy with public URLs' },
  { key: 'B', dirs: 'agents/ vcs/',                goal: 'git worktrees + headless `claude -p` agents (streamed live) and a git-backed PR/diff/merge UI' },
  { key: 'C', dirs: 'observability/ orchestration/', goal: 'log/metric ingestion + traceback->incident detection + Temporal workflows (threaded fallback) incl. the autonomous remediate loop' },
  { key: 'D', dirs: 'sample_apps/pocketshop/',     goal: 'a realistic legacy Django storefront with one deterministic planted bug, plus brief.md + rubric.md' },
]

const CONTRACT_SCHEMA = {
  type: 'object',
  required: ['summary', 'files', 'deviations'],
  properties: {
    summary: { type: 'string' },
    files: { type: 'array', items: { type: 'string' } },
    deviations: { type: 'string', description: 'any departures from CONTRACTS.md' },
    integration_notes: { type: 'string' },
  },
}

// 1. Foundation — must finish before any slice; it freezes the contracts.
phase('Foundation')
await agent(
  `Create the Helm Django skeleton: 7 apps, the full data model (Project, Environment, ` +
  `Deployment, Worktree, AgentRun, PullRequest, LogLine, MetricPoint, Incident), a ` +
  `service-contract stub per app (*/services.py with exact signatures + docstrings), ` +
  `the design-system CSS + base.html, the dashboard, and CONTRACTS.md documenting all ` +
  `of it. Migrate clean. The point: downstream agents depend ONLY on CONTRACTS.md.`,
  { label: 'foundation', schema: CONTRACT_SCHEMA },
)

// 2. Slices — fully parallel; each owns disjoint dirs, codes against the stubs.
phase('Slices')
const built = await parallel(
  SLICES.map((s) => () =>
    agent(
      `Read CONTRACTS.md. Build slice ${s.key} (${s.dirs}) implementing the stubs for: ` +
      `${s.goal}. Touch ONLY your dirs. Do not edit helm/, base.html, the CSS, other apps, ` +
      `or run the global migrate. Validate with \`python manage.py check\`. ` +
      `Return the contract object.`,
      { label: `slice-${s.key}`, phase: 'Slices', schema: CONTRACT_SCHEMA, isolation: 'worktree' },
    ),
  ),
)
const ok = built.filter(Boolean)
log(`slices complete: ${ok.length}/${SLICES.length}`)

// 3. Integrate — single agent merges slice worktrees, migrates, boots, smoke-tests.
phase('Integrate')
const INTEGRATION = {
  type: 'object',
  required: ['boots', 'failures'],
  properties: {
    boots: { type: 'boolean' },
    failures: { type: 'array', items: { type: 'string' } },
    notes: { type: 'string' },
  },
}
let integ = await agent(
  `Merge the four slice worktrees into the main tree. Run \`makemigrations\` + ` +
  `\`migrate\`, \`python manage.py check\`, and boot \`runserver\`. Curl the dashboard ` +
  `and every app index. Fix import/URL/template wiring errors until the stack boots ` +
  `cleanly. Report whether it boots and any remaining failures.`,
  { label: 'integrate', schema: INTEGRATION },
)

// 4. Grade — run the machine-checkable rubric; loop fixes until it passes (max 4 rounds).
phase('Grade')
const GRADE = {
  type: 'object',
  required: ['passed', 'failed'],
  properties: {
    passed: { type: 'array', items: { type: 'string' } },
    failed: { type: 'array', items: { type: 'object', properties: {
      item: { type: 'string' }, why: { type: 'string' }, fix: { type: 'string' },
    } } },
  },
}
let round = 0
let grade = { failed: [{ item: 'init', why: 'not yet run', fix: '' }] }
while (grade.failed.length && round < 4) {
  round++
  grade = await agent(
    `Run \`python manage.py helm_demo --break\` and grade the LIVE system against every ` +
    `assertion in ${RUBRIC}. For each item return pass/fail with how you checked it. ` +
    `An item passes only if objectively verified (HTTP 200 from the URL, green CI, an ` +
    `Incident that reached status=resolved with a merged remediation PR).`,
    { label: `grade-r${round}`, phase: 'Grade', schema: GRADE },
  )
  log(`round ${round}: ${grade.passed?.length || 0} pass / ${grade.failed.length} fail`)
  if (!grade.failed.length) break

  // Fan a fix agent at each failing rubric item, in parallel.
  await parallel(
    grade.failed.map((f) => () =>
      agent(
        `Rubric item FAILED: "${f.item}". Why: ${f.why}. Suggested fix: ${f.fix}. ` +
        `Make the minimal change to make this assertion pass, then re-verify it locally.`,
        { label: `fix:${f.item}`.slice(0, 40), phase: 'Grade' },
      ),
    ),
  )
}

return {
  built: ok.length,
  boots: integ.boots,
  rubricRounds: round,
  rubricPassed: !grade.failed.length,
  passed: grade.passed || [],
  stillFailing: grade.failed || [],
}
