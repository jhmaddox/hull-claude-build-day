"""End-to-end smoke test for Slice B using the fake claude stub.

Run with:
    HELM_CLAUDE_BIN=/abs/tests/fake_claude.sh \
    DJANGO_SETTINGS_MODULE=helm.settings \
    python tests/e2e_sliceb.py
"""

import os
import subprocess
import sys
import tempfile

import django

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "helm.settings")
django.setup()

from agents import services as agent_services  # noqa: E402
from agents.models import AgentRun  # noqa: E402
from projects.models import Project  # noqa: E402
from vcs.models import PullRequest  # noqa: E402


def run(cmd, cwd):
    subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True)


def main():
    repo = tempfile.mkdtemp(prefix="helm_e2e_repo_")
    run(["git", "init", "-b", "main"], repo)
    run(["git", "config", "user.email", "t@t.dev"], repo)
    run(["git", "config", "user.name", "Test"], repo)
    with open(os.path.join(repo, "README.md"), "w") as f:
        f.write("# test repo\n")
    run(["git", "add", "-A"], repo)
    run(["git", "commit", "-m", "init"], repo)

    slug = "e2e-" + os.path.basename(repo)[-6:]
    project = Project.objects.create(
        name="E2E Project",
        slug=slug,
        local_path=repo,
        default_branch="main",
        status="ready",
    )

    run_obj = agent_services.launch_agent(
        project,
        kind=AgentRun.Kind.FEATURE,
        title="Add marker file",
        prompt="Add a marker file.",
        open_pr=True,
        dispatch=False,  # run inline
    )
    agent_services.run_agent(run_obj)

    run_obj.refresh_from_db()
    print("status     :", run_obj.status)
    print("num_turns  :", run_obj.num_turns)
    print("cost_usd   :", run_obj.cost_usd)
    print("output:\n" + run_obj.output)
    print("result_summary:", run_obj.result_summary)

    assert run_obj.status == AgentRun.Status.DONE, "agent did not finish"
    assert run_obj.num_turns == 2, "turns not captured"
    assert abs((run_obj.cost_usd or 0) - 0.0123) < 1e-6, "cost not captured"
    assert "session started" in run_obj.output, "init not streamed"
    assert "Write AGENT_WAS_HERE.txt" in run_obj.output, "tool_use not streamed"

    # Verify the commit landed in the worktree branch.
    log = subprocess.run(
        ["git", "-C", run_obj.worktree.path, "log", "--oneline"],
        capture_output=True, text=True,
    ).stdout
    print("worktree log:\n" + log)
    assert "Add marker file" in log, "commit not created"

    # Verify PR exists with a diff.
    pr = run_obj.pull_request
    assert pr is not None, "PR not created"
    assert pr.additions >= 1, "PR has no additions"
    assert pr.diff.strip(), "PR diff empty"
    print(f"PR #{pr.number}: +{pr.additions} -{pr.deletions} files={pr.files_changed} ci={pr.ci_status}")

    # Verify merge works.
    from vcs.services import merge_pull_request
    ok = merge_pull_request(pr)
    pr.refresh_from_db()
    print("merge ok   :", ok, "pr.status:", pr.status)
    assert ok and pr.status == PullRequest.Status.MERGED, "merge failed"

    # Cleanup DB rows so we don't pollute the shared sqlite. Delete leaf rows
    # individually (avoid Project cascade, which can touch tables owned by
    # other slices that may not be migrated yet during a partial build).
    from agents.models import Worktree
    from core.models import Event

    pr_pk, run_pk, wt_pk, proj_pk = pr.pk, run_obj.pk, run_obj.worktree.pk, project.pk
    AgentRun.objects.filter(pk=run_pk).delete()
    PullRequest.objects.filter(pk=pr_pk).delete()
    Worktree.objects.filter(pk=wt_pk).delete()
    Event.objects.filter(project_id=proj_pk).delete()
    try:
        Project.objects.filter(pk=proj_pk).delete()
    except Exception as e:  # noqa: BLE001
        # Partial-build environment: leave a tiny orphan project rather than
        # crash the smoke test. Not a Slice B concern.
        print(f"(note) project cleanup skipped: {e}")

    print("\nALL ASSERTIONS PASSED ✓")


if __name__ == "__main__":
    main()
