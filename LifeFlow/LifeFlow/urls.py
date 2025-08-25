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
from django.contrib.auth import views as auth_views
from django.conf import settings
from django.conf.urls.static import static

from main import views


urlpatterns = [
    path('admin/', admin.site.urls),
    path('', views.LandingPage, name='LandingPage'),  
    path('calender/', views.calender, name='calender'),
    path('Subscription/', views.SubscriptionTracker, name='Subscription'),

    path('TaskManager/', views.TaskManager, name='TaskManager'),
    path('BillManager/', views.BillManager, name='BillManager'),
    path('register/', views.register, name='register'),
    path('login/', views.login_view, name='login'),
    path('DocumentStorage/', views.DocumentStorage, name='DocumentStorage'),
    path('confirm-password/', views.confirm_password, name='confirm_password'),
    path('create/', views.create_task, name='create_task'),
    path('list/', views.task_list, name='task_list'),
    path('complete/<int:task_id>/', views.complete_task, name='complete_task'),
    path('archive/<int:task_id>/', views.archive_task, name='archive_task'),
    path('HealthManager/', views.health_manager, name='HealthManager'),
    path('health/search/', views.health_search, name='health_search'),   # NEW
    path('dashboard/', views.dashboard, name='dashboard'),
    path('calendar/events/', views.calendar_events, name='calendar_events'),
    path('add/<str:item_type>/', views.add_item, name='add_item'),
    path('UserProfile/', views.user_profile, name='UserProfile'),
    path('delete-bill/<int:bill_id>/', views.delete_bill, name='delete_bill'),
     path('delete-sub/<int:sub_id>/', views.delete_sub, name='delete_sub'),
    path('delete-document/<int:doc_id>/', views.delete_document, name='delete_document'),
    path('change-password/', auth_views.PasswordChangeView.as_view(
        template_name='UserProfile.html',
        success_url='/UserProfile/'
    ), name='change_password'),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)