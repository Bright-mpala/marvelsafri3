import hashlib

from django.contrib.auth import authenticate, get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.authentication import AuthenticationService, CustomTokenObtainPairSerializer
from accounts.models import UserRole
from accounts.utils import create_email_verification, verify_email_code
from car_rentals.models import Car, CarCategory, CarRentalCompany, CarStatus
from properties.models import Property, PropertyStatus, PropertyType
from tours.models import Tour, TourOperator


class TokenSerializerTests(TestCase):
    """Ensure JWT serializers emit role information."""

    def setUp(self):
        self.User = get_user_model()
        self.user = self.User.objects.create_user(
            email='host@example.com', password='pass1234', role=UserRole.HOST, is_email_verified=True
        )

    def test_token_obtain_includes_role_and_user(self):
        serializer = CustomTokenObtainPairSerializer(data={'email': self.user.email, 'password': 'pass1234'})
        self.assertTrue(serializer.is_valid(), serializer.errors)

        data = serializer.validated_data
        self.assertIn('access', data)
        self.assertIn('refresh', data)
        self.assertEqual(data.get('role'), UserRole.HOST)

        user_payload = data.get('user', {})
        self.assertEqual(user_payload.get('id'), str(self.user.id))
        self.assertEqual(user_payload.get('role'), UserRole.HOST)


class EmailAuthenticationTests(TestCase):
    """Email should be the canonical login field across auth entry points."""

    def setUp(self):
        self.User = get_user_model()
        self.user = self.User.objects.create_user(
            email='Host@Example.com',
            password='pass1234',
            role=UserRole.HOST,
            is_email_verified=True,
        )

    def test_model_backend_authenticates_with_email_kwarg(self):
        authenticated_user = authenticate(email='host@example.com', password='pass1234')

        self.assertIsNotNone(authenticated_user)
        self.assertEqual(authenticated_user.pk, self.user.pk)

    def test_authentication_service_uses_email_login(self):
        payload = AuthenticationService.login_user(email='host@example.com', password='pass1234')

        self.assertIn('access', payload)
        self.assertIn('refresh', payload)
        self.assertEqual(payload['user']['email'], self.user.email)


class EmailVerificationHashingTests(TestCase):
    """Verification codes should be hashed at rest and validated by hash."""

    def setUp(self):
        self.User = get_user_model()
        self.user = self.User.objects.create_user(
            email='verify@example.com',
            password='pass1234',
            is_email_verified=False,
        )

    def test_create_email_verification_stores_sha256_hash(self):
        verification, raw_code = create_email_verification(self.user)

        self.assertNotEqual(verification.code, raw_code)
        self.assertEqual(verification.code, hashlib.sha256(raw_code.encode('utf-8')).hexdigest())
        self.assertEqual(len(verification.code), 64)

    def test_verify_email_code_hashes_input_before_comparing(self):
        verification, raw_code = create_email_verification(self.user)

        success, message = verify_email_code(self.user, raw_code)
        verification.refresh_from_db()
        self.user.refresh_from_db()

        self.assertTrue(success, message)
        self.assertTrue(verification.is_used)
        self.assertTrue(self.user.is_email_verified)

    def test_verify_email_code_rejects_wrong_code(self):
        create_email_verification(self.user)

        success, message = verify_email_code(self.user, '000000')

        self.assertFalse(success)
        self.assertEqual(message, 'Invalid verification code.')


class DashboardOwnerVisibilityTests(TestCase):
    """Dashboard owner section should respect account type and listing approvals."""

    @classmethod
    def setUpTestData(cls):
        cls.User = get_user_model()
        cls.property_type = PropertyType.objects.create(name='Hotel', slug='hotel')
        cls.car_category = CarCategory.objects.create(name='Sedan', code='SED')
        cls.car_company = CarRentalCompany.objects.create(name='Acme Cars', code='ACME')

    def _create_user(self, email, **extra):
        defaults = {
            'password': 'pass1234',
            'is_email_verified': True,
        }
        defaults.update(extra)
        return self.User.objects.create_user(email=email, **defaults)

    def _create_property(self, owner, slug, status):
        return Property.objects.create(
            name=f'Property {slug}',
            slug=slug,
            description='Test property',
            property_type=self.property_type,
            address='123 Main St',
            city='Harare',
            postal_code='0000',
            country='ZW',
            owner=owner,
            status=status,
        )

    def _create_car(self, owner, plate, moderation_status):
        return Car.objects.create(
            owner=owner,
            company=self.car_company,
            category=self.car_category,
            make='Toyota',
            model='Corolla',
            year=2022,
            license_plate=plate,
            moderation_status=moderation_status,
        )

    def _create_tour(self, user, slug, is_active):
        operator = TourOperator.objects.create(
            user=user,
            name=f'Operator {slug}',
            slug=f'operator-{slug}',
            description='Test operator',
        )
        return Tour.objects.create(
            operator=operator,
            name=f'Tour {slug}',
            slug=f'tour-{slug}',
            description='Test tour',
            tour_type='guided',
            location='Victoria Falls',
            city='Victoria Falls',
            country='Zimbabwe',
            base_price='99.99',
            languages=['English'],
            schedule=['Daily'],
            highlights=['Scenic views'],
            is_active=is_active,
        )

    def test_non_business_non_admin_hides_owner_dashboard(self):
        user = self._create_user('regular@example.com', role=UserRole.HOST, is_business_account=False)
        self._create_property(user, 'regular-approved', PropertyStatus.APPROVED)
        self._create_car(user, 'REG-100', CarStatus.APPROVED)
        self._create_tour(user, 'regular-active', True)

        self.client.force_login(user)
        response = self.client.get(reverse('accounts:dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['is_owner'])
        self.assertEqual(response.context['owned_properties_count'], 0)
        self.assertEqual(response.context['owned_cars_count'], 0)
        self.assertEqual(response.context['owned_tours_count'], 0)
        self.assertEqual(response.context['total_listings'], 0)

    def test_business_non_admin_only_sees_approved_owner_listings(self):
        user = self._create_user('business@example.com', role=UserRole.HOST, is_business_account=True)

        self._create_property(user, 'biz-approved', PropertyStatus.APPROVED)
        self._create_property(user, 'biz-pending', PropertyStatus.PENDING)

        self._create_car(user, 'BIZ-100', CarStatus.APPROVED)
        self._create_car(user, 'BIZ-101', CarStatus.PENDING)

        self._create_tour(user, 'biz-active', True)
        self._create_tour(user, 'biz-inactive', False)

        self.client.force_login(user)
        response = self.client.get(reverse('accounts:dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['is_owner'])
        self.assertEqual(response.context['owned_properties_count'], 1)
        self.assertEqual(response.context['owned_cars_count'], 1)
        self.assertEqual(response.context['owned_tours_count'], 1)
        self.assertEqual(response.context['total_listings'], 3)

    def test_admin_can_see_all_owner_listings_without_business_flag(self):
        admin_user = self._create_user('admin@example.com', role=UserRole.ADMIN, is_business_account=False)

        self._create_property(admin_user, 'admin-approved', PropertyStatus.APPROVED)
        self._create_property(admin_user, 'admin-pending', PropertyStatus.PENDING)

        self._create_car(admin_user, 'ADM-100', CarStatus.APPROVED)
        self._create_car(admin_user, 'ADM-101', CarStatus.PENDING)

        self._create_tour(admin_user, 'admin-active', True)
        self._create_tour(admin_user, 'admin-inactive', False)

        self.client.force_login(admin_user)
        response = self.client.get(reverse('accounts:dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['is_owner'])
        self.assertEqual(response.context['owned_properties_count'], 2)
        self.assertEqual(response.context['owned_cars_count'], 2)
        self.assertEqual(response.context['owned_tours_count'], 2)
        self.assertEqual(response.context['total_listings'], 6)
