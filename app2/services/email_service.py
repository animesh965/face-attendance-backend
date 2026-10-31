import asyncio
import smtplib
from email.message import EmailMessage

from app.core.config import settings


def email_is_configured() -> bool:
    return all([
        settings.SMTP_HOST,
        settings.SMTP_FROM_EMAIL,
    ])


def _send_email_sync(to_email: str, subject: str, text_body: str, html_body: str | None = None):
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_FROM_EMAIL}>"
    message["To"] = to_email
    message.set_content(text_body)
    if html_body:
        message.add_alternative(html_body, subtype="html")

    if settings.SMTP_USE_TLS:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            if settings.SMTP_USERNAME:
                smtp.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
            smtp.send_message(message)
    else:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as smtp:
            if settings.SMTP_USERNAME:
                smtp.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
            smtp.send_message(message)


async def send_email(to_email: str, subject: str, text_body: str, html_body: str | None = None):
    # SMTP is blocking; keep it off the FastAPI event loop.
    await asyncio.to_thread(_send_email_sync, to_email, subject, text_body, html_body)


async def send_password_reset_email(to_email: str, reset_url: str, expires_minutes: int):
    subject = "Reset your attendance app password"
    text_body = (
        "We received a request to reset your attendance app password.\n\n"
        f"Open this link to choose a new password (expires in {expires_minutes} minutes):\n"
        f"{reset_url}\n\n"
        "If you did not request this, you can ignore this email."
    )
    html_body = (
        "<p>We received a request to reset your attendance app password.</p>"
        f'<p><a href="{reset_url}">Reset password</a></p>'
        f"<p>This link expires in {expires_minutes} minutes and can only be used once.</p>"
        "<p>If you did not request this, you can ignore this email.</p>"
    )
    await send_email(to_email, subject, text_body, html_body)
