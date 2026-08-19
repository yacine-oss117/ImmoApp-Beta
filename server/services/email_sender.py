"""Durable outbound email sender backed by EmailOutbox."""

from __future__ import annotations

import logging
from datetime import timedelta
from smtplib import SMTPRecipientsRefused

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.utils import timezone

from server.accounts.models import EmailOutbox

logger = logging.getLogger(__name__)
_STATUS_SENDING = "sending"


def queue_email(*, to: str, subject: str, body_text: str, body_html: str = "") -> None:
    """Write outbound email to the persistent outbox queue."""
    EmailOutbox.objects.create(
        to_email=to.strip(),
        subject=subject,
        body_text=body_text,
        body_html=body_html,
    )


def _send_one(outbox_row: EmailOutbox) -> bool:
    """Attempt to send one queued message. Returns True on success."""
    try:
        # Sender identity is centralized by deployment policy in DEFAULT_FROM_EMAIL.
        message = EmailMultiAlternatives(
            subject=outbox_row.subject,
            body=outbox_row.body_text,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[outbox_row.to_email],
        )
        if outbox_row.body_html.strip():
            message.attach_alternative(outbox_row.body_html, "text/html")
        message.send(fail_silently=False)
        return True
    except SMTPRecipientsRefused as exc:
        outbox_row.status = EmailOutbox.STATUS_FAILED_PERMANENT
        outbox_row.error_message = str(exc)[:1000]
        outbox_row.last_attempt_at = timezone.now()
        outbox_row.attempts = int(outbox_row.attempts or 0) + 1
        outbox_row.save(update_fields=["status", "error_message", "last_attempt_at", "attempts"])
        logger.warning(
            "Email permanently failed: to=%s subject=%s reason=%s",
            outbox_row.to_email,
            outbox_row.subject,
            outbox_row.error_message[:200],
        )
        return False
    except Exception as exc:
        outbox_row.status = EmailOutbox.STATUS_PENDING
        outbox_row.error_message = str(exc)[:1000]
        outbox_row.last_attempt_at = timezone.now()
        outbox_row.attempts = int(outbox_row.attempts or 0) + 1
        outbox_row.save(update_fields=["status", "error_message", "last_attempt_at", "attempts"])
        return False


def flush_outbox(
    *,
    max_age_hours: int = 48,
    cleanup_days: int = 30,
    claim_ttl_seconds: int = 600,
) -> dict[str, int]:
    """
    Process pending outbox rows in short claim transactions.

    Claim rows with SKIP LOCKED, release quickly, then send each row independently.
    If processing crashes mid-run, untouched rows remain pending for next cycle.
    """
    now = timezone.now()
    cutoff = now - timedelta(hours=max(1, int(max_age_hours)))
    expired = EmailOutbox.objects.filter(
        status=EmailOutbox.STATUS_PENDING,
        created_at__lt=cutoff,
    ).update(
        status=EmailOutbox.STATUS_FAILED_PERMANENT,
        error_message="Expired after max retry window",
    )
    if expired:
        logger.warning("Email permanently failed: expired pending rows=%s", int(expired))

    stale_claim_cutoff = now - timedelta(seconds=max(60, int(claim_ttl_seconds)))
    reclaimed = EmailOutbox.objects.filter(
        status=_STATUS_SENDING,
        last_attempt_at__lt=stale_claim_cutoff,
    ).update(
        status=EmailOutbox.STATUS_PENDING,
        error_message="Delivery claim expired; retrying.",
    )
    if reclaimed:
        logger.warning("Email outbox recovered stale delivery claims=%s", int(reclaimed))

    with transaction.atomic():
        pending_rows = list(
            EmailOutbox.objects.select_for_update(skip_locked=True)
            .filter(
                status=EmailOutbox.STATUS_PENDING,
                created_at__gte=cutoff,
            )
            .order_by("created_at")
            .values("id")[:50]
        )
        pending_ids = [row["id"] for row in pending_rows]
        if pending_ids:
            EmailOutbox.objects.filter(
                id__in=pending_ids,
                status=EmailOutbox.STATUS_PENDING,
            ).update(
                status=_STATUS_SENDING,
                last_attempt_at=now,
            )

    sent = 0
    failed = 0
    for outbox_id in pending_ids:
        row = EmailOutbox.objects.filter(
            id=outbox_id,
            status=_STATUS_SENDING,
        ).first()
        if row is None:
            continue
        if _send_one(row):
            completed_at = timezone.now()
            row.status = EmailOutbox.STATUS_SENT
            row.sent_at = completed_at
            row.last_attempt_at = completed_at
            row.attempts = int(row.attempts or 0) + 1
            row.save(update_fields=["status", "sent_at", "last_attempt_at", "attempts"])
            sent += 1
        else:
            failed += 1

    cleanup_cutoff = now - timedelta(days=max(1, int(cleanup_days)))
    cleaned, _ = EmailOutbox.objects.filter(
        status__in=(EmailOutbox.STATUS_SENT, EmailOutbox.STATUS_FAILED_PERMANENT),
        created_at__lt=cleanup_cutoff,
    ).delete()

    return {
        "sent": int(sent),
        "failed": int(failed),
        "expired": int(expired),
        "reclaimed": int(reclaimed),
        "cleaned": int(cleaned),
    }


def send_platform_email(*, to: str, subject: str, body_text: str, body_html: str = "") -> bool:
    """Queue email for delivery via durable outbox."""
    if not to.strip():
        return False
    try:
        queue_email(to=to, subject=subject, body_text=body_text, body_html=body_html)
        return True
    except Exception:
        logger.warning("Failed to queue email", exc_info=True)
        return False


__all__ = ["flush_outbox", "queue_email", "send_platform_email"]
