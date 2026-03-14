# MarvelSafari Service Layer Implementation Guide

## Overview

The MarvelSafari platform has been refactored with a **service-oriented architecture** using the **Repository and Service patterns**. This guide explains how to use the new layered architecture.

---

## Architecture Layers

```
┌─────────────────────────────────────┐
│    API Views/Endpoints              │ ← HTTP Request/Response
├─────────────────────────────────────┤
│    Serializers                      │ ← Data validation & transformation
├─────────────────────────────────────┤
│    Service Layer (services.py)      │ ← Business logic orchesteration
├─────────────────────────────────────┤
│    Repository Layer (repositories.py)│ ← Data access abstraction
├─────────────────────────────────────┤
│    Django Models (models.py)        │ ← ORM & database
├─────────────────────────────────────┤
│    PostgreSQL Database              │ ← Persistent storage
└─────────────────────────────────────┘
```

---

## Booking Service Architecture

### Components

#### 1. **Models** (`bookings/models.py`)
Raw ORM definitions. Minimal business logic in models.

```python
class Booking(models.Model):
    user = ForeignKey(User, ...)
    property = ForeignKey(Property, ...)
    check_in_date = DateField()
    check_out_date = DateField()
    status = CharField(choices=BOOKING_STATUS)
    total_amount = DecimalField()
```

#### 2. **Validators** (`bookings/validators.py`)
Reusable validation rules:
- Date ranges
- Guest count limits
- Price constraints
- Business rule checks

```python
BookingValidator.validate_dates(check_in_date, check_out_date)
BookingValidator.validate_guests(guests)
BookingValidator.validate_price(price)
```

#### 3. **Repository** (`bookings/repositories.py`)
Data access layer with:
- Query methods with optimizations
- Transaction management
- Row-level locking for concurrency control

```python
class BookingRepository:
    def get_booking(booking_id, user=None)
    def get_user_bookings(user, status=None)
    def check_availability(property_id, dates)
    def create_booking(user, property, dates, ...)
    def update_booking_status(booking_id, new_status)
```

#### 4. **Service** (`bookings/services.py`)
Business logic orchestration:
- Complex workflows
- Event publishing
- Notification triggering
- Coordination between repositories

```python
class BookingService:
    def create_booking(user, property_id, dates, ...)
    def confirm_booking(booking_id, user)
    def cancel_booking(booking_id, user, reason)
    def expire_pending_bookings(minutes)
```

#### 5. **Tasks** (`bookings/tasks.py`)
Celery background tasks:
- Async operations
- Scheduled jobs
- Event processing

```python
@shared_task
def expire_pending_bookings(minutes=30)

@shared_task
def send_booking_reminders()

@shared_task
def publish_booking_event(booking_id, event_type)
```

---

## How to Use the Service Layer

### Creating a Booking (with transaction safety)

**Via Service Layer:**

```python
from bookings.services import BookingService
from datetime import date, timedelta

service = BookingService()

try:
    booking = service.create_booking(
        user=request.user,
        property_id=property_id,
        check_in_date=date.today() + timedelta(days=5),
        check_out_date=date.today() + timedelta(days=7),
        guests=2,
        special_requests="High floor preferred",
        price_per_night=None  # Auto-fetch from property
    )
    print(f"Booking created: {booking.id}")
    return booking

except InvalidDataError as e:
    # Handle validation errors
    return {'error': e.message, 'code': e.code}

except NonRecoverableBookingError as e:
    # Handle booking conflicts (double-booking, unavailable, etc.)
    return {'error': e.message, 'code': e.code}
```

**Key Features:**
- ✅ Automatic transaction wrapping
- ✅ Row-level locking prevents double-booking
- ✅ Validates availability before creating
- ✅ Publishes events asynchronously
- ✅ Sends confirmations via Celery
- ✅ Records metrics

---

### Confirming a Booking (Payment received)

```python
service = BookingService()

try:
    booking = service.confirm_booking(
        booking_id=booking_id,
        user=request.user
    )
    return {'status': 'success', 'booking': booking}

except NonRecoverableBookingError as e:
    return {'error': e.message}
```

---

### Cancelling a Booking

```python
try:
    booking = service.cancel_booking(
        booking_id=booking_id,
        user=request.user,
        reason="User requested"
    )
    # Refunds processing happens async
    return {'status': 'cancelled', 'booking': booking}

except NonRecoverableBookingError as e:
    return {'error': e.message}
```

---

### Getting User Bookings

```python
result = service.get_user_bookings(
    user=request.user,
    status='confirmed',           # Optional: pending, confirmed, cancelled, completed
    date_filter='upcoming',       # Optional: upcoming, past, or None
    page=1,
    page_size=20
)

bookings = result['bookings']
total_pages = result['total_pages']
```

---

## Direct Repository Access (Lower Level)

For simple queries that don't need business logic:

```python
from bookings.repositories import BookingRepository

# Check availability
is_available = BookingRepository.check_availability(
    property_id=property_id,
    check_in_date=start_date,
    check_out_date=end_date
)

# Get bookings for property
bookings = BookingRepository.get_property_bookings(
    property_id=property_id,
    start_date=start_date,
    end_date=end_date
)

# Get expiring bookings (for Celery tasks)
expiring = BookingRepository.get_pending_expiring_bookings(minutes=30)
```

---

## Validation

### Using Validators Independently

```python
from bookings.validators import BookingValidator
from django.core.exceptions import ValidationError

try:
    BookingValidator.validate_dates(check_in_date, check_out_date)
    BookingValidator.validate_guests(guests)
    BookingValidator.validate_price(price)
except ValidationError as e:
    print(f"Validation error: {e.message}")
```

### Batch Validation

```python
errors = BookingValidator.validate_booking_data(
    check_in_date=check_in_date,
    check_out_date=check_out_date,
    guests=guests,
    price_per_night=price,
    special_requests=requests
)

if errors:
    print(f"Validation errors: {errors}")
    # errors = {'dates': 'Check-out must be after check-in', ...}
```

---

## Exception Handling

The service layer uses enterprise exceptions:

```python
from core.exceptions import (
    NonRecoverableBookingError,   # e.g., double booking
    InvalidDataError,             # e.g., invalid dates
    ConcurrencyError,             # e.g., race condition
    EnterpriseAPIException,       # base class
)

try:
    booking = service.create_booking(...)
except InvalidDataError as e:
    # Validation error - can retry with different data
    print(f"{e.error_id}: {e.message}")
except NonRecoverableBookingError as e:
    # Business logic error - cannot be retried
    print(f"{e.error_id}: {e.message}")
```

Each exception includes:
- `error_id` - Unique UUID for tracking
- `code` - Machine-readable error code
- `message` - Human-readable message
- `status_code` - HTTP status code
- `details` - Additional context

---

## Transaction Safety & Locking

### Problem: Double-Booking

Without proper locking, concurrent bookings can occur:

```
User A: Check availability → Available
User B: Check availability → Available
User A: Create booking → SUCCESS
User B: Create booking → SUCCESS ❌ (DOUBLE BOOKED!)
```

### Solution: Row-Level Locking

The service uses `SELECT FOR UPDATE` to prevent this:

```python
# In BookingRepository.create_booking()

# Lock the property row
Property.objects.select_for_update().get(id=property_obj.id)

# Re-check availability AFTER locking
overlapping = Booking.objects.filter(...)

if overlapping.exists():
    raise NonRecoverableBookingError(...)

# Create booking safely
booking = Booking.objects.create(...)
```

This ensures:
1. Property is locked
2. No other transaction can modify it
3. Double-check availability
4. Create booking atomically
5. Release lock on transaction commit

---

## Asynchronous Operations

### Background Tasks (Celery)

Common operations that run async:

```python
# 1. Booking expiration (every 5 minutes)
@app.task
def expire_pending_bookings(minutes=30)

# 2. Send confirmations (immediately)
@app.task
def send_booking_confirmation_email(booking_id)

# 3. Send reminders (daily)
@app.task
def send_booking_reminders()

# 4. Event publishing (immediately)
@app.task
def publish_booking_event(booking_id, event_type)
```

### Triggering Tasks

```python
# From service layer:
from bookings.tasks import expire_pending_bookings

# Async (non-blocking)
expired_count = expire_pending_bookings.delay(minutes=30)

# Scheduled (Celery Beat handles)
# Defined in settings.CELERY_BEAT_SCHEDULE
```

---

## Adding New Services

### Pattern for New Domain Service

1. **Create Repository** (`myfeature/repositories.py`)
   ```python
   class MyFeatureRepository:
       @staticmethod
       def query_items(...): ...
       @staticmethod
       def create_item(...): ...
   ```

2. **Create Service** (`myfeature/services.py`)
   ```python
   class MyFeatureService:
       def __init__(self):
           self.repository = MyFeatureRepository()
       
       def complex_operation(self, ...): ...
   ```

3. **Create Validators** (`myfeature/validators.py`)
   ```python
   class MyFeatureValidator:
       @classmethod
       def validate_data(cls, ...): ...
   ```

4. **Create Tasks** (`myfeature/tasks.py`)
   ```python
   @shared_task
   def async_operation(...): ...
   ```

5. **Use in Views**
   ```python
   from myfeature.services import MyFeatureService
   
   service = MyFeatureService()
   result = service.complex_operation(...)
   ```

---

## Best Practices

### ✅ DO

- Use service layer for all business operations
- Use repository for simple data queries
- Validate input at service layer
- Let service handle transaction management
- Publish events asynchronously
- Log important operations with context
- Use specific exception types

### ❌ DON'T

- Create models directly in views
- Mix business logic with ORM queries
- Forget transaction.atomic() wrapping
- Ignore row-level locking for concurrent operations
- Perform long operations in request handler
- Send emails/notifications synchronously
- Use generic Exception for domain errors

---

## Monitoring & Debugging

### View Audit Trail

```python
from core.models import AuditLogEntry

# Get all changes to a booking
changes = AuditLogEntry.objects.filter(
    content_type='bookings.Booking',
    object_id=booking_id
).order_by('created_at')

for entry in changes:
    print(f"{entry.action} by {entry.user} at {entry.created_at}")
    print(f"Changes: {entry.changes}")
```

### Monitor with Metrics

```python
# Recorded automatically
- bookings_created_total
- bookings_cancelled_total
- bookings_completed_total
- http_requests_duration_seconds
- db_query_duration_seconds
```

### Health Checks

```
# Liveness
GET /health/live → Is app running?

# Readiness
GET /health/ready → Ready for traffic?

# Deep health
GET /health/deep → All systems operational?
```

---

## Performance Optimization Tips

1. **Use select_related() for foreign keys**
   ```python
   bookings = Booking.objects.select_related('user', 'property')
   ```

2. **Use prefetch_related() for reverse relations**
   ```python
   from django.db.models import Prefetch
   bookings = Booking.objects.prefetch_related(
       Prefetch('reviews')
   )
   ```

3. **Index frequently filtered fields**
   ```python
   # Already defined in models
   indexes = [
       models.Index(fields=['user', 'status']),
       models.Index(fields=['property', 'check_in_date']),
   ]
   ```

4. **Cache query results**
   ```python
   from django.views.decorators.cache import cache_page
   
   @cache_page(300)  # Cache for 5 minutes
   def get_available_properties(...): ...
   ```

5. **Use database replicas for read-heavy queries**
   ```python
   # Read from replica
   bookings = Booking.objects.using('replica').filter(...)
   
   # Write to primary  
   booking = Booking.objects.using('default').create(...)
   ```

---

For more details, see [ARCHITECTURE.md](../ARCHITECTURE.md)
