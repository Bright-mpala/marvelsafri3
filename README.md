# Travel Booking Platform - Production Ready

A professional Django-based travel accommodation booking platform with comprehensive features for users, properties, and admin management.

## Features

### Core Features
- **User Management**: Registration, login, profile management with custom user model
- **Property Listings**: Browse, search, and filter properties with detailed information
- **Booking System**: Create bookings with date validation and double-booking prevention
- **Admin Panel**: Comprehensive admin interface for managing all aspects of the platform
- **Authentication**: Email-based authentication with password reset functionality

### Advanced Features
- **Business Accounts**: Support for corporate travel accounts
- **Price Planning**: Dynamic pricing with seasonal adjustments
- **Booking Validation**: Prevent double bookings with date overlap detection
- **Property Amenities**: Comprehensive amenity management with hierarchical categories
- **Reviews & Ratings**: User review system with approval workflow
- **Multi-currency**: Support for multiple currencies and languages
- **API Integration**: RESTful API for third-party integrations
- **Analytics**: Track bookings, views, and performance metrics

## AI Intelligence Layer

MarvelSafari now ships with an AI intelligence layer that plugs into the existing Django stack without redesigning the rest of the product experience. The layer currently delivers:

- **AI Concierge Chatbot** – answers booking, cancellation, visa, and policy questions with MarvelSafari tone of voice.
- **AI Itinerary Generator** – turns destination + budget + days into JSON itineraries that existing templates can render.
- **AI Destination Recommendations** – blends user preferences with stored search history (session data or payload) to propose ranked destinations.
- **AI SEO Content Blocks** – produces JSON chunks for landing pages (hero copy, highlights, FAQ, meta description) aligned with MarvelSafari brand guidelines.

### Installation & Upgrades

Run the following commands inside your virtual environment to make sure the latest OpenAI SDK and tokenizer are available before you migrate or start the server:

```bash
pip install --upgrade "openai>=1.51.0,<2.0" "tiktoken>=0.7.0,<0.8"
pip install -r requirements.txt
```

### Environment Configuration (secure .env storage)

Append these secrets to your `.env` or secret manager (never commit the actual keys):

```
OPENAI_API_KEY=sk-live-your-key
OPENAI_ORG_ID=org-example
AI_OPENAI_TIMEOUT=30
AI_OPENAI_MAX_RETRIES=2
AI_MAX_DAILY_TOKENS=200000
AI_MAX_DAILY_COST_USD=75.0
AI_PROMPT_COST_PER_1K=0.005
AI_COMPLETION_COST_PER_1K=0.015
AI_RATE_LIMIT_REQUESTS_PER_MIN=20
```

### Django Endpoints

| Endpoint | Method | Purpose |
| --- | --- | --- |
| `/ai/support/chatbot/` | POST | Customer-support chatbot (booking, cancellation, visa, policies). |
| `/ai/itineraries/generate/` | POST | Destination + budget + days → structured itinerary JSON. |
| `/ai/destinations/recommend/` | POST | Ranked destination recommendations using preferences + history. |
| `/ai/seo/generate/` | POST | SEO landing-page content (hero title, highlights, FAQ, meta). |

### Frontend AJAX Example

```javascript
async function generateItinerary() {
    const response = await fetch('/ai/itineraries/generate/', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': window.csrfToken,
        },
        body: JSON.stringify({
            destination: document.querySelector('#destination').value,
            budget: document.querySelector('#budget').value,
            days: Number(document.querySelector('#days').value),
            travel_style: document.querySelector('#travelStyle').value || 'balanced',
            interests: Array.from(document.querySelectorAll('input[name="interests"]:checked')).map(
                (el) => el.value,
            ),
        }),
    });

    if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || 'AI request failed');
    }

    const payload = await response.json();
    renderItinerary(payload.data.daily_plan);
}
```

### Error Handling, Rate Limiting, and Logging

- Requests are wrapped with `django-ratelimit` (`AI_RATE_LIMIT_REQUESTS_PER_MIN`) so abusive spikes are blocked before hitting OpenAI.
- The reusable `ai_assistant.ai_service.OpenAIAIService` raises clear `AIServiceError`/`TokenBudgetExceeded` exceptions that views translate into `429`/`503` responses.
- AI usage is logged via the `ai_assistant.usage` logger; each log event includes prompt/completion tokens, USD cost, and the running daily totals for observability dashboards.

### Token Cost Control Strategy

`AIUsageTracker` enforces two guardrails before and after every OpenAI call:

1. **Pre-flight guard** – estimates prompt tokens with `tiktoken` and rejects the call if it would exceed `AI_MAX_DAILY_TOKENS` or the derived cost ceiling.
2. **Post-flight ledger** – persists the actual prompt/completion tokens plus estimated USD cost into Django’s cache (36-hour TTL) and stops subsequent calls once the cap is reached.

Tune `AI_MAX_DAILY_TOKENS`, `AI_MAX_DAILY_COST_USD`, and the per-1k pricing knobs to match whatever model tier you negotiated with OpenAI.

## Technology Stack

- **Backend**: Django 5.2
- **Database**: PostgreSQL (recommended for production)
- **Frontend**: Tailwind CSS + HTML5
- **API**: Django REST Framework
- **Authentication**: Django-allauth
- **Caching**: Redis
- **Email**: Django email backend
- **Task Queue**: Celery (optional)

## Installation

### Prerequisites
- Python 3.10+
- pip and virtualenv
- PostgreSQL (for production)

### Local Development Setup

```bash
# 1. Clone the repository
cd travel_booking_platform

# 2. Create and activate virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Create .env file with settings
cp .env.example .env  # Create from template or configure manually

# 5. Run migrations
cd travel_booking
python manage.py migrate

# 6. Create superuser
python manage.py createsuperuser

# 7. Collect static files
python manage.py collectstatic --noinput

# 8. Run development server
python manage.py runserver
```

## Configuration

### Environment Variables (.env)
```
DEBUG=True
SECRET_KEY=your-secret-key-here
ALLOWED_HOSTS=localhost,127.0.0.1

# Database
DATABASE_URL=sqlite:///db.sqlite3  # For development
# DATABASE_URL=postgresql://user:password@localhost/dbname  # For production

# Email
EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=your-email@gmail.com
EMAIL_HOST_PASSWORD=your-app-password

# Payment (if using Stripe)
STRIPE_PUBLIC_KEY=your-stripe-public-key
STRIPE_SECRET_KEY=your-stripe-secret-key

# Redis (for caching)
REDIS_URL=redis://localhost:6379/0
```

## Project Structure

```
travel_booking_platform/
├── travel_booking/              # Main Django project
│   ├── settings.py             # Project settings
│   ├── urls.py                 # URL routing
│   ├── wsgi.py                 # WSGI configuration
│   └── admin.py                # Custom admin site
│
├── accounts/                    # User management app
│   ├── models.py               # User, UserProfile, BusinessAccount
│   ├── views.py                # Authentication & profile views
│   └── forms.py                # User forms
│
├── properties/                  # Property management app
│   ├── models.py               # Property, RoomType, Amenity models
│   ├── views.py                # Property listing & detail views
│   └── admin.py                # Property admin
│
├── bookings/                    # Booking management app
│   ├── models.py               # Booking model with validation
│   ├── views.py                # Booking CRUD views
│   ├── forms.py                # Booking forms with validation
│   └── admin.py                # Booking admin
│
├── reviews/                     # Review system app
├── payments/                    # Payment processing app
├── notifications/               # Notification system app
├── analytics/                   # Analytics app
│
├── templates/                   # Django templates
│   ├── base.html               # Base template
│   ├── properties/             # Property templates
│   ├── bookings/               # Booking templates
│   └── accounts/               # Account templates
│
├── static/                      # Static files (CSS, JS, images)
├── media/                       # User-uploaded files
├── db.sqlite3                   # SQLite database (development only)
└── manage.py                    # Django management script
```

## Database Models

### Key Models

#### User Model (Custom)
- Email-based authentication
- Profile picture and contact information
- Preferred language and currency settings
- Business account flag
- Verification status tracking

#### Property Model
- UUID primary key for security
- Comprehensive property information
- Location data with coordinates
- Host/manager information
- Status workflow (draft → pending → active)
- Amenities and tags

#### Booking Model
- Date-based reservations
- Guest information
- Total amount calculation
- Status workflow
- Double-booking prevention via validation
- Special requests field

#### Supporting Models
- PropertyType, Amenity, AmenityCategory
- RoomType, Room, PropertyImage
- PricePlan, Availability
- PropertyDocument
- UserProfile, BusinessAccount

## API Endpoints

### Properties
- `GET /properties/` - List all properties
- `GET /properties/<slug>/` - Get property details
- `GET /properties/search/` - Search properties
- `GET /properties/api/availability/` - Check availability

### Bookings
- `GET /bookings/` - List user bookings
- `GET /bookings/<id>/` - Get booking details
- `POST /bookings/create/<property_id>/` - Create booking
- `POST /bookings/<id>/cancel/` - Cancel booking

### Accounts
- `POST /auth/register/` - User registration
- `POST /auth/login/` - User login
- `POST /auth/logout/` - User logout
- `GET /auth/dashboard/` - User dashboard
- `GET /auth/profile/` - View profile
- `POST /auth/profile/edit/` - Edit profile

## Admin Panel

Access the admin panel at `/admin/` after logging in as a superuser.

### Customizations
- Custom user admin with detailed field organization
- Booking admin with status visualization and bulk actions
- Property admin with inline room types and pricing
- Amenity management with categories
- Document management for properties

## Validation Features

### Booking Validation
- ✅ Check-in date cannot be in the past
- ✅ Check-out must be after check-in
- ✅ Minimum 1 night stay requirement
- ✅ Maximum 365 nights per booking
- ✅ Overlapping booking prevention
- ✅ Guest count validation (1-10)

### Form Validation
- Email uniqueness checking
- Password complexity requirements
- Date format validation
- Phone number validation
- Currency and language selection

## Best Practices Implemented

### Code Quality
- ✅ Class-based views for scalability
- ✅ Proper ORM usage with select_related/prefetch_related
- ✅ Model validation in clean() methods
- ✅ Transaction management for data consistency
- ✅ DRY principle throughout codebase

### Security
- ✅ CSRF protection on all forms
- ✅ SQL injection prevention via ORM
- ✅ Password hashing with Django's contrib.auth
- ✅ Email verification system
- ✅ Double booking prevention

### Performance
- ✅ Database query optimization
- ✅ Pagination for list views
- ✅ Caching support with Redis
- ✅ Static file compression
- ✅ Image optimization

### Maintainability
- ✅ Comprehensive docstrings
- ✅ Consistent code style
- ✅ Modular app structure
- ✅ Reusable forms and templates
- ✅ Clear separation of concerns

## Running Tests

```bash
# Run all tests
python manage.py test

# Run specific app tests
python manage.py test accounts
python manage.py test bookings
python manage.py test properties

# Run with coverage
coverage run --source='.' manage.py test
coverage report
```

## Production Deployment

### Prerequisites
- PostgreSQL database
- Redis for caching
- Domain name
- SSL certificate

### Deployment Steps

1. **Environment Setup**
```bash
export DEBUG=False
export SECRET_KEY=$(python -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())')
export ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com
export DATABASE_URL=postgresql://user:password@localhost/travel_db
```

2. **Database Migration**
```bash
python manage.py migrate --no-input
```

3. **Static Files**
```bash
python manage.py collectstatic --noinput
```

4. **Run with Gunicorn**
```bash
gunicorn travel_booking.wsgi:application --bind 0.0.0.0:8000 --workers 4
```

5. **Nginx Configuration** (example)
```nginx
server {
    listen 80;
    server_name yourdomain.com;

    location /static/ {
        alias /app/staticfiles/;
    }

    location /media/ {
        alias /app/media/;
    }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### Using Docker

```dockerfile
FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

RUN python manage.py collectstatic --noinput

CMD ["gunicorn", "travel_booking.wsgi:application", "--bind", "0.0.0.0:8000"]
```

## Troubleshooting

### Common Issues

1. **Database connection errors**
   - Ensure database is running
   - Check DATABASE_URL in .env
   - Verify credentials

2. **Static files not loading**
   - Run `python manage.py collectstatic`
   - Check STATIC_URL and STATIC_ROOT in settings

3. **Email not sending**
   - Verify EMAIL settings in .env
   - Check email provider SMTP settings
   - Look for errors in server logs

4. **Import errors**
   - Ensure virtual environment is activated
   - Run `pip install -r requirements.txt`
   - Check Python path

## Contributing

1. Follow Django best practices
2. Add tests for new features
3. Update documentation
4. Use descriptive commit messages
5. Keep code DRY and modular

## Support

For issues or questions, please create an issue in the repository or contact the development team.

## License

This project is proprietary and confidential.

---

**Last Updated**: February 26, 2026
**Version**: 1.0.0
**Status**: Production Ready
