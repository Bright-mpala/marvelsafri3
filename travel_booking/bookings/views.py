import json
from datetime import datetime, timedelta
from decimal import Decimal
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Prefetch, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_http_methods

from car_rentals.models import CarRentalBooking, TaxiBooking
from payments.models import Transaction
from properties.models import Property, PropertyStatus

from .forms import BookingForm, BookingModifyForm
from .models import Booking
from .services import get_booking_service


BOOKING_SORT_OPTIONS = {
    'recent': '-created_at',
    'check_in': 'check_in_date',
    'check_in_desc': '-check_in_date',
    'price_high': '-total_amount',
    'price_low': 'total_amount',
}


def _support_email():
    return getattr(
        settings,
        'SUPPORT_EMAIL',
        getattr(settings, 'DEFAULT_FROM_EMAIL', 'support@example.com'),
    )


def _summarize_booking_management_state(booking):
    transactions = list(booking.transactions.all())
    refunds = [refund for txn in transactions for refund in txn.refunds.all()]

    paid_transactions = [
        txn for txn in transactions
        if txn.transaction_type == 'payment' and txn.status in {'completed', 'refunded', 'partially_refunded'}
    ]
    paid_total = sum((txn.amount for txn in paid_transactions), Decimal('0.00'))
    refunded_total = sum(
        (refund.amount for refund in refunds if refund.status == 'completed'),
        Decimal('0.00'),
    )
    pending_refunds = [refund for refund in refunds if refund.status in {'pending', 'processing'}]

    payment_summary = _('Awaiting payment')
    if booking.payment_status == Booking.PaymentStatus.PAID:
        payment_summary = _('Paid in full')
    elif paid_total > 0:
        payment_summary = _('Payment received')
    elif booking.payment_status == Booking.PaymentStatus.FAILED:
        payment_summary = _('Payment failed')

    if booking.status == Booking.BookingStatus.CANCELLED:
        cancellation_summary = _('Cancelled')
    elif booking.status == Booking.BookingStatus.COMPLETED:
        cancellation_summary = _('Stay completed')
    elif booking.is_upcoming:
        cancellation_summary = _('Free to manage before check-in')
    else:
        cancellation_summary = _('Check-in window has started')

    if pending_refunds:
        refund_summary = _('Refund in progress')
    elif refunded_total and paid_total and refunded_total >= paid_total:
        refund_summary = _('Refunded in full')
    elif refunded_total > 0:
        refund_summary = _('Partially refunded')
    elif booking.status == Booking.BookingStatus.CANCELLED and paid_total > 0:
        refund_summary = _('Refund review pending')
    elif booking.status == Booking.BookingStatus.CANCELLED:
        refund_summary = _('No payment captured')
    elif booking.payment_status == Booking.PaymentStatus.PAID:
        refund_summary = _('Refund not requested')
    else:
        refund_summary = _('Not applicable')

    booking.payment_summary = payment_summary
    booking.cancellation_summary = cancellation_summary
    booking.refund_summary = refund_summary
    booking.refunded_total = refunded_total
    booking.paid_total = paid_total
    booking.has_invoice = paid_total > 0 or booking.payment_status == Booking.PaymentStatus.PAID
    booking.support_email = _support_email()
    return booking


def _base_booking_queryset(user):
    return (
        Booking.objects
        .filter(user=user)
        .select_related('property', 'room_type', 'car', 'tour', 'tour_schedule', 'user')
        .prefetch_related(
            'property__images',
            'tour__images',
            Prefetch(
                'transactions',
                queryset=Transaction.objects.prefetch_related('refunds', 'gateway').order_by('-created_at'),
            ),
        )
    )


@login_required
@require_http_methods(["GET"])
def booking_list(request):
    """List user's bookings with filtering, sorting, and pagination."""
    bookings = _base_booking_queryset(request.user)
    car_rental_bookings = (
        CarRentalBooking.objects.filter(user=request.user)
        .select_related('car', 'company', 'pickup_location', 'dropoff_location')
        .order_by('-created_at')
    )
    taxi_bookings = (
        TaxiBooking.objects.filter(user=request.user)
        .select_related('car', 'driver', 'company')
        .order_by('-created_at')
    )

    q = request.GET.get('q', '').strip()
    status_filter = request.GET.get('status')
    date_filter = request.GET.get('date')
    sort_key = request.GET.get('sort', 'recent')

    if q:
        bookings = bookings.filter(
            Q(id__icontains=q) |
            Q(property__name__icontains=q) |
            Q(property__city__icontains=q) |
            Q(room_type__name__icontains=q) |
            Q(special_requests__icontains=q)
        )

    if status_filter in dict(Booking.BOOKING_STATUS):
        bookings = bookings.filter(status=status_filter)

    today = timezone.now().date()
    if date_filter == 'upcoming':
        bookings = bookings.filter(check_in_date__gte=today)
    elif date_filter == 'past':
        bookings = bookings.filter(check_out_date__lt=today)

    bookings = bookings.order_by(BOOKING_SORT_OPTIONS.get(sort_key, '-created_at'))

    paginator = Paginator(bookings, 8)
    page_obj = paginator.get_page(request.GET.get('page'))
    bookings_page = list(page_obj.object_list)
    for booking in bookings_page:
        _summarize_booking_management_state(booking)
    page_obj.object_list = bookings_page

    query_params = request.GET.copy()
    query_params.pop('page', None)
    page_query = query_params.urlencode()

    context = {
        'bookings': page_obj,
        'car_rental_bookings': car_rental_bookings,
        'taxi_bookings': taxi_bookings,
        'status_filter': status_filter,
        'date_filter': date_filter,
        'sort_key': sort_key,
        'search_query': q,
        'page_query': page_query,
        'total_bookings': Booking.objects.filter(user=request.user).count(),
    }
    return render(request, 'bookings/booking_list.html', context)


@login_required
@require_http_methods(["GET"])
def booking_detail(request, pk):
    """Display booking details."""
    booking = get_object_or_404(_base_booking_queryset(request.user), pk=pk)
    _summarize_booking_management_state(booking)

    support_query = urlencode({
        'subject': f'Booking support for {booking.id}',
        'booking_reference': str(booking.id),
    })
    context = {
        'booking': booking,
        'can_cancel': booking.status in ['pending', 'confirmed'] and booking.is_upcoming,
        'can_modify': booking.status in ['pending', 'confirmed'] and booking.is_upcoming,
        'needs_payment': (
            booking.payment_status != Booking.PaymentStatus.PAID
            and booking.status in ['pending', 'confirmed']
            and booking.is_upcoming
        ),
        'support_url': f"{reverse('core:contact')}?{support_query}",
    }
    return render(request, 'bookings/booking_detail.html', context)


@login_required
@require_http_methods(["GET"])
def booking_rebook(request, pk):
    """Redirect to property booking flow with prior stay data prefilled."""
    booking = get_object_or_404(
        Booking.objects.select_related('property', 'room_type'),
        pk=pk,
        user=request.user,
    )
    if not booking.property_id:
        messages.error(request, _('Only property bookings can be rebooked here.'))
        return redirect('bookings:detail', pk=booking.pk)

    today = timezone.now().date()
    original_nights = max(1, booking.nights_count)
    default_check_in = max(today + timedelta(days=1), booking.check_in_date)
    default_check_out = default_check_in + timedelta(days=original_nights)

    params = {
        'check_in': default_check_in.isoformat(),
        'check_out': default_check_out.isoformat(),
        'guests': booking.guests,
    }
    if booking.room_type_id:
        params['room_type'] = str(booking.room_type_id)

    return redirect(f"{reverse('bookings:create', args=[booking.property_id])}?{urlencode(params)}")


def _render_booking_document(request, booking, template_name, filename_prefix):
    context = {
        'booking': booking,
        'generated_at': timezone.now(),
        'support_email': _support_email(),
    }
    content = render_to_string(template_name, context, request=request)
    response = HttpResponse(content, content_type='text/html; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="{filename_prefix}-{booking.id}.html"'
    return response


@login_required
@require_http_methods(["GET"])
def booking_download_confirmation(request, pk):
    booking = get_object_or_404(_base_booking_queryset(request.user), pk=pk)
    _summarize_booking_management_state(booking)
    return _render_booking_document(
        request,
        booking,
        'bookings/documents/confirmation.html',
        'booking-confirmation',
    )


@login_required
@require_http_methods(["GET"])
def booking_download_invoice(request, pk):
    booking = get_object_or_404(_base_booking_queryset(request.user), pk=pk)
    _summarize_booking_management_state(booking)
    return _render_booking_document(
        request,
        booking,
        'bookings/documents/invoice.html',
        'booking-invoice',
    )


@login_required
@require_http_methods(["GET", "POST"])
def booking_create(request, property_id):
    """Create a new booking for a property."""
    public_statuses = list(PropertyStatus.public_statuses())
    try:
        property_obj = Property.objects.get(id=property_id, status__in=public_statuses)
    except (Property.DoesNotExist, ValueError):
        property_obj = get_object_or_404(Property, slug=property_id, status__in=public_statuses)

    if request.method == 'POST':
        form = BookingForm(request.POST, property_obj=property_obj)
        if form.is_valid():
            try:
                booking = get_booking_service().create_booking(
                    user=request.user,
                    property_id=property_obj.id,
                    room_type_id=getattr(form.cleaned_data.get('room_type'), 'id', None),
                    check_in_date=form.cleaned_data['check_in_date'],
                    check_out_date=form.cleaned_data['check_out_date'],
                    guests=form.cleaned_data['guests'],
                    special_requests=form.cleaned_data.get('special_requests', ''),
                    payment_option=form.cleaned_data.get('payment_option', ''),
                )
                messages.success(
                    request,
                    _(
                        'Booking request submitted successfully. Total: ${:.2f}. '
                        'Secure payment method: {}. Platform commission applied: {}%.'
                    ).format(
                        booking.total_amount,
                        booking.get_payment_option_display(),
                        booking.commission_rate,
                    )
                )

                if getattr(settings, 'BOOKING_REQUIRE_PAYMENT', False):
                    messages.info(
                        request,
                        _('Complete secure checkout to confirm this booking.'),
                    )
                    return redirect('payments:booking_checkout', booking_id=booking.pk)
                return redirect('bookings:detail', pk=booking.pk)
            except Exception as e:
                messages.error(request, _('Error creating booking: {}').format(str(e)))
    else:
        today = timezone.now().date()
        check_in = request.GET.get('check_in')
        check_out = request.GET.get('check_out')
        guests = request.GET.get('guests', '2')

        check_in_date = None
        check_out_date = None

        if check_in:
            try:
                check_in_date = datetime.fromisoformat(check_in).date()
            except (ValueError, TypeError):
                pass

        if check_out:
            try:
                check_out_date = datetime.fromisoformat(check_out).date()
            except (ValueError, TypeError):
                pass

        initial_data = {
            'check_in_date': check_in_date or (today + timedelta(days=1)),
            'check_out_date': check_out_date or (today + timedelta(days=4)),
            'guests': guests,
        }
        room_type_id = request.GET.get('room_type')
        if room_type_id:
            initial_data['room_type'] = room_type_id
        form = BookingForm(initial=initial_data, property_obj=property_obj)

    room_types = list(property_obj.room_types.order_by('display_order', 'name'))
    room_type_price_map = {
        str(room.id): str(room.base_price or property_obj.minimum_price or Decimal('0'))
        for room in room_types
    }
    selected_room_type = None
    if 'room_type' in form.fields:
        selected_room_type = form['room_type'].value() or request.GET.get('room_type')
        if selected_room_type:
            selected_room_type = str(selected_room_type)

    context = {
        'form': form,
        'property': property_obj,
        'commission_rate_preview': property_obj.get_commission_rate_for_guest(request.user),
        'commission_type_preview': property_obj.get_commission_type_for_guest(request.user),
        'room_type_price_map_json': json.dumps(room_type_price_map),
        'default_nightly_price': room_type_price_map.get(selected_room_type, str(property_obj.minimum_price or Decimal('0'))),
    }
    return render(request, 'bookings/booking_create.html', context)


@login_required
@require_http_methods(["GET", "POST"])
def booking_modify(request, pk):
    """Allow guests to update dates/guest count for upcoming bookings."""
    booking = get_object_or_404(Booking, pk=pk, user=request.user)

    if booking.status not in ['pending', 'confirmed']:
        messages.error(request, _('Only pending or confirmed bookings can be modified.'))
        return redirect('bookings:detail', pk=booking.pk)

    if not booking.is_upcoming:
        messages.error(request, _('Past or active bookings cannot be modified.'))
        return redirect('bookings:detail', pk=booking.pk)

    original_total = booking.total_amount
    original_status = booking.status

    if request.method == 'POST':
        form = BookingModifyForm(request.POST, instance=booking)
        if form.is_valid():
            try:
                with transaction.atomic():
                    updated_booking = form.save(commit=False)

                    nights = (updated_booking.check_out_date - updated_booking.check_in_date).days
                    if nights <= 0:
                        raise ValidationError(_('Check-out must be after check-in.'))

                    updated_booking.total_amount = (
                        (updated_booking.price_per_night or Decimal('0')) * Decimal(str(nights))
                    )

                    amount_changed = updated_booking.total_amount != original_total
                    if amount_changed and updated_booking.payment_status == Booking.PaymentStatus.PAID:
                        updated_booking.payment_status = Booking.PaymentStatus.PENDING
                        updated_booking.status = Booking.BookingStatus.PENDING

                    updated_booking.save()

                    if amount_changed and original_status == Booking.BookingStatus.CONFIRMED:
                        messages.warning(
                            request,
                            _(
                                'Booking updated. Because the total changed, payment needs to be reconfirmed.'
                            ),
                        )
                    else:
                        messages.success(request, _('Booking updated successfully.'))
                    return redirect('bookings:detail', pk=updated_booking.pk)
            except Exception as exc:
                messages.error(request, _('Could not update booking: {}').format(str(exc)))
    else:
        form = BookingModifyForm(instance=booking)

    return render(
        request,
        'bookings/booking_modify.html',
        {
            'booking': booking,
            'form': form,
        },
    )


@login_required
@require_http_methods(["POST"])
def booking_cancel(request, pk):
    """Cancel a booking."""
    booking = get_object_or_404(Booking, pk=pk, user=request.user)

    if booking.status not in ['pending', 'confirmed']:
        messages.error(request, _('This booking cannot be cancelled.'))
        return redirect('bookings:detail', pk=booking.pk)

    if not booking.is_upcoming:
        messages.error(request, _('Cannot cancel bookings that have already started.'))
        return redirect('bookings:detail', pk=booking.pk)

    cancellation_reason = request.POST.get('reason', '')
    try:
        with transaction.atomic():
            booking.status = 'cancelled'
            booking.cancellation_reason = cancellation_reason
            booking.save()
            messages.success(request, _('Booking cancelled successfully.'))
    except Exception as e:
        messages.error(request, _('Error cancelling booking: {}').format(str(e)))

    return redirect('bookings:detail', pk=booking.pk)
