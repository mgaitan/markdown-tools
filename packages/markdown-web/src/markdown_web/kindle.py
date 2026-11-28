"""Send EPUBs using a short-lived Google access token provided by the sender."""

from __future__ import annotations

import re
from email.message import EmailMessage
from email.policy import SMTP

import requests

KINDLE_ADDRESS = re.compile(r"[a-z0-9][a-z0-9_.+-]{0,63}@(free\.)?kindle\.com", re.IGNORECASE | re.ASCII)
MAX_EPUB_EMAIL_BYTES = 24 * 1024 * 1024


class GmailAuthorizationError(ValueError):
    """The provided token does not identify an authorized sender."""

    def __init__(self) -> None:
        super().__init__("Authorize the configured Gmail sender to send this EPUB")


def verify_sender(token: str, sender: str) -> None:
    response = requests.get(
        "https://openidconnect.googleapis.com/v1/userinfo",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    if response.status_code in {401, 403}:
        raise GmailAuthorizationError
    response.raise_for_status()
    profile = response.json()
    if profile.get("email_verified") is not True or str(profile.get("email", "")).casefold() != sender.casefold():
        raise GmailAuthorizationError


def send_epub(token: str, sender: str, recipient: str, data: bytes, filename: str) -> None:
    message = EmailMessage(policy=SMTP)
    message["From"] = sender
    message["To"] = recipient
    message["Subject"] = filename.removesuffix(".epub")
    message.set_content("EPUB from Markdown Web.")
    message.add_attachment(data, maintype="application", subtype="epub+zip", filename=filename)
    response = requests.post(
        "https://gmail.googleapis.com/upload/gmail/v1/users/me/messages/send",
        params={"uploadType": "media"},
        headers={"Authorization": f"Bearer {token}", "Content-Type": "message/rfc822"},
        data=message.as_bytes(),
        timeout=60,
    )
    if response.status_code in {401, 403}:
        raise GmailAuthorizationError
    response.raise_for_status()
