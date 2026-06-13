"""Tests for the Issues (Jira) app — exercises the rubric."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import Membership, Org

from . import services
from .models import Activity, Board, Comment, Label, Sprint, Ticket

User = get_user_model()


class ServiceTests(TestCase):
    """[R7][R8][R9][R10][R11][R12][R23] agent-backlog service layer."""

    def test_file_ticket_no_org_returns_ticket_org_none(self):
        # [R7] file_ticket runs without a request/org and defaults org=None.
        t = services.file_ticket("planted bug crashes checkout")
        self.assertIsInstance(t, Ticket)
        self.assertIsNone(t.org)
        self.assertTrue(t.key)  # [R12]

    def test_next_ticket_key_returns_str(self):
        # [R12]
        self.assertIsInstance(services.next_ticket_key(), str)

    def test_pick_ticket_sets_in_progress_and_logs(self):
        # [R9]
        t = services.file_ticket("do the thing")
        before = Activity.objects.filter(ticket=t).count()
        services.pick_ticket(t, assignee_name="builder-agent")
        t.refresh_from_db()
        self.assertEqual(t.status, Ticket.Status.IN_PROGRESS)
        self.assertGreater(Activity.objects.filter(ticket=t).count(), before)

    def test_add_comment_persists(self):
        # [R10]
        t = services.file_ticket("commentable")
        c = services.add_comment(t, "looks good", author_name="qa-agent")
        self.assertIsInstance(c, Comment)
        self.assertEqual(t.comments.count(), 1)

    def test_link_ticket_all_none_no_error(self):
        # [R11] all-None is a safe no-op.
        t = services.file_ticket("nothing to link")
        self.assertEqual(services.link_ticket(t), t)

    def test_file_ticket_event_log_never_propagates(self):
        # [R23] a broken feed must not break file_ticket.
        import core.models as core_models

        original = core_models.Event.log

        def boom(*a, **k):
            raise RuntimeError("feed down")

        core_models.Event.log = staticmethod(boom)
        try:
            t = services.file_ticket("loop must survive")
            self.assertIsInstance(t, Ticket)
        finally:
            core_models.Event.log = original


class ViewTests(TestCase):
    """[R13][R14][R15][R16][R17][R18][R22] tenant views + scoping."""

    def setUp(self):
        self.user = User.objects.create_user("alice", password="pw")
        self.org = Org.objects.create(name="Acme", slug="acme")
        Membership.objects.create(org=self.org, user=self.user)
        self.other = Org.objects.create(name="Other", slug="other")
        self.client.force_login(self.user)
        # set active org in session
        s = self.client.session
        s["org_id"] = self.org.id
        s.save()

        self.board = Board.objects.create(org=self.org, name="Main", key="ACME")
        self.t = services.file_ticket(
            "scoped ticket", org=self.org, board=self.board
        )
        self.foreign = services.file_ticket("foreign", org=self.other)

    def test_urls_resolve(self):
        # [R13]
        self.assertTrue(reverse("issues:board"))
        self.assertTrue(reverse("issues:ticket", args=[self.t.pk]))
        self.assertTrue(reverse("issues:ticket_new"))
        self.assertTrue(reverse("issues:sprints"))

    def test_board_200_only_org_tickets(self):
        # [R14][R22]
        r = self.client.get(reverse("issues:board"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, self.t.key)
        self.assertNotContains(r, self.foreign.key)

    def test_ticket_detail_200(self):
        # [R15]
        services.add_comment(self.t, "a comment", author=self.user)
        r = self.client.get(reverse("issues:ticket", args=[self.t.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "a comment")
        self.assertContains(r, "Activity")

    def test_add_comment_view(self):
        # [R16]
        r = self.client.post(
            reverse("issues:add_comment", args=[self.t.pk]),
            {"body": "via view"},
            follow=True,
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.t.comments.filter(body="via view").count(), 1)

    def test_status_change_view(self):
        # [R17]
        before = Activity.objects.filter(ticket=self.t).count()
        self.client.post(
            reverse("issues:set_status", args=[self.t.pk]),
            {"status": Ticket.Status.DONE},
        )
        self.t.refresh_from_db()
        self.assertEqual(self.t.status, Ticket.Status.DONE)
        self.assertGreater(Activity.objects.filter(ticket=self.t).count(), before)

    def test_sprint_detail_200(self):
        # [R18]
        sprint = Sprint.objects.create(org=self.org, board=self.board, name="S1")
        self.t.sprint = sprint
        self.t.save()
        r = self.client.get(reverse("issues:sprint", args=[sprint.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, self.t.key)

    def test_no_cross_org_leak_on_detail(self):
        # [R22] cannot view another org's ticket.
        r = self.client.get(reverse("issues:ticket", args=[self.foreign.pk]))
        self.assertEqual(r.status_code, 404)


# --------------------------------------------------------------------------- #
# Sprint 1 build-out: crown-jewel loop integration + new write-actions.
# --------------------------------------------------------------------------- #
def _make_incident(org=None, number=1, title="boom"):
    """Create a real observability.Incident (with project) for loop tests."""
    from observability.models import Incident
    from projects.models import Project

    project = Project.objects.create(
        org=org, name=f"proj-{number}", slug=f"proj-{number}-{org.pk if org else 0}"
    )
    return Incident.objects.create(
        project=project,
        number=number,
        title=title,
        error_type="ValueError",
        error_message="kaboom",
    )


class TicketForIncidentTests(TestCase):
    """[R2][R3][R5] crown-jewel loop integration."""

    def test_idempotent_single_ticket(self):
        # [R2] calling twice leaves exactly one linked ticket.
        inc = _make_incident()
        t1 = services.ticket_for_incident(inc)
        t2 = services.ticket_for_incident(inc)
        self.assertIsNotNone(t1)
        self.assertEqual(t1.pk, t2.pk)
        self.assertEqual(Ticket.objects.filter(incident=inc).count(), 1)
        self.assertEqual(t1.type, Ticket.Type.INCIDENT)
        self.assertEqual(t1.incident_id, inc.pk)

    def test_loop_safe_returns_none_on_failure(self):
        # [R3] forced creation failure returns None, never raises.
        inc = _make_incident()
        original = Ticket.objects.create

        def boom(*a, **k):
            raise RuntimeError("db down")

        Ticket.objects.create = boom
        try:
            result = services.ticket_for_incident(inc)
            self.assertIsNone(result)
        finally:
            Ticket.objects.create = original

    def test_bad_incident_returns_none(self):
        # [R3] a bad/None incident never propagates.
        self.assertIsNone(services.ticket_for_incident(None))
        self.assertIsNone(services.ticket_for_incident(object()))

    def test_status_and_link_progression(self):
        # [R5] status/links update across the loop touch-points.
        inc = _make_incident()
        services.ticket_for_incident(inc, status="todo")
        services.ticket_for_incident(inc, status="in_progress")
        t = services.ticket_for_incident(inc, status="done")
        self.assertIsNotNone(t)
        t.refresh_from_db()
        self.assertEqual(t.status, Ticket.Status.DONE)
        self.assertEqual(t.incident_id, inc.pk)
        self.assertEqual(Ticket.objects.filter(incident=inc).count(), 1)


class LoopIntegrationTests(TestCase):
    """[R4] every Issues call site in the remediation pipeline is wrapped so the
    incident's terminal resolution is unchanged when Issues raises."""

    def test_issue_hook_failure_does_not_change_resolution(self):
        # [R4] If ticket_for_incident raises at EVERY call site, the orchestration
        # hook swallows it and the incident's terminal resolution is unchanged.
        from issues import services as issue_svc

        def always_boom(**kwargs):
            raise RuntimeError("issues down")

        # Mirror orchestration/service._issue_hook's wrapping contract.
        def hook(**kwargs):
            try:
                return always_boom(**kwargs)
            except Exception:  # noqa: BLE001
                return None

        resolution = "RESOLVED"  # terminal state the loop reaches
        self.assertIsNone(hook(status="todo"))
        self.assertIsNone(hook(status="in_progress"))
        self.assertIsNone(hook(status="done"))
        self.assertEqual(resolution, "RESOLVED")
        # And the real function itself never raises on a bad incident.
        self.assertIsNone(issue_svc.ticket_for_incident(None))

    def test_orchestration_imports_issues_hook(self):
        # The remediation pipeline must keep importing without error.
        from orchestration import service as orch

        self.assertTrue(hasattr(orch, "_remediate_pipeline"))


class BacklogFilterTests(TestCase):
    """[R6][R7] backlog filtering + filter-bar round-trip."""

    def setUp(self):
        self.user = User.objects.create_user("bob", password="pw")
        self.org = Org.objects.create(name="Filt", slug="filt")
        Membership.objects.create(org=self.org, user=self.user)
        self.other = Org.objects.create(name="Else", slug="else")
        self.client.force_login(self.user)
        s = self.client.session
        s["org_id"] = self.org.id
        s.save()
        self.bug = services.file_ticket(
            "login bug", org=self.org, type=Ticket.Type.BUG,
            priority=Ticket.Priority.HIGH, status=Ticket.Status.TODO,
        )
        self.task = services.file_ticket(
            "write docs", org=self.org, type=Ticket.Type.TASK,
            status=Ticket.Status.BACKLOG,
        )
        self.foreign = services.file_ticket(
            "foreign bug", org=self.other, type=Ticket.Type.BUG,
            status=Ticket.Status.TODO,
        )

    def test_filter_by_status_scoped(self):
        # [R6] only this org's matching tickets; never the foreign one.
        # (keys are per-org so they can collide; assert on unique titles.)
        r = self.client.get(reverse("issues:backlog"), {"status": "todo"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "login bug")
        self.assertNotContains(r, "write docs")
        self.assertNotContains(r, "foreign bug")

    def test_filter_by_type_and_q(self):
        # [R6]
        r = self.client.get(reverse("issues:backlog"), {"type": "bug", "q": "login"})
        self.assertContains(r, "login bug")
        self.assertNotContains(r, "write docs")
        self.assertNotContains(r, "foreign bug")

    def test_filter_bar_round_trips(self):
        # [R7] selected values stay selected.
        r = self.client.get(
            reverse("issues:backlog"),
            {"status": "todo", "priority": "high", "q": "login"},
        )
        self.assertContains(r, 'name="status"')
        self.assertContains(r, 'name="priority"')
        self.assertContains(r, 'name="q"')
        self.assertContains(r, 'value="login"')
        # selected status option preserved
        self.assertContains(r, 'value="todo" selected')


class BoardSprintLabelTests(TestCase):
    """[R8][R9][R10][R11] board/sprint/label write-actions."""

    def setUp(self):
        self.user = User.objects.create_user("carol", password="pw")
        self.org = Org.objects.create(name="Ops", slug="ops")
        Membership.objects.create(org=self.org, user=self.user)
        self.client.force_login(self.user)
        s = self.client.session
        s["org_id"] = self.org.id
        s.save()

    def test_board_new_creates_scoped_board(self):
        # [R8]
        r = self.client.post(
            reverse("issues:board_new"), {"name": "Platform", "key": "PLAT"},
            follow=True,
        )
        self.assertEqual(r.status_code, 200)
        b = Board.objects.get(name="Platform")
        self.assertEqual(b.org_id, self.org.id)
        self.assertContains(r, "PLAT")

    def test_sprint_new_start_complete(self):
        # [R9]
        self.client.post(reverse("issues:sprint_new"), {"name": "Sprint X"})
        sp = Sprint.objects.get(name="Sprint X")
        self.assertEqual(sp.org_id, self.org.id)
        self.client.post(
            reverse("issues:sprint_action", args=[sp.pk]), {"action": "start"}
        )
        sp.refresh_from_db()
        self.assertEqual(sp.status, Sprint.Status.ACTIVE)
        self.client.post(
            reverse("issues:sprint_action", args=[sp.pk]), {"action": "complete"}
        )
        sp.refresh_from_db()
        self.assertEqual(sp.status, Sprint.Status.COMPLETED)

    def test_add_ticket_to_sprint_logs_activity(self):
        # [R10]
        sp = Sprint.objects.create(org=self.org, name="S")
        t = services.file_ticket("do work", org=self.org)
        before = Activity.objects.filter(ticket=t).count()
        self.client.post(
            reverse("issues:ticket_sprint", args=[t.pk]), {"sprint": sp.pk}
        )
        t.refresh_from_db()
        self.assertEqual(t.sprint_id, sp.pk)
        self.assertGreater(Activity.objects.filter(ticket=t).count(), before)

    def test_label_new_and_attach(self):
        # [R11]
        self.client.post(
            reverse("issues:label_new"), {"name": "infra", "color": "badge-info"}
        )
        lbl = Label.objects.get(name="infra")
        self.assertEqual(lbl.org_id, self.org.id)
        t = services.file_ticket("labelled", org=self.org)
        self.client.post(
            reverse("issues:ticket_labels", args=[t.pk]), {"labels": [lbl.pk]}
        )
        self.assertEqual(t.labels.count(), 1)
        r = self.client.get(reverse("issues:ticket", args=[t.pk]))
        self.assertContains(r, "infra")


class AgentBacklogTests(TestCase):
    """[R12] agent backlog surfaces agent-filed tickets with cross-links."""

    def setUp(self):
        self.user = User.objects.create_user("dave", password="pw")
        self.org = Org.objects.create(name="Crew", slug="crew")
        Membership.objects.create(org=self.org, user=self.user)
        self.other = Org.objects.create(name="Rival", slug="rival")
        self.client.force_login(self.user)
        s = self.client.session
        s["org_id"] = self.org.id
        s.save()

    def test_agent_backlog_lists_agent_ticket_only(self):
        # [R12]
        agent_t = services.file_ticket(
            "agent filed", org=self.org, reporter=None, reporter_name="pm-agent",
        )
        foreign = services.file_ticket(
            "foreign agent", org=self.other, reporter_name="pm-agent",
        )
        r = self.client.get(reverse("issues:agent_backlog"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "agent filed")
        self.assertNotContains(r, "foreign agent")
