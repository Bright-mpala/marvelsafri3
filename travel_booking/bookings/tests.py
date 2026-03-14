from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User, UserRole
from core.exceptions import InvalidDataError
from payments.models import PaymentGateway, Refund, Transaction
from properties.models import Property, PropertyStatus, PropertyType, RoomType

from .models import Booking
from .services import BookingService


class BookingCommissionTests(TestCase):
    def setUp(self):
        self.zimbabwe_host = User.objects.create_user(
            email='zw-host@example.com',
            password='testpass123',
            role=UserRole.HOST,
            country='ZW',
        )
        self.outside_host = User.objects.create_user(
            email='outside-host@example.com',
            password='testpass123',
            role=UserRole.HOST,
            country='US',
        )
        self.local_guest = User.objects.create_user(
            email='guest-local@example.com',
            password='testpass123',
            country='ZW',
        )
        self.away_guest = User.objects.create_user(
            email='guest-away@example.com',
            password='testpass123',
            country='US',
        )

        property_type = PropertyType.objects.create(
            name='Lodge',
            slug='lodge',
            is_active=True,
        )
        self.zimbabwe_property = Property.objects.create(
            name='Zambezi Lodge',
            slug='zambezi-lodge',
            description='Comfortable riverside lodge for safari travelers.',
            property_type=property_type,
            address='1 River Road',
            city='Victoria Falls',
            postal_code='0001',
            country='ZW',
            owner=self.zimbabwe_host,
            status=PropertyStatus.APPROVED,
            minimum_price=Decimal('100.00'),
        )
        self.outside_property = Property.objects.create(
            name='Namib Desert Camp',
            slug='namib-desert-camp',
            description='Desert camp operated by an outside lister.',
            property_type=property_type,
            address='4 Dune Street',
            city='Swakopmund',
            postal_code='1000',
            country='NA',
            owner=self.outside_host,
            status=PropertyStatus.APPROVED,
            minimum_price=Decimal('100.00'),
        )

    def test_zimbabwe_lister_booking_uses_ten_percent_commission(self):
        booking = Booking.objects.create(
            user=self.local_guest,
            property=self.zimbabwe_property,
            check_in_date=timezone.now().date() + timedelta(days=3),
            check_out_date=timezone.now().date() + timedelta(days=5),
            guests=2,
            price_per_night=Decimal('100.00'),
            payment_option=Booking.PaymentOption.CARD,
        )

        self.assertEqual(booking.total_price, Decimal('200.00'))
        self.assertEqual(booking.commission_type, Booking.CommissionType.LOCAL)
        self.assertEqual(booking.commission_rate, Decimal('10.00'))
        self.assertEqual(booking.platform_commission, Decimal('20.00'))
        self.assertEqual(booking.owner_payout, Decimal('180.00'))

    def test_outside_lister_booking_uses_fifteen_percent_commission(self):
        booking = Booking.objects.create(
            user=self.away_guest,
            property=self.outside_property,
            check_in_date=timezone.now().date() + timedelta(days=6),
            check_out_date=timezone.now().date() + timedelta(days=8),
            guests=2,
            price_per_night=Decimal('100.00'),
            payment_option=Booking.PaymentOption.PAYNOW,
        )

        self.assertEqual(booking.total_price, Decimal('200.00'))
        self.assertEqual(booking.commission_type, Booking.CommissionType.AWAY)
        self.assertEqual(booking.commission_rate, Decimal('15.00'))
        self.assertEqual(booking.platform_commission, Decimal('30.00'))
        self.assertEqual(booking.owner_payout, Decimal('170.00'))


class BookingModifyFlowTests(TestCase):
    def setUp(self):
        self.host = User.objects.create_user(
            email='modify-host@example.com',
            password='testpass123',
            role=UserRole.HOST,
            country='ZW',
            is_email_verified=True,
        )
        self.guest = User.objects.create_user(
            email='modify-guest@example.com',
            password='testpass123',
            country='US',
            is_email_verified=True,
        )
        property_type = PropertyType.objects.create(
            name='Hotel',
            slug='modify-hotel',
            is_active=True,
        )
        self.property = Property.objects.create(
            name='Modify Hotel',
            slug='modify-hotel',
            description='Property for booking modify tests.',
            property_type=property_type,
            address='77 Sunset Avenue',
            city='Harare',
            postal_code='0001',
            country='ZW',
            owner=self.host,
            status=PropertyStatus.APPROVED,
            is_verified=True,
            minimum_price=Decimal('80.00'),
        )

        self.booking = Booking.objects.create(
            user=self.guest,
            property=self.property,
            check_in_date=timezone.now().date() + timedelta(days=5),
            check_out_date=timezone.now().date() + timedelta(days=7),
            guests=2,
            price_per_night=Decimal('80.00'),
            total_amount=Decimal('160.00'),
            payment_option=Booking.PaymentOption.CARD,
            payment_status=Booking.PaymentStatus.PAID,
            status=Booking.BookingStatus.CONFIRMED,
        )

    def test_modify_booking_reopens_payment_when_amount_changes(self):
        self.client.force_login(self.guest)
        response = self.client.post(
            reverse('bookings:modify', args=[self.booking.id]),
            data={
                'check_in_date': timezone.now().date() + timedelta(days=5),
                'check_out_date': timezone.now().date() + timedelta(days=9),
                'guests': 2,
                'special_requests': 'Late check-in',
            },
        )

        self.assertRedirects(response, reverse('bookings:detail', args=[self.booking.id]))

        self.booking.refresh_from_db()
        self.assertEqual(self.booking.total_amount, Decimal('320.00'))
        self.assertEqual(self.booking.payment_status, Booking.PaymentStatus.PENDING)
        self.assertEqual(self.booking.status, Booking.BookingStatus.PENDING)


class RoomAwareBookingTests(TestCase):
    def setUp(self):
        self.host = User.objects.create_user(
            email='room-host@example.com',
            password='testpass123',
            role=UserRole.HOST,
            country='ZW',
        )
        self.guest = User.objects.create_user(
            email='room-guest@example.com',
            password='testpass123',
            country='US',
        )
        property_type = PropertyType.objects.create(
            name='Safari Camp',
            slug='safari-camp',
            is_active=True,
        )
        self.property = Property.objects.create(
            name='Room Aware Camp',
            slug='room-aware-camp',
            description='Property with multiple room types.',
            property_type=property_type,
            address='9 Delta Road',
            city='Kasane',
            postal_code='0001',
            country='BW',
            owner=self.host,
            status=PropertyStatus.APPROVED,
            minimum_price=Decimal('90.00'),
            total_rooms=8,
        )
        self.standard_room = RoomType.objects.create(
            property=self.property,
            name='Standard Tent',
            base_price=Decimal('125.00'),
            quantity_available=2,
            max_occupancy=2,
            max_adults=2,
            max_children=0,
        )
        self.suite_room = RoomType.objects.create(
            property=self.property,
            name='River Suite',
            base_price=Decimal('240.00'),
            quantity_available=1,
            max_occupancy=4,
            max_adults=2,
            max_children=2,
        )

    def test_service_prices_booking_from_selected_room_type(self):
        booking = BookingService().create_booking(
            user=self.guest,
            property_id=self.property.id,
            room_type_id=self.suite_room.id,
            check_in_date=timezone.now().date() + timezone.timedelta(days=10),
            check_out_date=timezone.now().date() + timezone.timedelta(days=13),
            guests=2,
            special_requests='',
            payment_option=Booking.PaymentOption.CARD,
        )

        self.assertEqual(booking.room_type, self.suite_room)
        self.assertEqual(booking.price_per_night, Decimal('240.00'))
        self.assertEqual(booking.total_amount, Decimal('720.00'))

    def test_inventory_is_validated_per_room_type(self):
        check_in = timezone.now().date() + timezone.timedelta(days=15)
        check_out = timezone.now().date() + timezone.timedelta(days=17)
        for index in range(2):
            guest = User.objects.create_user(
                email=f'standard-{index}@example.com',
                password='testpass123',
                country='US',
            )
            Booking.objects.create(
                user=guest,
                property=self.property,
                room_type=self.standard_room,
                check_in_date=check_in,
                check_out_date=check_out,
                guests=2,
                price_per_night=Decimal('125.00'),
                payment_option=Booking.PaymentOption.CARD,
                status=Booking.BookingStatus.CONFIRMED,
            )

        suite_booking = BookingService().create_booking(
            user=self.guest,
            property_id=self.property.id,
            room_type_id=self.suite_room.id,
            check_in_date=check_in,
            check_out_date=check_out,
            guests=2,
            special_requests='',
            payment_option=Booking.PaymentOption.CARD,
        )
        self.assertEqual(suite_booking.room_type, self.suite_room)

        with self.assertRaises(InvalidDataError):
            BookingService().create_booking(
                user=User.objects.create_user(
                    email='overflow@example.com',
                    password='testpass123',
                    country='US',
                ),
                property_id=self.property.id,
                room_type_id=self.standard_room.id,
                check_in_date=check_in,
                check_out_date=check_out,
                guests=2,
                special_requests='',
                payment_option=Booking.PaymentOption.CARD,
            )


class BookingManagementViewTests(TestCase):
    def setUp(self):
        self.host = User.objects.create_user(
            email='manage-host@example.com',
            password='testpass123',
            role=UserRole.HOST,
            country='ZW',
        )
        self.guest = User.objects.create_user(
            email='manage-guest@example.com',
            password='testpass123',
            country='US',
        )
        property_type = PropertyType.objects.create(
            name='Camp',
            slug='camp',
            is_active=True,
        )
        self.property = Property.objects.create(
            name='Zebra Plains Camp',
            slug='zebra-plains-camp',
            description='A booking management test property.',
            property_type=property_type,
            address='2 Safari Way',
            city='Maun',
            postal_code='0001',
            country='BW',
            owner=self.host,
            status=PropertyStatus.APPROVED,
            minimum_price=Decimal('150.00'),
        )
        self.room_type = RoomType.objects.create(
            property=self.property,
            name='Deluxe Tent',
            base_price=Decimal('175.00'),
            quantity_available=5,
            max_occupancy=3,
            max_adults=2,
            max_children=1,
        )
        self.gateway = PaymentGateway.objects.create(
            name='Offline',
            gateway_type='offline',
            is_active=True,
        )

        self.bookings = []
        for index in range(9):
            booking = Booking.objects.create(
                user=self.guest,
                property=self.property,
                room_type=self.room_type,
                check_in_date=timezone.now().date() + timedelta(days=10 + index),
                check_out_date=timezone.now().date() + timedelta(days=12 + index),
                guests=2,
                price_per_night=Decimal('175.00'),
                total_amount=Decimal('350.00'),
                payment_option=Booking.PaymentOption.CARD,
                payment_status=Booking.PaymentStatus.PAID if index == 0 else Booking.PaymentStatus.PENDING,
                status=Booking.BookingStatus.CONFIRMED if index == 0 else Booking.BookingStatus.PENDING,
            )
            self.bookings.append(booking)

        self.paid_booking = self.bookings[0]
        self.cancelled_booking = self.bookings[1]
        self.cancelled_booking.status = Booking.BookingStatus.CANCELLED
        self.cancelled_booking.payment_status = Booking.PaymentStatus.PAID
        self.cancelled_booking.save(update_fields=['status', 'payment_status'])

        self.transaction = Transaction.objects.create(
            amount=Decimal('350.00'),
            currency='USD',
            transaction_type='payment',
            gateway=self.gateway,
            customer=self.guest,
            booking=self.cancelled_booking,
            status='completed',
        )
        Refund.objects.create(
            transaction=self.transaction,
            amount=Decimal('350.00'),
            currency='USD',
            reason='cancellation',
            status='completed',
            refund_reference='REF-MGMT-0001',
        )

    def test_booking_list_supports_search_sort_and_pagination(self):
        self.client.force_login(self.guest)
        response = self.client.get(
            reverse('bookings:list'),
            {'q': 'Zebra', 'sort': 'price_low', 'page': 2},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Page 2 of 2')
        self.assertEqual(response.context['search_query'], 'Zebra')
        self.assertEqual(response.context['sort_key'], 'price_low')
        self.assertEqual(response.context['bookings'].number, 2)

    def test_booking_detail_shows_refund_summary(self):
        self.client.force_login(self.guest)
        response = self.client.get(reverse('bookings:detail', args=[self.cancelled_booking.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Refunded in full')
        self.assertContains(response, 'Download confirmation')
        self.assertContains(response, 'Download invoice')

    def test_rebook_redirects_with_prior_booking_details(self):
        self.client.force_login(self.guest)
        response = self.client.get(reverse('bookings:rebook', args=[self.paid_booking.id]))

        self.assertEqual(response.status_code, 302)
        self.assertIn('room_type=', response['Location'])
        self.assertIn('guests=2', response['Location'])

    def test_confirmation_and_invoice_downloads_return_attachments(self):
        self.client.force_login(self.guest)

        confirmation = self.client.get(reverse('bookings:download_confirmation', args=[self.paid_booking.id]))
        invoice = self.client.get(reverse('bookings:download_invoice', args=[self.paid_booking.id]))

        self.assertEqual(confirmation.status_code, 200)
        self.assertIn('attachment; filename="booking-confirmation-', confirmation['Content-Disposition'])
        self.assertEqual(invoice.status_code, 200)
        self.assertIn('attachment; filename="booking-invoice-', invoice['Content-Disposition'])
