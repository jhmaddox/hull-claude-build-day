/**
 * backlog.workflow.js — IDEMPOTENT, backlog-driven build for Hull.
 *
 * The source of truth is a per-section markdown backlog: docs/backlog/<section>.md
 * with checkbox tickets:
 *     - [ ] DEP-3: <title> — <detail>   (acceptance: <how to verify>)
 *     - [x] DEP-1: <title>   (done: <note>)
 *
 * Each section runs the same loop, in parallel, on its OWN app dir:
 *   REFINE  read the code + the backlog (+ docs/prd/<section>.md if present).
 *           Create the backlog file if missing (seed tickets from the PRD/vision).
 *           Tick [x] every ticket already satisfied by the current code — so
 *           completed work is NEVER redone. Reprioritize open tickets.
 *   BUILD   implement the next N OPEN tickets (top of file). Tick them [x] with a
 *           note when done AND self-verified. Do not touch other dirs / shared
 *           files / migrations / git. Report wiring notes.
 *   QA      adversarially verify the tickets just built; reopen ([ ]) any that
 *           don't hold, with a fix hint.
 * Then one INTEGRATE agent wires shared files, migrates, tests, boots, and
 * regression-gates the autonomous loop. The mayor commits.
 *
 * Re-running is safe: done tickets stay done; agents only pick up open ones.
 *
 * args: { sections?: string[], maxPerSection?: number, qa_rounds?: number }
 */

export const meta = {
  name: 'hull-backlog',
  description: 'Idempotent backlog-driven sprint: refine (tick done) -> build next open tickets -> adversarial QA -> integrate',
  phases: [
    { title: 'Refine', detail: 'reconcile backlog with code; tick done' },
    { title: 'Build', detail: 'implement next open tickets per section' },
    { title: 'QA', detail: 'adversarially verify; reopen failures' },
    { title: 'Integrate', detail: 'wire, migrate, test, boot, gate loop' },
  ],
}

// Section -> the app dir(s) it owns. New sections can be added freely.
const SECTION_OWNS = {
  deploys: 'deploys/',
  vcs: 'vcs/',
  observability: 'observability/',
  oncall: 'oncall/',
  agents: 'agents/',
  orchestration: 'orchestration/',
  issues: 'issues/',
  wiki: 'wiki/',
  enterprise: 'enterprise/',
  accounts: 'accounts/',
  projects: 'projects/',
  core: 'core/',
  'sample-app': 'sample_apps/',
}

const ALL = Object.keys(SECTION_OWNS)
// Sprint 3 default target (hardcoded so a dropped `args` can't silently run ALL
// sections). Override via args.sections. These are exactly the sections we
// seeded docs/backlog/*.md for this sprint.
const DEFAULT_SECTIONS = ['projects', 'sample-app', 'issues', 'orchestration', 'observability']
const sections = (args && Array.isArray(args.sections) && args.sections.length) ? args.sections : DEFAULT_SECTIONS
const MAX = (args && args.maxPerSection) || 6
const QA_ROUNDS = (args && args.qa_rounds) || 2

log(`backlog sprint over ${sections.length} sections (≤${MAX} tickets each): ${sections.join(', ')}`)

const ctx =
  `Repo: /Users/james/dev/claude-hackathon (Django, package codename "helm"). Read docs/ROADMAP.md, ` +
  `CONTRACTS.md, and (if present) docs/prd/<section>.md. Multitenancy: tenant models subclass ` +
  `accounts.models.OrgScopedModel; scope request paths via accounts.scoping; org stays nullable so the ` +
  `autonomous incident->fix loop (no request) keeps working. HARD RULE: never break that loop ` +
  `(orchestration.service / deploys.services / observability.services / agents.services contracts stay ` +
  `intact; keep changes additive with fallbacks). Match static/css/helm.css; extend base.html via ` +
  `{% extends %} only. Do NOT git add/commit/push — the integrator commits. Do NOT run makemigrations/` +
  `migrate — the integrator does all migrations.`

const REFINE_SCHEMA = {
  type: 'object', required: ['backlog_path', 'open_count', 'done_count'],
  properties: {
    backlog_path: { type: 'string' },
    summary: { type: 'string' },
    open_count: { type: 'number' }, done_count: { type: 'number' },
    next_open: { type: 'array', items: { type: 'string' }, description: 'ids of the next open tickets to build' },
  },
}
const BUILD_SCHEMA = {
  type: 'object', required: ['built_ticket_ids', 'self_check_passed'],
  properties: {
    built_ticket_ids: { type: 'array', items: { type: 'string' } },
    summary: { type: 'string' },
    self_check_passed: { type: 'boolean' },
    wiring_notes: { type: 'string' },
  },
}
const QA_SCHEMA = {
  type: 'object', required: ['verified_ids', 'reopened'],
  properties: {
    verified_ids: { type: 'array', items: { type: 'string' } },
    reopened: { type: 'array', items: { type: 'object', properties: {
      id: { type: 'string' }, problem: { type: 'string' }, fix_hint: { type: 'string' } } } },
  },
}

function worker(section) {
  const owns = SECTION_OWNS[section]
  const backlog = `docs/backlog/${section}.md`
  return async () => {
    // REFINE — reconcile the backlog with reality (idempotency lives here).
    const refine = await agent(
      `${ctx}\n\nSection "${section}" (owns ${owns}). You are the PM/maintainer of its backlog at ${backlog}.\n` +
      `1) If ${backlog} does NOT exist, CREATE it: read docs/prd/${section}.md (if present) + the code and seed a ` +
      `prioritized checkbox backlog of build tickets toward the ROADMAP vision. Ticket format: ` +
      `"- [ ] ${section.toUpperCase()}-<n>: <title> — <detail> (acceptance: <objective check>)".\n` +
      `2) RECONCILE: for every ticket, inspect ${owns} and tick "- [x]" any that the current code ALREADY ` +
      `satisfies (append " (done: <evidence>)"). This is what makes re-runs safe — never rebuild done work.\n` +
      `3) Reprioritize remaining open tickets (most valuable first) and return the ids of the next ${MAX} open ones.`,
      { label: `refine:${section}`, phase: 'Refine', schema: REFINE_SCHEMA },
    )
    if (!refine || !(refine.open_count > 0)) {
      return { section, built: [], note: 'no open tickets — nothing to do' }
    }
    // BUILD + QA loop over the next open tickets.
    let reopened = []
    let built = []
    for (let round = 1; round <= QA_ROUNDS + 1; round++) {
      const fix = reopened.length
        ? `\n\nREWORK round ${round}: a reviewer reopened these — fix them:\n` +
          reopened.map((r) => `- ${r.id}: ${r.problem}${r.fix_hint ? ' | ' + r.fix_hint : ''}`).join('\n')
        : ''
      const b = await agent(
        `${ctx}\n\nSection "${section}" (OWN ONLY ${owns}). Open ${backlog} and implement the next ${MAX} ` +
        `OPEN ("- [ ]") tickets, top first. For each: implement it in ${owns}, then tick it "- [x]" in ` +
        `${backlog} with " (done: <note>)". Do NOT touch other sections' dirs or shared files (helm/settings.py, ` +
        `helm/urls.py, templates/base.html, accounts/models.py) — report those in wiring_notes. Run ` +
        `\`python manage.py check\`. Return the ticket ids you completed.${fix}`,
        { label: `build:${section}#${round}`, phase: 'Build', schema: BUILD_SCHEMA },
      )
      built = (b && b.built_ticket_ids) || built
      const qa = await agent(
        `${ctx}\n\nADVERSARIAL QA for section "${section}". For each ticket id just marked done in ${backlog} ` +
        `(${(built || []).join(', ') || 'recent'}), verify via the code + git diff that its acceptance truly holds; ` +
        `try to break it (missing org-scoping, broken templates, regressions to the loop). Run ` +
        `\`python manage.py check\`. Reopen (set "- [ ]" again in ${backlog}, with a note) any ticket that fails, ` +
        `and return verified ids + reopened list.`,
        { label: `qa:${section}#${round}`, phase: 'QA', schema: QA_SCHEMA },
      )
      reopened = (qa && qa.reopened) || []
      if (!reopened.length) break
      log(`${section}: QA round ${round} reopened ${reopened.length}`)
    }
    return { section, built, reopened: reopened.length }
  }
}

phase('Refine')
const results = (await parallel(sections.map((s) => worker(s)))).filter(Boolean)

phase('Integrate')
const built = results.filter((r) => r.built && r.built.length)
const synth = await agent(
  `${ctx}\n\nINTEGRATOR. Sections that built tickets this run: ` +
  `${built.map((r) => `${r.section}(${r.built.length})`).join(', ') || 'none'}. ` +
  `1) Wire shared files for any NEW apps/urls/nav/deps (INSTALLED_APPS, helm/urls.py, base.html, requirements.txt). ` +
  `2) \`python manage.py makemigrations\` then \`migrate\`; fix issues. 3) \`python manage.py check\` + \`pytest -q\` ` +
  `+ \`python manage.py test\`; fix breakages. 4) Boot runserver on :8000, curl the touched sections + dashboard, fix 500s. ` +
  `5) REGRESSION GATE: confirm the autonomous incident->fix loop still imports + the tests/ loop tests pass. ` +
  `Return pass/fail for check/migrations/tests/boot/loop and any problems.`,
  { label: 'integrate', phase: 'Integrate', schema: {
    type: 'object', required: ['check_ok', 'migrations_ok', 'tests_ok', 'boot_ok', 'loop_intact'],
    properties: { check_ok: { type: 'boolean' }, migrations_ok: { type: 'boolean' }, tests_ok: { type: 'boolean' },
      boot_ok: { type: 'boolean' }, loop_intact: { type: 'boolean' }, problems: { type: 'array', items: { type: 'string' } }, summary: { type: 'string' } } },
  },
)

return {
  sections: results.map((r) => ({ section: r.section, built: (r.built || []).length, reopened: r.reopened || 0, note: r.note })),
  integration: synth,
}
