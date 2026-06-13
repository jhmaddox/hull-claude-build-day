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
const WIDE = {
  goal: 'Build-out: make every section org-scoped (multitenant) and ship its features in parallel, on top of the accounts tenancy contract. NEVER break the autonomous incident->fix loop (keep additive + fallbacks).',
  qa_rounds: 2,
  workstreams: [
    { key: 'accounts', title: 'Accounts & User Management', owns: 'accounts/ (extend the existing skeleton)',
      pm_focus: 'Enterprise org/user management: members list + role management, invitations (create/accept), org settings, profile, an org switcher for the top nav.',
      build_brief: 'Extend the existing accounts app (Org/Membership/Invitation already exist): members management page (list, change role, remove), invitation create + accept flow, org settings page, and an org-switcher fragment for base.html (report the nav include as a wiring note). Use Membership.role for permissions. Own ONLY accounts/.' },
    { key: 'projects', title: 'Projects (multitenant)', owns: 'projects/',
      pm_focus: 'Org-scoped projects: every project belongs to an org; list/detail/import all scoped to request.org; nicer multi-project UX.',
      build_brief: 'Make projects.Project org-scoped: subclass accounts.models.OrgScopedModel (adds org FK) and set org=request.org on create; scope ALL project views with accounts.scoping (for_org / scoped). Keep import_project working (default org when none). Own ONLY projects/.' },
    { key: 'deploys', title: 'Docker-Compose Deploys + Custom Domains', owns: 'deploys/',
      pm_focus: 'Complex apps: each env runs as a Docker Compose stack (web+Postgres+worker+Redis). Per-env env-vars/secrets. Custom domain per project/env (hostname, not path) + Caddy on-demand TLS. Deploy history + rollback.',
      build_brief: 'Add a compose deploy mode to deploys (web+postgres+worker+redis), autodetected (Dockerfile/compose if present else generated). Add per-env EnvVar/secret config + a Domain model (env -> hostname like <project>-<env>.apps.dev-reservclaims.com, plus optional custom hostname) and a Caddy on-demand-TLS integration (serve a /caddy/ask allowlist + a hostname->port map view). Org-scope Environment/Deployment. CRITICAL: keep the existing subprocess deploy path as default fallback (HELM_DEPLOY_MODE=process|compose, default process) so the live loop is unbroken. Own ONLY deploys/.' },
    { key: 'agents', title: 'Agents (multitenant + UX)', owns: 'agents/',
      pm_focus: 'Org-scoped agent runs + a great live agent console; agent roster/types.',
      build_brief: 'Org-scope agents.Worktree/AgentRun (org FK; scope views). Polish the agent run live console (streaming output, status, cost, linked PR/incident) and an agents roster page. Keep run_agent/launch_agent contracts intact (the loop depends on them). Own ONLY agents/.' },
    { key: 'vcs', title: 'Pull Requests (multitenant + UX)', owns: 'vcs/',
      pm_focus: 'Org-scoped PRs + richer review UX (diff, CI status, merge, links).',
      build_brief: 'Org-scope vcs.PullRequest (org FK; scope views). Improve PR list/detail (better diff rendering, CI badges, links to issues/incidents). Keep open_pull_request/merge_pull_request contracts intact. Own ONLY vcs/.' },
    { key: 'observability', title: 'Observability v2 (Datadog-level)', owns: 'observability/',
      pm_focus: 'Structured log search/filter, metrics rollups (req rate, error rate, p50/p95/p99, throughput), live dashboards, Monitors (threshold -> incident).',
      build_brief: 'Additively extend observability (do NOT change ingest_line/Incident contracts the loop uses): org-scope LogLine/MetricPoint/Incident; add metric rollups + p50/p95/p99; a log search/filter view; a dashboards view (HTMX-polled, lightweight inline SVG charts, no heavy JS); a Monitor model whose threshold breach opens an Incident via the existing open_or_update_incident. Own ONLY observability/.' },
    { key: 'orchestration', title: 'Agent Org & Orchestration UI', owns: 'orchestration/',
      pm_focus: 'Surface the agent org in-product: workflow/sprint runs, live agent activity, the autonomous-build story.',
      build_brief: 'Org-scope orchestration.WorkflowRun; build an Agent Org page showing workflow/sprint runs with status + drill-in to agents, and a live activity view. Keep the service.py contracts (remediate/run_ci/deploy/run_feature_agent) intact. Own ONLY orchestration/.' },
    { key: 'issues', title: 'Issues (Jira)', owns: 'issues/ (NEW app)',
      pm_focus: 'Boards, tickets (type/status/priority/assignee/labels), sprints, ticket detail with comments + activity, links to PRs/incidents/commits. The agent backlog lives here.',
      build_brief: 'Create a NEW org-scoped `issues` app: Board, Ticket, Sprint, Comment, Label (all subclass OrgScopedModel where tenant data); kanban board + backlog + ticket detail (HTMX status changes). Link Ticket to vcs.PullRequest and observability.Incident (nullable FKs). Provide issues.services.create_ticket(org, ...) so agents can file tickets. Own ONLY issues/.' },
    { key: 'wiki', title: 'Docs / Wiki', owns: 'wiki/ (NEW app)',
      pm_focus: 'Spaces, hierarchical markdown pages, search, page history, knowledge vault, linking to code/PRs/incidents.',
      build_brief: 'Create a NEW org-scoped `wiki` app: Space, Page (markdown body, parent for hierarchy, slug, updated_at). Server-side markdown render, page tree nav, simple search, HTMX edit-in-place. Subclass OrgScopedModel. Own ONLY wiki/.' },
    { key: 'oncall', title: 'Incidents v2 (PagerDuty-level)', owns: 'oncall/ (NEW app)',
      pm_focus: 'Severities, on-call schedules, escalation policies, incident timeline, ack/resolve, postmortems, alert routing — wired to the autonomous remediation loop.',
      build_brief: 'Create a NEW org-scoped `oncall` app: Schedule, EscalationPolicy, OnCallShift, Postmortem, IncidentTimelineEvent (FK to observability.Incident; do NOT modify Incident schema). Render an incident timeline + ack/resolve + postmortem editor (as fragments linkable from the incident page). Subclass OrgScopedModel. Own ONLY oncall/.' },
    { key: 'enterprise', title: 'Enterprise (RBAC, Audit, API keys)', owns: 'enterprise/ (NEW app)',
      pm_focus: 'RBAC enforcement helpers (by Membership.role), an audit log of org actions, API keys for programmatic access, org settings.',
      build_brief: 'Create a NEW org-scoped `enterprise` app: AuditLogEntry (actor, org, action, target, ts) + a record_audit() helper; ApiKey (hashed, scoped to org) + a simple key-auth helper; a permissions module mapping Membership.role -> capabilities + a require_role decorator. Audit log + API keys management UI. Own ONLY enterprise/.' },
  ],
}

// Targeted follow-up: finish the two workstreams that didn't fully pass QA.
const FIX_OPS = {
  goal: 'Close the remaining rubric gaps in Observability v2 and Incidents v2 (oncall) from the build-out; keep all existing functionality and the autonomous loop intact.',
  qa_rounds: 3,
  workstreams: WIDE.workstreams
    .filter((w) => ['observability', 'oncall'].includes(w.key))
    .map((w) => ({
      ...w,
      build_brief:
        w.build_brief +
        ` NOTE: this app ALREADY EXISTS from the prior sprint — do NOT rebuild from scratch. Read ` +
        `docs/prd/${w.key}.md and the current code, then COMPLETE only the rubric items not yet satisfied. ` +
        `Preserve every working feature and the autonomous loop.`,
    })),
}

// Sprint 2: make deployments REAL (compose + custom domains, no /d/<pk>/ paths)
// on the same host as the control plane, plus manual create-flows + dashboard scoping.
const SPRINT2 = {
  goal: 'Make deployments real: Docker-Compose by default + a unique custom DOMAIN per environment (host-based routing + Caddy on-demand TLS), retiring the /d/<pk>/ path as the primary URL. Deployments run on the control-plane host (the EC2 box). Plus manual New-PR and Create-Incident flows and dashboard org-scoping. NEVER break the autonomous incident->fix loop (keep the /d/<pk>/ path proxy + the process runtime fallback working).',
  qa_rounds: 2,
  workstreams: [
    {
      key: 'deploys', title: 'Real Deployments: Compose + Custom Domains', owns: 'deploys/',
      pm_focus: 'Every environment deploys as a Docker-Compose stack (when Docker present) and is reachable at a real hostname like <project-slug>-<env>.apps.dev-reservclaims.com with Caddy on-demand TLS — NOT a /d/<pk>/ path. Deploy history, env vars, domain status all visible.',
      build_brief:
        'Make deployments real on the SAME host as the control plane:\n' +
        '1) Default Environment.runtime to COMPOSE when Docker is available (detect `docker` on PATH at deploy time; fall back to PROCESS if absent). Keep PROCESS as a working fallback — the autonomous loop and the existing /d/<pk>/ path proxy MUST keep working.\n' +
        '2) On a successful deploy, AUTO-PROVISION a Domain for the env: hostname=f"{project.slug}-{environment.name}.apps.dev-reservclaims.com", status=ACTIVE (wildcard *.apps.dev-reservclaims.com already points at the EC2 box). One stable hostname per environment.\n' +
        '3) Add a HostProxyMiddleware (deploys/middleware.py): if request.get_host() (minus port) matches an ACTIVE Domain, reverse-proxy the request to that deployment process/container port (reuse the existing proxy_to logic) and return; otherwise call get_response (pass through to normal Hull routing). Report the exact MIDDLEWARE settings line for the integrator (must sit just after SecurityMiddleware/Whitenoise, before CommonMiddleware).\n' +
        '4) Make Environment.public_url return https://<primary active domain>/ when one exists, else the existing /d/<pk>/ path. Update deploy templates/Open links to use it.\n' +
        '5) Ensure the Caddy on-demand TLS endpoints are correct: /deploys/tls/ask approves a host iff an ACTIVE Domain exists; /deploys/tls/hostmap returns {hostname: "127.0.0.1:<port>"} for live deployments.\n' +
        'Note: locally these hostnames will not DNS-resolve (wildcard points at EC2) — that is expected; verification happens on the VM. Own ONLY deploys/. Report settings + Caddyfile wiring notes; do not edit settings.py/helm urls/base.html yourself.',
    },
    {
      key: 'vcs', title: 'Manual New-PR flow', owns: 'vcs/',
      pm_focus: 'A user can open a Pull Request by hand from the UI (pick project + head branch + base), in addition to agent-created PRs.',
      build_brief:
        'Add a manual "New PR" UI: a form (project select, head branch, base branch defaulting to default_branch, title, description) that opens a PullRequest from an existing branch WITHOUT requiring an agent worktree. Add a vcs.services.open_pull_request_from_branch(project, head_branch, base_branch, title, description, org) helper (compute the git diff like the existing open_pull_request) and wire a "New PR" button on the PR list. Keep agent-created PRs and existing merge/CI working. Org-scope to request.org. Own ONLY vcs/.',
    },
    {
      key: 'observability', title: 'Manual Create-Incident flow', owns: 'observability/',
      pm_focus: 'A user can manually declare an incident (title, severity, project, message) that enters the same incident pipeline as auto-detected ones (timeline, on-call routing, optional remediation).',
      build_brief:
        'Add a manual "Create incident" UI on /obs/incidents/: form (project, severity, title, message). Create an Incident (status=FIRING, org=request.org) through the SAME path auto-incidents use so the on-call hook (oncall loop on_incident_opened) fires and it shows a timeline — add an observability.services.create_manual_incident(...) helper that reuses next_incident_number + emits the pagerduty Event + calls the oncall hook (do NOT change the Incident schema or the ingest_line/open_or_update_incident contracts the loop uses). Add a "Declare incident" button on the incidents list. Own ONLY observability/.',
    },
    {
      key: 'core', title: 'Dashboard org-scoping + org switcher', owns: 'core/',
      pm_focus: 'The Mission Control dashboard shows only the current org’s data; an org switcher is in the nav.',
      build_brief:
        'Scope the core dashboard queries (projects, deployments, incidents, agent runs, PRs, stats) to request.org via accounts.scoping (Model.objects.for_org(request.org) or scoped(...)); keep the global activity Event feed as-is (Event has no org). Require login on the dashboard (org_required), redirecting anon users to login. Add an org-switcher dropdown to the sidebar/topbar in core (a small included fragment is fine; if base.html must change, report it as a wiring note). Own ONLY core/.',
    },

    // -- PLANNING-ONLY this sprint: PM every other subcomponent in parallel --
    { key: 'import-loop', title: 'Agentic Import→Configure→Deploy loop', owns: 'projects/ + orchestration/ + agents/ (future)', pm_only: true,
      pm_focus: 'THE next-sprint centerpiece: import a GitHub repo -> a Temporal-durable agent inspects the repo, generates a working Dockerfile + docker-compose tuned to it, validates it builds, commits, then deploys. Must be GENERAL across Rails, Django, Node, Go, etc. — not Django-only. Today: dumb git clone + heuristic detect (manage.py/Procfile only). Spec the detection upgrades, the configure-agent prompt + validation loop, the Temporal workflow, and a deploy-failure->agent-fix loop.' },
    { key: 'agent-chat', title: 'Interactive Agent Chat sessions', owns: 'agents/ (future)', pm_only: true,
      pm_focus: 'Make launching an agent an interactive CHAT: user sends follow-up messages mid/after a run and the session continues (claude --resume or SDK), streaming live. Today: one-shot headless claude -p with a live log, no follow-ups. Spec the session-continuation model, schema (session id / parent run), and UI.' },
    { key: 'projects', title: 'Projects (repo mgmt, settings)', owns: 'projects/', pm_only: true,
      pm_focus: 'Project home as the hub: repo browser, branches, settings, environment management, connected resources. Multi-project UX, per-project config/secrets, danger-zone.' },
    { key: 'agents', title: 'Agents & the Agent Roster', owns: 'agents/', pm_only: true,
      pm_focus: 'Agent roster + run history, agent kinds (feature/remediation/ci/review/chore), cost/turn analytics, re-run, cancel, the live console. How agents surface across the product.' },
    { key: 'orchestration', title: 'Orchestration & Agent-Org UI', owns: 'orchestration/', pm_only: true,
      pm_focus: 'Surface the Gastown agent org in-product: sprint runs, workflow runs (Temporal-backed), live agent activity, PM/builder/QA hierarchy, the self-building story. Temporal Cloud visibility.' },
    { key: 'issues', title: 'Issues (Jira)', owns: 'issues/', pm_only: true,
      pm_focus: 'Jira-grade: boards, epics, sprints, ticket types/states/priorities/assignees/labels, comments, links to PRs/incidents/commits, and crucially THE AGENT BACKLOG — agents file + pick up tickets here. Spec where current impl falls short.' },
    { key: 'wiki', title: 'Docs / Wiki', owns: 'wiki/', pm_only: true,
      pm_focus: 'Knowledge vault: spaces, hierarchical pages, search, page history, links to code/PRs/incidents, auto-generated docs (e.g. postmortems land here). Spec gaps.' },
    { key: 'oncall', title: 'On-call / Incidents v2', owns: 'oncall/', pm_only: true,
      pm_focus: 'PagerDuty depth: on-call schedule UI + calendar, escalation policies, AUTO escalation tick (background/Temporal), alert routing, paging/notifications, postmortems + action items. Spec what is built vs missing (manual create, auto-tick).' },
    { key: 'enterprise', title: 'Enterprise (RBAC, Audit, API, Billing, SSO)', owns: 'enterprise/', pm_only: true,
      pm_focus: 'Enterprise-readiness: RBAC enforcement across the app (by Membership.role), audit log coverage, API keys + a public API, SSO/SAML, billing/usage. Spec the enforcement gaps and a public REST API surface.' },
    { key: 'accounts', title: 'Accounts & User Management', owns: 'accounts/', pm_only: true,
      pm_focus: 'Org/user lifecycle: invitations, member management, roles, profile, org settings, SSO-ready auth, onboarding. Spec polish + gaps.' },
  ],
}

const SPRINTS = { '1': WIDE, wide: WIDE, 'fix-ops': FIX_OPS, '2': SPRINT2 }

// --------------------------------------------------------------------------- //
const sprintKey = (args && args.sprint != null) ? String(args.sprint) : '1'
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
  `Read docs/ROADMAP.md and CONTRACTS.md first. Sprint ${sprintKey} goal: ${sprint.goal}\n` +
  `MULTITENANCY CONTRACT (already implemented in accounts/, import it — do NOT modify accounts/models.py): ` +
  `new tenant models subclass accounts.models.OrgScopedModel (gives an org FK + OrgManager); ` +
  `existing models add org by subclassing OrgScopedModel; scope request paths with accounts.scoping ` +
  `(org_required decorator, scoped(Model, request), or Model.objects.for_org(request.org)); the current ` +
  `org is on request.org (set by CurrentOrgMiddleware). Keep org nullable so the autonomous loop (which ` +
  `runs without a request) still works — services default org=None.\n` +
  `HARD RULE: never break the autonomous incident->fix loop (deploys.services / observability.services / ` +
  `orchestration.service / agents.services contracts stay intact; keep changes additive with fallbacks).\n` +
  `Match the dark UI design system in static/css/helm.css and extend base.html via {% extends %} only.`

// ---- PLAN ----------------------------------------------------------------- //
phase('Plan')
const plans = {}
const planned = await parallel(sprint.workstreams.map((w) => () =>
  agent(
    `${ctx}\n\nYou are the PRODUCT MANAGER for the "${w.title}" section (owns: ${w.owns}). ` +
    `Focus: ${w.pm_focus}\n\n` +
    (w.pm_only
      ? `This section is PLANNING-ONLY this sprint (no builder will run for it now). First READ the ` +
        `current code for ${w.owns} and the existing docs/prd/${w.key}.md if present to ground yourself ` +
        `in what already exists. Then produce a THOROUGH, well-prioritized PRD capturing the full vision ` +
        `(per docs/ROADMAP.md), an honest "current state vs target" gap list, and a prioritized backlog ` +
        `of build tickets for a FUTURE sprint. Be comprehensive, not MVP-only.`
      : `Generate-and-filter: brainstorm the full feature set, then filter to the highest-impact MVP ` +
        `achievable THIS sprint (a builder will implement your tickets immediately).`) +
    `\n\nWrite docs/prd/${w.key}.md (problem, user stories, current-state-vs-target, scope, and a ` +
    `numbered MACHINE-CHECKABLE rubric of pass/fail assertions). Return the rubric and a concrete ticket list.`,
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
      `Do NOT edit helm/settings.py, helm/urls.py, templates/base.html, accounts/models.py, or other ` +
      `workstreams' dirs — instead report needed shared-file changes in wiring_notes (INSTALLED_APPS, root ` +
      `urls include, base.html nav link, requirements). Do NOT run \`python manage.py makemigrations\` or ` +
      `\`migrate\` — only edit code; the INTEGRATOR generates ALL migrations at the end (this avoids races ` +
      `between parallel builders). ` +
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
// pm_only workstreams produced a PRD/backlog in the Plan phase and are NOT built this sprint.
const toBuild = sprint.workstreams.filter((w) => !w.pm_only)
const pmOnly = sprint.workstreams.filter((w) => w.pm_only)
if (pmOnly.length) log(`planning-only this sprint (PRD + backlog): ${pmOnly.map((w) => w.key).join(', ')}`)
// Sequential cross-cutting foundation first (e.g. tenancy), in declared order.
for (const w of toBuild.filter((w) => w.sequential)) {
  log(`sequential build: ${w.key}`)
  results.push(await buildAndQA(w))
}
// Then everything else in parallel.
const parallelWS = toBuild.filter((w) => !w.sequential)
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
