from django.urls import path
from . import views

app_name = "kanban"

urlpatterns = [
    path("", views.kanban_view, name="kanban"),

    path("add/<str:obj_type>/", views.kanban_add, name="kanbanAdd"),
    path("add/<str:obj_type>/<int:parent_id>/", views.kanban_add, name="kanbanAddWithParent"),

    path("edit/<str:obj_type>/<int:obj_id>/", views.kanban_edit, name="kanbanEdit"),
    path("edit/<str:obj_type>/<int:parent_id>/<int:obj_id>/", views.kanban_edit, name="kanbanEditWithParent"),

    path("delete/<str:obj_type>/<int:obj_id>/", views.kanban_delete, name="kanbanDelete"),
    path("delete/<str:obj_type>/<int:parent_id>/<int:obj_id>/", views.kanban_delete, name="kanbanDeleteWithParent"),

    path("projects/", views.projects_kanban, name="projectsKanban"),
    path("projects/<int:pk>/tasks/", views.project_tasks_kanban, name="projectTasksKanban"),

    path("update/<str:obj_type>/", views.kanban_update, name="kanbanUpdate"),
    path("update/<str:obj_type>/<int:parent_id>/", views.kanban_update, name="kanbanUpdateWithParent"),
]
