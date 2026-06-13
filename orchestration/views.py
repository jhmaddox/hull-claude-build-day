from django.shortcuts import get_object_or_404, render

from .models import WorkflowRun


def workflow_list(request):
    runs = WorkflowRun.objects.select_related("project").all()[:100]
    ctx = {
        "runs": runs,
        "running_count": WorkflowRun.objects.filter(
            status=WorkflowRun.Status.RUNNING
        ).count(),
    }
    return render(request, "orchestration/workflow_list.html", ctx)


def workflow_table(request):
    """HTMX-polled fragment of the workflow run table."""
    runs = WorkflowRun.objects.select_related("project").all()[:100]
    return render(request, "orchestration/_workflow_table.html", {"runs": runs})


def workflow_detail(request, pk):
    run = get_object_or_404(WorkflowRun.objects.select_related("project"), pk=pk)
    return render(request, "orchestration/workflow_detail.html", {"run": run})
