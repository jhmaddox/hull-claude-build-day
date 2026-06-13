from django.urls import path

from . import views

app_name = "issues"

urlpatterns = [
    path("", views.board, name="board"),
    path("backlog/", views.backlog, name="backlog"),
    path("agents/", views.agent_backlog, name="agent_backlog"),
    path("sprints/", views.sprints, name="sprints"),
    path("sprints/<int:pk>/", views.sprint_detail, name="sprint"),
    path("new/", views.ticket_new, name="ticket_new"),
    # Board / sprint / label management write-actions.
    path("boards/new/", views.board_new, name="board_new"),
    path("sprints/new/", views.sprint_new, name="sprint_new"),
    path("sprints/<int:pk>/action/", views.sprint_action, name="sprint_action"),
    path("labels/new/", views.label_new, name="label_new"),
    # Ticket detail + actions.
    path("t/<int:pk>/", views.ticket, name="ticket"),
    path("t/<int:pk>/edit/", views.ticket_edit, name="ticket_edit"),
    path("t/<int:pk>/comment/", views.add_comment, name="add_comment"),
    path("t/<int:pk>/status/", views.set_status, name="set_status"),
    path("t/<int:pk>/assign/", views.assign, name="assign"),
    path("t/<int:pk>/sprint/", views.ticket_sprint, name="ticket_sprint"),
    path("t/<int:pk>/labels/", views.ticket_labels, name="ticket_labels"),
]
