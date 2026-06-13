from .cart import Cart


def cart_summary(request):
    """Expose a lightweight cart summary to every template (header badge)."""
    try:
        cart = Cart(request)
        return {"cart_count": cart.count}
    except Exception:
        return {"cart_count": 0}
