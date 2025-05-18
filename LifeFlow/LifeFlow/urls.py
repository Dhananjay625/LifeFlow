"""LifeFlow URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path
from main import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', views.LandingPage, name='LandingPage'),  
    path('calender/', views.calender, name='calender'),
    path('Subscription/', views.Subscription, name='Subscription'),
    path('TaskManager/', views.TaskManager, name='TaskManager'),
    path('BillManager/', views.BillManager, name='BillManager'),
    path('register/', views.register, name='register'),
    path('login/', views.login_view, name='login'),
    path('DocumentStorage/', views.DocumentStorage, name='DocumentStorage'),
    path('create/', views.create_task, name='create_task'),
    path('list/', views.task_list, name='task_list'),
    path('complete/<int:task_id>/', views.complete_task, name='complete_task'),
    path('archive/<int:task_id>/', views.archive_task, name='archive_task'),
    path('archive/<int:task_id>/', views.archive_task, name='archive_task'),
    path('HealthManager/', views.HealthManager, name='HealthManager'),
    path('dashboard/', views.dashboard, name='dashboard'),
]
