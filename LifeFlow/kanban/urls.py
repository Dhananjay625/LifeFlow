from django.urls import path
from . import views

app_name = "kanban"

urlpatterns = [
    path("", views.kanban_table, name="kanbanTable"),
    path("<int:board_id>/", views.kanban_view, name="kanbanView"),
    path("<int:board_id>/update/", views.kanban_update, name="kanbanUpdate"),
    path("<int:board_id>/add/", views.kanban_add_item, name="kanbanAddItem"),
    path("<int:board_id>/item/<int:item_id>/edit/", views.kanban_edit_item, name="kanbanEditItem"),
    path("<int:board_id>/item/<int:item_id>/delete/", views.kanban_delete_item, name="kanbanDeleteItem"),
]
