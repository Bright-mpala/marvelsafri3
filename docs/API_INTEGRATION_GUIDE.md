# API Integration Guide

This guide shows how to integrate the new security layer, service layer, and business logic into production API endpoints.

---

## Authentication Endpoints

### Login

```python
# accounts/views.py

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from accounts.authentication import AuthenticationService
from core.exceptions import enterprise_exception_handler
from django.core.exceptions import ValidationError

@api_view(['POST'])
@permission_classes([AllowAny])
def login(request):
    """
    POST /api/v1/auth/login/
    
    Request:
    {
        "email": "user@example.com",
        "password": "MyPassword123!"
    }
    
    Response (Success):
    {
        "success": true,
        "data": {
            "access": "eyJ0eXAiOiJKV1QiLCJhbGc...",
            "refresh": "eyJ0eXAiOiJKV1QiLCJhbGc...",
            "user": {
                "id": "550e8400-e29b-41d4-a716-446655440000",
                "email": "user@example.com",
                "first_name": "John",
                "is_business_account": false
            }
        }
    }
    
    Response (Failure):
    {
        "success": false,
        "error": {
            "error_id": "AUTH-001",
            "request_id": "req-uuid",
            "code": "invalid_credentials",
            "message": "Email or password incorrect"
        }
    }
    """
    try:
        email = request.data.get('email')
        password = request.data.get('password')
        
        if not email or not password:
            raise ValidationError('Email and password required')
        
        result = AuthenticationService.login_user(email, password)
        
        response = Response({
            'success': True,
            'data': result
        }, status=status.HTTP_200_OK)
        
        # Set refresh token in httpOnly cookie (more secure than token in response body)
        response.set_cookie(
            key='refresh_token',
            value=result['refresh'],
            max_age=7 * 24 * 60 * 60,  # 7 days
            httponly=True,
            secure=True,
            samesite='Strict'
        )
        
        return response
    
    except ValidationError as e:
        return enterprise_exception_handler(request, 
            {'error': str(e), 'status': 401})
    except Exception as e:
        return enterprise_exception_handler(request, e)


@api_view(['POST'])
@permission_classes([AllowAny])
def register(request):
    """
    POST /api/v1/auth/register/
    
    Request:
    {
        "email": "newuser@example.com",
        "password": "MyPassword123!",
        "first_name": "John",
        "last_name": "Doe"
    }
    """
    try:
        email = request.data.get('email')
        password = request.data.get('password')
        first_name = request.data.get('first_name')
        last_name = request.data.get('last_name', '')
        
        result = AuthenticationService.register_user(
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name
        )
        
        return Response({
            'success': True,
            'message': 'Account created. Check email for verification link.',
            'data': result
        }, status=status.HTTP_201_CREATED)
    
    except ValidationError as e:
        return enterprise_exception_handler(request, e)
    except Exception as e:
        return enterprise_exception_handler(request, e)


@api_view(['POST'])
@permission_classes([AllowAny])
def refresh_token(request):
    """
    POST /api/v1/auth/refresh/
    
    Request body:
    {
        "refresh": "eyJ0eXAiOiJKV1QiLCJhbGc..."
    }
    
    Or use refresh token from httpOnly cookie (no body needed)
    """
    try:
        refresh_token = request.data.get('refresh')
        
        # Try cookie first, then body
        if not refresh_token:
            refresh_token = request.COOKIES.get('refresh_token')
        
        if not refresh_token:
            raise ValidationError('Refresh token required')
        
        access = AuthenticationService.refresh_token(refresh_token)
        
        return Response({
            'success': True,
            'data': {'access': access}
        })
    
    except Exception as e:
        return enterprise_exception_handler(request, e)
```

### Password Reset

```python
@api_view(['POST'])
@permission_classes([AllowAny])
def request_password_reset(request):
    """
    POST /api/v1/auth/password-reset/
    
    Request:
    {
        "email": "user@example.com"
    }
    """
    try:
        email = request.data.get('email')
        if not email:
            raise ValidationError('Email required')
        
        # Don't reveal if email exists (security best practice)
        AuthenticationService.request_password_reset(email)
        
        return Response({
            'success': True,
            'message': 'Password reset link sent to email'
        })
    
    except Exception as e:
        # Always return success, even if email doesn't exist
        return Response({
            'success': True,
            'message': 'Password reset link sent to email'
        })
```

---

## Booking Management Endpoints

### Create Booking

```python
# bookings/views.py

from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.throttling import UserRateThrottle
from rest_framework.response import Response
from rest_framework import status

from accounts.permissions import IsEmailVerified
from bookings.services import BookingService
from bookings.validators import BookingValidator
from core.exceptions import enterprise_exception_handler
from core.rate_limiting import BookingThrottles
from django.db import transaction

@api_view(['POST'])
@permission_classes([IsAuthenticated, IsEmailVerified])
@throttle_classes(BookingThrottles)
def create_booking(request):
    """
    POST /api/v1/bookings/
    
    Request:
    {
        "property_id": "550e8400-e29b-41d4-a716-446655440000",
        "check_in_date": "2024-02-15",
        "check_out_date": "2024-02-20",
        "guests": 2,
        "special_requests": "High floor please"
    }
    
    Response (Success):
    {
        "success": true,
        "data": {
            "id": "booking-uuid",
            "property_id": "property-uuid",
            "user_id": "user-uuid",
            "check_in_date": "2024-02-15",
            "check_out_date": "2024-02-20",
            "guests": 2,
            "total_price": 1500.00,
            "status": "pending",
            "created_at": "2024-01-15T10:00:00Z"
        }
    }
    
    Response (Rate Limited):
    {
        "success": false,
        "error": {
            "error_id": "THROTTLE-001",
            "code": "throttled",
            "message": "Request was throttled. Expected available in 3600 seconds."
        }
    }
    """
    try:
        # Extract data
        property_id = request.data.get('property_id')
        check_in_date = request.data.get('check_in_date')
        check_out_date = request.data.get('check_out_date')
        guests = request.data.get('guests')
        special_requests = request.data.get('special_requests', '')
        
        # Use service layer (handles validation, transactions, events)
        service = BookingService()
        
        booking = service.create_booking(
            user=request.user,
            property_id=property_id,
            check_in_date=check_in_date,
            check_out_date=check_out_date,
            guests=guests,
            special_requests=special_requests
        )
        
        # Serialize and return
        from bookings.serializers import BookingSerializer
        serializer = BookingSerializer(booking)
        
        return Response({
            'success': True,
            'data': serializer.data
        }, status=status.HTTP_201_CREATED)
    
    except Exception as e:
        return enterprise_exception_handler(request, e)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_bookings(request):
    """
    GET /api/v1/bookings/
    
    Query params:
    ?status=confirmed&start_date=2024-02-01&end_date=2024-02-28&page=1
    
    Returns paginated list with project's custom pagination
    """
    try:
        service = BookingService()
        
        # Filter by status if provided
        status_filter = request.query_params.get('status')
        
        bookings = service.get_user_bookings(
            user=request.user,
            status=status_filter
        )
        
        # Apply pagination
        from core.pagination import EnterprisePageNumberPagination
        paginator = EnterprisePageNumberPagination()
        paginated = paginator.paginate_queryset(bookings, request)
        
        from bookings.serializers import BookingSerializer
        serializer = BookingSerializer(paginated, many=True)
        
        return paginator.get_paginated_response({
            'success': True,
            'data': serializer.data
        })
    
    except Exception as e:
        return enterprise_exception_handler(request, e)


@api_view(['GET', 'PUT', 'DELETE'])
@permission_classes([IsAuthenticated])
@throttle_classes(BookingThrottles)
def booking_detail(request, booking_id):
    """
    GET /api/v1/bookings/{id}/ - Get booking
    PUT /api/v1/bookings/{id}/ - Update special requests
    DELETE /api/v1/bookings/{id}/ - Cancel booking
    """
    try:
        service = BookingService()
        
        # Get booking (raises 404 if not found)
        booking = service.get_booking_details(booking_id)
        
        # Check ownership (raise 403 if not owner/admin)
        if booking.user != request.user and not request.user.is_staff:
            return Response({
                'success': False,
                'error': {
                    'code': 'permission_denied',
                    'message': 'You can only access your own bookings'
                }
            }, status=status.HTTP_403_FORBIDDEN)
        
        if request.method == 'GET':
            from bookings.serializers import BookingSerializer
            return Response({
                'success': True,
                'data': BookingSerializer(booking).data
            })
        
        elif request.method == 'PUT':
            # Only allow updating special requests
            special_requests = request.data.get('special_requests')
            if special_requests:
                booking.special_requests = special_requests
                booking.save()
            
            from bookings.serializers import BookingSerializer
            return Response({
                'success': True,
                'data': BookingSerializer(booking).data
            })
        
        elif request.method == 'DELETE':
            # Cancel booking
            service.cancel_booking(booking_id, user=request.user)
            
            return Response({
                'success': True,
                'message': 'Booking cancelled successfully'
            })
    
    except Exception as e:
        return enterprise_exception_handler(request, e)
```

---

## Property Management Endpoints

### List Properties with Filtering

```python
# properties/views.py

from rest_framework.decorators import api_view, throttle_classes
from rest_framework.response import Response
from core.rate_limiting import SearchThrottles
from core.pagination import PropertySearchPagination
from core.exceptions import enterprise_exception_handler

@api_view(['GET'])
@throttle_classes(SearchThrottles)
def list_properties(request):
    """
    GET /api/v1/properties/
    
    Query params (all optional):
    ?location=New+York&min_price=100&max_price=500&limit=30&page=1
    
    Response:
    {
        "success": true,
        "data": [
            {
                "id": "prop-uuid",
                "name": "Beautiful Apartment",
                "location": "New York",
                "price_per_night": 250,
                "rating": 4.8,
                ...
            }
        ],
        "pagination": {
            "total": 1250,
            "page": 1,
            "total_pages": 42,
            "has_next": true
        }
    }
    """
    try:
        # Extract filters
        location = request.query_params.get('location')
        min_price = request.query_params.get('min_price')
        max_price = request.query_params.get('max_price')
        check_in = request.query_params.get('check_in')
        check_out = request.query_params.get('check_out')
        
        # Use search service (when implemented)
        # For now, use basic filtering
        from properties.models import Property
        
        queryset = Property.objects.filter(is_active=True)
        
        if location:
            queryset = queryset.filter(location__icontains=location)
        
        if min_price:
            queryset = queryset.filter(price_per_night__gte=min_price)
        
        if max_price:
            queryset = queryset.filter(price_per_night__lte=max_price)
        
        # Apply pagination
        paginator = PropertySearchPagination()
        paginated = paginator.paginate_queryset(queryset, request)
        
        from properties.serializers import PropertyListSerializer
        serializer = PropertyListSerializer(paginated, many=True)
        
        return paginator.get_paginated_response({
            'success': True,
            'data': serializer.data
        })
    
    except Exception as e:
        return enterprise_exception_handler(request, e)


@api_view(['GET', 'POST', 'PUT', 'DELETE'])
def property_detail(request, property_id):
    """
    GET /api/v1/properties/{id}/ - View property
    POST /api/v1/properties/ - Create (if owner)
    PUT /api/v1/properties/{id}/ - Update (if owner)
    DELETE /api/v1/properties/{id}/ - Delete (if owner)
    """
    from rest_framework.permissions import IsAuthenticated
    from accounts.permissions import IsPropertyOwner
    from properties.models import Property
    from properties.serializers import PropertySerializer
    
    try:
        if request.method == 'GET':
            # Public access to view property
            property_obj = Property.objects.get(id=property_id, is_active=True)
            return Response({
                'success': True,
                'data': PropertySerializer(property_obj).data
            })
        
        else:
            # Require authentication and ownership for modifications
            if not request.user.is_authenticated:
                return Response({
                    'success': False,
                    'error': {'code': 'not_authenticated'}
                }, status=401)
            
            property_obj = Property.objects.get(id=property_id)
            
            if property_obj.owner != request.user and not request.user.is_staff:
                return Response({
                    'success': False,
                    'error': {'code': 'permission_denied'}
                }, status=403)
            
            if request.method in ['PUT', 'DELETE']:
                # Update or delete
                # Implementation...
                pass
    
    except Property.DoesNotExist:
        return Response({
            'success': False,
            'error': {'code': 'not_found'}
        }, status=404)
    
    except Exception as e:
        return enterprise_exception_handler(request, e)
```

---

## URL Configuration

```python
# travel_booking/urls.py

from django.contrib import admin
from django.urls import path, include
from rest_framework.routers import DefaultRouter

# API endpoints
from accounts.views import login, register, refresh_token
from bookings.views import create_booking, list_bookings, booking_detail
from properties.views import list_properties, property_detail

# Core health checks
from core import views as core_views

urlpatterns = [
    # Admin
    path('admin/', admin.site.urls),
    
    # Health checks (used by orchestration)
    path('health/live', core_views.health_check_live, name='health-live'),
    path('health/ready', core_views.health_check_ready, name='health-ready'),
    path('health/deep', core_views.health_check_deep, name='health-deep'),
    
    # API v1
    path('api/v1/auth/login/', login, name='login'),
    path('api/v1/auth/register/', register, name='register'),
    path('api/v1/auth/refresh/', refresh_token, name='refresh-token'),
    
    # Bookings
    path('api/v1/bookings/', create_booking, name='create-booking'),
    path('api/v1/bookings/', list_bookings, name='list-bookings'),
    path('api/v1/bookings/<uuid:booking_id>/', booking_detail, name='booking-detail'),
    
    # Properties
    path('api/v1/properties/', list_properties, name='list-properties'),
    path('api/v1/properties/<uuid:property_id>/', property_detail, name='property-detail'),
    
    # Other apps
    path('api/', include('api.urls')),
]
```

---

## Testing Endpoints

### Using cURL

```bash
# Register user
curl -X POST http://localhost:8000/api/v1/auth/register/ \
  -H "Content-Type: application/json" \
  -d '{
    "email": "test@example.com",
    "password": "MyPassword123!",
    "first_name": "John"
  }'

# Login
curl -X POST http://localhost:8000/api/v1/auth/login/ \
  -H "Content-Type: application/json" \
  -d '{
    "email": "test@example.com",
    "password": "MyPassword123!"
  }'

# Create booking (use access token)
curl -X POST http://localhost:8000/api/v1/bookings/ \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <access_token>" \
  -d '{
    "property_id": "550e8400-e29b-41d4-a716-446655440000",
    "check_in_date": "2024-02-15",
    "check_out_date": "2024-02-20",
    "guests": 2
  }'

# Get bookings
curl http://localhost:8000/api/v1/bookings/ \
  -H "Authorization: Bearer <access_token>"
```

### Using Python Requests

```python
import requests

BASE_URL = 'http://localhost:8000/api/v1'

# Register
response = requests.post(
    f'{BASE_URL}/auth/register/',
    json={
        'email': 'test@example.com',
        'password': 'MyPassword123!',
        'first_name': 'John'
    }
)

# Login
response = requests.post(
    f'{BASE_URL}/auth/login/',
    json={
        'email': 'test@example.com',
        'password': 'MyPassword123!'
    }
)

tokens = response.json()['data']
access_token = tokens['access']

# Create booking
headers = {'Authorization': f'Bearer {access_token}'}

response = requests.post(
    f'{BASE_URL}/bookings/',
    headers=headers,
    json={
        'property_id': '550e8400-e29b-41d4-a716-446655440000',
        'check_in_date': '2024-02-15',
        'check_out_date': '2024-02-20',
        'guests': 2
    }
)

booking = response.json()['data']
print(f"Created booking: {booking['id']}")
```

---

## Error Handling

All endpoints use the enterprise exception handler which returns structured errors:

```json
{
  "success": false,
  "error": {
    "error_id": "UNIQUE-UUID",
    "request_id": "REQUEST-UUID",
    "code": "error_code",
    "message": "Human-readable error message"
  }
}
```

Common error codes:

- `not_authenticated` - 401 Unauthorized
- `permission_denied` - 403 Forbidden
- `not_found` - 404 Not Found
- `invalid_input` - 400 Bad Request
- `throttled` - 429 Too Many Requests
- `server_error` - 500 Internal Server Error

---

For more details:
- [SECURITY_GUIDE.md](SECURITY_GUIDE.md)
- [IMPLEMENTATION_GUIDE.md](IMPLEMENTATION_GUIDE.md)
- [TRANSACTION_SAFETY.md](TRANSACTION_SAFETY.md)
