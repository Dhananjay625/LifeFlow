from django import forms
from .models import Task
from .models import HealthMetric, Appointment

class TaskForm(forms.ModelForm):
    class Meta:
        model = Task
        fields = ['title', 'description', 'due_date', 'reminder_time', 'priority']

class HealthMetricForm(forms.ModelForm):
    class Meta:
        model = HealthMetric
        fields = ['weight', 'body_fat', 'water', 'steps', 'calories']

class AppointmentForm(forms.ModelForm):
    class Meta:
        model = Appointment
        fields = ['title', 'date', 'notes']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'})
        }