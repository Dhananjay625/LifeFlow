from django.contrib import admin
from django.utils.safestring import mark_safe

from .forms import PriceAdminForm
from .models import *


def get_fields_except(model, fields):
    """Returns an inverted list of a models fields."""
    return [field.name for field in model._meta.get_fields() if field.name not in fields]


class OrderInline(admin.TabularInline):
    model = Order
    extra = 0
    can_delete = False
    fields = (
        'customer',
        'complete',
        'stripe_checkout_session_id',
        'stripe_payment_intent_id',
        'receipt_url',
        'order_number',
        'created_at',
        'updated_at',
    )
    readonly_fields = (
        'customer',
        'complete',
        'stripe_checkout_session_id',
        'stripe_payment_intent_id',
        'receipt_url',
        'order_number',
        'created_at',
        'updated_at',
    )


class SubscriptionInline(admin.TabularInline):
    model = Subscription
    extra = 0
    can_delete = False
    fields = (
        'product',
        'customer',
        'stripe_subscription_id',
        'price',
        'status',
        'current_period_end',
        'next_payment_attempt',
        'attempt_count',
    )
    readonly_fields = (
        'customer',
        'product',
        'price',
        'status',
        'stripe_subscription_id',
        'current_period_end',
        'next_payment_attempt',
        'attempt_count',
    )


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ('email', 'stripe_customer_id', 'user')
    search_fields = ('user__username', 'email', 'name', 'stripe_customer_id')
    inlines = [OrderInline, SubscriptionInline]


@admin.register(ProductTag)
class ProductTagAdmin(admin.ModelAdmin):
    list_display = ('name', 'created_at')
    search_fields = ('name',)


class PriceInline(admin.TabularInline):
    model = Price
    extra = 0
    fields = (
        'active', 'amount',
        'is_subscription', 'billing_interval',
        'stripe_price_id',
        'created_at', 'updated_at',
    )
    readonly_fields = [
        'stripe_price_id', 'created_at', 'updated_at'
    ]

    def get_formset(self, request, obj=None, **kwargs):
        """
        Override formset to set per-instance readonly fields.
        """
        formset = super().get_formset(request, obj, **kwargs)

        class WrappedFormset(formset):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                for form in self.forms:
                    if form.instance.stripe_price_id:  # Existing object
                        for field_name in ('amount', 'is_subscription', 'billing_interval'):
                            if field_name in form.fields:
                                form.fields[field_name].disabled = True

        return WrappedFormset

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'stripe_product_id', 'description', 'single_purchase_only', 'created_at', 'updated_at')
    search_fields = ('id', 'name', 'description', 'stripe_product_id')
    list_filter = ('tags', 'single_purchase_only')
    inlines = [PriceInline]
    filter_horizontal = ('tags',)
    readonly_fields = ('created_at', 'updated_at', 'stripe_product_id')

    fieldsets = (
        ('Identifiers', {
            'fields': ('id', 'stripe_product_id',)
        }),
        ('Information', {
            'description': "This information will be available to the user",
            'fields': ('name', 'description', 'long_description', 'thumbnail', 'icon',)
        }),
        ('', {
            'fields': ('url', 'single_purchase_only'),
        }),
        ('', {
            'fields': ('created_at', 'updated_at'),
        }),
    )

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    def get_readonly_fields(self, request, obj=None):
        defaults = ['stripe_product_id', 'created_at', 'updated_at']
        if obj:
            defaults.append('id')
        return defaults


@admin.register(Price)
class PriceAdmin(admin.ModelAdmin):
    form = PriceAdminForm
    description = ""
    list_display = ('product', 'amount', 'stripe_price_id', 'active', 'is_subscription', 'billing_interval', 'created_at')
    list_filter = ('is_subscription', 'billing_interval', 'product')
    search_fields = ('product__name', 'stripe_price_id')

    fieldsets = (
        ('Status', {
            "description": "Whether this price is available for use for the associated product. This is synced with "
                           "Stripe.",
            'fields': ('active',)
        }),
        ('Most fields cannot be edited after creation. Stripe relies on consistency. Create a new price and deactivate this one if required.', {
            'fields': ('product', 'amount', 'is_subscription', 'billing_interval', 'stripe_price_id', 'created_at', 'updated_at'),
        }),
    )

    def get_readonly_fields(self, request, obj=None):
        if obj:
            return get_fields_except(Price, ['active'])
        return ('stripe_price_id', 'created_at', 'updated_at',)

    def save_model(self, request, obj, form, change):
        # Ensure product exists on Stripe first
        if not obj.product.stripe_product_id:
            obj.product.save(update_stripe=True)
        super().save_model(request, obj, form, change)

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    autocomplete_fields = ('product', 'price',)


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('order_number', 'customer', 'complete', 'created_at', 'updated_at')
    list_filter = ('complete',)
    search_fields = ('customer__user__username', 'order_number', 'stripe_checkout_session_id', 'stripe_payment_intent_id', 'stripe_charge_id')
    inlines = [OrderItemInline]
    readonly_fields = [
        'stripe_checkout_session_id', 'stripe_payment_intent_id', 'stripe_charge_id', 'receipt_url',
        'created_at', 'updated_at', 'complete',
    ]

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None) -> bool:
        return request.user.is_superuser


@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    list_display = ('order', 'product', 'price', 'quantity', 'added_at', 'total_price')
    search_fields = ('order__id', 'product__name')
    autocomplete_fields = ('order', 'product', 'price')
    readonly_fields = ('refunded', 'added_at', 'refunded_at')

    def has_delete_permission(self, request, obj=None):
        return False

    def get_readonly_fields(self, request, obj=None):
        if obj and obj.order.complete:
            return get_fields_except(OrderItem, [])

        return get_fields_except(OrderItem, ['added_at'])


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ('stripe_subscription_id', 'product', 'customer', 'price', 'status', 'current_period_start', 'current_period_end')
    list_filter = ('status',)
    autocomplete_fields = ('product', 'customer', 'price')
    search_fields = ('customer__user__username', 'product__name', 'stripe_subscription_id')

    fieldsets = (
        (None, {
            "fields": ('product', 'customer', 'price'),
        }),
        ("Stripe Status", {
            "description": "These fields are populated by stripe",
            "fields": ('stripe_subscription_id', 'status', 'current_period_start', 'current_period_end'),
        }),
        ("Payment Status", {
            "description": "These fields are populated by stripe",
            "fields": ('attempt_count', 'next_payment_attempt', 'latest_stripe_invoice_id',),
        }),
        ("Cancellation Status", {
            "description": "These fields are populated by stripe",
            "fields": ('cancel_at_period_end', 'cancel_at', 'canceled_at', 'ended_at',),
        }),
        (None, {
            "fields": ('created_at', 'updated_at'),
        })
    )

    def get_readonly_fields(self, request, obj=None):
        if obj:
            return get_fields_except(Subscription, ['cancel_at_period_end'])
        return get_fields_except(Subscription, ['product', 'customer', 'price', 'cancel_at_period_end'])

    def save_model(self, request, obj, form, change):
        try:
            # The purpose of this override is that the page must wait for the Stripe request to be completed,
            # inject some javascript to reload the page after 2 seconds (which should be enough time) for the
            # local database to be updated. (with stripe ID etc.)
            super().save_model(request, obj, form, change)
            self.message_user(
                request,
                mark_safe("Subscription updating on Stripe... <script>setTimeout(() => location.reload(), 2000);</script>"),
                level='INFO',
            )
        except AttributeError as e:
            self.message_user(request, e, level='error')
        except stripe.error.StripeError as e:
            self.message_user(request, f"Stripe error: {e}", level='error')

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


# class SubscriptionUtilsAdmin(admin.ModelAdmin):
#     change_list_template = "admin/subscription_utils_changelist.html"
#
#     def get_urls(self):
#         urls = super().get_urls()
#         custom_urls = [
#             path('run-subscription-check/', self.admin_site.admin_view(self.run_subscription_check))
#         ]
#         return custom_urls + urls
#
#     def run_subscription_check(self, request):
#         check_expired_subscriptions.delay()
#         self.message_user(request, "Subscription expiration check task has been triggered.", messages.SUCCESS)
#         return HttpResponseRedirect("../")
#
#
# class SubscriptionUtils(models.Model):
#     class Meta:
#         verbose_name_plural = "Subscription Utilities"
#         managed = False
#
#
# admin.site.register(SubscriptionUtils, SubscriptionUtilsAdmin)
