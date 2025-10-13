from django.db import models
from django.db.models import Count, Q, Sum, OuterRef, Subquery, IntegerField, Exists, ExpressionWrapper, F, Value


class StripeQueryset(models.QuerySet):
    """
    Custom queryset that enforces syncing updates with Stripe.
    Overrides the default `update()` method to use `save()` per object.
    This avoids bypassing custom save logic that may interact with Stripe.
    """
    def update(self, update_stripe=True, **kwargs):
        """
        Applies updates to each object individually and calls `.save()`
        so that Stripe-related logic runs as expected.

        Note: This sacrifices bulk performance for correctness.
        """
        for obj in self:
            for attr, value in kwargs.items():
                setattr(obj, attr, value)
            obj.save(update_stripe=update_stripe)


class StripeManager(models.Manager):
    """
    Custom manager that disables risky bulk operations and wraps object
    creation/update logic with Stripe sync.
    """
    def get_queryset(self):
        return StripeQueryset(self.model, using=self._db)

    def get_or_create(self, defaults=None, update_stripe=True, **lookup):
        raise NotImplementedError("Not allowed. Use `.update_or_create()` instead to ensure Stripe sync.")

    def update_or_create(self, defaults=None, update_stripe=True, **lookup):
        """
        Enforces Stripe update when an object is created or updated.

        Unlike Django's native `update_or_create`, this does not use
        atomic database updates for safety and Stripe integrity.
        """
        obj, created = self.get_queryset().filter(**lookup).first(), False

        if not obj:
            obj = self.model(**lookup)
            created = True

        for key, value in (defaults or {}).items():
            setattr(obj, key, value)

        obj.save(update_stripe=update_stripe)
        return obj, created


class ProductQuerySet(StripeQueryset):
    def annotate_popularity(self, weight_orders=1, weight_subscriptions=2):
        """
        Annotates each product with:
        - `total_orders`: the count of completed, non-refunded orders.
        - `total_subscriptions`: the count of active or grace-period subscriptions.
        - `popularity`: a weighted sum of orders and subscriptions, calculated as:

            popularity = (total_orders * weight_orders) + (total_subscriptions * weight_subscriptions)

        This metric reflects product popularity based on both sales and active subscriptions.
        """
        return self.annotate(
            # Total number of completed, non-refunded orders for this product
            total_orders=Count(
                'orderitem',
                filter=Q(orderitem__order__complete=True, orderitem__refunded=False),
                distinct=True
            ),
            # Total number of active subscriptions for this product
            total_subscriptions=Count(
                'subscription',
                filter=Q(subscription__status__in=['active', 'past_due']),
                distinct=True,
            ),
            popularity=ExpressionWrapper(
                F('total_orders') * Value(weight_orders) + F('total_subscriptions') * Value(weight_subscriptions),
                output_field=IntegerField()
            )
        )

    def annotate_customer_status(self, customer):
        """
        Annotates each product with:
        - `user_owns`: If the user has a non-refunded order with remaining quantity.
        - `active_subscription`: If the subscription status is `active` or is `past_due` with a retry pending.
        """
        from .models import OrderItem, Subscription

        return self.annotate(
            # If the user has a non-refunded order with remaining quantity
            user_owns=Exists(
                OrderItem.objects.filter(
                    product=OuterRef('pk'),
                    order__customer=customer,
                    order__complete=True,
                    refunded=False,
                )
            ),
            # If the user has an active subscription to the product
            active_subscription=Exists(
                Subscription.objects.filter(
                    customer=customer,
                    product=OuterRef('pk'),
                ).filter(
                    Q(status='active') | Q(status='past_due', next_payment_attempt__isnull=False)
                )
            )
        )


class ProductManager(models.Manager.from_queryset(ProductQuerySet)):  # StripeManager):
    def filter_customer_store(self, customer, weight_orders=1, weight_subscriptions=2):
        """
        Returns a queryset of products annotated with various information relevant to the customer.

        Annotates each product with:
        - `amount_dollars`: the current price in dollars
        - `amount_cents`: the current price in cents

        - `total_orders`: the count of completed, non-refunded orders.
        - `total_subscriptions`: the count of active or grace-period subscriptions.
        - `popularity`: a weighted sum of orders and subscriptions, calculated as

        - `user_owns`: If the user has a non-refunded order with remaining quantity.
        - `active_subscription`: If the subscription status is `active` or is `past_due` with a retry pending.
        """
        from .models import Price

        product_price_subquery = Price.objects.filter(
            product=OuterRef('pk'),
            active=True
        ).order_by('-created_at').values('amount')[:1]

        return (
            self.get_queryset()
            .prefetch_related('prices', 'tags')
            .filter(Exists(product_price_subquery))
            .annotate(
                amount_dollars=Subquery(product_price_subquery)
            )
            .annotate(
                amount_cents=ExpressionWrapper(
                    F('amount_dollars') * Value(100.0),
                    output_field=IntegerField()
                ),
            )
            .annotate_popularity(weight_orders=weight_orders, weight_subscriptions=weight_subscriptions)
            .annotate_customer_status(customer)
        )

    def filter_customer_store_owned(self, customer):
        """
        Returns a queryset of products owned/non-refunded or actively subscribed to by the given customer.

        A product is considered:
        - Owned if the customer has a completed, non-refunded order for it.
        - Subscribed if the status is `active` or is `past_due` with a retry pending.

        Use annotations to denote whether a subscription or ownership exists:
        - `user_owns`: If the user has a non-refunded order with remaining quantity.
        - `active_subscription`: If the subscription status is `active` or is `past_due` with a retry pending.
        """
        return (
            self.get_queryset()
            .annotate_customer_status(customer=customer)
            .filter(Q(user_owns=True) | Q(active_subscription=True))
        )


class PriceManager(StripeManager):
    pass


class OrderItemManager(models.Manager):
    def filter_customer_items(self, customer):
        """
        Returns a queryset of OrderItems owned by the specified customer.
        - if the item is a single purchase only, the total quantity should equal 1.
        - multi-purchase/consumable items should have a quantity greater than or equal to 1.
        """
        from .models import OrderItem

        # Get total quantity of a users purchase of each specific product
        product_quantity_subquery = (
            OrderItem.objects
            .filter(
                product=OuterRef('product'),
                refunded=False,
                order__complete=True,
                order__customer=customer,
            )
            .values('product')
            .annotate(total_quantity=Sum('quantity'))
            .values('total_quantity')[:1]
        )

        return (
            self.filter(
                refunded=False,
                order__complete=True,
                order__customer=customer,
            )
            .annotate(total_quantity=Subquery(product_quantity_subquery, output_field=IntegerField()))
            .filter(
                Q(product__single_purchase_only=True, total_quantity=1) |
                Q(product__single_purchase_only=False, total_quantity__gte=1)
            )
        )

    def get_cart(self, customer):
        return self.filter(
            order__customer=customer,
            order__complete=False
        )


class SubscriptionManager(StripeManager):
    def get_active_subscriptions(self, customer):
        """
        Returns a queryset of active subscriptions for the specified user.
        """
        return self.filter(
            customer=customer,
        ).filter(
            Q(status='active') |
            Q(status='past_due', next_payment_attempt__isnull=False)  # Grace period still active
        )
