import stripe
from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Customer

# Only set API key if in paid mode
if getattr(settings, "APPSTORE_PAID_MODE", False):
    stripe.api_key = getattr(settings, "STRIPE_SECRET_KEY", "")


@receiver(post_save, sender=Customer)
def create_stripe_customer(sender, instance, created, **kwargs):
    """Creates the Stripe customer ID if paid mode is enabled, else fake ID"""
    if created and not instance.stripe_customer_id:
        if getattr(settings, "APPSTORE_PAID_MODE", False) and settings.STRIPE_SECRET_KEY:
            # Real Stripe call
            stripe_customer = stripe.Customer.create(
                email=instance.user.email,
                name=getattr(instance.user, "get_full_name", lambda: "")() or instance.user.username,
            )
            instance.stripe_customer_id = stripe_customer.id
        else:
            # Fake ID for dev mode (no Stripe)
            instance.stripe_customer_id = f"cus_dev_{instance.user.id}"

        instance.save(update_fields=["stripe_customer_id"])
