import html
import logging

import resend
from fastapi import APIRouter, HTTPException, Request, status
from resend.exceptions import ResendError
from starlette.concurrency import run_in_threadpool

from app.contact.schemas import ContactResponse, ContactSubmission
from app.core.config import get_settings
from app.middlewares.rate_limit import limiter

logger = logging.getLogger(__name__)
contact_router = APIRouter()


@contact_router.post(
    "",
    summary="Send a contact message",
    response_model=ContactResponse,
    status_code=status.HTTP_200_OK,
)
@limiter.limit("5/minute")
async def submit_contact_message(
    request: Request, submission: ContactSubmission
) -> ContactResponse:
    settings = get_settings()
    api_key = settings.RESEND_API_KEY
    from_email = settings.MAIL_FROM_RESEND
    to_email = settings.MAIL_USERNAME
    if not api_key or not from_email or not to_email:
        missing_settings = [
            setting
            for setting, value in (
                ("RESEND_API_KEY", api_key),
                ("MAIL_FROM_RESEND", from_email),
                ("MAIL_USERNAME", to_email),
            )
            if not value
        ]
        logger.error(
            "Contact email service is missing configuration: %s",
            ", ".join(missing_settings),
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Contact email service is not configured",
        )

    resend.api_key = api_key
    name = html.escape(submission.name)
    email = html.escape(str(submission.email))
    phone = html.escape(submission.phone or "Not provided")
    message = html.escape(submission.message)
    email_text = (
        f"Name: {submission.name}\n"
        f"Email: {submission.email}\n"
        f"Phone: {submission.phone or 'Not provided'}\n\n"
        f"Message:\n{submission.message}"
    )
    email_html = (
        f"<p><strong>Name:</strong> {name}</p>"
        f"<p><strong>Email:</strong> {email}</p>"
        f"<p><strong>Phone:</strong> {phone}</p>"
        f"<p><strong>Message:</strong></p>"
        f'<pre style="white-space: pre-wrap; font: inherit">{message}</pre>'
    )

    try:
        await run_in_threadpool(
            resend.Emails.send,
            {
                "from": from_email,
                "to": [to_email],
                "reply_to": str(submission.email),
                "subject": "New contact message from the Pillars FC website",
                "text": email_text,
                "html": email_html,
            },
        )
    except ResendError as error:
        logger.exception("Resend failed to send a contact message")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unable to send your message right now",
        ) from error

    return ContactResponse(
        status="success",
        message="Your message has been sent successfully.",
    )
