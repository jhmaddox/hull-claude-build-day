from decimal import Decimal

from django.db import migrations

PRODUCTS = [
    {
        "name": "Aera Wireless Earbuds",
        "slug": "aera-wireless-earbuds",
        "tagline": "Studio sound, all-day pair",
        "description": "Active noise cancellation, 30-hour case, USB-C fast charge. Sold as a pair.",
        "price": Decimal("129.00"),
        "emoji": "🎧",
        "accent": "#6366f1",
    },
    {
        "name": "Drift Cold Brew Maker",
        "slug": "drift-cold-brew-maker",
        "tagline": "Smooth brew at home",
        "description": "Borosilicate glass carafe with a fine-mesh filter. Makes 1L of cold brew.",
        "price": Decimal("38.50"),
        "emoji": "☕",
        "accent": "#b45309",
    },
    {
        "name": "Nimbus Linen Sheet Set",
        "slug": "nimbus-linen-sheet-set",
        "tagline": "Stonewashed bedding set",
        "description": "Pure French flax linen. Includes flat sheet, fitted sheet, and two cases.",
        "price": Decimal("149.00"),
        "emoji": "🛏️",
        "accent": "#0ea5e9",
    },
    {
        "name": "Trailhead Water Bottle",
        "slug": "trailhead-water-bottle",
        "tagline": "Stays cold 24 hours",
        "description": "Vacuum-insulated 32oz stainless steel bottle with a leakproof cap.",
        "price": Decimal("29.00"),
        "emoji": "🧴",
        "accent": "#16a34a",
    },
    {
        "name": "Lumen Desk Lamp",
        "slug": "lumen-desk-lamp",
        "tagline": "Warm to cool dimming",
        "description": "Aluminum LED desk lamp with touch dimming and a USB charging port.",
        "price": Decimal("64.00"),
        "emoji": "💡",
        "accent": "#eab308",
    },
    {
        "name": "Forma Ceramic Mug",
        "slug": "forma-ceramic-mug",
        "tagline": "Hand-glazed",
        "description": "12oz speckled stoneware mug, microwave and dishwasher safe.",
        "price": Decimal("18.00"),
        "emoji": "🍵",
        "accent": "#ec4899",
    },
    {
        "name": "Pace Running Socks",
        "slug": "pace-running-socks",
        "tagline": "Cushioned 3-pair set",
        "description": "Merino-blend cushioned running socks. Comes as a set of three pairs.",
        "price": Decimal("24.00"),
        "emoji": "🧦",
        "accent": "#8b5cf6",
    },
    {
        "name": "Atlas Leather Wallet",
        "slug": "atlas-leather-wallet",
        "tagline": "Full-grain, slim",
        "description": "Vegetable-tanned full-grain leather. Six card slots and a cash pocket.",
        "price": Decimal("48.00"),
        "emoji": "👛",
        "accent": "#78350f",
    },
]


def seed(apps, schema_editor):
    Product = apps.get_model("store", "Product")
    for data in PRODUCTS:
        Product.objects.get_or_create(slug=data["slug"], defaults=data)


def unseed(apps, schema_editor):
    Product = apps.get_model("store", "Product")
    Product.objects.filter(slug__in=[p["slug"] for p in PRODUCTS]).delete()


class Migration(migrations.Migration):

    dependencies = [("store", "0001_initial")]

    operations = [migrations.RunPython(seed, unseed)]
