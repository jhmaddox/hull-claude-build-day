from django.urls import path

from . import views

app_name = "agents"

urlpatterns = [
    path("", views.agent_list, name="list"),
    path("roster/", views.agent_roster, name="roster"),
    path("new/", views.agent_new, name="new"),
    path("<int:pk>/", views.agent_detail, name="detail"),
    path("<int:pk>/stream/", views.agent_stream, name="stream"),
]
