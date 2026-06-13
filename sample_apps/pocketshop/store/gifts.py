"""Gift-wrap option for checkout — second deterministic planted bug.

This is an *alternate* planted bug (distinct from the BOGO promo bug in
``store/promos.py``) so back-to-back auto-fix demos do not replay the identical
incident. It lives in its own file/function and fires behind a distinct
trigger: the ``?gift=1`` query flag (or the gift checkbox) at checkout.

THE BUG: ``gift_wrap_fee`` looks up a per-product wrap fee in
``WRAP_FEES`` keyed by the product's *category*. The seeded catalog products
have no category set (it defaults to ``""``), so the lookup ``WRAP_FEES[key]``
raises ``KeyError`` for a normal cart. Triggered deterministically by adding any
seeded item and hitting checkout with ``?gift=1``.

EXPECTED FIX: use ``WRAP_FEES.get(key, DEFAULT_WRAP_FEE)`` (or guard the missing
key) so an unknown/blank category falls back to the default wrap fee instead of
crashing.
"""
from decimal import Decimal

# Per-category gift-wrap fees. Note there is no entry for the empty/default
# category, which is what every seeded product has.
WRAP_FEES = {
    "apparel": Decimal("3.00"),
    "electronics": Decimal("4.50"),
    "home": Decimal("3.50"),
}

DEFAULT_WRAP_FEE = Decimal("2.50")


def _category_for(product):
    """Best-effort category key for a product (blank for seeded catalog)."""
    return (getattr(product, "category", "") or "").strip().lower()


def gift_wrap_fee(lines):
    """Return the total gift-wrap fee for ``lines``.

    THE BUG: indexes ``WRAP_FEES`` directly by category. Seeded products have a
    blank category, so ``WRAP_FEES[""]`` raises ``KeyError`` — a deterministic
    500 distinct from the BOGO promo bug, in a different file/function.
    """
    total = Decimal("0")
    for line in lines:
        key = _category_for(line.product)
        # KeyError when the product has no/blank category (all seeded items).
        fee = WRAP_FEES[key]
        total += fee * line.quantity
    return total.quantize(Decimal("0.01"))
