from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from properties.models import RoomType

from .models import Booking


class BookingForm(forms.ModelForm):
    """Form for creating and updating bookings with comprehensive validation."""

    secure_payment_consent = forms.BooleanField(
        required=True,
        label=_('I will only complete payment through Marvel Safari secure checkout options.'),
        error_messages={
            'required': _('You must confirm secure on-platform payment.'),
        }
    )

    class Meta:
        model = Booking
        fields = [
            'room_type',
            'check_in_date',
            'check_out_date',
            'guests',
            'payment_option',
            'special_requests',
        ]
        widgets = {
            'room_type': forms.Select(attrs={
                'class': 'form-control',
            }),
            'check_in_date': forms.DateInput(attrs={
                'type': 'date',
                'class': 'form-control no-flatpickr',
                'min': timezone.now().date().isoformat(),
                'required': 'required',
            }),
            'check_out_date': forms.DateInput(attrs={
                'type': 'date',
                'class': 'form-control no-flatpickr',
                'required': 'required',
            }),
            'guests': forms.NumberInput(attrs={
                'min': 1,
                'max': 10,
                'class': 'form-control',
                'placeholder': _('Number of guests'),
                'required': 'required',
            }),
            'special_requests': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4,
                'placeholder': _('Any special requests or preferences (optional)'),
            }),
            'payment_option': forms.Select(attrs={
                'class': 'form-control',
            }),
        }
        labels = {
            'room_type': _('Room Type'),
            'check_in_date': _('Check-in Date'),
            'check_out_date': _('Check-out Date'),
            'guests': _('Number of Guests'),
            'payment_option': _('Secure Payment Method'),
            'special_requests': _('Special Requests'),
        }
        help_texts = {
            'guests': _('Maximum 10 guests per booking'),
            'payment_option': _('Only use secure in-platform payment channels.'),
            'special_requests': _('Optional - let the host know about any special needs'),
        }

    def __init__(self, *args, **kwargs):
        property_obj = kwargs.pop('property_obj', None)
        super().__init__(*args, **kwargs)
        self.fields['payment_option'].required = True
        self.fields['payment_option'].choices = [
            choice for choice in self.fields['payment_option'].choices if choice[0]
        ]
        self.fields['payment_option'].initial = Booking.PaymentOption.CARD
        self.fields['room_type'].required = False
        self.fields['room_type'].queryset = RoomType.objects.none()

        if property_obj:
            room_types = property_obj.room_types.order_by('display_order', 'name')
            self.fields['room_type'].queryset = room_types
            self.fields['room_type'].required = room_types.exists()
            if room_types.exists():
                self.fields['room_type'].empty_label = _('Select a room type')
            else:
                self.fields.pop('room_type')

    def clean(self):
        """Comprehensive validation for booking form."""
        cleaned_data = super().clean()
        check_in_date = cleaned_data.get('check_in_date')
        check_out_date = cleaned_data.get('check_out_date')
        guests = cleaned_data.get('guests')
        room_type = cleaned_data.get('room_type')

        if check_in_date and check_out_date:
            today = timezone.now().date()
            if check_in_date < today:
                self.add_error('check_in_date', _('Check-in date must be today or in the future.'))

            if check_out_date <= check_in_date:
                self.add_error('check_out_date', _('Check-out date must be after check-in date.'))
            else:
                nights = (check_out_date - check_in_date).days
                if nights < 1:
                    self.add_error('check_out_date', _('Minimum stay is 1 night.'))
                if nights > 365:
                    self.add_error('check_out_date', _('Maximum stay is 365 nights.'))

        if guests:
            if guests < 1 or guests > 10:
                self.add_error('guests', _('Number of guests must be between 1 and 10.'))
            elif room_type and guests > room_type.max_occupancy:
                self.add_error(
                    'guests',
                    _('Selected room type can host at most %(max_occupancy)s guest(s).') % {
                        'max_occupancy': room_type.max_occupancy
                    }
                )

        return cleaned_data

    def clean_check_in_date(self):
        """Validate check-in date is not in the past."""
        check_in_date = self.cleaned_data.get('check_in_date')
        if check_in_date and check_in_date < timezone.now().date():
            raise ValidationError(_('Check-in date cannot be in the past.'))
        return check_in_date

    def clean_check_out_date(self):
        """Validate check-out date."""
        check_out_date = self.cleaned_data.get('check_out_date')
        check_in_date = self.cleaned_data.get('check_in_date')

        if check_out_date and check_in_date and check_out_date <= check_in_date:
            raise ValidationError(_('Check-out date must be after check-in date.'))

        return check_out_date


class BookingModifyForm(forms.ModelForm):
    """Form for modifying an existing booking safely."""

    class Meta:
        model = Booking
        fields = [
            'check_in_date',
            'check_out_date',
            'guests',
            'special_requests',
        ]
        widgets = {
            'check_in_date': forms.DateInput(attrs={
                'type': 'date',
                'class': 'form-control no-flatpickr',
                'required': 'required',
            }),
            'check_out_date': forms.DateInput(attrs={
                'type': 'date',
                'class': 'form-control no-flatpickr',
                'required': 'required',
            }),
            'guests': forms.NumberInput(attrs={
                'min': 1,
                'max': 10,
                'class': 'form-control',
                'required': 'required',
            }),
            'special_requests': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4,
                'placeholder': _('Update any special requests (optional)'),
            }),
        }

    def clean(self):
        cleaned_data = super().clean()
        check_in_date = cleaned_data.get('check_in_date')
        check_out_date = cleaned_data.get('check_out_date')
        guests = cleaned_data.get('guests')

        if check_in_date and check_out_date:
            today = timezone.now().date()
            if check_in_date < today:
                self.add_error('check_in_date', _('Check-in date must be today or in the future.'))
            if check_out_date <= check_in_date:
                self.add_error('check_out_date', _('Check-out date must be after check-in date.'))
            else:
                nights = (check_out_date - check_in_date).days
                if nights < 1:
                    self.add_error('check_out_date', _('Minimum stay is 1 night.'))
                if nights > 365:
                    self.add_error('check_out_date', _('Maximum stay is 365 nights.'))

        if guests and (guests < 1 or guests > 10):
            self.add_error('guests', _('Number of guests must be between 1 and 10.'))

        return cleaned_data
