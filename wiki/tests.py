"""Wiki regression suite — covers the org-scoping, markdown, refs and feed rubric.

Each test builds its own user + org + membership and authenticates a Client so
``request.org`` is populated by ``CurrentOrgMiddleware``.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import Membership, Org
from core.models import Event
from projects.models import Project
from wiki.models import Page, PageRef, PageRevision, Space

User = get_user_model()


def make_org(slug="acme"):
    return Org.objects.create(name=slug.title(), slug=slug)


def make_user(username, org):
    user = User.objects.create_user(username=username, password="pw12345")
    Membership.objects.create(org=org, user=user, role=Membership.Role.OWNER)
    return user


class WikiBase(TestCase):
    def setUp(self):
        self.org = make_org("acme")
        self.user = make_user("alice", self.org)
        self.client.force_login(self.user)


# --------------------------------------------------------------------------- #
# URL reversing (R12)
# --------------------------------------------------------------------------- #
class ReverseTests(TestCase):
    def test_named_urls_reverse(self):
        reverse("wiki:index")
        reverse("wiki:space_new")
        reverse("wiki:space", args=["x"])
        reverse("wiki:page_new")
        reverse("wiki:page", args=[1])
        reverse("wiki:page_edit", args=[1])
        reverse("wiki:page_history", args=[1])
        reverse("wiki:revision", args=[1, 1])
        reverse("wiki:search")
        reverse("wiki:attach_ref", args=[1])
        reverse("wiki:remove_ref", args=[1, 1])


# --------------------------------------------------------------------------- #
# Landing + create flows (R13, R14, R15, R23, R24)
# --------------------------------------------------------------------------- #
class LandingTests(WikiBase):
    def test_landing_authed_with_org_200(self):
        resp = self.client.get(reverse("wiki:index"))
        self.assertEqual(resp.status_code, 200)

    def test_space_new_creates_one_space_for_org(self):
        before = Space.objects.count()
        resp = self.client.post(reverse("wiki:space_new"), {"name": "Engineering"})
        self.assertEqual(Space.objects.count(), before + 1)
        space = Space.objects.latest("id")
        self.assertEqual(space.org, self.org)

    def test_page_new_creates_page_and_revision_for_org(self):
        space = Space.objects.create(org=self.org, name="Docs")
        ev_before = Event.objects.count()
        resp = self.client.post(
            reverse("wiki:page_new"),
            {"space": space.slug, "title": "Hello", "body": "# Hi"},
        )
        page = Page.objects.get(title="Hello")
        self.assertEqual(page.org, self.org)
        self.assertTrue(PageRevision.objects.filter(page=page).exists())
        # R23: creating a page logs >=1 Event
        self.assertGreaterEqual(Event.objects.count(), ev_before + 1)

    def test_page_edit_logs_event(self):
        space = Space.objects.create(org=self.org, name="Docs")
        page = Page.objects.create(org=self.org, space=space, title="P", body="x")
        ev_before = Event.objects.count()
        self.client.post(
            reverse("wiki:page_edit_inline", args=[page.pk]),
            {"title": "P", "body": "changed"},
        )
        # R24: editing a page logs >=1 Event
        self.assertGreaterEqual(Event.objects.count(), ev_before + 1)


# --------------------------------------------------------------------------- #
# Markdown (R16, R17)
# --------------------------------------------------------------------------- #
class MarkdownTests(TestCase):
    def test_h1_renders_h1(self):
        from wiki.markdown import render_markdown

        out = render_markdown("# Title")
        self.assertIn("<h1>", out)

    def test_script_not_executable(self):
        from wiki.markdown import render_markdown

        out = render_markdown("<script>alert(1)</script>")
        self.assertNotIn("<script>", out)

    def test_renderer_never_raises(self):
        from wiki.markdown import render_markdown

        for body in ["", None, "**x", "[a](b)", "[[Loop]]", "```\nx"]:
            render_markdown(body)


# --------------------------------------------------------------------------- #
# Org isolation (R18)
# --------------------------------------------------------------------------- #
class IsolationTests(TestCase):
    def setUp(self):
        self.org_a = make_org("a")
        self.org_b = make_org("b")
        self.user_a = make_user("aa", self.org_a)
        self.client.force_login(self.user_a)
        space_b = Space.objects.create(org=self.org_b, name="B")
        self.page_b = Page.objects.create(
            org=self.org_b, space=space_b, title="Secret B", body="hidden"
        )

    def test_other_org_page_404(self):
        resp = self.client.get(reverse("wiki:page", args=[self.page_b.pk]))
        self.assertEqual(resp.status_code, 404)

    def test_other_org_page_absent_from_search(self):
        resp = self.client.get(reverse("wiki:search"), {"q": "Secret"})
        self.assertNotContains(resp, "Secret B")


# --------------------------------------------------------------------------- #
# Refs / related-work (R19, R20, R21, R22)
# --------------------------------------------------------------------------- #
class RefTests(WikiBase):
    def setUp(self):
        super().setUp()
        self.space = Space.objects.create(org=self.org, name="Docs")
        self.page = Page.objects.create(
            org=self.org, space=self.space, title="Runbook", body="body"
        )
        self.project = Project.objects.create(
            org=self.org, name="Web", slug="web", repo_url="https://x/y"
        )

    def test_attach_ref_creates_one_ref_for_org(self):
        before = PageRef.objects.count()
        resp = self.client.post(
            reverse("wiki:attach_ref", args=[self.page.pk]),
            {"kind": "project", "target": self.project.pk},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(PageRef.objects.count(), before + 1)
        ref = PageRef.objects.latest("id")
        self.assertEqual(ref.org, self.org)
        self.assertEqual(ref.project, self.project)

    def test_page_detail_with_project_ref_links_target(self):
        PageRef.objects.create(org=self.org, page=self.page, project=self.project)
        resp = self.client.get(reverse("wiki:page", args=[self.page.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, reverse("projects:detail", args=[self.project.slug]))

    def test_attach_ref_rejects_foreign_org_target(self):
        other = make_org("other")
        foreign = Project.objects.create(
            org=other, name="Foreign", slug="foreign", repo_url="https://x/z"
        )
        before = PageRef.objects.count()
        self.client.post(
            reverse("wiki:attach_ref", args=[self.page.pk]),
            {"kind": "project", "target": foreign.pk},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(PageRef.objects.count(), before)

    def test_page_detail_with_deleted_target_still_200(self):
        ref = PageRef.objects.create(
            org=self.org, page=self.page, project=self.project
        )
        self.project.delete()  # SET_NULL leaves a dangling ref
        ref.refresh_from_db()
        resp = self.client.get(reverse("wiki:page", args=[self.page.pk]))
        self.assertEqual(resp.status_code, 200)


# --------------------------------------------------------------------------- #
# Event.log resilience (R25)
# --------------------------------------------------------------------------- #
class FeedResilienceTests(WikiBase):
    def test_event_log_raising_still_saves_page(self):
        from unittest import mock

        space = Space.objects.create(org=self.org, name="Docs")
        with mock.patch(
            "core.models.Event.log", side_effect=RuntimeError("boom")
        ):
            resp = self.client.post(
                reverse("wiki:page_new"),
                {"space": space.slug, "title": "Survives", "body": "ok"},
            )
        self.assertTrue(Page.objects.filter(title="Survives").exists())
