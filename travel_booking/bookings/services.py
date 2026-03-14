"""
bookings/services.py - Business logic layer for bookings

Service layer orchestrates business logic, coordinates between repositories,
and handles domain-specific operations like booking workflows.
"""

import logging
from datetime import timedelta
from decimal import Decimal
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from core.exceptions import (
    NonRecoverableBookingError, 
    InvalidDataError,
)
from core.monitoring import record_booking_created, record_booking_cancelled, record_booking_completed
from .models import Booking
from .repositories import BookingRepository
from properties.models import Property, PropertyStatus, RoomType

logger = logging.getLogger(__name__)


class BookingService:
    """
    High-level booking operations and domain logic.
    
    Responsibilities:
    - Validate booking requests
    - Coordinate with repositories
    - Send notifications
    - Handle state transitions
    - Publish domain events
    """
    
    def __init__(self):
        self.repository = BookingRepository()
    
    def create_booking(
        self,
        user,
        property_id,
        room_type_id,
        check_in_date,
        check_out_date,
        guests=1,
        special_requests='',
        payment_option='',
    ):
        """
        Create a new booking through the service layer.
        
        This method:
        1. Validates input
        2. Checks property availability
        3. Creates booking with transaction safety
        4. Publishes booking created event
        5. Triggers notification tasks
        
        Args:
            user: User creating the booking
            property_id: Property UUID
            check_in_date: Date object for check-in
            check_out_date: Date object for check-out
            guests: Number of guests
            special_requests: Special requests text
            payment_option: Selected payment option
        
        Returns:
            Booking instance
        
        Raises:
            NonRecoverableBookingError: If booking cannot be created
            InvalidDataError: If input is invalid
        """
        
        # Validate dates
        if check_out_date <= check_in_date:
            raise InvalidDataError(
                message='Check-out date must be after check-in date',
                code='invalid_dates'
            )
        
        today = timezone.now().date()
        if check_in_date < today:
            raise InvalidDataError(
                message='Cannot book dates in the past',
                code='past_dates'
            )
        
        # Validate guests count
        if not isinstance(guests, int) or guests < 1 or guests > 20:
            raise InvalidDataError(
                message='Guests must be between 1 and 20',
                code='invalid_guests'
            )
        
        # Get property
        property_obj = self._get_and_validate_property(property_id)
        
        nights = (check_out_date - check_in_date).days
        if nights <= 0:
            raise InvalidDataError(
                message='Check-out date must be after check-in date',
                code='invalid_dates'
            )

        room_type = self._get_and_validate_room_type(
            property_obj=property_obj,
            room_type_id=room_type_id,
            guests=guests,
        )

        price_per_night = self._calculate_price_per_night(property_obj, room_type=room_type)
        total_amount = self._calculate_total_amount(price_per_night, nights)
        payment_status = Booking.PaymentStatus.PENDING

        try:
            with transaction.atomic():
                locked_property = Property.objects.select_for_update().get(id=property_obj.id)
                locked_room_type = None
                if room_type:
                    locked_room_type = RoomType.objects.select_for_update().get(id=room_type.id)

                overlapping = Booking.objects.filter(
                    property_id=locked_property.id,
                    status__in=[
                        Booking.BookingStatus.PENDING,
                        Booking.BookingStatus.CONFIRMED,
                    ],
                    check_in_date__lt=check_out_date,
                    check_out_date__gt=check_in_date,
                )
                if locked_room_type:
                    overlapping = overlapping.filter(room_type_id=locked_room_type.id)
                    capacity = locked_room_type.quantity_available or 1
                else:
                    capacity = locked_property.total_rooms or 1

                if overlapping.count() >= capacity:
                    raise InvalidDataError(
                        message=(
                            'Selected room type is not available for these dates.'
                            if locked_room_type
                            else 'Property is not available for these dates.'
                        ),
                        code='property_unavailable'
                    )

                booking = self.repository.create_booking(
                    user=user,
                    property_obj=locked_property,
                    room_type_obj=locked_room_type,
                    check_in_date=check_in_date,
                    check_out_date=check_out_date,
                    guests=guests,
                    special_requests=special_requests,
                    price_per_night=price_per_night,
                    total_amount=total_amount,
                    payment_option=payment_option,
                    payment_status=payment_status,
                    status=Booking.BookingStatus.PENDING,
                )
            
            # Record metrics
            record_booking_created()
            
            # Publish event (async via Celery)
            self._publish_booking_created_event(booking)
            
            # Send confirmation email (background task)
            self._send_booking_confirmation(booking)
            
            logger.info(
                f"Booking created successfully: {booking.id}",
                extra={
                    'booking_id': str(booking.id),
                    'user_id': str(user.id),
                    'property_id': str(property_id)
                }
            )
            
            return booking
        
        except Exception as e:
            logger.error(
                f"Error creating booking: {str(e)}",
                exc_info=True,
                extra={
                    'user_id': str(user.id),
                    'property_id': str(property_id)
                }
            )
            raise
    
    def confirm_booking(self, booking_id, user):
        """
        Confirm a pending booking (transition to confirmed state).
        
        Args:
            booking_id: Booking UUID
            user: User confirming the booking
        
        Returns:
            Updated Booking instance
        
        Raises:
            NonRecoverableBookingError: If booking cannot be confirmed
        """
        
        booking = self.repository.get_booking(booking_id, user=user)
        if not booking:
            raise NonRecoverableBookingError(
                message='Booking not found',
                code='booking_not_found'
            )
        
        if booking.status != 'pending':
            raise NonRecoverableBookingError(
                message=f'Cannot confirm booking in {booking.status} status',
                code='invalid_state_transition'
            )
        
        with transaction.atomic():
            booking = self.repository.update_booking_status(
                booking_id,
                'confirmed',
                reason='Payment confirmed'
            )
            self._mark_property_unavailable(booking)
        
        # Publish event
        self._publish_booking_confirmed_event(booking)
        
        # Send confirmation
        self._send_confirmation_notification(booking)
        
        return booking
    
    def cancel_booking(self, booking_id, user, reason=''):
        """
        Cancel an existing booking.
        
        Args:
            booking_id: Booking UUID
            user: User cancelling
            reason: Cancellation reason
        
        Returns:
            Updated Booking instance
        
        Raises:
            NonRecoverableBookingError: If booking cannot be cancelled
        """
        
        booking = self.repository.get_booking(booking_id, user=user)
        if not booking:
            raise NonRecoverableBookingError(
                message='Booking not found',
                code='booking_not_found'
            )
        
        if booking.status not in ['pending', 'confirmed']:
            raise NonRecoverableBookingError(
                message=f'Cannot cancel booking in {booking.status} status',
                code='invalid_state_transition'
            )
        
        # Check cancellation policy
        today = timezone.now().date()
        days_until_checkin = (booking.check_in_date - today).days
        
        if days_until_checkin < 0:
            raise NonRecoverableBookingError(
                message='Cannot cancel cancelled past bookings',
                code='already_passed'
            )
        
        with transaction.atomic():
            booking = self.repository.update_booking_status(
                booking_id,
                'cancelled',
                reason=reason
            )
            self._restore_property_availability(booking)
        
        # Record metrics
        record_booking_cancelled()
        
        # Publish event
        self._publish_booking_cancelled_event(booking)
        
        # Send cancellation notification
        self._send_cancellation_notification(booking)
        
        return booking
    
    def get_booking_details(self, booking_id, user):
        """Get booking details with authorization check."""
        booking = self.repository.get_booking(booking_id, user=user)
        if not booking:
            raise NonRecoverableBookingError(
                message='Booking not found',
                code='booking_not_found'
            )
        return booking
    
    def get_user_bookings(self, user, status=None, date_filter=None, page=1, page_size=20):
        """Get paginated list of user bookings."""
        query = self.repository.get_user_bookings(user, status=status, date_filter=date_filter)
        
        # Simple pagination
        offset = (page - 1) * page_size
        total_count = query.count()
        bookings = query[offset:offset + page_size]
        
        return {
            'bookings': bookings,
            'total_count': total_count,
            'page': page,
            'page_size': page_size,
            'total_pages': (total_count + page_size - 1) // page_size
        }
    
    @staticmethod
    def _get_and_validate_property(property_id):
        """Get and validate property exists and is active."""
        try:
            property_obj = Property.objects.get(
                id=property_id,
                status__in=PropertyStatus.public_statuses(),
            )
            return property_obj
        except Property.DoesNotExist:
            raise InvalidDataError(
                message='Property not found or not available',
                code='property_not_found'
            )

    @staticmethod
    def _get_and_validate_room_type(property_obj, room_type_id, guests):
        """Resolve and validate the selected room type for a property booking."""
        property_room_types = property_obj.room_types.all()

        if room_type_id:
            try:
                room_type = property_room_types.get(id=room_type_id)
            except RoomType.DoesNotExist:
                raise InvalidDataError(
                    message='Selected room type is invalid for this property',
                    code='room_type_not_found'
                )
        elif property_room_types.exists():
            raise InvalidDataError(
                message='A room type must be selected for this property',
                code='room_type_required'
            )
        else:
            room_type = None

        if room_type and guests > room_type.max_occupancy:
            raise InvalidDataError(
                message=f'Selected room type allows at most {room_type.max_occupancy} guests',
                code='room_type_capacity_exceeded'
            )

        return room_type

    @staticmethod
    def _calculate_price_per_night(property_obj, room_type=None):
        """Resolve nightly booking price for a property."""
        if room_type and room_type.base_price and room_type.base_price > 0:
            return room_type.base_price
        if property_obj.minimum_price and property_obj.minimum_price > 0:
            return property_obj.minimum_price
        return Decimal('100.00')

    @staticmethod
    def _calculate_total_amount(price_per_night, nights):
        """Calculate and validate the final booking total."""
        total_amount = price_per_night * Decimal(str(nights))
        if total_amount <= 0:
            raise InvalidDataError(
                message='Total amount must be greater than zero',
                code='invalid_total_amount'
            )
        return total_amount

    @staticmethod
    def _booking_dates(booking):
        """Yield each booked night from check-in up to, but not including, check-out."""
        current_date = booking.check_in_date
        while current_date < booking.check_out_date:
            yield current_date
            current_date += timedelta(days=1)

    @classmethod
    def _mark_property_unavailable(cls, booking):
        """Booking inventory is enforced via overlapping room-aware bookings."""
        return None

    @classmethod
    def _restore_property_availability(cls, booking):
        """Availability rows are not mutated for booking-created inventory holds."""
        return None
    
    @staticmethod
    def _publish_booking_created_event(booking):
        """Publish booking created event (async)."""
        # In a full microservices architecture, this would publish to a message queue
        # For now, we'll use Celery
        try:
            from bookings.tasks import publish_booking_event
            publish_booking_event.delay(booking.id, 'booking.created')
        except Exception as e:
            logger.warning(f"Failed to publish booking event: {e}")
    
    @staticmethod
    def _publish_booking_confirmed_event(booking):
        """Publish booking confirmed event (async)."""
        try:
            from bookings.tasks import publish_booking_event
            publish_booking_event.delay(booking.id, 'booking.confirmed')
        except Exception as e:
            logger.warning(f"Failed to publish booking event: {e}")
    
    @staticmethod
    def _publish_booking_cancelled_event(booking):
        """Publish booking cancelled event (async)."""
        try:
            from bookings.tasks import publish_booking_event
            publish_booking_event.delay(booking.id, 'booking.cancelled')
        except Exception as e:
            logger.warning(f"Failed to publish booking event: {e}")
    
    @staticmethod
    def _send_booking_confirmation(booking):
        """Send booking confirmation email (async)."""
        try:
            from notifications.tasks import send_booking_confirmation_email
            send_booking_confirmation_email.delay(booking.id)
        except Exception as e:
            logger.warning(f"Failed to send booking confirmation: {e}")
        
        # Also notify the property owner
        BookingService._send_owner_notification(booking, 'property')
    
    @staticmethod
    def _send_owner_notification(booking, booking_type='property'):
        """Send notification to listing owner when booking is made (async)."""
        try:
            from notifications.tasks import send_owner_booking_notification
            send_owner_booking_notification.delay(booking.id, booking_type)
        except Exception as e:
            logger.warning(f"Failed to send owner notification: {e}")
    
    @staticmethod
    def _send_confirmation_notification(booking):
        """Send booking confirmed notification (async)."""
        try:
            from notifications.tasks import send_booking_confirmed_email
            send_booking_confirmed_email.delay(booking.id)
        except Exception as e:
            logger.warning(f"Failed to send confirmed notification: {e}")
    
    @staticmethod
    def _send_cancellation_notification(booking):
        """Send booking cancellation notification (async)."""
        try:
            from notifications.tasks import send_booking_cancelled_email
            send_booking_cancelled_email.delay(booking.id)
        except Exception as e:
            logger.warning(f"Failed to send cancellation notification: {e}")
    
    @staticmethod
    def expire_pending_bookings(minutes=30):
        """
        Expire old pending bookings.

        When payment is disabled, this task becomes a no-op so pending bookings
        can stay open for manual host/approver workflows.
        
        Called by scheduled Celery task.
        
        Args:
            minutes: Minutes old for pending bookings to expire
        
        Returns:
            Number of bookings expired
        """
        if not getattr(settings, 'BOOKING_REQUIRE_PAYMENT', False):
            logger.info("Skipping pending booking expiration because payment is disabled.")
            return 0

        bookings = BookingRepository.get_pending_expiring_bookings(minutes=minutes)
        expired_count = 0
        
        for booking in bookings:
            try:
                BookingRepository.update_booking_status(
                    booking.id,
                    'cancelled',
                    reason='Auto-expired: Payment not received'
                )
                record_booking_cancelled()
                expired_count += 1
            except Exception as e:
                logger.error(f"Failed to expire booking {booking.id}: {e}")
        
        logger.info(f"Expired {expired_count} pending bookings")
        return expired_count


# Singleton-like service instance
_booking_service = None


def get_booking_service():
    """Get or create booking service instance."""
    global _booking_service
    if _booking_service is None:
        _booking_service = BookingService()
    return _booking_service
