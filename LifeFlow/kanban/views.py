import json
from django.db import transaction
from django.http import JsonResponse, HttpResponseBadRequest
from django.shortcuts import render, get_object_or_404, redirect
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType

from .models import KanbanBoard, KanbanItem
from main.models import Task  # <-- your Task model


def _status_labels():
    return dict(KanbanItem.STATUS_CHOICES)


def _title_for(item: KanbanItem) -> str:
    t = item.task
    # Prefer title, then name, then __str__
    return getattr(t, "title", None) or getattr(t, "name", None) or str(t)


@login_required
def kanban_table(request):
    boards = KanbanBoard.objects.all().only("id", "name")
    return render(request, "kanban/kanban_table.html", {"boards": boards})


@login_required
def kanban_view(request, board_id: int):
    board = get_object_or_404(KanbanBoard, pk=board_id)

    # Only this user's tasks
    task_ct = ContentType.objects.get_for_model(Task)
    user_task_ids = Task.objects.filter(user=request.user).values_list("id", flat=True)

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

    # Create a user-owned Task
    task = Task.objects.create(user=request.user, title=title, description=description)

    task_ct = ContentType.objects.get_for_model(Task)
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

    # Bulk update to avoid SQLite locks
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

    task_ct = ContentType.objects.get_for_model(Task)
    if item.task_content_type_id != task_ct.id:
        return HttpResponseBadRequest("Unsupported item type")

    task = get_object_or_404(Task, pk=item.task_object_id)
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

    task_ct = ContentType.objects.get_for_model(Task)
    if item.task_content_type_id != task_ct.id:
        return HttpResponseBadRequest("Unsupported item type")

    task = get_object_or_404(Task, pk=item.task_object_id)
    if getattr(task, "user_id", None) != request.user.id:
        return HttpResponseBadRequest("Not allowed")

    # Remove the KanbanItem
    item.delete()

    still_used = KanbanItem.objects.filter(
        task_content_type=task_ct, task_object_id=task.id
    ).exists()
    if not still_used:
        task.delete()

    return JsonResponse({"ok": True})