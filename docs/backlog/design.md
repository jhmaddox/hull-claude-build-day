# design backlog — global design system (static/css/helm.css + templates/base.html)

Owns the global design system ONLY: static/css/helm.css and templates/base.html.
Do NOT edit individual apps' templates (a palette + shared form classes live in
CSS and cascade everywhere). Keep the dark, premium feel — just warmer and more
bulletproof. Reconciled against current helm.css (230 lines) + base.html on
2026-06-13.

## Reconciliation findings (current state)
- Palette is still the ORIGINAL COOL theme: `--bg:#0a0c11` (blue-black),
  `--accent:#6d8bff` (cool indigo), `--accent-2:#8a6dff` (purple), body radial
  gradient seeds `#141824` (cool). btn-primary hardcodes `#5a78f0`; brand-mark
  drop-shadow hardcodes `rgba(109,139,255,.6)`. → DSGN-1/3 NOT done.
- Form CSS (helm.css:164) targets only `input[type=text|url|number|password|`
  `email|search], textarea, select`. It does NOT cover: bare `<input>` (no
  type), `input[type=tel|date|time|file]`, `.input`/`.select` classes, or
  checkbox/radio. Templates actively rely on the gaps:
  `projects/list.html` (`class="input"` search), `vcs/new.html`
  (`class="input"` x4 + select), `wiki/_refs.html` (`class="input"` selects +
  bare input), and many `<input class="field" ...>` with no type across
  incidents/observability/oncall/issues — all render as UNSTYLED native boxes.
  No checkbox/radio/`accent-color` styling exists. → DSGN-2 NOT done (high value).

## Tickets (priority order)

- [x] DSGN-2: Bulletproof input styling — make EVERY form control themed. (done: broadened form selector to tel/date/time/datetime-local/month/week/file + input:not([type]) + .input/.select classes; added ::placeholder, :disabled, and accent-colored checkbox/radio sizing; appearance:none on text controls but native checkbox/radio preserved)
  Broaden the form selector to cover `input[type=text/url/number/password/`
  `email/search/date/time/tel/file]`, bare `<input>` (no type attr, e.g.
  `input:not([type])`), `textarea`, `select`, AND add shared `.input`/`.select`
  classes (templates already use `class="input"` and put `class="field"` directly
  on inputs). Style focus/placeholder/disabled states and add minimal
  checkbox/radio styling (`accent-color: var(--accent)` + sizing). Ensure a bare
  `<input class="field">` still reads as an input, not just a wrapper.
  (acceptance: projects search, vcs/new.html fields, wiki/_refs selects, and a
  `<input class="field">` all render themed — no native boxes; `class="input"`
  and bare inputs are covered; checkboxes use the accent color.)

- [x] DSGN-1: Warmer color palette (done: retuned :root to warm charcoal bg/panel/border, warm text/muted/faint, amber --accent #f0a35a + coral --accent-2 #e8745a, added --accent-rgb token, warmed body radial-gradient seed and topbar backdrop) — retune the CSS custom properties in
  helm.css toward a warmer dark theme: warm-tinted backgrounds/panels (warm
  charcoal instead of cool blue-black), a warm accent (amber/coral/terra instead
  of cool indigo #6d8bff), warm-tinted borders/muted text. Update `--bg/--bg-2/`
  `--panel/--panel-2/--border/--border-2/--accent/--accent-2/--text/--muted` and
  the body radial-gradient seed so the whole UI shifts warm cohesively. Keep
  strong contrast/legibility. (acceptance: helm.css accent + bg variables are
  warm-hued; dashboard/login render with the new palette; contrast stays
  readable; no per-app template edits.)

- [x] DSGN-3: Polish pass (done: brand-mark drop-shadow + badge-accent + focus ring now use rgba(var(--accent-rgb),...); btn-primary gradient end uses --accent-2 with warm dark text; topbar backdrop warmed; grep confirms no rgba(109,139,255 / #5a78f0 / #6d8bff literals remain) — replace remaining HARDCODED cool colors so the warm
  palette is cohesive: btn-primary gradient end (`#5a78f0`), brand-mark
  drop-shadow (`rgba(109,139,255,.6)`), and every hardcoded `rgba(109,139,255,...)`
  in badge-accent/spinner/focus-ring/nav-active. Verify btn-primary, active nav
  (inset accent bar), badges, cards, focus rings, and the sidebar gradient all
  reflect the warm accent on hover/active.
  (acceptance: no `rgba(109,139,255` or `#5a78f0`/`#6d8bff` literals remain
  outside the `:root` token block; btn-primary + active nav use the warm accent.)

- [x] DSGN-4: Form layout helpers (done: .field stays a bottom-margin wrapper and is harmless on an input; added .form-row (flex, equal columns, wraps), .form-actions (right-aligned), and .field-hint/.help muted captions) — add light helpers app forms can opt into so
  they align with the system: keep `.field` as a bottom-margin wrapper but make
  it harmless when applied directly to an input; add `.form-row`/`.form-actions`
  and a `.field-hint`/`.help` muted caption. (acceptance: a two-column form row
  and a right-aligned actions bar are achievable with classes only; no app
  template edits required to use them.)

- [x] DSGN-5: Accessible focus + reduced-motion (done: :focus-visible accent outline on links/buttons/.btn/.nav-item/.link/[tabindex]/summary, ring mirrored for inputs; @media prefers-reduced-motion neutralizes animations/transitions and stops the dot-live pulse) — ensure keyboard focus is
  visible on links/buttons/nav-items (not just inputs) via `:focus-visible`, and
  add `@media (prefers-reduced-motion: reduce)` to calm pulse/spin/transition
  animations. (acceptance: tabbing shows a clear accent focus ring on buttons and
  nav items; reduced-motion users get no pulsing dot.)

- [x] DSGN-6: Responsive sidebar/topbar (done: @media (max-width:760px) collapses .app to one column, turns sidebar into a horizontal top strip with icon-only nav (active = bottom accent bar), tightens topbar/content padding to 16px, and stacks grid-2/3/4; desktop layout untouched) — at narrow widths the 240px sidebar +
  28px content padding crowd the layout. Add `@media (max-width: 760px)` that
  collapses `.app` to a single column (sidebar becomes a top strip or hides nav
  labels) and tightens `.content`/`.topbar` padding. (acceptance: at a 600px
  viewport content is readable and nothing overflows horizontally; desktop layout
  unchanged.)
