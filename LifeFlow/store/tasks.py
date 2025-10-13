from celery import shared_task
from .models import Subscription


@shared_task
def check_expired_subscriptions():
    """
    Cancels subscriptions that are either:
    - Past their current_period_end and marked to cancel at period end
    - Past their grace period for failed payments
    """
    subs_to_cancel = Subscription.objects.get_cancelable_subscriptions()

    for sub in subs_to_cancel:
        sub.cancel(at_period_end=False)
