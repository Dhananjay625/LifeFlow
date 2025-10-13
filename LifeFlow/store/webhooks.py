import logging
from datetime import datetime

import stripe
from django.conf import settings
from django.contrib.auth import get_user_model
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404
from django.utils.timezone import now
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import Order, Customer, Subscription, Price, Product, SubscriptionStatus

stripe.api_key = settings.STRIPE_SECRET_KEY
EMAIL_HOST_USER = settings.EMAIL_HOST_USER
CUSTOMER_SERVICE_EMAIL = settings.CUSTOMER_SERVICE_EMAIL
CUSTOMER_SERVICE_TELEPHONE = settings.CUSTOMER_SERVICE_TELEPHONE

User = get_user_model()

"""
This file represents event handling from Stripe. Note that events related to each purchase may not 
always come in the expected order. Separating logic into the appropriate events is necessary.

Be mindful of any mistakes in logic when testing charges, report any if found (e.g., having access to something when
the item has been refunded or a subscription is not available)
"""


def date_from_timestamp(stamp):
    if stamp:
        return datetime.fromtimestamp(stamp)
    return None


def get_or_create_customer(data):
    """Get of create the customer from a stripe event response"""
    obj = data.get('object')

    # Get customer information
    customer = None
    customer_id = data.get('id' if obj == 'customer' else 'customer', None)
    customer_email = None  # email is stored uniquely across event_type objects

    if obj == 'customer':
        customer_email = data.get('email')
    elif obj == 'checkout.session':
        customer_email = data.get('customer_details', {}).get('email')
    elif obj == 'invoice':
        customer_email = data.get('customer_email')
    elif obj == 'charge':
        customer_email = data.get('billing_details', {}).get('email')

    # Try to find customer by ID
    if customer_id:
        customer = Customer.objects.filter(stripe_customer_id=customer_id).first()

    # Try to find/create a customer by email
    if customer_email:
        user = User.objects.filter(email=customer_email).first()
        if user:
            customer, _ = Customer.objects.update_or_create(
                user_id=user.id,
                defaults={'stripe_customer_id': customer_id}
            )

    # Fallback behavior if customer couldn't be resolved
    if not customer:
        pass  # (f"Unhandled Stripe event_type {obj}, could not find customer email or ID.")

    return customer




def handle_subscription_created(customer, subscription):
    """
    Stripe Event Type: subscription.created

    Creates or updates the related subscription.
    """
    logger = logging.getLogger('stripe_webhook')
    subscription_id = subscription['id']  # sub_1RVLg4HBTjqORDmyF5fkBE81

    # Get specific item data from subscription json
    items = subscription.get('items', {}).get('data', [])
    if not items:
        logger.warning(f"No subscription items found for subscription {subscription_id}")
        return
    item = items[0]

    # Assuming the data comes as a list of items
    stripe_price_id = item['price']['id']  # price_1RVLfqHBTjqORDmycXRmLbQj
    stripe_product_id = item['price']['product']  # prod_SP3v762hCR1hoc

    # Get or create the subscription
    price = get_object_or_404(Price, stripe_price_id=stripe_price_id)
    product = get_object_or_404(Product, stripe_product_id=stripe_product_id)

    # Create local subscription object
    Subscription.objects.update_or_create(
        update_stripe=False,  # Stop webhook from being called from this update.
        customer=customer,
        product=product,
        price=price,
        stripe_subscription_id=subscription_id,
        defaults={
            # Basic updates
            'status': subscription.get('status'),
            'current_period_start': date_from_timestamp(item.get("current_period_start")),
            'current_period_end': date_from_timestamp(item.get("current_period_end")),

            # Subscription updates from latest data
            'cancel_at_period_end': subscription.get("cancel_at_period_end", False),
            'cancel_at': date_from_timestamp(subscription.get("cancel_at")),
            'canceled_at': date_from_timestamp(subscription.get("canceled_at")),
            'ended_at': date_from_timestamp(subscription.get("ended_at")),
        }
    )


def handle_checkout_session_completed(customer, session):
    """
    Stripe Event Type: checkout.session.completed

    Handles a completed checkout session. Can be for a one-time or subscription purchase.
    - Marks order complete
    - Sends confirmation email
    - Displays success page
    """
    session_id = session.get('id')
    subscription_id = session.get('subscription')
    mode = session.get('mode')  # 'payment' or 'subscription'
    metadata = session.get('metadata', {})

    # Payment mode determines kind of order
    if mode == 'subscription' and subscription_id:
        # Get latest subscription information from stripe
        sub = stripe.Subscription.retrieve(subscription_id)
        handle_subscription_created(customer, sub)
    else:
        # Find the order being completed
        # Note: that the session_id is set on the store view where the checkout is made
        Order.objects.filter(
            customer=customer,
            stripe_checkout_session_id=session_id,
        ).update(
            complete=True,
            stripe_payment_intent_id=session.get('payment_intent'),
        )

        # TODO: Send confirmation email
        # # Email receipt to user if customer and email available
        # user_email = customer.email if customer else session.get("customer_details", {}).get("email")
        #
        # if user_email:
        #     email_context = {
        #         "transaction_id": payment_intent_id,
        #         "transaction_date": order.created_at.strftime("%d %b %Y"),
        #         "total_price": f"{round(total_price, 2):.2f}",
        #         "contact_email": settings.CUSTOMER_SERVICE_EMAIL,
        #         "contact_phone": settings.CUSTOMER_SERVICE_TELEPHONE,
        #         "receipt_url": receipt_url,
        #     }
        #
        #     subject = 'Your order receipt'
        #     html_message = render_to_string('store/email_payment_successful.html', context=email_context)
        #     message = EmailMessage(subject, html_message, settings.EMAIL_HOST_USER, [user_email])
        #     message.content_subtype = 'html'
        #     message.send()


def handle_subscription_updated(customer, subscription):
    """
    Stripe Event Type: customer.subscription.updated

    Updates or creates a local Subscription record
    """
    subscription_id = subscription.get('id')  # sub_1RVLg4HBTjqORDmyF5fkBE81
    subscription_status = subscription.get('status')
    items = subscription.get('items', {}).get('data', [])

    # Cancellation fields
    cancel_at_period_end = subscription.get('cancel_at_period_end', False)
    cancel_at = date_from_timestamp(subscription.get('cancel_at'))  # TODO: This is when the sub SHOULD be canceled.
    canceled_at = date_from_timestamp(subscription.get('canceled_at'))

    # Assuming the data comes as a list of items
    for data in items:
        current_period_end = date_from_timestamp(data.get('current_period_end'))
        current_period_start = date_from_timestamp(data.get('current_period_start'))

        Subscription.objects.filter(
            customer=customer,
            stripe_subscription_id=subscription_id,
        ).update(
            update_stripe=False,  # Stop webhook from being called from this update.
            status=subscription_status,
            current_period_end=current_period_end,
            current_period_start=current_period_start,
            cancel_at_period_end=cancel_at_period_end,
            cancel_at=cancel_at,
            canceled_at=canceled_at,
        )


def handle_subscription_deleted(customer, subscription):
    """
    Stripe Event Type: customer.subscription.deleted

    Marks the Subscription as canceled in the local database and updates appropriate fields.
    """
    # items = subscription.get('items', {}).get('data', [])
    # Don't need to iterate subscription items as only the status, canceled_at and ended_at fields are updated
    obj = get_object_or_404(
        Subscription,
        customer=customer,
        stripe_subscription_id=subscription.get('id')
    )

    # Subscription updates from latest data
    obj.status = SubscriptionStatus.CANCELED
    obj.canceled_at = date_from_timestamp(subscription.get("canceled_at"))
    obj.ended_at = date_from_timestamp(subscription.get("ended_at"))
    obj.save(update_stripe=False)


def handle_invoice_payment_failed(customer, invoice):
    """
    Stripe Event Type: invoice.payment_failed

    This event is triggered only for Subscription purchases.
    For single-purchase items, only `payment_intent.payment_failed` and `charge.failed`.
    """
    attempt_count = invoice.get('attempt_count', 0)
    next_payment_attempt = date_from_timestamp(invoice.get('next_payment_attempt'))
    items = invoice.get('lines', {}).get('data', [])

    # Iterate each item and update local db
    for item in items:
        parent = item.get('parent')
        subscription_item_details = parent.get('subscription_item_details')  # Subscription invoices

        if subscription_item_details:
            continue

        stripe_subscription_id = subscription_item_details.get('subscription')

        subscription = Subscription.objects.filter(
            customer=customer,
            stripe_subscription_id=stripe_subscription_id
        ).first()

        if not subscription:
            continue

        subscription.attempt_count = attempt_count
        subscription.next_payment_attempt = next_payment_attempt
        subscription.status = SubscriptionStatus.PAST_DUE
        subscription.save(update_stripe=False, update_fields=['attempt_count', 'next_payment_attempt', 'status'])

        # If next_payment_attempt is None, that meanst stripe will not attempt to charge the user
        # again, so we trigger a cancel event.
        if next_payment_attempt is None:
            subscription.trigger_cancel(at_period_end=False)


def handle_invoice_payment_succeeded(customer, invoice):
    """
    Stripe Event Type: invoice.payment_succeeded

    This event is triggered only for Subscription purchases.
    For single-purchase items, only `payment_intent.succeeded` and `charge.succeeded` are created.
    """
    items = invoice.get('lines', {}).get('data', [])
    stripe_invoice_id = invoice.get('id')

    for item in items:
        parent = item.get('parent')
        # invoice_item_details = parent.get('invoice_item_details')  #
        subscription_item_details = parent.get('subscription_item_details')  # Subscription invoices

        if subscription_item_details:
            # Reset subscription items payment attempt fields
            stripe_subscription_id = subscription_item_details.get('subscription')

            # Get latest subscription data post successful payment
            stripe.api_key = settings.STRIPE_SECRET_KEY
            subscription = stripe.Subscription.retrieve(stripe_subscription_id)
            current_period = subscription.get('items', {}).get('data', [{}])[0]

            subscription, _ = Subscription.objects.update_or_create(
                update_stripe=False,  # Stop webhook from being called from this update.
                customer=customer,
                stripe_subscription_id=stripe_subscription_id,
                defaults={
                    # Status Fields
                    "status": subscription.get('status'),
                    "current_period_start": date_from_timestamp(current_period.get("current_period_start")),
                    "current_period_end": date_from_timestamp(current_period.get("current_period_end")),

                    # Invoice fields
                    "attempt_count": 1,
                    "next_payment_attempt": None,
                    "latest_stripe_invoice_id": stripe_invoice_id,

                    # Subscription updates from latest data
                    "cancel_at_period_end": subscription.get("cancel_at_period_end", False),
                    "cancel_at": date_from_timestamp(subscription.get("cancel_at")),
                    "canceled_at": date_from_timestamp(subscription.get("canceled_at")),
                    "ended_at": date_from_timestamp(subscription.get("ended_at")),
                }
            )


def handle_invoice_payment_upcoming(customer, invoice):
    pass  # TODO: Send reminder email to customer indicating new charge coming soon


def handle_charge_succeeded(customer, charge):
    """
    Stripe Event Type: charge.succeeded
    """
    Order.objects.filter(
        customer=customer,
        stripe_payment_intent_id=charge.get("payment_intent"),
    ).update(
        stripe_charge_id=charge.get("id"),
        receipt_url=charge.get("receipt_url"),
    )


def handle_charge_refunded(customer, charge):
    """
    Stripe Event Type: charge.refunded
    """
    invoice_id = charge.get("invoice")
    subscription_id = None

    if invoice_id:
        invoice = stripe.Invoice.retrieve(invoice_id)
        subscription_id = invoice.get("subscription")

    if subscription_id:
        # Stripe does not automatically cancel a subscription on refund
        stripe.Subscription.cancel(subscription_id)
    else:
        # Single item orders
        Order.objects.filter(
            customer=customer,
            stripe_payment_intent_id=charge.get("payment_intent"),
        ).update(
            stripe_charge_id=charge.get("id"),
            refunded=charge.get("refunded"),
            refunded_at=now(),
            receipt_url=charge.get("receipt_url"),
        )


def handle_customer_created(customer, data):
    email = data.get('email')
    customer_id = data.get('id')

    # If a customer is created on stripe, we must sync it with the local database
    # if our database does not have a user by the associated email, send a delete
    # request.
    if email and customer_id:
        user = User.objects.filter(email=email).first()
        if user:
            Customer.objects.update_or_create(
                user=user,
                defaults={
                    'stripe_customer_id': customer_id,
                }
            )
        else:
            stripe.Customer.delete(customer_id)


def handle_product_created(customer, product):
    """This doesn't do anything, logic is handled in the Price save method."""
    product_id = product.get('metadata', {}).get('internal_product_id', None)
    stripe_product_id = product.get('id')


def handle_product_updated(customer, product):
    pass


def handle_price_created(customer, price):
    """This doesn't do anything, logic is handled in the Price save method."""
    price_id = price.get('metadata', {}).get('internal_price_id', None)
    stripe_price_id = price.get('id')


def handle_price_updated(customer, price):
    pass


STRIPE_EVENT_HANDLERS = {
    # A Checkout session has been successfully completed (paid)
    # Mark order as paid, fulfill product (for both subscriptions and one time payments)
    'checkout.session.completed': handle_checkout_session_completed,
    # session.get('mode') is 'payment' or 'subscription'

    # Subscription handlers
    # ---------------------
    'customer.subscription.created': handle_subscription_created,  # A new subscription has been created, sync database
    # A subscription's status, plan, or billing details changed
    # Detect pending cancellations, pauses, changes including billing period updates
    'customer.subscription.updated': handle_subscription_updated,
    # A subscription has been canceled or deleted
    'customer.subscription.deleted': handle_subscription_deleted,  # Handle end-of-subscription cleanup
    'customer.subscription.paused': None,  # A subscription has been paused (requires billing settings)
    'customer.subscription.resumed': None,  # A previously paused subscription has resumed

    # Invoice handlers
    # ---------------------
    'invoice.payment_succeeded': handle_invoice_payment_succeeded,
    # Confirm ongoing access (monthly/yearly billing succeeded)
    'invoice.payment_failed': handle_invoice_payment_failed,  # Notify user, possibly suspend access
    'invoice.upcoming': handle_invoice_payment_upcoming,  # Notification sent before an invoice is created (for reminders)

    # Charge Handlers
    # ---------------------
    'charge.succeeded': handle_charge_succeeded,
    'charge.refunded': handle_charge_refunded,

    # Other handlers
    # ---------------------
    # If a customer was created on the Stripe dashboard, try to create one locally with the email provided
    # Only works if the user is already registered on GeoDesk
    'customer.created': handle_customer_created,

    # Not sure if these need to be handled or not
    'product.created': handle_product_created,
    'product.updated': handle_product_updated,
    'price.created': handle_price_created,
    'price.updated': handle_price_updated,
}


@csrf_exempt
@require_POST
def stripe_webhook(request):
    """
    Main Stripe webhook endpoint that listens for Stripe events.

    - Verifies webhook signature
    - Delegates to appropriate handler function
    """
    payload = request.body
    sig_header = request.META.get('HTTP_STRIPE_SIGNATURE')
    endpoint_secret = settings.STRIPE_WEBHOOK_SECRET
    logger = logging.getLogger('stripe_webhook')

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, endpoint_secret)
    except (ValueError, stripe.error.SignatureVerificationError):
        logger.warning("Invalid webhook signature or payload")
        return HttpResponseBadRequest("Invalid signature or payload")

    event_type = event['type']
    data = event.get('data', {}).get('object', {})
    customer = get_or_create_customer(data)

    logger.debug(f'event_type: {event_type}')

    if not customer:
        logger.warning(f"Could not resolve customer for event: {event_type}")

    handler = STRIPE_EVENT_HANDLERS.get(event_type)
    if handler:
        handler(customer, data)
    else:
        # Unknown or unhandled event
        print(f"Unhandled event type: {event_type}")

    return HttpResponse(status=200)

    # elif event_type == 'checkout.session.async_payment_succeeded':
    #     # Payment for an asynchronous Checkout session succeeded
    #     pass
    #
    # elif event_type == 'checkout.session.async_payment_failed':
    #     # Payment for an asynchronous Checkout session failed
    #     pass
    #
    # elif event_type == 'invoice.created':
    #     # A new invoice is created for a subscription or one-time item
    #     pass
    #
    # elif event_type == 'invoice.finalized':
    #     # An invoice has been finalized and is ready to be paid
    #     pass
    #
    # elif event_type == 'invoice.payment_succeeded':
    #     # A payment for an invoice has been successfully completed
    #     # handle_invoice_payment_succeeded(session)
    #     pass
    #
    # elif event_type == 'invoice.payment_failed':
    #     # An attempt to pay an invoice failed (e.g., card declined)
    #     # handle_invoice_payment_failed(session)
    #     pass
    #
    # elif event_type == 'invoice.marked_uncollectible':
    #     # Stripe marked the invoice as uncollectible after retries failed
    #     pass
    #
    # elif event_type == 'invoice.voided':
    #     # Invoice has been voided (canceled)
    #     pass
    #
    # elif event_type == 'payment_intent.created':
    #     # A PaymentIntent was created (used for manual payments)
    #     pass
    #
    # elif event_type == 'payment_intent.succeeded':
    #     # PaymentIntent has succeeded (i.e., payment completed)
    #     pass
    #
    # elif event_type == 'payment_intent.payment_failed':
    #     # PaymentIntent failed (e.g., card declined, auth failed)
    #     pass
    #
    # elif event_type == 'charge.succeeded':
    #     # A charge (payment) was successful
    #     pass
    #
    # elif event_type == 'charge.failed':
    #     # A charge failed (card declined, expired, etc.)
    #     pass
    #
    # elif event_type == 'charge.refunded':
    #     # A charge was refunded either partially or fully
    #     pass
    #
    # elif event_type == 'charge.updated':
    #     # A charge object was updated (e.g., dispute, metadata)
    #     pass
    #
    # elif event_type == 'charge.dispute.created':
    #     # A customer initiated a dispute for a charge
    #     pass
    #
    # elif event_type == 'charge.dispute.closed':
    #     # A dispute was resolved (either won or lost)
    #     pass
    #
    # elif event_type == 'customer.created':
    #     # A customer was created (usually automatic)
    #     pass
    #
    # elif event_type == 'customer.updated':
    #     # Customer info (email, address, etc.) was updated
    #     pass
    #
    # elif event_type == 'customer.deleted':
    #     # A customer was deleted
    #     pass
    #
    # elif event_type == 'payment_method.attached':
    #     # A new payment method (card, etc.) was attached to a customer
    #     pass
    #
    # elif event_type == 'payment_method.detached':
    #     # A payment method was removed from a customer
    #     pass
    #
    # elif event_type == 'product.created':
    #     # A new product was created in Stripe dashboard
    #     pass
    #
    # elif event_type == 'product.updated':
    #     # A product was updated (name, metadata, etc.)
    #     pass
    #
    # elif event_type == 'price.created':
    #     # A new price (recurring or one-time) was added
    #     pass
    #
    # elif event_type == 'price.updated':
    #     # A price was modified (though most fields are immutable)
    #     pass
    #
    # elif event_type == 'subscription_schedule.created':
    #     # A future subscription schedule was created
    #     pass
    #
    # elif event_type == 'subscription_schedule.updated':
    #     # A subscription schedule was updated
    #     pass
    #
    # elif event_type == 'subscription_schedule.released':
    #     # A schedule was released into an actual subscription
    #     pass
    #
    # elif event_type == 'subscription_schedule.canceled':
    #     # A schedule was canceled before starting
    #     pass
