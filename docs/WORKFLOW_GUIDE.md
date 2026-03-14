# Development Workflow Guide

Quick reference for common development tasks and workflows.

---

## 👋 Getting Started (First Time)

```bash
# 1. Clone repository
git clone <repo-url>
cd travel_booking_platform

# 2. Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Copy environment variables
cp .env.example .env
# Edit .env with your database credentials

# 5. Create database and tables
python manage.py migrate

# 6. Create admin user
python manage.py createsuperuser

# 7. Start development server
export ENVIRONMENT=development  # Windows: set ENVIRONMENT=development
python manage.py runserver
```

---

## 🔄 Daily Workflow

### Start of Day

```bash
# Activate virtual environment
source venv/bin/activate

# Pull latest changes
git pull origin main

# Apply any new migrations
python manage.py migrate

# Start development server
python manage.py runserver

# In another terminal, start Celery worker (if needed)
celery -A travel_booking worker -l info

# In third terminal, start Celery Beat (if needed)
celery -A travel_booking beat -l info
```

### Making Changes

```bash
# Create feature branch
git checkout -b feature/add-email-verification

# Make code changes
# Edit files as needed

# Check for errors
python manage.py check

# Run tests
pytest

# Format code
black .

# Lint code
flake8 .
```

### During Development

```bash
# Django shell (test code)
python manage.py shell
>>> from bookings.services import BookingService
>>> service = BookingService()
>>> # test code here

# Inspect database
python manage.py dbshell

# Create migrations (after model changes)
python manage.py makemigrations

# Apply migrations
python manage.py migrate

# View migration status
python manage.py showmigrations

# Create test data
python manage.py loaddata fixtures/test_data.json
```

### Before Commit

```bash
# Run all tests
pytest --cov=travel_booking

# Format code
black .

# Lint
flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics

# Stage changes
git add .

# Commit with meaningful message
git commit -m "[PHASE4] Add email verification permission class

- Filter bookings by verified email only
- Add IsEmailVerified permission class
- Add tests for email verification check
- Fixes #456"

# Push to remote
git push origin feature/add-email-verification
```

---

## 🧪 Testing

### Run Tests

```bash
# All tests
pytest

# Specific test file
pytest tests/test_bookings.py

# Specific test class
pytest tests/test_bookings.py::TestBookingService

# Specific test method
pytest tests/test_bookings.py::TestBookingService::test_create_booking

# With coverage
pytest --cov=travel_booking --cov-report=html

# Watch mode (re-run on file change)
pytest-watch

# Verbose output
pytest -v

# Stop on first failure
pytest -x

# Show print statements
pytest -s
```

### Write Tests

```python
# tests/test_bookings.py

import pytest
from django.contrib.auth import get_user_model
from bookings.services import BookingService
from bookings.models import Booking

User = get_user_model()

@pytest.fixture
def user():
    """Create test user."""
    return User.objects.create_user(
        email='test@example.com',
        password='testpass123',
        first_name='John'
    )

@pytest.fixture
def property_obj():
    """Create test property."""
    from properties.models import Property
    return Property.objects.create(
        name='Test Property',
        owner_id=user().id,
        price_per_night=100
    )

@pytest.mark.django_db
def test_create_booking(user, property_obj):
    """Test booking creation."""
    service = BookingService()
    booking = service.create_booking(
        user=user,
        property_id=property_obj.id,
        check_in_date='2024-02-15',
        check_out_date='2024-02-20',
        guests=2
    )
    assert booking.user == user
    assert booking.property == property_obj
    assert booking.guests == 2
```

---

## 🔐 Security Development

### Adding Permission Class

```python
# accounts/permissions.py

from rest_framework.permissions import BasePermission, IsAuthenticated

class IsThisUser(IsAuthenticated):
    """Only the user themselves."""
    
    def has_object_permission(self, request, view, obj):
        return obj.user == request.user

# Use in view:
@permission_classes([IsThisUser])
def user_detail(request, user_id):
    # Only owner can access their own details
    pass
```

### Adding Rate Limiting

```python
# bookings/views.py

from core.rate_limiting import BookingThrottles
from rest_framework.decorators import throttle_classes

@throttle_classes(BookingThrottles)
def create_booking(request):
    # 50 bookings/hour for regular users
    # Higher for business/admin
    pass
```

### Testing Security

```python
# tests/test_permissions.py

import pytest
from django.test import Client
from django.contrib.auth import get_user_model

User = get_user_model()

@pytest.mark.django_db
def test_unauthorized_access():
    """Test 401 without token."""
    client = Client()
    response = client.get('/api/v1/bookings/')
    assert response.status_code == 401

@pytest.mark.django_db
def test_permission_denied():
    """Test 403 without permission."""
    client = Client()
    user1 = User.objects.create_user(email='user1@example.com', password='pass')
    user2 = User.objects.create_user(email='user2@example.com', password='pass')
    
    # Create booking for user1
    booking = Booking.objects.create(user=user1, ...)
    
    # Login as user2
    token = get_token(user2)
    
    # Try to access user1's booking
    response = client.get(
        f'/api/v1/bookings/{booking.id}/',
        HTTP_AUTHORIZATION=f'Bearer {token}'
    )
    assert response.status_code == 403
```

---

## 📦 Service Layer

### Create New Service

```python
# bookings/search_service.py

class SearchService:
    """Service for searching bookings."""
    
    def __init__(self):
        self.repository = BookingRepository()
    
    def search_bookings(self, user, filters):
        """Search user's bookings with filters."""
        # Validation
        if not filters:
            raise InvalidDataError('Filters required')
        
        # Business logic
        bookings = self.repository.get_user_bookings(user)
        
        # Apply filters
        if filters.get('status'):
            bookings = bookings.filter(status=filters['status'])
        
        if filters.get('date_from'):
            bookings = bookings.filter(
                check_in_date__gte=filters['date_from']
            )
        
        return bookings

# Use in view:
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def search_bookings(request):
    service = SearchService()
    filters = {
        'status': request.query_params.get('status'),
        'date_from': request.query_params.get('date_from')
    }
    bookings = service.search_bookings(request.user, filters)
    serializer = BookingSerializer(bookings, many=True)
    return Response(serializer.data)
```

---

## 🐛 Debugging

### Django Shell

```bash
# Start shell
python manage.py shell

# Import models
from bookings.models import Booking
from django.contrib.auth import get_user_model
from bookings.services import BookingService
User = get_user_model()

# Query database
user = User.objects.first()
bookings = Booking.objects.filter(user=user)

# Test service
service = BookingService()
booking = service.get_booking_details('booking-uuid')

# Test permission
from accounts.permissions import IsBookingOwner
perm = IsBookingOwner()
can_access = perm.has_object_permission(request, view, booking)
```

### Print Debugging

```python
# Add debug print statements
def create_booking(request):
    print(f"DEBUG: User {request.user.id}")
    print(f"DEBUG: Data {request.data}")
    
    service = BookingService()
    booking = service.create_booking(...)
    
    print(f"DEBUG: Created booking {booking.id}")
    print(f"DEBUG: Response data {serializer.data}")
    
    return Response(serializer.data)

# Run with output
pytest -s tests/test_bookings.py
```

### Database Queries

```python
# Check slow queries
from django.db import connection
from django.test.utils import override_settings

@override_settings(DEBUG=True)
def test_query_performance():
    # Your code here
    print(f"Total queries: {len(connection.queries)}")
    for query in connection.queries:
        print(query['sql'][:100])
        print(f"Time: {query['time']}s")
```

### Health Checks

```bash
# Check if app is responding
curl http://localhost:8000/health/live

# Check if ready
curl http://localhost:8000/health/ready

# Check dependencies
curl http://localhost:8000/health/deep
```

---

## 📝 Code Patterns

### Service Layer Pattern

```python
# Always follow this pattern:

class MyService:
    def __init__(self):
        self.repository = MyRepository()
        self.validator = MyValidator()
    
    def do_something(self, **kwargs):
        # 1. Validate input
        self.validator.validate(kwargs)
        
        # 2. Check business rules
        existing = self.repository.get_something()
        if existing:
            raise NonRecoverableBookingError('Already exists')
        
        # 3. Execute transaction
        result = self.repository.create_something(**kwargs)
        
        # 4. Publish events
        publish_event('something_created', result)
        
        # 5. Return result
        return result
```

### View Pattern

```python
# Always follow this pattern:

@api_view(['GET', 'POST', 'PUT', 'DELETE'])
@permission_classes([Required, Permissions])
@throttle_classes(Required, Throttles)
def my_view(request, **kwargs):
    try:
        # 1. Extract and validate input
        data = request.data or {}
        
        # 2. Check permissions (already done by decorator)
        
        # 3. Use service layer
        service = MyService()
        result = service.do_something(**data)
        
        # 4. Serialize and return
        serializer = MySerializer(result)
        return Response({
            'success': True,
            'data': serializer.data
        }, status=201)
    
    except Exception as e:
        return enterprise_exception_handler(request, e)
```

### Test Pattern

```python
# Always follow this pattern:

@pytest.mark.django_db
class TestMyService:
    """Test cases for MyService."""
    
    def setup_method(self):
        """Setup for each test."""
        self.user = User.objects.create_user(...)
        self.service = MyService()
    
    def test_success_case(self):
        """Test successful operation."""
        result = self.service.do_something(self.user, ...)
        assert result.user == self.user
        assert result.status == 'pending'
    
    def test_validation_fails(self):
        """Test validation error."""
        with pytest.raises(InvalidDataError):
            self.service.do_something(self.user, invalid_data)
    
    def test_permission_denied(self):
        """Test authorization error."""
        other_user = User.objects.create_user(...)
        with pytest.raises(PermissionDenied):
            self.service.do_something(other_user, ...)
```

---

## 🔧 Git Workflow

### Branch Naming

```
feature/add-email-verification
bugfix/fix-double-booking-race
docs/update-security-guide
refactor/simplify-booking-service
test/add-coverage-for-permissions
```

### Commit Message Format

```
[PHASE4] Short description (max 50 chars)

Detailed explanation of the change goes here.
Can be multiple lines. Explain the "why" not the "what".

- Bullet point 1
- Bullet point 2

Fixes #123
Closes #456
```

### Create Pull Request

```bash
# Push to remote
git push origin feature/my-feature

# Go to GitHub and create PR
# Link issue: Fixes #123
# Describe changes in PR body
# Request review

# After review, merge
# Delete branch
git branch -d feature/my-feature
```

---

## 📊 Common Tasks

### Create New Endpoint

```python
# 1. Add URL in urls.py
path('api/v1/my-resource/', list_my_resources, name='list-resources'),

# 2. Add handler in views.py
@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
@throttle_classes([UserBasedThrottle])
def list_my_resources(request):
    # Implementation
    pass

# 3. Add serializer in serializers.py
class MyResourceSerializer(serializers.ModelSerializer):
    class Meta:
        model = MyResource
        fields = ['id', 'name', 'description']

# 4. Add tests in tests/test_views.py
def test_list_my_resources():
    # Test implementation
    pass
```

### Add Audit Logging

```python
from core.models import AuditLogEntry

# Automatic when:
# - Booking created/updated/deleted
# - User password changed
# - Permission changed

# Manual logging:
AuditLogEntry.objects.create(
    user=request.user,
    action='custom_action',
    content_type=ContentType.objects.get_for_model(MyModel),
    object_id=obj.id,
    changes={'field': 'new_value'}
)
```

### Add Metrics

```python
# In service.py
from core.monitoring import MetricsRecorder

class MyService:
    def do_something(self):
        with MetricsRecorder('my_operation'):
            # Code with automatic timing
            result = expensive_operation()
        
        return result

# Metrics recorded:
# - Execution time
# - Success/failure count
# - Error types
```

---

## ⚓ Quick Reference

### Environment Switching

```bash
# Development (default)
export ENVIRONMENT=development
python manage.py runserver  # SQLite, debug=True

# Staging
export ENVIRONMENT=staging
python manage.py runserver  # PostgreSQL, Sentry enabled

# Production (careful!)
export ENVIRONMENT=production
gunicorn travel_booking.wsgi  # PostgreSQL, Redis, no debug
```

### Management Commands

```bash
# Create superuser
python manage.py createsuperuser

# Load test data
python manage.py loaddata fixtures/test_data.json

# Clear cache
python manage.py clear_cache

# Check system health
python manage.py print_settings

# Generate database diagram (requires graphviz)
python manage.py graph_models bookings -o bookings_models.png

# Show migrations
python manage.py showmigrations

# Reset database (be careful!)
python manage.py flush

# Create backup
python manage.py dumpdata > backup.json

# Restore backup
python manage.py loaddata backup.json
```

### Useful Commands

```bash
# Check imports
python manage.py print_settings | grep INSTALLED_APPS

# Validate models
python manage.py check

# Find slow queries
django-extensions runserver 0.0.0.0:8000 --print-sql

# Generate API docs
python manage.py spectacular --file schema.yaml

# Test email without sending (file backend)
export EMAIL_BACKEND=django.core.mail.backends.filebased.EmailBackend
```

---

## 📚 Common Reference

### Import Patterns

```python
# Authentication
from accounts.authentication import AuthenticationService

# Services
from bookings.services import BookingService

# Permissions
from accounts.permissions import IsBookingOwner, IsEmailVerified

# Rate limiting
from core.rate_limiting import BookingThrottles

# Exceptions
from core.exceptions import (
    NonRecoverableBookingError,
    enterprise_exception_handler
)

# Serializers
from bookings.serializers import BookingSerializer

# Models
from bookings.models import Booking
from properties.models import Property
from django.contrib.auth import get_user_model

# Decorators
from rest_framework.decorators import (
    api_view,
    permission_classes,
    throttle_classes
)

# Pagination
from core.pagination import EnterprisePageNumberPagination

# Database
from django.db import transaction
from django.db.models import Q

# Testing
import pytest
from django.test import TestCase, Client, override_settings
```

### Useful Django ORM Patterns

```python
# Select for update (row-level locking)
Property.objects.select_for_update().get(id=prop_id)

# Prefetch related (optimize queries)
Booking.objects.prefetch_related('property__owner', 'user')

# Select related (optimize for FK)
Booking.objects.select_related('property', 'user')

# Filter with Q objects
from django.db.models import Q
Booking.objects.filter(
    Q(status='pending') | Q(status='confirmed')
)

# Atomic transactions
from django.db import transaction
@transaction.atomic
def do_something():
    # All or nothing
    pass

# Bulk operations
Booking.objects.bulk_create([booking1, booking2, ...])
Booking.objects.bulk_update([booking1, booking2], ['status'])
```

---

## 🆘 Troubleshooting

### Common Issues

**Issue:** `ProgrammingError: relation "bookings_booking" does not exist`
```bash
Solution: python manage.py migrate
```

**Issue:** `ImportError: No module named 'celery'`
```bash
Solution: pip install -r requirements.txt
```

**Issue:** `KeyError: 'SECRET_KEY'`
```bash
Solution: cp .env.example .env && edit .env with your key
```

**Issue:** `CORS error in browser`
```bash
Solution: Check CORS_ALLOWED_ORIGINS in settings
```

**Issue:** Token expired (401 Unauthorized)
```python
Solution: Refresh token
new_access = AuthenticationService.refresh_token(refresh_token)
```

---

**Last Updated:** Phase 4  
**Status:** Active Development  

For more help, see [QUICK_REFERENCE.md](QUICK_REFERENCE.md) or [DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md).
