# design backlog — Sprint 3: warmer palette + input styling

Owns the global design system ONLY: static/css/helm.css and templates/base.html.
Do NOT edit individual apps' templates (a palette lives in CSS variables and
cascades everywhere). Keep the dark, premium feel — just warmer.

- [ ] DSGN-1: Warmer color palette — retune the CSS custom properties in
  helm.css toward a warmer dark theme: warm-tinted backgrounds/panels (subtle
  warm-charcoal instead of cool blue-black), a warm accent (e.g. amber/coral/terra
  instead of the cool indigo #6d8bff), warm-tinted borders/muted text. Update
  --bg/--bg-2/--panel/--panel-2/--border/--accent/--accent-2/--success/--warn/
  --danger and any gradients so the whole UI shifts warm cohesively. Keep strong
  contrast/legibility (WCOG-ish). (acceptance: helm.css accent + bg variables are
  warm-hued; dashboard/login render with the new palette; contrast remains
  readable; no per-app template edits.)
- [ ] DSGN-2: Bulletproof input styling — ensure EVERY form control is styled by
  the design system: input[type=text/url/number/password/email/search/date/tel],
  textarea, select, AND bare <input> with no type. Add a shared `.input`/`.select`
  class (some templates reference class="input") so class-based inputs are styled
  too. Style focus/placeholder/disabled states + checkboxes/radios minimally.
  (acceptance: the login password field, projects search, and a sampling of forms
  across sections all render with the themed input style — no unstyled/native
  boxes; class="input" is covered.)
- [ ] DSGN-3: Polish pass — buttons, badges, cards, and the sidebar reflect the
  warm palette cohesively (hover/active states updated). (acceptance: btn-primary
  + active nav use the warm accent; visual cohesion across components.)
