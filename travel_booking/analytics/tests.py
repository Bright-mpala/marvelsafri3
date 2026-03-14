from django.test import TestCase
from django.urls import reverse

from accounts.models import User, UserRole


class AnalyticsDashboardAuthTests(TestCase):
    def setUp(self):
        self.staff_user = User.objects.create_user(
            email='staff-analytics@example.com',
            password='testpass123',
            role=UserRole.ADMIN,
            country='ZW',
            is_email_verified=True,
            is_staff=True,
        )
        self.regular_user = User.objects.create_user(
            email='regular-analytics@example.com',
            password='testpass123',
            role=UserRole.CUSTOMER,
            country='ZW',
            is_email_verified=True,
        )

    def test_dashboard_requires_staff(self):
        self.client.force_login(self.regular_user)
        response = self.client.get(reverse('analytics:analytics_dashboard'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/?next=/analytics/', response.url)

    def test_dashboard_allows_staff(self):
        self.client.force_login(self.staff_user)
        response = self.client.get(reverse('analytics:analytics_dashboard'))
        self.assertEqual(response.status_code, 200)
