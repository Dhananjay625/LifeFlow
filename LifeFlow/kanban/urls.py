from django.urls import path
from . import views

app_name = "kanban"

urlpatterns = [
    # General Kanban Boards
    path("", views.kanban_table, name="kanbanTable"),
    path("<int:board_id>/", views.kanban_view, name="kanbanView"),
    path("<int:board_id>/update/", views.kanban_update, name="kanbanUpdate"),
    path("<int:board_id>/add/", views.kanban_add_item, name="kanbanAddItem"),
    path("<int:board_id>/item/<int:item_id>/edit/", views.kanban_edit_item, name="kanbanEditItem"),
    path("<int:board_id>/item/<int:item_id>/delete/", views.kanban_delete_item, name="kanbanDeleteItem"),

    # Project Kanban
    path("projects/", views.projects_kanban, name="projectsKanban"),
    path("projects/add/", views.project_add, name="projectsAdd"),
    path("projects/<int:pk>/edit/", views.project_edit, name="projectsEdit"),
    path("projects/<int:pk>/delete/", views.project_delete, name="projectsDelete"),
    path("projects/update/", views.projects_update, name="projectsUpdate"),

    # Project Tasks Kanban
    path("projects/<int:pk>/", views.project_tasks_kanban, name="projectTasksKanban"),
    path("projects/<int:pk>/tasks/add/", views.task_add, name="taskAdd"),
    path("projects/<int:pk>/tasks/<int:task_id>/edit/", views.task_edit, name="taskEdit"),
    path("projects/<int:pk>/tasks/<int:task_id>/delete/", views.task_delete, name="taskDelete"),
    path("projects/<int:pk>/tasks/update/", views.task_update_status, name="taskUpdateStatus"),
]
