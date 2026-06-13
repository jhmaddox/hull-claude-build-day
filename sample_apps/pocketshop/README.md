# PocketShop

A small, polished Django storefront — the "established legacy app" that **Helm**
imports, deploys to staging + prod, monitors, and auto-fixes during the demo.

It is a fully standalone Django project (its own `manage.py`, settings, SQLite,
seed data, tests). It has no dependency on Helm and runs on its own.

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

```bash
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver 0.0.0.0:$PORT      # e.g. PORT=8021
```

Then open `http://localhost:$PORT/`. The home page returns **200** and lists the
8 seeded products. Add an item, go to checkout, place the order — you get an
order-confirmation page. (`migrate` is idempotent and seeds products.)

## Running behind Helm's reverse proxy (subpath)

Helm serves each environment under `/d/<env_pk>/`. PocketShop honors that:

- If `HELM_SCRIPT_NAME` is set (e.g. `/d/7`), settings apply
  `FORCE_SCRIPT_NAME`, and `STATIC_URL` is prefixed with it so `{% static %}`
  and `{% url %}` links all resolve correctly under the subpath.
- `ALLOWED_HOSTS = ["*"]`.
- `CSRF_TRUSTED_ORIGINS` is derived from `HELM_BASE_URL` if present.
- All links/forms use `{% url %}` — nothing is hardcoded to `/`.

Env vars Helm may set: `HELM_SCRIPT_NAME`, `HELM_BASE_URL`,
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

## Tests

```bash
python manage.py test
```

`store/tests.py` ships 5 passing tests (home, cart, normal checkout, place
order, SAVE10 promo) — CI is green **before** the bug is triggered, and the
structure makes the BOGO regression test above natural to add.
