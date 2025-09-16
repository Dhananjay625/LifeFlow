from django.contrib import admin
from django.urls import path, include, reverse_lazy
from django.contrib.auth import views as auth_views
from django.conf import settings
from django.conf.urls.static import static

from main import views as main_views 
from main import views

urlpatterns = [
    # Admin
    path('admin/', admin.site.urls),

    # Landing
    path('', main_views.LandingPage, name='LandingPage'),

    path("kanban/", include(("kanban.urls", "kanban"), namespace="kanban")),
    path('dashboard/', main_views.dashboard, name='dashboard'),
    path('dashboard-v2/', include(('appboard.urls', 'appboard'), namespace='appboard')),
    path('FamilyManager/', main_views.FamilyManager, name='FamilyManager'),
    path('google/connect/', main_views.google_connect, name='google_connect'),
    path('google/callback/', main_views.google_callback, name='google_callback'),
    path('google/oauth2/callback/', main_views.google_callback, name='google_oauth2_callback'),
    path('profile/', main_views.user_profile, name='user_profile'),
    path('UserProfile/', main_views.user_profile, name='UserProfile'),
    path('calendar/', main_views.calendar_view, name='calendar'),
    path('calendar/events/', main_views.calendar_events, name='calendar_events'),
    path('calendar/events/create/', main_views.calendar_events_create, name='calendar_events_create'),
    path('calendar/events/update/', main_views.calendar_events_update, name='calendar_events_update'),
    path('calendar/events/delete/', main_views.calendar_events_delete, name='calendar_events_delete'),
    path('Subscription/', main_views.SubscriptionTracker, name='Subscription'),
    path('TaskManager/', main_views.TaskManager, name='TaskManager'),
    path('BillManager/', main_views.BillManager, name='BillManager'),
    path('HealthManager/', main_views.health_manager, name='HealthManager'),
    path('health/search/', main_views.health_search, name='health_search'),
    path('reminder/<int:reminder_id>/edit/', views.edit_reminder, name='edit_reminder'),
    path('reminder/<int:reminder_id>/delete/', views.delete_reminder, name='delete_reminder'),
    path('google-fit-auth/', main_views.google_fit_auth, name="google_fit_auth"),
    path('google-fit-login/', main_views.google_fit_login, name="google_fit_login"),
    path('oauth2callback', views.oauth2callback, name="oauth2callback"),
    path("google-fit-connect/", views.google_fit_connect, name="google_fit_connect"),
    path('google-fit-callback/', views.google_fit_callback, name="google_fit_callback"),
    path('register/', main_views.register, name='register'),
    path('login/', main_views.login_view, name='login'),
    path('logout/', auth_views.LogoutView.as_view(next_page='login'), name='logout'),
    path(
        'change-password/',
        auth_views.PasswordChangeView.as_view(
            template_name='UserProfile.html',
            success_url=reverse_lazy('UserProfile')
        ),
        name='change_password',
    ),
    path('DocumentStorage/', main_views.DocumentStorage, name='DocumentStorage'),
    path('confirm-password/', main_views.confirm_password, name='confirm_password'),
    path('delete-document/<int:doc_id>/', main_views.delete_document, name='delete_document'),
    path('create/', main_views.create_task, name='create_task'),
    path('list/', main_views.task_list, name='task_list'),
    path('complete/<int:task_id>/', main_views.complete_task, name='complete_task'),
    path('archive/<int:task_id>/', main_views.archive_task, name='archive_task'),
    path('HealthManager/', main_views.HealthManager, name='HealthManager'),
    path('add/<str:item_type>/', main_views.add_item, name='add_item'),
]

urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)