"""Deliver branded transactional EmailMessage through HTTPS Resend API, not blocked SMTP ports."""
import logging
import os
from email.message import EmailMessage
from email.utils import parseaddr

import httpx


def api_configured() -> bool:
    return bool(os.getenv("RESEND_API_KEY") and os.getenv("SMTP_FROM"))


def send_message(message: EmailMessage) -> None:
    key = os.getenv("RESEND_API_KEY", "").strip()
    if not key:
        raise RuntimeError("Resend HTTPS API key missing")
    sender = str(message.get("From", ""))
    recipient = parseaddr(str(message.get("To", "")))[1]
    if not sender or not recipient or "\n" in recipient or "\r" in recipient:
        raise ValueError("Invalid email metadata")
    body = message.get_body(preferencelist=("plain",))
    html = message.get_body(preferencelist=("html",))
    payload = {
        "from": sender,
        "to": [recipient],
        "subject": str(message.get("Subject", "")),
        "text": body.get_content() if body else "",
    }
    if html is not None:
        payload["html"] = html.get_content()
    try:
        with httpx.Client(timeout=15.0, follow_redirects=False) as client:
            response = client.post(
                "https://api.resend.com/emails",
                headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
                json=payload,
            )
        if response.status_code < 200 or response.status_code >= 300:
            logging.warning("Resend transactional email rejected: HTTP %s", response.status_code)
            raise RuntimeError("Email delivery provider rejected request")
    except httpx.HTTPError as exc:
        logging.warning("Resend transactional email HTTPS transport failed: %s", type(exc).__name__)
        raise RuntimeError("Email delivery transport failed") from exc
