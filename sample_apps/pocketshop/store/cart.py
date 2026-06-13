"""Session-backed shopping cart.

The cart is stored in the session as a dict of {product_id (str): quantity}.
"""
from decimal import Decimal

from .models import Product

CART_SESSION_KEY = "cart"


class CartLine:
    def __init__(self, product, quantity):
        self.product = product
        self.quantity = quantity

    @property
    def line_total(self):
        return self.product.price * self.quantity


class Cart:
    def __init__(self, request):
        self.session = request.session
        self._data = self.session.get(CART_SESSION_KEY, {})

    def _save(self):
        self.session[CART_SESSION_KEY] = self._data
        self.session.modified = True

    def add(self, product, quantity=1):
        pid = str(product.id)
        self._data[pid] = self._data.get(pid, 0) + quantity
        self._save()

    def set_quantity(self, product_id, quantity):
        pid = str(product_id)
        if quantity <= 0:
            self._data.pop(pid, None)
        else:
            self._data[pid] = quantity
        self._save()

    def remove(self, product_id):
        self._data.pop(str(product_id), None)
        self._save()

    def clear(self):
        self._data = {}
        self._save()

    def lines(self):
        if not self._data:
            return []
        products = {
            str(p.id): p
            for p in Product.objects.filter(id__in=[int(k) for k in self._data])
        }
        out = []
        for pid, qty in self._data.items():
            product = products.get(pid)
            if product:
                out.append(CartLine(product, qty))
        return out

    @property
    def count(self):
        return sum(self._data.values())

    @property
    def subtotal(self):
        return sum((line.line_total for line in self.lines()), Decimal("0"))

    def __len__(self):
        return self.count
