from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase
from django.test.utils import override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User, UserRole
from bookings.models import Booking
from properties.models import Property, PropertyStatus, PropertyType

from .models import CommissionPayment, PaymentGateway, PayoutAccount, Transaction


@override_settings(BOOKING_ALLOW_SIMULATED_PAYMENTS=True)
class BookingCheckoutTests(TestCase):
    def setUp(self):
        self.host = User.objects.create_user(
            email='host-payments@example.com',
            password='testpass123',
            role=UserRole.HOST,
            country='ZW',
            is_email_verified=True,
        )
        self.guest = User.objects.create_user(
            email='guest-payments@example.com',
            password='testpass123',
            role=UserRole.CUSTOMER,
            country='US',
            is_email_verified=True,
        )

        property_type = PropertyType.objects.create(
            name='Lodge',
            slug='payments-lodge',
            is_active=True,
        )
        self.property = Property.objects.create(
            name='Payment Flow Lodge',
            slug='payment-flow-lodge',
            description='Testing payment checkout flow.',
            property_type=property_type,
            address='1 River Road',
            city='Victoria Falls',
            postal_code='0001',
            country='ZW',
            owner=self.host,
            status=PropertyStatus.APPROVED,
            is_verified=True,
            minimum_price=Decimal('120.00'),
        )

        self.booking = Booking.objects.create(
            user=self.guest,
            property=self.property,
            check_in_date=timezone.now().date() + timedelta(days=3),
            check_out_date=timezone.now().date() + timedelta(days=5),
            guests=2,
            price_per_night=Decimal('120.00'),
            total_amount=Decimal('240.00'),
            payment_option=Booking.PaymentOption.CARD,
            payment_status=Booking.PaymentStatus.PENDING,
            status=Booking.BookingStatus.PENDING,
        )

    def test_checkout_creates_transaction_and_marks_booking_paid(self):
        self.client.force_login(self.guest)

        response = self.client.post(
            reverse('payments:booking_checkout', args=[self.booking.id]),
            data={
                'payment_option': Booking.PaymentOption.CARD,
                'card_number': '4242 4242 4242 4242',
                'card_name': 'Guest Payments',
                'card_expiry_month': '12',
                'card_expiry_year': str(timezone.now().year + 1),
                'card_cvv': '123',
                'accept_terms': 'on',
            },
        )

        self.assertRedirects(response, reverse('bookings:detail', args=[self.booking.id]))

        self.booking.refresh_from_db()
        self.assertEqual(self.booking.payment_status, Booking.PaymentStatus.PAID)
        self.assertEqual(self.booking.status, Booking.BookingStatus.CONFIRMED)

        txn = Transaction.objects.get(booking=self.booking, customer=self.guest, transaction_type='payment')
        self.assertEqual(txn.status, 'completed')
        self.assertEqual(txn.amount, Decimal('240.00'))
        self.assertEqual(txn.metadata.get('card_last_four'), '4242')

        commission_payment = CommissionPayment.objects.get(booking=self.booking, recipient=self.host)
        self.assertEqual(commission_payment.amount, self.booking.host_payout_amount)
        self.assertEqual(commission_payment.commission_amount, self.booking.commission_amount)

    def test_checkout_for_other_user_booking_returns_404(self):
        other_user = User.objects.create_user(
            email='other-payments@example.com',
            password='testpass123',
            role=UserRole.CUSTOMER,
            country='ZW',
            is_email_verified=True,
        )
        self.client.force_login(other_user)

        response = self.client.get(reverse('payments:booking_checkout', args=[self.booking.id]))
        self.assertEqual(response.status_code, 404)

    def test_checkout_rejects_invalid_card_number(self):
        self.client.force_login(self.guest)

        response = self.client.post(
            reverse('payments:booking_checkout', args=[self.booking.id]),
            data={
                'payment_option': Booking.PaymentOption.CARD,
                'card_number': '1111 1111 1111 1111',
                'card_name': 'Guest Payments',
                'card_expiry_month': '12',
                'card_expiry_year': str(timezone.now().year + 1),
                'card_cvv': '123',
                'accept_terms': 'on',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Please enter a valid card number')

        self.booking.refresh_from_db()
        self.assertEqual(self.booking.payment_status, Booking.PaymentStatus.PENDING)
        self.assertFalse(Transaction.objects.filter(booking=self.booking).exists())

    @override_settings(BOOKING_ALLOW_SKIP_PAYMENT=True)
    def test_checkout_allows_skip_payment_in_testing_mode(self):
        self.client.force_login(self.guest)

        response = self.client.post(
            reverse('payments:booking_checkout', args=[self.booking.id]),
            data={
                'payment_option': 'skip',
                'accept_terms': 'on',
            },
        )

        self.assertRedirects(response, reverse('bookings:detail', args=[self.booking.id]))

        self.booking.refresh_from_db()
        self.assertEqual(self.booking.payment_status, Booking.PaymentStatus.PAID)
        self.assertEqual(self.booking.status, Booking.BookingStatus.CONFIRMED)

        txn = Transaction.objects.get(booking=self.booking, customer=self.guest, transaction_type='payment')
        self.assertEqual(txn.status, 'completed')
        self.assertEqual(txn.metadata.get('skip_reason'), 'testing_only')

    def test_bank_transfer_keeps_booking_pending_payment(self):
        self.client.force_login(self.guest)

        response = self.client.post(
            reverse('payments:booking_checkout', args=[self.booking.id]),
            data={
                'payment_option': Booking.PaymentOption.BANK_TRANSFER,
                'accept_terms': 'on',
            },
        )

        self.assertRedirects(response, reverse('bookings:detail', args=[self.booking.id]))

        self.booking.refresh_from_db()
        self.assertEqual(self.booking.payment_status, Booking.PaymentStatus.PENDING)
        self.assertEqual(self.booking.status, Booking.BookingStatus.PENDING)

        txn = Transaction.objects.get(booking=self.booking, customer=self.guest, transaction_type='payment')
        self.assertEqual(txn.status, 'processing')
        self.assertFalse(CommissionPayment.objects.filter(booking=self.booking).exists())

    @override_settings(BOOKING_ALLOW_SIMULATED_PAYMENTS=False)
    def test_checkout_blocks_unconfigured_card_gateway_when_simulation_disabled(self):
        self.client.force_login(self.guest)

        response = self.client.post(
            reverse('payments:booking_checkout', args=[self.booking.id]),
            data={
                'payment_option': Booking.PaymentOption.CARD,
                'card_number': '4242 4242 4242 4242',
                'card_name': 'Guest Payments',
                'card_expiry_month': '12',
                'card_expiry_year': str(timezone.now().year + 1),
                'card_cvv': '123',
                'accept_terms': 'on',
            },
        )

        self.assertRedirects(response, reverse('payments:booking_checkout', args=[self.booking.id]))
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.payment_status, Booking.PaymentStatus.PENDING)
        self.assertFalse(Transaction.objects.filter(booking=self.booking).exists())

    @override_settings(STRIPE_ENABLED=True, STRIPE_SECRET_KEY='sk_test_dummy', STRIPE_PUBLIC_KEY='pk_test_dummy')
    @patch('payments.views.stripe.checkout.Session.create')
    def test_card_checkout_redirects_to_stripe_hosted_checkout(self, mock_stripe_create):
        self.client.force_login(self.guest)
        mock_stripe_create.return_value = SimpleNamespace(
            id='cs_test_123',
            url='https://checkout.stripe.com/c/pay/cs_test_123',
            payment_status='unpaid',
        )

        response = self.client.post(
            reverse('payments:booking_checkout', args=[self.booking.id]),
            data={
                'payment_option': Booking.PaymentOption.CARD,
                'accept_terms': 'on',
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, 'https://checkout.stripe.com/c/pay/cs_test_123')

        self.booking.refresh_from_db()
        self.assertEqual(self.booking.payment_status, Booking.PaymentStatus.PENDING)
        self.assertEqual(self.booking.payment_option, Booking.PaymentOption.CARD)

        txn = Transaction.objects.get(booking=self.booking, customer=self.guest, transaction_type='payment')
        self.assertEqual(txn.status, 'pending')
        self.assertEqual(txn.gateway.gateway_type, 'stripe')
        self.assertEqual(txn.gateway_transaction_id, 'cs_test_123')

    @override_settings(STRIPE_ENABLED=True, STRIPE_SECRET_KEY='sk_test_dummy', STRIPE_PUBLIC_KEY='pk_test_dummy')
    @patch('payments.views.stripe.checkout.Session.retrieve')
    def test_stripe_success_marks_booking_paid(self, mock_stripe_retrieve):
        self.client.force_login(self.guest)
        gateway = PaymentGateway.objects.create(
            name='Stripe Hosted Checkout',
            gateway_type='stripe',
            is_active=True,
            is_test_mode=True,
            supported_currencies=['USD'],
        )
        txn = Transaction.objects.create(
            amount=self.booking.total_amount,
            currency='USD',
            transaction_type='payment',
            gateway=gateway,
            customer=self.guest,
            booking=self.booking,
            status='pending',
            gateway_transaction_id='cs_test_success',
            description='Stripe checkout initialized',
        )
        mock_stripe_retrieve.return_value = SimpleNamespace(
            id='cs_test_success',
            payment_status='paid',
            status='complete',
        )

        response = self.client.get(
            f"{reverse('payments:stripe_checkout_success', args=[self.booking.id])}?session_id=cs_test_success"
        )

        self.assertRedirects(response, reverse('bookings:detail', args=[self.booking.id]))

        self.booking.refresh_from_db()
        self.assertEqual(self.booking.payment_status, Booking.PaymentStatus.PAID)
        self.assertEqual(self.booking.status, Booking.BookingStatus.CONFIRMED)

        txn.refresh_from_db()
        self.assertEqual(txn.status, 'completed')
        self.assertTrue(CommissionPayment.objects.filter(booking=self.booking, recipient=self.host).exists())

    @override_settings(
        STRIPE_ENABLED=True,
        STRIPE_SECRET_KEY='sk_test_dummy',
        STRIPE_PUBLIC_KEY='pk_test_dummy',
        AUTO_EXECUTE_LISTER_PAYOUTS=True,
    )
    @patch('payments.views.stripe.Transfer.create')
    @patch('payments.views.stripe.checkout.Session.retrieve')
    def test_stripe_success_auto_disburses_lister_payout(self, mock_stripe_retrieve, mock_transfer_create):
        self.client.force_login(self.guest)
        gateway = PaymentGateway.objects.create(
            name='Stripe Hosted Checkout',
            gateway_type='stripe',
            is_active=True,
            is_test_mode=True,
            supported_currencies=['USD'],
        )
        Transaction.objects.create(
            amount=self.booking.total_amount,
            currency='USD',
            transaction_type='payment',
            gateway=gateway,
            customer=self.guest,
            booking=self.booking,
            status='pending',
            gateway_transaction_id='cs_test_disburse',
            description='Stripe checkout initialized',
        )
        PayoutAccount.objects.create(
            user=self.host,
            account_type='stripe',
            account_name='Host Connect',
            account_id='acct_123456789',
            is_verified=True,
            is_default=True,
            is_active=True,
        )

        mock_stripe_retrieve.return_value = SimpleNamespace(
            id='cs_test_disburse',
            payment_status='paid',
            status='complete',
        )
        mock_transfer_create.return_value = SimpleNamespace(id='tr_123456')

        response = self.client.get(
            f"{reverse('payments:stripe_checkout_success', args=[self.booking.id])}?session_id=cs_test_disburse"
        )
        self.assertRedirects(response, reverse('bookings:detail', args=[self.booking.id]))

        commission_payment = CommissionPayment.objects.get(booking=self.booking, recipient=self.host)
        self.assertEqual(commission_payment.status, 'paid')
        self.assertEqual(commission_payment.transaction_id, 'tr_123456')
        self.assertTrue(mock_transfer_create.called)

    @override_settings(STRIPE_ENABLED=True, STRIPE_SECRET_KEY='sk_test_dummy', STRIPE_PUBLIC_KEY='pk_test_dummy')
    def test_stripe_cancel_marks_pending_transaction_cancelled(self):
        self.client.force_login(self.guest)
        gateway = PaymentGateway.objects.create(
            name='Stripe Hosted Checkout',
            gateway_type='stripe',
            is_active=True,
            is_test_mode=True,
            supported_currencies=['USD'],
        )
        txn = Transaction.objects.create(
            amount=self.booking.total_amount,
            currency='USD',
            transaction_type='payment',
            gateway=gateway,
            customer=self.guest,
            booking=self.booking,
            status='pending',
            gateway_transaction_id='cs_test_cancel',
            description='Stripe checkout initialized',
        )

        response = self.client.get(reverse('payments:stripe_checkout_cancel', args=[self.booking.id]))
        self.assertRedirects(response, reverse('bookings:detail', args=[self.booking.id]))

        self.booking.refresh_from_db()
        self.assertEqual(self.booking.payment_status, Booking.PaymentStatus.PENDING)

        txn.refresh_from_db()
        self.assertEqual(txn.status, 'cancelled')

    @override_settings(
        PAYNOW_ENABLED=True,
        PAYNOW_INTEGRATION_ID='123456',
        PAYNOW_INTEGRATION_KEY='integration-key',
    )
    @patch('payments.views._initiate_paynow_payment')
    def test_paynow_checkout_redirects_to_gateway(self, mock_paynow_init):
        self.client.force_login(self.guest)
        mock_paynow_init.return_value = {
            'success': True,
            'redirect_url': 'https://www.paynow.co.zw/interface/initiatetransaction/?id=abc',
            'poll_url': 'https://www.paynow.co.zw/interface/checktransaction/?guid=abc',
        }

        response = self.client.post(
            reverse('payments:booking_checkout', args=[self.booking.id]),
            data={
                'payment_option': Booking.PaymentOption.PAYNOW,
                'accept_terms': 'on',
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, 'https://www.paynow.co.zw/interface/initiatetransaction/?id=abc')

        self.booking.refresh_from_db()
        self.assertEqual(self.booking.payment_option, Booking.PaymentOption.PAYNOW)
        self.assertEqual(self.booking.payment_status, Booking.PaymentStatus.PENDING)

        txn = Transaction.objects.get(booking=self.booking, customer=self.guest, transaction_type='payment')
        self.assertEqual(txn.status, 'pending')
        self.assertEqual(txn.metadata.get('paynow_poll_url'), 'https://www.paynow.co.zw/interface/checktransaction/?guid=abc')

    @override_settings(
        PAYNOW_ENABLED=True,
        PAYNOW_INTEGRATION_ID='123456',
        PAYNOW_INTEGRATION_KEY='integration-key',
    )
    @patch('payments.views._refresh_paynow_transaction')
    def test_paynow_return_uses_refresh_helper(self, mock_refresh):
        self.client.force_login(self.guest)
        gateway = PaymentGateway.objects.create(
            name='Paynow Redirect Checkout',
            gateway_type='offline',
            is_active=True,
            is_test_mode=True,
            supported_currencies=['USD'],
        )
        Transaction.objects.create(
            amount=self.booking.total_amount,
            currency='USD',
            transaction_type='payment',
            gateway=gateway,
            customer=self.guest,
            booking=self.booking,
            status='pending',
            description='Paynow initialized',
            metadata={'paynow_poll_url': 'https://www.paynow.co.zw/interface/checktransaction/?guid=abc'},
        )
        mock_refresh.return_value = True

        response = self.client.get(reverse('payments:paynow_checkout_return', args=[self.booking.id]))
        self.assertRedirects(response, reverse('bookings:detail', args=[self.booking.id]))
        self.assertTrue(mock_refresh.called)
