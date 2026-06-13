/**
 * name_product.workflow.js — generate-and-filter naming workflow.
 *
 * GENERATE: 5 generators, each with a distinct naming strategy, fan out
 *   candidates in parallel (diversity > redundancy).
 * FILTER:   dedupe, then vet EACH candidate independently and concurrently —
 *   web-search for collisions with existing developer-tool/company brands,
 *   score on brandability/relevance/memorability/availability, and hard-kill
 *   anything that collides with a known product.
 * RANK:     drop killed names, sort by composite score, return the top vetted
 *   list (>= 10).
 */

export const meta = {
  name: 'name-product',
  description: 'Generate and filter product-name candidates into a ranked, vetted top-N list',
  phases: [
    { title: 'Generate', detail: '5 strategy-diverse generators' },
    { title: 'Vet', detail: 'web-checked collision + scoring per candidate' },
    { title: 'Rank', detail: 'dedupe, drop collisions, sort by composite' },
  ],
}

const PRODUCT = `
An all-in-one, AI-native autonomous software operating system for engineering teams.
A single control plane that unifies version control, CI/CD, deployments, infrastructure,
logging, metrics, and incident response — like GitHub + Vercel + PagerDuty + Datadog
mashed together — and is operated by a crew of autonomous Claude agents. A small, elite
team points it at a repo and it imports, deploys, ships features, monitors production,
and autonomously fixes incidents (error -> agent debugs in a worktree -> PR -> CI ->
merge -> redeploy). Audience: senior/elite engineers and small high-leverage teams.
Desired vibe: serious, fast, control/command, crew/orchestration, trustworthy autonomy.
Avoid cute or childish. One short, ownable word is ideal.
`

const STRATEGIES = [
  { key: 'command-control', brief: 'metaphors of command, steering, and mission control (a bridge/helm/cockpit/flight-deck feel) — the place you run everything from. Avoid the literal word "Hull".' },
  { key: 'crew-orchestration', brief: 'metaphors of a crew, conductor, or foreman directing many autonomous workers/agents in concert.' },
  { key: 'forge-shipyard', brief: 'metaphors of building, shipping, and maintaining vessels/structures — foundry, shipyard, drydock, atelier — evoking software being built and shipped.' },
  { key: 'coined-latin-greek', brief: 'invented/coined words and Latin/Greek roots that sound modern, short, and brandable (2-3 syllables), suggesting autonomy, order, or sentience.' },
  { key: 'abstract-techy', brief: 'short abstract tech-brand words (think Linear/Vercel/Stripe energy) — clean, ownable, easy to say and spell, not necessarily literal.' },
]

const GEN_SCHEMA = {
  type: 'object',
  required: ['names'],
  properties: {
    names: {
      type: 'array',
      items: {
        type: 'object',
        required: ['name', 'rationale'],
        properties: {
          name: { type: 'string' },
          rationale: { type: 'string' },
          tagline: { type: 'string' },
        },
      },
    },
  },
}

const VET_SCHEMA = {
  type: 'object',
  required: ['name', 'keep', 'composite', 'scores', 'collision', 'one_liner'],
  properties: {
    name: { type: 'string' },
    keep: { type: 'boolean', description: 'false if it hard-collides with a known dev-tool/company brand or is otherwise unusable' },
    collision: { type: 'boolean' },
    collision_note: { type: 'string', description: 'the colliding product/company, if any' },
    scores: {
      type: 'object',
      required: ['brandability', 'relevance', 'memorability', 'availability'],
      properties: {
        brandability: { type: 'number', description: '0-10 ownable/clean/easy to say+spell' },
        relevance: { type: 'number', description: '0-10 fit to an autonomous eng control plane' },
        memorability: { type: 'number', description: '0-10 sticky/distinctive' },
        availability: { type: 'number', description: '0-10 likely .com/.dev + trademark headroom (10 = wide open)' },
      },
    },
    composite: { type: 'number', description: 'weighted 0-10 overall' },
    one_liner: { type: 'string', description: 'a crisp positioning line using the name' },
  },
}

// ---- GENERATE -------------------------------------------------------------
phase('Generate')
const generated = await parallel(
  STRATEGIES.map((s) => () =>
    agent(
      `You are naming a software product. Product:\n${PRODUCT}\n\n` +
      `Use ONLY this strategy: ${s.brief}\n\n` +
      `Propose 8 distinct candidate names in this strategy. Prefer single words. ` +
      `For each, give a one-sentence rationale and an optional tagline. Avoid names ` +
      `you know are taken by major developer tools/companies (e.g. Hull, Vercel, ` +
      `Railway, Render, Fly, Pulumi, Terraform, Temporal, Argo, Flux, Harness, ` +
      `Backstage, Spinnaker, Nomad, Dagger, Earthly, Sentry, Datadog, PagerDuty).`,
      { label: `gen:${s.key}`, phase: 'Generate', schema: GEN_SCHEMA },
    ),
  ),
)

// Dedupe candidates by lowercased name.
const seen = new Map()
for (const g of generated.filter(Boolean)) {
  for (const n of g.names || []) {
    const key = (n.name || '').trim().toLowerCase()
    if (key && !seen.has(key)) seen.set(key, n)
  }
}
const candidates = [...seen.values()]
log(`generated ${candidates.length} unique candidates from ${STRATEGIES.length} strategies`)

// Cap how many we pay to vet (keep the first ~28 unique).
const toVet = candidates.slice(0, 28)
if (candidates.length > toVet.length) log(`vetting first ${toVet.length} of ${candidates.length}`)

// ---- VET (filter) ---------------------------------------------------------
phase('Vet')
const vetted = await parallel(
  toVet.map((c, i) => () =>
    agent(
      `Vet this product-name candidate: "${c.name}" (proposed rationale: ${c.rationale}).\n\n` +
      `Product:\n${PRODUCT}\n\n` +
      `Use web search to check whether "${c.name}" is already a notable software/` +
      `developer-tools product, company, or trademark. If it clearly collides with a ` +
      `known dev-tools/cloud/AI product or major company, set collision=true and ` +
      `keep=false (be strict — when in doubt about a real collision, kill it). ` +
      `Then score 0-10 on brandability, relevance, memorability, and availability ` +
      `(domain/trademark headroom), compute a weighted composite (relevance 0.30, ` +
      `brandability 0.30, memorability 0.20, availability 0.20), and give a crisp ` +
      `one-liner positioning the product with this name.`,
      { label: `vet:${c.name}`.slice(0, 40), phase: 'Vet', schema: VET_SCHEMA },
    ),
  ),
)

// ---- RANK -----------------------------------------------------------------
phase('Rank')
const survivors = vetted
  .filter(Boolean)
  .filter((v) => v.keep && !v.collision)
  .sort((a, b) => (b.composite || 0) - (a.composite || 0))

// If strict filtering left fewer than 10, backfill with the next-best
// non-colliding (or least-risky) candidates so we always return >= 10.
let ranked = survivors
if (ranked.length < 10) {
  const extra = vetted
    .filter(Boolean)
    .filter((v) => !ranked.includes(v))
    .sort((a, b) => (b.composite || 0) - (a.composite || 0))
  ranked = ranked.concat(extra).slice(0, Math.max(10, ranked.length))
}

const top = ranked.slice(0, 12).map((v, i) => ({
  rank: i + 1,
  name: v.name,
  composite: Math.round((v.composite || 0) * 10) / 10,
  scores: v.scores,
  collision: v.collision,
  collision_note: v.collision_note || '',
  one_liner: v.one_liner,
}))

return {
  generated: candidates.length,
  vetted: vetted.filter(Boolean).length,
  survived_strict: survivors.length,
  ranked: top,
}
