"""Notification providers (Phase 3.3).

One narrow abstraction — ``send(user, subject, body)`` — with three
implementations:

- :class:`LogNotificationProvider` — the default; logs the message and
  reports success. Used whenever no real channel is configured, so plan
  reminders degrade gracefully instead of crashing a request.
- :class:`SmtpNotificationProvider` — real e-mail through the same SMTP
  settings the magic-link mailer uses (``SMTP_HOST`` / ``SMTP_PORT`` /
  ``SMTP_USER`` / ``SMTP_PASSWORD`` / ``SMTP_FROM`` environment variables).
- :class:`WhatsAppNotificationProvider` — a documented stub. It raises
  :class:`NotImplementedError` on purpose: WhatsApp delivery needs
  owner-provided credentials and template approval, neither of which exists
  yet. Do not "finish" it by inventing an integration.
"""

from __future__ import annotations

import logging
import os
import smtplib
import ssl
from abc import ABC, abstractmethod
from dataclasses import dataclass
from email.message import EmailMessage

logger = logging.getLogger("career_guidance.notifications")


@dataclass(frozen=True)
class SmtpConfig:
    host: str
    port: int = 587
    user: str = ""
    password: str = ""
    sender: str = "no-reply@localhost"

    @property
    def enabled(self) -> bool:
        return bool(self.host)

    @classmethod
    def from_env(cls) -> SmtpConfig:
        """Same SMTP environment the auth magic-link mailer reads."""
        return cls(
            host=os.getenv("SMTP_HOST", ""),
            port=int(os.getenv("SMTP_PORT", "587")),
            user=os.getenv("SMTP_USER", ""),
            password=os.getenv("SMTP_PASSWORD", ""),
            sender=os.getenv("SMTP_FROM", os.getenv("SMTP_USER", "no-reply@localhost")),
        )


class NotificationProvider(ABC):
    """A channel that can deliver one message to one user."""

    name = "base"

    @abstractmethod
    def send(self, user: dict, subject: str, body: str) -> bool:
        """Deliver ``body`` to ``user`` (needs an ``email`` key).

        Returns True when the message was handed to the channel.
        """


class LogNotificationProvider(NotificationProvider):
    """Default provider: logs only. Never pretends a message was delivered."""

    name = "log"

    def send(self, user: dict, subject: str, body: str) -> bool:
        logger.info(
            "notification (log-only) to=%s subject=%r body=%r",
            user.get("email", "?"),
            subject,
            body[:200],
        )
        return True


class SmtpNotificationProvider(NotificationProvider):
    """E-mail via SMTP, mirroring ``backend.auth.Auth.send_magic_link``."""

    name = "smtp"

    def __init__(self, config: SmtpConfig | None = None) -> None:
        self.config = config or SmtpConfig.from_env()

    def send(self, user: dict, subject: str, body: str) -> bool:
        email = (user.get("email") or "").strip()
        if not email or not self.config.enabled:
            logger.warning("SMTP notification skipped (no address or SMTP not configured)")
            return False
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = self.config.sender
        msg["To"] = email
        msg.set_content(body)
        try:
            if self.config.port == 465:
                with smtplib.SMTP_SSL(
                    self.config.host, self.config.port, context=ssl.create_default_context()
                ) as srv:
                    if self.config.user:
                        srv.login(self.config.user, self.config.password)
                    srv.send_message(msg)
            else:
                with smtplib.SMTP(self.config.host, self.config.port, timeout=15) as srv:
                    srv.starttls(context=ssl.create_default_context())
                    if self.config.user:
                        srv.login(self.config.user, self.config.password)
                    srv.send_message(msg)
            return True
        except Exception:  # noqa: BLE001 - a failed reminder must not break callers
            logger.exception("SMTP notification failed")
            return False


class WhatsAppNotificationProvider(NotificationProvider):
    """Stub — needs owner-provided WhatsApp Business credentials and approved
    message templates before any real integration can be built. Calling
    :meth:`send` raises NotImplementedError by design."""

    name = "whatsapp"

    def send(self, user: dict, subject: str, body: str) -> bool:
        raise NotImplementedError(
            "WhatsApp delivery is not integrated: it requires owner-provided "
            "WhatsApp Business API credentials and template approval."
        )


def default_provider() -> NotificationProvider:
    """SMTP when configured, otherwise the log-only provider."""
    config = SmtpConfig.from_env()
    if config.enabled:
        return SmtpNotificationProvider(config)
    return LogNotificationProvider()


def send_plan_reminder(
    user: dict,
    week: dict,
    provider: NotificationProvider | None = None,
) -> bool:
    """Remind ``user`` about the current week of their 90-day plan.

    No-ops gracefully (returns False) when there is nothing to send, no
    usable provider, or delivery raises — reminders are best-effort and must
    never break the plan flow.

    Phase 5: a caller that knows the user is an unconsented minor passes
    ``minor_restricted=True`` in the user dict (from
    ``career_guidance.consent.restrictions_for``) — streak/plan nudges are
    then suppressed and nothing is sent.
    """
    if not user or not week:
        return False
    if user.get("minor_restricted"):
        logger.info("plan reminder suppressed for unconsented minor")
        return False
    provider = provider or default_provider()
    tasks = week.get("tasks", [])
    lines = [
        f"Week {week.get('week', '?')} of your 90-day plan focuses on {week.get('skill', 'your next skill')}.",  # noqa: E501
        "",
    ]
    lines += [f"- {task.get('title', 'Task')}" for task in tasks]
    check = week.get("verification_check")
    if check:
        lines += ["", check]
    subject = f"Your plan for week {week.get('week', '?')}: {week.get('skill', '')}".strip()
    try:
        return bool(provider.send(user, subject, "\n".join(lines)))
    except NotImplementedError:
        logger.warning("notification provider %s is not implemented yet", provider.name)
        return False
    except Exception:  # noqa: BLE001
        logger.exception("plan reminder failed")
        return False
