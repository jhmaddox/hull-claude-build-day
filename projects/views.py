import threading

from django.contrib import messages
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from accounts.scoping import org_required, visible

from .health import health_verdict
from .models import Project


def _portfolio_summary(projects):
    """Org-scoped portfolio counts from the (prefetched) project set.

    Reflects the whole org portfolio, independent of any active q/status filter,
    so the caller passes the unfiltered org-scoped list. Reads only prefetched
    relations (environments+deployments, incidents) so it adds no per-project
    queries. Each project is expected to carry an attached ``.health`` verdict.

    Returns: total, live (>=1 env current deployment live), failed
    (status == failed), incidents (>=1 unresolved incident).
    """
    total = len(projects)
    live = failed = incidents = 0
    for p in projects:
        v = getattr(p, "health", None) or health_verdict(p)
        if v.live_count:
            live += 1
        if p.status == Project.Status.FAILED:
            failed += 1
        if v.open_incident_count:
            incidents += 1
    return {"total": total, "live": live, "failed": failed, "incidents": incidents}


def _scoped_project_qs(request):
    """Org-scoped Project queryset prefetching environments -> their non-stopped
    deployments (newest first) and incidents, so the health verdict + summary +
    per-card badges render N projects without O(N) queries."""
    from deploys.models import Deployment

    deploy_qs = Deployment.objects.exclude(
        status=Deployment.Status.STOPPED
    ).order_by("-created_at")
    return visible(Project, request).prefetch_related(
        Prefetch("environments__deployments", queryset=deploy_qs),
        "environments",
        "incidents",
    )


@org_required
def project_list(request):
    # Whole org portfolio first (drives the summary strip, independent of the
    # active q/status filter). Attach the verdict once per project so the
    # summary + per-card badges reuse it and the template stays logic-light.
    all_projects = list(_scoped_project_qs(request))
    for p in all_projects:
        p.health = health_verdict(p)
    summary = _portfolio_summary(all_projects)

    # --- org-scoped search (?q=) + validated status filter (?status=) ---
    q = (request.GET.get("q") or "").strip()
    raw_status = (request.GET.get("status") or "").strip()
    valid_statuses = {c[0] for c in Project.Status.choices}
    status = raw_status if raw_status in valid_statuses else ""

    projects = all_projects
    if q:
        needle = q.lower()
        projects = [
            p
            for p in projects
            if needle in (p.name or "").lower()
            or needle in (p.repo_url or "").lower()
            or needle in (p.local_path or "").lower()
        ]
    if status:
        projects = [p for p in projects if p.status == status]

    return render(
        request,
        "projects/list.html",
        {
            "projects": projects,
            "org": request.org,
            "project_count": len(projects),
            "total_count": summary["total"],
            "summary": summary,
            "q": q,
            "status": status,
            "statuses": Project.Status.choices,
            "has_query": bool(q or status),
        },
    )


@org_required
def project_new(request):
    if request.method == "POST":
        name = (request.POST.get("name") or "").strip()
        repo_url = (request.POST.get("repo_url") or "").strip()
        description = (request.POST.get("description") or "").strip()
        if not name or not repo_url:
            messages.error(request, "Name and repository URL are required.")
            return render(
                request,
                "projects/new.html",
                {"name": name, "repo_url": repo_url, "description": description},
            )

        # Create the project shell synchronously + redirect straight to its page
        # so the user watches the live import stepper. The clone/detect/deploy
        # work runs in the background.
        from . import services as project_services

        org = getattr(request, "org", None)
        project = project_services.begin_import(
            name, repo_url, description=description, org=org
        )
        threading.Thread(
            target=_import_in_background, args=(project.id,), daemon=True
        ).start()
        messages.success(request, f"Importing {name}…")
        return redirect(project.get_absolute_url())

    return render(request, "projects/new.html", {"org": request.org})


def _import_in_background(project_id):
    """Run the clone/detect/deploy work on an already-created project shell
    (from ``begin_import``), advancing the live import stepper. Prefer the
    orchestration path (durable + a WorkflowRun); fall back to the direct
    services path on any error."""
    from . import services as project_services
    from .models import Project

    project = Project.objects.filter(pk=project_id).first()
    if project is None:
        return

    try:
        from orchestration import service as orch

        orch.import_project(
            project.name, project.repo_url, description=project.description,
            org=project.org, project=project,
        )
        return
    except Exception:  # noqa: BLE001 — fall through to the direct path
        pass

    project = project_services.import_project(
        project.name, project.repo_url, project=project, org=project.org
    )
    if project.status != Project.Status.READY:
        return
    for env in sorted(project.environments.all(), key=lambda e: e.name != "staging"):
        try:
            project_services.deploy_environment(env)
        except Exception:  # noqa: BLE001
            pass


@org_required
def project_detail(request, slug):
    from deploys.models import Deployment

    deploy_qs = Deployment.objects.exclude(
        status=Deployment.Status.STOPPED
    ).order_by("-created_at")
    project = get_object_or_404(
        visible(Project, request).prefetch_related(
            Prefetch("environments__deployments", queryset=deploy_qs),
            "environments",
            "incidents",
        ),
        slug=slug,
    )
    environments = list(project.environments.all())

    # Shared verdict helper drives the header per-env rollup + open-incident count.
    health = health_verdict(project)

    deployments = (
        Deployment.objects.filter(environment__project=project)
        .select_related("environment")
        .order_by("-created_at")[:25]
    )

    agent_runs = project.agent_runs.all()[:8]
    pull_requests = project.pull_requests.all()[:8]
    incidents = project.incidents.all()[:8]

    import_steps = list(project.import_steps.all())

    return render(
        request,
        "projects/detail.html",
        {
            "project": project,
            "environments": environments,
            "deployments": deployments,
            "agent_runs": agent_runs,
            "pull_requests": pull_requests,
            "incidents": incidents,
            "health": health,
            "import_steps": import_steps,
            "import_active": _import_in_progress(import_steps),
        },
    )


def _import_in_progress(steps):
    """True while any import step is still pending/running (drives HTMX poll)."""
    from .models import ImportStep

    active = {ImportStep.State.PENDING, ImportStep.State.RUNNING}
    return any(s.state in active for s in steps)


@org_required
def import_steps_fragment(request, slug):
    """HTMX-polled fragment: the live import-progress stepper for a project.

    Org-scoped (404 cross-tenant). Returns just the stepper markup so the detail
    page can poll it (~1.5s) and animate pending -> running -> done/failed. When
    no steps are in flight it stops self-polling (the wrapper drops hx-trigger)."""
    project = get_object_or_404(
        visible(Project, request), slug=slug
    )
    steps = list(project.import_steps.all())
    active = _import_in_progress(steps)
    response = render(
        request,
        "projects/_import_steps.html",
        {
            "project": project,
            "import_steps": steps,
            "import_active": active,
        },
    )
    # The page only polls this endpoint WHILE the import is active, so the first
    # poll that comes back settled is exactly the active->done transition. Tell
    # HTMX to do one full-page reload so the freshly-created environments,
    # deployments, and status badge appear without the user hitting refresh.
    if not active:
        response["HX-Refresh"] = "true"
    return response


@org_required
def project_deploy(request, slug, env_pk):
    """POST: trigger a deploy of one environment in the background."""
    project = get_object_or_404(visible(Project, request), slug=slug)
    env = get_object_or_404(project.environments, pk=env_pk)

    from orchestration import service as orch

    def _go():
        try:
            orch.deploy(env.pk)
            return
        except NotImplementedError:
            pass
        except Exception:  # noqa: BLE001
            pass
        from . import services as project_services

        try:
            project_services.deploy_environment(env)
        except Exception:  # noqa: BLE001
            pass

    threading.Thread(target=_go, daemon=True).start()
    messages.success(request, f"Deploying {project.name} / {env.name}…")
    return redirect(project.get_absolute_url())


@org_required
def project_delete(request, slug):
    """Delete a project: stop its deployments (process + compose), then remove it
    (cascades envs/deployments/domains/incidents/agent runs). Demo-friendly reset.
    """
    project = get_object_or_404(visible(Project, request), slug=slug)
    if request.method != "POST":
        return redirect(project.get_absolute_url())

    import subprocess as _sp

    from deploys import services as deploy_services

    for env in project.environments.all():
        for dep in env.deployments.all():
            try:
                deploy_services.stop(dep)
            except Exception:  # noqa: BLE001
                pass
        # Best-effort compose teardown by project name (no file needed).
        try:
            from deploys.compose.runtime import compose_project_name

            pname = compose_project_name(project.slug, env.name)
            _sp.run(["docker", "compose", "-p", pname, "down", "-v"],
                    stdout=_sp.PIPE, stderr=_sp.STDOUT, timeout=60)
        except Exception:  # noqa: BLE001
            pass

    name = project.name
    project.delete()
    messages.success(request, f"Deleted project “{name}”.")
    return redirect("projects:list")
