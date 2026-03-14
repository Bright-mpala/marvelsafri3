# MarvelSafari Development Setup Guide (Enterprise Version)

## Prerequisites

- Python 3.10+
- PostgreSQL 12+ (recommended) or SQLite for development
- Redis 6+ (for caching and Celery)
- virtualenv or conda

---

## Quick Start (Development)

### 1. Clone and Setup Environment

```bash
cd travel_booking_platform

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Environment Configuration

```bash
# Copy and configure environment
cp .env.example .env

# Edit .env for development
# ENVIRONMENT=development
# DEBUG=True
# DATABASE_URL=sqlite:///db.sqlite3
# REDIS_URL=redis://localhost:6379/0
```

### 3. Database Setup

```bash
cd travel_booking

# Create migrations
python manage.py makemigrations

# Run migrations
python manage.py migrate

# Create superuser
python manage.py createsuperuser

# (Optional) Load sample data
python manage.py shell
# >>> from django.core.management import call_command
# >>> call_command('loaddata', 'initial_data')

# Create sample properties
python manage.py shell
# >>> from properties.models import PropertyType, Property
# >>> from django.contrib.auth import get_user_model
# >>> User = get_user_model()
# >>> user = User.objects.first()
# >>> prop_type = PropertyType.objects.create(name="Hotel", slug="hotel")
# >>> Property.objects.create(
# ...     name="Sample Hotel",
# ...     slug="sample-hotel",
# ...     description="A nice hotel",
# ...     property_type=prop_type,
# ...     address="123 Main St",
# ...     city="New York",
# ...     postal_code="10001",
# ...     country="US",
# ...     minimum_price=150.00
# ... )
```

### 4. Run Development Server

```bash
# Terminal 1: Django development server
python manage.py runserver

# Terminal 2: Redis (if not running as service)
redis-cli ping  # Check if running
# If not: redis-server (or use Docker)

# Terminal 3: Celery worker (async tasks)
celery -A travel_booking worker --loglevel=info --concurrency=4

# Terminal 4: Celery Beat (scheduled tasks)
celery -A travel_booking beat --loglevel=info

# Access the application
# http://localhost:8000
# Admin: http://localhost:8000/admin
# API: http://localhost:8000/api/v1/
# Health: http://localhost:8000/health/
```

---

## Using the Service Layer

### Example: Creating a Booking

```python
# In Django shell
python manage.py shell

from bookings.services import BookingService
from datetime import date, timedelta
from django.contrib.auth import get_user_model

User = get_user_model()
user = User.objects.first()
property_id = "your-property-uuid"

service = BookingService()

booking = service.create_booking(
    user=user,
    property_id=property_id,
    check_in_date=date.today() + timedelta(days=5),
    check_out_date=date.today() + timedelta(days=7),
    guests=2,
    special_requests="High floor"
)

print(f"Booking created: {booking.id}")
print(f"Total: ${booking.total_amount}")
```

---

## Testing

### Run Tests

```bash
# All tests
python manage.py test

# Specific app
python manage.py test bookings

# Specific test class
python manage.py test bookings.tests.BookingServiceTests

# With coverage
coverage run --source='.' manage.py test
coverage report
coverage html  # Generate HTML report
```

### Running Service Layer Tests

```bash
# Booking service tests
python manage.py test bookings.services

# Repository tests
python manage.py test bookings.repositories

# Validator tests
python manage.py test bookings.validators
```

---

## Using PostgreSQL (Recommended)

### Setup PostgreSQL

```bash
# Install PostgreSQL (macOS)
brew install postgresql@15

# Start PostgreSQL
brew services start postgresql@15

# Create database
createdb marvelsafari_dev

# Create user
createuser marvelsafari
psql -U postgres -d marvelsafari_dev -h localhost -c "ALTER USER marvelsafari WITH PASSWORD 'dev-password';"

# Grant permissions
psql -U postgres -d marvelsafari_dev -h localhost -c "GRANT ALL PRIVILEGES ON DATABASE marvelsafari_dev TO marvelsafari;"
```

### Update .env

```env
DATABASE_URL=postgresql://marvelsafari:dev-password@localhost:5432/marvelsafari_dev
```

### Run Migrations

```bash
python manage.py migrate
```

---

## Redis Setup

### Using Docker (Recommended)

```bash
# Run Redis container
docker run -d --name marvelsafari-redis -p 6379:6379 redis:7-alpine

# Check status
redis-cli ping  # Should return PONG
```

### Manual Installation

```bash
# macOS
brew install redis
brew services start redis

# Linux
sudo apt-get install redis-server
sudo systemctl start redis-server

# Verify
redis-cli ping  # Should return PONG
```

---

## Celery Setup

### Development Configuration

```env
# Use Redis for both broker and result backend
CELERY_BROKER_URL=redis://localhost:6379/2
CELERY_RESULT_BACKEND=redis://localhost:6379/3
```

### Running Celery

```bash
# Terminal 1: Celery Worker
celery -A travel_booking worker --loglevel=info --concurrency=4

# Terminal 2: Celery Beat (Scheduler)
celery -A travel_booking beat --loglevel=info

# Terminal 3: Celery Flower (Monitoring UI)
celery -A travel_booking flower --port=5555
# Access at http://localhost:5555
```

### Testing Tasks

```bash
# Run task synchronously (for testing)
python manage.py shell

from bookings.tasks import expire_pending_bookings
result = expire_pending_bookings.apply_async(kwargs={'minutes': 30})
print(result.get())  # Wait for result
```

---

## Debugging

### Enable Debug Toolbar

```env
DEBUG=True
# Debug Toolbar will be available at http://localhost:8000/__debug__/
```

### View Logs

```bash
# All
python manage.py runserver 2>&1 | tee runserver.log

# Filter
tail -f runserver.log | grep -i error

# Django logs
python manage.py runserver --verbosity=2
```

### Database Queries in Shell

```python
python manage.py shell

from django.db import connection, reset_queries
from django.conf import settings

# Enable query logging
settings.DEBUG = True

from bookings.services import BookingService
service = BookingService()
# ... run some operations ...

# View all queries
for query in connection.queries:
    print(query['sql'])
    print(f"Time: {query['time']}")
```

### Check Service Status

```bash
# Health endpoints
curl http://localhost:8000/health/live
curl http://localhost:8000/health/ready
curl http://localhost:8000/health/deep

# Redis status
redis-cli ping

# Celery status
celery -A travel_booking inspect active

# Database status
python manage.py dbshell
> SELECT COUNT(*) FROM bookings_booking;
```

---

## Environment Switching

### Development

```env
ENVIRONMENT=development
DEBUG=True
DATABASE_URL=sqlite:///db.sqlite3
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=memory://
EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
```

### Staging

```env
ENVIRONMENT=staging
DEBUG=False
DATABASE_URL=postgresql://user:pass@staging-db.example.com/db
REDIS_URL=redis://staging-redis.example.com:6379/0
CELERY_BROKER_URL=redis://staging-redis.example.com:6379/1
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
```

### Production

```env
ENVIRONMENT=production
DEBUG=False
SECRET_KEY=your-super-secret-key-min-50-chars
DATABASE_URL=postgresql://user:pass@prod-db.example.com/db
DATABASE_REPLICA_URL=postgresql://user:pass@prod-replica.example.com/db
REDIS_URL=redis://prod-redis-cluster:6379/0
CELERY_BROKER_URL=redis://prod-redis-cluster:6379/1
SENTRY_DSN=https://...@sentry.io/...
```

---

## Common Commands

```bash
# Create superuser
python manage.py createsuperuser

# Run migrations
python manage.py migrate

# Create migrations
python manage.py makemigrations

# Collect static files
python manage.py collectstatic

# Clear cache
python manage.py shell
>>> from django.core.cache import cache
>>> cache.clear()

# Check for issues
python manage.py check

# Create sample data
python manage.py shell < scripts/load_sample_data.py

# Full test suite
python manage.py test --verbosity=2 --keepdb

# Performance profiling
python manage.py runprofileserver --use-cprofile 0.0.0.0:8000
```

---

## Docker Development (Optional)

### docker-compose.yml

```yaml
version: '3.8'

services:
  db:
    image: postgres:15
    environment:
      POSTGRES_DB: marvelsafari_dev
      POSTGRES_USER: marvelsafari
      POSTGRES_PASSWORD: devpass
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

  app:
    build: .
    command: python manage.py runserver 0.0.0.0:8000
    environment:
      ENVIRONMENT: development
      DATABASE_URL: postgresql://marvelsafari:devpass@db:5432/marvelsafari_dev
      REDIS_URL: redis://redis:6379/0
      CELERY_BROKER_URL: redis://redis:6379/1
    ports:
      - "8000:8000"
    depends_on:
      - db
      - redis
    volumes:
      - .:/app

  celery:
    build: .
    command: celery -A travel_booking worker --loglevel=info
    environment:
      ENVIRONMENT: development
      DATABASE_URL: postgresql://marvelsafari:devpass@db:5432/marvelsafari_dev
      REDIS_URL: redis://redis:6379/0
      CELERY_BROKER_URL: redis://redis:6379/1
    depends_on:
      - db
      - redis
    volumes:
      - .:/app

  beat:
    build: .
    command: celery -A travel_booking beat --loglevel=info
    environment:
      ENVIRONMENT: development
      DATABASE_URL: postgresql://marvelsafari:devpass@db:5432/marvelsafari_dev
      CELERY_BROKER_URL: redis://redis:6379/1
    depends_on:
      - db
      - redis
    volumes:
      - .:/app

volumes:
  postgres_data:
```

### Run with Docker Compose

```bash
docker-compose up

# In another terminal
docker-compose exec app python manage.py migrate
docker-compose exec app python manage.py createsuperuser
```

---

## Troubleshooting

### Issue: "Connection refused" on Redis

```bash
# Check if Redis is running
redis-cli ping

# Start Redis
redis-server

# Or with Homebrew
brew services start redis
```

### Issue: Database migration errors

```bash
# Reset migrations (development only!)
python manage.py migrate bookings zero

# Recreate migrations
python manage.py makemigrations
python manage.py migrate
```

### Issue: Celery tasks not running

```bash
# Check Celery worker status
celery -A travel_booking inspect active

# View logs
celery -A travel_booking worker --loglevel=debug

# Check task routing
celery -A travel_booking inspect active_queues
```

### Issue: Static files not loading

```bash
# Collect static files
python manage.py collectstatic --noinput --clear

# Check STATIC_ROOT
python manage.py shell
>>> from django.conf import settings
>>> print(settings.STATIC_ROOT)
```

---

## Next Steps

1. Review [ARCHITECTURE.md](ARCHITECTURE.md) for system design
2. Follow [IMPLEMENTATION_GUIDE.md](IMPLEMENTATION_GUIDE.md) for service layer usage
3. Run tests: `python manage.py test`
4. Explore admin: http://localhost:8000/admin
5. Try API endpoints: http://localhost:8000/api/v1/

Happy developing! 🚀
