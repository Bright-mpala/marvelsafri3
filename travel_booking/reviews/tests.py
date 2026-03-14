from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User, UserRole
from bookings.models import Booking
from properties.models import Property, PropertyStatus, PropertyType

from .models import Review, ReviewHelpful


class ReviewListTests(TestCase):
    def setUp(self):
        self.host = User.objects.create_user(
            email='host-reviews@example.com',
            password='testpass123',
            role=UserRole.HOST,
            country='ZW',
            is_email_verified=True,
        )
        self.guest = User.objects.create_user(
            email='guest-reviews@example.com',
            password='testpass123',
            role=UserRole.CUSTOMER,
            country='US',
            is_email_verified=True,
        )

        property_type = PropertyType.objects.create(
            name='Camp',
            slug='reviews-camp',
            is_active=True,
        )
        self.property = Property.objects.create(
            name='Review Test Camp',
            slug='review-test-camp',
            description='Property used for review list tests.',
            property_type=property_type,
            address='1 Safari Road',
            city='Victoria Falls',
            postal_code='0001',
            country='ZW',
            owner=self.host,
            status=PropertyStatus.APPROVED,
            is_verified=True,
            minimum_price=Decimal('110.00'),
        )

        completed_check_in = timezone.now().date() - timedelta(days=8)
        completed_check_out = timezone.now().date() - timedelta(days=6)

        booking_one = Booking.objects.create(
            user=self.guest,
            property=self.property,
            check_in_date=completed_check_in,
            check_out_date=completed_check_out,
            guests=2,
            price_per_night=Decimal('110.00'),
            total_amount=Decimal('220.00'),
            payment_option=Booking.PaymentOption.CARD,
            payment_status=Booking.PaymentStatus.PAID,
            status=Booking.BookingStatus.COMPLETED,
        )

        self.review_one = Review.objects.create(
            booking=booking_one,
            user=self.guest,
            property=self.property,
            overall_rating=Decimal('4.5'),
            title='Excellent stay',
            comment='Everything was clean and the team was very welcoming.',
            is_published=True,
            is_verified=True,
        )

        guest_two = User.objects.create_user(
            email='guest-reviews-2@example.com',
            password='testpass123',
            role=UserRole.CUSTOMER,
            country='ZW',
            is_email_verified=True,
        )
        booking_two = Booking.objects.create(
            user=guest_two,
            property=self.property,
            check_in_date=completed_check_in - timedelta(days=4),
            check_out_date=completed_check_out - timedelta(days=4),
            guests=2,
            price_per_night=Decimal('110.00'),
            total_amount=Decimal('220.00'),
            payment_option=Booking.PaymentOption.CARD,
            payment_status=Booking.PaymentStatus.PAID,
            status=Booking.BookingStatus.COMPLETED,
        )

        self.review_two = Review.objects.create(
            booking=booking_two,
            user=guest_two,
            property=self.property,
            overall_rating=Decimal('4.0'),
            title='Good but noisy',
            comment='Helpful staff, though nights were slightly noisy.',
            is_published=True,
            is_verified=True,
        )

        voter_one = User.objects.create_user(
            email='voter-1@example.com',
            password='testpass123',
            role=UserRole.CUSTOMER,
            country='ZW',
            is_email_verified=True,
        )
        voter_two = User.objects.create_user(
            email='voter-2@example.com',
            password='testpass123',
            role=UserRole.CUSTOMER,
            country='ZW',
            is_email_verified=True,
        )
        ReviewHelpful.objects.create(review=self.review_two, user=voter_one, is_helpful=True)
        ReviewHelpful.objects.create(review=self.review_two, user=voter_two, is_helpful=True)

    def test_review_list_page_renders(self):
        response = self.client.get(reverse('reviews:review_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Guest Reviews')
        self.assertContains(response, self.review_one.title)

    def test_review_list_allows_most_helpful_sort(self):
        response = self.client.get(reverse('reviews:review_list'), {'sort': '-helpful_votes'})
        self.assertEqual(response.status_code, 200)
        page_obj = response.context['page_obj']
        self.assertEqual(page_obj.object_list[0].pk, self.review_two.pk)
