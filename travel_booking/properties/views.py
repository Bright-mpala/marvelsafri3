import logging
from decimal import Decimal
from urllib.parse import urlencode

from django.conf import settings
from django.core.mail import send_mail
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views import View
from django.views.generic import ListView, DetailView
from django.db.models import Q, Count, Avg, Sum, F, OuterRef, Subquery, IntegerField, Value
from django.db.models.functions import Coalesce
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.core.paginator import Paginator
from django.utils import timezone
from django.views.decorators.http import require_POST
from datetime import datetime, timedelta
from django.utils.text import slugify

from accounts.models import UserRole

from .models import (
    Property,
    PropertyImage,
    PropertyType,
    Amenity,
    PropertyStatus,
    RoomType,
    PropertyActivity,
    RoomTypeImage,
    PropertyFavorite,
)
from .forms import PropertyCreateForm, PropertyImageUploadForm
from bookings.models import Booking
from reviews.models import Review

logger = logging.getLogger(__name__)


def _safe_send_mail(subject, message, recipients):
    if not recipients:
        return
    try:
        send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, recipients)
    except Exception:
        logger.exception("Failed to send property email")


def _process_room_types(request, property_obj):
    """
    Process room types from form data.
    
    Room types are submitted with keys like:
    room_types[1][name], room_types[1][price], etc.
    Images are submitted as room_types[1][images][] file uploads.
    """
    import re
    from decimal import Decimal, InvalidOperation
    
    room_types_data = {}
    pattern = re.compile(r'^room_types\[(\d+)\]\[(\w+)\](\[\])?$')
    
    # Process POST data (text fields)
    for key in request.POST:
        match = pattern.match(key)
        if match:
            index = match.group(1)
            field = match.group(2)
            is_array = match.group(3) is not None
            
            if index not in room_types_data:
                room_types_data[index] = {}
            
            if is_array:
                room_types_data[index][field] = request.POST.getlist(key)
            else:
                room_types_data[index][field] = request.POST.get(key)
    
    # Process FILES (room images)
    room_images = {}
    for key in request.FILES:
        match = pattern.match(key)
        if match:
            index = match.group(1)
            field = match.group(2)
            if field == 'images':
                room_images[index] = request.FILES.getlist(key)
    
    for idx, data in room_types_data.items():
        name = data.get('name', '').strip()
        if not name:
            continue  # Skip empty room types
        
        # Parse price safely
        price = None
        price_str = data.get('price', '')
        if price_str:
            try:
                price = Decimal(price_str)
                if price < 0:
                    price = None
            except (InvalidOperation, ValueError):
                price = None
        
        # Parse numeric fields
        def safe_int(val, default):
            try:
                return int(val) if val else default
            except (ValueError, TypeError):
                return default
        
        # Parse room size safely
        room_size = None
        size_str = data.get('size', '')
        if size_str:
            try:
                room_size = Decimal(size_str)
            except (InvalidOperation, ValueError):
                room_size = None
        
        room_type = RoomType.objects.create(
            property=property_obj,
            name=name,
            description=data.get('description', ''),
            base_price=price,
            quantity_available=safe_int(data.get('quantity'), 1),
            max_adults=safe_int(data.get('max_adults'), 2),
            max_children=safe_int(data.get('max_children'), 2),
            bed_type=data.get('bed_type', ''),
            room_size=room_size,
            bathroom_count=safe_int(data.get('bathrooms'), 1),
            display_order=int(idx),
        )
        
        # Process room images
        if idx in room_images:
            for img_index, image_file in enumerate(room_images[idx]):
                # Validate image
                if not image_file.content_type.startswith('image/'):
                    continue
                if image_file.size > 5 * 1024 * 1024:  # 5MB limit
                    continue
                
                RoomTypeImage.objects.create(
                    room_type=room_type,
                    image=image_file,
                    is_primary=(img_index == 0),
                    display_order=img_index,
                )


def _process_activities(request, property_obj):
    """
    Process activities from form data.
    
    Activities are submitted with keys like:
    activities[1][name], activities[1][price], etc.
    """
    import re
    from decimal import Decimal, InvalidOperation
    
    activities_data = {}
    pattern = re.compile(r'^activities\[(\d+)\]\[(\w+)\](\[\])?$')
    
    for key in request.POST:
        match = pattern.match(key)
        if match:
            index = match.group(1)
            field = match.group(2)
            is_array = match.group(3) is not None
            
            if index not in activities_data:
                activities_data[index] = {}
            
            if is_array:
                activities_data[index][field] = request.POST.getlist(key)
            else:
                activities_data[index][field] = request.POST.get(key)
    
    for idx, data in activities_data.items():
        name = data.get('name', '').strip()
        if not name:
            continue  # Skip empty activities
        
        # Parse price safely
        price = None
        price_str = data.get('price', '')
        if price_str:
            try:
                price = Decimal(price_str)
                if price < 0:
                    price = None
            except (InvalidOperation, ValueError):
                price = None
        
        # Parse numeric fields
        def safe_int(val, default):
            try:
                return int(val) if val else default
            except (ValueError, TypeError):
                return default
        
        PropertyActivity.objects.create(
            property=property_obj,
            name=name,
            description=data.get('description', ''),
            activity_type=data.get('type', 'tour'),
            price_per_person=price,
            duration=data.get('duration', ''),
            min_participants=safe_int(data.get('min_participants'), 1),
            max_participants=safe_int(data.get('max_participants'), None),
            availability=data.get('availability', 'daily'),
            difficulty=data.get('difficulty', 'moderate'),
            included=data.get('included', ''),
            display_order=int(idx),
        )


class PropertyListView(ListView):
    """Display list of all active properties with search and filtering."""
    model = Property
    template_name = 'properties/property_list.html'
    paginate_by = 12
    context_object_name = 'properties'
    
    def get_queryset(self):
        """Get active properties with annotations."""
        properties = Property.objects.filter(
            status__in=[PropertyStatus.ACTIVE, PropertyStatus.APPROVED],
            is_deleted=False
        ).select_related('property_type', 'owner').prefetch_related(
            'images', 'amenities', 'room_types'
        ).annotate(
            # avoid name collision with model fields; provide dynamic counts
            num_bookings=Count('unified_bookings', distinct=True),
            num_reviews=Count('reviews', distinct=True)
        )
        # If a property is not yet verified but approved, keep it visible on the frontend
        properties = properties.filter(Q(is_verified=True) | Q(status=PropertyStatus.APPROVED))
        
        # Search filter
        query = self.request.GET.get('q')
        if query:
            properties = properties.filter(
                Q(name__icontains=query) |
                Q(description__icontains=query) |
                Q(city__icontains=query) |
                Q(country__icontains=query) |
                Q(tags__name__icontains=query)
            ).distinct()
        
        # Location filter
        city = self.request.GET.get('city')
        if city:
            properties = properties.filter(city__icontains=city)
        
        country = self.request.GET.get('country')
        if country:
            properties = properties.filter(country=country)
        
        # Price range filter
        min_price = self.request.GET.get('min_price')
        max_price = self.request.GET.get('max_price')
        if min_price and max_price:
            properties = properties.filter(
                minimum_price__gte=float(min_price) if min_price else 0,
                maximum_price__lte=float(max_price) if max_price else 10000
            )
        
        # Property type filter
        property_type = self.request.GET.get('type')
        if property_type:
            properties = properties.filter(property_type__slug=property_type)
        
        # Amenity filter
        amenities = self.request.GET.getlist('amenities')
        if amenities:
            for amenity_id in amenities:
                properties = properties.filter(amenities__id=amenity_id).distinct()
        
        # Sorting
        sort_by = self.request.GET.get('sort', '-created_at')
        if sort_by in ['name', '-name', 'average_rating', '-average_rating', 'created_at', '-created_at']:
            properties = properties.order_by(sort_by)
        
        return properties
    
    def get_context_data(self, **kwargs):
        """Add additional context for filtering."""
        context = super().get_context_data(**kwargs)
        context['total_properties'] = Property.objects.filter(status__in=[PropertyStatus.ACTIVE, PropertyStatus.APPROVED], is_deleted=False).count()
        context['query'] = self.request.GET.get('q', '')
        
        # Statistics
        active_filter = {'status__in': [PropertyStatus.ACTIVE, PropertyStatus.APPROVED], 'is_deleted': False}
        context['total_cities'] = Property.objects.filter(**active_filter).values('city').distinct().count()
        context['total_countries'] = Property.objects.filter(**active_filter).values('country').distinct().count()
        
        # Recent bookings count
        recent_date = timezone.now().date() - timedelta(days=30)
        context['total_bookings'] = Booking.objects.filter(
            created_at__gte=recent_date
        ).count()
        
        # Dynamic homepage enhancements
        context['popular_destinations'] = Property.objects.filter(
            status__in=[PropertyStatus.ACTIVE, PropertyStatus.APPROVED],
            is_deleted=False
        ).values('city').annotate(total=Count('id')).order_by('-total')[:4]
        # use same queryset as used in get_queryset() for consistency
        queryset = self.get_queryset()
        context['featured_properties'] = queryset.filter(is_featured=True)[:6]

        # Blog highlights for the homepage hero row
        try:
            from blog.models import Post
            featured_posts = Post.objects.filter(is_featured=True, is_published=True).order_by('-published_at')[:3]
            latest_posts = Post.objects.filter(is_published=True).order_by('-published_at')[:3]
            context['featured_posts'] = featured_posts
            context['latest_posts'] = latest_posts
        except Exception:
            # Avoid breaking the homepage if blog app or data is unavailable
            context['featured_posts'] = []
            context['latest_posts'] = []

        # Some template sections expect a ``property`` object for hero cards.
        hero_property = context['featured_properties'].first()
        if not hero_property:
            hero_property = context.get('object_list').first() if context.get('object_list') else None
        context['highlight_property'] = hero_property
        context['property'] = hero_property

        # Date inputs on the homepage search form need today as a minimum
        context['today'] = timezone.now().date()

        return context

class PropertyDetailView(DetailView):
    """Display property details with reviews and booking information."""
    model = Property
    template_name = 'properties/property_detail.html'
    context_object_name = 'property'
    slug_field = 'slug'
    slug_url_kwarg = 'slug'
    
    def get_queryset(self):
        """Get active verified properties only."""
        from django.db.models import Prefetch
        
        return Property.objects.filter(
            status__in=[PropertyStatus.ACTIVE, PropertyStatus.APPROVED],
            is_deleted=False
        ).select_related('property_type', 'owner').prefetch_related(
            'images',
            'amenities',
            Prefetch(
                'room_types',
                queryset=RoomType.objects.prefetch_related(
                    'images', 'amenities', 'price_plans'
                ).order_by('display_order')
            ),
            'property_activities',
            'reviews'
        )
    
    def get_context_data(self, **kwargs):
        """Add reviews, room rate table, availability, wishlist and date context."""
        from decimal import Decimal
        from .models import PricePlan

        context = super().get_context_data(**kwargs)
        prop = self.object

        # Increment view count (fire-and-forget, non-critical)
        try:
            Property.objects.filter(pk=prop.pk).update(view_count=prop.view_count + 1)
        except Exception:
            pass

        # Full published reviews (not sliced — template uses .count)
        reviews = (
            Review.objects.filter(property=prop, is_published=True)
            .select_related('user')
            .order_by('-created_at')
        )
        context['reviews'] = reviews

        # Upcoming bookings (next 30 days)
        today = timezone.now().date()
        context['today'] = today
        context['upcoming_availability'] = Booking.objects.filter(
            property=prop,
            check_in_date__gte=today,
            check_in_date__lte=today + timedelta(days=30),
            status__in=['confirmed', 'pending'],
        ).order_by('check_in_date')

        # Per-user state
        if self.request.user.is_authenticated:
            completed_bookings = Booking.objects.filter(
                user=self.request.user,
                property=prop,
                status='completed',
            )
            context['user_has_booked'] = completed_bookings.exists()
            context['review_booking'] = (
                completed_bookings.exclude(review__isnull=False)
                .order_by('-check_out_date', '-created_at')
                .first()
            )
            context['is_favorited'] = PropertyFavorite.objects.filter(
                user=self.request.user,
                property=prop,
            ).exists()
        else:
            context['user_has_booked'] = False
            context['review_booking'] = None
            context['is_favorited'] = False

        # ── Property-level policy signals ────────────────────────────
        policy_text = (prop.cancellation_policy or '').lower()

        # Cancellation: parse free-cancel deadline from common phrase patterns
        # e.g. "free cancellation up to 48 hours before" → "Free cancellation up to 48 hours before check-in"
        # e.g. "free cancellation until 3 days before"   → date computed if dates known
        cancel_signal = None
        cancel_signal_class = 'gray'

        import re as _re
        # Match "N days/hours before" patterns
        _m = _re.search(r'(\d+)\s*(day|hour)s?\s*before', policy_text)
        if _m:
            n_val  = int(_m.group(1))
            n_unit = _m.group(2)
            if any(k in policy_text for k in ('free cancel', 'no charge', 'full refund')):
                if ci:
                    from datetime import timedelta as _td
                    if n_unit == 'day':
                        deadline = ci - _td(days=n_val)
                    else:
                        deadline = ci - _td(hours=n_val)
                    cancel_signal = f'Free cancellation until {deadline.strftime("%b %-d, %Y")}'
                else:
                    unit_label = f'{n_val} {n_unit}{"s" if n_val != 1 else ""}'
                    cancel_signal = f'Free cancellation up to {unit_label} before check-in'
                cancel_signal_class = 'green'
            elif 'non-refund' in policy_text or 'no refund' in policy_text:
                cancel_signal = 'Non-refundable'
                cancel_signal_class = 'red'
        elif any(k in policy_text for k in ('free cancel', 'no charge', 'full refund')):
            cancel_signal = 'Free cancellation available'
            cancel_signal_class = 'green'
        elif 'non-refund' in policy_text or 'no refund' in policy_text:
            cancel_signal = 'Non-refundable rate'
            cancel_signal_class = 'red'
        elif policy_text.strip():
            # Truncate to first sentence for a short display
            first_sentence = policy_text.split('.')[0].strip().capitalize()
            if first_sentence:
                cancel_signal = first_sentence[:80]
                cancel_signal_class = 'gray'

        context['cancel_signal']       = cancel_signal
        context['cancel_signal_class'] = cancel_signal_class

        # Tax transparency: check all active PricePlans for this property
        try:
            from .models import PricePlan as _PP
            plans_qs = _PP.objects.filter(
                room_type__property=prop, is_active=True
            ).values_list('taxes_included', 'breakfast_included')
            taxes_included_any  = any(t for t, _ in plans_qs)
            taxes_excluded_any  = any(not t for t, _ in plans_qs)
            breakfast_any       = any(b for _, b in plans_qs)

            if taxes_included_any and not taxes_excluded_any:
                tax_signal = 'All rates include taxes & fees'
                tax_signal_class = 'green'
            elif taxes_excluded_any and not taxes_included_any:
                tax_signal = 'Taxes & fees added at checkout'
                tax_signal_class = 'amber'
            elif taxes_included_any and taxes_excluded_any:
                tax_signal = 'Some rates include taxes — see per-room breakdown'
                tax_signal_class = 'amber'
            else:
                # No PricePlans: estimate
                tax_signal = 'Taxes & fees may apply at checkout'
                tax_signal_class = 'amber'

            meal_signal = 'Breakfast available on select rates' if breakfast_any else None
        except Exception:
            tax_signal       = 'Taxes & fees may apply at checkout'
            tax_signal_class = 'amber'
            meal_signal      = None

        context['tax_signal']       = tax_signal
        context['tax_signal_class'] = tax_signal_class
        context['meal_signal']      = meal_signal

        # Payment timing: derive from accepted_payment_methods
        accepted = getattr(prop, 'accepted_payment_methods', '') or ''
        methods  = [m.strip() for m in accepted.split(',') if m.strip()]
        # If bank_transfer is the ONLY option, show "Pay before arrival"
        # If card/paynow/ecocash present → immediate charge at booking
        instant_pay_methods = {'card', 'paynow', 'ecocash'}
        has_instant = any(m in instant_pay_methods for m in methods)
        has_bank    = 'bank_transfer' in methods

        if has_instant and has_bank:
            pay_signal = 'Pay now (card/mobile) or by bank transfer'
            pay_signal_class = 'blue'
        elif has_instant:
            pay_signal = 'Pay now — card & mobile money accepted'
            pay_signal_class = 'blue'
        elif has_bank:
            pay_signal = 'Pay by bank transfer before arrival'
            pay_signal_class = 'amber'
        elif methods:
            pay_signal = f'Payment via {", ".join(methods)}'
            pay_signal_class = 'blue'
        else:
            pay_signal = 'Secure payment at checkout'
            pay_signal_class = 'blue'

        context['pay_signal']       = pay_signal
        context['pay_signal_class'] = pay_signal_class

        # ── Room / Rate table ────────────────────────────────────────
        check_in_str  = self.request.GET.get('check_in', '')
        check_out_str = self.request.GET.get('check_out', '')
        guests_str    = self.request.GET.get('guests', '2')

        try:
            from datetime import date as _date, datetime as _dt
            ci = _dt.strptime(check_in_str, '%Y-%m-%d').date() if check_in_str else None
            co = _dt.strptime(check_out_str, '%Y-%m-%d').date() if check_out_str else None
            nights = (co - ci).days if (ci and co and co > ci) else None
        except ValueError:
            ci = co = nights = None

        try:
            guests = max(1, int(guests_str))
        except (ValueError, TypeError):
            guests = 2

        commission_rate = prop.get_commission_rate_for_guest()  # e.g. Decimal('10.00')
        # Standard platform tax estimate when not included in rate (12 %)
        TAX_RATE = Decimal('0.12')

        room_rows = []
        for room in prop.room_types.prefetch_related('price_plans', 'amenities', 'images').order_by('display_order'):
            # ── Pick the best active PricePlan for the date window ──
            plan = None
            if ci and co:
                plan_qs = (
                    PricePlan.objects
                    .filter(
                        room_type=room,
                        is_active=True,
                        start_date__lte=ci,
                        end_date__gte=co,
                    )
                    .order_by('base_price')   # cheapest qualifying plan first
                )
                plan = plan_qs.first()

            # ── Nightly rate ──
            nightly = Decimal('0')
            if plan:
                nightly = plan.base_price
            elif room.base_price:
                nightly = room.base_price

            # ── Per-night extras ──
            extra_pp = Decimal('0')
            if plan and plan.extra_person_charge:
                extra_capacity = max(0, guests - room.max_adults)
                extra_pp = plan.extra_person_charge * extra_capacity

            effective_nightly = nightly + extra_pp

            # ── Totals (only when nights are known) ──
            subtotal       = (effective_nightly * nights) if nights else None
            taxes_included = plan.taxes_included if plan else False
            tax_amount     = Decimal('0') if taxes_included or not subtotal else (subtotal * TAX_RATE).quantize(Decimal('0.01'))
            platform_fee   = ((subtotal * commission_rate / 100).quantize(Decimal('0.01'))) if subtotal else None
            total_payable  = ((subtotal + tax_amount)) if subtotal else None

            # ── Cancellation rule ──
            cancel_days = plan.cancellation_days if plan else None
            if cancel_days is not None:
                if cancel_days == 0:
                    cancel_label = 'Non-refundable'
                    cancel_class = 'red'
                elif cancel_days >= 7:
                    cancel_label = f'Free cancel >{cancel_days}d before'
                    cancel_class = 'green'
                else:
                    cancel_label = f'Free cancel >{cancel_days}d before'
                    cancel_class = 'amber'
            else:
                # fall back to property cancellation policy text
                policy = (prop.cancellation_policy or '').lower()
                if any(k in policy for k in ('free cancel', 'full refund', 'no charge')):
                    cancel_label = 'Free cancellation'
                    cancel_class = 'green'
                elif 'non-refund' in policy or 'no refund' in policy:
                    cancel_label = 'Non-refundable'
                    cancel_class = 'red'
                else:
                    cancel_label = 'See policy'
                    cancel_class = 'gray'

            # ── Meal plan label ──
            breakfast = plan.breakfast_included if plan else False
            if breakfast:
                meal_label = 'Breakfast included'
                meal_icon  = '☕'
            else:
                meal_label = 'Room only'
                meal_icon  = '🛏️'

            # ── Inventory urgency ──
            overlapping_bookings = 0
            if ci and co:
                overlapping_bookings = Booking.objects.filter(
                    property=prop,
                    room_type=room,
                    status__in=['confirmed', 'pending'],
                    check_in_date__lt=co,
                    check_out_date__gt=ci,
                ).count()
            qty = max(0, room.quantity_available - overlapping_bookings)
            if qty == 0:
                inv_label = 'Sold out'
                inv_class = 'sold'
            elif qty == 1:
                inv_label = 'Only 1 left!'
                inv_class = 'critical'
            elif qty <= 3:
                inv_label = f'Only {qty} left'
                inv_class = 'low'
            else:
                inv_label = f'{qty} available'
                inv_class = 'ok'

            # ── Occupancy string ──
            occ_parts = [f'{room.max_adults} adult{"s" if room.max_adults != 1 else ""}']
            if room.max_children:
                occ_parts.append(f'{room.max_children} child{"ren" if room.max_children != 1 else ""}')
            occ_str = ' + '.join(occ_parts)

            room_rows.append({
                'room':            room,
                'plan':            plan,
                'nightly':         effective_nightly,
                'subtotal':        subtotal,
                'tax_amount':      tax_amount,
                'taxes_included':  taxes_included,
                'platform_fee':    platform_fee,
                'total_payable':   total_payable,
                'cancel_label':    cancel_label,
                'cancel_class':    cancel_class,
                'meal_label':      meal_label,
                'meal_icon':       meal_icon,
                'inv_label':       inv_label,
                'inv_class':       inv_class,
                'occ_str':         occ_str,
                'nights':          nights,
                'guests':          guests,
            })

        context['room_rows']  = room_rows
        context['room_rate_rows'] = []
        for row in room_rows:
            remaining_inventory = max(0, row['room'].quantity_available - (
                Booking.objects.filter(
                    property=prop,
                    room_type=row['room'],
                    status__in=['confirmed', 'pending'],
                    check_in_date__lt=co,
                    check_out_date__gt=ci,
                ).count() if ci and co else 0
            ))
            base_room_rate = (
                row['plan'].base_price
                if row['plan']
                else (row['room'].base_price or Decimal('0'))
            )
            extra_charge_total = (row['nightly'] - base_room_rate) * (nights or 1)
            context['room_rate_rows'].append({
                'room': row['room'],
                'occupancy_label': row['occ_str'],
                'meal_plan_label': row['meal_label'],
                'cancellation_label': (
                    f"Free cancellation up to {row['plan'].cancellation_days} day{'s' if row['plan'].cancellation_days != 1 else ''} before check-in"
                    if row['plan'] and row['plan'].cancellation_days
                    else row['cancel_label']
                ),
                'taxes_label': (
                    'Included'
                    if row['taxes_included']
                    else (f"${row['tax_amount']:.2f} est." if row['tax_amount'] else 'Estimated at checkout')
                ),
                'remaining_inventory': remaining_inventory,
                'nightly_label': f"${row['nightly']:.2f}" if row['nightly'] else 'On request',
                'final_total_label': (
                    f"${row['total_payable']:.2f}"
                    if row['total_payable'] is not None
                    else (f"${row['nightly'] + row['tax_amount']:.2f} / night" if row['nightly'] else 'Select dates')
                ),
                'extra_guest_label': (
                    f"+ ${extra_charge_total:.2f} extra guest charges"
                    if extra_charge_total > 0 else ''
                ),
                'has_valid_stay': bool(nights),
                'nights': nights,
                'book_query': urlencode({
                    'room_type': str(row['room'].id),
                    'guests': str(guests),
                    **({'check_in': ci.isoformat(), 'check_out': co.isoformat()} if ci and co else {}),
                }),
            })
        context['ci']         = ci
        context['co']         = co
        context['nights']     = nights
        context['guests']     = guests
        context['has_dates']  = bool(nights)
        context['selected_check_in'] = ci
        context['selected_check_out'] = co
        context['selected_nights'] = nights
        context['selected_guests'] = guests

        return context


@login_required
@require_POST
def toggle_favorite(request, slug):
    """Toggle a property in the authenticated user's favorites."""
    property_obj = get_object_or_404(
        Property.objects.filter(
            status__in=PropertyStatus.public_statuses(),
            is_deleted=False,
        ),
        slug=slug,
    )

    favorite_qs = PropertyFavorite.objects.filter(
        user=request.user,
        property=property_obj,
    )

    if favorite_qs.exists():
        favorite_qs.delete()
        messages.success(request, _('Property removed from favorites.'))
    else:
        PropertyFavorite.objects.create(user=request.user, property=property_obj)
        messages.success(request, _('Property saved to favorites.'))

    next_url = request.POST.get('next')
    if next_url:
        return redirect(next_url)
    return redirect('properties:detail', slug=slug)

class PropertySearchView(View):
    """Search properties by multiple criteria."""
    template_name = 'properties/property_search.html'
    
    def get(self, request):
        """Handle property search."""
        params = request.GET
        query = params.get('q', '').strip()
        city = params.get('city', '').strip()
        sort_by = params.get('sort', '-created_at')
        min_price = params.get('min_price')
        max_price = params.get('max_price')
        property_type = params.get('type')
        stars = params.get('stars')
        rating = params.get('rating')
        verified_only_param = params.get('verified_only')
        verified_only = str(verified_only_param).lower() in {'1', 'true', 'on', 'yes'}
        amenity_params = params.getlist('amenities')

        # New filter params added by the upgraded search template
        check_in  = params.get('check_in', '').strip()
        check_out = params.get('check_out', '').strip()
        free_cancellation_param = params.get('free_cancellation')
        free_cancellation = str(free_cancellation_param).lower() in {'1', 'true', 'on', 'yes'}
        instant_booking_param = params.get('instant_booking')
        instant_booking = str(instant_booking_param).lower() in {'1', 'true', 'on', 'yes'}

        public_statuses = list(PropertyStatus.public_statuses())
        properties = (
            Property.objects.filter(status__in=public_statuses, is_deleted=False)
            .filter(Q(is_verified=True) | Q(status=PropertyStatus.APPROVED))
            .select_related('property_type')
            .prefetch_related('images', 'amenities')
        )

        if verified_only:
            properties = properties.filter(is_verified=True)

        if query:
            properties = properties.filter(
                Q(name__icontains=query) |
                Q(description__icontains=query) |
                Q(city__icontains=query) |
                Q(country__icontains=query)
            )

        if city:
            properties = properties.filter(city__icontains=city)

        if min_price or max_price:
            try:
                min_val = float(min_price) if min_price else 0
                max_val = float(max_price) if max_price else 100000
                properties = properties.filter(
                    minimum_price__gte=min_val,
                    maximum_price__lte=max_val
                )
            except (TypeError, ValueError):
                pass

        if property_type:
            properties = properties.filter(property_type__slug=property_type)

        amenity_ids = []
        for amenity_id in amenity_params:
            try:
                amenity_pk = int(amenity_id)
            except (TypeError, ValueError):
                continue
            amenity_ids.append(amenity_pk)
            properties = properties.filter(amenities__id=amenity_pk)

        if stars:
            try:
                star_value = int(stars)
                properties = properties.filter(star_rating__gte=star_value)
            except (TypeError, ValueError):
                pass

        if rating:
            try:
                rating_value = float(rating)
                properties = properties.filter(average_rating__gte=rating_value)
            except (TypeError, ValueError):
                pass

        # Free cancellation — derived from cancellation_policy text
        if free_cancellation:
            properties = properties.filter(
                Q(cancellation_policy__icontains='free cancel') |
                Q(cancellation_policy__icontains='no charge') |
                Q(cancellation_policy__icontains='full refund') |
                Q(cancellation_policy__icontains='free of charge')
            )

        # Instant booking — verified + approved properties only
        if instant_booking:
            properties = properties.filter(
                is_verified=True,
                status__in=[PropertyStatus.APPROVED, PropertyStatus.ACTIVE],
            )

        # Date availability filter — capacity-aware
        # A property is only excluded when ALL its rooms are occupied for the
        # requested window, not merely when one booking exists.
        #
        # Capacity is resolved in two tiers:
        #   1. Properties WITH room types  → sum(room_type.quantity_available)
        #   2. Properties WITHOUT room types → property.total_rooms  (fallback)
        if check_in and check_out:
            try:
                from datetime import datetime as dt

                ci = dt.strptime(check_in, '%Y-%m-%d').date()
                co = dt.strptime(check_out, '%Y-%m-%d').date()

                if co > ci:
                    # Count overlapping active bookings per property
                    overlap_qs = (
                        Booking.objects
                        .filter(
                            property=OuterRef('pk'),
                            status__in=['confirmed', 'pending'],
                            check_in_date__lt=co,
                            check_out_date__gt=ci,
                        )
                        .values('property')          # group by property
                        .annotate(cnt=Count('id'))
                        .values('cnt')
                    )

                    # Sum of room-type inventory per property (None when no room types)
                    rt_capacity_qs = (
                        RoomType.objects
                        .filter(property=OuterRef('pk'))
                        .values('property')
                        .annotate(total=Sum('quantity_available'))
                        .values('total')
                    )

                    properties = (
                        properties
                        .annotate(
                            _overlap=Coalesce(
                                Subquery(overlap_qs, output_field=IntegerField()), Value(0)
                            ),
                            # Tier-1 capacity: sum of room-type inventory
                            _rt_capacity=Subquery(
                                rt_capacity_qs, output_field=IntegerField()
                            ),
                            # Effective capacity: use room-type sum when available,
                            # else fall back to property.total_rooms (min 1)
                            _capacity=Coalesce('_rt_capacity', 'total_rooms', Value(1)),
                        )
                        # Only exclude when bookings fill or exceed capacity
                        .exclude(_overlap__gte=models.F('_capacity'))
                    )
            except (ValueError, TypeError):
                pass

        if sort_by in ['minimum_price', '-minimum_price', 'average_rating', '-average_rating', 'name', '-name', 'created_at', '-created_at']:
            properties = properties.order_by(sort_by)

        properties = properties.distinct()

        paginator = Paginator(properties, 12)
        page_number = params.get('page')
        page_obj = paginator.get_page(page_number)

        base_params = params.copy()
        base_params.pop('page', None)
        query_string = base_params.urlencode()

        def build_remove_link(keys, value=None):
            """Return a querystring with specific filters removed."""
            updated = params.copy()
            updated.pop('page', None)

            if isinstance(keys, (list, tuple, set, frozenset)):
                for key in keys:
                    updated.pop(key, None)
            else:
                if value is None:
                    updated.pop(keys, None)
                else:
                    values = updated.getlist(keys)
                    filtered = [val for val in values if val != value]
                    if filtered:
                        updated.setlist(keys, filtered)
                    else:
                        updated.pop(keys, None)

            return updated.urlencode()

        active_filters = []

        def add_filter(label, value, keys, remove_value=None):
            active_filters.append({
                'label': label,
                'value': value,
                'remove_query': build_remove_link(keys, remove_value)
            })

        if query:
            add_filter('Destination', query, 'q')
        if city:
            add_filter('City', city, 'city')
        if property_type:
            type_label = PropertyType.objects.filter(slug=property_type).values_list('name', flat=True).first()
            add_filter('Type', type_label or property_type, 'type')
        if min_price:
            add_filter('Min price', f"${min_price}", 'min_price')
        if max_price:
            add_filter('Max price', f"${max_price}", 'max_price')
        if stars:
            add_filter('Star rating', f"{stars}+", 'stars')
        if rating:
            add_filter('Guest rating', f"{rating}+", 'rating')
        if sort_by and sort_by != '-created_at':
            sort_labels = {
                'minimum_price': 'Lowest price',
                '-minimum_price': 'Highest price',
                'average_rating': 'Guest rating (asc)',
                '-average_rating': 'Top rated',
                'name': 'Name (A-Z)',
                '-name': 'Name (Z-A)',
                'created_at': 'Oldest first',
            }
            add_filter('Sort', sort_labels.get(sort_by, sort_by), 'sort')
        if verified_only:
            add_filter('Verified only', 'Enabled', 'verified_only')

        if free_cancellation:
            add_filter('Cancellation', 'Free cancellation', 'free_cancellation')

        if instant_booking:
            add_filter('Booking', 'Instant booking', 'instant_booking')

        if check_in:
            add_filter('Check-in', check_in, 'check_in')

        if check_out:
            add_filter('Check-out', check_out, 'check_out')

        if amenity_ids:
            amenity_names = dict(
                Amenity.objects.filter(id__in=amenity_ids).values_list('id', 'name')
            )
            for amenity_id in amenity_ids:
                name = amenity_names.get(amenity_id, str(amenity_id))
                add_filter('Amenity', name, 'amenities', str(amenity_id))

        context = {
            'page_obj': page_obj,
            'properties': page_obj.object_list,
            'query': query,
            'city': city,
            'sort_by': sort_by,
            'total_results': paginator.count,
            'query_string': query_string,
            'active_filters': active_filters,
            'property_types': PropertyType.objects.filter(is_active=True).order_by('name'),
            'amenities': Amenity.objects.filter(is_active=True).order_by('name'),
            'selected_type': property_type,
            'selected_amenities': [str(a) for a in amenity_ids],
            'min_price': min_price,
            'max_price': max_price,
            # New filter state — lets templates re-check boxes on page reload
            'selected_stars': stars,
            'selected_rating': rating,
            'free_cancellation_active': free_cancellation,
            'instant_booking_active': instant_booking,
            'check_in': check_in,
            'check_out': check_out,
            'today': timezone.now().date(),
        }
        return render(request, self.template_name, context)

def property_availability(request, property_id):
    """Check property availability for given dates (AJAX endpoint)."""
    from django.http import JsonResponse
    from datetime import datetime
    
    property_obj = get_object_or_404(Property, id=property_id)
    
    check_in = request.GET.get('check_in')
    check_out = request.GET.get('check_out')
    
    if not check_in or not check_out:
        return JsonResponse({'error': _('Missing dates')}, status=400)
    
    try:
        check_in_date = datetime.strptime(check_in, '%Y-%m-%d').date()
        check_out_date = datetime.strptime(check_out, '%Y-%m-%d').date()
    except ValueError:
        return JsonResponse({'error': _('Invalid date format')}, status=400)
    
    # Capacity-aware availability check.
    # Tier-1: use sum of RoomType.quantity_available when room types exist.
    # Tier-2: fall back to property.total_rooms otherwise.
    from properties.models import RoomType as RT
    rt_capacity = (
        RT.objects
        .filter(property=property_obj)
        .aggregate(total=Sum('quantity_available'))['total']
    )
    capacity = max(1, int(rt_capacity or property_obj.total_rooms or 1))

    overlapping_count = Booking.objects.filter(
        property=property_obj,
        status__in=['confirmed', 'pending'],
        check_in_date__lt=check_out_date,
        check_out_date__gt=check_in_date,
    ).count()

    if overlapping_count >= capacity:
        return JsonResponse({
            'available': False,
            'message': _('Property is fully booked for the selected dates'),
            'overlapping': overlapping_count,
            'capacity': capacity,
        })

    return JsonResponse({
        'available': True,
        'message': _('Property is available'),
        'remaining': capacity - overlapping_count,
        'capacity': capacity,
    })


def user_can_list_properties(user):
    """Allow listing for authenticated users (admin approval required)."""
    return user.is_authenticated


@login_required
def property_create(request):
    """Create property listing - requires admin approval after submission."""
    if not request.user.is_authenticated:
        messages.error(request, 'You must be logged in to list a property.')
        return redirect('accounts:login')

    # Only hosts/admins can list properties
    if not (
        request.user.is_staff
        or request.user.is_superuser
        or request.user.role in {UserRole.HOST, UserRole.ADMIN}
    ):
        messages.error(request, 'Only hosts or admins can list a property. Enable a host account to continue.')
        return redirect('accounts:enable_business')

    if request.method == 'POST':
        form = PropertyCreateForm(request.POST)
        image_form = PropertyImageUploadForm(request.POST, request.FILES)
        
        # Get uploaded images
        images = request.FILES.getlist('images')
        
        # Validate images
        allowed_extensions = {'jpg', 'jpeg', 'png', 'gif', 'webp'}
        image_errors = []
        for image in images:
            ext = image.name.split('.')[-1].lower()
            if ext not in allowed_extensions:
                image_errors.append(f'Invalid file type: {image.name}. Allowed: jpg, jpeg, png, gif, webp')
            if image.size > 5 * 1024 * 1024:
                image_errors.append(f'File too large: {image.name}. Maximum 5MB per image.')
        
        # Validate both forms and images
        if form.is_valid() and image_form.is_valid() and not image_errors:
            prop = form.save(commit=False)
            prop.owner = request.user
            prop.status = 'pending'
            prop.is_verified = False
            
            # Generate unique slug
            base_slug = slugify(prop.name)
            unique_slug = base_slug
            counter = 1
            
            # Ensure slug uniqueness by appending counter if needed
            while Property.objects.filter(slug=unique_slug).exists():
                unique_slug = f"{base_slug}-{counter}"
                counter += 1
            
            prop.slug = unique_slug
            prop.save()
            
            # Save many-to-many relationships (amenities)
            form.save_m2m()

            # Process images from request.FILES
            images = request.FILES.getlist('images')
            if images:
                for index, image in enumerate(images):
                    PropertyImage.objects.create(
                        property=prop,
                        image=image,
                        is_primary=(index == 0),
                        display_order=index,
                    )

            # Process room types (optional)
            _process_room_types(request, prop)
            
            # Process activities (optional)
            _process_activities(request, prop)

            messages.success(request, 'Property submitted for review. It will appear after verification.')

            primary_admin = 'marvelsafari@gmail.com'
            configured_admin = getattr(settings, 'CONTACT_NOTIFY_EMAIL', None) or getattr(settings, 'DEFAULT_FROM_EMAIL', None)
            admin_recipients = {email for email in [primary_admin, configured_admin] if email}
            admin_subject = f"New property listing request: {prop.name}"
            admin_message = (
                "A new property listing request has been submitted.\n\n"
                f"Property: {prop.name}\n"
                f"Host: {request.user.get_full_name() or request.user.email}\n"
                f"Email: {request.user.email}\n"
                f"Location: {prop.city}, {prop.country.name}\n"
            )
            _safe_send_mail(admin_subject, admin_message, list(admin_recipients))

            owner_recipients = [request.user.email] if request.user.email else []
            owner_subject = f"Property request received: {prop.name}"
            owner_message = (
                "We received your property listing request and will review it shortly.\n\n"
                f"Property: {prop.name}\n"
                f"Location: {prop.city}, {prop.country.name}\n"
            )
            _safe_send_mail(owner_subject, owner_message, owner_recipients)

            return redirect('properties:create_success', slug=prop.slug)
        else:
            # Show form errors and image errors
            if image_errors:
                for error in image_errors:
                    messages.error(request, error)
    else:
        form = PropertyCreateForm(initial={'email': request.user.email, 'city': request.user.city})
        image_form = PropertyImageUploadForm()
        image_errors = []

    return render(request, 'properties/property_create.html', {
        'form': form, 
        'image_form': image_form,
        'image_errors': image_errors if request.method == 'POST' else []
    })


@login_required
def property_edit(request, slug):
    """Allow hosts to edit their property and add new images."""
    if not (
        request.user.is_staff
        or request.user.is_superuser
        or request.user.role in {UserRole.HOST, UserRole.ADMIN}
    ):
        messages.error(request, 'Only hosts or admins can edit property listings.')
        return redirect('accounts:enable_business')

    if request.user.is_staff or request.user.is_superuser:
        prop = get_object_or_404(Property, slug=slug)
    else:
        prop = get_object_or_404(Property, slug=slug, owner=request.user)

    if request.method == 'POST':
        form = PropertyCreateForm(request.POST, instance=prop)
        image_form = PropertyImageUploadForm(request.POST, request.FILES)
        if form.is_valid() and image_form.is_valid():
            form.save()

            images = request.FILES.getlist('images')
            if images:
                start_order = prop.images.count()
                for index, image in enumerate(images):
                    PropertyImage.objects.create(
                        property=prop,
                        image=image,
                        display_order=start_order + index,
                        is_primary=(start_order == 0 and index == 0),
                    )

            # Handle image deletions
            delete_ids = request.POST.getlist('delete_images')
            if delete_ids:
                prop.images.filter(id__in=delete_ids).delete()

            # Handle primary image selection
            primary_id = request.POST.get('primary_image')
            if primary_id:
                prop.images.update(is_primary=False)
                prop.images.filter(id=primary_id).update(is_primary=True)

            # Handle display order updates
            for image in prop.images.all():
                order_val = request.POST.get(f'order_{image.id}')
                if order_val is not None and str(order_val).strip() != '':
                    try:
                        image.display_order = int(order_val)
                        image.save(update_fields=['display_order'])
                    except ValueError:
                        pass

            # Ensure at least one primary image if any remain
            if prop.images.exists() and not prop.images.filter(is_primary=True).exists():
                first_image = prop.images.order_by('display_order', 'created_at').first()
                if first_image:
                    first_image.is_primary = True
                    first_image.save(update_fields=['is_primary'])

            messages.success(request, 'Property updated successfully.')
            return redirect('properties:detail', slug=prop.slug)
    else:
        form = PropertyCreateForm(instance=prop)
        image_form = PropertyImageUploadForm()

    context = {
        'form': form,
        'image_form': image_form,
        'property': prop,
        'existing_images': prop.images.all(),
    }
    return render(request, 'properties/property_edit.html', context)


@login_required
def property_submission_success(request, slug):
    """Show confirmation after a host submits a property for review."""
    if request.user.is_staff or request.user.is_superuser:
        prop = get_object_or_404(Property, slug=slug)
    else:
        prop = get_object_or_404(Property, slug=slug, owner=request.user)

    context = {
        'property': prop,
        'support_email': getattr(settings, 'SUPPORT_EMAIL', getattr(settings, 'DEFAULT_FROM_EMAIL', 'support@example.com')),
    }
    return render(request, 'properties/property_submission_success.html', context)
