"""Promo code logic for checkout.

PocketShop supports a few promo codes. Most are simple percentage / flat
discounts. The BOGO ("buy one, get one") code is more involved: it finds the
qualifying items in the cart and gives the cheapest qualifying unit for free,
spread across the qualifying lines.

NOTE FOR MAINTAINERS: the BOGO branch has a long-standing latent bug — see
README.md ("The planted bug"). It only manifests when BOGO is applied to a
cart that contains no qualifying ("pair"/"set") items, which is why it slipped
past normal testing.
"""
from decimal import Decimal


class PromoError(Exception):
    """Raised for a user-facing, recoverable promo problem (e.g. unknown code)."""


def normalize(code):
    return (code or "").strip().upper()


def apply_promo(code, lines, subtotal):
    """Return the discount Decimal for ``code`` applied to ``lines``.

    ``lines`` is a list of CartLine-like objects (``.product``, ``.quantity``,
    ``.line_total``). ``subtotal`` is the cart subtotal as a Decimal.

    Raises PromoError for an unknown code. Returns Decimal("0") for no code.
    """
    code = normalize(code)
    if not code:
        return Decimal("0")

    if code == "SAVE10":
        return (subtotal * Decimal("0.10")).quantize(Decimal("0.01"))

    if code == "WELCOME5":
        # Flat $5 off, never more than the subtotal.
        return min(Decimal("5.00"), subtotal)

    if code == "BOGO":
        return _bogo_discount(lines, subtotal)

    raise PromoError(f"'{code}' is not a valid promo code.")


def _bogo_discount(lines, subtotal):
    """Buy-one-get-one: the cheapest qualifying unit is free.

    THE BUG: ``qualifying`` can be empty (no pair/set items in the cart). The
    code below then divides by ``len(qualifying)`` (ZeroDivisionError) and
    indexes ``qualifying[0]`` (IndexError) without guarding against the empty
    case. Triggered deterministically by applying BOGO to any cart of
    non-qualifying items.
    """
    qualifying = [line for line in lines if line.product.is_qualifying_for_bogo]

    # Spread the value of the single free unit evenly across qualifying lines.
    free_unit_value = min(line.product.price for line in qualifying)  # IndexError-ish via min([])
    per_line = free_unit_value / len(qualifying)  # ZeroDivisionError when empty
    cheapest_line = qualifying[0]  # IndexError when empty

    discount = per_line * len(qualifying)
    return min(discount, cheapest_line.line_total).quantize(Decimal("0.01"))
