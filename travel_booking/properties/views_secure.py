"""
properties/views_secure.py - Production-Ready Secure Property Views

Class-based views with:
- LoginRequiredMixin for authentication
- Permission checks for HOST role
- Service layer for business logic
- Atomic transactions
- Overposting prevention
- Proper error handling
"""

import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import JsonResponse, HttpResponseForbidden
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils.translation import gettext_lazy as _
from django.views import View
from django.views.generic import CreateView, UpdateView, DetailView, ListView

from accounts.models import UserRole
from .forms import PropertyCreateForm, PropertyEditForm, PropertyImageUploadForm, AdminPropertyApprovalForm
from .models import Property, PropertyImage, PropertyStatus
from .services import get_property_service, PropertyService

logger = logging.getLogger(__name__)


# ============================================================================
# MIXIN CLASSES
# ============================================================================

class HostRequiredMixin(UserPassesTestMixin):
    """
    Mixin that requires user to have HOST role.
    
    Admins and superusers are also allowed.
    """
    permission_denied_message = _(
        'Only hosts can access this feature. '
        'Please upgrade your account to become a host.'
    )
    
    def test_func(self):
        user = self.request.user
        if not user.is_authenticated:
            return False
        
        # Allow admins and superusers
        if user.is_staff or user.is_superuser:
            return True
        
        # Require HOST or ADMIN role
        return user.role in {UserRole.HOST, UserRole.ADMIN}
    
    def handle_no_permission(self):
        if not self.request.user.is_authenticated:
            return redirect('accounts:login')
        
        messages.error(self.request, self.permission_denied_message)
        return redirect('accounts:enable_business')


class PropertyOwnerMixin(UserPassesTestMixin):
    """
    Mixin that requires user to own the property.
    
    Admins can access any property.
    """
    
    def test_func(self):
        user = self.request.user
        if not user.is_authenticated:
            return False
        
        # Get property from URL
        property_obj = self.get_property()
        if not property_obj:
            return False
        
        # Admins can access any property
        if user.is_staff or user.is_superuser or user.role == UserRole.ADMIN:
            return True
        
        # Check ownership
        return property_obj.owner_id == user.id
    
    def get_property(self):
        """Get property from URL slug."""
        slug = self.kwargs.get('slug')
        try:
            return Property.objects.get(slug=slug)
        except Property.DoesNotExist:
            return None
    
    def handle_no_permission(self):
        if not self.request.user.is_authenticated:
            return redirect('accounts:login')
        
        messages.error(self.request, _('You do not have permission to access this property.'))
        return redirect('properties:list')


class AdminRequiredMixin(UserPassesTestMixin):
    """
    Mixin that requires admin privileges.
    """
    
    def test_func(self):
        user = self.request.user
        return (
            user.is_authenticated and
            (user.is_staff or user.is_superuser or user.role == UserRole.ADMIN)
        )
    
    def handle_no_permission(self):
        raise PermissionDenied(_('Admin privileges required.'))


# ============================================================================
# PROPERTY CREATION VIEW
# ============================================================================

class PropertyCreateView(LoginRequiredMixin, HostRequiredMixin, CreateView):
    """
    Secure property creation view.
    
    Security features:
    - Requires authentication (LoginRequiredMixin)
    - Requires HOST role (HostRequiredMixin)
    - Uses form validation
    - Atomic transaction
    - Overposting prevention via form field whitelist
    - Owner automatically set to request.user
    - Status forced to DRAFT on creation
    """
    
    model = Property
    form_class = PropertyCreateForm
    template_name = 'properties/property_create.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['image_form'] = PropertyImageUploadForm()
        context['image_errors'] = self.request.session.pop('image_errors', [])

        # Step definitions — used by sidebar and mobile progress bar
        context['steps'] = [
            (1, 'Basic Information',  'fa-home'),
            (2, 'Location',           'fa-map-marker-alt'),
            (3, 'Photos',             'fa-camera'),
            (4, 'Pricing & Payments', 'fa-dollar-sign'),
            (5, 'Amenities & Rooms',  'fa-concierge-bell'),
            (6, 'Policies & Review',  'fa-clipboard-check'),
        ]

        # Payment method choices for the template card UI
        context['payment_method_choices'] = [
            ('card',          'Card (3D Secure)',  'fa-credit-card',      'Visa, Mastercard, 3D Secure protected'),
            ('paynow',        'Paynow',            'fa-mobile-screen',    'Zimbabwe Paynow mobile payments'),
            ('ecocash',       'EcoCash',           'fa-wallet',           'EcoCash mobile money wallet'),
            ('bank_transfer', 'Bank Transfer',     'fa-building-columns', 'Direct bank deposit (ZWL / USD)'),
        ]

        # Pre-selected methods (from form initial or posted data)
        form = context.get('form')
        if form:
            raw = form.initial.get('accepted_payment_methods', [])
            if isinstance(raw, str):
                raw = [m.strip() for m in raw.split(',') if m.strip()]
            context['selected_payment_methods'] = raw
        else:
            context['selected_payment_methods'] = ['card', 'paynow', 'ecocash', 'bank_transfer']

        return context
    
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        # Pre-fill email from user
        if self.request.method == 'GET':
            kwargs['initial'] = {
                'email': self.request.user.email,
                'city': getattr(self.request.user, 'city', ''),
            }
        return kwargs
    
    def form_valid(self, form):
        """
        Handle valid form submission with proper validation.
        """
        try:
            with transaction.atomic():
                # Save the property with owner and status
                property_obj = form.save(commit=False)
                property_obj.owner = self.request.user
                
                property_obj.status = PropertyStatus.DRAFT
                property_obj.submitted_at = None
                
                # Generate unique slug
                from django.utils.text import slugify
                base_slug = slugify(property_obj.name)
                unique_slug = base_slug
                counter = 1
                
                while Property.objects.filter(slug=unique_slug).exists():
                    unique_slug = f"{base_slug}-{counter}"
                    counter += 1
                
                property_obj.slug = unique_slug
                
                # Save the property
                property_obj.save()
                
                # Save many-to-many relationships (amenities)
                form.save_m2m()
                
                # Handle image uploads
                image_errors = self._handle_image_uploads(property_obj)
                
                if image_errors:
                    self.request.session['image_errors'] = image_errors
                    messages.warning(self.request, _('Property saved but some images could not be uploaded.'))
                else:
                    messages.success(
                        self.request,
                        _('Property saved as draft. Submit it for review when you are ready.')
                    )

                if property_obj.requires_listing_payment and property_obj.listing_fee_amount:
                    messages.info(
                        self.request,
                        _(
                            'Optional host listing payment set: %(amount)s %(currency)s via %(method)s. '
                            'Complete payment through secure platform channels only.'
                        ) % {
                            'amount': property_obj.listing_fee_amount,
                            'currency': property_obj.listing_fee_currency,
                            'method': property_obj.get_listing_payment_method_display() or _('Selected method'),
                        }
                    )
                
                # Handle room types (optional)
                self._handle_room_types(property_obj)
                
                # Handle activities/tours (optional)
                self._handle_activities(property_obj)
                
                return redirect('properties:edit', slug=property_obj.slug)
                    
        except Exception as e:
            logger.exception(f"Property creation failed: {e}")
            messages.error(
                self.request,
                _('An error occurred while creating your property. Please try again.')
            )
            return self.form_invalid(form)
    
    def form_invalid(self, form):
        """Handle invalid form."""
        # Capture any image errors from request
        if self.request.FILES.getlist('images'):
            # Validate images manually
            from .validators import validate_image_file
            image_errors = []
            for image_file in self.request.FILES.getlist('images'):
                try:
                    validate_image_file(image_file)
                except Exception as e:
                    image_errors.append(str(e))
            
            if image_errors:
                self.request.session['image_errors'] = image_errors
        
        return super().form_invalid(form)
    
    def _handle_image_uploads(self, prop):
        """Process uploaded images and return any errors."""
        from properties.validators import validate_image_file
        
        images = self.request.FILES.getlist('images')
        image_errors = []
        
        for index, image_file in enumerate(images):
            try:
                # Validate image
                validate_image_file(image_file)
                
                # Create image record
                PropertyImage.objects.create(
                    property=prop,
                    image=image_file,
                    is_primary=(index == 0 and prop.images.count() == 0),
                    display_order=prop.images.count() + index,
                )
            except Exception as e:
                logger.warning(f"Failed to upload image: {e}")
                image_errors.append(f"{image_file.name}: {str(e)}")
        
        return image_errors

    def _handle_room_types(self, prop):
        """Process room types from the form (optional)."""
        from properties.models import RoomType
        from decimal import Decimal, InvalidOperation
        
        # Parse room types from POST data
        room_data = {}
        for key, value in self.request.POST.items():
            if key.startswith('room_types['):
                # Parse key like room_types[1][name]
                import re
                match = re.match(r'room_types\[(\d+)\]\[(\w+)\](\[\])?', key)
                if match:
                    room_id = match.group(1)
                    field = match.group(2)
                    is_array = match.group(3) is not None
                    
                    if room_id not in room_data:
                        room_data[room_id] = {}
                    
                    if is_array:
                        # Handle array fields (like amenities)
                        if field not in room_data[room_id]:
                            room_data[room_id][field] = []
                        room_data[room_id][field].append(value)
                    else:
                        room_data[room_id][field] = value
        
        # Create room types
        for room_id, data in room_data.items():
            if not data.get('name', '').strip():
                continue  # Skip rooms without names
            
            try:
                # Parse price safely
                price = None
                if data.get('price'):
                    try:
                        price = Decimal(data['price'])
                    except InvalidOperation:
                        price = None
                
                # Parse room size
                room_size = None
                if data.get('size'):
                    try:
                        room_size = Decimal(data['size'])
                    except InvalidOperation:
                        room_size = None
                
                # Create room type
                room_type = RoomType.objects.create(
                    property=prop,
                    name=data.get('name', '').strip(),
                    description=data.get('description', '').strip(),
                    base_price=price,
                    max_adults=int(data.get('max_adults', 2) or 2),
                    max_children=int(data.get('max_children', 2) or 2),
                    max_occupancy=int(data.get('max_adults', 2) or 2) + int(data.get('max_children', 2) or 2),
                    room_size=room_size,
                    bed_type=data.get('bed_type', 'double'),
                    bed_count=1,
                    bathroom_count=int(data.get('bathrooms', 1) or 1),
                    quantity_available=int(data.get('quantity', 1) or 1),
                )
                
                # Handle room images
                room_images = self.request.FILES.getlist(f'room_types[{room_id}][images]')
                for img_index, image_file in enumerate(room_images):
                    try:
                        from .models import RoomTypeImage
                        RoomTypeImage.objects.create(
                            room_type=room_type,
                            image=image_file,
                            is_primary=(img_index == 0),
                            display_order=img_index,
                        )
                    except Exception as e:
                        logger.warning(f"Failed to upload room image: {e}")
                
                logger.info(f"Created room type '{room_type.name}' for property {prop.id}")
                
            except Exception as e:
                logger.warning(f"Failed to create room type: {e}")

    def _handle_activities(self, prop):
        """Process activities/tours from the form (optional)."""
        from properties.models import PropertyActivity
        from decimal import Decimal, InvalidOperation
        
        # Parse activities from POST data
        activity_data = {}
        for key, value in self.request.POST.items():
            if key.startswith('activities['):
                # Parse key like activities[1][name]
                import re
                match = re.match(r'activities\[(\d+)\]\[(\w+)\]', key)
                if match:
                    activity_id = match.group(1)
                    field = match.group(2)
                    
                    if activity_id not in activity_data:
                        activity_data[activity_id] = {}
                    
                    activity_data[activity_id][field] = value
        
        # Skip if no activities
        if not activity_data:
            return
        
        # Create activities linked to property
        for activity_id, data in activity_data.items():
            if not data.get('name', '').strip():
                continue  # Skip activities without names
            
            try:
                # Parse price safely
                price = None
                if data.get('price'):
                    try:
                        price = Decimal(data['price'])
                    except InvalidOperation:
                        price = None
                
                PropertyActivity.objects.create(
                    property=prop,
                    name=data.get('name', '').strip(),
                    description=data.get('description', '').strip(),
                    activity_type=data.get('type', 'tour'),
                    price_per_person=price,
                    duration=data.get('duration', ''),
                    min_participants=int(data.get('min_participants', 1) or 1),
                    max_participants=int(data.get('max_participants', 10) or 10) if data.get('max_participants') else None,
                    availability=data.get('availability', 'daily'),
                    difficulty=data.get('difficulty', 'moderate'),
                    included=data.get('included', ''),
                    is_active=False,
                )
                
                logger.info(f"Created activity for property {prop.id}")
                
            except Exception as e:
                logger.warning(f"Failed to create activity: {e}")


# ============================================================================
# PROPERTY EDIT VIEW
# ============================================================================

class PropertyEditView(LoginRequiredMixin, PropertyOwnerMixin, UpdateView):
    """
    Secure property edit view.
    
    Security features:
    - Requires authentication
    - Requires property ownership (or admin)
    - Only allows editing in certain statuses
    - Uses form validation
    - Atomic transaction
    - Cannot modify status, owner, or approval fields
    """
    
    model = Property
    form_class = PropertyEditForm
    template_name = 'properties/property_edit.html'
    context_object_name = 'property'
    slug_url_kwarg = 'slug'
    
    def get_queryset(self):
        """Only allow editing non-deleted properties."""
        return Property.objects.filter(is_deleted=False)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['image_form'] = PropertyImageUploadForm()
        context['existing_images'] = self.object.images.all()
        return context
    
    def dispatch(self, request, *args, **kwargs):
        """Check if property can be edited."""
        response = super().dispatch(request, *args, **kwargs)
        
        prop = self.get_object()
        
        # Check if user can edit this property
        if not prop.can_be_edited_by(request.user):
            messages.error(
                request,
                _('This property cannot be edited in its current status. '
                  'Please contact support for changes.')
            )
            return redirect('properties:detail', slug=prop.slug)
        
        return response
    
    @transaction.atomic
    def form_valid(self, form):
        """Handle valid form submission."""
        try:
            property_obj = form.save()
            
            # Handle new image uploads
            self._handle_image_uploads(property_obj)
            
            # Handle image deletions
            self._handle_image_deletions(property_obj)
            
            # Handle primary image selection
            self._handle_primary_image(property_obj)
            
            messages.success(self.request, _('Property updated successfully.'))
            return redirect('properties:detail', slug=property_obj.slug)
            
        except PermissionDenied as e:
            messages.error(self.request, str(e))
            return redirect('properties:list')
            
        except Exception as e:
            logger.exception(f"Property update failed: {e}")
            messages.error(
                self.request,
                _('An error occurred while updating your property. Please try again.')
            )
            return self.form_invalid(form)
    
    def _handle_image_uploads(self, prop):
        """Process new image uploads."""
        from properties.validators import validate_image_file
        
        images = self.request.FILES.getlist('images')
        start_order = prop.images.count()
        
        for index, image_file in enumerate(images):
            try:
                validate_image_file(image_file)
                PropertyImage.objects.create(
                    property=prop,
                    image=image_file,
                    display_order=start_order + index,
                    is_primary=(start_order == 0 and index == 0 and not prop.images.filter(is_primary=True).exists()),
                )
            except Exception as e:
                logger.warning(f"Failed to upload image: {e}")
                messages.warning(self.request, f"Could not upload {image_file.name}: {str(e)}")
    
    def _handle_image_deletions(self, prop):
        """Process image deletion requests."""
        delete_ids = self.request.POST.getlist('delete_images')
        if delete_ids:
            # Check if we're deleting the primary image
            primary_deleted = prop.images.filter(id__in=delete_ids, is_primary=True).exists()
            prop.images.filter(id__in=delete_ids).delete()
            
            # If primary was deleted, set a new primary
            if primary_deleted and prop.images.exists():
                first_image = prop.images.order_by('display_order', 'created_at').first()
                if first_image:
                    first_image.is_primary = True
                    first_image.save(update_fields=['is_primary'])
    
    def _handle_primary_image(self, prop):
        """Process primary image selection."""
        primary_id = self.request.POST.get('primary_image')
        if primary_id:
            prop.images.update(is_primary=False)
            prop.images.filter(id=primary_id).update(is_primary=True)
        
        # Ensure at least one primary image
        if prop.images.exists() and not prop.images.filter(is_primary=True).exists():
            first_image = prop.images.order_by('display_order', 'created_at').first()
            if first_image:
                first_image.is_primary = True
                first_image.save(update_fields=['is_primary'])


# ============================================================================
# PROPERTY SUBMISSION SUCCESS VIEW  
# ============================================================================

class PropertySubmissionSuccessView(LoginRequiredMixin, PropertyOwnerMixin, DetailView):
    """Show confirmation after property submission."""
    
    model = Property
    template_name = 'properties/property_submission_success.html'
    context_object_name = 'property'
    slug_url_kwarg = 'slug'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['support_email'] = getattr(
            settings, 'SUPPORT_EMAIL', 
            getattr(settings, 'DEFAULT_FROM_EMAIL', 'support@example.com')
        )
        return context


# ============================================================================
# ADMIN APPROVAL VIEWS
# ============================================================================

class AdminPendingPropertiesView(LoginRequiredMixin, AdminRequiredMixin, ListView):
    """List all properties pending admin review."""
    
    model = Property
    template_name = 'admin/properties/pending_list.html'
    context_object_name = 'properties'
    paginate_by = 20
    
    def get_queryset(self):
        return Property.objects.filter(
            status=PropertyStatus.PENDING_REVIEW,
            is_deleted=False
        ).select_related(
            'owner', 'property_type'
        ).prefetch_related(
            'images'
        ).order_by('submitted_at', 'created_at')


class AdminPropertyReviewView(LoginRequiredMixin, AdminRequiredMixin, DetailView):
    """Admin view for reviewing and approving/rejecting a property."""
    
    model = Property
    template_name = 'admin/properties/review_property.html'
    context_object_name = 'property'
    slug_url_kwarg = 'slug'
    
    def get_queryset(self):
        return Property.objects.filter(
            is_deleted=False
        ).select_related('owner', 'property_type').prefetch_related('images', 'amenities')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['form'] = AdminPropertyApprovalForm()
        return context
    
    @transaction.atomic
    def post(self, request, *args, **kwargs):
        """Handle approval/rejection submission."""
        self.object = self.get_object()
        form = AdminPropertyApprovalForm(request.POST)
        
        if form.is_valid():
            try:
                service = get_property_service(request)
                action = form.cleaned_data['action']
                
                if action == 'approve':
                    service.approve_property(
                        self.object,
                        request.user,
                        notes=form.cleaned_data.get('notes', '')
                    )
                    messages.success(request, _('Property approved successfully.'))
                    
                elif action == 'reject':
                    service.reject_property(
                        self.object,
                        request.user,
                        reason=form.cleaned_data['rejection_reason']
                    )
                    messages.success(request, _('Property rejected. Owner has been notified.'))

                elif action == 'suspend':
                    service.suspend_property(
                        self.object,
                        request.user,
                        reason=form.cleaned_data['rejection_reason']
                    )
                    messages.success(request, _('Property suspended successfully.'))
                
                return redirect('properties:admin_property_pending')
                
            except Exception as e:
                logger.exception(f"Admin action failed: {e}")
                messages.error(request, _('An error occurred. Please try again.'))
        
        context = self.get_context_data(form=form)
        return render(request, self.template_name, context)


class AdminPropertyApproveView(LoginRequiredMixin, AdminRequiredMixin, View):
    """Approve a property from the moderation interface."""

    @transaction.atomic
    def post(self, request, slug):
        property_obj = get_object_or_404(Property, slug=slug, is_deleted=False)
        try:
            get_property_service(request).approve_property(property_obj, request.user)
            messages.success(request, _('Property approved successfully.'))
        except Exception as exc:
            logger.exception("Property approval failed: %s", exc)
            messages.error(request, _('Could not approve this property.'))
        return redirect('properties:admin_property_review', slug=slug)


class AdminPropertyRejectView(LoginRequiredMixin, AdminRequiredMixin, View):
    """Reject a property from the moderation interface."""

    @transaction.atomic
    def post(self, request, slug):
        property_obj = get_object_or_404(Property, slug=slug, is_deleted=False)
        reason = request.POST.get('rejection_reason', '').strip()

        if not reason:
            messages.error(request, _('A rejection reason is required.'))
            return redirect('properties:admin_property_review', slug=slug)

        try:
            get_property_service(request).reject_property(property_obj, request.user, reason=reason)
            messages.success(request, _('Property rejected and host notified.'))
        except Exception as exc:
            logger.exception("Property rejection failed: %s", exc)
            messages.error(request, _('Could not reject this property.'))
        return redirect('properties:admin_property_review', slug=slug)


# ============================================================================
# AJAX ENDPOINTS
# ============================================================================

class PropertySubmitForReviewView(LoginRequiredMixin, PropertyOwnerMixin, View):
    """AJAX endpoint to submit a draft property for review."""
    
    def get_property(self):
        slug = self.kwargs.get('slug')
        return get_object_or_404(Property, slug=slug)
    
    @transaction.atomic
    def post(self, request, slug):
        prop = self.get_property()
        
        try:
            service = get_property_service(request)
            service.submit_for_review(prop, request.user)
            
            return JsonResponse({
                'success': True,
                'message': _('Property submitted for review.')
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=400)


class PropertyDeactivateView(LoginRequiredMixin, PropertyOwnerMixin, View):
    """AJAX endpoint to deactivate a property."""
    
    def get_property(self):
        slug = self.kwargs.get('slug')
        return get_object_or_404(Property, slug=slug)
    
    @transaction.atomic
    def post(self, request, slug):
        prop = self.get_property()
        
        try:
            service = get_property_service(request)
            service.deactivate_property(prop, request.user)
            
            return JsonResponse({
                'success': True,
                'message': _('Property deactivated.')
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=400)


# ============================================================================
# OWNER DASHBOARD VIEWS
# ============================================================================

class OwnerPropertyListView(LoginRequiredMixin, HostRequiredMixin, ListView):
    """List all properties owned by the current user."""
    
    model = Property
    template_name = 'properties/owner/property_list.html'
    context_object_name = 'properties'
    paginate_by = 12
    
    def get_queryset(self):
        service = get_property_service(self.request)
        queryset = service.get_owner_properties(self.request.user)

        status_filter = self.request.GET.get('status')
        valid_statuses = {choice[0] for choice in PropertyStatus.choices}
        if status_filter in valid_statuses:
            queryset = queryset.filter(status=status_filter)

        sort_by = self.request.GET.get('sort', '-created_at')
        valid_sorts = {'-created_at', 'created_at', 'name', '-name', 'status', '-status'}
        if sort_by in valid_sorts:
            queryset = queryset.order_by(sort_by)

        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Status counts
        all_owner_properties = get_property_service(self.request).get_owner_properties(self.request.user)
        context['draft_count'] = all_owner_properties.filter(status=PropertyStatus.DRAFT).count()
        context['pending_count'] = all_owner_properties.filter(status=PropertyStatus.PENDING_REVIEW).count()
        context['approved_count'] = all_owner_properties.filter(
            status__in=[PropertyStatus.APPROVED, PropertyStatus.ACTIVE]
        ).count()
        context['rejected_count'] = all_owner_properties.filter(status=PropertyStatus.REJECTED).count()
        
        return context


# ============================================================================
# HOST ANALYTICS DASHBOARD
# ============================================================================

from decimal import Decimal
from datetime import date, timedelta
from django.utils import timezone
from django.db.models import Sum, Count, Avg, Q


class HostAnalyticsView(LoginRequiredMixin, HostRequiredMixin, View):
    """
    Comprehensive analytics dashboard for property hosts.
    Shows revenue, occupancy, booking trends and per-property performance.
    """
    template_name = 'properties/host_analytics.html'

    def get(self, request):
        from bookings.models import Booking
        from reviews.models import Review

        user = request.user
        now = timezone.now()
        today = now.date()

        # ── Properties owned by this host ─────────────────────────
        host_properties = Property.objects.filter(
            owner=user, is_deleted=False
        ).prefetch_related('images').order_by('-created_at')

        property_ids = list(host_properties.values_list('id', flat=True))

        # ── All bookings across host's properties ──────────────────
        all_bookings = Booking.objects.filter(
            property_id__in=property_ids,
            is_deleted=False,
        ).select_related('property', 'user')

        # ── KPI cards ──────────────────────────────────────────────
        total_revenue = all_bookings.filter(
            status__in=['confirmed', 'completed'],
            payment_status='paid',
        ).aggregate(total=Sum('host_payout_amount'))['total'] or Decimal('0')

        total_bookings = all_bookings.count()
        confirmed_bookings = all_bookings.filter(status__in=['confirmed', 'completed']).count()
        pending_bookings = all_bookings.filter(status='pending').count()
        cancelled_bookings = all_bookings.filter(status='cancelled').count()

        # ── This month vs last month ────────────────────────────────
        month_start = today.replace(day=1)
        last_month_end = month_start - timedelta(days=1)
        last_month_start = last_month_end.replace(day=1)

        this_month_revenue = all_bookings.filter(
            status__in=['confirmed', 'completed'],
            payment_status='paid',
            check_in_date__gte=month_start,
        ).aggregate(total=Sum('host_payout_amount'))['total'] or Decimal('0')

        last_month_revenue = all_bookings.filter(
            status__in=['confirmed', 'completed'],
            payment_status='paid',
            check_in_date__gte=last_month_start,
            check_in_date__lt=month_start,
        ).aggregate(total=Sum('host_payout_amount'))['total'] or Decimal('0')

        if last_month_revenue > 0:
            revenue_change_pct = round(float((this_month_revenue - last_month_revenue) / last_month_revenue * 100), 1)
        else:
            revenue_change_pct = None

        this_month_bookings = all_bookings.filter(
            created_at__date__gte=month_start,
        ).count()

        # ── Monthly revenue — last 12 months (for bar chart) ───────
        monthly_revenue = []
        monthly_labels = []
        for i in range(11, -1, -1):
            # Calculate month boundaries
            ref = today.replace(day=1)
            month_offset = ref.month - i - 1
            year_offset = ref.year + month_offset // 12
            month_num = month_offset % 12 + 1
            if month_num <= 0:
                month_num += 12
                year_offset -= 1
            try:
                m_start = date(year_offset, month_num, 1)
            except ValueError:
                m_start = date(today.year, today.month, 1)
            if month_num == 12:
                m_end = date(year_offset + 1, 1, 1)
            else:
                m_end = date(year_offset, month_num + 1, 1)

            rev = all_bookings.filter(
                status__in=['confirmed', 'completed'],
                payment_status='paid',
                check_in_date__gte=m_start,
                check_in_date__lt=m_end,
            ).aggregate(total=Sum('host_payout_amount'))['total'] or Decimal('0')

            monthly_revenue.append(round(float(rev), 2))
            monthly_labels.append(m_start.strftime('%b %y'))

        # ── Booking status breakdown (for donut chart) ─────────────
        status_counts = {
            'confirmed': confirmed_bookings,
            'pending': pending_bookings,
            'cancelled': cancelled_bookings,
            'completed': all_bookings.filter(status='completed').count(),
        }

        # ── Occupancy — last 30 days ────────────────────────────────
        last_30_start = today - timedelta(days=30)
        active_property_count = host_properties.filter(
            status__in=['approved', 'active']
        ).count()

        booked_nights_30d = 0
        for bk in all_bookings.filter(
            status__in=['confirmed', 'completed'],
            check_in_date__lt=today,
            check_out_date__gt=last_30_start,
        ):
            overlap_start = max(bk.check_in_date, last_30_start)
            overlap_end = min(bk.check_out_date, today)
            booked_nights_30d += max((overlap_end - overlap_start).days, 0)

        total_available_nights = active_property_count * 30
        occupancy_rate = round(booked_nights_30d / total_available_nights * 100, 1) if total_available_nights else 0

        # ── Per-property performance table ─────────────────────────
        property_stats = []
        for prop in host_properties:
            prop_bookings = all_bookings.filter(property=prop)
            prop_revenue = prop_bookings.filter(
                status__in=['confirmed', 'completed'],
                payment_status='paid',
            ).aggregate(total=Sum('host_payout_amount'))['total'] or Decimal('0')

            prop_confirmed = prop_bookings.filter(status__in=['confirmed', 'completed']).count()
            prop_pending = prop_bookings.filter(status='pending').count()

            property_stats.append({
                'property': prop,
                'total_bookings': prop_bookings.count(),
                'confirmed': prop_confirmed,
                'pending': prop_pending,
                'revenue': prop_revenue,
                'rating': prop.average_rating,
                'review_count': prop.review_count,
            })

        property_stats.sort(key=lambda x: x['revenue'], reverse=True)

        # ── Recent bookings ─────────────────────────────────────────
        recent_bookings = all_bookings.order_by('-created_at')[:10]

        # ── Avg review score across all properties ─────────────────
        avg_review = host_properties.aggregate(avg=Avg('average_rating'))['avg']
        avg_review = round(float(avg_review), 2) if avg_review else None

        context = {
            # KPIs
            'total_revenue': total_revenue,
            'total_bookings': total_bookings,
            'confirmed_bookings': confirmed_bookings,
            'pending_bookings': pending_bookings,
            'cancelled_bookings': cancelled_bookings,
            'this_month_revenue': this_month_revenue,
            'last_month_revenue': last_month_revenue,
            'revenue_change_pct': revenue_change_pct,
            'this_month_bookings': this_month_bookings,
            'occupancy_rate': occupancy_rate,
            'avg_review': avg_review,
            'active_property_count': active_property_count,
            'total_properties': host_properties.count(),
            # Charts
            'monthly_revenue_json': monthly_revenue,
            'monthly_labels_json': monthly_labels,
            'status_counts_json': status_counts,
            # Tables
            'property_stats': property_stats,
            'recent_bookings': recent_bookings,
        }
        return render(request, self.template_name, context)
