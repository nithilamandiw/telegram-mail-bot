"""
Outgoing Email Sender — Direct SMTP Delivery

Sends emails directly from the VPS by resolving the recipient's MX records
and connecting to their mail server. No third-party relay needed.
Users send from their own domain email addresses registered in the bot.
"""

import logging
import dns.resolver
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timezone

import aiosmtplib

logger = logging.getLogger(__name__)


def resolve_mx(domain: str) -> list[str]:
    """
    Resolve MX records for a domain and return hostnames sorted by priority.
    Falls back to the domain itself if no MX records found.
    """
    try:
        answers = dns.resolver.resolve(domain, "MX")
        mx_records = sorted(answers, key=lambda r: r.preference)
        hosts = [str(r.exchange).rstrip(".") for r in mx_records]
        logger.info("MX records for %s: %s", domain, hosts)
        return hosts
    except dns.resolver.NoAnswer:
        logger.warning("No MX records for %s, falling back to domain", domain)
        return [domain]
    except dns.resolver.NXDOMAIN:
        logger.error("Domain %s does not exist", domain)
        return []
    except Exception as e:
        logger.error("Failed to resolve MX for %s: %s", domain, e)
        return [domain]


class EmailSender:
    """Send emails directly from the VPS to recipient mail servers."""

    @property
    def is_configured(self) -> bool:
        """Direct sending is always available — no credentials needed."""
        return True

    async def send_email(
        self,
        from_addr: str,
        to_addr: str,
        subject: str,
        body: str,
        reply_to: str | None = None,
    ) -> dict:
        """
        Send an email by resolving the recipient's MX and delivering directly.

        Returns a dict with 'success' (bool) and 'error' (str or None).
        """
        # Extract recipient domain
        if "@" not in to_addr:
            return {"success": False, "error": "Invalid recipient address."}

        recipient_domain = to_addr.split("@")[1]

        # Resolve MX records
        mx_hosts = resolve_mx(recipient_domain)
        if not mx_hosts:
            return {
                "success": False,
                "error": f"Cannot resolve mail server for {recipient_domain}",
            }

        # Build the email message
        try:
            msg = MIMEMultipart("alternative")
            msg["From"] = from_addr
            msg["To"] = to_addr
            msg["Subject"] = subject
            msg["Date"] = datetime.now(timezone.utc).strftime(
                "%a, %d %b %Y %H:%M:%S +0000"
            )

            if reply_to:
                msg["Reply-To"] = reply_to

            # Add plain text body
            msg.attach(MIMEText(body, "plain", "utf-8"))

            # Also add an HTML version (basic formatting)
            html_body = (
                body.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace("\n", "<br>\n")
            )
            html_content = f"""\
<html>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; 
             font-size: 14px; line-height: 1.6; color: #333;">
{html_body}
</body>
</html>"""
            msg.attach(MIMEText(html_content, "html", "utf-8"))

        except Exception as e:
            logger.exception("Failed to build email message")
            return {"success": False, "error": f"Failed to build email: {e}"}

        # Try each MX host in priority order
        last_error = None
        for mx_host in mx_hosts:
            try:
                kwargs = {
                    "hostname": mx_host,
                    "port": 25,
                    "start_tls": True,
                }

                logger.info("Attempting delivery to %s via %s", to_addr, mx_host)

                await aiosmtplib.send(msg, **kwargs)

                logger.info(
                    "Email sent successfully: %s → %s (via %s)",
                    from_addr,
                    to_addr,
                    mx_host,
                )
                return {"success": True, "error": None}

            except aiosmtplib.SMTPResponseException as e:
                last_error = f"Rejected by {mx_host}: {e.code} {e.message}"
                logger.warning("MX %s rejected: %s %s", mx_host, e.code, e.message)
                # If the recipient is explicitly rejected, don't try other MX
                if e.code in (550, 551, 552, 553, 554):
                    return {"success": False, "error": last_error}
                continue

            except aiosmtplib.SMTPException as e:
                last_error = f"SMTP error with {mx_host}: {e}"
                logger.warning("SMTP error with %s: %s", mx_host, e)
                continue

            except Exception as e:
                last_error = f"Connection failed to {mx_host}: {e}"
                logger.warning("Failed to connect to %s: %s", mx_host, e)
                continue

        return {
            "success": False,
            "error": last_error or f"All MX servers for {recipient_domain} failed.",
        }
