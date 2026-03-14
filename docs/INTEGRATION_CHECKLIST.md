# Integration Checklist - Phase 4 Security Implementation

## Phase 4: Security & Authentication - Integration Tasks

This checklist tracks the integration of JWT authentication, RBAC, and rate limiting into existing views and endpoints.

---

## ✅ COMPLETED (Phase 4 Infrastructure)

### Core Components Created
- [x] `accounts/authentication.py` - JWT token service + authentication workflows
- [x] `accounts/permissions.py` - RBAC permission classes
- [x] `core/rate_limiting.py` - Tiered rate limiting throttles
- [x] `SECURITY_GUIDE.md` - Security best practices and patterns
- [x] `API_INTEGRATION_GUIDE.md` - Integration examples and patterns

### Security Foundation
- [x] JWT token generation with custom claims
- [x] Token refresh with rotation
- [x] Password hashing and validation
- [x] Email verification workflows (basics)
- [x] Password reset workflows (basics)
- [x] Object-level permissions (IsBookingOwner, IsPropertyOwner)
- [x] Class-level permissions (IsAdmin, IsSuperUser)
- [x] View-level rate limiting by user tier
- [x] Request tracking (X-Request-ID)
- [x] Audit logging infrastructure

---

## 🔄 IN PROGRESS (Phase 4 Integration)

### Priority 1: Authentication Views (HIGH - Required for login)

#### Task: Create/Update accounts/views.py

```python
# accounts/views.py

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from accounts.authentication import AuthenticationService
from core.exceptions import enterprise_exception_handler

@api_view(['POST'])
@permission_classes([AllowAny])
def login(request):
    """User login endpoint with JWT token response."""
    # Implementation: See API_INTEGRATION_GUIDE.md
    ...

@api_view(['POST'])
@permission_classes([AllowAny])
def register(request):
    """User registration with email verification."""
    # Implementation: See API_INTEGRATION_GUIDE.md
    ...

@api_view(['POST'])
@permission_classes([AllowAny])
def refresh_token(request):
    """Refresh access token using refresh token."""
    # Implementation: See API_INTEGRATION_GUIDE.md
    ...

@api_view(['POST'])
@permission_classes([AllowAny])
def request_password_reset(request):
    """Request password reset email."""
    # Implementation: See API_INTEGRATION_GUIDE.md
    ...
```

**Status:** [ ] Not Started / [ ] In Progress / [x] Code Example Provided

**Subtasks:**
- [ ] Create views.py with login endpoint
- [ ] Create views.py with register endpoint
- [ ] Create views.py with refresh_token endpoint
- [ ] Create views.py with password reset endpoint
- [ ] Add URL routes in accounts/urls.py
- [ ] Test with cURL/Postman

**Dependencies:**
- ✅ accounts/authentication.py (completed)
- ✅ core/exceptions.py (completed)

---

### Priority 2: Booking Endpoints (HIGH - Core functionality)

#### Task: Update bookings/views.py

Current state: Basic CRUD views (mixing ORM with business logic)

Required changes:
- Use BookingService instead of direct model access
- Add permission_classes for RBAC
- Add throttle_classes for rate limiting
- Update exception handling to use enterprise_exception_handler

```python
# bookings/views.py - BEFORE

def create_booking(request):
    # Direct ORM + business logic mix
    data = request.data
    booking = Booking.objects.create(
        user=request.user,
        property_id=data['property_id'],
        # ... other fields
    )
    return Response({'booking': BookingSerializer(booking).data})

# bookings/views.py - AFTER

from rest_framework.decorators import throttle_classes, permission_classes
from accounts.permissions import IsEmailVerified
from core.rate_limiting import BookingThrottles
from bookings.services import BookingService

@throttle_classes(BookingThrottles)
@permission_classes([IsEmailVerified])
def create_booking(request):
    # Service layer handles validation + transactions + events
    service = BookingService()
    booking = service.create_booking(
        user=request.user,
        property_id=request.data['property_id'],
        # ... other fields
    )
    return Response({
        'success': True,
        'data': BookingSerializer(booking).data
    })
```

**Status:** [ ] Not Started / [ ] In Progress / [ ] Code Example Provided

**Subtasks:**
- [ ] Update create_booking to use BookingService
- [ ] Add @permission_classes decorator with IsEmailVerified
- [ ] Add @throttle_classes decorator with BookingThrottles
- [ ] Update list_bookings with pagination
- [ ] Update booking_detail (get/update/delete)
- [ ] Update exception handling to use enterprise_exception_handler
- [ ] Test all endpoints with rate limiting

**Dependencies:**
- ✅ bookings/services.py (completed)
- ✅ bookings/validators.py (completed)
- ✅ accounts/permissions.py (completed)
- ✅ core/rate_limiting.py (completed)

---

### Priority 3: Properties Endpoints (MEDIUM - Search functionality)

#### Task: Update properties/views.py

```python
# properties/views.py

from core.rate_limiting import SearchThrottles
from core.pagination import PropertySearchPagination

@throttle_classes(SearchThrottles)
def list_properties(request):
    """
    Public search - high rate limit for search term diversity.
    Use PropertySearchPagination (30 items, cacheable).
    """
    # 1. Extract filters from query params
    # 2. Use PropertyRepository or search_service (when implemented)
    # 3. Apply PropertySearchPagination
    # 4. Return structured response
    ...

@permission_classes([IsPropertyOwner])
def property_detail_update(request, property_id):
    """
    Owner-only updates.
    Use IsPropertyOwner permission class for access control.
    """
    ...
```

**Status:** [ ] Not Started / [ ] In Progress / [ ] Code Example Provided

**Subtasks:**
- [ ] Add SearchThrottles to list_properties
- [ ] Replace pagination with PropertySearchPagination
- [ ] Add permission classes to update/delete endpoints
- [ ] Use enterprise_exception_handler for errors
- [ ] Test rate limiting per user tier

**Dependencies:**
- ✅ core/rate_limiting.py (completed)
- ✅ core/pagination.py (completed)

---

### Priority 4: Other Endpoints (MEDIUM)

#### Task: Audit existing endpoints for security

Endpoints to review:
- [ ] admin/views.py - Add IsAdmin permission
- [ ] blog/views.py - Add permission classes
- [ ] newsletter/views.py - Add rate limiting
- [ ] reviews/views.py - Add IsEmailVerified for creation
- [ ] api/views.py - Add API versioning headers
- [ ] tours/views.py - Add search rate limiting

**Status:** [ ] Not Started / [ ] In Progress / [ ] Code Example Provided

---

## ⏳ NOT YET STARTED (Future Integration)

### Phase 5: Caching & Search (Next Phase)

- [ ] Create properties/search_service.py
- [ ] Create properties/search_repository.py
- [ ] Implement Redis cache for search results
- [ ] Cache invalidation on booking changes
- [ ] Create advanced filtering API
- [ ] Setup cache warming jobs

**Timeline:** After Phase 4 integration complete

---

### Phase 6: Celery Background Tasks (Next Phase)

- [ ] Create notifications/tasks.py (email sending)
- [ ] Create analytics/tasks.py (event logging)
- [ ] Wire up email in Celery tasks
- [ ] Setup Celery Beat schedule
- [ ] Create task monitoring/alerts
- [ ] Test task retry logic

**Timeline:** After Phase 4 integration complete

---

### Phase 7: Advanced Monitoring (Future Phase)

- [ ] Setup structured JSON logging
- [ ] Collect metrics with Prometheus
- [ ] Configure Sentry for error tracking
- [ ] Create monitoring dashboard
- [ ] Setup alerts for anomalies

**Timeline:** After Phases 5-6 complete

---

### Phase 8: Deployment (Production Phase)

- [ ] Create Dockerfile
- [ ] Create docker-compose.yml
- [ ] Create nginx.conf
- [ ] Setup CI/CD pipeline
- [ ] Document deployment process

**Timeline:** After all core phases complete

---

## Task Tracking Template

### Task: [Task Name]

**Description:** What needs to be done

**Files Affected:**
- [ ] File 1
- [ ] File 2

**Testing Required:**
- [ ] Unit tests
- [ ] Integration tests
- [ ] Manual testing via cURL

**Acceptance Criteria:**
- [ ] Requirement 1
- [ ] Requirement 2

**Status:** [ ] Ready / [ ] In Progress / [ ] Complete

---

## Implementation Guidelines

### 1. Update Every API Endpoint

Pattern:
```python
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import IsAuthenticated
from core.rate_limiting import [AppropriateThrottle]
from accounts.permissions import [RequiredPermissions]

@api_view(['GET', 'POST', 'PUT', 'DELETE'])
@permission_classes([Required permissions])
@throttle_classes([Required throttles])
def endpoint_view(request):
    try:
        # Implementation using service layer
        ...
    except Exception as e:
        return enterprise_exception_handler(request, e)
```

### 2. Always Use Service Layer

❌ DON'T:
```python
booking = Booking.objects.create(...)
user.email = request.data['email']
user.save()
```

✅ DO:
```python
service = BookingService()
booking = service.create_booking(...)

service = AuthenticationService()
service.change_password(user, old, new)
```

### 3. Handle Errors with enterprise_exception_handler

❌ DON'T:
```python
except Exception as e:
    return Response({'error': str(e)})
```

✅ DO:
```python
except Exception as e:
    return enterprise_exception_handler(request, e)
```

### 4. Check Permissions Before Operations

```python
# For object-level permissions
if not request.user.is_staff and booking.user != request.user:
    return Response(
        {'error': 'Permission denied'},
        status=403
    )
```

### 5. Use Appropriate Throttles

- `BookingThrottles` for booking creation/cancellation
- `SearchThrottles` for property search
- `UserBasedThrottle` for general API calls
- `SMSThrottle` for phone verification

---

## Testing Checklist

After implementing each endpoint:

- [ ] Unit tests for business logic
- [ ] Integration tests for API endpoint
- [ ] Test with valid token (should succeed)
- [ ] Test with invalid token (should fail 401)
- [ ] Test without token (should fail 401 or 403)
- [ ] Test rate limiting (should fail 429 after limit)
- [ ] Test permission denied (should fail 403)
- [ ] Test with admin user (should succeed)
- [ ] Test with regular user (should fail or limited access)
- [ ] Test pagination works
- [ ] Test error response format matches enterprise_exception_handler

---

## Priority Order

Implement in this order for maximum impact:

1. **First (This Week)**: Authentication endpoints (login, register, refresh)
2. **Second (This Week)**: Booking endpoints (create, list, detail)
3. **Third (Next Session)**: Properties endpoints (list, filter, detail)
4. **Fourth (Next Session)**: Other endpoints (admin, blog, newsletter)

---

## Expected Outcomes

After completing Phase 4 integration:

✅ All users must authenticate with JWT tokens
✅ Users can only access their own bookings/properties
✅ Rate limiting prevents abuse (50 bookings/hour per user)
✅ All errors tracked with error_id + request_id
✅ Service layer handles all business logic
✅ No direct model access in views
✅ All endpoints return structured responses

---

## Reference Documents

- [SECURITY_GUIDE.md](SECURITY_GUIDE.md) - Security concepts and patterns
- [API_INTEGRATION_GUIDE.md](API_INTEGRATION_GUIDE.md) - Integration examples
- [IMPLEMENTATION_GUIDE.md](IMPLEMENTATION_GUIDE.md) - Service layer usage
- [accounts/authentication.py](accounts/authentication.py) - Auth service implementation
- [accounts/permissions.py](accounts/permissions.py) - Permission classes
- [core/rate_limiting.py](core/rate_limiting.py) - Rate limiting implementation

---

## Questions & Troubleshooting

### Q: Should I update all views at once or gradually?

**A:** Gradually. Start with authentication endpoints, then bookings, then others. This allows for testing at each stage.

### Q: What if an endpoint doesn't need throttling?

**A:** Some endpoints (like read-only public data) might not need throttles. Document the decision in code comments.

### Q: How do I test rate limiting locally?

**A:** Use `@override_settings` decorator or loop requests rapidly in test:
```python
from django.test import override_settings

@override_settings(THROTTLE_RATES={'booking': '2/hour'})
def test_booking_throttle():
    for i in range(3):
        response = client.post('/api/v1/bookings/', {...})
    # Third should return 429
```

### Q: Permission denied errors returning 403 or 401?

**A:** 401 = not authenticated (missing/invalid token)
      403 = authenticated but not authorized (permission denied)

---

**Last Updated:** Phase 4
**Status:** Infrastructure Complete → Integration In Progress
**Next Checkpoint:** All authentication endpoints working
