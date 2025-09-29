import json
from django.db import transaction
from django.http import JsonResponse, HttpResponseBadRequest
from django.shortcuts import render, get_object_or_404, redirect
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType

from .models import KanbanBoard, KanbanItem, Project, Task 
from main.models import Task as MainTask  


def _status_labels():
    return dict(KanbanItem.STATUS_CHOICES)


def _title_for(item: KanbanItem) -> str:
    t = item.task
    return getattr(t, "title", None) or getattr(t, "name", None) or str(t)


@login_required
def kanban_table(request):
    boards = KanbanBoard.objects.all().only("id", "name")
    return render(request, "kanban/kanban_table.html", {"boards": boards})


@login_required
def kanban_view(request, board_id: int):
    board = get_object_or_404(KanbanBoard, pk=board_id)

    task_ct = ContentType.objects.get_for_model(MainTask)
    user_task_ids = MainTask.objects.filter(user=request.user).values_list("id", flat=True)

    items_qs = (
        board.items
             .filter(task_content_type=task_ct, task_object_id__in=user_task_ids)
             .select_related("task_content_type")
             .order_by("status", "order", "id")
    )

    buckets = {s: [] for s, _ in KanbanItem.STATUS_CHOICES}
    for it in items_qs:
        buckets[it.status].append({"id": it.id, "title": _title_for(it)})

    status_labels = _status_labels()
    columns_ctx = [
        {"status": s, "label": status_labels[s], "items": buckets.get(s, [])}
        for s, _ in KanbanItem.STATUS_CHOICES
    ]

    return render(request, "kanban/kanban_view.html", {
        "board": board,
        "columns_ctx": columns_ctx,
        "task_ct_id": task_ct.id,
    })


@require_POST
@login_required
def kanban_add_item(request, board_id: int):
    board = get_object_or_404(KanbanBoard, pk=board_id)

    title = (request.POST.get("title") or "").strip()
    description = (request.POST.get("description") or "").strip()
    status = int(request.POST.get("status", KanbanItem.NOT_STARTED))
    if not title:
        return redirect("kanban:kanbanView", board_id=board.id)

    task = MainTask.objects.create(user=request.user, title=title, description=description)

    task_ct = ContentType.objects.get_for_model(MainTask)
    KanbanItem.objects.create(
        board=board,
        task_content_type=task_ct,
        task_object_id=task.pk,
        status=status,
        order=0,
    )
    return redirect("kanban:kanbanView", board_id=board.id)


@require_POST
@login_required
def kanban_update(request, board_id: int):
    board = get_object_or_404(KanbanBoard, pk=board_id)

    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return HttpResponseBadRequest("Invalid JSON")

    moves = data.get("moves", [])
    if not isinstance(moves, list):
        return HttpResponseBadRequest("Invalid payload")

    try:
        ids = [int(m["item_id"]) for m in moves]
    except Exception:
        return HttpResponseBadRequest("Bad move values")

    items = {i.id: i for i in KanbanItem.objects.filter(board=board, id__in=ids)}
    valid_statuses = {s for s, _ in KanbanItem.STATUS_CHOICES}

    for m in moves:
        try:
            iid = int(m["item_id"]); status = int(m["status"]); order = int(m["order"])
        except Exception:
            return HttpResponseBadRequest("Bad move values")
        if status not in valid_statuses or iid not in items:
            return HttpResponseBadRequest("Bad status or item_id")
        obj = items[iid]
        obj.status = status
        obj.order = order

    with transaction.atomic():
        KanbanItem.objects.bulk_update(items.values(), ["status", "order"])

    return JsonResponse({"ok": True})


@require_POST
@login_required
def kanban_edit_item(request, board_id: int, item_id: int):
    board = get_object_or_404(KanbanBoard, pk=board_id)
    item = get_object_or_404(KanbanItem, pk=item_id, board=board)

    task_ct = ContentType.objects.get_for_model(MainTask)
    if item.task_content_type_id != task_ct.id:
        return HttpResponseBadRequest("Unsupported item type")

    task = get_object_or_404(MainTask, pk=item.task_object_id)
    if getattr(task, "user_id", None) != request.user.id:
        return HttpResponseBadRequest("Not allowed")

    title = (request.POST.get("title") or "").strip()
    description = (request.POST.get("description") or "").strip()
    if not title:
        return HttpResponseBadRequest("Title is required")

    if hasattr(task, "title"):
        task.title = title
    elif hasattr(task, "name"):
        task.name = title

    if hasattr(task, "description"):
        task.description = description

    task.save(update_fields=[fld for fld in ["title", "name", "description"]
                             if hasattr(task, fld)])

    return JsonResponse({"ok": True, "title": title})


@require_POST
@login_required
def kanban_delete_item(request, board_id: int, item_id: int):
    board = get_object_or_404(KanbanBoard, pk=board_id)
    item = get_object_or_404(KanbanItem, pk=item_id, board=board)

    task_ct = ContentType.objects.get_for_model(MainTask)
    if item.task_content_type_id != task_ct.id:
        return HttpResponseBadRequest("Unsupported item type")

    task = get_object_or_404(MainTask, pk=item.task_object_id)
    if getattr(task, "user_id", None) != request.user.id:
        return HttpResponseBadRequest("Not allowed")

    item.delete()

    still_used = KanbanItem.objects.filter(
        task_content_type=task_ct, task_object_id=task.id
    ).exists()
    if not still_used:
        task.delete()

    return JsonResponse({"ok": True})

@login_required
def projects_kanban(request):
    """Top-level Kanban showing Projects by status"""
    columns_ctx = [
        {"label": "Active", "status": "active", "items": Project.objects.filter(status="active")},
        {"label": "On Hold", "status": "onhold", "items": Project.objects.filter(status="onhold")},
        {"label": "Completed", "status": "completed", "items": Project.objects.filter(status="completed")},
    ]
    return render(request, "kanban/projects/projects_kanban.html", {"columns_ctx": columns_ctx})


@login_required
def project_tasks_kanban(request, pk):
    """Kanban of tasks for a single Project"""
    project = get_object_or_404(Project, pk=pk)
    columns_ctx = [
        {"label": "To Do", "status": "todo", "items": project.tasks.filter(status="todo")},
        {"label": "In Progress", "status": "inprogress", "items": project.tasks.filter(status="inprogress")},
        {"label": "Done", "status": "done", "items": project.tasks.filter(status="done")},
    ]
    return render(request, "kanban/projects/project_tasks_kanban.html", {
        "project": project,
        "columns_ctx": columns_ctx,
    })

@require_POST
@login_required
def project_add(request):
    name = request.POST.get("name", "").strip()
    description = request.POST.get("description", "").strip()
    status = request.POST.get("status", "active")

    if not name:
        return JsonResponse({"ok": False, "error": "Project name required"})

    Project.objects.create(name=name, description=description, status=status)
    return redirect("kanban:projectsKanban")


@require_POST
@login_required
def project_edit(request, pk):
    project = get_object_or_404(Project, pk=pk)

    name = request.POST.get("name", "").strip()
    description = request.POST.get("description", "").strip()
    if not name:
        return JsonResponse({"ok": False, "error": "Project name required"})

    project.name = name
    project.description = description
    project.save(update_fields=["name", "description"])
    return JsonResponse({"ok": True, "title": name})


@require_POST
@login_required
def project_delete(request, pk):
    project = get_object_or_404(Project, pk=pk)
    project.delete()
    return JsonResponse({"ok": True})

@require_POST
@login_required
def task_add(request, pk):
    """Add a new task to a specific Project"""
    project = get_object_or_404(Project, pk=pk)

    title = (request.POST.get("title") or "").strip()
    description = (request.POST.get("description") or "").strip()
    status = request.POST.get("status", "todo")

    if not title:
        return JsonResponse({"ok": False, "error": "Task title required"})

    # Assuming your Task model is linked to Project with FK (project=...)
    task = Task.objects.create(
        project=project,
        title=title,
        description=description,
        status=status,
    )
    return redirect("kanban:projectTasksKanban", pk=project.pk)


@require_POST
@login_required
def task_edit(request, pk, task_id):
    """Edit a task inside a specific Project"""
    project = get_object_or_404(Project, pk=pk)
    task = get_object_or_404(Task, pk=task_id, project=project)

    title = (request.POST.get("title") or "").strip()
    description = (request.POST.get("description") or "").strip()
    status = request.POST.get("status", task.status)

    if not title:
        return JsonResponse({"ok": False, "error": "Title required"})

    task.title = title
    task.description = description
    task.status = status
    task.save(update_fields=["title", "description", "status"])

    return JsonResponse({"ok": True, "title": title})


@require_POST
@login_required
def task_delete(request, pk, task_id):
    """Delete a task from a specific Project"""
    project = get_object_or_404(Project, pk=pk)
    task = get_object_or_404(Task, pk=task_id, project=project)

    task.delete()
    return JsonResponse({"ok": True})

@require_POST
@login_required
def projects_update(request):
    """
    Update project statuses and order (drag & drop).
    """
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return HttpResponseBadRequest("Invalid JSON")

    moves = data.get("moves", [])
    if not isinstance(moves, list):
        return HttpResponseBadRequest("Invalid payload")

    for m in moves:
        try:
            pid = int(m["item_id"])
            status = m["status"]
        except Exception:
            return HttpResponseBadRequest("Bad move values")

        Project.objects.filter(id=pid).update(status=status)

    return JsonResponse({"ok": True})

@require_POST
@login_required
def task_update_status(request, pk):
    """
    Update a task's status inside a project (used for drag & drop).
    """
    project = get_object_or_404(Project, pk=pk)

    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return HttpResponseBadRequest("Invalid JSON")

    task_id = data.get("id")
    new_status = data.get("status")

    if not task_id or not new_status:
        return HttpResponseBadRequest("Missing task id or status")

    try:
        task = Task.objects.get(id=task_id, project=project)
        task.status = new_status
        task.save(update_fields=["status"])
        return JsonResponse({"ok": True, "id": task.id, "status": task.status})
    except Task.DoesNotExist:
        return JsonResponse({"ok": False, "error": "Task not found"}, status=404)
