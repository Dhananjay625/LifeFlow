# store/models.py

import os
import random
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models, IntegrityError
from django.template.defaultfilters import slugify
from django.utils.timezone import now
from django.utils.translation import gettext_lazy as _

from .managers import OrderItemManager, SubscriptionManager, ProductManager, PriceManager


# -----------------------------------------------------------------------------
# Utilities
# -----------------------------------------------------------------------------

def _stripe_enabled() -> bool:
    """True only when paid mode is on AND a secret key is provided."""
    return bool(getattr(settings, "APPSTORE_PAID_MODE", False) and getattr(settings, "STRIPE_SECRET_KEY", ""))


def _get_stripe():
    """
    Lazy import stripe and set api_key.
    Returns the stripe module or None if disabled/unavailable.
    """
    if not _stripe_enabled():
        return None
    try:
        import stripe  # local import to avoid module import errors when unused
        stripe.api_key = settings.STRIPE_SECRET_KEY
        return stripe
    except Exception:
        return None


def get_updated_fields(model, instance):
    """Returns the fields that have changed between the instance and original DB instance"""
    changed_fields = []
    original = None

    if instance.pk:
        original = model.objects.get(pk=instance.pk)

        for field in model._meta.fields:
            field_name = field.name
            old_value = getattr(original, field_name)
            new_value = getattr(instance, field_name)
            if old_value != new_value:
                changed_fields.append(field_name)

    return changed_fields, original


def get_product_static_folder(instance, filename):
    name_slug = slugify(instance.name)
    folder = f"{name_slug}-{instance.pk}"
    ext = '.'.join(filename.split('.')[1:])
    return folder, ext


def get_product_thumbnail(instance, filename):
    folder, ext = get_product_static_folder(instance, filename)
    return os.path.join('products', folder, f"thumbnail{ext}")


def get_product_icon(instance, filename):
    folder, ext = get_product_static_folder(instance, filename)
    return os.path.join('products', folder, f"icon{ext}")


def generate_order_number():
    # Example: ORD-YYYYMMDD-1234567
    date_part = now().strftime('%Y%m%d')
    while True:
        rand_part = str(random.randint(0, 9_999_999)).zfill(7)
        order_num = f"ORD-{date_part}-{rand_part}"
        if not Order.objects.filter(order_number=order_num).exists():
            return order_num


# -----------------------------------------------------------------------------
# Models
# -----------------------------------------------------------------------------

class Customer(models.Model):
    """
    Represents a Stripe customer, associated with a Django user.
    In free mode (no Stripe), stripe_customer_id stays empty.
    """
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    stripe_customer_id = models.CharField(max_length=255, null=True, blank=True)

    def __str__(self):
        return f"{self.name} ({self.email})"

    @property
    def name(self):
        # Safely derive a display name
        full = getattr(self.user, "get_full_name", lambda: "")() or ""
        return full.strip() or getattr(self.user, "username", "") or str(self.user)

    @property
    def email(self):
        return getattr(self.user, "email", "") or ""

    def save(self, *args, **kwargs):
        creating = not self.pk
        super().save(*args, **kwargs)

        # Create a Stripe customer only in paid mode with a key
        if (creating or not self.stripe_customer_id) and _stripe_enabled():
            stripe = _get_stripe()
            if stripe:
                try:
                    stripe_customer = stripe.Customer.create(
                        email=self.email or None,
                        name=self.name or None,
                    )
                    self.stripe_customer_id = stripe_customer.id
                    super().save(update_fields=['stripe_customer_id'])
                except Exception as e:
                    # In free mode or on any Stripe failure, do nothing fatal
                    print(f"[Store] Stripe customer creation skipped/failed: {e}")


class ProductTag(models.Model):
    """
    Product tags for grouping products in the store.
    """
    name = models.CharField(
        max_length=100,
        help_text=_("Designates the name of the tag."),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return self.name

    class Meta:
        ordering = ['name']


class BillingType(models.TextChoices):
    ONE_TIME = "one_time", "One-Time"
    SUBSCRIPTION = "subscription", "Subscription"


class BillingInterval(models.TextChoices):
    MONTHLY = "month", "Monthly"
    YEARLY = "year", "Yearly"
    SIX_MONTHS = "6_months", "6 Months"  # Custom, only if you support it


class Product(models.Model):
    """
    Represents a product listed in the store, optionally linked to a Stripe product ID.
    """
    # Product Identifiers
    id = models.CharField(
        primary_key=True,
        max_length=255,
        help_text="Unique code like 'tenement_management_system'",
        validators=[
            RegexValidator(
                regex=r'[a-z0-9_]+',
                message="ID must contain lowercase and underscores only."
            )
        ]
    )
    stripe_product_id = models.CharField(max_length=255, null=True, blank=True, help_text="Auto-filled by Stripe.")

    # Product Information
    name = models.CharField(max_length=200, help_text="Display name like 'Tenement Management System'")
    description = models.CharField(max_length=200, default="", blank=True, help_text="Short description for product")
    long_description = models.CharField(max_length=5000, default="", blank=True)
    tags = models.ManyToManyField(ProductTag, blank=True)
    thumbnail = models.ImageField(upload_to=get_product_thumbnail, blank=True, null=True)
    icon = models.ImageField(upload_to=get_product_icon, blank=True, null=True)

    # Purchase Information
    url = models.URLField(
        help_text="Destination URL for the product after purchase (e.g. https://app.example.com/dashboard)",
        blank=True, null=True
    )
    single_purchase_only = models.BooleanField(
        default=False,
        help_text="If enabled, users can only buy this product once."
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ProductManager()

    def __str__(self):
        return self.name

    class Meta:
        ordering = ["-created_at"]

    def get_current_price(self):
        return Price.objects.filter(product=self).order_by("-active", "-updated_at").first()

    @property
    def current_price(self):
        price = self.get_current_price()
        return price.amount if price else 0

    def save(self, *args, update_stripe=True, **kwargs):
        """
        In free mode: just save to DB and skip Stripe.
        In paid mode: create/update Stripe product as needed.
        """
        super().save(*args, **kwargs)

        if not update_stripe:
            return

        stripe = _get_stripe()
        if not stripe:
            # Free mode or missing key: skip Stripe side-effects
            return

        # Create product on Stripe if missing
        if not self.stripe_product_id:
            try:
                stripe_product = stripe.Product.create(
                    name=self.name,
                    description=self.description or None,
                    images=[self.thumbnail.url] if self.thumbnail else [],
                    metadata={"internal_product_id": str(self.id)},
                )
                self.stripe_product_id = stripe_product.id
                super().save(update_fields=['stripe_product_id'])
            except Exception as e:
                print(f"[Store] Stripe product creation failed: {e}")
        else:
            # Update existing product if fields have changed
            try:
                stripe.Product.modify(
                    self.stripe_product_id,
                    name=self.name,
                    description=self.description or None,
                    images=[self.thumbnail.url] if self.thumbnail else [],
                )
            except Exception as e:
                print(f"[Store] Stripe product update failed: {e}")


class Price(models.Model):
    """
    A price in **dollars** for a product.
    If you enable paid mode, note Stripe expects unit_amount in **cents**.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="prices")
    amount = models.PositiveIntegerField(help_text="Numerical value in Dollars")

    is_subscription = models.BooleanField(default=False)
    billing_interval = models.CharField(max_length=20, choices=BillingInterval.choices, null=True, blank=True)
    active = models.BooleanField(default=True, help_text="Active prices are visible to customers")

    stripe_price_id = models.CharField(max_length=255, null=True, blank=True, help_text="Auto-filled by Stripe")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = PriceManager()

    @property
    def amount_cents(self) -> int:
        return int(self.amount) * 100

    def stripe_recurring(self):
        if self.billing_interval == BillingInterval.MONTHLY:
            return {"interval": "month", "interval_count": 1}
        elif self.billing_interval == BillingInterval.YEARLY:
            return {"interval": "year", "interval_count": 1}
        elif self.billing_interval == BillingInterval.SIX_MONTHS:
            return {"interval": "month", "interval_count": 6}
        else:
            raise ValueError("Unsupported billing interval")

    def save(self, *args, update_stripe=True, **kwargs):
        """
        In free mode: save and return.
        In paid mode: ensure Stripe product exists and create/modify Stripe price.
        """
        super().save(*args, **kwargs)

        if not update_stripe:
            return

        stripe = _get_stripe()
        if not stripe:
            # Free mode or missing key
            return

        # Ensure product exists in Stripe
        if not self.product.stripe_product_id:
            self.product.save(update_stripe=True)

        # Create or update Stripe price
        if not self.stripe_price_id:
            try:
                stripe_price = stripe.Price.create(
                    product=self.product.stripe_product_id,
                    # IMPORTANT: Stripe expects cents; your `amount` is dollars.
                    unit_amount=self.amount_cents,
                    currency="aud",
                    recurring=self.stripe_recurring() if self.is_subscription else None,
                    metadata={"internal_price_id": str(self.id)},
                )
                self.stripe_price_id = stripe_price.id
                self.save(update_fields=['stripe_price_id'], update_stripe=False)
            except Exception as e:
                print(f"[Store] Stripe price creation failed: {e}")
        else:
            try:
                stripe.Price.modify(self.stripe_price_id, active=self.active)
            except Exception as e:
                print(f"[Store] Stripe price update failed: {e}")

    class Meta:
        ordering = ["product", "-active", "amount"]

    def __str__(self):
        if self.is_subscription:
            return f"{self.product.name} - ${self.amount} ({self.get_billing_interval_display()})"
        return f"{self.product.name} - ${self.amount}"


class Order(models.Model):
    """
    Tracks the state of an order made by the user.
    Stripe fields are optional and only populated in paid mode.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order_number = models.CharField(max_length=20, unique=True, editable=False)
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE)
    complete = models.BooleanField(default=False, help_text="Incomplete orders are still in the customer's cart.")

    # Stripe fields
    stripe_checkout_session_id = models.CharField(max_length=255, null=True, blank=True, help_text="Auto-filled by Stripe")
    stripe_payment_intent_id = models.CharField(max_length=255, null=True, blank=True, help_text="Auto-filled by Stripe")
    stripe_charge_id = models.CharField(max_length=255, null=True, blank=True, help_text="Auto-filled by Stripe")
    receipt_url = models.URLField(null=True, blank=True, help_text="Digital receipt URL")

    stripe_refund_id = models.CharField(max_length=255, null=True, blank=True, help_text="Auto-filled by Stripe")
    refunded_amount = models.PositiveIntegerField(default=0, help_text="Amount of cents refunded")  # in cents

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Order {self.order_number} - {'Complete' if self.complete else 'Cart'}"

    @property
    def total_items(self):
        return sum(item.quantity for item in self.items.all())

    @property
    def total_price(self):
        return sum(item.price.amount * item.quantity for item in self.items.all())

    @property
    def total_price_cents(self):
        return self.total_price * 100

    def save(self, *args, **kwargs):
        if not self.order_number:
            # Try to generate a unique order number for the model
            for _ in range(20):
                self.order_number = generate_order_number()
                try:
                    super().save(*args, **kwargs)
                    return
                except IntegrityError:
                    continue
            raise ValueError("Could not generate a unique order number after 20 attempts.")
        else:
            super().save(*args, **kwargs)

    def request_refund(self, reason):
        """
        Attempt to refund via Stripe. In free mode returns False.
        """
        valid_reasons = {'duplicate', 'fraudulent', 'requested_by_customer'}

        if reason not in valid_reasons:
            raise ValidationError(f"Invalid refund reason. Must be one of {', '.join(valid_reasons)}.")

        if not self.stripe_payment_intent_id:
            raise ValidationError("No payment intent associated with this order.")

        if self.refunded_amount == self.total_price_cents:
            raise ValidationError("This order has already been refunded.")

        stripe = _get_stripe()
        if not stripe:
            # Free mode: no-op
            return False

        try:
            refund = stripe.Refund.create(
                payment_intent=self.stripe_payment_intent_id,
                reason=reason,
                currency="aud",
                metadata={'internal_order_id': str(self.id)},
            )

            self.stripe_refund_id = refund.get('id')
            self.refunded_amount = self.total_price_cents
            self.save(update_fields=['stripe_refund_id', 'refunded_amount'])
            self.items.update(refunded=True, refunded_at=now())
        except Exception as e:
            print(f"[Store] Refund failed: {e}")
            return False

        return True


class OrderItem(models.Model):
    """
    The item history stored in the database indicating which price was paid for the product.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    price = models.ForeignKey(Price, on_delete=models.PROTECT)  # Prevent deletion of historical prices

    quantity = models.PositiveIntegerField(default=0)
    added_at = models.DateTimeField(auto_now_add=True)

    refunded = models.BooleanField(default=False)
    refunded_at = models.DateTimeField(null=True, blank=True)

    objects = OrderItemManager()

    @property
    def total_price(self):
        return self.quantity * self.price.amount

    def request_refund(self, reason):
        """
        Partial refund for this line item. In free mode returns None (no-op).
        """
        valid_reasons = {'duplicate', 'fraudulent', 'requested_by_customer'}

        if reason not in valid_reasons:
            raise ValidationError(f"Invalid refund reason. Must be one of {', '.join(valid_reasons)}.")

        if not self.order.stripe_payment_intent_id:
            raise ValidationError("No payment intent associated with this item.")

        if self.refunded:
            raise ValidationError("This item has already been refunded.")

        stripe = _get_stripe()
        if not stripe:
            # Free mode: no-op
            return None

        refund_amount = self.price.amount_cents
        try:
            refund = stripe.Refund.create(
                payment_intent=self.order.stripe_payment_intent_id,
                reason=reason,
                currency="aud",
                amount=refund_amount,
                metadata={
                    'internal_order_id': str(self.order.id),
                    'item_id': str(self.id),
                }
            )
        except Exception as e:
            print(f"[Store] Item refund failed: {e}")
            return None

        # Update order & item
        self.order.stripe_refund_id = refund.get('id')
        self.order.refunded_amount = (self.order.refunded_amount or 0) + refund_amount
        self.order.save(update_fields=['stripe_refund_id', 'refunded_amount'])

        self.refunded = True
        self.refunded_at = now()
        self.save(update_fields=['refunded', 'refunded_at'])
        return refund

    def __str__(self):
        return f"{self.quantity} × {self.product.name} @ ${self.price.amount}"

    class Meta:
        ordering = ["order", "added_at"]


class SubscriptionStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    CANCELED = "canceled", "Canceled"
    INCOMPLETE = "incomplete", "Incomplete"
    INCOMPLETE_EXPIRED = "incomplete_expired", "Incomplete Expired"
    PAST_DUE = "past_due", "Past Due"
    TRIALING = "trialing", "Trialing"
    PAID = "paid", "Paid"
    UNPAID = "unpaid", "Unpaid"


class Subscription(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # Relation fields
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="subscriptions")
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    price = models.ForeignKey(Price, on_delete=models.CASCADE)

    # Status Fields
    status = models.CharField(max_length=30, choices=SubscriptionStatus.choices)
    current_period_start = models.DateTimeField()
    current_period_end = models.DateTimeField()

    # Stripe Fields
    stripe_subscription_id = models.CharField(max_length=255, unique=True, null=True, blank=True, help_text="Auto-filled by Stripe")
    attempt_count = models.IntegerField(default=0)
    next_payment_attempt = models.DateTimeField(null=True, blank=True, help_text="Auto-filled by Stripe if payment failed.")
    latest_stripe_invoice_id = models.CharField(max_length=255, null=True, blank=True, help_text="Auto-filled by Stripe")

    cancel_at_period_end = models.BooleanField(
        default=False,
        help_text="Whether to renew subscription at end of period"
    )
    cancel_at = models.DateTimeField(null=True, blank=True)
    canceled_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = SubscriptionManager()

    def is_active(self):
        """Whether this subscription is active, including grace period allowances."""
        if self.status in [SubscriptionStatus.ACTIVE, SubscriptionStatus.PAID]:
            return True
        if self.status == SubscriptionStatus.PAST_DUE and self.next_payment_attempt:
            return True
        return False

    def get_subscription_id_display(self):
        return (self.stripe_subscription_id or "")[4:]

    def trigger_cancel(self, at_period_end=False):
        """
        Cancels the subscription immediately or at period end.
        Free mode: returns False (no-op).
        """
        stripe = _get_stripe()
        if not stripe or not self.stripe_subscription_id:
            return False

        try:
            if at_period_end:
                stripe.Subscription.modify(self.stripe_subscription_id, cancel_at_period_end=True)
                self.cancel_at = self.current_period_end
                self.cancel_at_period_end = True
                self.save(update_fields=['cancel_at', 'cancel_at_period_end'])
            else:
                stripe.Subscription.cancel(self.stripe_subscription_id)
                self.status = SubscriptionStatus.CANCELED
                self.canceled_at = now()
                self.ended_at = now()
                self.save(update_fields=['status', 'canceled_at', 'ended_at'])
        except Exception as e:
            print(f"[Store] Stripe cancellation failed: {e}")
            return False
        return True

    def modify(self, **kwargs):
        stripe = _get_stripe()
        if not stripe or not self.stripe_subscription_id:
            return False
        try:
            stripe.Subscription.modify(self.stripe_subscription_id, **kwargs)
        except Exception as e:
            print(f"[Store] Stripe subscription modify failed: {e}")
            return False
        return True

    def save(self, *args, update_stripe=True, **kwargs):
        """
        When updating fields that should sync to Stripe,
        only attempt that sync in paid mode with a key.
        """
        if update_stripe and self.pk and _stripe_enabled():
            changed_fields, _original = get_updated_fields(Subscription, self)
            updated_fields = {}

            if 'price' in changed_fields:
                if self.price.product == self.product:
                    # NOTE: This is illustrative; real Stripe item update usually needs item IDs.
                    updated_fields['items'] = [{'price': self.price.stripe_price_id}]
                else:
                    raise AttributeError('Price must match subscription product')

            if 'cancel_at_period_end' in changed_fields:
                updated_fields['cancel_at_period_end'] = self.cancel_at_period_end

            # Save locally first
            super().save(*args, **kwargs)

            # Attempt Stripe sync
            if updated_fields:
                self.modify(**updated_fields)
        else:
            super().save(*args, **kwargs)

    def __str__(self):
        return f"Subscription for {self.customer.user} - {self.status}"

    class Meta:
        ordering = ["-current_period_end"]
