"""
Lightweight SMTP server for receiving emails.

Uses aiosmtpd to listen on port 25 (or configured port). When an email
arrives, it parses the message and forwards it to the corresponding
Telegram chat via the Bot API.
"""

import email
import logging
import re
from email import policy
from html import unescape

import aiohttp
from aiosmtpd.controller import Controller
from aiosmtpd.smtp import SMTP, Envelope, Session

from database import Database

logger = logging.getLogger(__name__)

MAX_TELEGRAM_LENGTH = 4096


def strip_html(html_text: str) -> str:
    """Remove HTML tags and decode entities to plain text."""
    text = re.sub(r"<br\s*/?>", "\n", html_text, flags=re.IGNORECASE)
    text = re.sub(r"<p[^>]*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</p>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = unescape(text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_body(msg):
    """Extract plain-text body, falling back to stripped HTML."""
    body = None
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            disp = str(part.get("Content-Disposition", ""))
            if "attachment" in disp:
                continue
            if ctype == "text/plain" and body is None:
                payload = part.get_payload(decode=True)
                if payload:
                    body = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
                    break
            elif ctype == "text/html" and body is None:
                payload = part.get_payload(decode=True)
                if payload:
                    body = strip_html(payload.decode(part.get_content_charset() or "utf-8", errors="replace"))
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            raw = payload.decode(msg.get_content_charset() or "utf-8", errors="replace")
            body = strip_html(raw) if msg.get_content_type() == "text/html" else raw
    return body or "(No body content)"


def extract_attachments(msg):
    """Return filenames of all attachments."""
    attachments = []
    if msg.is_multipart():
        for part in msg.walk():
            if "attachment" in str(part.get("Content-Disposition", "")):
                attachments.append(part.get_filename() or "unnamed")
    return attachments


def _escape_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class EmailHandler:
    """aiosmtpd handler — receives emails and forwards to Telegram."""

    def __init__(self, bot_token: str, db: Database):
        self.bot_token = bot_token
        self.db = db
        self.telegram_api = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    async def handle_RCPT(self, server, session, envelope, address, rcpt_options):
        normalized = address.lower().strip()
        record = self.db.get_email(normalized)
        if record is None:
            domain = normalized.split("@")[-1] if "@" in normalized else ""
            if domain not in self.db.get_all_verified_domains():
                logger.info("Rejected %s — not registered", normalized)
                return "550 User not found"
        envelope.rcpt_tos.append(address)
        return "250 OK"

    async def handle_DATA(self, server, session, envelope):
        logger.info("Email from=%s to=%s", envelope.mail_from, envelope.rcpt_tos)

        msg = email.message_from_bytes(envelope.content, policy=policy.default)
        sender = msg.get("From", envelope.mail_from or "Unknown")
        subject = msg.get("Subject", "(No subject)")
        date = msg.get("Date", "Unknown date")
        body = extract_body(msg)
        attachments = extract_attachments(msg)

        for rcpt in envelope.rcpt_tos:
            to_email = rcpt.lower().strip()
            record = self.db.get_email(to_email)
            if not record:
                logger.warning("No DB record for %s", to_email)
                continue

            chat_id = record["chat_id"]
            header = (
                "📧 <b>New Email</b>\n\n"
                f"<b>From:</b> {_escape_html(sender)}\n"
                f"<b>To:</b> {_escape_html(to_email)}\n"
                f"<b>Subject:</b> {_escape_html(subject)}\n"
                f"<b>Date:</b> {_escape_html(date)}\n\n"
                + "─" * 30 + "\n\n"
            )
            att_text = ""
            if attachments:
                names = ", ".join(_escape_html(a) for a in attachments)
                att_text = f"\n\n📎 <b>Attachments:</b> {names}"

            avail = MAX_TELEGRAM_LENGTH - len(header) - len(att_text) - 20
            escaped = _escape_html(body)
            if len(escaped) > avail:
                escaped = escaped[: avail - 15] + "\n\n… [truncated]"

            message = header + escaped + att_text
            await self._send_telegram(chat_id, message)

        return "250 Message accepted for delivery"

    async def _send_telegram(self, chat_id, text):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.telegram_api,
                    json={"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status != 200:
                        logger.error("Telegram API %s: %s", resp.status, await resp.text())
                    else:
                        logger.info("Forwarded to chat_id=%s", chat_id)
        except Exception:
            logger.exception("Failed to send to chat_id=%s", chat_id)


def start_smtp_server(bot_token, db, host="0.0.0.0", port=25):
    """Start SMTP server in background thread. Returns Controller."""
    handler = EmailHandler(bot_token, db)
    controller = Controller(handler, hostname=host, port=port)
    controller.start()
    logger.info("SMTP server listening on %s:%d", host, port)
    return controller
