# Security & Authentication Guide (Phase 4)

## Overview

MarvelSafari implements enterprise-grade security with:

- **JWT Authentication** - Stateless, secure tokens
- **Role-Based Access Control (RBAC)** - Fine-grained permissions
- **Rate Limiting** - Multi-tier throttling
- **API Versioning** - Backward compatibility
- **Encryption** - HTTPS, PII encryption
- **Audit Trail** - Complete action logging
- **Session Security** - Secure cookies, CSRF protection

---

## JWT Authentication

### Token-Based Flow

```
┌──────────────────────────────────────────────────────┐
│ User Login                                            │
│ POST /api/v1/auth/login/                             │
│ { "email": "user@example.com", "password": "..." }  │
└──────────────────────┬───────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────┐
│ Server generates token pair                          │
│ - Access token (1 hour expiry)                      │
│ - Refresh token (7 days expiry)                     │
└──────────────────────┬───────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────┐
│ Response with tokens                                 │
│ {                                                     │
│   "access": "eyJ0eXAiOiJKV1QiLCJhbGc...",          │
│   "refresh": "eyJ0eXAiOiJKV1QiLCJhbGc...",         │
│   "user": { "id": "...", "email": "..." }          │
│ }                                                     │
└──────────────────────┬───────────────────────────────┘
                       │
          ┌────────────┴────────────┐
          ▼                         ▼
   ┌─────────────────┐      ┌──────────────┐
   │ Access Token    │      │ Refresh Token│
   │ -> Requests     │      │ -> Refresh   │
   │ -> 1 hour TTL   │      │ -> 7 day TTL │
   └─────────────────┘      └──────────────┘
```

### Implementation: Login

```python
# accounts/views.py

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from accounts.authentication import AuthenticationService

@api_view(['POST'])
@permission_classes([AllowAny])
def login_view(request):
    """User login endpoint."""
    
    email = request.data.get('email')
    password = request.data.get('password')
    
    if not email or not password:
        return Response({
            'error': 'Email and password required'
        }, status=400)
    
    try:
        result = AuthenticationService.login_user(email, password)
        return Response(result)
    
    except ValidationError as e:
        return Response({
            'error': str(e)
        }, status=401)
```

### Implementation: Using Token

```python
# Client-side (JavaScript/React)

// After login, store tokens
localStorage.setItem('access_token', response.access);
localStorage.setItem('refresh_token', response.refresh);

// Include token in requests
fetch('/api/v1/bookings/', {
    headers: {
        'Authorization': `Bearer ${localStorage.getItem('access_token')}`
    }
});
```

### Token Refresh

```python
# After access token expires (1 hour)

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny

@api_view(['POST'])
@permission_classes([AllowAny])
def refresh_token_view(request):
    """Refresh expired access token."""
    
    refresh_token = request.data.get('refresh')
    
    if not refresh_token:
        return Response({'error': 'Refresh token required'}, status=400)
    
    try:
        new_access = AuthenticationService.refresh_token(refresh_token)
        return Response({'access': new_access})
    
    except AuthenticationFailed as e:
        return Response({'error': str(e)}, status=401)
```

### JWT Payload

```json
{
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "email": "user@example.com",
  "is_staff": false,
  "is_superuser": false,
  "first_name": "John",
  "is_business_account": false,
  "permissions": ["bookings.add_booking", "bookings.view_booking"],
  "iat": 1704067200,
  "exp": 1704070800,
  "jti": "abc123..."
}
```

---

## Role-Based Access Control (RBAC)

### Permission Classes

```python
# accounts/permissions.py

class IsBookingOwner(IsAuthenticated):
    """Only booking owner can modify."""
    def has_object_permission(self, request, view, obj):
        return obj.user == request.user

class IsPropertyOwner(IsAuthenticated):
    """Only property owner can modify."""
    def has_object_permission(self, request, view, obj):
        return obj.owner == request.user

class IsAdmin(IsAuthenticated):
    """Only admin users."""
    def has_permission(self, request, view):
        return request.user.is_staff
```

### Using in Views

```python
# bookings/views.py

from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from accounts.permissions import IsBookingOwner, IsEmailVerified

@api_view(['GET', 'PUT', 'DELETE'])
@permission_classes([IsAuthenticated, IsEmailVerified, IsBookingOwner])
def booking_detail(request, booking_id):
    """Get/update/delete booking - requires ownership + email verified."""
    
    try:
        booking = Booking.objects.get(id=booking_id)
    except Booking.DoesNotExist:
        return Response({'error': 'Not found'}, status=404)
    
    # Check permission
    if not IsBookingOwner().has_object_permission(request, None, booking):
        return Response({'error': 'Permission denied'}, status=403)
    
    if request.method == 'GET':
        return Response({'booking': BookingSerializer(booking).data})
    
    # ... PUT/DELETE handling
```

### Permission Combinations

```python
# Define reusable permission sets

BOOKING_PERMISSION_REQUIRED = [
    IsAuthenticated,        # Must be logged in
    IsEmailVerified,        # Must have verified email
    HasBookingPermission,   # Domain-specific permission
]

ADMIN_PERMISSION_REQUIRED = [
    IsAuthenticated,
    IsAdmin,                # Must be admin
]

PROPERTY_OWNER_PERMISSION = [
    IsAuthenticated,
    IsPropertyOwner,        # Must own property
]

@api_view(['POST'])
@permission_classes(BOOKING_PERMISSION_REQUIRED)
def create_booking(request):
    # Automatically checks all permissions
    ...
```

---

## Rate Limiting

### Tiered System

```
┌─────────────────┬─────────┬──────────┬──────────┐
│ Operation       │ Free    │ Business │ Admin    │
├─────────────────┼─────────┼──────────┼──────────┤
│ Search          │ 100/h   │ 1000/h   │ 50k/h    │
│ Booking         │ 50/h    │ 500/h    │ 1k/h     │
│ API calls       │ 1000/h  │ 5000/h   │ 10k/h    │
│ SMS/Email       │ 3/h     │ 50/h     │ 500/h    │
└─────────────────┴─────────┴──────────┴──────────┘
```

### Implementation

```python
# core/rate_limiting.py

class UserBasedThrottle(UserRateThrottle):
    """Auto-detect user tier and apply limit."""
    
    def get_rate(self):
        if self.request.user.is_staff:
            return '10000/hour'  # Admin
        
        if self.request.user.is_business_account:
            return '5000/hour'   # Business
        
        return '1000/hour'       # Free
```

### Using in API

```python
# bookings/views.py

from core.rate_limiting import BookingThrottles

class BookingViewSet(viewsets.ModelViewSet):
    throttle_classes = BookingThrottles
    
    # Automatic rate limiting applied:
    # - Free users: 50 bookings/hour
    # - Business: 500 bookings/hour
    # - Admin: 1000 bookings/hour
```

### Handling Rate Limit

```python
# Client receives 429 response when rate limited

{
  "detail": "Request was throttled. Expected available in 3600 seconds.",
  "wait_time": 3600,
  "limit": 50,
  "remaining": 0
}

# Client should retry after wait_time
```

---

## API Versioning

### Endpoint Structure

```
Version 1 (Stable):
  /api/v1/bookings/
  /api/v1/properties/
  /api/v1/users/

Version 2 (New Features):
  /api/v2/bookings/
  /api/v2/properties/
  /api/v2/users/

Experimental:
  /api/internal/analytics/
  /api/internal/metrics/
```

### Header-Based Versioning

```python
# Client specifies version in Accept header

GET /api/bookings/
Accept: application/json; version=1.0

# Or query parameter
GET /api/bookings/?version=1.0
```

### Handling Versions

```python
# rest_framework settings

REST_FRAMEWORK = {
    'DEFAULT_VERSIONING_CLASS': 'rest_framework.versioning.AcceptHeaderVersioning',
    'DEFAULT_VERSION': '1.0',
    'ALLOWED_VERSIONS': ['1.0', '2.0'],
}

# In views
class BookingViewSet(viewsets.ModelViewSet):
    def get_serializer_class(self):
        if self.request.version == '2.0':
            return BookingSerializerV2
        return BookingSerializer
```

---

## Encryption & Data Protection

### Passwords

```python
# Django automatically hashes passwords

user = User.objects.create_user(
    email='user@example.com',
    password='plaintext_password'  # Automatically hashed
)

# PBKDF2 with SHA256 (configurable)
# 180,000 iterations by default
```

### Sensitive Data Encryption

```python
from django.core.management.base import BaseCommand
from cryptography.fernet import Fernet

# For sensitive fields, use encrypted storage

class EncryptedFields:
    """Encrypt PII before storing."""
    
    @staticmethod
    def encrypt_field(value):
        cipher = Fernet(ENCRYPTION_KEY)
        return cipher.encrypt(value.encode())
    
    @staticmethod
    def decrypt_field(encrypted_value):
        cipher = Fernet(ENCRYPTION_KEY)
        return cipher.decrypt(encrypted_value).decode()

# Usage
user.phone_number_encrypted = EncryptedFields.encrypt_field(phone)
user.save()

phone = EncryptedFields.decrypt_field(user.phone_number_encrypted)
```

### HTTPS Only

```python
# settings/production.py

SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
```

---

## CSRF & CORS Protection

### CSRF Prevention

```python
# All POST/PUT/DELETE protected automatically

# Include CSRF token in form
<form method="post">
    {% csrf_token %}
    ...
</form>

# Or in AJAX header
headers: {
    'X-CSRFToken': getCookie('csrftoken')
}

# settings
CSRF_COOKIE_HTTPONLY = False  # JS needs to read it
CSRF_COOKIE_SECURE = True     # HTTPS only
CSRF_COOKIE_SAMESITE = 'Strict'
```

### CORS Configuration

```python
# settings/base.py

CORS_ALLOWED_ORIGINS = [
    'https://app.marvelsafari.com',
    'https://admin.marvelsafari.com',
]

CORS_ALLOW_CREDENTIALS = True
CORS_MAX_AGE = 86400

# Don't allow CORS_ALLOW_ALL_ORIGINS in production!
```

---

## Audit Trail

### Automatic Logging

```python
# All significant actions logged

from core.models import AuditLogEntry

# Automatically created on:
# - Booking created, confirmed, cancelled
# - Password changed
# - Permission granted/revoked
# - Admin actions

# Query audit trail
changes = AuditLogEntry.objects.filter(
    object_id=booking_id,
    content_type='bookings.Booking'
).order_by('-created_at')

for entry in changes:
    print(f"{entry.action} by {entry.user} at {entry.created_at}")
    print(f"Changes: {entry.changes}")
```

### Request Tracking

```python
# Unique request ID for tracing

request.id  # UUID automatically generated

# Logged in every operation
logger.info(
    "Booking created",
    extra={
        'request_id': request.id,
        'user_id': user.id,
        'booking_id': booking.id
    }
)

# Appears in all responses
X-Request-ID: 550e8400-e29b-41d4-a716-446655440000
```

---

## Best Practices

### ✅ DO

- Store access tokens in memory (not localStorage)
- Use refresh tokens in httpOnly cookies
- Always require email verification for bookings
- Log all security-related events  
- Use HTTPS in production
- Rotate refresh tokens on use
- Implement rate limiting
- Encrypt sensitive data
- Validate all input
- Use strong password requirements

### ❌ DON'T

- Store tokens in localStorage (XSS vulnerability)
- Send passwords in plain text
- Trust client-side validation alone
- Allow CORS_ALLOW_ALL_ORIGINS in production
- Log passwords or PII
- Reveal whether email exists if forgot password
- Use old/deprecated authentication methods
- Disable CSRF protection
- Store secrets in code
- Use predictable IDs

---

## Common Security Issues

### Issue: Token Hijacking

```
Attack: Attacker steals access token from localStorage
Solution: Store in memory, refresh token in httpOnly cookie
```

### Issue: CSRF Attack

```
Attack: Malicious site makes request on user's behalf
Solution: Use CSRF middleware (enabled by default)
```

### Issue: Rate Limit Bypass

```
Attack: Attacker uses multiple IPs or accounts
Solution: Monitor aggregate patterns, IP-based limits
```

### Mitigation Checklist

- [ ] Enable HTTPS with HSTS
- [ ] Use httpOnly, Secure, SameSite cookies
- [ ] Implement rate limiting
- [ ] Validate all input
- [ ] Use CSRF tokens
- [ ] Log security events
- [ ] Monitor suspicious activity
- [ ] Keep dependencies updated
- [ ] Use security headers
- [ ] Regular security audits

---

## Monitoring & Alerts

### Security Metrics to Monitor

```python
# Failed login attempts
AnonymousUser failed logins: > 10/hour/IP

# Rate limit violations
Rate limit exceeded: > 50/day

# Unusual access patterns
User accessing others' bookings

# Failed permission checks
403 errors: > 100/hour

# Token refresh failures
Invalid tokens: > 1000/day
```

### Set Up Alerts

```python
# Example: Alert on multiple failed logins

from django.core.mail import send_mail
from django.contrib.auth import signals

def alert_on_failed_login(sender, **kwargs):
    request = kwargs['request']
    ip = get_client_ip(request)
    
    # Count recent failures
    failures = cache.get(f'login_failures:{ip}', 0)
    
    if failures > 5:
        send_mail(
            'Suspicious login activity',
            f'Multiple failed logins from {ip}',
            'security@marvelsafari.com',
            ['admin@marvelsafari.com']
        )

signals.user_login_failed.connect(alert_on_failed_login)
```

---

For more information, see:
- [ARCHITECTURE.md](ARCHITECTURE.md)
- [IMPLEMENTATION_GUIDE.md](IMPLEMENTATION_GUIDE.md)
- [Django Security Docs](https://docs.djangoproject.com/en/5.2/topics/security/)
