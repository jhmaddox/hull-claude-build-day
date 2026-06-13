import threading

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from .models import Project


def project_list(request):
    projects = Project.objects.all().prefetch_related("environments")
    return render(request, "projects/list.html", {"projects": projects})


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

        threading.Thread(
            target=_import_in_background,
            args=(name, repo_url, description),
            daemon=True,
        ).start()
        messages.success(request, f"Importing {name}… this runs in the background.")
        return redirect(reverse("projects:list"))

    return render(request, "projects/new.html", {})


def _import_in_background(name, repo_url, description):
    """Prefer orchestration.import_project (which also auto-deploys). If that
    raises NotImplementedError, fall back to projects.services.import_project +
    auto-deploy each environment via deploys.services.deploy."""
    from orchestration import service as orch

    try:
        orch.import_project(name, repo_url, description=description)
        return
    except NotImplementedError:
        pass
    except Exception:  # noqa: BLE001 — fall through to direct path on any error
        pass

    from deploys import services as deploy_services
    from . import services as project_services

    project = project_services.import_project(name, repo_url, description=description)
    if project.status != Project.Status.READY:
        return
    for env in project.environments.all():
        try:
            deploy_services.deploy(env)
        except Exception:  # noqa: BLE001
            pass


def project_detail(request, slug):
    project = get_object_or_404(
        Project.objects.prefetch_related("environments"), slug=slug
    )
    environments = list(project.environments.all())

    from deploys.models import Deployment

    deployments = (
        Deployment.objects.filter(environment__project=project)
        .select_related("environment")
        .order_by("-created_at")[:25]
    )

    agent_runs = project.agent_runs.all()[:8]
    pull_requests = project.pull_requests.all()[:8]
    incidents = project.incidents.all()[:8]

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
        },
    )


def project_deploy(request, slug, env_pk):
    """POST: trigger a deploy of one environment in the background."""
    project = get_object_or_404(Project, slug=slug)
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
        from deploys import services as deploy_services

        try:
            deploy_services.deploy(env)
        except Exception:  # noqa: BLE001
            pass

    threading.Thread(target=_go, daemon=True).start()
    messages.success(request, f"Deploying {project.name} / {env.name}…")
    return redirect(project.get_absolute_url())
