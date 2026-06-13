"""Issues signal wiring — auto-advance a ticket when its linked PR merges.

ISSUES-11 (rework): ``advance_tickets_for_merged_pr`` is correct/idempotent/
loop-safe but needs a *caller*. The issues workstream cannot edit vcs files, so
instead of relying on the integrator to add a call inside ``vcs.services`` /
``vcs.views``, we wire the trigger entirely from within *our own* app via a
``post_save`` receiver on ``vcs.PullRequest``. Both real merge entry points
(``vcs.services.merge_pull_request`` and the manual-merge view
``vcs.views.pr_merge``) finish by calling ``pr.save(...)`` with the status set to
``merged``, so this receiver fires for every merge path — present and future —
with no cross-app edits.

HARD RULE: this is purely additive and must NEVER raise into a merge or the
autonomous incident -> fix loop. The connection is guarded (a missing/renamed
vcs app is a silent no-op) and the handler swallows everything; the underlying
service already guards ``status != 'merged'`` and the already-Done case, so it is
safe + idempotent to fire on every PR save.
"""

from __future__ import annotations


def _on_pull_request_saved(sender, instance, **kwargs):
    """Fire the fail-soft auto-advance whenever a PR is saved as merged.

    Never raises. The service is idempotent (no-ops when the PR isn't merged and
    when a linked ticket is already Done), so an unconditional call on every save
    is cheap and safe.
    """
    try:
        if getattr(instance, "status", None) != "merged":
            return
        from .services import advance_tickets_for_merged_pr

        advance_tickets_for_merged_pr(instance)
    except Exception:  # noqa: BLE001 — must never break a merge or the loop.
        pass


def connect():
    """Best-effort connect the post_save receiver to ``vcs.PullRequest``.

    Guarded so that if vcs (or the model) is unavailable the app still loads.
    """
    try:
        from django.db.models.signals import post_save

        from vcs.models import PullRequest

        post_save.connect(
            _on_pull_request_saved,
            sender=PullRequest,
            dispatch_uid="issues_advance_tickets_on_pr_merge",
        )
    except Exception:  # noqa: BLE001 — wiring failure must never break startup.
        pass
