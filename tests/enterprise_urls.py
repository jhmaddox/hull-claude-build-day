"""Dedicated test urlconf so enterprise view/whoami tests run independently of
whether the integrator has wired enterprise into helm/urls.py yet."""

from django.urls import include, path

urlpatterns = [
    path("accounts/", include("accounts.urls")),
    path("enterprise/", include("enterprise.urls")),
]
