import json
from django.db import transaction
from django.http import JsonResponse, HttpResponseBadRequest
from django.shortcuts import render, get_object_or_404
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse

from .models import KanbanItem, Project, Task
from main.models import Task as MainTask


def _status_labels():
    return dict(KanbanItem.STATUS_CHOICES)


def _title_for(item: KanbanItem) -> str:
    t = item.task
    return getattr(t, "title", None) or getattr(t, "name", None) or str(t)


# ---------------- Boards ----------------
@login_required
def kanban_table(request):
    boards = KanbanBoard.objects.all().only("id", "name")
    return render(request, "kanban/kanban_table.html", {"boards": boards})

@login_required
def kanban_view(request):
    columns_ctx = []
    for status, label in KanbanItem.STATUS_CHOICES:
        items = KanbanItem.objects.filter(status=status)

        for it in items:
            if hasattr(it.task, "title"):  
                it.title = it.task.title
            elif hasattr(it.task, "name"):  
                it.title = it.task.name
            else:
                it.title = str(it.task)

            it.edit_url = reverse("kanban:kanbanEdit", args=["item", it.id])
            it.delete_url = reverse("kanban:kanbanDelete", args=["item", it.id])

        columns_ctx.append({
            "status": status,
            "label": label,
            "items": items
        })

    return render(request, "kanban/kanban_view.html", {
        "columns_ctx": columns_ctx
    })



# ---------------- Generic Add ----------------
# ---------------- Generic Add ----------------
@require_POST
@login_required
def kanban_add(request, obj_type, parent_id=None):
    title = (request.POST.get("title") or "").strip()
    description = (request.POST.get("description") or "").strip()
    status = request.POST.get("status", "active")

    if not title:
        return JsonResponse({"ok": False, "error": "Title required"})

    # --- Item (no board now) ---
    if obj_type == "item":
        task = MainTask.objects.create(user=request.user, title=title, description=description)
        task_ct = ContentType.objects.get_for_model(MainTask)
        item = KanbanItem.objects.create(
            task_content_type=task_ct, task_object_id=task.pk,
            status=status, order=0
        )
        return JsonResponse({
            "ok": True,
            "id": item.id,
            "title": task.title,
            "edit_url": reverse("kanban:kanbanEdit", args=["item", item.id]),
            "delete_url": reverse("kanban:kanbanDelete", args=["item", item.id]),
        })

    # --- Project task ---
    elif obj_type == "task":
        project = get_object_or_404(Project, pk=parent_id)
        task = Task.objects.create(project=project, title=title, description=description, status=status)
        return JsonResponse({
            "ok": True,
            "id": task.id,
            "title": task.title,
            "edit_url": reverse("kanban:kanbanEditWithParent", args=["task", project.id, task.id]),
            "delete_url": reverse("kanban:kanbanDeleteWithParent", args=["task", project.id, task.id]),
        })

    # --- Project ---
    elif obj_type == "project":
        project = Project.objects.create(name=title, description=description, status=status)
        return JsonResponse({
            "ok": True,
            "id": project.id,
            "name": project.name,
            "edit_url": reverse("kanban:kanbanEdit", args=["project", project.id]),
            "delete_url": reverse("kanban:kanbanDelete", args=["project", project.id]),
        })

    return HttpResponseBadRequest("Invalid type")


@require_POST
@login_required
def kanban_edit(request, obj_type, obj_id, parent_id=None):
    title = (request.POST.get("title") or "").strip()
    description = (request.POST.get("description") or "").strip()
    status = request.POST.get("status")

    if not title:
        return JsonResponse({"ok": False, "error": "Title required"})

    # --- Board item (MainTask) ---
    if obj_type == "item":
        item = get_object_or_404(KanbanItem, pk=obj_id)
        task = get_object_or_404(MainTask, pk=item.task_object_id, user=request.user)
        task.title, task.description = title, description
        task.save(update_fields=["title", "description"])
        return JsonResponse({"ok": True, "id": item.id, "title": task.title})

    # --- Project task ---
    elif obj_type == "task":
        project = get_object_or_404(Project, pk=parent_id)
        task = get_object_or_404(Task, pk=obj_id, project=project)
        task.title, task.description = title, description
        if status:
            task.status = status
        task.save(update_fields=["title", "description", "status"])
        return JsonResponse({"ok": True, "id": task.id, "title": task.title, "status": task.status})

    # --- Project itself ---
    elif obj_type == "project":
        project = get_object_or_404(Project, pk=obj_id)
        project.name, project.description = title, description
        if status:
            project.status = status
        project.save(update_fields=["name", "description", "status"])
        return JsonResponse({"ok": True, "id": project.id, "name": project.name, "status": project.status})

    return HttpResponseBadRequest("Invalid type")


# ---------------- Generic Delete ----------------
@require_POST
@login_required
def kanban_delete(request, obj_type, obj_id, parent_id=None):
    # --- Kanban task item (MainTask) ---
    if obj_type == "item":
        item = get_object_or_404(KanbanItem, pk=obj_id)
        task = get_object_or_404(MainTask, pk=item.task_object_id, user=request.user)
        item.delete()
        if not KanbanItem.objects.filter(task_object_id=task.id).exists():
            task.delete()
        return JsonResponse({"ok": True, "id": obj_id, "message": "Deleted"})

    # --- Project task ---
    elif obj_type == "task":
        project = get_object_or_404(Project, pk=parent_id)
        task = get_object_or_404(Task, pk=obj_id, project=project)
        task.delete()
        return JsonResponse({"ok": True, "id": obj_id, "message": "Deleted"})

    # --- Project itself ---
    elif obj_type == "project":
        project = get_object_or_404(Project, pk=obj_id)
        project.delete()
        return JsonResponse({"ok": True, "id": obj_id, "message": "Deleted"})

    return HttpResponseBadRequest("Invalid type")



# ---------------- Projects ----------------
@login_required
def projects_kanban(request):
    columns_ctx = []
    for status, label in Project.STATUS_CHOICES:
        items = Project.objects.filter(status=status)
        for p in items:
            p.edit_url = reverse("kanban:kanbanEdit", args=["project", p.id])
            p.delete_url = reverse("kanban:kanbanDelete", args=["project", p.id])
        columns_ctx.append({"label": label, "status": status, "items": items})

    return render(request, "kanban/projects/projects_kanban.html", {
        "columns_ctx": columns_ctx
    })


@login_required
def project_tasks_kanban(request, pk):
    project = get_object_or_404(Project, pk=pk)
    columns_ctx = [
        {"label": "Not Started", "status": "not_started", "items": project.tasks.filter(status="not_started")},
        {"label": "In Progress", "status": "in_progress", "items": project.tasks.filter(status="in_progress")},
        {"label": "Hold", "status": "on_hold", "items": project.tasks.filter(status="on_hold")},
        {"label": "Review", "status": "review", "items": project.tasks.filter(status="review")},
        {"label": "Complete", "status": "done", "items": project.tasks.filter(status="done")},
    ]
    return render(request, "kanban/projects/project_tasks_kanban.html", {
        "project": project,
        "columns_ctx": columns_ctx
    })


# ---------------- Update (drag/drop) ----------------
# ---------------- Generic Update ----------------
@require_POST
@login_required
# ---------------- Update (drag/drop) ----------------
@require_POST
@login_required
def kanban_update(request, obj_type, parent_id=None):
    try:
        data = json.loads(request.body.decode("utf-8")) if request.body else request.POST
    except Exception:
        return HttpResponseBadRequest("Invalid JSON")

    new_status = data.get("status")
    ids = data.get("ids") if isinstance(data.get("ids"), list) else []

    if not ids or new_status is None:
        return HttpResponseBadRequest("Invalid payload")

    # --- Items (no board now) ---
    if obj_type == "item":
        with transaction.atomic():
            for idx, pk in enumerate(ids):
                KanbanItem.objects.filter(id=pk).update(
                    status=new_status, order=idx
                )

    # --- Project tasks ---
    elif obj_type == "task":
        project = get_object_or_404(Project, pk=parent_id)
        with transaction.atomic():
            for pk in ids:
                Task.objects.filter(project=project, id=pk).update(status=new_status)

    # --- Projects ---
    elif obj_type == "project":
        with transaction.atomic():
            for pk in ids:
                Project.objects.filter(id=pk).update(status=new_status)

    else:
        return HttpResponseBadRequest("Invalid type")

    return JsonResponse({"ok": True, "status": new_status, "ids": ids})
