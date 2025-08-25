from django import forms
from .models import Task
from .models import HealthMetric


class TaskForm(forms.ModelForm):
    class Meta:
        model = Task
        fields = ['title', 'description', 'due_date', 'reminder_time', 'priority']

class HealthMetricForm(forms.ModelForm):
    class Meta:
        model = HealthMetric
        fields = ['water_intake', 'steps', 'calories']
        widgets = {
            'water_intake': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.1', 'min': '0'}),
            'steps': forms.NumberInput(attrs={'class': 'form-control', 'min': '0'}),
            'calories': forms.NumberInput(attrs={'class': 'form-control', 'min': '0'}),
        }