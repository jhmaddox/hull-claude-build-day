from django.urls import path

from . import views

app_name = "issues"

urlpatterns = [
    path("", views.board, name="board"),
    path("backlog/", views.backlog, name="backlog"),
    path("sprints/", views.sprints, name="sprints"),
    path("sprints/<int:pk>/", views.sprint_detail, name="sprint"),
    path("new/", views.ticket_new, name="ticket_new"),
    path("t/<int:pk>/", views.ticket, name="ticket"),
    path("t/<int:pk>/edit/", views.ticket_edit, name="ticket_edit"),
    path("t/<int:pk>/comment/", views.add_comment, name="add_comment"),
    path("t/<int:pk>/status/", views.set_status, name="set_status"),
    path("t/<int:pk>/assign/", views.assign, name="assign"),
]
