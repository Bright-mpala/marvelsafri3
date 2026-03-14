from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from decimal import Decimal

from accounts.models import User, UserRole
from bookings.models import Booking

from .models import PricePlan, Property, PropertyFavorite, PropertyStatus, PropertyType, RoomType


class PropertyFavoriteTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='favorite-user@example.com',
            password='testpass123',
            role=UserRole.CUSTOMER,
            country='ZW',
            is_email_verified=True,
        )
        self.host = User.objects.create_user(
            email='favorite-host@example.com',
            password='testpass123',
            role=UserRole.HOST,
            country='ZW',
            is_email_verified=True,
        )
        property_type = PropertyType.objects.create(name='Cabin', slug='favorite-cabin')
        self.property = Property.objects.create(
            name='Favorite Cabin',
            slug='favorite-cabin',
            description='Cabin for favorite tests.',
            property_type=property_type,
            address='123 Forest Road',
            city='Nyanga',
            postal_code='0001',
            country='ZW',
            owner=self.host,
            status=PropertyStatus.APPROVED,
            is_verified=True,
        )

    def test_toggle_favorite_adds_and_removes_property(self):
        self.client.force_login(self.user)

        add_response = self.client.post(
            reverse('properties:toggle_favorite', args=[self.property.slug]),
        )
        self.assertEqual(add_response.status_code, 302)
        self.assertTrue(
            PropertyFavorite.objects.filter(user=self.user, property=self.property).exists()
        )

        remove_response = self.client.post(
            reverse('properties:toggle_favorite', args=[self.property.slug]),
        )
        self.assertEqual(remove_response.status_code, 302)
        self.assertFalse(
            PropertyFavorite.objects.filter(user=self.user, property=self.property).exists()
        )


class PropertyDetailReviewCtaTests(TestCase):
    def setUp(self):
        self.host = User.objects.create_user(
            email='detail-host@example.com',
            password='testpass123',
            role=UserRole.HOST,
            country='ZW',
            is_email_verified=True,
        )
        self.guest = User.objects.create_user(
            email='detail-guest@example.com',
            password='testpass123',
            role=UserRole.CUSTOMER,
            country='ZW',
            is_email_verified=True,
        )
        property_type = PropertyType.objects.create(name='Lodge', slug='detail-lodge')
        self.property = Property.objects.create(
            name='Detail Lodge',
            slug='detail-lodge',
            description='Property used for detail page review CTA tests.',
            property_type=property_type,
            address='5 River Road',
            city='Kariba',
            postal_code='0001',
            country='ZW',
            owner=self.host,
            status=PropertyStatus.APPROVED,
            is_verified=True,
            minimum_price=Decimal('150.00'),
        )

    def test_property_detail_renders_without_review_cta_for_non_guest(self):
        self.client.force_login(self.guest)

        response = self.client.get(reverse('properties:detail', args=[self.property.slug]))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Write a review')

    def test_property_detail_shows_review_cta_for_completed_booking(self):
        booking = Booking.objects.create(
            user=self.guest,
            property=self.property,
            check_in_date=timezone.now().date() - timezone.timedelta(days=4),
            check_out_date=timezone.now().date() - timezone.timedelta(days=2),
            guests=2,
            price_per_night=Decimal('150.00'),
            total_amount=Decimal('300.00'),
            payment_option=Booking.PaymentOption.CARD,
            payment_status=Booking.PaymentStatus.PAID,
            status=Booking.BookingStatus.COMPLETED,
        )
        self.client.force_login(self.guest)

        response = self.client.get(reverse('properties:detail', args=[self.property.slug]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse('reviews:review_create', args=[booking.id]))


class PropertyDetailRoomRateTableTests(TestCase):
    def setUp(self):
        self.host = User.objects.create_user(
            email='rates-host@example.com',
            password='testpass123',
            role=UserRole.HOST,
            country='ZW',
            is_email_verified=True,
        )
        self.guest = User.objects.create_user(
            email='rates-guest@example.com',
            password='testpass123',
            role=UserRole.CUSTOMER,
            country='ZW',
            is_email_verified=True,
        )
        property_type = PropertyType.objects.create(name='Camp', slug='rate-camp')
        self.property = Property.objects.create(
            name='Rate Table Camp',
            slug='rate-table-camp',
            description='Property used for detail rate table tests.',
            property_type=property_type,
            address='77 Plains Road',
            city='Hwange',
            postal_code='0001',
            country='ZW',
            owner=self.host,
            status=PropertyStatus.APPROVED,
            is_verified=True,
            minimum_price=Decimal('100.00'),
        )
        self.room = RoomType.objects.create(
            property=self.property,
            name='Savanna Suite',
            base_price=Decimal('100.00'),
            quantity_available=2,
            max_adults=2,
            max_children=1,
            max_occupancy=3,
        )

    def test_property_detail_displays_computed_room_rate_row(self):
        today = timezone.now().date()
        days_until_next_monday = (7 - today.weekday()) % 7 or 7
        check_in = today + timezone.timedelta(days=days_until_next_monday)
        check_out = check_in + timezone.timedelta(days=3)

        PricePlan.objects.create(
            room_type=self.room,
            name='Flexible Breakfast Rate',
            base_price=Decimal('100.00'),
            min_nights=1,
            cancellation_days=3,
            extra_person_charge=Decimal('20.00'),
            breakfast_included=True,
            taxes_included=False,
            start_date=check_in - timezone.timedelta(days=5),
            end_date=check_out + timezone.timedelta(days=5),
            weekday_multiplier=Decimal('1.00'),
            weekend_multiplier=Decimal('1.00'),
        )

        Booking.objects.create(
            user=self.guest,
            property=self.property,
            room_type=self.room,
            check_in_date=check_in,
            check_out_date=check_out,
            guests=2,
            price_per_night=Decimal('100.00'),
            total_amount=Decimal('300.00'),
            payment_option=Booking.PaymentOption.CARD,
            payment_status=Booking.PaymentStatus.PAID,
            status=Booking.BookingStatus.CONFIRMED,
        )

        response = self.client.get(
            reverse('properties:detail', args=[self.property.slug]),
            {
                'check_in': check_in.isoformat(),
                'check_out': check_out.isoformat(),
                'guests': 3,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Savanna Suite')
        self.assertContains(response, 'Breakfast included')
        self.assertContains(response, 'Free cancellation up to 3 days before check-in')
        self.assertContains(response, '$43.20 est.')
        self.assertContains(response, '$403.20')
        self.assertContains(response, '1 room left')
