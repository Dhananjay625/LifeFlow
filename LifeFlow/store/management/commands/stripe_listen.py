from django.core.management.base import BaseCommand
import subprocess
from django.conf import settings
from django.urls import reverse


class Command(BaseCommand):
    help = "Run Stripe CLI listener forwarding to local webhook URL"

    def handle(self, *args, **kwargs):
        webhook_url = f"{settings.SITE_URL}{reverse('store:webhook')}"
        try:
            self.stdout.write(f"Starting Store webhook. Listening to Stripe and forwarding to {webhook_url}")
            subprocess.run(
                ['stripe', 'listen', '--forward-to', webhook_url],
                check=True
            )
        except subprocess.CalledProcessError as e:
            self.stderr.write(f"Error running Stripe CLI: {e}")
        except KeyboardInterrupt:
            self.stdout.write("Webhook listener stopped.")
