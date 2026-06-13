from django.apps import AppConfig


class IssuesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "issues"
    verbose_name = "Issues (Jira)"

    def ready(self):
        # ISSUES-11: auto-advance a ticket to Done when its linked PR merges.
        # Wired entirely from within the issues app via a guarded post_save
        # receiver on vcs.PullRequest (no cross-app edits). Fail-soft: a wiring
        # error must never break startup, a merge, or the autonomous loop.
        try:
            from . import signals

            signals.connect()
        except Exception:  # noqa: BLE001 — defensive; startup must never break.
            pass
