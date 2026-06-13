"""oncall service layer.

Submodules:
- ``timeline`` — first-class incident timeline; ``record`` NEVER raises.
- ``routing``  — alert routing rules -> escalation policy / first on-call.
- ``escalation`` — pure escalation-step selection.

All hooks called from the autonomous loop must be best-effort and exception
safe so importing/using oncall can never block incident creation or
remediation.
"""

from . import escalation, routing, timeline  # noqa: F401

__all__ = ["timeline", "routing", "escalation"]
