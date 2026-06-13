# Enterprise app — integrator wiring (3 lines, all in integrator-owned files)

This app is self-contained under `enterprise/`. To activate it the integrator
must make these additive changes (the builder is not allowed to edit these
shared files):

1. **`helm/settings.py`** — add `"enterprise"` to `INSTALLED_APPS`
   (after the other Hull apps, e.g. after `"orchestration"`).

2. **`helm/urls.py`** — add the route include:
   ```python
   path("enterprise/", include("enterprise.urls")),
   ```

3. **`templates/base.html`** (optional, recommended) — add a sidebar nav link:
   ```html
   <a class="nav-item" href="/enterprise/settings/" data-match="^/enterprise">
     <span class="ico">⚙</span> Enterprise</a>
   ```

4. **Migrations** — the integrator runs `python manage.py makemigrations`
   (already passes `--check --dry-run` clean — `enterprise/migrations/0001_initial.py`
   is hand-written and matches the model state) and `python manage.py migrate`.

No new dependencies. No new CSS file (uses `static/css/helm.css`).
No context processor registered (the `can` filter is an app-local template tag:
`{% load enterprise_extras %}`).

## What this app provides
- `enterprise.services.record_audit(...)` — single, loop-safe audit write path
  (never raises; defaults `actor="system"`, `org=None` for autonomous-loop calls).
- `enterprise.services.create_api_key / verify_api_key / revoke_api_key`.
- `enterprise.rbac` — `ROLE_RANK`, `has_role` (fail-open), `role_required`.
- `enterprise.auth` — Bearer/X-Api-Key auth + session-less `GET /enterprise/api/whoami/`.
- UI: `/enterprise/settings/`, `/enterprise/keys/`, `/enterprise/audit/`.

## Cross-app usage example (e.g. from observability after opening an incident)
```python
from enterprise.services import record_audit
record_audit("incident.opened", org=incident.project.org, target=incident)
```
This is safe to call from the autonomous loop with no request/org — it will
record `actor="system"`, `org=None` and will never raise.
