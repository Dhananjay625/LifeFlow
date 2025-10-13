from django.contrib import admin
from django.urls import path
from . import views
from . import webhooks

app_name = 'store'

urlpatterns = [
    # Storefront
    path('', views.store, name='store'),
    path("products/<slug:pk>/", views.product_detail, name="product_detail"),

    # Cart and Checkout
    path('cart/', views.cart, name='cart'),
    path('checkout/', views.checkout, name='checkout'),
    path('subscribe/', views.subscribe_checkout, name='subscribe_checkout'),
    path('update_cart/', views.update_cart, name='update_cart'),
    path('cart_quantity/', views.cart_quantity, name='cart_quantity'),

    # Order and Payment
    path('success/', views.payment_successful, name='payment_successful'),
    path('canceled/', views.payment_canceled, name='payment_canceled'),

    # Order history management
    path('history/', views.order_history, name='order_history'),
    path('history/subscription', views.history_subscription, name='history_subscription'),
    path('history/order', views.history_order, name='history_order'),
    path('history/item', views.history_order_item, name='history_item'),

    # Stripe Webhook endpoint
    path('stripe/webhook/', webhooks.stripe_webhook, name='webhook'),

    # Admin pages
    # path('admin/prices_for_product/<int:product_id>/',
    #      admin.site.admin_view(views.prices_for_product),
    #      name="admin_prices_for_product"
    # ),
]
