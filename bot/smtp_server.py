"""
Lightweight SMTP server for receiving emails.

Uses aiosmtpd to listen on port 25 (or configured port). When an email
arrives, it parses the message and forwards it to the corresponding
Telegram chat via the Bot API — including attachments as files/photos.
"""

import email
import io
import logging
import mimetypes
import re
import uuid
from email import policy
from html import unescape

import aiohttp
from aiosmtpd.controller import Controller
from aiosmtpd.smtp import SMTP, Envelope, Session

from database import Database

logger = logging.getLogger(__name__)

MAX_TELEGRAM_LENGTH = 4096
TELEGRAM_FILE_LIMIT = 50 * 1024 * 1024  # 50 MB


def strip_html(html_text: str) -> str:
    """Remove HTML tags and decode entities to plain text."""
    # Remove entire <head> section (contains meta, styles, scripts, etc.)
    text = re.sub(r"<head[\s>].*?</head>", "", html_text, flags=re.IGNORECASE | re.DOTALL)
    # Remove <style> blocks and their CSS content
    text = re.sub(r"<style[\s>].*?</style>", "", text, flags=re.IGNORECASE | re.DOTALL)
    # Remove <script> blocks
    text = re.sub(r"<script[\s>].*?</script>", "", text, flags=re.IGNORECASE | re.DOTALL)
    # Remove HTML comments (including conditional comments like <!--[if ...]>)
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    # Convert <br> to newlines
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    # Convert block-level elements to newlines for readability
    text = re.sub(r"<p[^>]*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</p>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<div[^>]*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</div>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"<tr[^>]*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<h[1-6][^>]*>", "\n\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</h[1-6]>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<li[^>]*>", "\n• ", text, flags=re.IGNORECASE)
    # Strip remaining HTML tags
    text = re.sub(r"<[^>]+>", "", text)
    # Decode HTML entities
    text = unescape(text)
    # Clean up excessive whitespace
    text = re.sub(r"[ \t]+", " ", text)           # collapse horizontal whitespace
    text = re.sub(r" *\n *", "\n", text)          # trim spaces around newlines
    text = re.sub(r"\n{3,}", "\n\n", text)        # max 2 consecutive newlines
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


def extract_html_body(msg):
    """Extract the raw HTML body (for web viewer), or None if not available."""
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            disp = str(part.get("Content-Disposition", ""))
            if "attachment" in disp:
                continue
            if ctype == "text/html":
                payload = part.get_payload(decode=True)
                if payload:
                    return payload.decode(part.get_content_charset() or "utf-8", errors="replace")
    else:
        if msg.get_content_type() == "text/html":
            payload = msg.get_payload(decode=True)
            if payload:
                return payload.decode(msg.get_content_charset() or "utf-8", errors="replace")
    return None


def extract_attachments(msg):
    """Return list of dicts with filename, data, and content_type for each attachment."""
    attachments = []
    if not msg.is_multipart():
        return attachments

    for part in msg.walk():
        disp = str(part.get("Content-Disposition", ""))
        ctype = part.get_content_type()

        # Skip text body parts
        if ctype in ("text/plain", "text/html") and "attachment" not in disp:
            continue

        # Pick up both inline images and explicit attachments
        if "attachment" in disp or "inline" in disp or ctype.startswith("image/"):
            payload = part.get_payload(decode=True)
            if not payload:
                continue

            filename = part.get_filename() or "unnamed"
            # Guess extension if missing
            if "." not in filename:
                ext = mimetypes.guess_extension(ctype) or ""
                filename += ext

            attachments.append({
                "filename": filename,
                "data": payload,
                "content_type": ctype,
                "size": len(payload),
            })

    return attachments


def _escape_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class EmailHandler:
    """aiosmtpd handler — receives emails and forwards to Telegram."""

    def __init__(self, bot_token: str, db: Database, telegraph_client=None):
        self.bot_token = bot_token
        self.db = db
        self.api_base = f"https://api.telegram.org/bot{bot_token}"
        self.telegraph_client = telegraph_client

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
        html_body = extract_html_body(msg)
        attachments = extract_attachments(msg)

        for rcpt in envelope.rcpt_tos:
            to_email = rcpt.lower().strip()
            record = self.db.get_email(to_email)
            if not record:
                logger.warning("No DB record for %s", to_email)
                continue

            chat_id = record["chat_id"]

            # Build the text message
            header = (
                "📧 <b>New Email</b>\n\n"
                f"<b>From:</b> {_escape_html(sender)}\n"
                f"<b>To:</b> {_escape_html(to_email)}\n"
                f"<b>Subject:</b> {_escape_html(subject)}\n"
                f"<b>Date:</b> {_escape_html(date)}\n\n"
                + "─" * 30 + "\n\n"
            )

            att_summary = ""
            if attachments:
                names = ", ".join(_escape_html(a["filename"]) for a in attachments)
                att_summary = f"\n\n📎 <b>{len(attachments)} attachment(s):</b> {names}"

            avail = MAX_TELEGRAM_LENGTH - len(header) - len(att_summary) - 20
            escaped = _escape_html(body)
            if len(escaped) > avail:
                escaped = escaped[: avail - 15] + "\n\n… [truncated]"

            message = header + escaped + att_summary

            # Save email to DB
            email_id = str(uuid.uuid4())
            try:
                self.db.save_email(
                    email_id=email_id,
                    chat_id=chat_id,
                    to_email=to_email,
                    from_addr=sender,
                    subject=subject,
                    date=date,
                    body_html=html_body,
                    body_text=body,
                )
            except Exception:
                logger.exception("Failed to save email to DB")

            # Publish to Telegraph for full HTML view
            reply_markup = None
            if self.telegraph_client and body:
                try:
                    from telegraph_publisher import publish_email_to_telegraph
                    telegraph_url = await publish_email_to_telegraph(
                        client=self.telegraph_client,
                        subject=subject,
                        from_addr=sender,
                        to_email=to_email,
                        date=date,
                        body_text=body,
                    )
                    if telegraph_url:
                        reply_markup = {
                            "inline_keyboard": [
                                [{"text": "🌐 View Full Email", "url": telegraph_url}]
                            ]
                        }
                except Exception:
                    logger.exception("Failed to publish to Telegraph")

            # Send the text message
            await self._send_message(chat_id, message, reply_markup=reply_markup)

            # Send each attachment
            for att in attachments:
                if att["size"] > TELEGRAM_FILE_LIMIT:
                    await self._send_message(
                        chat_id,
                        f"⚠️ Attachment <code>{_escape_html(att['filename'])}</code> "
                        f"is too large ({att['size'] // (1024*1024)} MB) — skipped."
                    )
                    continue

                await self._send_attachment(chat_id, att)

        return "250 Message accepted for delivery"

    async def _send_message(self, chat_id: str, text: str, reply_markup: dict | None = None) -> None:
        """Send a text message to Telegram."""
        try:
            payload = {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            }
            if reply_markup:
                payload["reply_markup"] = reply_markup

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.api_base}/sendMessage",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status != 200:
                        logger.error("Telegram sendMessage %s: %s", resp.status, await resp.text())
                    else:
                        logger.info("Sent text to chat_id=%s", chat_id)
        except Exception:
            logger.exception("Failed to send text to chat_id=%s", chat_id)

    async def _send_attachment(self, chat_id: str, att: dict) -> None:
        """Send an attachment as a photo (images) or document (everything else)."""
        filename = att["filename"]
        data = att["data"]
        content_type = att["content_type"]

        is_image = content_type.startswith("image/") and content_type != "image/svg+xml"

        try:
            async with aiohttp.ClientSession() as session:
                form = aiohttp.FormData()
                form.add_field("chat_id", chat_id)

                if is_image:
                    # Send as photo for better preview
                    form.add_field(
                        "photo",
                        io.BytesIO(data),
                        filename=filename,
                        content_type=content_type,
                    )
                    form.add_field("caption", f"📎 {filename}")
                    endpoint = f"{self.api_base}/sendPhoto"
                else:
                    # Send as document
                    form.add_field(
                        "document",
                        io.BytesIO(data),
                        filename=filename,
                        content_type=content_type,
                    )
                    form.add_field("caption", f"📎 {filename}")
                    endpoint = f"{self.api_base}/sendDocument"

                async with session.post(
                    endpoint,
                    data=form,
                    timeout=aiohttp.ClientTimeout(total=60),
                ) as resp:
                    if resp.status != 200:
                        logger.error(
                            "Telegram send attachment %s: %s",
                            resp.status, await resp.text(),
                        )
                    else:
                        logger.info("Sent attachment %s to chat_id=%s", filename, chat_id)

        except Exception:
            logger.exception("Failed to send attachment %s to chat_id=%s", filename, chat_id)


def start_smtp_server(bot_token, db, host="0.0.0.0", port=25, telegraph_client=None):
    """Start SMTP server in background thread. Returns Controller."""
    handler = EmailHandler(bot_token, db, telegraph_client=telegraph_client)
    controller = Controller(handler, hostname=host, port=port)
    controller.start()
    logger.info("SMTP server listening on %s:%d", host, port)
    return controller

