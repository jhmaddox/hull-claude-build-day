from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("signup/", views.signup, name="signup"),
    path("onboarding/", views.onboarding, name="onboarding"),
    path("switch/<int:org_id>/", views.switch_org, name="switch_org"),
]
