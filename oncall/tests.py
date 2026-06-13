"""Tests for the oncall (Incidents v2) app.

Covers: rotation (R9), escalation ordering (R10), routing incl. cross-org (R11),
timeline record + org=None (R12/R8), ack+resolve (R13/R14), note/assign (R15),
tick idempotency (R16), tenant isolation (R18), anonymous redirect (R19),
postmortem (R17), Event emission (R21), and loop-survives-oncall-failure (R7).
"""

from __future__ import annotations

import datetime as dt
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.utils import timezone

from accounts.models import Membership, Org
from core.models import Event
from observability.models import Incident
from projects.models import Project

from .models import (
    EscalationPolicy,
    EscalationStep,
    Postmortem,
    RoutingRule,
    Schedule,
    ScheduleMember,
    TimelineEntry,
)
from .services import escalation, routing, timeline

User = get_user_model()


def _mk_org(slug):
    return Org.objects.create(name=slug.title(), slug=slug)


def _mk_user(name, org):
    u = User.objects.create_user(username=name, password="pw")
    Membership.objects.create(org=org, user=u, role=Membership.Role.MEMBER)
    return u


_PROJ_SEQ = {"n": 0}


def _mk_incident(org=None, project=None, severity="sev2", status="firing"):
    if project is None:
        # Incident.project is non-nullable; make a throwaway project.
        _PROJ_SEQ["n"] += 1
        project = Project.objects.create(
            name=f"proj{_PROJ_SEQ['n']}", slug=f"proj{_PROJ_SEQ['n']}", org=org
        )
    return Incident.objects.create(
        org=org,
        project=project,
        number=Incident.objects.count() + 1,
        title="boom",
        severity=severity,
        status=status,
    )


# --------------------------------------------------------------------------- #
# R9 — weekly rotation
# --------------------------------------------------------------------------- #
class RotationTests(TestCase):
    def setUp(self):
        self.org = _mk_org("acme")
        self.sched = Schedule.objects.create(name="primary", org=self.org)
        self.a = _mk_user("alice", self.org)
        self.b = _mk_user("bob", self.org)
        ScheduleMember.objects.create(schedule=self.sched, org=self.org, user=self.a, order=0)
        ScheduleMember.objects.create(schedule=self.sched, org=self.org, user=self.b, order=1)

    def test_empty_schedule_returns_none(self):
        empty = Schedule.objects.create(name="empty", org=self.org)
        self.assertIsNone(empty.current_oncall())

    def test_rotates_across_iso_weeks(self):
        # Two timestamps one ISO week apart should yield different members.
        wk1 = dt.datetime(2026, 1, 5, 12, 0, tzinfo=dt.timezone.utc)  # ISO week 2
        wk2 = wk1 + dt.timedelta(days=7)
        m1 = self.sched.current_oncall(at=wk1)
        m2 = self.sched.current_oncall(at=wk2)
        self.assertIsNotNone(m1)
        self.assertIsNotNone(m2)
        self.assertNotEqual(m1.pk, m2.pk)
        # Deterministic by week index mod member count.
        self.assertEqual(self.sched.current_oncall(at=wk1 + dt.timedelta(days=14)).pk, m1.pk)


# --------------------------------------------------------------------------- #
# R10 — escalation ordering
# --------------------------------------------------------------------------- #
class EscalationTests(TestCase):
    def setUp(self):
        self.org = _mk_org("acme")
        self.policy = EscalationPolicy.objects.create(name="p", org=self.org)
        self.s0 = EscalationStep.objects.create(policy=self.policy, org=self.org, after_minutes=0, order=0)
        self.s1 = EscalationStep.objects.create(policy=self.policy, org=self.org, after_minutes=10, order=1)
        self.s2 = EscalationStep.objects.create(policy=self.policy, org=self.org, after_minutes=30, order=2)

    def test_first_step_at_zero(self):
        self.assertEqual(escalation.next_step(self.policy, 0).pk, self.s0.pk)

    def test_highest_eligible(self):
        self.assertEqual(escalation.next_step(self.policy, 9).pk, self.s0.pk)
        self.assertEqual(escalation.next_step(self.policy, 10).pk, self.s1.pk)
        self.assertEqual(escalation.next_step(self.policy, 100).pk, self.s2.pk)

    def test_monotonic(self):
        prev = -1
        for m in range(0, 60):
            step = escalation.next_step(self.policy, m)
            self.assertGreaterEqual(step.order, prev)
            prev = step.order

    def test_none_policy(self):
        self.assertIsNone(escalation.next_step(None, 5))


# --------------------------------------------------------------------------- #
# R11 / R8 — routing incl cross-org + org=None safety
# --------------------------------------------------------------------------- #
class RoutingTests(TestCase):
    def setUp(self):
        self.orgA = _mk_org("a")
        self.orgB = _mk_org("b")
        self.polA = EscalationPolicy.objects.create(name="pa", org=self.orgA)
        self.polB = EscalationPolicy.objects.create(name="pb", org=self.orgB)
        self.ruleA = RoutingRule.objects.create(
            name="A-all", org=self.orgA, min_severity="sev3", policy=self.polA, priority=0
        )
        self.ruleB = RoutingRule.objects.create(
            name="B-all", org=self.orgB, min_severity="sev3", policy=self.polB, priority=0
        )

    def test_routes_within_org(self):
        inc = _mk_incident(org=self.orgA, severity="sev2")
        self.assertEqual(routing.route(inc).pk, self.ruleA.pk)

    def test_never_cross_org(self):
        inc = _mk_incident(org=self.orgA, severity="sev1")
        r = routing.route(inc)
        self.assertNotEqual(r.pk, self.ruleB.pk)

    def test_priority_order(self):
        hi = RoutingRule.objects.create(
            name="A-hi", org=self.orgA, min_severity="sev3", policy=self.polA, priority=-5
        )
        inc = _mk_incident(org=self.orgA, severity="sev2")
        self.assertEqual(routing.route(inc).pk, hi.pk)

    def test_severity_floor(self):
        sev1only = RoutingRule.objects.create(
            name="sev1", org=self.orgA, min_severity="sev1", policy=self.polA, priority=-10
        )
        inc3 = _mk_incident(org=self.orgA, severity="sev3")
        # sev1-only rule must NOT match a sev3 incident -> falls to ruleA.
        self.assertEqual(routing.route(inc3).pk, self.ruleA.pk)
        inc1 = _mk_incident(org=self.orgA, severity="sev1")
        self.assertEqual(routing.route(inc1).pk, sev1only.pk)

    def test_project_filter(self):
        proj = Project.objects.create(name="p", slug="p", org=self.orgA)
        scoped_rule = RoutingRule.objects.create(
            name="proj", org=self.orgA, min_severity="sev3",
            policy=self.polA, project=proj, priority=-1,
        )
        inc_other = _mk_incident(org=self.orgA, project=None, severity="sev2")
        self.assertEqual(routing.route(inc_other).pk, self.ruleA.pk)
        inc_proj = _mk_incident(org=self.orgA, project=proj, severity="sev2")
        self.assertEqual(routing.route(inc_proj).pk, scoped_rule.pk)

    def test_org_none_safe(self):
        inc = _mk_incident(org=None, severity="sev2")
        # Must not raise and must not return another org's rule.
        self.assertIsNone(routing.route(inc))


# --------------------------------------------------------------------------- #
# R12 / R8 — timeline record + org=None
# --------------------------------------------------------------------------- #
class TimelineTests(TestCase):
    def test_record_persists(self):
        inc = _mk_incident()
        e = timeline.record(inc, "note", "x")
        self.assertIsNotNone(e)
        self.assertEqual(e.kind, "note")
        self.assertEqual(e.message, "x")
        self.assertEqual(TimelineEntry.objects.filter(incident=inc).count(), 1)

    def test_org_none_does_not_raise(self):
        inc = _mk_incident(org=None)
        self.assertIsNone(inc.org)
        timeline.record(inc, "note", "x")  # must not raise
        self.assertIsNone(routing.route(inc))  # must not raise

    def test_chronological(self):
        inc = _mk_incident()
        timeline.record(inc, "opened", "1")
        timeline.record(inc, "note", "2")
        kinds = [e.kind for e in timeline.for_incident(inc)]
        self.assertEqual(kinds, ["opened", "note"])


# --------------------------------------------------------------------------- #
# R7 — loop survives oncall failure
# --------------------------------------------------------------------------- #
class FallbackTests(TestCase):
    def test_record_never_raises(self):
        inc = _mk_incident()
        with mock.patch("oncall.models.TimelineEntry.objects") as m:
            m.create.side_effect = RuntimeError("db down")
            # Must swallow and return None, never raise.
            self.assertIsNone(timeline.record(inc, "note", "x"))

    def test_loop_hook_swallows_record_failure(self):
        from .services import loop as loop_svc

        inc = _mk_incident()
        with mock.patch("oncall.services.timeline.record", side_effect=RuntimeError("boom")):
            # The hook must not propagate the failure.
            loop_svc.on_incident_opened(inc)
            loop_svc.on_incident_resolved(inc)

    def test_open_or_update_incident_survives_oncall_failure(self):
        """Even if oncall internals raise, the incident is still created."""
        import os

        from deploys.models import Deployment, Environment
        import observability.services as obs

        os.environ["HELM_AUTO_REMEDIATE"] = "0"
        org = _mk_org("acme")
        proj = Project.objects.create(name="p", slug="p", org=org)
        env = Environment.objects.create(project=proj, name="prod", branch="main", port=9100)
        dep = Deployment.objects.create(environment=env, commit_sha="abc", status="live", port=9100)
        with mock.patch("oncall.services.timeline.record", side_effect=RuntimeError("boom")):
            inc = obs.open_or_update_incident(
                dep, error_type="ValueError", error_message="bad", severity="sev2"
            )
        self.assertIsNotNone(inc)
        self.assertEqual(inc.error_type, "ValueError")


# --------------------------------------------------------------------------- #
# R13-R16, R21 — human actions + tick idempotency
# --------------------------------------------------------------------------- #
class ActionViewTests(TestCase):
    def setUp(self):
        self.org = _mk_org("acme")
        self.user = _mk_user("alice", self.org)
        self.client = Client()
        self.client.force_login(self.user)
        self.inc = _mk_incident(org=self.org, severity="sev2")

    def test_ack(self):
        before = Event.objects.count()
        r = self.client.post(f"/oncall/incidents/{self.inc.pk}/ack/")
        self.assertIn(r.status_code, (200, 302))
        self.inc.refresh_from_db()
        self.assertEqual(self.inc.status, "acknowledged")
        self.assertIsNotNone(self.inc.acknowledged_at)
        self.assertTrue(
            TimelineEntry.objects.filter(incident=self.inc, kind="acknowledged", user=self.user).exists()
        )
        self.assertEqual(Event.objects.count(), before + 1)

    def test_resolve(self):
        before = Event.objects.count()
        self.client.post(f"/oncall/incidents/{self.inc.pk}/resolve/")
        self.inc.refresh_from_db()
        self.assertEqual(self.inc.status, "resolved")
        self.assertIsNotNone(self.inc.resolved_at)
        self.assertTrue(TimelineEntry.objects.filter(incident=self.inc, kind="resolved").exists())
        self.assertEqual(Event.objects.count(), before + 1)

    def test_note(self):
        self.client.post(f"/oncall/incidents/{self.inc.pk}/note/", {"message": "hello"})
        e = TimelineEntry.objects.get(incident=self.inc, kind="note")
        self.assertEqual(e.message, "hello")

    def test_assign(self):
        self.client.post(f"/oncall/incidents/{self.inc.pk}/assign/", {"user": self.user.pk})
        e = TimelineEntry.objects.get(incident=self.inc, kind="assigned")
        self.assertEqual(e.user_id, self.user.pk)

    def test_tick_idempotent(self):
        # Build a policy with a step at 0 minutes routed to this org.
        sched = Schedule.objects.create(name="s", org=self.org)
        ScheduleMember.objects.create(schedule=sched, org=self.org, user=self.user, order=0)
        pol = EscalationPolicy.objects.create(name="p", org=self.org)
        EscalationStep.objects.create(policy=pol, org=self.org, target_schedule=sched, after_minutes=0, order=0)
        RoutingRule.objects.create(name="r", org=self.org, min_severity="sev3", policy=pol, priority=0)
        # Backdate the incident so it is past the threshold.
        Incident.objects.filter(pk=self.inc.pk).update(
            created_at=timezone.now() - dt.timedelta(minutes=5)
        )
        self.inc.refresh_from_db()
        self.client.post(f"/oncall/incidents/{self.inc.pk}/tick/")
        self.client.post(f"/oncall/incidents/{self.inc.pk}/tick/")
        self.assertEqual(
            TimelineEntry.objects.filter(incident=self.inc, kind="escalated", step_order=0).count(),
            1,
        )


# --------------------------------------------------------------------------- #
# R23 / R24 / R25 / R27 — severity change, reopen, board tick
# --------------------------------------------------------------------------- #
class SeverityChangeTests(TestCase):
    def setUp(self):
        self.org = _mk_org("acme")
        self.user = _mk_user("alice", self.org)
        self.client = Client()
        self.client.force_login(self.user)
        self.inc = _mk_incident(org=self.org, severity="sev2")

    def test_valid_change_records_entry_and_event(self):
        before = Event.objects.count()
        self.client.post(f"/oncall/incidents/{self.inc.pk}/severity/", {"severity": "sev1"})
        self.inc.refresh_from_db()
        self.assertEqual(self.inc.severity, "sev1")
        self.assertTrue(
            TimelineEntry.objects.filter(
                incident=self.inc, kind="severity_changed", user=self.user
            ).exists()
        )
        self.assertEqual(Event.objects.count(), before + 1)

    def test_invalid_change_rejected_no_crash(self):
        r = self.client.post(
            f"/oncall/incidents/{self.inc.pk}/severity/", {"severity": "nope"}
        )
        self.assertIn(r.status_code, (200, 302))
        self.inc.refresh_from_db()
        self.assertEqual(self.inc.severity, "sev2")
        self.assertFalse(
            TimelineEntry.objects.filter(incident=self.inc, kind="severity_changed").exists()
        )

    def test_detail_exposes_severity_selector(self):
        r = self.client.get(f"/oncall/incidents/{self.inc.pk}/")
        self.assertContains(r, f"/oncall/incidents/{self.inc.pk}/severity/")
        self.assertContains(r, 'name="severity"')


class ReopenTests(TestCase):
    def setUp(self):
        self.org = _mk_org("acme")
        self.user = _mk_user("alice", self.org)
        self.client = Client()
        self.client.force_login(self.user)
        self.inc = _mk_incident(org=self.org, severity="sev2", status="resolved")
        Incident.objects.filter(pk=self.inc.pk).update(resolved_at=timezone.now())
        self.inc.refresh_from_db()

    def test_reopen_resolved_incident(self):
        before = Event.objects.count()
        self.client.post(f"/oncall/incidents/{self.inc.pk}/reopen/")
        self.inc.refresh_from_db()
        self.assertEqual(self.inc.status, "firing")
        self.assertIsNone(self.inc.resolved_at)
        self.assertTrue(
            TimelineEntry.objects.filter(
                incident=self.inc, kind="reopened", user=self.user
            ).exists()
        )
        self.assertEqual(Event.objects.count(), before + 1)

    def test_reopen_noop_if_not_resolved(self):
        inc = _mk_incident(org=self.org, severity="sev2", status="firing")
        self.client.post(f"/oncall/incidents/{inc.pk}/reopen/")
        inc.refresh_from_db()
        self.assertEqual(inc.status, "firing")
        self.assertFalse(TimelineEntry.objects.filter(incident=inc, kind="reopened").exists())

    def test_reopen_control_only_for_resolved(self):
        r = self.client.get(f"/oncall/incidents/{self.inc.pk}/")
        self.assertContains(r, f"/oncall/incidents/{self.inc.pk}/reopen/")
        firing = _mk_incident(org=self.org, severity="sev2", status="firing")
        r2 = self.client.get(f"/oncall/incidents/{firing.pk}/")
        self.assertNotContains(r2, f"/oncall/incidents/{firing.pk}/reopen/")


class BoardTickTests(TestCase):
    def setUp(self):
        self.org = _mk_org("acme")
        self.user = _mk_user("alice", self.org)
        self.client = Client()
        self.client.force_login(self.user)
        self.inc = _mk_incident(org=self.org, severity="sev2", status="firing")

    def test_board_tick_200_and_invokes_escalation(self):
        with mock.patch("oncall.views.escalation.tick") as m:
            r = self.client.get("/oncall/board/tick/")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(m.called)
        self.assertContains(r, "/oncall/board/tick/")  # partial re-wires polling

    def test_board_tick_survives_tick_exception(self):
        with mock.patch(
            "oncall.views.escalation.tick", side_effect=RuntimeError("boom")
        ):
            r = self.client.get("/oncall/board/tick/")
        self.assertEqual(r.status_code, 200)

    def test_board_includes_polling_partial(self):
        r = self.client.get("/oncall/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "/oncall/board/tick/")
        self.assertContains(r, 'hx-trigger="every 10s"')


# --------------------------------------------------------------------------- #
# R17 — postmortem
# --------------------------------------------------------------------------- #
class PostmortemTests(TestCase):
    def setUp(self):
        self.org = _mk_org("acme")
        self.user = _mk_user("alice", self.org)
        self.client = Client()
        self.client.force_login(self.user)
        self.inc = _mk_incident(org=self.org, severity="sev1", status="resolved")

    def test_create_with_action_items(self):
        self.client.post(
            f"/oncall/incidents/{self.inc.pk}/postmortem/",
            {"summary": "s", "root_cause": "rc", "action_item": ["fix x", "fix y"]},
        )
        pm = Postmortem.objects.get(incident=self.inc)
        self.assertEqual(pm.summary, "s")
        self.assertEqual([a.title for a in pm.ordered_action_items()], ["fix x", "fix y"])

    def test_auto_stub_on_resolve(self):
        from .services import loop as loop_svc

        inc = _mk_incident(org=self.org, severity="sev1", status="resolved")
        loop_svc.on_incident_resolved(inc)
        self.assertTrue(Postmortem.objects.filter(incident=inc).exists())


# --------------------------------------------------------------------------- #
# R18 / R19 — tenant isolation + anonymous redirect
# --------------------------------------------------------------------------- #
class IsolationTests(TestCase):
    def setUp(self):
        self.orgA = _mk_org("a")
        self.orgB = _mk_org("b")
        self.userA = _mk_user("alice", self.orgA)
        self.incB = _mk_incident(org=self.orgB, severity="sev2")
        Schedule.objects.create(name="B-sched", org=self.orgB)

    def test_member_cannot_see_other_org_incident(self):
        c = Client()
        c.force_login(self.userA)
        r = c.get(f"/oncall/incidents/{self.incB.pk}/")
        self.assertEqual(r.status_code, 404)

    def test_board_excludes_other_org(self):
        c = Client()
        c.force_login(self.userA)
        r = c.get("/oncall/")
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, f"INC-{self.incB.number}")

    def test_schedules_excludes_other_org(self):
        c = Client()
        c.force_login(self.userA)
        r = c.get("/oncall/schedules/")
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, "B-sched")

    def test_anonymous_redirected_to_login(self):
        c = Client()
        for url in ("/oncall/", f"/oncall/incidents/{self.incB.pk}/ack/", "/oncall/schedules/"):
            r = c.get(url)
            self.assertIn(r.status_code, (301, 302))
            self.assertIn("/accounts/login", r.url)
