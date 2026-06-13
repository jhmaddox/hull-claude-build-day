# sample-app backlog

Owns `sample_apps/`. Goal: ship a realistic "legacy" app that Hull imports,
deploys to staging + prod, monitors, and **auto-fixes** via the autonomous
incident→agent→PR→CI→merge→redeploy loop (the crown-jewel demo). The app must
be self-contained, deploy with no manual step, and carry a deterministic
planted bug the demo can trigger on command.

History note: an earlier backlog scoped a Node/Express "NodeShop". The section
instead shipped **PocketShop** — a polished standalone Django storefront — which
better fits Hull's deploy substrate (compose/process), the reverse-proxy
subpath contract, and the auto-fix demo. NodeShop tickets are superseded
(SAMP-1/2 below, marked obsolete) and replaced by the PocketShop ticket set.

## Done (PocketShop — reconciled against current code)

- [x] SAMPLE-APP-1: Standalone Django storefront scaffold — own manage.py,
  settings, wsgi, SQLite; runs with no dependency on Hull.
  (acceptance: `python manage.py check` clean; project boots standalone)
  (done: sample_apps/pocketshop/ with manage.py + pocketshop/{settings,urls,wsgi}.py;
  `python manage.py check` -> "no issues")
- [x] SAMPLE-APP-2: Storefront UX — home (hero + product grid), product detail,
  session cart, checkout, confirmation; own CSS, emoji art (no asset pipeline).
  (acceptance: home returns 200 listing seeded products; add->checkout->place works)
  (done: store/views.py home/product_detail/cart_view/checkout/_create_order;
  store/templates/store/{home,product,cart,checkout,confirmation,base}.html;
  store/static/store/shop.css)
- [x] SAMPLE-APP-3: Zero-step seed data — products seeded by data migration so a
  fresh deploy has data after migrate only.
  (acceptance: no manual seed step; home shows catalog post-migrate)
  (done: store/migrations/0002_seed_products.py seeds 8 products incl. "Aera
  Wireless Earbuds")
- [x] SAMPLE-APP-4: Pinned deps — minimal requirements.txt (Django 5.1 +
  WhiteNoise) so import/build is reproducible.
  (acceptance: requirements.txt pins exact versions)
  (done: requirements.txt -> Django==5.1.4, whitenoise==6.8.2)
- [x] SAMPLE-APP-5: Reverse-proxy subpath support — honors HELM_SCRIPT_NAME
  (FORCE_SCRIPT_NAME + STATIC_URL prefix), ALLOWED_HOSTS=*, CSRF from
  HELM_BASE_URL; all links via `{% url %}`.
  (acceptance: serves correctly under /d/<env_pk>/; static + form links resolve)
  (done: pocketshop/settings.py HELM_SCRIPT_NAME/FORCE_SCRIPT_NAME/STATIC_URL
  prefix + CSRF_TRUSTED_ORIGINS from HELM_BASE_URL; README "Running behind Hull")
- [x] SAMPLE-APP-6: $PORT-bindable run command + WhiteNoise static — runs via
  `runserver 0.0.0.0:$PORT` with styles even without collectstatic.
  (acceptance: README documents $PORT run; WHITENOISE_USE_FINDERS serves CSS)
  (done: README "Run it" uses $PORT; settings WHITENOISE_USE_FINDERS=True)
- [x] SAMPLE-APP-7: Green CI baseline — passing test suite covering home, cart,
  normal checkout, place-order, and a working promo.
  (acceptance: `manage.py test` all pass before the bug is triggered)
  (done: store/tests.py, 5 tests pass — verified `Ran 5 tests ... OK`)
- [x] SAMPLE-APP-8: Deterministic planted bug for the auto-fix loop — promo
  `BOGO` against a non-qualifying cart raises 500 via
  `store/promos.py:_bogo_discount()`; normal flows + SAVE10/WELCOME5 stay 200.
  (acceptance: `GET /checkout/?promo=BOGO` (item in cart) -> 500; SAVE10 -> 200)
  (done: verified smoke test — BOGO->500 ValueError at promos.py:61,
  SAVE10->200; README "The planted bug" documents trigger + expected fix)
- [x] SAMPLE-APP-9: Inner git repo on `main` for import — pocketshop is its own
  repo with a baseline commit so Hull can clone/import + open worktrees.
  (acceptance: inner .git on branch main with >=1 commit; db.sqlite3 gitignored)
  (done: .git on main, commit b162c31 "Import baseline", 27 tracked files;
  .gitignore present)

## Obsolete (superseded by PocketShop)

- [~] SAMP-1: Node/Express "NodeShop" sample — SUPERSEDED. PocketShop (Django)
  delivers the same import/deploy/proxy/auto-fix capability and matches Hull's
  stack. No Node sample shipped.
- [~] SAMP-2: Node 20 / docker build for NodeShop — SUPERSEDED with SAMP-1.

## Open (forward-looking — toward the roadmap demo)

- [x] SAMPLE-APP-10: Confirm the BOGO regression test genuinely fails pre-fix —
  keep `_bogo_discount()` bug intact but verify the README's suggested regression
  test errors against the unfixed code and passes once the empty-qualifying guard
  is added, so the agent's PR adds real value. (acceptance: README test errors on
  current code; passes with `if not qualifying: return Decimal("0")` guard)
  (done: ran the README regression test as a temp test against unfixed code ->
  ERRORS with `ValueError: min() arg is an empty sequence` at promos.py:61;
  applying the `if not qualifying: return Decimal("0")` guard -> test PASSES;
  bug restored intact (no guard in promos.py). README "Expected fix" now
  documents this verified pre/post-fix behavior.)
- [x] SAMPLE-APP-11: Docker Compose deploy path — add `docker-compose.yml` (web
  service binding $PORT) + `Dockerfile` (python:3.11-slim, pip install, migrate
  on start, gunicorn or runserver) so PocketShop deploys as a compose stack per
  the roadmap's Projects/Environments bar; keep plain-process run as fallback.
  (acceptance: `docker compose config` valid; documented; process run still works)
  (done: Dockerfile (python:3.11-slim, pip install -r requirements.txt, CMD
  entrypoint.sh) + docker-compose.yml (single `web` service, ports
  ${PORT:-8000}:${PORT}, named volume pocketshop_data, Hull env passthrough);
  `docker compose config` -> EXIT 0 / valid; requirements.txt now pins
  gunicorn==23.0.0; README "Docker Compose" section; plain `runserver` path
  still works -> 5 tests OK.)
- [x] SAMPLE-APP-12: Production-style entrypoint — `entrypoint.sh`/start script
  that runs `migrate` (idempotent, seeds) then serves on $PORT; document
  collectstatic-optional behavior. (acceptance: one command brings up a fresh,
  seeded, styled instance on $PORT)
  (done: executable entrypoint.sh -> `migrate --noinput` (idempotent; mig 0002
  seeds) -> optional collectstatic gated on POCKETSHOP_COLLECTSTATIC=1
  (default skip; WhiteNoise WHITENOISE_USE_FINDERS serves CSS from source) ->
  `exec gunicorn pocketshop.wsgi:application --bind 0.0.0.0:$PORT` with
  runserver fallback; `sh -n entrypoint.sh` OK; README "Production-style
  entrypoint" documents `PORT=8021 ./entrypoint.sh`.)
- [x] SAMPLE-APP-13: Richer observability surface — emit meaningful log lines /
  a slow path so Hull's logs + latency metrics + incident signal look real (e.g.
  a structured request log, an intentionally slower endpoint). (acceptance:
  hitting the app produces varied levels/latency Hull can ingest via
  observability.services.ingest_line)
  (done: store/observability.RequestLogMiddleware emits one greppable line per
  request to stdout — `[pocketshop] level=info method=GET path=/ status=200
  latency_ms=12.3` — level varies with status (info 2xx/3xx, warning 4xx, error
  5xx) and adds an X-Response-Time-Ms header; LOGGING config in settings routes
  the `pocketshop` logger to console; new `GET /slow/` view sleeps ~250-600ms
  for a real p95/p99 tail. Verified live: 200/302 -> info, BOGO/gift 500 ->
  `level=error ... status=500`, /slow/ -> latency_ms ~287.)
- [x] SAMPLE-APP-14: Health endpoint — lightweight `GET /healthz` returning 200
  JSON (no DB write) for Hull's per-deployment health checks
  (deploys.services.health_check). (acceptance: `/healthz` -> 200; honors subpath)
  (done: store/health.healthz wired at `path("healthz", ...)` -> 200 JSON
  `{"status":"ok","service":"pocketshop","db":"ok","uptime_seconds":...}` via
  read-only `SELECT 1` (no DB write; 503 only if DB unreachable); honors
  subpath -> reverse('store:healthz') under HELM_SCRIPT_NAME=/d/7 yields
  `/d/7/healthz`. Verified 200 application/json.)
- [x] SAMPLE-APP-15: Second planted-bug variant (optional) — an alternate
  deterministic 5xx behind a distinct trigger (e.g. a product slug or query flag)
  so back-to-back demos do not replay the identical incident. (acceptance: a
  documented distinct trigger -> 500 with a clear traceback in a different
  file/function; normal flows unaffected)
  (done: gift-wrap bug in store/gifts.gift_wrap_fee() -> `WRAP_FEES[key]` raises
  `KeyError: ''` because every seeded product has a blank category and WRAP_FEES
  has no "" entry. Distinct trigger: `GET /checkout/?gift=1` (or POST gift=1);
  distinct file (store/gifts.py vs promos.py). Verified live: ?gift=1 -> 500
  with traceback at gift_wrap_fee(); normal checkout / SAVE10 -> 200 (gift path
  untouched without the flag). Documented fix: WRAP_FEES.get(key,
  DEFAULT_WRAP_FEE) -> 200 with $2.50 fee. README "Second planted bug" section.)
