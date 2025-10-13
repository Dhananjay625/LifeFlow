from django.apps import AppConfig
from django.urls import reverse
from django.conf import settings


class StoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'store'

    def ready(self):
        from . import signals
