/**
 * sprint.workflow.js — the "Gastown" autonomous build org for Hull.
 *
 * The MAYOR (the human + lead in the main chat thread) is the chief PM: it
 * shapes docs/ROADMAP.md and kicks off a sprint. This script runs one sprint:
 *
 *   PLAN     section PM agents (one per workstream) read ROADMAP + code and
 *            write docs/prd/<key>.md — requirements + a MACHINE-CHECKABLE
 *            rubric + a ticket list. Strategy: generate-and-filter (propose
 *            many, filter to the sprint MVP).
 *   BUILD    builder agents implement each workstream. Cross-cutting
 *            "sequential" workstreams (e.g. tenancy) run first and in order;
 *            the rest run in parallel. Builders own DISJOINT dirs and never
 *            touch shared wiring (settings/root urls/base nav) — the integrator
 *            does. Strategy: fan-out.
 *   QA       an adversarial QA agent verifies each build against its rubric and
 *            tries to break it. On failure the builder is re-dispatched with the
 *            failures. Strategy: adversarial verification + loop-until-done.
 *   SYNTH    one integrator wires shared files, runs makemigrations + migrate +
 *            tests + boot, and confirms the autonomous incident loop is intact.
 *            Strategy: fan-out & synthesize.
 *
 * Run:  Workflow({ scriptPath: "workflows/sprint.workflow.js", args: { sprint: "0" } })
 */

export const meta = {
  name: 'hull-sprint',
  description: 'Run one autonomous build sprint for Hull (PM -> build -> adversarial QA -> synthesize)',
  phases: [
    { title: 'Plan', detail: 'section PMs: PRD + rubric + tickets' },
    { title: 'Build', detail: 'builders implement (sequential prep, then parallel)' },
    { title: 'QA', detail: 'adversarial verify vs rubric, loop until green' },
    { title: 'Synthesize', detail: 'integrate, migrate, test, boot' },
  ],
}

// --------------------------------------------------------------------------- //
// Sprint definitions. The Mayor selects one via args.sprint.
// --------------------------------------------------------------------------- //
const SPRINTS = {
  '0': {
    goal: 'Foundation: auth + multitenancy + Postgres + Docker-Compose deploys + custom domains. Must NOT break the autonomous incident->fix loop.',
    qa_rounds: 2,
    workstreams: [
      {
        key: 'tenancy', title: 'Accounts & Multitenancy', sequential: true,
        owns: 'accounts/ + a nullable org FK on existing tenant models + scoping middleware',
        pm_focus: 'Orgs, Users (Django auth), Membership with roles (owner/admin/member), invitations, signup/login/logout, org switcher, org-scoped everything, SSO-ready.',
        build_brief:
          'Create an `accounts` Django app: Org, Membership(role), Invitation; use django.contrib.auth User. ' +
          'Add a NULLABLE `org` FK to every existing tenant-scoped model (projects.Project, deploys.Environment/Deployment, agents.Worktree/AgentRun, vcs.PullRequest, observability.LogLine/MetricPoint/Incident, core.Event, orchestration.WorkflowRun) and a data migration creating a default Org "Acme Inc" and backfilling existing rows. ' +
          'Add a thread-local current-org middleware + an OrgScoped manager/mixin and a login_required + org-scoping pattern documented in accounts/scoping.py. ' +
          'Build login/signup/logout + an org switcher + members/invite pages (HTMX, base.html styling). ' +
          'Do NOT delete data or break existing views — make org optional in code paths so the autonomous loop keeps working. You MAY makemigrations for ALL apps for this workstream (you are the cross-cutting foundation), but do NOT migrate.',
      },
      {
        key: 'deploys-v2', title: 'Docker-Compose Deploys + Custom Domains', sequential: false,
        owns: 'deploys/ (services, compose builder, domain model/routing), a deploys/compose/ dir',
        pm_focus: 'Each environment runs as a Docker Compose stack (web + Postgres + worker + Redis). Per-env config/secrets. Custom domain per project/env (hostname, not path) with Caddy on-demand TLS. Deploy history + rollback.',
        build_brief:
          'Evolve deploys to optionally run an environment as a Docker Compose stack (web + postgres + worker + redis), autodetected from the repo (Dockerfile/compose if present, else a generated compose using the detected runtime). Add a Domain concept (project/env -> hostname like <project>-<env>.apps.dev-reservclaims.com, plus optional custom hostname) and a routing/registration layer that a Caddy on-demand-TLS reverse proxy can consume (e.g. Hull serves a /caddy/ask allowlist endpoint and a hostname->upstream map). Keep the EXISTING lightweight subprocess deploy path working as a fallback (HELM_DEPLOY_MODE=process|compose, default process) so the live autonomous loop is not broken. Do NOT edit settings.py/root urls/base.html — leave wiring notes for the integrator.',
      },
    ],
  },
  '1': {
    goal: 'Work & knowledge: a Jira-grade issues tracker and a Docs/Wiki, both org-scoped and linked to PRs/incidents.',
    qa_rounds: 2,
    workstreams: [
      {
        key: 'issues', title: 'Issues (Jira)', sequential: false, owns: 'issues/',
        pm_focus: 'Boards, tickets (type/status/priority/assignee/labels), sprints, ticket detail with comments + activity, links to PRs/incidents/commits. The agent backlog lives here.',
        build_brief: 'Create an `issues` Django app (org-scoped): Board, Ticket, Sprint, Comment, Label; board (kanban) + backlog + ticket detail UI (HTMX drag/status). Link tickets to vcs.PullRequest and observability.Incident. Provide a service API issues.services.create_ticket(...) so agents can file tickets. Own only issues/. Leave wiring notes.',
      },
      {
        key: 'docs', title: 'Docs / Wiki', sequential: false, owns: 'wiki/',
        pm_focus: 'Spaces, hierarchical markdown pages, search, page history, linking to code/PRs/incidents, a knowledge vault.',
        build_brief: 'Create a `wiki` Django app (org-scoped): Space, Page (markdown, parent for hierarchy, slug), simple full-text search, page tree nav + render (server-side markdown). HTMX edit-in-place. Own only wiki/. Leave wiring notes.',
      },
    ],
  },
  '2': {
    goal: 'Operations: Datadog-grade observability and PagerDuty-grade incident management, wired to the autonomous loop.',
    qa_rounds: 2,
    workstreams: [
      {
        key: 'observability-v2', title: 'Observability v2 (Datadog-level)', sequential: false, owns: 'observability/ (additive)',
        pm_focus: 'Structured logs with search/filter, metrics (req rate, error rate, p50/p95/p99 latency, throughput), live dashboards, monitors/alerts with thresholds.',
        build_brief: 'Extend observability (additively; do not remove ingest_line/Incident contracts): metrics rollups + p50/p95/p99, a log search/filter view, a dashboards view (HTMX-polled time series, lightweight inline SVG/canvas charts, no heavy JS), and a Monitor model (threshold -> fires an Incident). Own only observability/. Leave wiring notes.',
      },
      {
        key: 'incidents-v2', title: 'Incidents v2 (PagerDuty-level)', sequential: false, owns: 'oncall/ (new app) + additive incident fields via oncall',
        pm_focus: 'Severities, on-call schedules, escalation policies, incident timeline, ack/resolve, postmortems, alert routing. Wired to the autonomous remediation loop.',
        build_brief: 'Create an `oncall` Django app (org-scoped): Schedule, EscalationPolicy, OnCallShift, plus Postmortem + IncidentTimelineEvent referencing observability.Incident (FK, do not modify Incident schema). Incident detail additions via includes/fragments. Render an incident timeline + ack/resolve + postmortem editor. Own only oncall/. Leave wiring notes.',
      },
    ],
  },
}

// --------------------------------------------------------------------------- //
const sprintKey = (args && args.sprint != null) ? String(args.sprint) : '0'
const sprint = SPRINTS[sprintKey]
if (!sprint) throw new Error(`unknown sprint ${sprintKey}; have ${Object.keys(SPRINTS)}`)
const QA_ROUNDS = (args && args.qa_rounds) || sprint.qa_rounds || 2
log(`Sprint ${sprintKey}: ${sprint.goal}`)

const PM_SCHEMA = {
  type: 'object',
  required: ['summary', 'rubric', 'tickets'],
  properties: {
    summary: { type: 'string' },
    prd_path: { type: 'string' },
    rubric: { type: 'array', items: { type: 'object', required: ['id', 'assertion'], properties: {
      id: { type: 'string' }, assertion: { type: 'string' }, how_to_check: { type: 'string' } } } },
    tickets: { type: 'array', items: { type: 'object', required: ['id', 'title'], properties: {
      id: { type: 'string' }, title: { type: 'string' }, detail: { type: 'string' }, acceptance: { type: 'string' } } } },
  },
}
const BUILD_SCHEMA = {
  type: 'object', required: ['summary', 'self_check_passed'],
  properties: {
    summary: { type: 'string' },
    files_changed: { type: 'array', items: { type: 'string' } },
    self_check_passed: { type: 'boolean', description: '`python manage.py check` passes and only owned dirs were touched' },
    wiring_notes: { type: 'string', description: 'shared-file changes the integrator must make (INSTALLED_APPS, root urls, base nav, deps)' },
    notes: { type: 'string' },
  },
}
const QA_SCHEMA = {
  type: 'object', required: ['passed', 'failures'],
  properties: {
    passed: { type: 'boolean' },
    failures: { type: 'array', items: { type: 'object', required: ['problem'], properties: {
      rubric_id: { type: 'string' }, problem: { type: 'string' }, severity: { type: 'string' }, fix_hint: { type: 'string' } } } },
    notes: { type: 'string' },
  },
}
const SYNTH_SCHEMA = {
  type: 'object', required: ['check_ok', 'migrations_ok', 'tests_ok', 'boot_ok'],
  properties: {
    check_ok: { type: 'boolean' }, migrations_ok: { type: 'boolean' },
    tests_ok: { type: 'boolean' }, boot_ok: { type: 'boolean' },
    loop_intact: { type: 'boolean', description: 'the autonomous incident->fix loop still works (or untouched this sprint)' },
    problems: { type: 'array', items: { type: 'string' } }, summary: { type: 'string' },
  },
}

const ctx =
  `Repo: /Users/james/dev/claude-hackathon (Django 5 + HTMX, package codename "helm"). ` +
  `Read docs/ROADMAP.md and CONTRACTS.md first. Sprint ${sprintKey} goal: ${sprint.goal} ` +
  `HARD RULE: never break the autonomous incident->fix loop (deploys.services / observability.services / orchestration.service / agents.services). ` +
  `Match the existing dark UI design system in static/css/helm.css and extend base.html via {% extends %} only.`

// ---- PLAN ----------------------------------------------------------------- //
phase('Plan')
const plans = {}
const planned = await parallel(sprint.workstreams.map((w) => () =>
  agent(
    `${ctx}\n\nYou are the PRODUCT MANAGER for the "${w.title}" section (owns: ${w.owns}). ` +
    `Focus: ${w.pm_focus}\n\nGenerate-and-filter: brainstorm the full feature set, then filter to the ` +
    `highest-impact MVP achievable THIS sprint. Write docs/prd/${w.key}.md (problem, user stories, ` +
    `scope-in/scope-out, and a numbered MACHINE-CHECKABLE rubric of pass/fail assertions). Return the ` +
    `rubric and a concrete ticket list for the builder.`,
    { label: `pm:${w.key}`, phase: 'Plan', schema: PM_SCHEMA },
  ).then((r) => { if (r) plans[w.key] = r; return r })
))
log(`PRDs written for: ${Object.keys(plans).join(', ')}`)

// ---- BUILD + QA (loop-until-done) ----------------------------------------- //
async function buildAndQA(w) {
  const plan = plans[w.key] || { rubric: [], tickets: [] }
  const rubricText = (plan.rubric || []).map((r) => `- [${r.id}] ${r.assertion}`).join('\n')
  const ticketText = (plan.tickets || []).map((t) => `- [${t.id}] ${t.title}: ${t.detail || ''}`).join('\n')
  let failures = []
  for (let round = 1; round <= QA_ROUNDS + 1; round++) {
    const fixNote = failures.length
      ? `\n\nThis is REWORK round ${round}. A QA reviewer found these failures — fix ALL of them:\n` +
        failures.map((f) => `- (${f.severity || 'bug'}) ${f.problem}${f.fix_hint ? ' | hint: ' + f.fix_hint : ''}`).join('\n')
      : ''
    await agent(
      `${ctx}\n\nYou are a BUILDER. Implement the "${w.title}" workstream. OWN ONLY: ${w.owns}. ` +
      `Do NOT edit helm/settings.py, helm/urls.py, templates/base.html, or other workstreams' dirs — instead ` +
      `report needed shared-file changes in wiring_notes. Do NOT run \`python manage.py migrate\`. ` +
      `${w.sequential ? 'You ARE the cross-cutting foundation; you may makemigrations across apps.' : 'You may makemigrations only for your own new app.'} ` +
      `Brief: ${w.build_brief}\n\nRubric to satisfy:\n${rubricText}\n\nTickets:\n${ticketText}${fixNote}\n\n` +
      `When done, run \`python manage.py check\` and confirm you only touched owned files.`,
      { label: `build:${w.key}#${round}`, phase: 'Build', schema: BUILD_SCHEMA },
    )
    const qa = await agent(
      `${ctx}\n\nYou are an ADVERSARIAL QA reviewer for "${w.title}". Inspect the working-tree changes ` +
      `(git diff) and the code. Verify EACH rubric assertion is genuinely met; actively try to break it ` +
      `(missing org-scoping, broken templates, unhandled cases, regressions to the autonomous loop). Run ` +
      `\`python manage.py check\`. Be strict: passed=true ONLY if every rubric item holds. Return concrete failures.\n\n` +
      `Rubric:\n${rubricText}`,
      { label: `qa:${w.key}#${round}`, phase: 'QA', schema: QA_SCHEMA },
    )
    if (!qa || qa.passed || !(qa.failures && qa.failures.length)) {
      return { key: w.key, title: w.title, rounds: round, passed: !!(qa && qa.passed), open_failures: (qa && qa.failures) || [] }
    }
    failures = qa.failures
    log(`${w.key}: QA round ${round} found ${failures.length} issue(s) — reworking`)
  }
  return { key: w.key, title: w.title, rounds: QA_ROUNDS + 1, passed: false, open_failures: failures, exhausted: true }
}

phase('Build')
const results = []
// Sequential cross-cutting foundation first (e.g. tenancy), in declared order.
for (const w of sprint.workstreams.filter((w) => w.sequential)) {
  log(`sequential build: ${w.key}`)
  results.push(await buildAndQA(w))
}
// Then everything else in parallel.
const parallelWS = sprint.workstreams.filter((w) => !w.sequential)
if (parallelWS.length) {
  const r = await parallel(parallelWS.map((w) => () => buildAndQA(w)))
  results.push(...r.filter(Boolean))
}

// ---- SYNTHESIZE ----------------------------------------------------------- //
phase('Synthesize')
const wiring = results.map((r) => `### ${r.key} (${r.passed ? 'QA green' : 'QA OPEN: ' + r.open_failures.length})`).join('\n')
const synth = await agent(
  `${ctx}\n\nYou are the INTEGRATOR. The sprint's builders worked in disjoint dirs and left wiring notes ` +
  `in their PRDs / return values. Now make the whole app cohesive:\n` +
  `1. Wire shared files: add new apps to INSTALLED_APPS, include their urls in helm/urls.py, add nav links ` +
  `to templates/base.html, add any new deps to requirements.txt.\n` +
  `2. Run \`python manage.py makemigrations\` then \`migrate\`; fix any migration issues.\n` +
  `3. Run \`python manage.py check\` and \`pytest -q\` (and \`python manage.py test\` for app suites); fix breakages.\n` +
  `4. Boot \`runserver\` on port 8000 and curl the new sections + the dashboard; fix 500s.\n` +
  `5. CRITICAL regression gate: confirm the autonomous incident->fix loop is intact (the code paths in ` +
  `orchestration.service.remediate, deploys.services, observability.services, agents.services still import ` +
  `and the unit tests in tests/ pass).\n` +
  `Workstreams this sprint:\n${wiring}\n\nReturn pass/fail for check/migrations/tests/boot/loop and any problems.`,
  { label: 'integrate', phase: 'Synthesize', schema: SYNTH_SCHEMA },
)

return {
  sprint: sprintKey,
  goal: sprint.goal,
  workstreams: results.map((r) => ({ key: r.key, passed: r.passed, rounds: r.rounds, open_failures: r.open_failures.length })),
  integration: synth,
}
