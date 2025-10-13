# Store Component



This document provides setup instructions specifically for the store component of the platform.

## Project Structure

```
project_root/
├── requirements.txt
├── README.md
└── web/
    └── store/  # store is inside web directory
        ├── management/
        │   └── commands/
        │       ├── stripe_listen.py  # Starts the stripe webhook
        ├── migrations/
        ├── static/
        │   └── store/
        │       ├── images/
        │       ├── css/
        │       └── js/
        ├── templates/
        │   └── store/
        │       ├── cart.html
        │       ├── cart_small.html  # Small cart on the right side of the store page
        │       ├── cart_small_item.html  # HTML for an individual cart item
        │       ├── checkout.html
        │       ├── email_payment_successful.html
        │       ├── order_history.html
        │       ├── payment_cancelled.html
        │       ├── payment_successful.html
        │       ├── product_details.html
        │       └── store.html  # Main store page
        ├── __init__.py
        ├── admin.py
        ├── apps.py
        ├── decorators.py  # Decorator methods for checking subscription/purchase permissions
        ├── forms.py
        ├── managers.py    # Additional queryset methods
        ├── models.py
        ├── README.md      # This README file should be placed here
        ├── signals.py     # For certain model callbacks
        ├── tasks.py       # Celery tasks, e.g., canceling expired subscriptions
        ├── urls.py
        └── views.py
        └── webhooks.py    # Stripe webhook (handles messages from stripe)
```

## Contents

* [Stripe Integration](#stripe-integration)
* [Stripe Webhook Setup](#stripe-webhook-setup)
* [Creating/Managing Products](#creatingmanaging-products)
* [Testing the Store](#testing-the-store)
* [Troubleshooting](#troubleshooting)

## Required: Stripe Webhook Setup

The store a payment management service called [Stripe](https://stripe.com/au) for payment processing. 

The stripe webhook **MUST** be active in order for any store functionality to work as intended as the majority of 
database operations happen as a result of event messages that come directly from stripe in order to keep them in sync.

1. The following API keys are to be placed in your `.env` file. They can be acquired from the [Stripe Dashboard](https://dashboard.stripe.com): 
   ```python
   STRIPE_PUBLIC_KEY = "GET_THIS_FROM_STRIPE"  # Publishable key
   STRIPE_SECRET_KEY = "GET_THIS_FROM_STRIPE"  # Secret key
   ```
2. Install the [Stripe CLI](https://stripe.com/docs/stripe-cli)
3. Login to your Stripe account: `stripe login`
4. Start local stripe webhook: `python manage.py stripe_listen`   
   
   
**Note:** For deployment, the webhook should be set up on the stripe development console on their website. 


## Creating/Managing Products

1. Visit the admin dashboard; [127.0.0.1:8000/admin](127.0.0.1:8000/admin)
2. Scroll to `STORE` > `Products`
3. Use "Add Product" button on top right of screen
4. Fill all boxes, new tags can also be created.
   - Readonly fields are populated by event messages sent from Stripe.
   - Tags are used for search functions and for showing related products to the user.
5. Prices can be set-up for single purchase or subscription.
   - **IMPORTANT** Price objects may not be modified or deleted upon creation only disabled! 
   - Having no `active` price means the product is unavailable in the store.
   - Subscriptions need a billing interval. 
   - Historical prices are also saved here. 
6. Press the "Save" button at the bottom to submit changes 

## Managing Prices

- Price objects cannot be modified once created, except the `Active` field. This is to ensure data 

## Testing the Store

1. Ensure your Django server is running: `python manage.py runserver`
2. Visit http://127.0.0.1:8000/store/
3. Browse products, add items to cart, and proceed to checkout
4. For test payments, you can use Stripe's [test card numbers](https://docs.stripe.com/testing) e.g.:
   * Card Number: `4242 4242 4242 4242`
   * Expiry: Any future date
   * CVC: Any 3 digits
   * ZIP: Any 5 digits

## Subscription/Ownership Views

To expect a users subscription/ownership of a product to limit access to a portion of the website, the view decorators
within `store.decorators` can be used. 

Requires that you create a product and get the product ID manually.

```
@require_user_is_subscribed("prod_12341234")
def some_view(request):
   # This view requires that the request.user 
   # has a subscription for the product 'prod_12341234'
   ...
```

_TODO: Think of a better way to do the ID stuff. So it can be managed at the database level_ 

## Troubleshooting

### Common Issues

1. **Products not appearing in store**
   * Check that the product has an active price on admin dashboard: [127.0.0.1:8000/admin](127.0.0.1:8000/admin)
2. **Payment/Stripe processing errors**
   * Check that valid `STRIPE_PUBLIC_KEY` and `STRIPE_SECRET_KEY` are set up in `.env`
   * Ensure webhook has been started `python manage.py stripe_listen`. Database only updates from stripe messages
3. **Image loading issues**
   * Verify media settings in settings.py
   * Check file permissions on product image directories
