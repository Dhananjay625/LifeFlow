from django.db import models
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType


class KanbanItem(models.Model):
    task_content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    task_object_id = models.PositiveIntegerField()
    task = GenericForeignKey("task_content_type", "task_object_id")

    NOT_STARTED, IN_PROGRESS, ON_HOLD, REVIEW, DONE = 0, 1, 2, 3, 4
    STATUS_CHOICES = (
        (NOT_STARTED, "Not Started"),
        (IN_PROGRESS, "In Progress"),
        (ON_HOLD, "Hold"),
        (REVIEW, "Review"),
        (DONE, "Complete"),
    )
    status = models.PositiveSmallIntegerField(
        choices=STATUS_CHOICES, default=NOT_STARTED
    )
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["status", "order", "id"]
        indexes = [
            models.Index(fields=("status", "order")),
            models.Index(fields=("task_content_type", "task_object_id")),
        ]

    def __str__(self):
        return str(self.task)


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
        ("not_started", "Not Started"),
        ("in_progress", "In Progress"),
        ("on_hold", "Hold"),
        ("review", "Review"),
        ("done", "Complete"),
    ]
    project = models.ForeignKey(Project, related_name="tasks", on_delete=models.CASCADE)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="not_started")

    def __str__(self):
        return f"{self.title} ({self.project.name})"
