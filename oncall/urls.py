from django.urls import path

from . import views

app_name = "oncall"

urlpatterns = [
    path("", views.board, name="board"),
    # Incident center
    path("incidents/<int:pk>/", views.incident_detail, name="incident_detail"),
    path("incidents/<int:pk>/timeline/", views.incident_timeline, name="incident_timeline"),
    path("incidents/<int:pk>/ack/", views.ack, name="ack"),
    path("incidents/<int:pk>/resolve/", views.resolve, name="resolve"),
    path("incidents/<int:pk>/note/", views.note, name="note"),
    path("incidents/<int:pk>/assign/", views.assign, name="assign"),
    path("incidents/<int:pk>/tick/", views.tick, name="tick"),
    path("incidents/<int:pk>/severity/", views.change_severity, name="change_severity"),
    path("incidents/<int:pk>/reopen/", views.reopen, name="reopen"),
    path("incidents/<int:pk>/postmortem/", views.postmortem, name="postmortem"),
    # Live board auto-tick
    path("board/tick/", views.board_tick, name="board_tick"),
    # Schedules
    path("schedules/", views.schedules, name="schedules"),
    path("schedules/<int:pk>/", views.schedule_detail, name="schedule_detail"),
    # Escalation policies
    path("policies/", views.policies, name="policies"),
    path("policies/<int:pk>/", views.policy_detail, name="policy_detail"),
    # Routing rules
    path("rules/", views.rules, name="rules"),
]
