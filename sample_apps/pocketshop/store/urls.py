from django.urls import path

from . import health, views

app_name = "store"

urlpatterns = [
    path("", views.home, name="home"),
    path("cart/", views.cart_view, name="cart"),
    path("checkout/", views.checkout, name="checkout"),
    path("product/<slug:slug>/", views.product_detail, name="product"),
    path("product/<slug:slug>/add/", views.add_to_cart, name="add_to_cart"),
    # Observability / health surface for Hull.
    path("healthz", health.healthz, name="healthz"),
    path("slow/", views.slow, name="slow"),
]
