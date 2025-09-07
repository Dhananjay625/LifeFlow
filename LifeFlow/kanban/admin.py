from django.contrib import admin
from .models import KanbanBoard, KanbanItem

@admin.register(KanbanBoard)
class KanbanBoardAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "created_at")
    search_fields = ("name",)

@admin.register(KanbanItem)
class KanbanItemAdmin(admin.ModelAdmin):
    list_display = ("id", "board", "task_content_type", "task_object_id", "status", "order", "created_at")
    list_filter = ("board", "status", "task_content_type")
    search_fields = ("task_object_id",)
