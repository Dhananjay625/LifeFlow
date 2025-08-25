from django import forms
from .models import Task
from .models import HealthMetric, UserHealthProfile, Reminder


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

class HealthProfileForm(forms.ModelForm):
    class Meta:
        model = UserHealthProfile
        fields = ['age', 'height_cm', 'weight_kg']
        labels = {
            'age': 'Age (years)',
            'height_cm': 'Height (cm)',
            'weight_kg': 'Weight (kg)',
        }
        widgets = {
            'age': forms.NumberInput(attrs={'min': '0'}),
            'height_cm': forms.NumberInput(attrs={'step': '0.1', 'min': '0'}),
            'weight_kg': forms.NumberInput(attrs={'step': '0.1', 'min': '0'}),
        }

class ReminderForm(forms.ModelForm):
    class Meta:
        model = Reminder
        fields = ['text', 'date']
        widgets = {
            'text': forms.TextInput(attrs={'class': 'form-control'}),
            'date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        }