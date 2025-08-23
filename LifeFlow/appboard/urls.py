from django.urls import path
from . import views

app_name = "appboard"

urlpatterns = [
    path("", views.home, name="home"),
    path("api/file-uploader/", views.file_uploader, name="file_uploader"),
    path("api/mapplotter/", views.mapplotter, name="mapplotter"),
]