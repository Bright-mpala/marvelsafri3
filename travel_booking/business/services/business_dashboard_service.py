from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, Q
from django.utils import timezone

from ..models import (
    BusinessBookingApproval,
    BusinessDepartment,
    BusinessEmployee,
    BusinessExpenseReport,
    BusinessTravelPolicy,
)


def _approval_total_amount(approval):
    """Return the total monetary amount for any approval booking type."""
    if approval.booking and approval.booking.total_amount is not None:
        return approval.booking.total_amount
    if approval.flight_booking and approval.flight_booking.total_amount is not None:
        return approval.flight_booking.total_amount
    if approval.car_rental_booking and approval.car_rental_booking.total_amount is not None:
        return approval.car_rental_booking.total_amount
    if approval.tour_booking and approval.tour_booking.total_amount is not None:
        return approval.tour_booking.total_amount
    return Decimal("0")


def _approval_destination(approval):
    """Resolve city/country for different approval booking types."""
    if approval.booking and approval.booking.property:
        property_obj = approval.booking.property
        return property_obj.city, str(property_obj.country or "")
    if approval.flight_booking and approval.flight_booking.flight_schedule:
        destination = approval.flight_booking.flight_schedule.flight.destination
        return destination.city, destination.country
    if approval.car_rental_booking and approval.car_rental_booking.dropoff_location:
        location = approval.car_rental_booking.dropoff_location
        return location.city, str(location.country or "")
    if approval.tour_booking and approval.tour_booking.tour:
        tour = approval.tour_booking.tour
        return tour.city, tour.country
    return "", ""


def _format_trend(current, previous):
    """Format trend percentage between two windows."""
    if previous > 0:
        percent = ((current - previous) / previous) * 100
    elif current > 0:
        percent = 100
    else:
        percent = 0
    rounded = round(percent, 1)
    sign = "+" if rounded > 0 else ""
    return f"{sign}{rounded}%"


def _get_dashboard_approvals_queryset(business_account):
    return (
        BusinessBookingApproval.objects.filter(business_account=business_account)
        .select_related(
            "employee__user",
            "approver",
            "booking__property",
            "flight_booking__flight_schedule__flight__destination",
            "car_rental_booking__dropoff_location",
            "tour_booking__tour",
        )
        .order_by("-created_at")
    )


def get_approval_statistics(business_account):
    approvals = _get_dashboard_approvals_queryset(business_account)

    pending_approvals = approvals.filter(status="pending").count()
    approved_approvals = approvals.filter(status="approved").count()
    rejected_approvals = approvals.filter(status="rejected").count()

    approved_spend = Decimal("0")
    for approval in approvals.filter(status="approved"):
        approved_spend += _approval_total_amount(approval)

    now = timezone.now()
    last_30_days = now - timedelta(days=30)
    previous_30_days = now - timedelta(days=60)

    pending_recent = approvals.filter(status="pending", created_at__gte=last_30_days).count()
    pending_previous = approvals.filter(
        status="pending",
        created_at__gte=previous_30_days,
        created_at__lt=last_30_days,
    ).count()
    approved_recent = approvals.filter(status="approved", created_at__gte=last_30_days).count()
    approved_previous = approvals.filter(
        status="approved",
        created_at__gte=previous_30_days,
        created_at__lt=last_30_days,
    ).count()
    rejected_recent = approvals.filter(status="rejected", created_at__gte=last_30_days).count()
    rejected_previous = approvals.filter(
        status="rejected",
        created_at__gte=previous_30_days,
        created_at__lt=last_30_days,
    ).count()

    approved_recent_spend = Decimal("0")
    for approval in approvals.filter(status="approved", decision_date__gte=last_30_days):
        approved_recent_spend += _approval_total_amount(approval)

    approved_previous_spend = Decimal("0")
    for approval in approvals.filter(
        status="approved",
        decision_date__gte=previous_30_days,
        decision_date__lt=last_30_days,
    ):
        approved_previous_spend += _approval_total_amount(approval)

    decisions_count = approved_approvals + rejected_approvals

    return {
        "recent_approvals": approvals[:8],
        "pending_approvals": pending_approvals,
        "approved_approvals": approved_approvals,
        "rejected_approvals": rejected_approvals,
        "approved_spend": approved_spend,
        "pending_trend": _format_trend(pending_recent, pending_previous),
        "approved_trend": _format_trend(approved_recent, approved_previous),
        "rejected_trend": _format_trend(rejected_recent, rejected_previous),
        "spend_trend": _format_trend(float(approved_recent_spend), float(approved_previous_spend)),
        "approval_success_rate": round((approved_approvals / decisions_count) * 100, 1) if decisions_count else 0,
    }


def get_monthly_spend(business_account):
    approvals = _get_dashboard_approvals_queryset(business_account)
    now = timezone.now()
    six_months_ago = now - timedelta(days=180)

    monthly_map = {}
    for approval in approvals.filter(created_at__gte=six_months_ago):
        month_key = approval.created_at.strftime("%Y-%m")
        if month_key not in monthly_map:
            monthly_map[month_key] = {
                "month_key": month_key,
                "month_label": approval.created_at.strftime("%b %Y"),
                "approved_count": 0,
                "pending_count": 0,
                "spend": Decimal("0"),
            }

        entry = monthly_map[month_key]
        if approval.status == "approved":
            entry["approved_count"] += 1
            entry["spend"] += _approval_total_amount(approval)
        elif approval.status == "pending":
            entry["pending_count"] += 1

    monthly_summary = [monthly_map[key] for key in sorted(monthly_map.keys())]
    max_monthly_spend = max((entry["spend"] for entry in monthly_summary), default=Decimal("0"))

    for entry in monthly_summary:
        if max_monthly_spend > 0:
            entry["spend_percent"] = round(float((entry["spend"] / max_monthly_spend) * 100), 1)
        else:
            entry["spend_percent"] = 0

    return monthly_summary


def get_destination_summary(business_account):
    approvals = _get_dashboard_approvals_queryset(business_account)
    destination_summary = {}

    for approval in approvals.filter(status="approved"):
        city, country = _approval_destination(approval)
        if not city:
            continue

        key = (city, country)
        if key not in destination_summary:
            destination_summary[key] = {
                "city": city,
                "country": country,
                "count": 0,
                "total_amount": Decimal("0"),
            }

        destination_summary[key]["count"] += 1
        destination_summary[key]["total_amount"] += _approval_total_amount(approval)

    return sorted(
        destination_summary.values(),
        key=lambda item: (item["count"], item["total_amount"]),
        reverse=True,
    )[:5]


def get_dashboard_metrics(business_account):
    departments = (
        BusinessDepartment.objects.filter(business_account=business_account, is_active=True)
        .annotate(employee_count=Count("employees", filter=Q(employees__is_active=True)))
    )
    employees = (
        BusinessEmployee.objects.filter(business_account=business_account, is_active=True)
        .select_related("user", "department")[:12]
    )
    recent_expenses = (
        BusinessExpenseReport.objects.filter(business_account=business_account)
        .select_related("employee__user")
        .order_by("-submitted_at")[:5]
    )

    try:
        policy = BusinessTravelPolicy.objects.get(business_account=business_account)
    except BusinessTravelPolicy.DoesNotExist:
        policy = None

    total_employees = BusinessEmployee.objects.filter(
        business_account=business_account,
        is_active=True,
    ).count()
    active_travelers = (
        BusinessEmployee.objects.filter(business_account=business_account, is_active=True)
        .filter(Q(booking_approvals__isnull=False))
        .distinct()
        .count()
    )

    return {
        "departments": departments[:6],
        "employees": employees,
        "recent_expenses": recent_expenses,
        "policy": policy,
        "total_employees": total_employees,
        "active_travelers": active_travelers,
    }
