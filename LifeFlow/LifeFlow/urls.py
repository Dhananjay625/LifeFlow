# LifeFlow/urls.py

from django.contrib import admin
from django.urls import path, include, reverse_lazy
from django.contrib.auth import views as auth_views
from django.conf import settings
from django.conf.urls.static import static

from main import views as main_views
from main import views_widgets
from main import views

urlpatterns = [
    # Admin
    path('admin/', admin.site.urls),

    # Landing
    path('', main_views.LandingPage, name='LandingPage'),

    # ---------- Boards / Dashboards ----------
    path("kanban/", include(("kanban.urls", "kanban"), namespace="kanban")),
    path('dashboard/', main_views.dashboard, name='dashboard'),
    path('dashboard-v2/', include(('appboard.urls', 'appboard'), namespace='appboard')),
    path("store/", include(("store.urls", "store"), namespace="store")),

    # ---------- Family ----------
    # Menu page (wrapper using real data)
    path('FamilyManager/', main_views.FamilyManager, name='FamilyManager'),
    # Optional direct family page
    path('family/', main_views.family_page, name='FamilyPage'),

    # Family actions (copied from the first file)
    path('family/create/', main_views.family_create, name='family_create'),
    path('family/leave/', main_views.family_leave, name='family_leave'),
    path('family/delete/', main_views.family_delete, name='family_delete'),
    path('family/invite/create/', main_views.family_invite_create, name='family_invite_create'),
    path('family/join/<str:code>/', main_views.family_join, name='family_join'),
    path('family/join/', main_views.family_join_code, name='family_join_code'),
    path('family/task/assign/', main_views.family_task_assign, name='family_task_assign'),

    # ---------- Google OAuth (Calendar) ----------
    path('google/connect/', main_views.google_connect, name='google_connect'),
    path('google/callback/', main_views.google_callback, name='google_callback'),
    path('google/oauth2/callback/', main_views.google_callback, name='google_oauth2_callback'),

    # ---------- Profile / Auth ----------
    path('profile/', main_views.user_profile, name='user_profile'),
    path('UserProfile/', main_views.user_profile, name='UserProfile'),
    path('calendar/', main_views.calendar_view, name='calendar'),
    path('calendar/events/', main_views.calendar_view, name='calendar_view'),
    path('calendar/events/create/', main_views.calendar_events_create, name='calendar_events_create'),
    path('calendar/events/update/', main_views.calendar_events_update, name='calendar_events_update'),
    path('calendar/events/delete/', main_views.calendar_events_delete, name='calendar_events_delete'),
    path('Subscription/', main_views.SubscriptionTracker, name='Subscription'),
    path('TaskManager/', main_views.TaskManager, name='TaskManager'),
    path('BillManager/', main_views.BillManager, name='BillManager'),
    path("health-manager/", main_views.health_manager, name="HealthManager"),
    path('health/search/', main_views.health_search, name='health_search'), 
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

    # ---------- Calendar ----------
    path('calendar/', main_views.calendar_view, name='calendar'),
    path('calendar/events/', views_widgets.calendar_events, name='calendar_events'),
    path('calendar/events/create/', main_views.calendar_events_create, name='calendar_events_create'),
    path('calendar/events/update/', main_views.calendar_events_update, name='calendar_events_update'),
    path('calendar/events/delete/', main_views.calendar_events_delete, name='calendar_events_delete'),

    # ---------- App sections ----------
    path('Subscription/', main_views.SubscriptionTracker, name='Subscription'),
    path('BillManager/', main_views.BillManager, name='BillManager'),
    path('add/<str:item_type>/', main_views.add_item, name='add_item'),
 
    

    # ---------- Documents ----------
    path('DocumentStorage/', main_views.DocumentStorage, name='DocumentStorage'),
    path('confirm-password/', main_views.confirm_password, name='confirm_password'),
    path('delete-document/<int:doc_id>/', main_views.delete_document, name='delete_document'),

    # ---------- Tasks ----------
    path('create/', main_views.create_task, name='create_task'),
    path('list/', main_views.task_list, name='task_list'),
    path('complete/<int:task_id>/', main_views.complete_task, name='complete_task'),
    path('archive/<int:task_id>/', main_views.archive_task, name='archive_task'),

    # ---------- Health ----------
    path('HealthManager/', main_views.health_manager, name='HealthManager'),
    path('health/search/', main_views.health_search, name='health_search'),
    path('reminder/<int:reminder_id>/edit/', main_views.edit_reminder, name='edit_reminder'),
    path('reminder/<int:reminder_id>/delete/', main_views.delete_reminder, name='delete_reminder'),
    path("ingest-health-data/", main_views.ingest_health_data, name="ingest_health_data"),
    path("upload-health-data/", main_views.upload_health_data, name="upload_health_data"),
    path("ai-query/", main_views.ai_query, name="ai_query"),

    # ---------- Google Fit ----------
    path('google-fit-auth/', main_views.google_fit_auth, name="google_fit_auth"),
    path('google-fit-login/', main_views.google_fit_login, name="google_fit_login"),
    path('oauth2callback', main_views.oauth2callback, name="oauth2callback"),
    path("google-fit-connect/", main_views.google_fit_connect, name="google_fit_connect"),
    path('google-fit-callback/', main_views.google_fit_callback, name="google_fit_callback"),

    # ---------- Deletes (from first file) ----------
    path('delete-bill/<int:bill_id>/', main_views.delete_bill, name='delete_bill'),
    path('delete-sub/<int:sub_id>/', main_views.delete_sub, name='delete_sub'),


    path('api/widgets/kanban/', views_widgets.kanban_summary),
    path("api/widgets/calendar/", views_widgets.calendar_events, name="calendar_events"),
    path('api/widgets/bills/', views_widgets.bills_summary),
    path("api/widgets/subscription/", views_widgets.subscriptions_summary, name="subscription_summary"),
    path("api/widgets/dashboard/", views_widgets.dashboard_summary, name="dashboard_summary"),
    path("api/widgets/document/", views_widgets.documents_summary, name="document_summary"),
    path('api/widgets/health/', views_widgets.health_summary),
    path('api/widgets/family/', views_widgets.family_summary),
    path('add/<str:item_type>/', main_views.add_item, name='add_item'),
]

# Static/media (single append)
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
