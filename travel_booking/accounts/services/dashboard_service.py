"""Dashboard service layer.

Keeps aggregation and owner workspace calculations out of the view so the
controller remains small and easy to maintain.
"""

from django.db.models import Count, Q, Sum
from django.utils import timezone

from bookings.models import Booking
from car_rentals.models import Car, CarRentalBooking, CarStatus, TaxiBooking
from properties.models import Property, PropertyStatus
from tours.models import Tour, TourBooking

from accounts.models import UserRole


class DashboardService:
    """Build the full dashboard context for a user."""

    @classmethod
    def build_context(cls, user):
        """Return the template context for the dashboard view."""
        today = timezone.now().date()

        stay_bookings = Booking.objects.filter(user=user).select_related('property')
        car_rental_bookings = CarRentalBooking.objects.filter(user=user).select_related('car', 'company')
        taxi_bookings = TaxiBooking.objects.filter(user=user).select_related('car', 'driver', 'company')

        booking_stats = cls._build_booking_stats(stay_bookings, car_rental_bookings, taxi_bookings, today)
        owner_stats = cls._build_owner_stats(user)

        return {
            **booking_stats,
            **owner_stats,
            'email_verified': user.is_email_verified,
        }

    @staticmethod
    def _build_booking_stats(stay_bookings, car_rental_bookings, taxi_bookings, today):
        """Build traveler-facing booking metrics and recent activity."""
        total_bookings = stay_bookings.count() + car_rental_bookings.count() + taxi_bookings.count()

        upcoming_bookings = (
            stay_bookings.filter(check_in_date__gte=today, status__in=['confirmed', 'pending']).count()
            + car_rental_bookings.filter(pickup_date__gte=today, status__in=['confirmed', 'pending', 'active']).count()
            + taxi_bookings.filter(
                pickup_datetime__date__gte=today,
                status__in=['confirmed', 'pending', 'driver_assigned', 'en_route'],
            ).count()
        )

        completed_bookings = (
            stay_bookings.filter(status='completed').count()
            + car_rental_bookings.filter(status='completed').count()
            + taxi_bookings.filter(status='completed').count()
        )

        pending_bookings = (
            stay_bookings.filter(status='pending').count()
            + car_rental_bookings.filter(status='pending').count()
            + taxi_bookings.filter(status='pending').count()
        )

        recent_bookings = DashboardService._build_recent_bookings(
            stay_bookings,
            car_rental_bookings,
            taxi_bookings,
        )

        favorite_destinations = stay_bookings.values(
            'property__city', 'property__country'
        ).annotate(
            booking_count=Count('id')
        ).order_by('-booking_count')[:5]

        return {
            'total_bookings': total_bookings,
            'upcoming_bookings': upcoming_bookings,
            'completed_bookings': completed_bookings,
            'pending_bookings': pending_bookings,
            'loyalty_points': total_bookings * 100,
            'recent_bookings': recent_bookings,
            'favorite_destinations': favorite_destinations,
            'car_rental_count': car_rental_bookings.count(),
            'taxi_booking_count': taxi_bookings.count(),
            'stay_booking_count': stay_bookings.count(),
            'pending_alert': pending_bookings > 0,
        }

    @staticmethod
    def _build_recent_bookings(stay_bookings, car_rental_bookings, taxi_bookings):
        """Normalize recent traveler bookings into one sorted list."""
        recent_items = []

        for booking in stay_bookings:
            recent_items.append({
                'kind': 'stay',
                'title': getattr(booking.property, 'name', 'Stay booking'),
                'location': f"{getattr(booking.property, 'city', '')}, {getattr(booking.property, 'country', '')}",
                'date_range': f"{booking.check_in_date} - {booking.check_out_date}",
                'status': booking.status,
                'status_label': booking.get_status_display(),
                'amount': booking.total_amount,
                'created_at': booking.created_at,
            })

        for booking in car_rental_bookings:
            recent_items.append({
                'kind': 'car',
                'title': f"{getattr(booking.car, 'make', 'Car')} {getattr(booking.car, 'model', '')}".strip(),
                'location': getattr(booking.pickup_location, 'city', '') if booking.pickup_location else '',
                'date_range': f"{booking.pickup_date} - {booking.dropoff_date}",
                'status': booking.status,
                'status_label': booking.get_status_display(),
                'amount': booking.total_amount,
                'created_at': booking.created_at,
            })

        for booking in taxi_bookings:
            recent_items.append({
                'kind': 'taxi',
                'title': 'Taxi ride',
                'location': booking.pickup_address[:50] if booking.pickup_address else '',
                'date_range': booking.pickup_datetime.strftime('%Y-%m-%d %H:%M') if booking.pickup_datetime else '',
                'status': booking.status,
                'status_label': booking.get_status_display(),
                'amount': booking.total_fare,
                'created_at': booking.created_at,
            })

        return sorted(recent_items, key=lambda item: item['created_at'], reverse=True)[:5]

    @classmethod
    def _build_owner_stats(cls, user):
        """Build listing-owner workspace data and financial rollups."""
        is_admin_user = user.is_staff or user.is_superuser or user.role == UserRole.ADMIN
        can_view_owner_dashboard = user.is_business_account or is_admin_user
        approved_property_statuses = [PropertyStatus.APPROVED, PropertyStatus.ACTIVE]

        owned_properties = Property.objects.none()
        owned_cars = Car.objects.none()
        owned_properties_count = 0
        owned_cars_count = 0
        owned_tours_count = 0
        expected_owner_payout_total = 0
        expected_platform_commission_total = 0
        total_bookings_received = 0
        received_bookings = []

        if can_view_owner_dashboard:
            owner_data = cls._collect_owner_data(user, is_admin_user, approved_property_statuses)
            owned_properties = owner_data['owned_properties']
            owned_cars = owner_data['owned_cars']
            owned_properties_count = owner_data['owned_properties_count']
            owned_cars_count = owner_data['owned_cars_count']
            owned_tours_count = owner_data['owned_tours_count']
            expected_owner_payout_total = owner_data['expected_owner_payout_total']
            expected_platform_commission_total = owner_data['expected_platform_commission_total']
            total_bookings_received = owner_data['total_bookings_received']
            received_bookings = owner_data['received_bookings']

        is_owner = can_view_owner_dashboard and (
            owned_properties_count > 0 or owned_cars_count > 0 or owned_tours_count > 0
        )

        pending_received_bookings_count = sum(1 for booking in received_bookings if booking['status'] == 'pending')
        confirmed_received_bookings_count = sum(1 for booking in received_bookings if booking['status'] == 'confirmed')
        completed_received_bookings_count = sum(1 for booking in received_bookings if booking['status'] == 'completed')

        return {
            'is_owner': is_owner,
            'owned_properties': owned_properties,
            'owned_properties_count': owned_properties_count,
            'owned_cars': owned_cars,
            'owned_cars_count': owned_cars_count,
            'owned_tours_count': owned_tours_count,
            'total_listings': owned_properties_count + owned_cars_count + owned_tours_count,
            'total_bookings_received': total_bookings_received,
            'expected_owner_payout_total': expected_owner_payout_total,
            'expected_platform_commission_total': expected_platform_commission_total,
            'received_bookings': received_bookings,
            'pending_received_bookings_count': pending_received_bookings_count,
            'confirmed_received_bookings_count': confirmed_received_bookings_count,
            'completed_received_bookings_count': completed_received_bookings_count,
        }

    @classmethod
    def _collect_owner_data(cls, user, is_admin_user, approved_property_statuses):
        """Collect owner listing counts, booking intake, and payout totals."""
        owned_properties = Property.objects.filter(owner=user, is_deleted=False)
        if not is_admin_user:
            owned_properties = owned_properties.filter(status__in=approved_property_statuses)
        owned_properties = owned_properties.select_related('property_type')
        owned_properties_count = owned_properties.count()

        property_bookings_received_qs = Booking.objects.filter(
            property__owner=user,
            property__is_deleted=False,
        )
        if not is_admin_user:
            property_bookings_received_qs = property_bookings_received_qs.filter(
                property__status__in=approved_property_statuses
            )

        owned_cars = Car.objects.filter(owner=user, is_deleted=False)
        if not is_admin_user:
            owned_cars = owned_cars.filter(moderation_status=CarStatus.APPROVED)
        owned_cars = owned_cars.select_related('company', 'category')
        owned_cars_count = owned_cars.count()

        car_bookings_received_qs = CarRentalBooking.objects.filter(
            car__owner=user,
            car__is_deleted=False,
        )
        taxi_bookings_received_qs = TaxiBooking.objects.filter(
            car__owner=user,
            car__is_deleted=False,
        )
        if not is_admin_user:
            car_bookings_received_qs = car_bookings_received_qs.filter(car__moderation_status=CarStatus.APPROVED)
            taxi_bookings_received_qs = taxi_bookings_received_qs.filter(car__moderation_status=CarStatus.APPROVED)

        owned_tours = Tour.objects.filter(operator__user=user, is_deleted=False)
        if not is_admin_user:
            owned_tours = owned_tours.filter(is_active=True).filter(
                Q(property__isnull=True) | Q(property__status__in=approved_property_statuses)
            )
        owned_tours_count = owned_tours.count()

        tour_bookings_qs = TourBooking.objects.filter(
            tour__operator__user=user,
            tour__is_deleted=False,
        )
        if not is_admin_user:
            tour_bookings_qs = tour_bookings_qs.filter(tour__is_active=True).filter(
                Q(tour__property__isnull=True) | Q(tour__property__status__in=approved_property_statuses)
            )

        property_bookings_received = property_bookings_received_qs.select_related('user', 'property').order_by('-created_at')[:10]
        car_bookings_received = car_bookings_received_qs.select_related('user', 'car').order_by('-created_at')[:10]
        taxi_bookings_received = taxi_bookings_received_qs.select_related('user', 'car').order_by('-created_at')[:10]
        tour_bookings_received = list(tour_bookings_qs.select_related('user', 'tour').order_by('-created_at')[:10])

        return {
            'owned_properties': owned_properties,
            'owned_cars': owned_cars,
            'owned_properties_count': owned_properties_count,
            'owned_cars_count': owned_cars_count,
            'owned_tours_count': owned_tours_count,
            'expected_owner_payout_total': property_bookings_received_qs.aggregate(
                total=Sum('host_payout_amount')
            ).get('total') or 0,
            'expected_platform_commission_total': property_bookings_received_qs.aggregate(
                total=Sum('commission_amount')
            ).get('total') or 0,
            'total_bookings_received': (
                property_bookings_received_qs.count()
                + car_bookings_received_qs.count()
                + taxi_bookings_received_qs.count()
                + tour_bookings_qs.count()
            ),
            'received_bookings': cls._build_received_bookings(
                property_bookings_received,
                car_bookings_received,
                taxi_bookings_received,
                tour_bookings_received,
            ),
        }

    @staticmethod
    def _build_received_bookings(
        property_bookings_received,
        car_bookings_received,
        taxi_bookings_received,
        tour_bookings_received,
    ):
        """Normalize bookings received by owners into one feed."""
        received_bookings = []

        for booking in property_bookings_received[:5]:
            received_bookings.append({
                'type': 'property',
                'type_icon': 'building',
                'listing_name': booking.property.name if booking.property else 'Property',
                'guest_name': booking.user.get_full_name() or booking.user.email,
                'guest_email': booking.user.email,
                'date_info': f"{booking.check_in_date} - {booking.check_out_date}",
                'guests': booking.guests,
                'amount': booking.total_price,
                'owner_payout': booking.owner_payout,
                'platform_commission': booking.platform_commission,
                'commission_rate': booking.commission_rate,
                'status': booking.status,
                'status_display': booking.get_status_display(),
                'created_at': booking.created_at,
                'booking_id': booking.id,
            })

        for booking in car_bookings_received[:5]:
            received_bookings.append({
                'type': 'car',
                'type_icon': 'car',
                'listing_name': f"{booking.car.make} {booking.car.model}" if booking.car else 'Car',
                'guest_name': booking.user.get_full_name() or booking.user.email,
                'guest_email': booking.user.email,
                'date_info': f"{booking.pickup_date} - {booking.dropoff_date}",
                'guests': 1,
                'amount': booking.total_amount,
                'status': booking.status,
                'status_display': booking.get_status_display(),
                'created_at': booking.created_at,
                'booking_id': booking.id,
            })

        for booking in taxi_bookings_received[:5]:
            received_bookings.append({
                'type': 'taxi',
                'type_icon': 'taxi',
                'listing_name': f"{booking.car.make} {booking.car.model}" if booking.car else 'Taxi',
                'guest_name': booking.user.get_full_name() or booking.user.email,
                'guest_email': booking.user.email,
                'date_info': booking.pickup_datetime.strftime('%Y-%m-%d %H:%M') if booking.pickup_datetime else 'TBD',
                'guests': getattr(booking, 'passengers', 1),
                'amount': booking.total_fare,
                'status': booking.status,
                'status_display': booking.get_status_display(),
                'created_at': booking.created_at,
                'booking_id': booking.id,
            })

        for booking in tour_bookings_received[:5]:
            received_bookings.append({
                'type': 'tour',
                'type_icon': 'hiking',
                'listing_name': booking.tour.name if booking.tour else 'Tour',
                'guest_name': booking.user.get_full_name() or booking.user.email,
                'guest_email': booking.user.email,
                'date_info': booking.tour_date.strftime('%Y-%m-%d') if hasattr(booking, 'tour_date') and booking.tour_date else 'TBD',
                'guests': getattr(booking, 'participant_count', 1),
                'amount': booking.total_price if hasattr(booking, 'total_price') else 0,
                'status': booking.status,
                'status_display': booking.get_status_display(),
                'created_at': booking.created_at,
                'booking_id': booking.id,
            })

        return sorted(received_bookings, key=lambda item: item['created_at'], reverse=True)[:10]
