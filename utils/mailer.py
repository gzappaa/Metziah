"""
Simple SMTP email sending, used by utils/promo_notifications.py.

Credentials come from config.py / .env -- never hardcoded.
"""

import logging
import smtplib
from email.mime.text import MIMEText

from config import settings

logger = logging.getLogger(__name__)


def send_email(subject: str, body: str) -> bool:
    """
    Sends a plain-text email using settings.SMTP_*.

    Returns True on success, False on failure (logs the exception).
    """

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = settings.EMAIL_FROM
    msg["To"] = settings.EMAIL_TO

    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
            server.starttls()
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.sendmail(
                settings.EMAIL_FROM,
                [settings.EMAIL_TO],
                msg.as_string(),
            )

        return True

    except Exception:
        logger.exception("Email failed for subject=%r", subject)
        return False