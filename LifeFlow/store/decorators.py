from functools import wraps
from urllib.parse import urlencode

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, get_object_or_404
from django.conf import settings
from django.urls import reverse

from .models import Customer, Subscription, Product


def attach_customer(view_func):
    """
    Attaches the users associated Customer object to the request via `request.customer`.
    If one does not yet exist it is created both locally and on Stripe.
    """
    @login_required
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        request.customer, _ = Customer.objects.get_or_create(user=request.user)

        return view_func(request, *args, **kwargs)
    return _wrapped_view


def get_store_view(product):
    url = reverse('store:store')
    query_params = {'search': product.name}
    full_url = f"{url}?{urlencode(query_params)}"
    return redirect(full_url)


def require_user_is_subscribed(product_id, redirect_url=None):
    """
    Ensures the user has an active subscription to the given `app_code` stored in ProductApp table.
    Redirects to the store view or custom URL if not subscribed.
    """
    def decorator(view_func):
        @login_required
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            customer, _ = Customer.objects.get_or_create(user=request.user)
            subscription = (
                Subscription.objects
                .get_active_subscriptions(customer)
                .filter(product_id=product_id)
                .first()
            )

            if subscription:
                request.customer = customer
                request.subscription = subscription
                return view_func(request, *args, **kwargs)

            # Not subscribed, get product and redirect appropriately
            product = get_object_or_404(Product, id=product_id)

            return redirect(redirect_url) if redirect_url else get_store_view(product)

        return _wrapped_view
    return decorator


# def require_user_is_subscribed(stripe_product_id, redirect_url=None):
#     """
#     Ensures the user has an active subscription to the given stripe_product_id.
#     If not, redirects to the given redirect_url or the product's own URL.
#
#     Developer Notes:
#
#     If you do not know the `stripe_product_id` for your product, either check the local database,
#     or ask the administrator for the stripe account.
#     """
#     def decorator(view_func):
#         @login_required
#         @wraps(view_func)
#         def _wrapped_view(request, *args, **kwargs):
#             customer, _ = Customer.objects.get_or_create(user=request.user)
#             subscription = Subscription.objects.get_active_subscriptions(customer).filter(
#                 product__stripe_product_id=stripe_product_id,
#             ).first()
#
#             if subscription:
#                 request.customer = customer
#                 request.subscription = subscription
#                 return view_func(request, *args, **kwargs)
#
#             # Not subscribed, get product and redirect appropriately
#             product = get_object_or_404(Product, stripe_product_id=stripe_product_id)
#
#             return redirect(redirect_url) if redirect_url else get_store_view(product)
#
#         return _wrapped_view
#     return decorator
#
#
# def require_user_owns_product(stripe_product_id, redirect_url=None):
#     """
#     Ensures the user owns the product with the given stripe_product_id.
#     If not, redirects to the given redirect_url or the product's own URL.
#
#     Developer Notes:
#
#     If you do not know the `stripe_product_id` for your product, either check the local database,
#     or ask the administrator for the stripe account.
#     """
#     def decorator(view_func):
#         @login_required
#         @wraps(view_func)
#         def _wrapped_view(request, *args, **kwargs):
#             customer, _ = Customer.objects.get_or_create(user=request.user)
#             owned_product = Product.objects.filter_customer_store_owned(customer).filter(
#                 stripe_product_id=stripe_product_id,
#             ).first()
#
#             if owned_product:
#                 request.customer = customer
#                 request.product = owned_product
#                 return view_func(request, *args, **kwargs)
#
#             # Not owned, get product and redirect appropriately
#             product = get_object_or_404(Product, stripe_product_id=stripe_product_id)
#
#             return redirect(redirect_url) if redirect_url else get_store_view(product)
#
#         return _wrapped_view
#
#     return decorator



