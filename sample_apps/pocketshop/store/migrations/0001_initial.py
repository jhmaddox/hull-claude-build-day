from decimal import Decimal

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Product",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=120)),
                ("slug", models.SlugField(unique=True)),
                ("tagline", models.CharField(blank=True, max_length=200)),
                ("description", models.TextField(blank=True)),
                ("price", models.DecimalField(decimal_places=2, max_digits=8)),
                ("emoji", models.CharField(default="📦", max_length=8)),
                ("accent", models.CharField(default="#6366f1", help_text="Hex accent color for the card.", max_length=7)),
                ("in_stock", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"ordering": ["id"]},
        ),
        migrations.CreateModel(
            name="Order",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("reference", models.CharField(max_length=12, unique=True)),
                ("email", models.EmailField(blank=True, max_length=254)),
                ("subtotal", models.DecimalField(decimal_places=2, default=Decimal("0"), max_digits=10)),
                ("discount", models.DecimalField(decimal_places=2, default=Decimal("0"), max_digits=10)),
                ("total", models.DecimalField(decimal_places=2, default=Decimal("0"), max_digits=10)),
                ("promo_code", models.CharField(blank=True, max_length=24)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="OrderItem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=120)),
                ("unit_price", models.DecimalField(decimal_places=2, max_digits=8)),
                ("quantity", models.PositiveIntegerField(default=1)),
                ("order", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="items", to="store.order")),
                ("product", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="store.product")),
            ],
        ),
    ]
