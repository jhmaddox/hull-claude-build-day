import logging
import random
import secrets
import time
from decimal import Decimal

from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from .cart import Cart
from .gifts import gift_wrap_fee
from .models import Order, OrderItem, Product
from .promos import PromoError, apply_promo, normalize

logger = logging.getLogger("pocketshop.access")


def home(request):
    products = Product.objects.filter(in_stock=True)
    return render(request, "store/home.html", {"products": products})


def product_detail(request, slug):
    product = get_object_or_404(Product, slug=slug)
    return render(request, "store/product.html", {"product": product})


def add_to_cart(request, slug):
    product = get_object_or_404(Product, slug=slug)
    cart = Cart(request)
    cart.add(product)
    messages.success(request, f"Added {product.name} to your cart.")
    return redirect("store:cart")


def cart_view(request):
    cart = Cart(request)
    if request.method == "POST":
        # Quantity updates from the cart page.
        for line in cart.lines():
            field = f"qty_{line.product.id}"
            if field in request.POST:
                try:
                    cart.set_quantity(line.product.id, int(request.POST[field]))
                except (TypeError, ValueError):
                    pass
        remove_id = request.POST.get("remove")
        if remove_id:
            cart.remove(remove_id)
        return redirect("store:cart")

    lines = cart.lines()
    return render(
        request,
        "store/cart.html",
        {"lines": lines, "subtotal": cart.subtotal},
    )


def checkout(request):
    cart = Cart(request)
    lines = cart.lines()
    subtotal = cart.subtotal

    # Promo can arrive via querystring (?promo=) or the checkout form field.
    promo_code = normalize(request.POST.get("promo") or request.GET.get("promo"))

    if not lines:
        messages.info(request, "Your cart is empty.")
        return redirect("store:home")

    discount = Decimal("0")
    promo_error = None
    if promo_code:
        try:
            discount = apply_promo(promo_code, lines, subtotal)
        except PromoError as exc:
            # Unknown codes are a friendly, recoverable error.
            promo_error = str(exc)
            promo_code = ""

    # Optional gift-wrap add-on (second planted bug — see store/gifts.py).
    # Triggered by ?gift=1 (querystring) or the gift checkbox on the form.
    wrap_fee = Decimal("0")
    gift_wrap = bool(request.POST.get("gift") or request.GET.get("gift"))
    if gift_wrap:
        wrap_fee = gift_wrap_fee(lines)

    total = subtotal - discount + wrap_fee

    # POST without ?preview means "place order".
    placing_order = request.method == "POST" and request.POST.get("place_order")
    if placing_order:
        order = _create_order(
            email=request.POST.get("email", ""),
            lines=lines,
            subtotal=subtotal,
            discount=discount,
            total=total,
            promo_code=promo_code,
        )
        cart.clear()
        return render(request, "store/confirmation.html", {"order": order})

    return render(
        request,
        "store/checkout.html",
        {
            "lines": lines,
            "subtotal": subtotal,
            "discount": discount,
            "wrap_fee": wrap_fee,
            "gift_wrap": gift_wrap,
            "total": total,
            "promo_code": promo_code,
            "promo_error": promo_error,
        },
    )


def slow(request):
    """Intentionally slow endpoint so Hull's latency charts get a real tail.

    Sleeps a randomized ~250-600ms, which shows up in the access-log
    ``latency_ms`` field and gives Hull a visible p95/p99. Returns small JSON
    so it is cheap to hit repeatedly in a demo loop.
    """
    delay = random.uniform(0.25, 0.6)
    time.sleep(delay)
    logger.info(
        "[pocketshop] slow endpoint served after %.1fms (simulated work)",
        delay * 1000.0,
    )
    return JsonResponse({"ok": True, "simulated_delay_ms": round(delay * 1000.0, 1)})


def _create_order(*, email, lines, subtotal, discount, total, promo_code):
    order = Order.objects.create(
        reference="PS-" + secrets.token_hex(3).upper(),
        email=email,
        subtotal=subtotal,
        discount=discount,
        total=total,
        promo_code=promo_code,
    )
    for line in lines:
        OrderItem.objects.create(
            order=order,
            product=line.product,
            name=line.product.name,
            unit_price=line.product.price,
            quantity=line.quantity,
        )
    return order
