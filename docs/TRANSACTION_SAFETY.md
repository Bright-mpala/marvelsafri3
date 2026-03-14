# Transaction-Safe Booking Workflow (Phase 3)

## Problem: Double-Booking Race Condition

### Without Locking (UNSAFE)

```
Timeline:
┌────────────────────────────────────────────────────────┐
│ 10:00:00 - User A: Check availability for Room 101    │ SELECT * FROM...
│            Result: AVAILABLE ✓                          │
├────────────────────────────────────────────────────────┤
│ 10:00:01 - User B: Check availability for Room 101    │ SELECT * FROM...
│            Result: AVAILABLE ✓                          │
├────────────────────────────────────────────────────────┤
│ 10:00:02 - User A: Create booking                      │ INSERT INTO bookings...
│            SUCCESS ✓                                     │
├────────────────────────────────────────────────────────┤
│ 10:00:03 - User B: Create booking                      │ INSERT INTO bookings...
│            SUCCESS ✓ (DOUBLE-BOOKED! ❌)              │
└────────────────────────────────────────────────────────┘

Both bookings created for same property, same dates!
```

### With Row-Level Locking (SAFE)

```
Timeline:
┌────────────────────────────────────────────────────────┐
│ 10:00:00 - User A: BEGIN TRANSACTION                   │
│            Lock property row: LOCK ACQUIRED             │
│            Check availability: AVAILABLE                │
├────────────────────────────────────────────────────────┤
│ 10:00:01 - User B: BEGIN TRANSACTION                   │
│            Lock property row: WAITING... (blocked)      │
├────────────────────────────────────────────────────────┤
│ 10:00:02 - User A: Create booking: SUCCESS             │
│            COMMIT & Release lock                        │
├────────────────────────────────────────────────────────┤
│ 10:00:03 - User B: Lock acquired                       │
│            Re-check availability: NOT AVAILABLE ❌      │
│            Error: "Property not available"              │
│            ROLLBACK                                      │
└────────────────────────────────────────────────────────┘

Only User A's booking succeeds. User B gets clear error.
```

---

## Solution: SELECT FOR UPDATE

### Key Concept

```python
from django.db import transaction

with transaction.atomic():
    # Lock the property row
    property = Property.objects.select_for_update().get(id=property_id)
    
    # Re-check availability after acquiring lock
    overlapping = Booking.objects.filter(
        property_id=property.id,
        status__in=['pending', 'confirmed'],
        check_in_date__lt=check_out_date,
        check_out_date__gt=check_in_date,
    ).exists()
    
    if overlapping:
        raise BookingError("Property not available")
    
    # Create booking
    booking = Booking.objects.create(
        property=property,
        check_in_date=check_in_date,
        check_out_date=check_out_date,
        ...
    )
    # Lock automatically released when transaction commits
```

### SQL Generated

```sql
-- Django ORM: Property.objects.select_for_update().get(id=...)
BEGIN TRANSACTION;

SELECT * FROM properties_property 
WHERE id = 'property-uuid'
FOR UPDATE;
-- This locks the row until transaction ends

SELECT * FROM bookings_booking
WHERE property_id = 'property-uuid'
  AND status IN ('pending', 'confirmed')
  AND check_in_date < '2024-12-01'
  AND check_out_date > '2024-11-25';

INSERT INTO bookings_booking (user_id, property_id, check_in_date, ...) 
VALUES (...)

COMMIT;
-- Lock released here
```

---

## Database Optimization for Transaction Safety

### 1. Indexes for Fast Queries

```python
# Already defined in bookings/models.py

class Booking(models.Model):
    class Meta:
        indexes = [
            # For booking list queries
            models.Index(fields=['user', 'status']),
            
            # For availability checking (CRITICAL)
            models.Index(fields=['property', 'check_in_date', 'check_out_date']),
            
            # For sorting and filtering
            models.Index(fields=['status', 'check_in_date']),
        ]
```

### 2. Database Constraints

```python
# bookings/migrations/0002_add_constraints.py

from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [
        ('bookings', '0001_initial'),
    ]

    operations = [
        # Prevent logical invalid states
        migrations.AlterField(
            model_name='booking',
            name='status',
            field=models.CharField(
                choices=[
                    ('pending', 'Pending'),
                    ('confirmed', 'Confirmed'),
                    ('cancelled', 'Cancelled'),
                    ('completed', 'Completed'),
                ],
                max_length=20,
            ),
        ),
        
        # Add CHECK constraint
        migrations.RunSQL(
            sql='ALTER TABLE bookings_booking ADD CONSTRAINT check_dates CHECK (check_out_date > check_in_date);',
            reverse_sql='ALTER TABLE bookings_booking DROP CONSTRAINT check_dates;',
        ),
        
        # Add index for availability queries
        migrations.RunSQL(
            sql='''
            CREATE INDEX idx_booking_property_active_dates 
            ON bookings_booking (property_id, check_in_date, check_out_date) 
            WHERE status IN ('pending', 'confirmed');
            ''',
            reverse_sql='DROP INDEX idx_booking_property_active_dates;',
        ),
    ]
```

### 3. Partial Indexes (PostgreSQL)

```python
# Only index active bookings (small index, fast queries)

# bookings/migrations/0003_add_partial_index.py

from django.db import migrations

class Migration(migrations.Migration):
    dependencies = [
        ('bookings', '0002_add_constraints'),
    ]

    operations = [
        migrations.RunSQL(
            sql='''
            CREATE INDEX idx_booking_property_status 
            ON bookings_booking (property_id, check_in_date, check_out_date) 
            WHERE status IN ('pending', 'confirmed');
            ''',
            reverse_sql='DROP INDEX idx_booking_property_status;',
        ),
    ]
```

---

## Implementation in Service Layer

### The BookingRepository with Locking

```python
# bookings/repositories.py

class BookingRepository:
    
    @staticmethod
    @transaction.atomic
    def create_booking(user, property_obj, check_in_date, check_out_date, ...):
        """
        Create booking with transaction safety.
        
        1. Acquire lock on property
        2. Re-check availability
        3. Create booking
        4. Automatic rollback on error
        """
        from core.exceptions import NonRecoverableBookingError
        
        # CRITICAL: Lock property row to prevent race conditions
        try:
            property = Property.objects.select_for_update().get(
                id=property_obj.id
            )
        except Property.DoesNotExist:
            raise NonRecoverableBookingError('Property not found')
        
        # Re-check availability after acquiring lock
        overlapping = Booking.objects.filter(
            property_id=property.id,
            status__in=['pending', 'confirmed'],
            check_in_date__lt=check_out_date,
            check_out_date__gt=check_in_date,
        ).exists()
        
        if overlapping:
            raise NonRecoverableBookingError(
                'Property not available for these dates'
            )
        
        # Safe to create booking now
        booking = Booking.objects.create(
            user=user,
            property=property,
            check_in_date=check_in_date,
            check_out_date=check_out_date,
            guests=guests,
            price_per_night=price_per_night,
            total_amount=total_amount,
            status='pending'
        )
        
        return booking
        # Transaction commits here, lock released
```

---

## Testing Transaction Safety

### Unit Test: Concurrent Bookings

```python
# bookings/tests.py

from django.test import TransactionTestCase
from django.db import connection
from concurrent.futures import ThreadPoolExecutor
import threading

class BookingTransactionSafetyTests(TransactionTestCase):
    """Test transaction safety using actual database transactions."""
    
    def setUp(self):
        self.user1 = User.objects.create(email='user1@example.com')
        self.user2 = User.objects.create(email='user2@example.com')
        self.property = Property.objects.create(
            name="Hotel",
            slug="hotel",
            property_type=PropertyType.objects.create(name="Hotel", slug="hotel"),
            minimum_price=100
        )
    
    def test_concurrent_bookings_prevented(self):
        """Test that concurrent bookings for same dates are prevented."""
        
        from bookings.services import BookingService
        
        check_in = date.today() + timedelta(days=10)
        check_out = date.today() + timedelta(days=12)
        
        service = BookingService()
        results = {
            'user1_result': None,
            'user1_error': None,
            'user2_result': None,
            'user2_error': None,
        }
        
        def book_user1():
            try:
                booking = service.create_booking(
                    user=self.user1,
                    property_id=self.property.id,
                    check_in_date=check_in,
                    check_out_date=check_out,
                    guests=1
                )
                results['user1_result'] = booking
            except Exception as e:
                results['user1_error'] = str(e)
        
        def book_user2():
            # Small delay to ensure overlap
            threading.Event().wait(0.1)
            try:
                booking = service.create_booking(
                    user=self.user2,
                    property_id=self.property.id,
                    check_in_date=check_in,
                    check_out_date=check_out,
                    guests=1
                )
                results['user2_result'] = booking
            except Exception as e:
                results['user2_error'] = str(e)
        
        # Run concurrently
        with ThreadPoolExecutor(max_workers=2) as executor:
            executor.submit(book_user1)
            executor.submit(book_user2)
        
        # Verify only one booking succeeded
        successful_bookings = [
            results['user1_result'],
            results['user2_result']
        ]
        successful_bookings = [b for b in successful_bookings if b is not None]
        
        self.assertEqual(len(successful_bookings), 1, 
            "Only 1 booking should succeed")
        
        # Verify other got error
        if results['user1_error']:
            self.assertIn('not available', results['user1_error'].lower())
        if results['user2_error']:
            self.assertIn('not available', results['user2_error'].lower())
```

### Integration Test: Happy Path

```python
def test_booking_creation_happy_path(self):
    """Test successful booking creation flow."""
    
    check_in = date.today() + timedelta(days=5)
    check_out = date.today() + timedelta(days=7)
    
    service = BookingService()
    
    booking = service.create_booking(
        user=self.user1,
        property_id=self.property.id,
        check_in_date=check_in,
        check_out_date=check_out,
        guests=2,
        special_requests="High floor"
    )
    
    self.assertEqual(booking.user, self.user1)
    self.assertEqual(booking.property, self.property)
    self.assertEqual(booking.status, 'pending')
    self.assertEqual(booking.guests, 2)
    self.assertEqual(booking.special_requests, "High floor")
    self.assertGreater(booking.total_amount, 0)
```

---

## Handling Errors

### User Sees Clear Error

```python
# API View

from rest_framework.response import Response
from rest_framework import status

@api_view(['POST'])
def create_booking(request):
    try:
        booking = BookingService().create_booking(...)
        return Response({
            'success': True,
            'booking': BookingSerializer(booking).data
        })
    
    except InvalidDataError as e:
        # Bad input (e.g., invalid dates)
        return Response({
            'success': False,
            'error': e.message,
            'error_id': e.error_id
        }, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
    
    except NonRecoverableBookingError as e:
        # Business logic error (e.g., double-book)
        return Response({
            'success': False,
            'error': e.message,
            'error_id': e.error_id
        }, status=status.HTTP_409_CONFLICT)
```

---

## Performance Considerations

### Lock Wait Times

```sql
-- In high concurrency, some requests wait for lock

-- Good: Most locks released quickly (< 100ms)
-- Bad: Locks held for seconds (database degradation)

-- Monitor lock performance:
SELECT 
    relation::regclass,
    database,
    transaction,
    locked_mode,
    waiting
FROM pg_locks 
WHERE waiting;  -- Shows waiting locks

-- Identify slow queries:
SELECT query, calls, mean_time FROM pg_stat_statements
ORDER BY mean_time DESC LIMIT 10;
```

### Optimization Strategies

1. **Keep transactions short**
   ```python
   # GOOD: Quick lock
   with transaction.atomic():
       property = Property.objects.select_for_update().get(id=property_id)
       overlapping = Booking.objects.filter(...).exists()  # Fast query
       booking = Booking.objects.create(...)
       # Lock released immediately
   ```

2. **Use database connection pooling**
   ```python
   # In production settings:
   DATABASES['default']['CONN_MAX_AGE'] = 600
   # Reuse connections to reduce overhead
   ```

3. **Index aggressively**
   ```python
   # Indexes on filtered columns
   models.Index(fields=['property', 'check_in_date', 'check_out_date']),
   
   # Prevents full table scans
   # Speeds up lock acquisition
   ```

4. **Cache availability grid** (Redis)
   ```python
   # Pre-compute available dates for each property
   # Update on booking creation
   # Serve from cache (no database lock needed for queries)
   ```

---

## Monitoring

### Set Up Alerts

```python
# bookings/monitoring.py

from django.core.management import BaseCommand
import logging

class CheckLockContention(BaseCommand):
    def handle(self, *args, **options):
        from django.db import connection
        
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT 
                    database,
                    count(*) as waiting_count
                FROM pg_locks 
                WHERE waiting
                GROUP BY database
            """)
            
            for db, count in cursor.fetchall():
                if count > 5:
                    logging.warning(
                        f"High lock contention on {db}: {count} waiting"
                    )
```

---

## Best Practices Summary

✅ **DO**:
- Use `select_for_update()` to prevent race conditions
- Keep transactions short and focused
- Index columns used in WHERE clauses
- Test with concurrent users
- Monitor lock contention
- Handle exceptions gracefully
- Log errors with request tracking

❌ **DON'T**:
- Check availability then create separately (gap for race condition)
- Hold locks during external API calls
- Forget to wrap in `transaction.atomic()`
- Use locks for read-only operations
- Trust client-side validation alone
- Ignore database constraints

---

## Further Reading

- [Django Transactions Documentation](https://docs.djangoproject.com/en/5.2/topics/db/transactions/)
- [PostgreSQL Row Locking](https://www.postgresql.org/docs/15/explicit-locking.html)
- [ACID Compliance](https://en.wikipedia.org/wiki/ACID)
- [Optimistic vs Pessimistic Locking](https://en.wikibooks.org/wiki/Java_Persistence/Locking)
