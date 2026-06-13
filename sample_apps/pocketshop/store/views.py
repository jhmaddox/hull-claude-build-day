import secrets
from decimal import Decimal

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render

from .cart import Cart
from .models import Order, OrderItem, Product
from .promos import PromoError, apply_promo, normalize


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

    total = subtotal - discount

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
            "total": total,
            "promo_code": promo_code,
            "promo_error": promo_error,
        },
    )


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
