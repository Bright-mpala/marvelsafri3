# MarvelSafari: Enterprise-Scale Booking Platform Architecture

## Overview
MarvelSafari is evolving from a traditional Django monolith into a **modular, service-oriented architecture** capable of handling millions of users while maintaining domain-driven design principles and future microservice extractability.

---

## Architecture Principles

### 1. **Domain-Driven Design (DDD)**
- Clear service boundaries around booking domains
- Rich domain models with explicit business logic
- Repository pattern for data access abstraction
- Service layer for orchestration and transaction management

### 2. **Service-Oriented Architecture (SOA)**
- Decouple business logic into distinct services:
  - **Identity Service** (accounts, authentication, RBAC)
  - **Booking Service** (core booking operations, inventory management)
  - **Search Service** (advanced filtering, pagination, recommendations)
  - **Inventory Service** (property availability, pricing, capacity)
  - **Review Service** (ratings, user-generated content)
  - **Analytics Service** (events, metrics, business intelligence)
  - **Notification Service** (emails, SMS, push notifications)
  - **Payment Service** (payment processing, transactions)

### 3. **Scalability & High Availability**
- **Horizontal Scaling**: Stateless app servers behind load balancer
- **Database Optimization**: PostgreSQL with indexing, partitioning, query optimization
- **Caching Layer**: Redis for frequently accessed data, session storage
- **Async Processing**: Celery for background tasks, decoupling, resource optimization
- **Message Queue**: Distributed task queue for event-driven architecture

### 4. **Fault Tolerance & Resilience**
- Idempotent APIs for safe retries
- Circuit breaker patterns for external service calls
- Transaction safety with row-level locking for booking operations
- Dead letter queues for failed async tasks
- Graceful degradation when services fail

### 5. **Data & Transaction Management**
- **ACID Compliance** for critical operations (bookings, payments)
- **Transaction-Safe Booking Workflow**:
  - Pessimistic locking (SELECT FOR UPDATE) to prevent double-booking
  - Atomic state transitions
  - Clear cancellation policies and refund workflows
  - Audit trail for all state changes

---

## Service Architecture

### Booking Service (Core)
**Responsibility**: Handle all booking operations with transactional integrity

**Key Components**:
- `BookingRepository`: Abstraction for data access
- `BookingService`: Business logic orchestration
- `BookingValidator`: Validation rules engine
- `AvailabilityService`: Check property availability with row-level locking
- `BookingStateTransition`: Explicit state machine for booking lifecycle

**Lock Strategy**:
```sql
-- Prevent double-booking using row-level locking
SELECT * FROM properties_property 
WHERE id = property_id 
FOR UPDATE;

-- Check overlapping bookings within transaction
SELECT * FROM bookings_booking 
WHERE property_id = property_id 
  AND status IN ('pending', 'confirmed')
  AND check_in_date < check_out_date
  AND check_out_date > check_in_date
FOR UPDATE;
```

### Search Service
**Responsibility**: High-performance search, filtering, sorting, pagination

**Key Components**:
- `SearchFilter`: Advanced filtering engine
- `SearchIndexer`: Redis-based search index
- `PropertySearchRepository`: Optimized read-only queries
- `SearchCacheService`: Distributed caching

### Identity Service
**Responsibility**: Authentication, authorization, user management

**Key Components**:
- `UserRepository`: Custom user data access
- `AuthService`: JWT token management, refresh tokens
- `PermissionService`: Role-based access control (RBAC)
- `TwoFactorService`: 2FA for high-security operations

### Inventory Service
**Responsibility**: Manage property availability, pricing, capacity

**Key Components**:
- `InventoryRepository`: Property availability data access
- `PricingService`: Dynamic pricing rules
- `AvailabilityGrid`: Date-based availability tracking

### Analytics Service
**Responsibility**: Event tracking, metrics, business intelligence

**Key Components**:
- `AnalyticsEvent`: Base event class
- `EventPublisher`: Async event publishing
- `MetricsCollector`: Performance metrics

---

## Database Design (PostgreSQL)

### Optimization Strategies

#### 1. **Indexing**
```sql
-- Booking queries
CREATE INDEX idx_booking_property_dates 
  ON bookings_booking(property_id, check_in_date, check_out_date) 
  WHERE status IN ('pending', 'confirmed');

CREATE INDEX idx_booking_user_status 
  ON bookings_booking(user_id, status);

-- Property search
CREATE INDEX idx_property_type_status 
  ON properties_property(property_type_id, status) 
  WHERE status = 'active';

CREATE INDEX idx_property_location 
  ON properties_property(city, country);

-- Full-text search
CREATE INDEX idx_property_search 
  ON properties_property 
  USING GIN(to_tsvector('english', name || ' ' || description));
```

#### 2. **Partitioning**
```sql
-- Time-based partitioning for bookings
CREATE TABLE bookings_booking_2025_q1 PARTITION OF bookings_booking
  FOR VALUES FROM ('2025-01-01') TO ('2025-04-01');
```

#### 3. **Constraints**
```sql
-- Prevent overlapping bookings at database level
ALTER TABLE bookings_booking
ADD CONSTRAINT check_checkout_after_checkin 
  CHECK (check_out_date > check_in_date);
```

---

## Caching Strategy (Redis)

### Cache Layers
1. **Session Layer** (`SESSION_ENGINE = 'django.contrib.sessions.backends.cache'`)
2. **Query Cache** (ORM query results for 5-15 minutes)
3. **Search Cache** (filtered search results with TTL)
4. **Configuration Cache** (amenities, property types, static data)
5. **Rate Limiting** (per-user/per-IP request quotas)

### Cache Invalidation Patterns
- **Time-based**: TTL for all cache entries
- **Event-based**: Invalidate on model changes
- **Tag-based**: Group related cache entries for mass invalidation

---

## Asynchronous Processing (Celery)

### Background Tasks

```python
# High-priority tasks
- Email notifications (booking confirmations, cancellations)
- Payment processing webhooks
- Booking expiration (auto-cancel unpaid bookings)

# Medium-priority tasks
- Review reminders (send after stay completion)
- Analytics event logging
- Search index updates

# Low-priority tasks
- Newsletter sending
- Report generation
- Data synchronization
```

### Task Workflow
```
User Action → Celery Task Queue → Worker Pool → Result Backend → Notification
```

---

## API Architecture

### Versioning Strategy
```
/api/v1/bookings       # Current stable API
/api/v2/bookings       # New features, breaking changes
/api/internal/metrics  # Internal only endpoints
```

### Response Structure
```json
{
  "success": true,
  "data": {...},
  "errors": ["error1", "error2"],
  "metadata": {
    "timestamp": "2024-01-15T10:30:00Z",
    "request_id": "uuid",
    "api_version": "1"
  }
}
```

### Rate Limiting
- **Anonymous**: 100 requests/hour per IP
- **Authenticated**: 1000 requests/hour per user
- **Premium Users**: 10000 requests/hour
- **Admin**: Unlimited

---

## Security Architecture

### Authentication Flow
```
1. User login → 2. Issue JWT + Refresh Token → 3. Store refresh in HTTP-only cookie
4. Access with JWT in Authorization header → 5. Refresh when expired
```

### Authorization (RBAC)
```
Roles: Guest, User, Property Owner, Admin, Superadmin

Resource-Level Permissions:
- User can only view/edit their own bookings
- Property Owner can manage their own properties
- Admin can manage users and properties
```

### Data Security
- Encryption at rest (database columns for sensitive data)
- HTTPS only in production
- SQL injection protection (ORM parameterized queries)
- XSS protection (template auto-escaping)
- CSRF protection (Django middleware)

---

## Monitoring & Observability

### Structured Logging
```json
{
  "timestamp": "2024-01-15T10:30:00Z",
  "level": "INFO",
  "logger": "bookings.service",
  "message": "Booking created",
  "context": {
    "booking_id": "12345",
    "user_id": "user_uuid",
    "service": "BookingService",
    "duration_ms": 234
  },
  "request_id": "req_uuid"
}
```

### Key Metrics
- **Request latency** (p50, p95, p99)
- **Error rate** (by endpoint, by error type)
- **Queue depth** (Celery tasks pending)
- **Cache hit/miss ratio**
- **Database query time**
- **Active connections**

### Health Checks
```
/health/live      # Is app running?
/health/ready     # Is app ready to accept traffic?
/health/deep      # Database, Redis, Celery connection status
```

---

## Deployment Architecture

### Environment Configuration
```
Development  → SQLite, LocalMemCache, Celery (sync), Debug=True
Staging      → PostgreSQL, Redis, Celery, Debug=False, SSL
Production   → PostgreSQL (replicated), Redis (cluster), Celery (multiple workers), SSL, WAF
```

### Container Orchestration
```
┌─────────────────────────────────────────────────────┐
│            Nginx Load Balancer                      │
└────────┬──────────────────────────────┬─────────────┘
         │                              │
    ┌────▼─────┐                  ┌─────▼────┐
    │ App Pod 1 │                  │ App Pod 2 │
    │ Django    │                  │ Django   │
    └────┬─────┘                  └─────┬────┘
         │                              │
    ┌────▼──────────────────────────────▼─────┐
    │      PostgreSQL Primary               │
    │      (with streaming replication)      │
    └─────────────────────────────────────────┘
         │
    ┌────▼─────┐
    │ PostgreSQL│
    │ Replica  │
    └──────────┘

Parallel:
┌─────────────────────────────────────────────────────┐
│   Celery Worker Pool (multiple workers)            │
│   - High priority queue                            │
│   - Default queue                                  │
│   - Low priority queue                             │
└─────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────┐
│   Redis Cluster                                    │
│   - Caching layer                                  │
│   - Session storage                                │
│   - Rate limiting                                  │
└─────────────────────────────────────────────────────┘
```

### Horizontal Scaling
1. **Stateless App Servers**: Deploy multiple instances
2. **Sticky Sessions**: Use Redis for distributed sessions
3. **Shared Database**: PostgreSQL with read replicas
4. **Distributed Cache**: Redis cluster
5. **Task Queue**: Celery with multiple workers

---

## Migration Path to Microservices

### Phase 1: Modular Monolith (Current)
Django apps with service interfaces ready for extraction

### Phase 2: Async Decoupling
Event-driven architecture using message queue (RabbitMQ/Kafka)

### Phase 3: Service Extraction
Convert critical services to independent microservices:
1. Identity Service (separate API)
2. Booking Service (separate API)
3. Search Service (separate API)
4. Analytics Service (separate API)

### Phase 4: Full Microservices
Complete decomposition with API Gateway

---

## Technology Stack v2

| Layer | Technology | Purpose |
|-------|-----------|---------|
| **Framework** | Django 5.2 | Web framework |
| **REST API** | Django REST Framework | API layer |
| **Database** | PostgreSQL 16+ | Primary data store |
| **Cache** | Redis 7+ | Caching, sessions, rate limiting |
| **Task Queue** | Celery 5.3+ | Async processing |
| **Message Broker** | Redis/RabbitMQ | Task queue broker |
| **Search** | PostgreSQL FTS + Redis | Full-text search, caching |
| **Auth** | JWT (djangorestframework-simplejwt) | API authentication |
| **RBAC** | django-guardian | Fine-grained permissions |
| **Logging** | Python logging + JSON | Structured logging |
| **Monitoring** | Prometheus + Grafana | Metrics, alerting |
| **Container** | Docker | Containerization |
| **Reverse Proxy** | Nginx | Load balancing, SSL |
| **Orchestration** | Docker Compose / Kubernetes | Deployment |

---

## Implementation Roadmap

### Iteration 1: Foundation (Week 1-2)
- [x] Environment-based configuration
- [x] PostgreSQL setup with migrations
- [x] Redis integration
- [ ] Service layer scaffolding
- [ ] Repository pattern

### Iteration 2: Core Services (Week 3-4)
- [ ] Booking Service with locking
- [ ] Search Service
- [ ] Identity Service refactor

### Iteration 3: API & Security (Week 5-6)
- [ ] JWT authentication
- [ ] RBAC implementation
- [ ] Rate limiting
- [ ] API versioning

### Iteration 4: Async & Caching (Week 7-8)
- [ ] Celery configuration
- [ ] Background tasks
- [ ] Redis caching

### Iteration 5: Scale & Observe (Week 9-10)
- [ ] Structured logging
- [ ] Health checks
- [ ] Metrics collection

### Iteration 6: Deploy (Week 11-12)
- [ ] Docker setup
- [ ] Nginx configuration
- [ ] Production deployment

---

## Success Metrics

- **Scalability**: Support 1M+ concurrent users
- **Performance**: P99 response time < 500ms
- **Reliability**: 99.9% uptime
- **Data Integrity**: Zero double-bookings via locking
- **Developer Experience**: Clear service boundaries, easy feature addition
- **Future-Proofness**: Modular enough for microservices extraction

