from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta
import uuid


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

class CalendarEvent(models.Model):
    TYPE_CHOICES = [
        ('task', 'Task'),
        ('bill', 'Bill'),
        ('subscription', 'Subscription'),
        ('other', 'Other'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='calendar_events')
    title = models.CharField(max_length=255)
    start = models.DateTimeField(null=True, blank=True)
    end = models.DateTimeField(null=True, blank=True)
    all_day = models.BooleanField(default=False)

    rrule = models.JSONField(null=True, blank=True)

    type = models.CharField(max_length=20, choices=TYPE_CHOICES, default='other')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['user', 'start']),
        ]
        ordering = ['start', 'created_at']

    def __str__(self):
        return f"{self.title} ({self.user})"
    
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
    
class UserHealthProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="health_profile")
    age = models.PositiveIntegerField(null=True, blank=True)
    height_cm = models.FloatField(null=True, blank=True)
    weight_kg = models.FloatField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def bmi(self):
        if not self.height_cm or not self.weight_kg or self.height_cm <= 0:
            return None
        h_m = self.height_cm / 100.0
        return round(self.weight_kg / (h_m * h_m), 1)
    
    def bmi_category(self):
        b = self.bmi()
        if b is None:
            return "N/A"
        if b < 18.5:
            return "Underweight"
        if b < 25:
            return "Normal weight"
        if b < 30:
            return "Overweight"
        return "Obese"
    
    def __str__(self):
        return f"{self.user.username} Profile"
    
    # Family domain
# ──────────────────────────────────────────────────────────────────────────────

class Family(models.Model):
    name = models.CharField(max_length=100)
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="owned_families")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class FamilyMembership(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="family_memberships")
    family = models.ForeignKey(Family, on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField(max_length=20, default="member")  # e.g., "parent" / "child"
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "family")

    def __str__(self):
        return f"{self.user} in {self.family} ({self.role})"


def _default_expiry():
    return timezone.now() + timedelta(days=7)


class FamilyInvite(models.Model):
    family = models.ForeignKey(Family, on_delete=models.CASCADE, related_name="invites")
    inviter = models.ForeignKey(User, on_delete=models.CASCADE, related_name="sent_family_invites")
    email = models.EmailField()
    role = models.CharField(max_length=20, default="member")
    code = models.CharField(max_length=36, default=uuid.uuid4, unique=True)
    expires_at = models.DateTimeField(default=_default_expiry)

    accepted_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="accepted_family_invites"
    )
    accepted_at = models.DateTimeField(null=True, blank=True)
    used = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def is_active(self):
        return (self.accepted_at is None) and (self.expires_at > timezone.now())

    def __str__(self):
        return f"Invite {self.email} to {self.family} (active={self.is_active})"

