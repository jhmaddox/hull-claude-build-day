"""Tests for the org-scoped, UX-polished VCS / Pull Request workstream."""

import subprocess
import tempfile

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import Membership, Org
from agents.models import Worktree
from core.models import Event
from projects.models import Project
from vcs import services
from vcs.diffrender import render_diff, split_diff
from vcs.models import PullRequest

User = get_user_model()


def _git(repo, *args):
    return subprocess.run(
        ["git", "-C", repo, *args], capture_output=True, text=True
    )


def _make_repo():
    """Create a tiny real git repo with a feature branch that diffs from main."""
    repo = tempfile.mkdtemp(prefix="vcs-test-")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@t.dev")
    _git(repo, "config", "user.name", "Tester")
    with open(f"{repo}/a.py", "w") as fh:
        fh.write("print('hello')\n")
    with open(f"{repo}/b.py", "w") as fh:
        fh.write("x = 1\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    _git(repo, "checkout", "-q", "-b", "feature")
    with open(f"{repo}/a.py", "w") as fh:
        fh.write("print('hello world')\n")
    with open(f"{repo}/b.py", "w") as fh:
        fh.write("x = 2\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "feature change")
    _git(repo, "checkout", "-q", "main")
    return repo


class OrgIsolationTests(TestCase):
    def setUp(self):
        self.org_a = Org.objects.create(name="A", slug="a")
        self.org_b = Org.objects.create(name="B", slug="b")
        self.user_a = User.objects.create_user("alice", password="pw")
        self.user_b = User.objects.create_user("bob", password="pw")
        Membership.objects.create(org=self.org_a, user=self.user_a)
        Membership.objects.create(org=self.org_b, user=self.user_b)

        self.proj_a = Project.objects.create(name="PA", slug="pa", org=self.org_a)
        self.proj_b = Project.objects.create(name="PB", slug="pb", org=self.org_b)

        self.pr_a = PullRequest.objects.create(
            org=self.org_a, project=self.proj_a, number=1,
            title="A PR", head_branch="feat-a",
        )
        self.pr_b = PullRequest.objects.create(
            org=self.org_b, project=self.proj_b, number=1,
            title="B PR", head_branch="feat-b",
        )

    def test_list_org_isolated(self):
        self.client.force_login(self.user_a)
        resp = self.client.get(reverse("vcs:list"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "A PR")
        self.assertNotContains(resp, "B PR")

    def test_detail_cross_org_404(self):
        self.client.force_login(self.user_a)
        resp = self.client.get(reverse("vcs:pr_detail", args=[self.pr_b.pk]))
        self.assertEqual(resp.status_code, 404)
        # own PR is fine
        ok = self.client.get(reverse("vcs:pr_detail", args=[self.pr_a.pk]))
        self.assertEqual(ok.status_code, 200)

    def test_ci_status_cross_org_404(self):
        self.client.force_login(self.user_a)
        resp = self.client.get(reverse("vcs:pr_ci_status", args=[self.pr_b.pk]))
        self.assertEqual(resp.status_code, 404)
        ok = self.client.get(reverse("vcs:pr_ci_status", args=[self.pr_a.pk]))
        self.assertEqual(ok.status_code, 200)

    def test_run_ci_cross_org_404(self):
        self.client.force_login(self.user_a)
        resp = self.client.post(reverse("vcs:pr_ci", args=[self.pr_b.pk]))
        self.assertEqual(resp.status_code, 404)

    def test_merge_cross_org_404(self):
        self.client.force_login(self.user_a)
        resp = self.client.post(reverse("vcs:pr_merge", args=[self.pr_b.pk]))
        self.assertEqual(resp.status_code, 404)

    def test_list_requires_org(self):
        # anonymous -> redirected (login), not 200
        resp = self.client.get(reverse("vcs:list"))
        self.assertEqual(resp.status_code, 302)


class LegacyFallbackTests(TestCase):
    def setUp(self):
        self.org = Org.objects.create(name="A", slug="a")
        self.user = User.objects.create_user("alice", password="pw")
        Membership.objects.create(org=self.org, user=self.user)
        self.proj = Project.objects.create(name="PA", slug="pa", org=self.org)
        # Legacy / loop-created PR: org=NULL but project belongs to this org.
        self.legacy_pr = PullRequest.objects.create(
            org=None, project=self.proj, number=7,
            title="Loop PR", head_branch="loop",
        )

    def test_legacy_null_pr_visible_to_matching_member(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse("vcs:list"))
        self.assertContains(resp, "Loop PR")
        detail = self.client.get(
            reverse("vcs:pr_detail", args=[self.legacy_pr.pk])
        )
        self.assertEqual(detail.status_code, 200)

    def test_orgless_project_null_pr_visible(self):
        # Project with no org + PR with no org -> still visible to a member.
        orphan_proj = Project.objects.create(name="O", slug="o", org=None)
        orphan_pr = PullRequest.objects.create(
            org=None, project=orphan_proj, number=1,
            title="Orphan PR", head_branch="orph",
        )
        self.client.force_login(self.user)
        resp = self.client.get(reverse("vcs:pr_detail", args=[orphan_pr.pk]))
        self.assertEqual(resp.status_code, 200)


class LoopOpenMergeTests(TestCase):
    """The autonomous loop path: open + merge with org=None must work."""

    def test_open_and_merge_with_org_none(self):
        repo = _make_repo()
        proj = Project.objects.create(
            name="Loop", slug="loop", org=None, local_path=repo
        )
        wt = Worktree.objects.create(
            project=proj, name="w", branch="feature", base_branch="main", path=repo
        )
        pr = services.open_pull_request(wt, title="loop fix")
        self.assertIsNotNone(pr)
        self.assertIsNone(pr.org)
        self.assertTrue(pr.diff.strip())
        self.assertEqual(pr.files_changed, 2)
        # Event emitted with icon pr
        self.assertTrue(
            Event.objects.filter(icon="pr").exists(), "open should emit pr event"
        )

        ok = services.merge_pull_request(pr)
        self.assertTrue(ok)
        pr.refresh_from_db()
        self.assertEqual(pr.status, PullRequest.Status.MERGED)
        self.assertTrue(
            Event.objects.filter(icon="merge").exists(), "merge should emit merge event"
        )

    def test_open_project_without_org_attr_does_not_raise(self):
        repo = _make_repo()
        proj = Project.objects.create(
            name="NoOrg", slug="noorg", org=None, local_path=repo
        )
        wt = Worktree.objects.create(
            project=proj, name="w", branch="feature", base_branch="main", path=repo
        )
        # getattr(project, 'org', None) is None -> must not raise
        pr = services.open_pull_request(wt, title="x")
        self.assertIsNotNone(pr)
        self.assertIsNone(pr.org)

    def test_open_inherits_project_org(self):
        repo = _make_repo()
        org = Org.objects.create(name="A", slug="a")
        proj = Project.objects.create(
            name="P", slug="p", org=org, local_path=repo
        )
        wt = Worktree.objects.create(
            project=proj, name="w", branch="feature", base_branch="main", path=repo
        )
        pr = services.open_pull_request(wt, title="scoped")
        self.assertEqual(pr.org_id, org.id)


class DiffRenderTests(TestCase):
    SAMPLE = (
        "diff --git a/a.py b/a.py\n"
        "index 111..222 100644\n"
        "--- a/a.py\n"
        "+++ b/a.py\n"
        "@@ -1 +1 @@\n"
        "-print('hello')\n"
        "+print('hello world')\n"
        "diff --git a/b.py b/b.py\n"
        "index 333..444 100644\n"
        "--- a/b.py\n"
        "+++ b/b.py\n"
        "@@ -1 +1 @@\n"
        "-x = 1\n"
        "+x = 2\n"
    )

    def test_render_diff_still_works(self):
        html = render_diff(self.SAMPLE)
        self.assertIn("diff", html)
        self.assertIn("add", html)
        self.assertIn("del", html)

    def test_render_diff_empty(self):
        self.assertIn("No changes", render_diff(""))

    def test_split_diff_per_file(self):
        files = split_diff(self.SAMPLE)
        self.assertEqual(len(files), 2)
        paths = {f["path"] for f in files}
        self.assertEqual(paths, {"a.py", "b.py"})
        for f in files:
            self.assertEqual(f["additions"], 1)
            self.assertEqual(f["deletions"], 1)
            self.assertIn("class=\"line", f["html"])

    def test_split_diff_empty(self):
        self.assertEqual(split_diff(""), [])

    def test_detail_renders_per_file_cards(self):
        org = Org.objects.create(name="A", slug="a")
        user = User.objects.create_user("alice", password="pw")
        Membership.objects.create(org=org, user=user)
        proj = Project.objects.create(name="P", slug="p", org=org)
        pr = PullRequest.objects.create(
            org=org, project=proj, number=1, title="multi",
            head_branch="f", diff=self.SAMPLE, files_changed=2,
        )
        self.client.force_login(user)
        resp = self.client.get(reverse("vcs:pr_detail", args=[pr.pk]))
        self.assertContains(resp, "a.py")
        self.assertContains(resp, "b.py")
        # collapsible per-file card
        self.assertContains(resp, "<details")
        # permalink present
        self.assertContains(resp, "pr-permalink")


class ConflictDetectionTests(TestCase):
    def test_conflict_detection_is_read_only(self):
        repo = _make_repo()
        org = Org.objects.create(name="A", slug="a")
        user = User.objects.create_user("alice", password="pw")
        Membership.objects.create(org=org, user=user)
        proj = Project.objects.create(
            name="P", slug="p", org=org, local_path=repo
        )
        pr = PullRequest.objects.create(
            org=org, project=proj, number=1, title="t",
            base_branch="main", head_branch="feature",
        )
        before = _git(repo, "rev-parse", "main").stdout.strip()
        self.client.force_login(user)
        resp = self.client.get(reverse("vcs:pr_detail", args=[pr.pk]))
        self.assertEqual(resp.status_code, 200)
        # repo must be unchanged + no in-progress merge
        after = _git(repo, "rev-parse", "main").stdout.strip()
        self.assertEqual(before, after)
        status = _git(repo, "status", "--porcelain").stdout.strip()
        self.assertEqual(status, "", "working tree must stay clean")
        # this PR has no conflicts -> mergeable
        self.assertTrue(resp.context["mergeable"])

    def test_unknown_repo_degrades_to_mergeable(self):
        org = Org.objects.create(name="A", slug="a")
        user = User.objects.create_user("alice", password="pw")
        Membership.objects.create(org=org, user=user)
        proj = Project.objects.create(name="P", slug="p", org=org, local_path="")
        pr = PullRequest.objects.create(
            org=org, project=proj, number=1, title="t", head_branch="f",
        )
        self.client.force_login(user)
        resp = self.client.get(reverse("vcs:pr_detail", args=[pr.pk]))
        # no repo -> unknown -> button enabled (loop never blocked)
        self.assertTrue(resp.context["mergeable"])

    def test_merged_pr_not_mergeable(self):
        org = Org.objects.create(name="A", slug="a")
        user = User.objects.create_user("alice", password="pw")
        Membership.objects.create(org=org, user=user)
        proj = Project.objects.create(name="P", slug="p", org=org, local_path="")
        pr = PullRequest.objects.create(
            org=org, project=proj, number=1, title="t", head_branch="f",
            status=PullRequest.Status.MERGED,
        )
        self.client.force_login(user)
        resp = self.client.get(reverse("vcs:pr_detail", args=[pr.pk]))
        self.assertFalse(resp.context["mergeable"])
        self.assertTrue(resp.context["merge_blocked_reason"])
