from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from decimal import Decimal, ROUND_HALF_UP
from datetime import timedelta

from core.models import SoftDeletableModel
from properties.models import Property, PropertyAvailability, PropertyStatus, RoomType
from car_rentals.models import Car, CarAvailability, CarStatus
from tours.models import Tour, TourSchedule

class Booking(SoftDeletableModel):
    """Unified booking model for properties, cars, and tours with marketplace payouts."""

    # Backwards-compatible alias used by views/templates
    BOOKING_STATUS = (
        ('pending', _('Pending')),
        ('confirmed', _('Confirmed')),
        ('cancelled', _('Cancelled')),
        ('completed', _('Completed')),
    )

    class BookingStatus(models.TextChoices):
        PENDING = 'pending', _('Pending')
        CONFIRMED = 'confirmed', _('Confirmed')
        CANCELLED = 'cancelled', _('Cancelled')
        COMPLETED = 'completed', _('Completed')

    class CommissionType(models.TextChoices):
        LOCAL = 'local', _('Local (Zimbabwe)')
        AWAY = 'away', _('Away')

    class PaymentOption(models.TextChoices):
        CARD = 'card', _('Card (3D Secure)')
        PAYNOW = 'paynow', _('Paynow')
        ECOCASH = 'ecocash', _('EcoCash')
        BANK_TRANSFER = 'bank_transfer', _('Bank Transfer')

    class PaymentStatus(models.TextChoices):
        PENDING = 'pending', _('Pending')
        PAID = 'paid', _('Paid')
        FAILED = 'failed', _('Failed')

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='bookings',
        help_text=_('User who made the booking')
    )

    # One of these must be set
    property = models.ForeignKey(
        Property,
        on_delete=models.CASCADE,
        related_name='unified_bookings',
        null=True,
        blank=True,
        help_text=_('Property being booked')
    )
    room_type = models.ForeignKey(
        RoomType,
        on_delete=models.SET_NULL,
        related_name='bookings',
        null=True,
        blank=True,
        help_text=_('Selected room type for property bookings')
    )
    car = models.ForeignKey(
        Car,
        on_delete=models.CASCADE,
        related_name='unified_bookings',
        null=True,
        blank=True,
        help_text=_('Car being booked')
    )
    tour = models.ForeignKey(
        Tour,
        on_delete=models.CASCADE,
        related_name='unified_bookings',
        null=True,
        blank=True,
        help_text=_('Tour being booked')
    )
    tour_schedule = models.ForeignKey(
        TourSchedule,
        on_delete=models.SET_NULL,
        related_name='unified_bookings',
        null=True,
        blank=True,
    )

    check_in_date = models.DateField(_('check-in date'))
    check_out_date = models.DateField(_('check-out date'))

    guests = models.PositiveIntegerField(_('number of guests'), default=1)
    special_requests = models.TextField(_('special requests'), blank=True, help_text=_('Any special requests or preferences'))

    price_per_night = models.DecimalField(_('price per night'), max_digits=10, decimal_places=2, default=0)
    total_amount = models.DecimalField(_('total amount'), max_digits=10, decimal_places=2, default=0)
    commission_type = models.CharField(
        _('commission type'),
        max_length=20,
        choices=CommissionType.choices,
        default=CommissionType.AWAY,
    )
    commission_rate = models.DecimalField(
        _('commission rate'),
        max_digits=5,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text=_('Platform commission percentage applied to this booking.'),
    )
    commission_amount = models.DecimalField(
        _('commission amount'),
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
    )
    host_payout_amount = models.DecimalField(
        _('host payout amount'),
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
    )
    payment_option = models.CharField(
        _('payment option'),
        max_length=30,
        choices=PaymentOption.choices,
        blank=True,
    )
    payment_status = models.CharField(
        _('payment status'),
        max_length=20,
        choices=PaymentStatus.choices,
        default=PaymentStatus.PENDING,
    )

    status = models.CharField(
        _('status'),
        max_length=20,
        choices=BookingStatus.choices,
        default=BookingStatus.PENDING
    )
    cancellation_reason = models.TextField(_('cancellation reason'), blank=True)

    def __str__(self):
        target = self.property or self.car or self.tour
        return f"Booking #{self.id} - {self.user.email} ({target})"

    def clean(self):
        """Central booking validation for all listing types."""
        self._validate_dates()
        self._validate_listing_selection()
        self._validate_room_selection()
        self._validate_not_owner()
        self._validate_moderation_state()
        self._validate_availability()

    def _validate_dates(self):
        if self.check_out_date <= self.check_in_date:
            raise ValidationError({'check_out_date': _('Check-out must be after check-in.')})

    def _validate_listing_selection(self):
        selected = [bool(self.property), bool(self.car), bool(self.tour)]
        if sum(selected) != 1:
            raise ValidationError(_('Exactly one of property, car, or tour must be specified for a booking.'))

    def _validate_not_owner(self):
        owner = None
        if self.property:
            owner = getattr(self.property, 'owner', None)
        elif self.car:
            owner = getattr(self.car, 'owner', None)
        elif self.tour and self.tour.property:
            owner = getattr(self.tour.property, 'owner', None)

        if owner and owner == self.user:
            raise ValidationError(_('Owners cannot book their own listings.'))

    def _validate_room_selection(self):
        if self.room_type and not self.property:
            raise ValidationError({'room_type': _('Room type can only be used with property bookings.')})

        if self.property and self.room_type and self.room_type.property_id != self.property_id:
            raise ValidationError({'room_type': _('Selected room type does not belong to this property.')})

        if self.property and self.property.room_types.exists() and not self.room_type:
            raise ValidationError({'room_type': _('Please select a room type for this booking.')})

        if self.property and self.room_type and self.guests and self.guests > self.room_type.max_occupancy:
            raise ValidationError({
                'guests': _(
                    'Selected room type can host at most %(max_occupancy)s guest(s).'
                ) % {'max_occupancy': self.room_type.max_occupancy}
            })

    def _validate_moderation_state(self):
        if self.property and not getattr(self.property, 'owner_id', None):
            raise ValidationError(_('Property must have an owner before it can be booked.'))
        if self.property and self.property.status not in {PropertyStatus.APPROVED, PropertyStatus.ACTIVE}:
            raise ValidationError(_('Property must be approved before it can be booked.'))
        if self.car and self.car.moderation_status != CarStatus.APPROVED:
            raise ValidationError(_('Car must be approved before it can be booked.'))
        if self.tour:
            if self.tour.property and self.tour.property.status not in {PropertyStatus.APPROVED, PropertyStatus.ACTIVE}:
                raise ValidationError(_('Tour property must be approved before the tour can be booked.'))
            if not self.tour.is_active:
                raise ValidationError(_('Tour is not active.'))

    def _validate_availability(self):
        if self.property:
            self._validate_property_availability()
        if self.car:
            self._validate_car_availability()
        if self.tour:
            self._validate_tour_availability()

    def _validate_property_availability(self):
        overlapping = Booking.objects.filter(
            property=self.property,
            status__in=[self.BookingStatus.PENDING, self.BookingStatus.CONFIRMED],
            check_in_date__lt=self.check_out_date,
            check_out_date__gt=self.check_in_date,
        )
        if self.room_type_id:
            overlapping = overlapping.filter(room_type_id=self.room_type_id)
        if self.pk:
            overlapping = overlapping.exclude(pk=self.pk)

        capacity = (
            getattr(self.room_type, 'quantity_available', None)
            if self.room_type_id
            else getattr(self.property, 'total_rooms', 1)
        ) or 1
        if overlapping.count() >= capacity:
            message = (
                _('Selected room type is fully booked for the chosen dates.')
                if self.room_type_id
                else _('All rooms for this property are fully booked for the selected dates.')
            )
            raise ValidationError(message)

        # availability table
        dates = self._date_range()
        unavailable = PropertyAvailability.objects.filter(
            property=self.property,
            date__in=dates,
            is_available=False,
        )
        if unavailable.exists():
            raise ValidationError(_('Selected dates are not available for this property.'))

    def _validate_car_availability(self):
        overlapping = Booking.objects.filter(
            car=self.car,
            status__in=[self.BookingStatus.PENDING, self.BookingStatus.CONFIRMED],
            check_in_date__lt=self.check_out_date,
            check_out_date__gt=self.check_in_date,
        )
        if self.pk:
            overlapping = overlapping.exclude(pk=self.pk)
        if overlapping.exists():
            raise ValidationError(_('The car is already booked for the selected dates.'))

        dates = self._date_range()
        unavailable = CarAvailability.objects.filter(
            car=self.car,
            date__in=dates,
            is_available=False,
        )
        if unavailable.exists():
            raise ValidationError(_('Selected dates are not available for this car.'))

    def _validate_tour_availability(self):
        if self.tour_schedule:
            if not self.tour_schedule.is_available or self.tour_schedule.is_booked_out:
                raise ValidationError(_('The selected tour schedule is not available.'))
        else:
            # Fallback: ensure schedule_date matches check-in
            if self.tour.schedule_date and self.tour.schedule_date != self.check_in_date:
                raise ValidationError(_('Tour schedule date does not match check-in date.'))

    def _date_range(self):
        current = self.check_in_date
        while current < self.check_out_date:
            yield current
            current += timedelta(days=1)

    def save(self, *args, **kwargs):
        # Only calculate if not already computed (don't override explicit values)
        if not self.total_amount or self.total_amount == Decimal('0'):
            # Gracefully handle cases where dates are not yet set
            if self.check_in_date and self.check_out_date:
                nights = (self.check_out_date - self.check_in_date).days
            else:
                nights = 0
            base_rate = self.price_per_night or Decimal('0')
            if self.car and self.car.daily_price:
                base_rate = self.car.daily_price
            if self.property and self.room_type and self.room_type.base_price:
                base_rate = self.room_type.base_price
            if self.property and nights and base_rate:
                self.total_amount = base_rate * Decimal(str(nights))
            elif self.car and nights and base_rate:
                self.total_amount = base_rate * Decimal(str(nights))
            elif self.tour:
                self.total_amount = self.tour.base_price or base_rate

        self._calculate_property_financials()

        self.full_clean()  # Run validation after total is computed
        super().save(*args, **kwargs)

    def _calculate_property_financials(self):
        """Calculate commission and host payout for property bookings."""
        if not self.property or not self.total_amount:
            self.commission_rate = Decimal('0.00')
            self.commission_amount = Decimal('0.00')
            self.host_payout_amount = self.total_amount or Decimal('0.00')
            self.commission_type = self.CommissionType.AWAY
            return

        rate = self.property.get_commission_rate_for_guest(self.user)
        commission_type = self.property.get_commission_type_for_guest(self.user)

        commission_amount = (
            (self.total_amount * rate) / Decimal('100')
        ).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        payout_amount = (
            self.total_amount - commission_amount
        ).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        self.commission_rate = rate.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        self.commission_amount = max(commission_amount, Decimal('0.00'))
        self.host_payout_amount = max(payout_amount, Decimal('0.00'))
        self.commission_type = (
            self.CommissionType.LOCAL if commission_type == 'local' else self.CommissionType.AWAY
        )

    import builtins

    # Marketplace-facing aliases expected by business stakeholders.
    @builtins.property
    def total_price(self):
        return self.total_amount

    @total_price.setter
    def total_price(self, value):
        self.total_amount = value

    @builtins.property
    def platform_commission(self):
        return self.commission_amount

    @platform_commission.setter
    def platform_commission(self, value):
        self.commission_amount = value

    @builtins.property
    def owner_payout(self):
        return self.host_payout_amount

    @owner_payout.setter
    def owner_payout(self, value):
        self.host_payout_amount = value

    # builtins.property is used here because the class defines a field named
    # `property` which shadows the built-in `property` decorator inside the
    # class body. Using builtins.property avoids the TypeError encountered when
    # the decorator attempted to call the ForeignKey object.
    @builtins.property
    def nights_count(self):
        """Calculate number of nights."""
        if not self.check_in_date or not self.check_out_date:
            return 0
        return (self.check_out_date - self.check_in_date).days

    @builtins.property
    def is_upcoming(self):
        """Check if booking is in the future."""
        from django.utils import timezone
        return self.check_in_date >= timezone.now().date()

    class Meta:
        verbose_name = _('booking')
        verbose_name_plural = _('bookings')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'status']),
            models.Index(fields=['property', 'check_in_date', 'check_out_date']),
            models.Index(fields=['room_type', 'check_in_date', 'check_out_date']),
            models.Index(fields=['car', 'check_in_date', 'check_out_date']),
            models.Index(fields=['tour', 'check_in_date']),
            models.Index(fields=['status', 'check_in_date']),
        ]
