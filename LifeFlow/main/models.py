from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone

class Task(models.Model):
    PRIORITY_CHOICES = [
        ('high', 'High'),
        ('medium', 'Medium'),
        ('low', 'Low'),
    ]
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('completed', 'Completed'),
        ('archived', 'Archived'),
    ]
    
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    due_date = models.DateTimeField(null=True, blank=True)
    reminder_time = models.DateTimeField(null=True, blank=True)
    priority = models.CharField(max_length=6, choices=PRIORITY_CHOICES, default='medium')
    status = models.CharField(max_length=9, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE)  

    def __str__(self):
        return self.title

    def is_due_today(self):
        """Check if the task is due today"""
        return self.due_date and self.due_date.date() == timezone.now().date()

    def is_overdue(self):
        """Check if the task is overdue"""
        return self.due_date and self.due_date < timezone.now()