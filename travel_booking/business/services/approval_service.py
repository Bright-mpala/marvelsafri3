from django.db import transaction
from django.utils import timezone

from bookings.models import Booking
from bookings.services import BookingService

from ..models import BusinessBookingApproval


def _confirm_related_booking(approval):
    """Confirm the linked booking when an approval is granted."""
    if approval.booking:
        booking = approval.booking
        if booking.status != Booking.BookingStatus.CONFIRMED:
            booking.status = Booking.BookingStatus.CONFIRMED
            booking.save(update_fields=["status"])
            BookingService._mark_property_unavailable(booking)
            BookingService._publish_booking_confirmed_event(booking)
            BookingService._send_confirmation_notification(booking)
        return

    linked_bookings = [
        approval.flight_booking,
        approval.car_rental_booking,
        approval.tour_booking,
    ]
    for linked_booking in linked_bookings:
        if linked_booking and getattr(linked_booking, "status", None) != "confirmed":
            linked_booking.status = "confirmed"
            linked_booking.save(update_fields=["status"])
            return


def approve_booking(approval, approver, notes):
    with transaction.atomic():
        approval.approver = approver
        approval.status = "approved"
        approval.decision_notes = notes
        approval.decision_date = timezone.now()
        approval.save(update_fields=["approver", "status", "decision_notes", "decision_date", "updated_at"])
        _confirm_related_booking(approval)

    return approval


def reject_booking(approval, approver, notes):
    approval.approver = approver
    approval.status = "rejected"
    approval.decision_notes = notes
    approval.decision_date = timezone.now()
    approval.save(update_fields=["approver", "status", "decision_notes", "decision_date", "updated_at"])
    return approval


def escalate_booking(approval, approver, next_approver, notes=""):
    with transaction.atomic():
        approval.approver = approver
        approval.status = "escalated"
        approval.decision_notes = notes
        approval.decision_date = timezone.now()
        approval.escalated_to = next_approver
        approval.escalation_reason = notes
        approval.save(
            update_fields=[
                "approver",
                "status",
                "decision_notes",
                "decision_date",
                "escalated_to",
                "escalation_reason",
                "updated_at",
            ]
        )

        return BusinessBookingApproval.objects.create(
            business_account=approval.business_account,
            employee=approval.employee,
            approver=next_approver,
            booking=approval.booking,
            flight_booking=approval.flight_booking,
            car_rental_booking=approval.car_rental_booking,
            tour_booking=approval.tour_booking,
            approval_level=approval.approval_level + 1,
        )
