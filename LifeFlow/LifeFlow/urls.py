from django.contrib import admin
from django.urls import path, reverse_lazy
from django.contrib.auth import views as auth_views
from django.conf import settings
from django.conf.urls.static import static

from main import views

urlpatterns = [
    # Admin
    path('admin/', admin.site.urls),

    # Landing
    path('', views.LandingPage, name='LandingPage'),


    # Family (front-end page)
    path('FamilyManager/', views.FamilyManager, name='FamilyManager'), 

    # ---------- Google OAuth (single flow) ----------
    path('google/connect/', views.google_connect, name='google_connect'),
    path('google/callback/', views.google_callback, name='google_callback'),
    path('google/oauth2/callback/', views.google_callback, name='google_oauth2_callback'),

    # Profile
    path('profile/', views.user_profile, name='user_profile'),
    path('UserProfile/', views.user_profile, name='UserProfile'), 

    # ---------- Calendar ----------
    path('calendar/', views.calendar_view, name='calendar'),
    path('calendar/events/', views.calendar_events, name='calendar_events'),
    path('calendar/events/create/', views.calendar_events_create, name='calendar_events_create'),
    path('calendar/events/update/', views.calendar_events_update, name='calendar_events_update'),
    path('calendar/events/delete/', views.calendar_events_delete, name='calendar_events_delete'),

    # ---------- App sections ----------
    path('Subscription/', views.SubscriptionTracker, name='Subscription'),
    path('TaskManager/', views.TaskManager, name='TaskManager'),
    path('BillManager/', views.BillManager, name='BillManager'),

    # ---------- Auth (username/password) ----------
    path('register/', views.register, name='register'),
    path('login/', views.login_view, name='login'),
    path(
        'change-password/',
        auth_views.PasswordChangeView.as_view(
            template_name='UserProfile.html',
            success_url=reverse_lazy('UserProfile')  
        ),
        name='change_password',
    ),

    # ---------- Documents ----------
    path('DocumentStorage/', views.DocumentStorage, name='DocumentStorage'),
    path('confirm-password/', views.confirm_password, name='confirm_password'),
    path('delete-document/<int:doc_id>/', views.delete_document, name='delete_document'),

    # ---------- Tasks ----------
    path('create/', views.create_task, name='create_task'),
    path('list/', views.task_list, name='task_list'),
    path('complete/<int:task_id>/', views.complete_task, name='complete_task'),
    path('archive/<int:task_id>/', views.archive_task, name='archive_task'),

    path('HealthManager/', views.HealthManager, name='HealthManager'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('add/<str:item_type>/', views.add_item, name='add_item'),

    # ---------- Deletes ----------
    path('delete-bill/<int:bill_id>/', views.delete_bill, name='delete_bill'),
    path('delete-sub/<int:sub_id>/', views.delete_sub, name='delete_sub'),
]

urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
