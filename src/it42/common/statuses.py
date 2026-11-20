from django.db import models


class ApplicationStatus(models.TextChoices):
    """Application statuses, shared by every zone. ``submitted`` exists only in the core,
    before the org acknowledges the application. The three signing statuses are set only
    by the org itself (its handlers and expiry job) while the administrating organisation
    signs, never by staff."""

    SUBMITTED = "submitted", "Submitted"
    AWAITING_SIGNATURE = "awaiting_signature", "Awaiting signature"
    RO_DECLINED = "ro_declined", "Declined by organisation"
    RO_EXPIRED = "ro_expired", "Signature expired"
    RECEIVED = "received", "Received"
    UNDER_REVIEW = "under_review", "Under review"
    NEEDS_INFO = "needs_info", "Needs info"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"


# Room for the longest value ("awaiting_signature").
STATUS_MAX_LENGTH = 24

# Statuses an org's staff may set (via application.status_changed).
ORG_SETTABLE_STATUSES = (
    ApplicationStatus.UNDER_REVIEW,
    ApplicationStatus.NEEDS_INFO,
    ApplicationStatus.APPROVED,
    ApplicationStatus.REJECTED,
)

# How sign-off can end. Received/declined come directly from the RO zone; expired is
# emitted by the funding org that owns the deadline. Only valid while awaiting signature.
SIGNING_OUTCOMES = (
    ApplicationStatus.RECEIVED,
    ApplicationStatus.RO_DECLINED,
    ApplicationStatus.RO_EXPIRED,
)

# Not (yet) open for review: no status changes, questions or panel work.
NOT_REVIEWABLE = (
    ApplicationStatus.AWAITING_SIGNATURE,
    ApplicationStatus.RO_DECLINED,
    ApplicationStatus.RO_EXPIRED,
)

# Ended before review: the applicant may apply to the same grant again.
ENDED_BEFORE_REVIEW = (ApplicationStatus.RO_DECLINED, ApplicationStatus.RO_EXPIRED)

STATUS_BADGES = {
    ApplicationStatus.SUBMITTED: "secondary",
    ApplicationStatus.AWAITING_SIGNATURE: "warning",
    ApplicationStatus.RO_DECLINED: "danger",
    ApplicationStatus.RO_EXPIRED: "secondary",
    ApplicationStatus.RECEIVED: "info",
    ApplicationStatus.UNDER_REVIEW: "primary",
    ApplicationStatus.NEEDS_INFO: "warning",
    ApplicationStatus.APPROVED: "success",
    ApplicationStatus.REJECTED: "danger",
}
