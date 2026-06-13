"""Docs / Wiki models — org-scoped knowledge vault.

Every model subclasses ``accounts.models.OrgScopedModel`` which adds a nullable
``org`` FK + the ``OrgManager`` (``objects.for_org(...)`` / ``.for_current_org()``).
Org is kept nullable so background/autonomous code (which runs without a request)
can still create docs with ``org=None`` — this keeps the incident->fix loop and any
agent that wants to write a postmortem page working without a tenant context.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.text import slugify

from accounts.models import OrgScopedModel


class Space(OrgScopedModel):
    """A top-level container for pages (e.g. "Engineering", "Runbooks").

    Slug is unique per-org (see Meta.constraints) so two orgs can each have a
    space with the same slug.
    """

    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=140, blank=True)
    description = models.TextField(blank=True)
    icon = models.CharField(max_length=8, blank=True, default="📚")

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["org", "slug"], name="wiki_space_unique_org_slug"
            )
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = _unique_slug(
                Space, self.org_id, slugify(self.name) or "space", exclude_pk=self.pk
            )
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        from django.urls import reverse

        return reverse("wiki:space", args=[self.slug])

    @property
    def root_pages(self):
        return self.pages.filter(parent__isnull=True)


class Page(OrgScopedModel):
    """A markdown document. Pages form a tree via the nullable ``parent`` self-FK
    and belong to a ``Space``."""

    space = models.ForeignKey(
        Space, null=True, blank=True, on_delete=models.CASCADE, related_name="pages"
    )
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="children",
    )

    title = models.CharField(max_length=300)
    slug = models.SlugField(max_length=160, blank=True)
    body = models.TextField(blank=True, help_text="Markdown source")

    # Optional links back into the rest of Hull (additive; nullable).
    project = models.ForeignKey(
        "projects.Project",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["title"]
        indexes = [
            models.Index(fields=["org", "space"]),
            models.Index(fields=["org", "slug"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["space", "slug"], name="wiki_page_unique_space_slug"
            )
        ]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = _unique_page_slug(
                self.space_id, slugify(self.title) or "page", exclude_pk=self.pk
            )
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        from django.urls import reverse

        return reverse("wiki:page", args=[self.pk])

    def get_edit_url(self):
        from django.urls import reverse

        return reverse("wiki:page_edit", args=[self.pk])

    @property
    def rendered_html(self):
        from .markdown import render_markdown

        return render_markdown(self.body)

    @property
    def excerpt(self):
        text = " ".join(self.body.split())
        return text[:160]

    @property
    def breadcrumbs(self):
        """List of ancestor pages from root to self (inclusive)."""
        chain, node, seen = [], self, set()
        while node is not None and node.pk not in seen:
            seen.add(node.pk)
            chain.append(node)
            node = node.parent
        return list(reversed(chain))

    def snapshot_revision(self, user=None):
        """Persist the current body/title as an immutable PageRevision."""
        last = self.revisions.first()
        number = (last.number + 1) if last else 1
        return PageRevision.objects.create(
            org=self.org,
            page=self,
            number=number,
            title=self.title,
            body=self.body,
            edited_by=user if (user and getattr(user, "pk", None)) else None,
        )


class PageRevision(OrgScopedModel):
    """An immutable historical snapshot of a Page's title + body."""

    page = models.ForeignKey(
        Page, on_delete=models.CASCADE, related_name="revisions"
    )
    number = models.PositiveIntegerField(default=1)
    title = models.CharField(max_length=300)
    body = models.TextField(blank=True)
    edited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-number", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["page", "number"], name="wiki_revision_unique_page_number"
            )
        ]

    def __str__(self):
        return f"{self.page.title} v{self.number}"

    @property
    def rendered_html(self):
        from .markdown import render_markdown

        return render_markdown(self.body)


class PageLink(OrgScopedModel):
    """A wiki-style link from one page to another ([[Target]] syntax).

    ``target`` is resolved when possible; ``target_title`` always records the raw
    link text so unresolved (red) links can be surfaced.
    """

    source = models.ForeignKey(
        Page, on_delete=models.CASCADE, related_name="outgoing_links"
    )
    target = models.ForeignKey(
        Page,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="incoming_links",
    )
    target_title = models.CharField(max_length=300, blank=True)

    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["target_title"]
        indexes = [models.Index(fields=["org", "target"])]

    def __str__(self):
        return f"{self.source} -> {self.target or self.target_title}"

    @property
    def is_resolved(self):
        return self.target_id is not None


# --------------------------------------------------------------------------- #
# slug helpers (org/space-scoped uniqueness)
# --------------------------------------------------------------------------- #
def _unique_slug(model, org_id, base, exclude_pk=None):
    slug, n = base, 1
    qs = model.objects.filter(org_id=org_id)
    while qs.filter(slug=slug).exclude(pk=exclude_pk).exists():
        n += 1
        slug = f"{base}-{n}"
    return slug


def _unique_page_slug(space_id, base, exclude_pk=None):
    slug, n = base, 1
    qs = Page.objects.filter(space_id=space_id)
    while qs.filter(slug=slug).exclude(pk=exclude_pk).exists():
        n += 1
        slug = f"{base}-{n}"
    return slug
