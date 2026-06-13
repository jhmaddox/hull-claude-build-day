from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from .models import Product


class StorefrontTests(TestCase):
    def setUp(self):
        # Seed data is loaded by migration 0002; tests run on a migrated DB.
        self.product = Product.objects.create(
            name="Test Widget",
            slug="test-widget",
            tagline="A plain widget",
            price=Decimal("10.00"),
            emoji="🔧",
        )

    def test_home_returns_200_and_lists_products(self):
        resp = self.client.get(reverse("store:home"))
        self.assertEqual(resp.status_code, 200)
        # Seeded products from the data migration should be present.
        self.assertContains(resp, "Aera Wireless Earbuds")

    def test_add_to_cart_and_view(self):
        self.client.get(reverse("store:add_to_cart", args=[self.product.slug]))
        resp = self.client.get(reverse("store:cart"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Test Widget")

    def test_checkout_without_promo_succeeds(self):
        self.client.get(reverse("store:add_to_cart", args=[self.product.slug]))
        resp = self.client.get(reverse("store:checkout"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Total")

    def test_place_order_creates_confirmation(self):
        self.client.get(reverse("store:add_to_cart", args=[self.product.slug]))
        resp = self.client.post(
            reverse("store:checkout"),
            {"place_order": "1", "email": "buyer@example.com"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Order confirmed")

    def test_save10_promo_applies_discount(self):
        self.client.get(reverse("store:add_to_cart", args=[self.product.slug]))
        resp = self.client.get(reverse("store:checkout"), {"promo": "SAVE10"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "1.00")  # 10% of $10.00
