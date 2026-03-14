# Quick Reference Guide - Phase 4 Security

A fast lookup guide for common security tasks and patterns.

---

## Authentication

### Login User
```python
from accounts.authentication import AuthenticationService

result = AuthenticationService.login_user(
    email='user@example.com',
    password='password123'
)

# Returns:
# {
#     'access': 'token...',
#     'refresh': 'token...',
#     'user': {...}
# }
```

### Register User
```python
result = AuthenticationService.register_user(
    email='newuser@example.com',
    password='Password123!',
    first_name='John',
    last_name='Doe'
)
```

### Refresh Token
```python
new_access = AuthenticationService.refresh_token(refresh_token)
```

### Change Password
```python
AuthenticationService.change_password(
    user=request.user,
    old_password='old_pass',
    new_password='new_pass'
)
```

### Reset Password
```python
# Request reset
AuthenticationService.request_password_reset('user@example.com')

# Confirm reset (usually via email link)
AuthenticationService.reset_password(
    uid='user_id',
    token='reset_token',
    new_password='new_pass'
)
```

---

## Permissions

### Add to View
```python
from rest_framework.decorators import permission_classes
from accounts.permissions import IsEmailVerified, IsBookingOwner

@permission_classes([IsEmailVerified, IsBookingOwner])
def my_view(request):
    pass
```

### Available Permissions
```python
# Authentication required
IsAuthenticated

# Email verified
IsEmailVerified

# Admin only
IsAdmin
IsSuperUser

# Ownership-based
IsBookingOwner      # Must own booking
IsPropertyOwner     # Must own property

# Account tier
IsBusinessAccount   # Must be business tier

# Complex rules
HasBookingPermission     # GET own, POST auth, PUT/DELETE owner
HasSearchPermission      # GET public, POST auth
HasPermissionOrReadOnly  # GET public + write own
```

### Create Permission Class
```python
from rest_framework.permissions import BasePermission

class IsVIPUser(BasePermission):
    def has_permission(self, request, view):
        return (
            request.user and 
            request.user.is_authenticated and 
            request.user.is_vip
        )

# Use in view
@permission_classes([IsVIPUser])
def vip_endpoint(request):
    pass
```

---

## Rate Limiting

### Add to View
```python
from rest_framework.decorators import throttle_classes
from core.rate_limiting import BookingThrottles

@throttle_classes(BookingThrottles)
def my_view(request):
    pass
```

### Available Throttles
```python
# Standard API calls
UserBasedThrottle        # 1k-10k/hr by tier
IPBasedThrottle          # 10k/hr global per IP
AnonymousUserThrottle    # 100/hr for guests

# Specific operations
BookingThrottles         # 50/hr standard users
SearchThrottles          # 100-50k/hr by tier
SMSThrottle              # 3-10/hr
EmailThrottle            # 5-50/hr

# Shorthand combinations
DefaultThrottles         # UserBased + IPBased
PublicThrottles          # AnonymousUser only
```

### Check Current Rate Limit (in request)
```python
throttle = request.user_throttle  # UserRateThrottle instance
remaining = throttle.get_available_requests(request)
limit = throttle.get_rate()
```

### Bypass Rate Limit (admin only)
```python
# Admins and staff automatically get higher limits
# Or use @override_settings in tests
```

---

## Service Layer

### BookingService
```python
from bookings.services import BookingService

service = BookingService()

# Create booking
booking = service.create_booking(
    user=request.user,
    property_id=property_uuid,
    check_in_date='2024-02-15',
    check_out_date='2024-02-20',
    guests=2,
    special_requests='High floor please'
)

# Get user's bookings
bookings = service.get_user_bookings(request.user)

# Get specific booking
booking = service.get_booking_details(booking_id)

# Confirm booking
service.confirm_booking(booking_id)

# Cancel booking
service.cancel_booking(booking_id, user=request.user)
```

### AuthenticationService
```python
from accounts.authentication import AuthenticationService

service = AuthenticationService()

# All methods are static (no instance needed)
AuthenticationService.login_user(email, password)
AuthenticationService.register_user(email, password, first_name)
AuthenticationService.refresh_token(refresh_token)
AuthenticationService.change_password(user, old, new)
AuthenticationService.request_password_reset(email)
AuthenticationService.reset_password(uid, token, password)
```

---

## Exception Handling

### Use enterprise_exception_handler
```python
from core.exceptions import enterprise_exception_handler

try:
    # Your code
    ...
except Exception as e:
    return enterprise_exception_handler(request, e)
```

### Response Format
```json
{
  "success": false,
  "error": {
    "error_id": "unique-uuid",
    "request_id": "request-uuid", 
    "code": "error_code",
    "message": "Friendly message"
  }
}
```

### Custom Exceptions
```python
from core.exceptions import (
    NonRecoverableBookingError,
    ConcurrencyError,
    ServiceUnavailableError,
    InvalidDataError
)

# Use in service layer
raise NonRecoverableBookingError(
    message='Property not available',
    code='property_not_available'
)
```

---

## Pagination

### Use Correct Paginator
```python
# Booking operations (strict page size)
from core.pagination import BookingSafePageNumberPagination
paginator = BookingSafePageNumberPagination()

# General / Enterprise API
from core.pagination import EnterprisePageNumberPagination
paginator = EnterprisePageNumberPagination()

# Property search (30 items, cacheable)
from core.pagination import PropertySearchPagination
paginator = PropertySearchPagination()

# Apply
page = paginator.paginate_queryset(queryset, request)
serializer = MySerializer(page, many=True)
return paginator.get_paginated_response(serializer.data)
```

### Response Format
```json
{
  "success": true,
  "data": [...],
  "pagination": {
    "count": 100,
    "next": "http://api.example.com/properties/?page=2",
    "previous": null,
    "total_pages": 4,
    "current_page": 1,
    "page_size": 25
  }
}
```

---

## View Template

### Minimal View
```python
from rest_framework.decorators import (
    api_view, 
    permission_classes, 
    throttle_classes
)
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from core.exceptions import enterprise_exception_handler
from core.rate_limiting import UserBasedThrottle

@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
@throttle_classes([UserBasedThrottle])
def my_endpoint(request):
    try:
        # Implementation
        data = {...}
        return Response({
            'success': True,
            'data': data
        })
    except Exception as e:
        return enterprise_exception_handler(request, e)
```

### Full View with Pagination
```python
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from core.pagination import EnterprisePageNumberPagination
from core.exceptions import enterprise_exception_handler

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_items(request):
    try:
        queryset = MyModel.objects.filter(user=request.user)
        
        # Paginate
        paginator = EnterprisePageNumberPagination()
        page = paginator.paginate_queryset(queryset, request)
        
        # Serialize
        serializer = MySerializer(page, many=True)
        
        # Return with pagination info
        return paginator.get_paginated_response({
            'success': True,
            'data': serializer.data
        })
    except Exception as e:
        return enterprise_exception_handler(request, e)
```

---

## Testing

### Test Authentication
```python
from django.test import TestCase
from accounts.authentication import AuthenticationService

class AuthTestCase(TestCase):
    def test_login(self):
        # Register
        AuthenticationService.register_user(
            email='test@example.com',
            password='Pass123!',
            first_name='Test'
        )
        
        # Login
        result = AuthenticationService.login_user(
            email='test@example.com',
            password='Pass123!'
        )
        
        self.assertIn('access', result)
        self.assertIn('refresh', result)
```

### Test Permissions
```python
from django.test import TestCase, Client
from django.contrib.auth import get_user_model

User = get_user_model()

class PermissionTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            email='test@example.com',
            password='pass'
        )
    
    def test_authenticated_required(self):
        # Without token: unauthorized
        response = self.client.get('/api/v1/bookings/')
        self.assertEqual(response.status_code, 401)
        
        # With token: authorized
        # (Get token from login)
```

### Test Rate Limiting
```python
from django.test import override_settings
from django.test import TestCase
from accounts.authentication import AuthenticationService

@override_settings(THROTTLE_RATES={'booking': '2/hour'})
class RateLimitTestCase(TestCase):
    def test_booking_throttle(self):
        user = User.objects.create_user(
            email='test@example.com',
            password='pass'
        )
        token = AuthenticationService.login_user(...)['access']
        
        # First request
        resp1 = self.client.post(
            '/api/v1/bookings/',
            HTTP_AUTHORIZATION=f'Bearer {token}'
        )
        self.assertEqual(resp1.status_code, 201)
        
        # Third request should fail
        for i in range(2):
            self.client.post(
                '/api/v1/bookings/',
                HTTP_AUTHORIZATION=f'Bearer {token}'
            )
        
        resp_throttled = self.client.post(
            '/api/v1/bookings/',
            HTTP_AUTHORIZATION=f'Bearer {token}'
        )
        self.assertEqual(resp_throttled.status_code, 429)
```

---

## Debugging

### Check Health Status
```bash
# Liveness check (is app running?)
curl http://localhost:8000/health/live

# Readiness check (dependencies ok?)
curl http://localhost:8000/health/ready

# Deep check (full system)
curl http://localhost:8000/health/deep
```

### View Audit Trail
```python
from core.models import AuditLogEntry

# Get all changes to a booking
AuditLogEntry.objects.filter(
    object_id=booking_id,
    content_type='bookings.Booking'
).order_by('-created_at')

# Get user actions
AuditLogEntry.objects.filter(
    user=request.user
).order_by('-created_at')
```

### Track Request ID
```python
# Every response has X-Request-ID header
# Use to correlate logs and errors
response = requests.get(..., headers={...})
request_id = response.headers['X-Request-ID']
print(f"Request ID: {request_id}")

# Use in logs to debug
Sentry will automatically track this
```

---

## Common Errors & Solutions

### Error: 401 Unauthorized
**Cause:** Missing or invalid JWT token
```python
# Fix: Include token in Authorization header
headers = {
    'Authorization': f'Bearer {access_token}'
}
```

### Error: 403 Forbidden
**Cause:** User authenticated but not authorized
```python
# Fix: Check permission class requirements
# e.g., IsEmailVerified might require email verification
```

### Error: 429 Too Many Requests
**Cause:** Rate limit exceeded
```python
# Fix: Wait before retrying (check Retry-After header)
# Increase subscription tier for higher limits
```

### Error: Double Booking
**Cause:** Race condition in booking creation
```python
# Fix: Use BookingService (handles row-level locking)
service = BookingService()
booking = service.create_booking(...)  # Safe!
```

### Error: Token Expired
**Cause:** Access token past 1 hour expiry
```python
# Fix: Refresh token
new_access = AuthenticationService.refresh_token(refresh_token)
```

---

## File Locations

Main security files:
- `accounts/authentication.py` - JWT + auth service
- `accounts/permissions.py` - Permission classes
- `core/rate_limiting.py` - Rate limiting throttles
- `core/exceptions.py` - Error handler + custom exceptions
- `core/pagination.py` - Response pagination
- `bookings/services.py` - Business logic service

Documentation:
- `SECURITY_GUIDE.md` - Detailed security patterns
- `API_INTEGRATION_GUIDE.md` - Integration examples
- `IMPLEMENTATION_GUIDE.md` - Service layer guide
- `INTEGRATION_CHECKLIST.md` - Integration tasks

---

## Quick Links

- [Full Security Guide](SECURITY_GUIDE.md)
- [API Integration Examples](API_INTEGRATION_GUIDE.md)
- [Service Layer Guide](IMPLEMENTATION_GUIDE.md)
- [Integration Checklist](INTEGRATION_CHECKLIST.md)
