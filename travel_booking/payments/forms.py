from datetime import date
import re

from django import forms
from django.utils.translation import gettext_lazy as _

from bookings.models import Booking


class BookingCheckoutForm(forms.Form):
    """Checkout form for booking payments (simulated gateway)."""

    SKIP_PAYMENT_OPTION = 'skip'

    payment_option = forms.ChoiceField(
        choices=(),
        widget=forms.RadioSelect,
        label=_('Payment method'),
    )

    card_number = forms.CharField(
        max_length=19,
        required=False,
        widget=forms.TextInput(
            attrs={
                'class': 'form-control',
                'placeholder': '1234 5678 9012 3456',
                'inputmode': 'numeric',
                'autocomplete': 'cc-number',
            }
        ),
        label=_('Card number'),
    )
    card_name = forms.CharField(
        max_length=120,
        required=False,
        widget=forms.TextInput(
            attrs={
                'class': 'form-control',
                'placeholder': _('Name on card'),
                'autocomplete': 'cc-name',
            }
        ),
        label=_('Name on card'),
    )
    card_expiry_month = forms.ChoiceField(
        choices=[(str(i), f'{i:02d}') for i in range(1, 13)],
        required=False,
        widget=forms.Select(attrs={'class': 'form-control', 'autocomplete': 'cc-exp-month'}),
        label=_('Expiry month'),
    )
    card_expiry_year = forms.ChoiceField(
        choices=[(str(i), str(i)) for i in range(date.today().year, date.today().year + 11)],
        required=False,
        widget=forms.Select(attrs={'class': 'form-control', 'autocomplete': 'cc-exp-year'}),
        label=_('Expiry year'),
    )
    card_cvv = forms.CharField(
        max_length=4,
        required=False,
        widget=forms.TextInput(
            attrs={
                'class': 'form-control',
                'placeholder': '123',
                'inputmode': 'numeric',
                'autocomplete': 'cc-csc',
            }
        ),
        label=_('CVV'),
    )

    billing_address = forms.CharField(
        max_length=200,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': _('Billing address')}),
        label=_('Billing address'),
    )
    billing_city = forms.CharField(
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': _('City')}),
        label=_('Billing city'),
    )
    billing_country = forms.CharField(
        max_length=2,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': _('Country code')}),
        label=_('Billing country'),
    )
    billing_postal_code = forms.CharField(
        max_length=20,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': _('Postal code')}),
        label=_('Billing postal code'),
    )

    accept_terms = forms.BooleanField(
        required=True,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        label=_('I accept the terms and confirm this is an on-platform payment.'),
        error_messages={
            'required': _('You must accept the terms before completing checkout.'),
        },
    )

    def __init__(
        self,
        *args,
        payment_choices=None,
        allow_skip=False,
        require_card_fields=True,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.require_card_fields = bool(require_card_fields)
        choices = list(payment_choices or Booking.PaymentOption.choices)
        if allow_skip:
            choices.append((self.SKIP_PAYMENT_OPTION, _('Skip payment (testing only)')))
        self.fields['payment_option'].choices = choices

    def clean_card_number(self):
        card_number = (self.cleaned_data.get('card_number') or '').replace(' ', '')
        selected_option = self.cleaned_data.get('payment_option')

        if self.require_card_fields and selected_option == Booking.PaymentOption.CARD and not card_number:
            raise forms.ValidationError(_('Card number is required for card payments.'))

        if card_number:
            if not re.fullmatch(r'\d{13,19}', card_number):
                raise forms.ValidationError(_('Card number must contain 13 to 19 digits.'))
            if not self._validate_luhn(card_number):
                raise forms.ValidationError(_('Please enter a valid card number.'))
        return card_number

    def clean_card_cvv(self):
        cvv = (self.cleaned_data.get('card_cvv') or '').strip()
        selected_option = self.cleaned_data.get('payment_option')

        if self.require_card_fields and selected_option == Booking.PaymentOption.CARD and not cvv:
            raise forms.ValidationError(_('CVV is required for card payments.'))

        if cvv and not re.fullmatch(r'\d{3,4}', cvv):
            raise forms.ValidationError(_('CVV must be 3 or 4 digits.'))
        return cvv

    def clean(self):
        cleaned_data = super().clean()
        selected_option = cleaned_data.get('payment_option')

        if self.require_card_fields and selected_option == Booking.PaymentOption.CARD:
            required_fields = (
                'card_number',
                'card_name',
                'card_expiry_month',
                'card_expiry_year',
                'card_cvv',
            )
            for field_name in required_fields:
                if not cleaned_data.get(field_name):
                    self.add_error(field_name, _('This field is required for card payments.'))

            month_value = cleaned_data.get('card_expiry_month')
            year_value = cleaned_data.get('card_expiry_year')
            if month_value and year_value:
                now = date.today()
                exp_month = int(month_value)
                exp_year = int(year_value)
                if exp_year < now.year or (exp_year == now.year and exp_month < now.month):
                    self.add_error('card_expiry_month', _('Card expiry date cannot be in the past.'))

        return cleaned_data

    @staticmethod
    def _validate_luhn(card_number):
        digits = [int(digit) for digit in card_number]
        checksum = 0
        parity = len(digits) % 2

        for index, digit in enumerate(digits):
            if index % 2 == parity:
                digit *= 2
                if digit > 9:
                    digit -= 9
            checksum += digit
        return checksum % 10 == 0
