import json
import logging
import uuid
from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.mail import send_mail
from django.db import transaction as db_transaction
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.utils.translation import gettext_lazy as _
import stripe

from bookings.models import Booking
from .forms import BookingCheckoutForm
from .models import CommissionPayment, PaymentGateway, PayoutAccount, Transaction


logger = logging.getLogger(__name__)


def _get_or_create_checkout_gateway():
    """Return a default gateway used by in-platform checkout."""
    gateway, created = PaymentGateway.objects.get_or_create(
        name='Marvel Safari Secure Checkout',
        gateway_type='offline',
        defaults={
            'is_active': True,
            'is_test_mode': True,
            'supported_currencies': ['USD'],
        },
    )

    changed = False
    if not gateway.is_active:
        gateway.is_active = True
        changed = True
    if not gateway.supported_currencies:
        gateway.supported_currencies = ['USD']
        changed = True
    if changed:
        gateway.save(update_fields=['is_active', 'supported_currencies', 'updated_at'])

    return gateway


def _get_or_create_stripe_gateway():
    gateway, _ = PaymentGateway.objects.get_or_create(
        name='Stripe Hosted Checkout',
        gateway_type='stripe',
        defaults={
            'is_active': True,
            'is_test_mode': True,
            'supported_currencies': [getattr(settings, 'STRIPE_CURRENCY', 'USD').upper()],
        },
    )
    return gateway


def _get_or_create_paynow_gateway():
    gateway, _ = PaymentGateway.objects.get_or_create(
        name='Paynow Redirect Checkout',
        gateway_type='offline',
        defaults={
            'is_active': True,
            'is_test_mode': True,
            'supported_currencies': ['USD'],
        },
    )
    return gateway


def _is_stripe_card_checkout(selected_option):
    return (
        selected_option == Booking.PaymentOption.CARD
        and getattr(settings, 'STRIPE_ENABLED', False)
        and bool(getattr(settings, 'STRIPE_SECRET_KEY', ''))
    )


def _is_paynow_checkout(selected_option):
    return (
        selected_option == Booking.PaymentOption.PAYNOW
        and getattr(settings, 'PAYNOW_ENABLED', False)
        and bool(getattr(settings, 'PAYNOW_INTEGRATION_ID', ''))
        and bool(getattr(settings, 'PAYNOW_INTEGRATION_KEY', ''))
    )


def _can_complete_without_simulation(selected_option):
    if selected_option == Booking.PaymentOption.BANK_TRANSFER:
        return True
    if _is_stripe_card_checkout(selected_option):
        return True
    if _is_paynow_checkout(selected_option):
        return True
    return False


def _build_absolute_url(request, route_name, **kwargs):
    path = reverse(route_name, kwargs=kwargs)
    return request.build_absolute_uri(path)


def _to_minor_units(amount):
    cents = (Decimal(amount) * Decimal('100')).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
    return int(cents)


def _platform_fee_for_booking(booking):
    return (booking.commission_amount or Decimal('0.00')).quantize(Decimal('0.01'))


def _build_paynow_client(result_url, return_url):
    try:
        from paynow import Paynow
    except Exception as exc:
        raise RuntimeError('Paynow SDK is not installed. Install `paynow` package.') from exc

    return Paynow(
        integration_id=settings.PAYNOW_INTEGRATION_ID,
        integration_key=settings.PAYNOW_INTEGRATION_KEY,
        result_url=result_url,
        return_url=return_url,
    )


def _initiate_paynow_payment(request, booking, transaction_obj):
    result_url = _build_absolute_url(request, 'payments:paynow_result')
    return_url = _build_absolute_url(
        request,
        'payments:paynow_checkout_return',
        booking_id=booking.id,
    )
    paynow = _build_paynow_client(result_url=result_url, return_url=return_url)

    payment = paynow.create_payment(transaction_obj.transaction_reference, booking.user.email or '')
    listing_name = booking.property.name if booking.property else f'Booking {booking.id}'
    payment.add(f'Marvel Safari booking - {listing_name}', float(booking.total_amount))

    response = paynow.send(payment)
    if getattr(response, 'success', False):
        return {
            'success': True,
            'redirect_url': getattr(response, 'redirect_url', ''),
            'poll_url': getattr(response, 'poll_url', ''),
        }

    return {
        'success': False,
        'error': _('Paynow did not accept this payment request.'),
    }


def _create_stripe_checkout_session(request, booking, transaction_obj):
    stripe.api_key = settings.STRIPE_SECRET_KEY
    currency = getattr(settings, 'STRIPE_CURRENCY', 'USD').lower()

    success_base = _build_absolute_url(
        request,
        'payments:stripe_checkout_success',
        booking_id=booking.id,
    )
    success_url = f"{success_base}?session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = _build_absolute_url(
        request,
        'payments:stripe_checkout_cancel',
        booking_id=booking.id,
    )

    property_name = booking.property.name if booking.property else f'Booking {booking.id}'
    return stripe.checkout.Session.create(
        mode='payment',
        payment_method_types=['card'],
        line_items=[
            {
                'price_data': {
                    'currency': currency,
                    'product_data': {
                        'name': f'Marvel Safari booking - {property_name}',
                    },
                    'unit_amount': _to_minor_units(booking.total_amount),
                },
                'quantity': 1,
            }
        ],
        customer_email=booking.user.email or None,
        success_url=success_url,
        cancel_url=cancel_url,
        metadata={
            'booking_id': str(booking.id),
            'transaction_id': str(transaction_obj.id),
            'user_id': str(booking.user_id),
        },
    )


def _mark_booking_paid(booking):
    was_paid = booking.payment_status == Booking.PaymentStatus.PAID
    was_confirmed = booking.status == Booking.BookingStatus.CONFIRMED

    booking.payment_status = Booking.PaymentStatus.PAID
    if booking.status == Booking.BookingStatus.PENDING:
        booking.status = Booking.BookingStatus.CONFIRMED
    booking.save(update_fields=['payment_status', 'status', 'updated_at'])
    return not (was_paid and was_confirmed)


def _mark_booking_pending(booking):
    booking.payment_status = Booking.PaymentStatus.PENDING
    booking.save(update_fields=['payment_status', 'updated_at'])


def _complete_transaction(transaction_obj, gateway_response=None):
    now = timezone.now()
    transaction_obj.status = 'completed'
    transaction_obj.processed_at = now
    transaction_obj.settled_at = now
    if gateway_response:
        transaction_obj.gateway_response = gateway_response
    transaction_obj.save(update_fields=['status', 'processed_at', 'settled_at', 'gateway_response', 'updated_at'])


def _cancel_transaction(transaction_obj, gateway_response=None):
    transaction_obj.status = 'cancelled'
    if gateway_response:
        transaction_obj.gateway_response = gateway_response
    transaction_obj.save(update_fields=['status', 'gateway_response', 'updated_at'])


def _resolve_payout_recipient(booking):
    if booking.property and getattr(booking.property, 'owner', None):
        return booking.property.owner, 'property_owner'
    if booking.car and getattr(booking.car, 'owner', None):
        return booking.car.owner, 'car_rental_company'
    if booking.tour and getattr(booking.tour, 'property', None) and getattr(booking.tour.property, 'owner', None):
        return booking.tour.property.owner, 'tour_operator'
    return None, ''


def _ensure_commission_payment_record(booking, transaction_obj=None):
    recipient, recipient_type = _resolve_payout_recipient(booking)
    if not recipient:
        return None, False

    now_date = timezone.now().date()
    defaults = {
        'recipient_type': recipient_type or 'property_owner',
        'amount': booking.host_payout_amount or Decimal('0.00'),
        'currency': 'USD',
        'commission_rate': booking.commission_rate or Decimal('0.00'),
        'commission_amount': booking.commission_amount or Decimal('0.00'),
        'platform_fee': booking.commission_amount or Decimal('0.00'),
        'payment_method': 'bank_transfer',
        'payment_reference': transaction_obj.transaction_reference if transaction_obj else '',
        'transaction_id': transaction_obj.transaction_reference if transaction_obj else '',
        'status': 'processing',
        'due_date': now_date,
        'payment_date': now_date,
        'notes': 'Auto-generated after customer payment confirmation.',
    }
    commission_payment, created = CommissionPayment.objects.get_or_create(
        booking=booking,
        recipient=recipient,
        defaults=defaults,
    )

    if not created:
        changed_fields = []
        for field_name in (
            'recipient_type',
            'amount',
            'currency',
            'commission_rate',
            'commission_amount',
            'platform_fee',
            'due_date',
            'payment_date',
        ):
            new_value = defaults[field_name]
            if getattr(commission_payment, field_name) != new_value:
                setattr(commission_payment, field_name, new_value)
                changed_fields.append(field_name)

        if transaction_obj and commission_payment.transaction_id != transaction_obj.transaction_reference:
            commission_payment.transaction_id = transaction_obj.transaction_reference
            commission_payment.payment_reference = transaction_obj.transaction_reference
            changed_fields.extend(['transaction_id', 'payment_reference'])

        if commission_payment.status == 'pending':
            commission_payment.status = 'processing'
            changed_fields.append('status')

        if changed_fields:
            commission_payment.save(update_fields=changed_fields + ['updated_at'])

    return commission_payment, created


def _default_stripe_payout_account(user):
    if not user:
        return None
    return (
        PayoutAccount.objects.filter(
            user=user,
            account_type='stripe',
            is_default=True,
            is_verified=True,
            is_active=True,
        )
        .exclude(account_id='')
        .order_by('-updated_at')
        .first()
    )


def _execute_automatic_lister_payout(booking, commission_payment, transaction_obj=None):
    """
    Attempt Stripe Connect transfer for the lister payout.

    Returns:
    - True when payout is successfully disbursed
    - False when disbursement is not possible or fails
    """
    if not commission_payment:
        return False
    if not getattr(settings, 'AUTO_EXECUTE_LISTER_PAYOUTS', True):
        return False
    if commission_payment.amount <= Decimal('0.00'):
        return False
    if commission_payment.status == 'paid':
        return True
    if not transaction_obj or not transaction_obj.gateway or transaction_obj.gateway.gateway_type != 'stripe':
        return False
    if not getattr(settings, 'STRIPE_SECRET_KEY', ''):
        return False

    recipient, _recipient_type = _resolve_payout_recipient(booking)
    payout_account = _default_stripe_payout_account(recipient)
    if not payout_account:
        return False

    try:
        stripe.api_key = settings.STRIPE_SECRET_KEY
        transfer = stripe.Transfer.create(
            amount=_to_minor_units(commission_payment.amount),
            currency=(commission_payment.currency or 'USD').lower(),
            destination=payout_account.account_id,
            transfer_group=f'booking_{booking.id}',
            metadata={
                'booking_id': str(booking.id),
                'commission_payment_id': str(commission_payment.id),
                'transaction_reference': transaction_obj.transaction_reference,
            },
        )

        commission_payment.status = 'paid'
        commission_payment.payment_method = 'wire_transfer'
        commission_payment.payment_reference = transfer.id
        commission_payment.transaction_id = transfer.id
        commission_payment.payment_date = timezone.now().date()
        commission_payment.notes = (
            (commission_payment.notes or '') + f"\nAuto-disbursed via Stripe transfer: {transfer.id}"
        ).strip()
        commission_payment.save(
            update_fields=[
                'status',
                'payment_method',
                'payment_reference',
                'transaction_id',
                'payment_date',
                'notes',
                'updated_at',
            ]
        )
        return True
    except Exception as exc:
        logger.warning("Automatic Stripe payout failed for booking %s: %s", booking.id, exc)
        commission_payment.status = 'failed'
        commission_payment.notes = (
            (commission_payment.notes or '') + f"\nAutomatic Stripe payout failed: {exc}"
        ).strip()
        commission_payment.save(update_fields=['status', 'notes', 'updated_at'])
        return False


def _notify_listing_owner_payment(booking, commission_payment):
    recipient, _recipient_type = _resolve_payout_recipient(booking)
    if not recipient or not getattr(recipient, 'email', ''):
        return

    listing_name = (
        booking.property.name
        if booking.property
        else (f"{booking.car.make} {booking.car.model}" if booking.car else getattr(booking.tour, 'name', 'Listing'))
    )
    subject = f"Payment received for booking #{booking.id}"
    message = (
        f"Hi {recipient.get_full_name() or recipient.email},\n\n"
        f"A traveler payment has been confirmed for {listing_name}.\n"
        f"Booking ID: {booking.id}\n"
        f"Gross amount: ${booking.total_amount}\n"
        f"Platform commission: ${booking.commission_amount}\n"
        f"Your payout amount: ${booking.host_payout_amount}\n"
        f"Payout record status: {commission_payment.status}\n\n"
        "Please check your dashboard for details.\n"
    )
    send_mail(
        subject=subject,
        message=message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[recipient.email],
        fail_silently=True,
    )


def _notify_site_owner_payment(booking, transaction_obj=None):
    recipients = set()
    configured = (getattr(settings, 'CONTACT_EMAIL_RECIPIENT', '') or '').strip()
    if configured:
        for email in configured.split(','):
            cleaned = email.strip()
            if cleaned:
                recipients.add(cleaned)

    User = get_user_model()
    admin_emails = User.objects.filter(is_superuser=True, is_active=True).exclude(
        email=''
    ).values_list('email', flat=True)
    recipients.update(admin_emails)

    if not recipients:
        return

    listing_name = booking.property.name if booking.property else str(booking.id)
    subject = f"Payment confirmed - booking #{booking.id}"
    message = (
        f"Payment confirmed for booking #{booking.id} ({listing_name}).\n"
        f"Total paid: ${booking.total_amount}\n"
        f"Platform commission: ${booking.commission_amount}\n"
        f"Lister payout amount: ${booking.host_payout_amount}\n"
        f"Payment option: {booking.get_payment_option_display()}\n"
        f"Transaction reference: {getattr(transaction_obj, 'transaction_reference', 'n/a')}\n"
    )
    send_mail(
        subject=subject,
        message=message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=sorted(recipients),
        fail_silently=True,
    )


def _finalize_successful_booking_payment(booking, transaction_obj=None):
    just_marked_paid = _mark_booking_paid(booking)
    commission_payment, _created = _ensure_commission_payment_record(
        booking=booking,
        transaction_obj=transaction_obj,
    )
    _execute_automatic_lister_payout(
        booking=booking,
        commission_payment=commission_payment,
        transaction_obj=transaction_obj,
    )

    # Avoid duplicate notification spam when webhooks/callbacks replay.
    if just_marked_paid:
        if commission_payment:
            _notify_listing_owner_payment(booking, commission_payment)
        _notify_site_owner_payment(booking, transaction_obj=transaction_obj)


def _refresh_paynow_transaction(request, transaction_obj):
    if not transaction_obj:
        return False

    poll_url = (transaction_obj.metadata or {}).get('paynow_poll_url') or transaction_obj.gateway_transaction_id
    if not poll_url:
        return False

    try:
        # Result/return URLs are required by SDK constructor but not used for polling.
        fallback_result = _build_absolute_url(request, 'payments:paynow_result')
        fallback_return = _build_absolute_url(
            request,
            'payments:paynow_checkout_return',
            booking_id=transaction_obj.booking_id,
        )
        paynow = _build_paynow_client(result_url=fallback_result, return_url=fallback_return)
        status_response = paynow.check_transaction_status(poll_url)
    except Exception:
        return False

    paid = bool(getattr(status_response, 'paid', False))
    status_text = str(getattr(status_response, 'status', '') or '').lower()
    response_payload = {
        'mode': 'paynow_poll',
        'poll_url': poll_url,
        'status': status_text,
        'paid': paid,
    }

    if paid:
        _complete_transaction(transaction_obj, gateway_response=response_payload)
        if transaction_obj.booking:
            _finalize_successful_booking_payment(
                booking=transaction_obj.booking,
                transaction_obj=transaction_obj,
            )
        return True

    # Keep pending for in-progress statuses; mark cancelled for explicit termination.
    if status_text in {'cancelled', 'failed', 'error'}:
        _cancel_transaction(transaction_obj, gateway_response=response_payload)
        if transaction_obj.booking:
            _mark_booking_pending(transaction_obj.booking)
        return False

    transaction_obj.gateway_response = response_payload
    transaction_obj.save(update_fields=['gateway_response', 'updated_at'])
    return False


def _clean_dict(raw_data):
    """Drop empty values from metadata payloads."""
    return {key: value for key, value in raw_data.items() if value not in (None, '', [], {}, ())}


def _build_checkout_metadata(form, selected_option, is_skip):
    metadata = {
        'simulated_checkout': True,
        'payment_option': selected_option,
    }

    if is_skip:
        metadata['skip_reason'] = 'testing_only'

    if selected_option == Booking.PaymentOption.CARD:
        card_number = form.cleaned_data.get('card_number', '')
        metadata.update(
            _clean_dict(
                {
                    'card_last_four': card_number[-4:] if len(card_number) >= 4 else '',
                    'card_holder_name': form.cleaned_data.get('card_name'),
                    'card_expiry_month': form.cleaned_data.get('card_expiry_month'),
                    'card_expiry_year': form.cleaned_data.get('card_expiry_year'),
                }
            )
        )

    billing_data = _clean_dict(
        {
            'address': form.cleaned_data.get('billing_address'),
            'city': form.cleaned_data.get('billing_city'),
            'country': form.cleaned_data.get('billing_country'),
            'postal_code': form.cleaned_data.get('billing_postal_code'),
        }
    )
    if billing_data:
        metadata['billing'] = billing_data

    return metadata


@login_required
def payment_list(request):
    """List payments for the current authenticated user."""
    transactions = (
        Transaction.objects.filter(customer=request.user)
        .select_related('gateway', 'booking')
        .order_by('-created_at')
    )
    return render(
        request,
        'payments/payment_list.html',
        {
            'transactions': transactions,
            'transaction_count': transactions.count(),
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def booking_checkout(request, booking_id):
    """Complete payment for a booking and create a transaction record."""
    booking = get_object_or_404(Booking, id=booking_id, user=request.user)

    if booking.status not in [Booking.BookingStatus.PENDING, Booking.BookingStatus.CONFIRMED]:
        messages.error(request, _('This booking cannot be paid in its current status.'))
        return redirect('bookings:detail', pk=booking.pk)

    if not booking.is_upcoming:
        messages.error(request, _('Only upcoming bookings can be paid online.'))
        return redirect('bookings:detail', pk=booking.pk)

    if booking.payment_status == Booking.PaymentStatus.PAID:
        messages.info(request, _('This booking is already fully paid.'))
        return redirect('bookings:detail', pk=booking.pk)

    payment_options = list(Booking.PaymentOption.choices)
    allow_skip_payment = bool(getattr(settings, 'BOOKING_ALLOW_SKIP_PAYMENT', False))
    use_stripe_for_card = bool(
        getattr(settings, 'STRIPE_ENABLED', False) and bool(getattr(settings, 'STRIPE_SECRET_KEY', ''))
    )
    use_paynow_gateway = bool(
        getattr(settings, 'PAYNOW_ENABLED', False)
        and bool(getattr(settings, 'PAYNOW_INTEGRATION_ID', ''))
        and bool(getattr(settings, 'PAYNOW_INTEGRATION_KEY', ''))
    )
    allow_simulated_payments = bool(
        getattr(settings, 'BOOKING_ALLOW_SIMULATED_PAYMENTS', bool(getattr(settings, 'DEBUG', False)))
    )
    initial_option = booking.payment_option or Booking.PaymentOption.CARD

    if request.method == 'POST':
        form = BookingCheckoutForm(
            request.POST,
            payment_choices=payment_options,
            allow_skip=allow_skip_payment,
            require_card_fields=not use_stripe_for_card,
        )
        if form.is_valid():
            selected_option = form.cleaned_data['payment_option']
            is_skip_payment = selected_option == BookingCheckoutForm.SKIP_PAYMENT_OPTION
            uses_live_gateway = _can_complete_without_simulation(selected_option)

            if not is_skip_payment and not allow_simulated_payments and not uses_live_gateway:
                messages.error(
                    request,
                    _(
                        'Selected payment option is not available right now. '
                        'Please use a configured gateway or bank transfer.'
                    ),
                )
                return redirect('payments:booking_checkout', booking_id=booking.pk)

            if _is_paynow_checkout(selected_option):
                try:
                    with db_transaction.atomic():
                        gateway = _get_or_create_paynow_gateway()
                        booking.payment_option = Booking.PaymentOption.PAYNOW
                        booking.payment_status = Booking.PaymentStatus.PENDING
                        booking.save(update_fields=['payment_option', 'payment_status', 'updated_at'])

                        transaction_obj = Transaction.objects.create(
                            amount=booking.total_amount,
                            currency='USD',
                            transaction_type='payment',
                            gateway=gateway,
                            customer=request.user,
                            booking=booking,
                            status='pending',
                            description=_('Paynow checkout initialized for booking {}').format(booking.id),
                            platform_fee=_platform_fee_for_booking(booking),
                            metadata={'provider': 'paynow', 'flow': 'redirect'},
                        )

                    paynow_result = _initiate_paynow_payment(
                        request=request,
                        booking=booking,
                        transaction_obj=transaction_obj,
                    )
                    if not paynow_result.get('success'):
                        transaction_obj.status = 'failed'
                        transaction_obj.error_message = str(
                            paynow_result.get('error') or _('Paynow initialization failed.')
                        )
                        transaction_obj.save(update_fields=['status', 'error_message', 'updated_at'])
                        messages.error(request, transaction_obj.error_message)
                        return redirect('bookings:detail', pk=booking.pk)

                    transaction_obj.gateway_transaction_id = paynow_result.get('poll_url', '')
                    transaction_obj.metadata = {
                        **(transaction_obj.metadata or {}),
                        'paynow_poll_url': paynow_result.get('poll_url', ''),
                        'paynow_redirect_url': paynow_result.get('redirect_url', ''),
                    }
                    transaction_obj.gateway_response = {
                        'mode': 'paynow_redirect',
                        'status': 'pending',
                    }
                    transaction_obj.save(
                        update_fields=['gateway_transaction_id', 'metadata', 'gateway_response', 'updated_at']
                    )
                    return redirect(paynow_result['redirect_url'])
                except Exception as exc:
                    messages.error(request, _('Could not initialize Paynow checkout: {}').format(str(exc)))
                    return redirect('bookings:detail', pk=booking.pk)

            if _is_stripe_card_checkout(selected_option):
                try:
                    with db_transaction.atomic():
                        gateway = _get_or_create_stripe_gateway()
                        booking.payment_option = Booking.PaymentOption.CARD
                        booking.payment_status = Booking.PaymentStatus.PENDING
                        booking.save(update_fields=['payment_option', 'payment_status', 'updated_at'])

                        transaction_obj = Transaction.objects.create(
                            amount=booking.total_amount,
                            currency=getattr(settings, 'STRIPE_CURRENCY', 'USD').upper(),
                            transaction_type='payment',
                            gateway=gateway,
                            customer=request.user,
                            booking=booking,
                            status='pending',
                            description=_('Stripe checkout initialized for booking {}').format(booking.id),
                            platform_fee=_platform_fee_for_booking(booking),
                            metadata={'provider': 'stripe', 'flow': 'hosted_checkout'},
                        )

                        checkout_session = _create_stripe_checkout_session(
                            request=request,
                            booking=booking,
                            transaction_obj=transaction_obj,
                        )

                        transaction_obj.gateway_transaction_id = checkout_session.id
                        transaction_obj.metadata = {
                            **(transaction_obj.metadata or {}),
                            'stripe_session_id': checkout_session.id,
                            'checkout_url': checkout_session.url,
                        }
                        transaction_obj.gateway_response = {
                            'mode': 'stripe_hosted',
                            'session_id': checkout_session.id,
                            'payment_status': getattr(checkout_session, 'payment_status', None),
                        }
                        transaction_obj.save(
                            update_fields=[
                                'gateway_transaction_id',
                                'metadata',
                                'gateway_response',
                                'updated_at',
                            ]
                        )

                    return redirect(checkout_session.url)
                except Exception as exc:
                    messages.error(request, _('Could not initialize Stripe checkout: {}').format(str(exc)))
                    return redirect('bookings:detail', pk=booking.pk)

            try:
                with db_transaction.atomic():
                    gateway = _get_or_create_checkout_gateway()
                    now = timezone.now()
                    is_bank_transfer = (
                        selected_option == Booking.PaymentOption.BANK_TRANSFER and not is_skip_payment
                    )

                    transaction_status = 'processing' if is_bank_transfer else 'completed'
                    transaction_description = _(
                        'Booking payment for {}'
                    ).format(booking.property.name if booking.property else booking.id)
                    if is_skip_payment:
                        transaction_description = _('Testing checkout: payment skipped for booking {}').format(
                            booking.id
                        )

                    transaction_metadata = _build_checkout_metadata(
                        form=form,
                        selected_option=selected_option,
                        is_skip=is_skip_payment,
                    )

                    transaction_obj = Transaction.objects.create(
                        amount=booking.total_amount,
                        currency='USD',
                        transaction_type='payment',
                        gateway=gateway,
                        customer=request.user,
                        booking=booking,
                        status=transaction_status,
                        description=transaction_description,
                        platform_fee=_platform_fee_for_booking(booking),
                        gateway_transaction_id=f"SIM-{uuid.uuid4().hex[:16].upper()}",
                        metadata=transaction_metadata,
                        gateway_response={
                            'mode': 'simulated',
                            'status': transaction_status,
                            'selected_option': selected_option,
                            'skip': is_skip_payment,
                        },
                        processed_at=now,
                        settled_at=None if is_bank_transfer else now,
                    )

                    if not is_skip_payment:
                        booking.payment_option = selected_option
                    elif not booking.payment_option:
                        booking.payment_option = Booking.PaymentOption.CARD

                    if is_bank_transfer:
                        booking.payment_status = Booking.PaymentStatus.PENDING
                    else:
                        _finalize_successful_booking_payment(
                            booking=booking,
                            transaction_obj=transaction_obj,
                        )
                        booking.refresh_from_db(fields=['payment_status', 'status'])
                    booking.save(update_fields=['payment_option', 'payment_status', 'status', 'updated_at'])

                if is_skip_payment:
                    messages.success(
                        request,
                        _('Booking confirmed in testing mode. No live payment was processed.'),
                    )
                elif is_bank_transfer:
                    messages.info(
                        request,
                        _('Bank transfer initiated. Your booking will confirm after payment reconciliation.'),
                    )
                else:
                    messages.success(request, _('Payment completed successfully. Your booking is now confirmed.'))
                return redirect('bookings:detail', pk=booking.pk)
            except Exception as exc:
                messages.error(request, _('Could not complete payment: {}').format(str(exc)))
    else:
        form = BookingCheckoutForm(
            initial={'payment_option': initial_option},
            payment_choices=payment_options,
            allow_skip=allow_skip_payment,
            require_card_fields=not use_stripe_for_card,
        )

    return render(
        request,
        'payments/booking_checkout.html',
        {
            'booking': booking,
            'form': form,
            'card_payment_option': Booking.PaymentOption.CARD,
            'skip_payment_option': BookingCheckoutForm.SKIP_PAYMENT_OPTION,
            'allow_skip_payment': allow_skip_payment,
            'use_stripe_for_card': use_stripe_for_card,
            'use_paynow_gateway': use_paynow_gateway,
            'allow_simulated_payments': allow_simulated_payments,
            'stripe_publishable_key': getattr(settings, 'STRIPE_PUBLIC_KEY', ''),
        },
    )


@login_required
@require_http_methods(["GET"])
def stripe_checkout_success(request, booking_id):
    booking = get_object_or_404(Booking, id=booking_id, user=request.user)
    session_id = request.GET.get('session_id', '').strip()
    if not session_id:
        messages.warning(request, _('Stripe session was not provided. Please contact support if charged.'))
        return redirect('bookings:detail', pk=booking.pk)

    transaction_obj = (
        Transaction.objects.filter(
            booking=booking,
            customer=request.user,
            gateway_transaction_id=session_id,
            transaction_type='payment',
        )
        .select_related('gateway')
        .order_by('-created_at')
        .first()
    )
    if not transaction_obj:
        messages.warning(request, _('No matching Stripe transaction was found for this booking.'))
        return redirect('bookings:detail', pk=booking.pk)

    try:
        stripe.api_key = settings.STRIPE_SECRET_KEY
        checkout_session = stripe.checkout.Session.retrieve(session_id)
        payment_status = getattr(checkout_session, 'payment_status', '')

        if payment_status == 'paid':
            _complete_transaction(
                transaction_obj,
                gateway_response={
                    'mode': 'stripe_hosted',
                    'session_id': session_id,
                    'payment_status': payment_status,
                    'status': getattr(checkout_session, 'status', ''),
                },
            )
            _finalize_successful_booking_payment(
                booking=booking,
                transaction_obj=transaction_obj,
            )
            messages.success(request, _('Stripe payment completed successfully.'))
        else:
            messages.info(
                request,
                _('Stripe checkout returned status "{}". We will finalize once payment is confirmed.').format(
                    payment_status or 'unknown'
                ),
            )
    except Exception as exc:
        messages.error(request, _('Could not verify Stripe payment: {}').format(str(exc)))

    return redirect('bookings:detail', pk=booking.pk)


@login_required
@require_http_methods(["GET"])
def stripe_checkout_cancel(request, booking_id):
    booking = get_object_or_404(Booking, id=booking_id, user=request.user)
    latest_txn = (
        Transaction.objects.filter(
            booking=booking,
            customer=request.user,
            transaction_type='payment',
            status='pending',
        )
        .order_by('-created_at')
        .first()
    )
    if latest_txn:
        _cancel_transaction(
            latest_txn,
            gateway_response={
                'mode': 'stripe_hosted',
                'cancelled_by_user': True,
            },
        )
    _mark_booking_pending(booking)
    messages.info(request, _('Stripe checkout was cancelled. Your booking remains unpaid.'))
    return redirect('bookings:detail', pk=booking.pk)


@csrf_exempt
@require_http_methods(["POST"])
def stripe_webhook(request):
    if not getattr(settings, 'STRIPE_ENABLED', False):
        return JsonResponse({'detail': 'stripe_disabled'}, status=400)

    payload = request.body.decode('utf-8')
    sig_header = request.META.get('HTTP_STRIPE_SIGNATURE', '')
    webhook_secret = getattr(settings, 'STRIPE_WEBHOOK_SECRET', '')
    stripe.api_key = settings.STRIPE_SECRET_KEY

    try:
        if webhook_secret:
            event = stripe.Webhook.construct_event(payload=payload, sig_header=sig_header, secret=webhook_secret)
        else:
            event = json.loads(payload)
    except Exception:
        return HttpResponse(status=400)

    event_type = event.get('type') if isinstance(event, dict) else getattr(event, 'type', None)
    data_object = (
        event.get('data', {}).get('object')
        if isinstance(event, dict)
        else getattr(getattr(event, 'data', None), 'object', None)
    )

    if event_type == 'checkout.session.completed' and data_object:
        session_id = data_object.get('id') if isinstance(data_object, dict) else getattr(data_object, 'id', '')
        payment_status = (
            data_object.get('payment_status')
            if isinstance(data_object, dict)
            else getattr(data_object, 'payment_status', '')
        )

        txn = Transaction.objects.filter(gateway_transaction_id=session_id, transaction_type='payment').first()
        if txn:
            if payment_status == 'paid':
                _complete_transaction(
                    txn,
                    gateway_response={
                        'mode': 'stripe_webhook',
                        'event': event_type,
                        'session_id': session_id,
                        'payment_status': payment_status,
                    },
                )
                if txn.booking:
                    _finalize_successful_booking_payment(
                        booking=txn.booking,
                        transaction_obj=txn,
                    )
            else:
                txn.gateway_response = {
                    'mode': 'stripe_webhook',
                    'event': event_type,
                    'session_id': session_id,
                    'payment_status': payment_status,
                }
                txn.save(update_fields=['gateway_response', 'updated_at'])

    if event_type == 'checkout.session.expired' and data_object:
        session_id = data_object.get('id') if isinstance(data_object, dict) else getattr(data_object, 'id', '')
        txn = Transaction.objects.filter(gateway_transaction_id=session_id, transaction_type='payment').first()
        if txn and txn.status == 'pending':
            _cancel_transaction(
                txn,
                gateway_response={
                    'mode': 'stripe_webhook',
                    'event': event_type,
                    'session_id': session_id,
                },
            )
            if txn.booking:
                _mark_booking_pending(txn.booking)

    return HttpResponse(status=200)


@login_required
@require_http_methods(["GET"])
def paynow_checkout_return(request, booking_id):
    booking = get_object_or_404(Booking, id=booking_id, user=request.user)
    transaction_obj = (
        Transaction.objects.filter(
            booking=booking,
            customer=request.user,
            transaction_type='payment',
        )
        .order_by('-created_at')
        .first()
    )
    if not transaction_obj:
        messages.warning(request, _('No Paynow transaction was found for this booking.'))
        return redirect('bookings:detail', pk=booking.pk)

    paid = _refresh_paynow_transaction(request=request, transaction_obj=transaction_obj)
    if paid:
        messages.success(request, _('Paynow payment completed successfully.'))
    else:
        status = str((transaction_obj.gateway_response or {}).get('status') or 'pending').lower()
        if status in {'cancelled', 'failed', 'error'}:
            messages.warning(request, _('Paynow payment was not completed (status: {}).').format(status))
        else:
            messages.info(request, _('Paynow payment is still pending confirmation.'))
    return redirect('bookings:detail', pk=booking.pk)


@csrf_exempt
@require_http_methods(["POST"])
def paynow_result(request):
    # Paynow posts the merchant reference to the result URL.
    reference = (
        request.POST.get('reference')
        or request.POST.get('Reference')
        or request.POST.get('merchantreference')
        or request.POST.get('merchant_reference')
    )
    if not reference:
        return HttpResponse(status=200)

    transaction_obj = Transaction.objects.filter(transaction_reference=reference, transaction_type='payment').first()
    if not transaction_obj:
        return HttpResponse(status=200)

    if transaction_obj.booking:
        _refresh_paynow_transaction(request=request, transaction_obj=transaction_obj)
    return HttpResponse(status=200)
