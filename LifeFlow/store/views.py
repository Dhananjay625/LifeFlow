# store/views.py

from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.db.models import (
    Prefetch,
    Exists,
    BooleanField,
    Value,
    When,
    Case,
    OuterRef,
    Q,
)
from django.http import JsonResponse, HttpResponse
from django.shortcuts import get_object_or_404, render, redirect
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.timezone import now
from django.views.decorators.http import require_POST

from .decorators import attach_customer
from .models import (
    Product,
    ProductTag,
    Price,
    Order,
    OrderItem,
    Subscription,
)

# ---- Stripe optionality ------------------------------------------------------
PAID_MODE: bool = getattr(settings, "APPSTORE_PAID_MODE", False)

stripe = None  # type: ignore[assignment]
if PAID_MODE:
    try:
        import stripe as _stripe  # type: ignore
        _stripe.api_key = getattr(settings, "STRIPE_SECRET_KEY", "")
        stripe = _stripe
    except Exception:
        # If Stripe import or keys fail, disable paid mode gracefully
        PAID_MODE = False
        stripe = None

EMAIL_HOST_USER = getattr(settings, "EMAIL_HOST_USER", "no-reply@lifeflow.local")
CUSTOMER_SERVICE_EMAIL = getattr(settings, "CUSTOMER_SERVICE_EMAIL", "support@lifeflow.local")


# =============================================================================
# Storefront
# =============================================================================

@attach_customer
def store(request):
    """
    Displays the main store page with sorting, filtering, and search.
    """
    search_query = request.GET.get("search", "")
    min_price = max(int(request.GET.get("min-price") or 0), 0)
    max_price = max(int(request.GET.get("max-price") or 0), 0)
    sort_order = request.GET.get("sort", "popular")  # popular, asc, desc
    filter_tags = [tag for tag in request.GET.get("tags", "").split(",") if tag.isdigit()]

    # Base queryset
    products = Product.objects.filter_customer_store(request.customer)

    # Sorting
    if sort_order == "desc":
        products = products.order_by("-latest_price")
    elif sort_order == "asc":
        products = products.order_by("latest_price")
    else:  # "popular" default
        products = products.order_by("-popularity")

    # Search
    if search_query:
        products = products.filter(name__icontains=search_query)

    # Price range
    if min_price > 0:
        products = products.filter(amount_dollars__gte=min_price)
    if max_price > min_price:
        products = products.filter(amount_dollars__lte=max_price)

    # Tags
    if filter_tags:
        products = products.filter(tags__in=filter_tags).distinct()

    # Small cart preview (if your manager exists), else empty
    try:
        shopping_cart = OrderItem.objects.get_cart(customer=request.customer)
    except Exception:
        shopping_cart = OrderItem.objects.none()

    context = {
        "products": products,
        "sort_order": sort_order,
        "search_query": search_query,
        "min_price": min_price or None,
        "max_price": max_price or None,
        "selected_tags": filter_tags,
        "shopping_cart": shopping_cart,
        "tags": ProductTag.objects.all(),
        "paid_mode": PAID_MODE,
    }
    return render(request, "store/store.html", context)


@attach_customer
def product_detail(request, pk: str):
    """
    Single product page with similar items sharing at least one tag.
    """
    product = get_object_or_404(Product, pk=pk)

    similar_products = (
        Product.objects
        .prefetch_related("tags")
        .filter(tags__in=product.tags.all())
        .exclude(pk=product.pk)
        .distinct()
        .annotate_popularity()
        .order_by("-popularity")[:5]
    )

    return render(
        request,
        "store/product_details.html",
        {"product": product, "similar_products": similar_products, "paid_mode": PAID_MODE},
    )


# =============================================================================
# Cart
# =============================================================================

@attach_customer
def cart(request):
    """
    Display the user's shopping cart with items and totals.
    """
    # Incomplete order for this customer
    order = (
        Order.objects
        .filter(customer=request.customer, complete=False)
        .prefetch_related(
            Prefetch(
                "items",
                queryset=OrderItem.objects.select_related("product", "price").prefetch_related("product__tags"),
            )
        )
        .first()
    )

    if order:
        items = list(order.items.all())
        total_items = order.total_items
        total_price = order.total_price
    else:
        items = []
        total_items = 0
        total_price = 0

    context = {
        "order": order,
        "items": items,
        "total_items": total_items,
        "total_price": total_price,
        "paid_mode": PAID_MODE,
    }
    return render(request, "store/cart.html", context)


@require_POST
@attach_customer
def update_cart(request):
    """
    AJAX updates to add/subtract/remove items in cart.
    """
    action = request.POST.get("action")
    product_id = request.POST.get("product_id")
    quantity = int(request.POST.get("quantity", 1))

    if not product_id:
        return JsonResponse({"error": "Missing product_id"}, status=400)

    order, _ = Order.objects.get_or_create(customer=request.customer, complete=False)
    product = get_object_or_404(Product, id=product_id)
    price = product.get_current_price()

    order_item, created = OrderItem.objects.get_or_create(
        order=order,
        product=product,
        price=price,
    )

    if product.single_purchase_only and not created and action in {"add", "sub"}:
        return JsonResponse({"error": "This product can only be purchased once."}, status=400)

    if action == "add":
        order_item.quantity += quantity
    elif action == "sub":
        order_item.quantity -= quantity
    elif action == "rem":
        order_item.quantity = 0

    if order_item.quantity <= 0:
        order_item.delete()
        html = ""
    else:
        order_item.save(update_fields=["quantity"])
        html = render_to_string("store/cart_small_item.html", {"order_item": order_item})

    return JsonResponse({"id": product.id, "html": html})


@attach_customer
def cart_quantity(request):
    """
    Returns total cart item count for header badge.
    """
    total_quantity = 0
    if request.user.is_authenticated:
        order = Order.objects.filter(customer=request.customer, complete=False).first()
        if order:
            total_quantity = order.total_items
    return JsonResponse({"total_quantity": total_quantity})


# =============================================================================
# Checkout (Stripe guarded)
# =============================================================================

@attach_customer
def checkout(request):
    """
    Start a Stripe Checkout Session (if PAID_MODE), otherwise show a friendly message.
    """
    if not request.user.is_authenticated:
        return redirect(f"{reverse('account_login')}?next={request.get_full_path()}")

    if not PAID_MODE or not stripe:
        return render(
            request,
            "store/checkout.html",
            {"paid_mode": False, "message": "Payments are disabled in this environment."},
            status=200,
        )

    order = Order.objects.filter(customer__user=request.user, complete=False).first()
    if not order:
        return redirect("store:cart")

    metadata = {"order_id": str(order.id)}
    line_items = [{"price": it.amount.stripe_price_id, "quantity": it.quantity} for it in order.items.all()]
    for it in order.items.all():
        metadata[f"order_item__{it.product.id}"] = str(it.id)

    checkout_session = stripe.checkout.Session.create(  # type: ignore[attr-defined]
        customer=request.customer.stripe_customer_id,
        payment_method_types=["card"],
        mode="payment",
        line_items=line_items,
        metadata=metadata,
        success_url=f"{settings.SITE_URL}{reverse('store:payment_successful')}?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{settings.SITE_URL}{reverse('store:payment_canceled')}?order_id={order.id}",
    )

    order.stripe_checkout_session_id = checkout_session.id
    order.save(update_fields=["stripe_checkout_session_id"])

    return redirect(checkout_session.url, code=303)


@attach_customer
def subscribe_checkout(request):
    """
    Start a subscription checkout (Stripe), or show disabled page when PAID_MODE is False.
    """
    if not request.user.is_authenticated:
        return redirect(f"{reverse('account_login')}?next={request.get_full_path()}")

    if not PAID_MODE or not stripe:
        return render(
            request,
            "store/checkout.html",
            {"paid_mode": False, "message": "Subscriptions are disabled in this environment."},
            status=200,
        )

    price_id = request.GET.get("price_id")
    product_id = request.GET.get("product_id")
    price = get_object_or_404(Price, id=price_id, product_id=product_id, is_subscription=True)

    checkout_session = stripe.checkout.Session.create(  # type: ignore[attr-defined]
        customer=request.customer.stripe_customer_id,
        payment_method_types=["card"],
        mode="subscription",
        line_items=[{"price": price.stripe_price_id, "quantity": 1}],
        metadata={
            "stripe_product_id": price.product.stripe_product_id,
            "stripe_price_id": price.stripe_price_id,
        },
        success_url=f"{settings.SITE_URL}{reverse('store:payment_successful')}?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{settings.SITE_URL}{reverse('store:payment_canceled')}",
    )

    return redirect(checkout_session.url, code=303)


# =============================================================================
# Order / Subscription history
# =============================================================================

@attach_customer
def order_history(request):
    """
    Completed orders and subscriptions for the current customer.
    """
    seven_days_ago = now() - timedelta(days=7)

    orders = (
        Order.objects
        .filter(customer=request.customer, complete=True)
        .prefetch_related("items", "items__product", "items__price")
        .annotate(
            has_unrefunded_items=Exists(
                OrderItem.objects.filter(order=OuterRef("pk"), refunded=False)
            ),
            can_refund=Case(
                When(created_at__gte=seven_days_ago, has_unrefunded_items=True, then=Value(True)),
                default=Value(False),
                output_field=BooleanField(),
            ),
        )
        .order_by("-created_at")
    )

    subscriptions = (
        Subscription.objects
        .filter(customer=request.customer)
        .annotate(
            is_sub_active=Exists(
                Subscription.objects.filter(
                    Q(status="active") | Q(status="past_due", next_payment_attempt__isnull=False)
                )
            ),
            can_refund=Case(
                When(current_period_start__gte=seven_days_ago, status="active", then=Value(True)),
                default=Value(False),
                output_field=BooleanField(),
            ),
        )
        .select_related("product", "price")
        .order_by("is_sub_active", "-created_at")
    )

    return render(
        request,
        "store/order_history.html",
        {"orders": orders, "subscriptions": subscriptions, "paid_mode": PAID_MODE},
    )


@attach_customer
def history_subscription(request):
    """
    Stubbed actions on a subscription (refund/cancel/retry) — expand as needed.
    """
    subscription_id = request.POST.get("id")
    action = request.POST.get("action")

    subscription = Subscription.objects.filter(
        customer=request.customer,
        stripe_subscription_id=f"sub_{subscription_id}",
    ).first()

    if not subscription:
        return JsonResponse({"error": "Subscription not found."}, status=404)

    # TODO: implement real logic if/when PAID_MODE is True
    return JsonResponse({"status": "ok", "action": action})


@attach_customer
def history_order(request):
    """
    Stubbed actions on an order (refund/retry) — expand as needed.
    """
    order_number = request.POST.get("id")
    action = request.POST.get("action")

    order = Order.objects.filter(customer=request.customer, order_number=order_number, complete=True).first()
    if not order:
        return JsonResponse({"error": "Order not found."}, status=404)

    # TODO: implement real logic if/when PAID_MODE is True
    return JsonResponse({"status": "ok", "action": action})


@attach_customer
def history_order_item(request):
    """
    Stubbed actions on a single order item — expand as needed.
    """
    order_item_id = request.POST.get("id")
    order_number = request.POST.get("order")
    action = request.POST.get("action")

    order_item = OrderItem.objects.filter(
        id=order_item_id,
        order__customer=request.customer,
        order__order_number=order_number,
        order__complete=True,
        refunded=False,
        quantity__gte=1,
    ).first()

    if not order_item:
        return JsonResponse({"error": "Item not found."}, status=404)

    # TODO: implement real logic if/when PAID_MODE is True
    return JsonResponse({"status": "ok", "action": action})


# =============================================================================
# Payment result pages
# =============================================================================

@attach_customer
def payment_successful(request):
    """
    Stripe success target. In non-paid mode, show a generic success page.
    """
    if not PAID_MODE or not stripe:
        return render(
            request,
            "store/payment_successful.html",
            {"customer": request.customer, "user": request.user, "paid_mode": False},
        )

    session_id = request.GET.get("session_id")
    session = stripe.checkout.Session.retrieve(session_id)  # type: ignore[attr-defined]
    ctx = {**(session.metadata or {}), "customer": request.customer, "user": request.user, "paid_mode": True}
    return render(request, "store/payment_successful.html", ctx)


@attach_customer
def payment_canceled(request):
    """
    Stripe cancel target. In non-paid mode, show a generic canceled page.
    """
    order_id = request.GET.get("order_id")
    order = Order.objects.filter(customer=request.customer, id=order_id).first()

    return render(
        request,
        "store/payment_canceled.html",
        {"user": request.user, "customer": request.customer, "order": order, "paid_mode": PAID_MODE},
    )


# =============================================================================
# Cancel subscription (simple API)
# =============================================================================

@require_POST
@attach_customer
def cancel_subscription(request):
    """
    Mark a subscription to cancel at period end (data-model only, no Stripe required).
    """
    product_id = request.POST.get("product_id")
    if not product_id:
        return HttpResponse("Missing product_id", status=400)

    subscription = (
        Subscription.objects
        .get_active_subscriptions(request.customer)
        .filter(product_id=product_id)
        .first()
    )

    if not subscription:
        return JsonResponse({"status": "error", "message": "Subscription not found."}, status=404)

    try:
        # If your model exposes a helper, use it; else toggle the flag directly.
        if hasattr(subscription, "trigger_cancel"):
            subscription.trigger_cancel(at_period_end=True)
        else:
            subscription.cancel_at_period_end = True
            subscription.save(update_fields=["cancel_at_period_end"])
        return JsonResponse({"status": "ok", "message": "Subscription will cancel at period end."})
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)
