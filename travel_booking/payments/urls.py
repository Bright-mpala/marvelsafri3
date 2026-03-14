from django.urls import path
from . import views

app_name = 'payments'

urlpatterns = [
    path('', views.payment_list, name='payment_list'),
    path('bookings/<uuid:booking_id>/checkout/', views.booking_checkout, name='booking_checkout'),
    path(
        'bookings/<uuid:booking_id>/checkout/stripe/success/',
        views.stripe_checkout_success,
        name='stripe_checkout_success',
    ),
    path(
        'bookings/<uuid:booking_id>/checkout/stripe/cancel/',
        views.stripe_checkout_cancel,
        name='stripe_checkout_cancel',
    ),
    path('stripe/webhook/', views.stripe_webhook, name='stripe_webhook'),
    path(
        'bookings/<uuid:booking_id>/checkout/paynow/return/',
        views.paynow_checkout_return,
        name='paynow_checkout_return',
    ),
    path('paynow/result/', views.paynow_result, name='paynow_result'),
]
