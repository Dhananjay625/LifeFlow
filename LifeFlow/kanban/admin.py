from django.contrib import admin
from .models import KanbanItem, Project, Task


@admin.register(KanbanItem)
class KanbanItemAdmin(admin.ModelAdmin):
    list_display = ("id", "task_content_type", "task_object_id", "status", "order", "created_at")
    list_filter = ("status", "task_content_type")
    search_fields = ("task_object_id",)


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "status")
    list_filter = ("status",)
    search_fields = ("name",)


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "project", "status")
    list_filter = ("status", "project")
    search_fields = ("title", "description")
