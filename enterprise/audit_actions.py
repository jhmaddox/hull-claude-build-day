"""Canonical audit action-name constants (ENT-8). Pure strings, import-safe."""

from __future__ import annotations

PR_MERGED = "pr.merged"
DEPLOY_SHIPPED = "deploy.shipped"
INCIDENT_OPENED = "incident.opened"
INCIDENT_RESOLVED = "incident.resolved"
MEMBER_ADDED = "member.added"
MEMBER_ROLE_CHANGED = "member.role_changed"
MEMBER_REMOVED = "member.removed"
INVITE_SENT = "invite.sent"
APIKEY_CREATED = "apikey.created"
APIKEY_REVOKED = "apikey.revoked"
ORG_UPDATED = "org.updated"

ALL_ACTIONS = (
    PR_MERGED, DEPLOY_SHIPPED, INCIDENT_OPENED, INCIDENT_RESOLVED,
    MEMBER_ADDED, MEMBER_ROLE_CHANGED, MEMBER_REMOVED, INVITE_SENT,
    APIKEY_CREATED, APIKEY_REVOKED, ORG_UPDATED,
)
