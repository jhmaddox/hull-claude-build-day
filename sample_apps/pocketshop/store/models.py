from decimal import Decimal

from django.db import models


class Product(models.Model):
    """A single sellable item in the PocketShop catalog."""

    name = models.CharField(max_length=120)
    slug = models.SlugField(unique=True)
    tagline = models.CharField(max_length=200, blank=True)
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=8, decimal_places=2)
    # We render product imagery with an emoji + CSS gradient, so deploys need
    # no asset pipeline or external images.
    emoji = models.CharField(max_length=8, default="📦")
    accent = models.CharField(
        max_length=7, default="#6366f1", help_text="Hex accent color for the card."
    )
    in_stock = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return self.name

    @property
    def price_display(self):
        return f"${self.price:.2f}"

    @property
    def is_qualifying_for_bogo(self):
        """A product qualifies for the BOGO promo if it's a 'pair' item."""
        return "pair" in self.tagline.lower() or "set" in self.tagline.lower()


class Order(models.Model):
    """A completed checkout. Created on the confirmation page."""

    reference = models.CharField(max_length=12, unique=True)
    email = models.EmailField(blank=True)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"))
    discount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"))
    total = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"))
    promo_code = models.CharField(max_length=24, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Order {self.reference}"


class OrderItem(models.Model):
    order = models.ForeignKey(Order, related_name="items", on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    name = models.CharField(max_length=120)
    unit_price = models.DecimalField(max_digits=8, decimal_places=2)
    quantity = models.PositiveIntegerField(default=1)

    @property
    def line_total(self):
        return self.unit_price * self.quantity
