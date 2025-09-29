from django.db import models
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType

class KanbanBoard(models.Model):
    name = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.name

class KanbanItem(models.Model):
    task_content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    task_object_id = models.PositiveIntegerField()
    task = GenericForeignKey('task_content_type', 'task_object_id')

    board = models.ForeignKey(KanbanBoard, on_delete=models.CASCADE, related_name="items")

    NOT_STARTED, IN_PROGRESS, ON_HOLD, REVIEW, DONE = 0, 1, 2, 3, 4
    STATUS_CHOICES = (
        (NOT_STARTED, "Not Started"),
        (IN_PROGRESS, "In Progress"),
        (ON_HOLD, "Hold"),
        (REVIEW, "Review"),
        (DONE, "Complete"),
    )
    status = models.PositiveSmallIntegerField(choices=STATUS_CHOICES, default=NOT_STARTED)
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = (('board', 'task_content_type', 'task_object_id'),)
        ordering = ["status", "order", "id"]
        indexes = [
            models.Index(fields=("board", "status", "order")),
            models.Index(fields=("task_content_type", "task_object_id")),
        ]

    def __str__(self):
        return f"{self.task} @ {self.board}"

class Project(models.Model):
    STATUS_CHOICES = [
        ("active", "Active"),
        ("onhold", "On Hold"),
        ("completed", "Completed"),
    ]
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active")

    def __str__(self):
        return self.name


class Task(models.Model):
    STATUS_CHOICES = [
        ("todo", "To Do"),
        ("inprogress", "In Progress"),
        ("done", "Done"),
    ]
    project = models.ForeignKey(Project, related_name="tasks", on_delete=models.CASCADE)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="todo")

    def __str__(self):
        return f"{self.title} ({self.project.name})"
