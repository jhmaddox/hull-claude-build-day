from django.urls import path

from . import views

app_name = "store"

urlpatterns = [
    path("", views.home, name="home"),
    path("cart/", views.cart_view, name="cart"),
    path("checkout/", views.checkout, name="checkout"),
    path("product/<slug:slug>/", views.product_detail, name="product"),
    path("product/<slug:slug>/add/", views.add_to_cart, name="add_to_cart"),
]
