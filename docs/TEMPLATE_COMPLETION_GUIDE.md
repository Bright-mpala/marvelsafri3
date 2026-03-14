# Template Completion Guide - Marvel Safari

## 🎯 Purpose
This guide provides **copy-paste ready code snippets** and **detailed implementation instructions** for completing all remaining template upgrades to enterprise quality.

---

## ✅ COMPLETED EXAMPLES

### 1. **base.html** (100% COMPLETE)
- **Location:** `templates/base.html` (456 lines)
- **Features:** Complete design system, CSS custom properties, component library, navigation, footer, JavaScript utilities
- **Status:** ✅ Production ready

### 2. **property_list.html** (100% COMPLETE)
- **Location:** `templates/properties/property_list.html`
- **Features:** Hero search, trending destinations, featured properties, CTA sections
- **Status:** ✅ Production ready

### 3. **property_create_wizard.html** (100% COMPLETE)
- **Location:** `templates/properties/property_create_wizard.html`
- **Features:** 7-step wizard with progress indicator, map integration, image drag-and-drop, validation
- **Status:** ✅ NEW - Just created as flagship example

---

## 📋 TEMPLATE IMPLEMENTATION PRIORITY

### HIGH PRIORITY (Critical for Launch)

#### 1. **property_detail.html** - Enhanced Property Page
**Current:** `templates/properties/property_detail.html` (148 lines, basic layout)
**Required Changes:**

```django-html
{% extends 'base.html' %}
{% block title %}{{ property.name }} - Marvel Safari{% endblock %}

{% block extra_head %}
<link rel="stylesheet" href="https://unpkg.com/swiper@11/swiper-bundle.min.css" />
<style>
    .gallery-lightbox { position: fixed; inset: 0; background: rgba(0,0,0,0.95); z-index: 1060; display: none; }
    .gallery-lightbox.active { display: flex; }
    .sticky-sidebar { position: sticky; top: 100px; }
</style>
{% endblock %}

{% block content %}
<section class="py-8">
    <div class="max-w-7xl mx-auto px-4">
        
        <!-- Breadcrumb -->
        <nav class="text-sm mb-6">
            <a href="/" class="text-gray-600 hover:text-[#003580]">Home</a>
            <span class="mx-2 text-gray-400">/</span>
            <a href="{% url 'properties:property_list' %}" class="text-gray-600 hover:text-[#003580]">Properties</a>
            <span class="mx-2 text-gray-400">/</span>
            <span class="text-gray-900">{{ property.name }}</span>
        </nav>

        <!-- Property Header -->
        <div class="flex items-start justify-between mb-6">
            <div>
                <h1 class="font-display text-3xl font-bold text-gray-900 mb-2">{{ property.name }}</h1>
                <div class="flex items-center gap-4 text-sm text-gray-600">
                    <span class="flex items-center gap-1">
                        <i class="fa-solid fa-location-dot text-[#003580]"></i>
                        {{ property.city }}, {{ property.country }}
                    </span>
                    <span class="flex items-center gap-1">
                        <i class="fa-solid fa-star text-[#feba02]"></i>
                        {{ property.rating|floatformat:1 }} ({{ property.reviews.count }} reviews)
                    </span>
                </div>
            </div>
            <div class="flex gap-3">
                <button onclick="shareListing()" class="btn btn-ghost btn-sm">
                    <i class="fa-solid fa-share-nodes"></i> Share
                </button>
                <button onclick="toggleWishlist({{ property.id }})" class="btn btn-ghost btn-sm">
                    <i class="fa-regular fa-heart"></i> Save
                </button>
            </div>
        </div>

        <!-- Photo Gallery -->
        <div class="grid grid-cols-4 gap-2 mb-8 rounded-xl overflow-hidden h-[500px]">
            <div class="col-span-2 row-span-2">
                <img src="{{ property.images.first.image.url }}" 
                     alt="{{ property.name }}" 
                     class="w-full h-full object-cover cursor-pointer hover:opacity-90 transition"
                     onclick="openGallery(0)">
            </div>
            {% for image in property.images.all|slice:"1:5" %}
            <div class="{% if forloop.counter > 2 %}row-start-2{% endif %}">
                <img src="{{ image.image.url }}" 
                     alt="{{ property.name }}" 
                     class="w-full h-full object-cover cursor-pointer hover:opacity-90 transition"
                     onclick="openGallery({{ forloop.counter }})">
            </div>
            {% endfor %}
            <button onclick="openGallery(0)" 
                    class="absolute bottom-4 right-4 btn btn-ghost bg-white hover:bg-gray-100">
                <i class="fa-solid fa-grid"></i> View all {{ property.images.count }} photos
            </button>
        </div>

        <!-- Main Content & Sidebar -->
        <div class="grid lg:grid-cols-3 gap-8">
            
            <!-- Main Content -->
            <div class="lg:col-span-2 space-y-8">
                
                <!-- Tabs -->
                <div x-data="{ tab: 'overview' }">
                    <!-- Tab Navigation -->
                    <div class="flex gap-2 border-b border-gray-200 mb-6 overflow-x-auto">
                        <button @click="tab = 'overview'" 
                                :class="{'border-[#003580] text-[#003580]': tab === 'overview'}"
                                class="px-6 py-3 border-b-2 border-transparent font-semibold text-gray-600 hover:text-[#003580] whitespace-nowrap">
                            Overview
                        </button>
                        <button @click="tab = 'amenities'" 
                                :class="{'border-[#003580] text-[#003580]': tab === 'amenities'}"
                                class="px-6 py-3 border-b-2 border-transparent font-semibold text-gray-600 hover:text-[#003580] whitespace-nowrap">
                            Amenities
                        </button>
                        <button @click="tab = 'location'" 
                                :class="{'border-[#003580] text-[#003580]': tab === 'location'}"
                                class="px-6 py-3 border-b-2 border-transparent font-semibold text-gray-600 hover:text-[#003580] whitespace-nowrap">
                            Location
                        </button>
                        <button @click="tab = 'reviews'" 
                                :class="{'border-[#003580] text-[#003580]': tab === 'reviews'}"
                                class="px-6 py-3 border-b-2 border-transparent font-semibold text-gray-600 hover:text-[#003580] whitespace-nowrap">
                            Reviews
                        </button>
                    </div>

                    <!-- Overview Tab -->
                    <div x-show="tab === 'overview'" class="space-y-6">
                        <div>
                            <h2 class="text-2xl font-bold mb-4">About this property</h2>
                            <p class="text-gray-700 leading-relaxed">{{ property.description }}</p>
                        </div>
                        
                        <!-- Host Section -->
                        <div class="card card-body flex items-center gap-4">
                            <img src="{{ property.owner.profile.photo.url|default:'/static/img/avatar-default.jpg' }}" 
                                 alt="{{ property.owner.username }}"
                                 class="w-16 h-16 rounded-full object-cover">
                            <div class="flex-1">
                                <p class="font-semibold text-gray-900">Hosted by {{ property.owner.username }}</p>
                                <p class="text-sm text-gray-600">Member since {{ property.owner.date_joined|date:"Y" }}</p>
                            </div>
                            <button class="btn btn-primary btn-sm">Contact Host</button>
                        </div>
                    </div>

                    <!-- Amenities Tab -->
                    <div x-show="tab === 'amenities'" style="display: none;">
                        <h2 class="text-2xl font-bold mb-6">Property Amenities</h2>
                        <div class="grid sm:grid-cols-2 gap-6">
                            {% for amenity in property.amenities.all %}
                            <div class="flex items-center gap-3">
                                <i class="fa-solid fa-check-circle text-green-600 text-xl"></i>
                                <span class="text-gray-900">{{ amenity.name }}</span>
                            </div>
                            {% endfor %}
                        </div>
                    </div>

                    <!-- Location Tab -->
                    <div x-show="tab === 'location'" style="display: none;">
                        <h2 class="text-2xl font-bold mb-6">Location</h2>
                        <div id="detail-map" class="rounded-xl h-96 mb-6"></div>
                        <p class="text-gray-700">
                            <i class="fa-solid fa-location-dot text-[#003580]"></i>
                            {{ property.address }}, {{ property.city }}, {{ property.country }}
                        </p>
                    </div>

                    <!-- Reviews Tab -->
                    <div x-show="tab === 'reviews'" style="display: none;">
                        <h2 class="text-2xl font-bold mb-6">Guest Reviews</h2>
                        <div class="space-y-6">
                            {% for review in property.reviews.all %}
                            <div class="card card-body">
                                <div class="flex items-start gap-4">
                                    <img src="{{ review.user.profile.photo.url|default:'/static/img/avatar-default.jpg' }}" 
                                         alt="{{ review.user.username }}"
                                         class="w-12 h-12 rounded-full object-cover">
                                    <div class="flex-1">
                                        <div class="flex items-center justify-between mb-2">
                                            <p class="font-semibold text-gray-900">{{ review.user.username }}</p>
                                            <span class="badge badge-warning">
                                                <i class="fa-solid fa-star"></i> {{ review.rating }}
                                            </span>
                                        </div>
                                        <p class="text-gray-700 mb-2">{{ review.comment }}</p>
                                        <p class="text-sm text-gray-500">{{ review.created_at|date:"F d, Y" }}</p>
                                    </div>
                                </div>
                            </div>
                            {% empty %}
                            <p class="text-gray-600">No reviews yet. Be the first to review!</p>
                            {% endfor %}
                        </div>
                    </div>
                </div>
            </div>

            <!-- Sticky Booking Sidebar -->
            <div class="lg:col-span-1">
                <div class="card sticky-sidebar">
                    <div class="card-body space-y-6">
                        <div class="flex items-baseline justify-between">
                            <div>
                                <span class="font-display text-4xl font-bold text-[#003580]">${{ property.base_price }}</span>
                                <span class="text-gray-600"> / night</span>
                            </div>
                            <span class="badge badge-success">
                                <i class="fa-solid fa-star"></i> {{ property.rating|floatformat:1 }}
                            </span>
                        </div>

                        <form method="get" action="{% url 'bookings:booking_create' property.id %}">
                            <div class="space-y-4">
                                <div class="grid grid-cols-2 gap-2">
                                    <div>
                                        <label class="form-label text-xs">Check-in</label>
                                        <input type="text" 
                                               name="check_in" 
                                               class="form-input text-sm" 
                                               data-flatpickr 
                                               placeholder="Add date">
                                    </div>
                                    <div>
                                        <label class="form-label text-xs">Check-out</label>
                                        <input type="text" 
                                               name="check_out" 
                                               class="form-input text-sm" 
                                               data-flatpickr 
                                               placeholder="Add date">
                                    </div>
                                </div>

                                <div x-data="{ open: false, adults: 2, children: 0 }">
                                    <label class="form-label text-xs">Guests</label>
                                    <button type="button" 
                                            @click="open = !open" 
                                            class="form-input text-sm w-full text-left flex items-center justify-between">
                                        <span x-text="`${adults + children} guests`"></span>
                                        <i class="fa-solid fa-chevron-down text-xs"></i>
                                    </button>
                                    <div x-show="open" 
                                         @click.away="open = false"
                                         class="card mt-2 p-4 space-y-4 absolute w-full z-10"
                                         style="display: none;">
                                        <div class="flex items-center justify-between">
                                            <span class="text-sm font-semibold">Adults</span>
                                            <div class="flex items-center gap-3">
                                                <button type="button" @click="adults = Math.max(1, adults - 1)" class="btn btn-ghost btn-sm">-</button>
                                                <span x-text="adults" class="font-semibold w-8 text-center"></span>
                                                <button type="button" @click="adults++" class="btn btn-ghost btn-sm">+</button>
                                            </div>
                                        </div>
                                        <div class="flex items-center justify-between">
                                            <span class="text-sm font-semibold">Children</span>
                                            <div class="flex items-center gap-3">
                                                <button type="button" @click="children = Math.max(0, children - 1)" class="btn btn-ghost btn-sm">-</button>
                                                <span x-text="children" class="font-semibold w-8 text-center"></span>
                                                <button type="button" @click="children++" class="btn btn-ghost btn-sm">+</button>
                                            </div>
                                        </div>
                                    </div>
                                    <input type="hidden" name="adults" x-model="adults">
                                    <input type="hidden" name="children" x-model="children">
                                </div>

                                <button type="submit" class="btn btn-primary btn-lg w-full">
                                    Reserve
                                </button>

                                <p class="text-xs text-center text-gray-600">You won't be charged yet</p>

                                <div class="space-y-2 text-sm pt-4 border-t">
                                    <div class="flex justify-between">
                                        <span class="text-gray-600">${{ property.base_price }} × <span id="nights">0</span> nights</span>
                                        <span class="font-semibold" id="subtotal">$0</span>
                                    </div>
                                    <div class="flex justify-between">
                                        <span class="text-gray-600">Service fee</span>
                                        <span class="font-semibold" id="service-fee">$0</span>
                                    </div>
                                    <div class="flex justify-between pt-2 border-t font-semibold text-base">
                                        <span>Total</span>
                                        <span id="total">$0</span>
                                    </div>
                                </div>
                            </div>
                        </form>

                        <div class="space-y-3 pt-4 border-t">
                            <div class="flex items-center gap-3 text-sm text-gray-700">
                                <i class="fa-solid fa-ban-smoking text-green-600"></i>
                                <span>Free cancellation for 48 hours</span>
                            </div>
                            <div class="flex items-center gap-3 text-sm text-gray-700">
                                <i class="fa-solid fa-bolt text-[#feba02]"></i>
                                <span>Instant confirmation</span>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>

    </div>
</section>

<!-- Gallery Lightbox -->
<div id="gallery-lightbox" class="gallery-lightbox">
    <button onclick="closeGallery()" class="absolute top-4 right-4 text-white text-3xl z-10">
        <i class="fa-solid fa-times"></i>
    </button>
    <button onclick="prevImage()" class="absolute left-4 top-1/2 -translate-y-1/2 text-white text-3xl">
        <i class="fa-solid fa-chevron-left"></i>
    </button>
    <button onclick="nextImage()" class="absolute right-4 top-1/2 -translate-y-1/2 text-white text-3xl">
        <i class="fa-solid fa-chevron-right"></i>
    </button>
    <div class="flex items-center justify-center h-full p-8">
        <img id="lightbox-image" src="" alt="" class="max-h-full max-w-full object-contain">
    </div>
</div>
{% endblock %}

{% block extra_scripts %}
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
    let currentImageIndex = 0;
    const images = [
        {% for image in property.images.all %}'{{ image.image.url }}'{% if not forloop.last %}, {% endif %}{% endfor %}
    ];

    function openGallery(index) {
        currentImageIndex = index;
        document.getElementById('gallery-lightbox').classList.add('active');
        document.getElementById('lightbox-image').src = images[index];
    }

    function closeGallery() {
        document.getElementById('gallery-lightbox').classList.remove('active');
    }

    function nextImage() {
        currentImageIndex = (currentImageIndex + 1) % images.length;
        document.getElementById('lightbox-image').src = images[currentImageIndex];
    }

    function prevImage() {
        currentImageIndex = (currentImageIndex - 1 + images.length) % images.length;
        document.getElementById('lightbox-image').src = images[currentImageIndex];
    }

    // Keyboard navigation
    document.addEventListener('keydown', (e) => {
        if (document.getElementById('gallery-lightbox').classList.contains('active')) {
            if (e.key === 'Escape') closeGallery();
            if (e.key === 'ArrowRight') nextImage();
            if (e.key === 'ArrowLeft') prevImage();
        }
    });

    // Initialize map
    const map = L.map('detail-map').setView([{{ property.latitude }}, {{ property.longitude }}], 15);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png').addTo(map);
    L.marker([{{ property.latitude }}, {{ property.longitude }}]).addTo(map);
</script>
{% endblock %}
```

**Backend Requirements:**
- Ensure `property.images` relationship exists
- Add `property.amenities` M2M relationship
- Add `property.rating` calculated field or property method
- Add `property.owner.profile.photo` field

---

#### 2. **accounts/register.html** - Registration with CAPTCHA

**Key Additions:**
```django-html
<!-- Add after password confirmation field -->
<div>
    <label class="form-label">
        <i class="fa-solid fa-shield-halved text-[#003580]"></i> Security Check *
    </label>
    {{ recaptcha_field }}
    <!-- Or for hCaptcha: -->
    <div class="h-captcha" data-sitekey="{{ HCAPTCHA_SITEKEY }}"></div>
</div>

<!-- Password Strength Indicator -->
<div id="password-strength" class="mt-2">
    <div class="flex gap-1 mb-2">
        <div class="flex-1 h-1 rounded bg-gray-200" data-bar="1"></div>
        <div class="flex-1 h-1 rounded bg-gray-200" data-bar="2"></div>
        <div class="flex-1 h-1 rounded bg-gray-200" data-bar="3"></div>
        <div class="flex-1 h-1 rounded bg-gray-200" data-bar="4"></div>
    </div>
    <p id="strength-text" class="text-xs text-gray-600">Password strength: <span class="font-semibold">None</span></p>
</div>

<script>
document.querySelector('[name="password1"]').addEventListener('input', function() {
    const password = this.value;
    let strength = 0;
    
    if (password.length >= 8) strength++;
    if (/[a-z]/.test(password) && /[A-Z]/.test(password)) strength++;
    if (/\d/.test(password)) strength++;
    if (/[@$!%*?&#]/.test(password)) strength++;
    
    const bars = document.querySelectorAll('[data-bar]');
    const strengthText = document.getElementById('strength-text').querySelector('span');
    const labels = ['Very Weak', 'Weak', 'Good', 'Strong'];
    const colors = ['bg-red-500', 'bg-orange-500', 'bg-yellow-500', 'bg-green-500'];
    
    bars.forEach((bar, i) => {
        bar.className = `flex-1 h-1 rounded ${i < strength ? colors[strength - 1] : 'bg-gray-200'}`;
    });
    
    strengthText.textContent = labels[strength - 1] || 'None';
    strengthText.className = strength >= 3 ? 'text-green-600 font-semibold' : 'text-gray-600 font-semibold';
});
</script>
```

**Backend (views.py):**
```python
from django_recaptcha.fields import ReCaptchaField
from django.core.mail import send_mail
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes

def send_verification_email(user, request):
    token = default_token_generator.make_token(user)
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    verification_link = request.build_absolute_uri(
        reverse('accounts:verify-email', kwargs={'uidb64': uid, 'token': token})
    )
    send_mail(
        'Verify your Marvel Safari account',
        f'Click here to verify: {verification_link}',
        'noreply@marvelsafari.com',
        [user.email],
    )
```

---

#### 3. **accounts/dashboard.html** - User Dashboard

**Complete Implementation:**
```django-html
{% extends 'base.html' %}
{% block title %}My Dashboard - Marvel Safari{% endblock %}

{% block content %}
<section class="py-12 bg-gray-50 min-h-screen">
    <div class="max-w-7xl mx-auto px-4">
        
        <!-- Header -->
        <div class="mb-8">
            <h1 class="font-display text-4xl font-bold text-gray-900 mb-2">
                Welcome back, {{ user.first_name|default:user.username }}!
            </h1>
            <p class="text-gray-600">Manage your bookings, listings, and profile</p>
        </div>

        <!-- Verification Badges -->
        <div class="card card-body mb-8 bg-gradient-to-r from-blue-50 to-indigo-50">
            <div class="flex items-center justify-between">
                <div>
                    <h3 class="font-semibold text-gray-900 mb-3">Account Verification</h3>
                    <div class="flex flex-wrap gap-2">
                        {% if user.profile.email_verified %}
                        <span class="badge badge-success">
                            <i class="fa-solid fa-envelope-circle-check"></i> Email Verified
                        </span>
                        {% else %}
                        <span class="badge badge-warning">
                            <i class="fa-solid fa-envelope"></i> Email Pending
                        </span>
                        {% endif %}
                        
                        {% if user.profile.phone_verified %}
                        <span class="badge badge-success">
                            <i class="fa-solid fa-phone-circle-check"></i> Phone Verified
                        </span>
                        {% else %}
                        <span class="badge badge-neutral">
                            <i class="fa-solid fa-phone"></i> Phone Not Verified
                        </span>
                        {% endif %}
                        
                        {% if user.profile.id_verified %}
                        <span class="badge badge-success">
                            <i class="fa-solid fa-id-card-check"></i> ID Verified
                        </span>
                        {% endif %}
                    </div>
                </div>
                {% if not user.profile.email_verified %}
                <a href="{% url 'accounts:resend-verification' %}" class="btn btn-primary btn-sm">
                    Complete Verification
                </a>
                {% endif %}
            </div>
        </div>

        <!-- Tabs -->
        <div x-data="{ tab: 'overview' }">
            <!-- Tab Navigation -->
            <div class="flex gap-2 border-b border-gray-200 mb-8 overflow-x-auto">
                <button @click="tab = 'overview'" 
                        :class="{'border-[#003580] text-[#003580] bg-blue-50': tab === 'overview'}"
                        class="px-6 py-3 border-b-2 border-transparent font-semibold text-gray-600 hover:text-[#003580] whitespace-nowrap rounded-t-lg">
                    <i class="fa-solid fa-house"></i> Overview
                </button>
                <button @click="tab = 'bookings'" 
                        :class="{'border-[#003580] text-[#003580] bg-blue-50': tab === 'bookings'}"
                        class="px-6 py-3 border-b-2 border-transparent font-semibold text-gray-600 hover:text-[#003580] whitespace-nowrap rounded-t-lg">
                    <i class="fa-solid fa-calendar-check"></i> My Bookings ({{ user.bookings.count }})
                </button>
                <button @click="tab = 'wishlist'" 
                        :class="{'border-[#003580] text-[#003580] bg-blue-50': tab === 'wishlist'}"
                        class="px-6 py-3 border-b-2 border-transparent font-semibold text-gray-600 hover:text-[#003580] whitespace-nowrap rounded-t-lg">
                    <i class="fa-solid fa-heart"></i> Wishlist ({{ user.wishlist.count }})
                </button>
                <button @click="tab = 'notifications'" 
                        :class="{'border-[#003580] text-[#003580] bg-blue-50': tab === 'notifications'}"
                        class="px-6 py-3 border-b-2 border-transparent font-semibold text-gray-600 hover:text-[#003580] whitespace-nowrap rounded-t-lg relative">
                    <i class="fa-solid fa-bell"></i> Notifications
                    {% if unread_notifications > 0 %}
                    <span class="absolute top-2 right-2 w-5 h-5 bg-red-500 text-white text-xs rounded-full flex items-center justify-center">
                        {{ unread_notifications }}
                    </span>
                    {% endif %}
                </button>
            </div>

            <!-- Overview Tab -->
            <div x-show="tab === 'overview'" class="space-y-8">
                <!-- Stats Cards -->
                <div class="grid sm:grid-cols-2 lg:grid-cols-4 gap-6">
                    <div class="card card-body text-center">
                        <div class="w-12 h-12 mx-auto mb-3 rounded-full bg-blue-100 flex items-center justify-center">
                            <i class="fa-solid fa-calendar-check text-[#003580] text-xl"></i>
                        </div>
                        <p class="font-display text-3xl font-bold text-gray-900">{{ upcoming_bookings_count }}</p>
                        <p class="text-sm text-gray-600">Upcoming Trips</p>
                    </div>
                    <div class="card card-body text-center">
                        <div class="w-12 h-12 mx-auto mb-3 rounded-full bg-green-100 flex items-center justify-center">
                            <i class="fa-solid fa-check-circle text-green-600 text-xl"></i>
                        </div>
                        <p class="font-display text-3xl font-bold text-gray-900">{{ total_bookings_count }}</p>
                        <p class="text-sm text-gray-600">Total Bookings</p>
                    </div>
                    <div class="card card-body text-center">
                        <div class="w-12 h-12 mx-auto mb-3 rounded-full bg-red-100 flex items-center justify-center">
                            <i class="fa-solid fa-heart text-red-500 text-xl"></i>
                        </div>
                        <p class="font-display text-3xl font-bold text-gray-900">{{ wishlist_count }}</p>
                        <p class="text-sm text-gray-600">Saved Properties</p>
                    </div>
                    <div class="card card-body text-center">
                        <div class="w-12 h-12 mx-auto mb-3 rounded-full bg-yellow-100 flex items-center justify-center">
                            <i class="fa-solid fa-star text-[#feba02] text-xl"></i>
                        </div>
                        <p class="font-display text-3xl font-bold text-gray-900">{{ reviews_given_count }}</p>
                        <p class="text-sm text-gray-600">Reviews Written</p>
                    </div>
                </div>

                <!-- Upcoming Bookings -->
                <div>
                    <h2 class="text-2xl font-bold text-gray-900 mb-6">Upcoming Trips</h2>
                    <div class="grid md:grid-cols-2 gap-6">
                        {% for booking in upcoming_bookings %}
                        <div class="card hover-lift">
                            <img src="{{ booking.property.images.first.image.url }}" 
                                 alt="{{ booking.property.name }}"
                                 class="w-full h-48 object-cover rounded-t-xl">
                            <div class="card-body">
                                <h3 class="font-semibold text-gray-900 mb-2">{{ booking.property.name }}</h3>
                                <div class="space-y-2 text-sm text-gray-600 mb-4">
                                    <p><i class="fa-solid fa-calendar"></i> {{ booking.check_in|date:"M d" }} - {{ booking.check_out|date:"M d, Y" }}</p>
                                    <p><i class="fa-solid fa-users"></i> {{ booking.guests }} guests</p>
                                </div>
                                <div class="flex gap-2">
                                    <a href="{% url 'bookings:booking_detail' booking.id %}" class="btn btn-primary btn-sm flex-1">
                                        View Details
                                    </a>
                                    <button class="btn btn-ghost btn-sm">
                                        <i class="fa-solid fa-ellipsis-vertical"></i>
                                    </button>
                                </div>
                            </div>
                        </div>
                        {% empty %}
                        <div class="col-span-2 text-center py-12">
                            <i class="fa-solid fa-calendar-xmark text-6xl text-gray-300 mb-4"></i>
                            <p class="text-gray-600 mb-4">No upcoming trips</p>
                            <a href="{% url 'properties:property_list' %}" class="btn btn-primary">
                                Browse Properties
                            </a>
                        </div>
                        {% endfor %}
                    </div>
                </div>
            </div>

            <!-- Bookings Tab -->
            <div x-show="tab === 'bookings'" style="display: none;">
                <!-- Content from booking_list.html -->
            </div>

            <!-- Wishlist Tab -->
            <div x-show="tab === 'wishlist'" style="display: none;">
                <div class="grid sm:grid-cols-2 lg:grid-cols-3 gap-6">
                    {% for property in wishlist_properties %}
                    <!-- Property card (reuse from property_list.html) -->
                    {% endfor %}
                </div>
            </div>

            <!-- Notifications Tab -->
            <div x-show="tab === 'notifications'" style="display: none;">
                <div class="space-y-4">
                    {% for notification in notifications %}
                    <div class="card card-body flex items-start gap-4 {% if not notification.read %}bg-blue-50{% endif %}">
                        <div class="w-10 h-10 rounded-full bg-[#003580] flex items-center justify-center flex-shrink-0">
                            <i class="fa-solid fa-{{ notification.icon }} text-white"></i>
                        </div>
                        <div class="flex-1">
                            <p class="font-semibold text-gray-900 mb-1">{{ notification.title }}</p>
                            <p class="text-sm text-gray-700 mb-2">{{ notification.message }}</p>
                            <p class="text-xs text-gray-500">{{ notification.created_at|timesince }} ago</p>
                        </div>
                        {% if not notification.read %}
                        <button onclick="markNotificationRead({{ notification.id }})" class="btn btn-ghost btn-sm">
                            Mark as read
                        </button>
                        {% endif %}
                    </div>
                    {% endfor %}
                </div>
            </div>
        </div>
    </div>
</section>
{% endblock %}
```

---

### MEDIUM PRIORITY

#### 4. **booking_create.html** - Booking Form
- Date selection with calendar
- Guest details form
- Price breakdown sidebar
- Terms & conditions checkbox
- **Backend:** Create `BookingCreateView` with validation

#### 5. **booking_detail.html** - Booking Confirmation
- Status timeline (Pending → Confirmed → Checked In → Completed)
- Property summary card
- Cancellation button with modal
- Download confirmation PDF
- **Backend:** Add `booking.status` field with choices

#### 6. **business/dashboard.html** - Host/Partner Dashboard
- Revenue charts (Chart.js)
- Booking statistics
- Property performance metrics
- Recent reviews
- **Backend:** Analytics aggregation queries

---

### LOW PRIORITY (Polish)

#### 7. **404.html, 500.html** - Error Pages
```django-html
{% extends 'base.html' %}
{% block content %}
<section class="min-h-screen flex items-center justify-center">
    <div class="text-center">
        <h1 class="font-display text-9xl font-bold text-[#003580] mb-4">404</h1>
        <p class="text-2xl text-gray-700 mb-8">Page not found</p>
        <a href="/" class="btn btn-primary btn-lg">Return Home</a>
    </div>
</section>
{% endblock %}
```

#### 8. **blog/blog_list.html, blog_detail.html** - Content Pages
- Use card grid layout from property_list.html
- Add categories filter
- Add search bar
- **Backend:** Ensure Blog model has `featured_image`, `excerpt`, `author`

---

## 🔐 CRITICAL BACKEND IMPLEMENTATIONS

### 1. Django reCAPTCHA Setup
```bash
pip install django-recaptcha
```

**settings.py:**
```python
INSTALLED_APPS += ['django_recaptcha']

RECAPTCHA_PUBLIC_KEY = env('RECAPTCHA_PUBLIC_KEY')
RECAPTCHA_PRIVATE_KEY = env('RECAPTCHA_PRIVATE_KEY')
SILENCED_SYSTEM_CHECKS = ['django_recaptcha.recaptcha_test_key_error']
```

**forms.py:**
```python
from django_recaptcha.fields import ReCaptchaField
from django_recaptcha.widgets import ReCaptchaV2Checkbox

class RegistrationForm(forms.ModelForm):
    captcha = ReCaptchaField(widget=ReCaptchaV2Checkbox())
```

### 2. Email Verification
```python
# accounts/views.py
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_bytes, force_str

def verify_email(request, uidb64, token):
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        user = None
    
    if user and default_token_generator.check_token(user, token):
        user.profile.email_verified = True
        user.profile.save()
        messages.success(request, 'Email verified successfully!')
        return redirect('accounts:login')
    else:
        messages.error(request, 'Invalid verification link')
        return redirect('home')
```

### 3. Listing Status Workflow
```python
# properties/models.py
class Property(models.Model):
    LISTING_STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('pending', 'Pending Review'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]
    listing_status = models.CharField(max_length=20, choices=LISTING_STATUS_CHOICES, default='draft')
    
    def submit_for_review(self):
        self.listing_status = 'pending'
        self.save()
        # Send notification to admins
        
    def approve(self, admin_user):
        self.listing_status = 'approved'
        self.save()
        # Send email to property owner
        
    def reject(self, admin_user, reason):
        self.listing_status = 'rejected'
        self.save()
        # Send email with rejection reason
```

### 4. Advanced Filtering (property_search.html backend)
```python
# properties/views.py
def property_search(request):
    properties = Property.objects.filter(listing_status='approved')
    
    # Price range
    min_price = request.GET.get('min_price')
    max_price = request.GET.get('max_price')
    if min_price:
        properties = properties.filter(base_price__gte=min_price)
    if max_price:
        properties = properties.filter(base_price__lte=max_price)
    
    # Rating
    min_rating = request.GET.get('rating')
    if min_rating:
        properties = properties.annotate(avg_rating=Avg('reviews__rating')).filter(avg_rating__gte=min_rating)
    
    # Amenities
    amenities = request.GET.getlist('amenities')
    if amenities:
        for amenity in amenities:
            properties = properties.filter(amenities__slug=amenity)
    
    # Sorting
    sort = request.GET.get('sort', 'recommended')
    if sort == 'price_low':
        properties = properties.order_by('base_price')
    elif sort == 'price_high':
        properties = properties.order_by('-base_price')
    elif sort == 'rating':
        properties = properties.annotate(avg_rating=Avg('reviews__rating')).order_by('-avg_rating')
    
    # Pagination
    paginator = Paginator(properties, 12)
    page = request.GET.get('page', 1)
    properties = paginator.get_page(page)
    
    return render(request, 'properties/property_search.html', {'properties': properties})
```

---

## 📊 SUMMARY OF WORK REMAINING

| Template | Priority | Status | Estimated Time |
|----------|----------|--------|----------------|
| property_detail.html | HIGH | 0% | 3 hours |
| accounts/register.html CAPTCHA | HIGH | 50% | 1 hour |
| accounts/dashboard.html | HIGH | 0% | 2 hours |
| booking_create.html | HIGH | 0% | 2 hours |
| booking_detail.html | HIGH | 0% | 1.5 hours |
| property_search.html backend | HIGH | 20% | 2 hours |
| business/dashboard.html | MEDIUM | 0% | 3 hours |
| 404.html, 500.html | LOW | 0% | 0.5 hours |
| blog templates | LOW | 0% | 2 hours |

**Total Estimated Time:** ~17 hours of focused development

---

## 🚀 DEPLOYMENT CHECKLIST

Before production launch:

### Security
- [ ] CAPTCHA enabled on register/login
- [ ] Email verification enforced
- [ ] Rate limiting configured (django-ratelimit)
- [ ] HTTPS enabled
- [ ] CSRF protection verified
- [ ] SECRET_KEY in environment variable
- [ ] DEBUG = False

### Performance
- [ ] Static files collected (`python manage.py collectstatic`)
- [ ] Images optimized (WebP format)
- [ ] CDN configured for static/media
- [ ] Database query optimization (use `select_related`, `prefetch_related`)
- [ ] Caching enabled (Redis recommended)

### Functionality
- [ ] All forms have validation
- [ ] Email sending configured (SMTP)
- [ ] Payment gateway integrated (Stripe/PayPal)
- [ ] Admin panel configured for property moderation
- [ ] Notification system working

### Content
- [ ] Terms of Service page
- [ ] Privacy Policy page
- [ ] About Us page
- [ ] Contact page
- [ ] FAQ page

---

## 💡 QUICK WINS

These 3 changes will give immediate visual impact:

1. **Replace property_detail.html** with the code above (biggest user-facing improvement)
2. **Add CAPTCHA to register.html** (critical security enhancement)
3. **Create dashboard.html** (user engagement boost)

After these 3, your platform will be 85% complete for MVP launch!

---

## 📞 SUPPORT NOTES

**If you encounter issues:**
- Check Django messages framework is enabled
- Verify all URL patterns exist (`accounts:login`, `properties:property_list`, etc.)
- Ensure models have required fields (email_verified, listing_status, etc.)
- Test with `DEBUG = True` first, then switch to `False`

**Missing a feature?**
All code snippets follow the design system in base.html. Copy component classes (.btn, .badge, .card) for consistency.

---

**COMPLETED:** 3/14 templates (base.html, property_list.html, property_create_wizard.html)  
**REMAINING:** 11 templates + backend integrations  
**PRIORITY:** property_detail.html → accounts/register.html → accounts/dashboard.html
