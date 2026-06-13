# PocketShop

A small, polished Django storefront — the "established legacy app" that **Hull**
imports, deploys to staging + prod, monitors, and auto-fixes during the demo.

It is a fully standalone Django project (its own `manage.py`, settings, SQLite,
seed data, tests). It has no dependency on Hull and runs on its own.

## What it is

A tidy e-commerce shop for everyday small goods:

- **Home** (`/`) — hero + a grid of 8 seeded products (emoji art, price,
  "Add to cart").
- **Product** (`/product/<slug>/`) — detail page.
- **Cart** (`/cart/`) — session-backed cart with quantity update / remove.
- **Checkout** (`/checkout/`) — order summary, promo-code box, "Place order".
- **Confirmation** — order reference + receipt after placing an order.

Products are seeded automatically by a data migration
(`store/migrations/0002_seed_products.py`), so a fresh deploy has data with **no
manual step** — just migrate.

## Stack

- Django 5.1 + WhiteNoise (static). No JS frameworks. Deps pinned in
  `requirements.txt`.
- SQLite, server-rendered templates, own CSS (`store/static/store/shop.css`).

## Run it

### Plain process (no Docker)

```bash
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver 0.0.0.0:$PORT      # e.g. PORT=8021
```

Then open `http://localhost:$PORT/`. The home page returns **200** and lists the
8 seeded products. Add an item, go to checkout, place the order — you get an
order-confirmation page. (`migrate` is idempotent and seeds products.)

### Production-style entrypoint (one command)

`entrypoint.sh` brings up a fresh, seeded, styled instance on `$PORT` in one
step: it runs `migrate` (idempotent; migration 0002 seeds the catalog), then
serves on `0.0.0.0:$PORT` via **gunicorn** (falling back to `runserver` if
gunicorn is absent).

```bash
pip install -r requirements.txt
PORT=8021 ./entrypoint.sh
```

`collectstatic` is **optional** — WhiteNoise serves CSS straight from the source
dirs (`WHITENOISE_USE_FINDERS=True`), so styles appear without a static build.
Set `POCKETSHOP_COLLECTSTATIC=1` to run a real production static build.

### Docker Compose (Hull's deploy substrate)

PocketShop ships a `Dockerfile` (python:3.11-slim) and a `docker-compose.yml`
with a single `web` service that builds the image, migrates+seeds on start, and
binds `$PORT`. This matches Hull's "Docker Compose per environment" deploy path;
the plain-process run above still works as a fallback.

```bash
docker compose config            # validate the stack
PORT=8021 docker compose up --build
```

The SQLite DB persists on the `pocketshop_data` named volume. Hull injects
`PORT`, `HELM_SCRIPT_NAME`, `HELM_BASE_URL`, and secrets as environment.

## Health & observability (for Hull)

- **Health:** `GET /healthz` returns small JSON `200` (`{"status":"ok", "db":
  "ok", ...}`) with **no DB write** (a read-only `SELECT 1`), for Hull's
  per-deployment `deploys.services.health_check`. It honors the reverse-proxy
  subpath (resolves at `/d/<env_pk>/healthz`).
- **Structured access logs:** every request emits a greppable line to stdout —
  `[pocketshop] level=info method=GET path=/ status=200 latency_ms=12.3` — at a
  level that tracks status (info 2xx/3xx, warning 4xx, error 5xx). Hull ingests
  these via `observability.services.ingest_line` for logs + latency metrics +
  incident signal. Each response also carries an `X-Response-Time-Ms` header.
- **Slow path:** `GET /slow/` sleeps ~250-600ms and returns small JSON, giving
  Hull's latency charts a visible p95/p99 tail.

## Running behind Hull's reverse proxy (subpath)

Hull serves each environment under `/d/<env_pk>/`. PocketShop honors that:

- If `HELM_SCRIPT_NAME` is set (e.g. `/d/7`), settings apply
  `FORCE_SCRIPT_NAME`, and `STATIC_URL` is prefixed with it so `{% static %}`
  and `{% url %}` links all resolve correctly under the subpath.
- `ALLOWED_HOSTS = ["*"]`.
- `CSRF_TRUSTED_ORIGINS` is derived from `HELM_BASE_URL` if present.
- All links/forms use `{% url %}` — nothing is hardcoded to `/`.

Env vars Hull may set: `HELM_SCRIPT_NAME`, `HELM_BASE_URL`,
`POCKETSHOP_SECRET_KEY`, `POCKETSHOP_DEBUG`.

## The planted bug (demo-controlled)

The checkout promo-code path has a realistic latent bug that only triggers on a
specific, repeatable action, so the demo controls its timing.

**Trigger:** apply the promo code **`BOGO`** at checkout.

- Easiest URL trigger: **`GET /checkout/?promo=BOGO`** (with at least one item
  in the cart). Returns **HTTP 500** with a traceback.
- Also triggers on `POST /checkout/` with `promo=BOGO` (placing the order).

**Why it crashes:** `BOGO` ("buy one get one") looks for *qualifying* items
(products tagged "pair"/"set") and gives the cheapest qualifying unit free,
spread across the qualifying lines. When the cart contains **no** qualifying
items, the qualifying list is empty and the function:

1. calls `min(...)` over an empty sequence → `ValueError`, and (if guarded
   naively, the next lines also fail)
2. divides by `len(qualifying) == 0` → `ZeroDivisionError`, and
3. indexes `qualifying[0]` → `IndexError`.

**Buggy file / function:** `store/promos.py` → `_bogo_discount()`
(the traceback points at this one function).

**Normal flow is unaffected:** no promo, or `SAVE10` / `WELCOME5`, all return a
clean 200 and a normal confirmation page. Only `BOGO` (against a cart of
non-qualifying items) raises the 500. The seeded catalog's default
"Add to cart" demo carts use non-qualifying items, so the bug fires reliably.

### Expected fix

Guard the empty-qualifying case in `_bogo_discount()` — if there are no
qualifying items, return `Decimal("0")` (no discount) before touching
`min()` / division / indexing. A natural regression test:

```python
def test_bogo_with_no_qualifying_items_does_not_crash(self):
    self.client.get(reverse("store:add_to_cart", args=[self.product.slug]))
    resp = self.client.get(reverse("store:checkout"), {"promo": "BOGO"})
    self.assertEqual(resp.status_code, 200)   # no 500
```

**Verified regression:** against the *current* (unfixed) code this test errors
with `ValueError: min() arg is an empty sequence` raised in
`store/promos.py:_bogo_discount()` (under `DEBUG=1` the test client re-raises
the 500). Adding the one-line guard
`if not qualifying: return Decimal("0")` at the top of `_bogo_discount()`
(right after `qualifying` is computed) makes the test pass — so the agent's PR
adds real, test-backed value rather than a no-op.

## Second planted bug (alternate incident — for back-to-back demos)

So consecutive auto-fix demos don't replay the identical incident, there is a
**second, distinct** deterministic 5xx behind a different trigger, in a
different file/function.

**Trigger:** add **any** seeded item, then check out with the **gift-wrap**
flag: **`GET /checkout/?gift=1`** (also fires on `POST` with `gift=1`).

- Returns **HTTP 500** with a traceback.
- Unlike BOGO (which needs a *non-qualifying* cart), this fires on **every**
  seeded product, so it is even simpler to trigger.

**Why it crashes:** gift-wrap fees are looked up by product *category*
(`store/gifts.py` → `gift_wrap_fee()` → `WRAP_FEES[key]`). Every seeded product
has a blank category, and `WRAP_FEES` has no `""` entry, so the lookup raises
`KeyError: ''`.

**Buggy file / function:** `store/gifts.py` → `gift_wrap_fee()` (distinct from
the BOGO bug's `store/promos.py`).

**Expected fix:** use `WRAP_FEES.get(key, DEFAULT_WRAP_FEE)` so an unknown/blank
category falls back to the default wrap fee instead of crashing. A natural
regression test:

```python
def test_gift_wrap_unknown_category_does_not_crash(self):
    self.client.get(reverse("store:add_to_cart", args=[self.product.slug]))
    resp = self.client.get(reverse("store:checkout"), {"gift": "1"})
    self.assertEqual(resp.status_code, 200)   # no 500
```

**Normal flow is unaffected:** without `?gift=1`, checkout never touches the
gift-wrap path. Verified: the unfixed code raises `KeyError: ''` at
`store/gifts.py:gift_wrap_fee()`; the `.get(...)` fallback returns the default
`$2.50` fee and the request is 200.

## Tests

```bash
python manage.py test
```

`store/tests.py` ships 5 passing tests (home, cart, normal checkout, place
order, SAVE10 promo) — CI is green **before** the bug is triggered, and the
structure makes the BOGO regression test above natural to add.
