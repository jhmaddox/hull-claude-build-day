"""Tests for the Issues (Jira) app — exercises the rubric."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import Membership, Org

from . import services
from .models import Activity, Board, Comment, Sprint, Ticket

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
