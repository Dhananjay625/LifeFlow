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
    
class Bill(models.Model):
    name = models.CharField(max_length=100)
    cost = models.DecimalField(max_digits=10, decimal_places=2)
    renewal_date = models.DateField(null=True, blank=True)
    contract_type = models.CharField(max_length=50, default='NA')

    STATUS_CHOICES = [
        ('active', 'Active'),
        ('suspended', 'Suspended'),
        ('canceled', 'Canceled'),
    ]
    status = models.CharField(max_length=10, choices=STATUS_CHOICES)

    def __str__(self):
        return self.name
    
class sub(models.Model):
    name = models.CharField(max_length=100)
    cost = models.DecimalField(max_digits=10, decimal_places=2)
    renewal_date = models.DateField(null=True, blank=True)
    contract_type = models.CharField(max_length=50, default='NA')

    STATUS_CHOICES = [
        ('active', 'Active'),
        ('suspended', 'Suspended'),
        ('canceled', 'Canceled'),
    ]
    status = models.CharField(max_length=10, choices=STATUS_CHOICES)

    def __str__(self):
        return self.name
    
class Document(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    doc_name = models.CharField(max_length=100)
    file = models.FileField(upload_to='documents/')
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.doc_name
    
class HealthMetric(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="health_metrics")
    water_intake = models.FloatField(help_text="Litres of water intake")
    steps = models.PositiveIntegerField(help_text="Number of steps walked")
    calories = models.PositiveIntegerField(help_text="Calories consumed")
    date = models.DateField(auto_now_add=True)

    class Meta:
        ordering = ['-date']   # latest first
        unique_together = ('user', 'date')  # prevent duplicates for same day

    def __str__(self):
        return f"{self.user.username} - {self.date}"
    
class Reminder(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="reminders")
    text = models.CharField(max_length=255)
    date = models.DateField()

    def __str__(self):
        return f"{self.text} - {self.date}"