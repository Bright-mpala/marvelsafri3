"""Payment integration layer for booking payments."""

import logging
import uuid
from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from bookings.models import Booking
from bookings.services import get_booking_service
from payments.models import PaymentGateway, Transaction

logger = logging.getLogger(__name__)


class PaymentService:
    """Coordinates payment intent creation and payment settlement for bookings."""

    PROVIDER_STRIPE = "stripe"
    PROVIDER_PAYNOW = "paynow"
    PROVIDER_ECOCASH = "ecocash"

    SUPPORTED_PROVIDERS = {
        PROVIDER_STRIPE: {
            "gateway_type": "stripe",
            "display_name": "Stripe",
            "payment_option": Booking.PaymentOption.CARD,
            "currency": lambda: getattr(settings, "STRIPE_CURRENCY", "USD").upper(),
        },
        PROVIDER_PAYNOW: {
            "gateway_type": "offline",
            "display_name": "PayNow",
            "payment_option": Booking.PaymentOption.PAYNOW,
            "currency": lambda: "USD",
        },
        PROVIDER_ECOCASH: {
            "gateway_type": "offline",
            "display_name": "EcoCash",
            "payment_option": Booking.PaymentOption.ECOCASH,
            "currency": lambda: "USD",
        },
    }

    def __init__(self, booking_service=None):
        self.booking_service = booking_service or get_booking_service()

    def create_payment_intent(self, booking, provider, return_url=None, metadata=None):
        """Create a provider-specific payment intent for a pending booking."""
        provider_key = self._normalize_provider(provider)
        metadata = metadata or {}

        with transaction.atomic():
            locked_booking = (
                Booking.objects.select_for_update()
                .select_related("user", "property", "car", "tour")
                .get(pk=booking.pk)
            )

            self._validate_pending_booking(locked_booking)
            gateway = self._get_or_create_gateway(provider_key)

            locked_booking.payment_option = self._provider_payment_option(provider_key)
            locked_booking.payment_status = Booking.PaymentStatus.PENDING
            locked_booking.save(update_fields=["payment_option", "payment_status", "updated_at"])

            transaction_obj = Transaction.objects.create(
                amount=locked_booking.total_amount,
                currency=self._provider_currency(provider_key),
                transaction_type="payment",
                gateway=gateway,
                customer=locked_booking.user,
                booking=locked_booking,
                status="pending",
                description=f"{self._provider_label(provider_key)} payment intent for booking {locked_booking.id}",
                gateway_transaction_id=self._generate_gateway_reference(provider_key),
                metadata={
                    "provider": provider_key,
                    "booking_id": str(locked_booking.id),
                    "return_url": return_url or "",
                    **metadata,
                },
                gateway_response={},
            )

            transaction_obj.gateway_response = self._build_intent_payload(
                booking=locked_booking,
                provider=provider_key,
                transaction_obj=transaction_obj,
                return_url=return_url,
            )
            transaction_obj.save(update_fields=["gateway_response", "updated_at"])

        return {
            "provider": provider_key,
            "booking_id": str(locked_booking.id),
            "transaction_id": str(transaction_obj.id),
            "transaction_reference": transaction_obj.transaction_reference,
            "gateway_transaction_id": transaction_obj.gateway_transaction_id,
            "status": transaction_obj.status,
            "payment_status": locked_booking.payment_status,
            "intent": transaction_obj.gateway_response,
        }

    def process_payment_confirmation(self, booking, provider, success, gateway_response=None):
        """
        Finalize payment result for a booking.

        Success:
        - marks booking payment_status as paid
        - confirms the booking

        Failure:
        - marks booking payment_status as failed
        - keeps booking status pending
        """
        provider_key = self._normalize_provider(provider)
        gateway_response = gateway_response or {}

        with transaction.atomic():
            locked_booking = Booking.objects.select_for_update().get(pk=booking.pk)
            transaction_obj = (
                Transaction.objects.select_for_update()
                .filter(
                    booking=locked_booking,
                    transaction_type="payment",
                    metadata__provider=provider_key,
                )
                .order_by("-created_at")
                .first()
            )

            if transaction_obj is None:
                gateway = self._get_or_create_gateway(provider_key)
                transaction_obj = Transaction.objects.create(
                    amount=locked_booking.total_amount,
                    currency=self._provider_currency(provider_key),
                    transaction_type="payment",
                    gateway=gateway,
                    customer=locked_booking.user,
                    booking=locked_booking,
                    status="pending",
                    description=f"{self._provider_label(provider_key)} payment for booking {locked_booking.id}",
                    gateway_transaction_id=self._generate_gateway_reference(provider_key),
                    metadata={
                        "provider": provider_key,
                        "booking_id": str(locked_booking.id),
                    },
                )

            if success:
                self._mark_transaction_completed(transaction_obj, gateway_response)
                locked_booking.payment_status = Booking.PaymentStatus.PAID
                locked_booking.save(update_fields=["payment_status", "updated_at"])
            else:
                self._mark_transaction_failed(transaction_obj, gateway_response)
                locked_booking.payment_status = Booking.PaymentStatus.FAILED
                if locked_booking.status != Booking.BookingStatus.PENDING:
                    locked_booking.status = Booking.BookingStatus.PENDING
                    locked_booking.save(update_fields=["payment_status", "status", "updated_at"])
                else:
                    locked_booking.save(update_fields=["payment_status", "updated_at"])

        if success and locked_booking.status == Booking.BookingStatus.PENDING:
            confirmed_booking = self.booking_service.confirm_booking(
                booking_id=locked_booking.id,
                user=locked_booking.user,
            )
            locked_booking = confirmed_booking

        return {
            "provider": provider_key,
            "booking_id": str(locked_booking.id),
            "transaction_id": str(transaction_obj.id),
            "success": bool(success),
            "booking_status": locked_booking.status,
            "payment_status": locked_booking.payment_status,
        }

    def _validate_pending_booking(self, booking):
        if booking.payment_status == Booking.PaymentStatus.PAID:
            raise ValueError("Booking payment is already completed.")
        if booking.status not in {
            Booking.BookingStatus.PENDING,
            Booking.BookingStatus.CONFIRMED,
        }:
            raise ValueError(f"Cannot create a payment intent for booking status '{booking.status}'.")

    def _normalize_provider(self, provider):
        provider_key = str(provider or "").strip().lower()
        if provider_key not in self.SUPPORTED_PROVIDERS:
            supported = ", ".join(sorted(self.SUPPORTED_PROVIDERS))
            raise ValueError(f"Unsupported payment provider '{provider}'. Supported providers: {supported}.")
        return provider_key

    def _get_or_create_gateway(self, provider):
        config = self.SUPPORTED_PROVIDERS[provider]
        gateway, _ = PaymentGateway.objects.get_or_create(
            name=f"{config['display_name']} Booking Gateway",
            gateway_type=config["gateway_type"],
            defaults={
                "is_active": True,
                "is_test_mode": bool(getattr(settings, "DEBUG", False)),
                "supported_currencies": [self._provider_currency(provider)],
            },
        )
        return gateway

    def _provider_payment_option(self, provider):
        return self.SUPPORTED_PROVIDERS[provider]["payment_option"]

    def _provider_label(self, provider):
        return self.SUPPORTED_PROVIDERS[provider]["display_name"]

    def _provider_currency(self, provider):
        currency_resolver = self.SUPPORTED_PROVIDERS[provider]["currency"]
        return currency_resolver() if callable(currency_resolver) else currency_resolver

    def _generate_gateway_reference(self, provider):
        return f"{provider.upper()}-{uuid.uuid4().hex[:20].upper()}"

    def _build_intent_payload(self, booking, provider, transaction_obj, return_url):
        amount = Decimal(booking.total_amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        payload = {
            "provider": provider,
            "provider_label": self._provider_label(provider),
            "booking_id": str(booking.id),
            "amount": str(amount),
            "currency": self._provider_currency(provider),
            "status": "pending",
            "return_url": return_url or "",
        }

        if transaction_obj is not None:
            payload.update(
                {
                    "transaction_id": str(transaction_obj.id),
                    "transaction_reference": transaction_obj.transaction_reference,
                    "gateway_transaction_id": transaction_obj.gateway_transaction_id,
                }
            )

        if provider == self.PROVIDER_STRIPE:
            payload["client_secret"] = f"pi_{uuid.uuid4().hex}_secret_{uuid.uuid4().hex}"
        elif provider == self.PROVIDER_PAYNOW:
            payload["redirect_url"] = f"/payments/paynow/{booking.id}/{uuid.uuid4().hex}/"
            payload["poll_reference"] = uuid.uuid4().hex
        elif provider == self.PROVIDER_ECOCASH:
            payload["poll_reference"] = uuid.uuid4().hex
            payload["instructions"] = "Prompt customer to approve the EcoCash charge on their device."

        return payload

    def _mark_transaction_completed(self, transaction_obj, gateway_response):
        now = timezone.now()
        transaction_obj.status = "completed"
        transaction_obj.processed_at = now
        transaction_obj.settled_at = now
        transaction_obj.gateway_response = {
            **(transaction_obj.gateway_response or {}),
            **gateway_response,
            "status": "completed",
        }
        transaction_obj.save(
            update_fields=[
                "status",
                "processed_at",
                "settled_at",
                "gateway_response",
                "updated_at",
            ]
        )

    def _mark_transaction_failed(self, transaction_obj, gateway_response):
        transaction_obj.status = "failed"
        transaction_obj.error_message = str(gateway_response.get("error") or "Payment failed.")
        transaction_obj.gateway_response = {
            **(transaction_obj.gateway_response or {}),
            **gateway_response,
            "status": "failed",
        }
        transaction_obj.save(
            update_fields=[
                "status",
                "error_message",
                "gateway_response",
                "updated_at",
            ]
        )
