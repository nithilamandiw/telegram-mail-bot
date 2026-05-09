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

# Timeout per MX host connection attempt (seconds)
MX_CONNECT_TIMEOUT = 15
# Max MX hosts to try before giving up
MAX_MX_ATTEMPTS = 2


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


def check_a_record(domain: str, expected_ip: str) -> dict:
    """
    Check if mail.<domain> has an A record pointing to the expected IP.
    Returns dict with 'exists' (bool) and 'value' (str or None).
    """
    hostname = f"mail.{domain}"
    try:
        answers = dns.resolver.resolve(hostname, "A")
        for rdata in answers:
            ip = str(rdata)
            if ip == expected_ip:
                return {"exists": True, "value": ip, "correct": True}
            return {"exists": True, "value": ip, "correct": False}
        return {"exists": False, "value": None, "correct": False}
    except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
        return {"exists": False, "value": None, "correct": False}
    except Exception as e:
        logger.warning("Failed to check A record for %s: %s", hostname, e)
        return {"exists": False, "value": None, "correct": False}


def check_mx_record(domain: str) -> dict:
    """
    Check if the domain has an MX record pointing to mail.<domain>.
    Returns dict with 'exists' (bool) and 'value' (str or None).
    """
    expected = f"mail.{domain}"
    try:
        answers = dns.resolver.resolve(domain, "MX")
        for rdata in answers:
            mx_host = str(rdata.exchange).rstrip(".")
            if mx_host.lower() == expected.lower():
                return {"exists": True, "value": mx_host, "correct": True}
        # MX exists but points elsewhere
        first = str(list(answers)[0].exchange).rstrip(".")
        return {"exists": True, "value": first, "correct": False}
    except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
        return {"exists": False, "value": None, "correct": False}
    except Exception as e:
        logger.warning("Failed to check MX for %s: %s", domain, e)
        return {"exists": False, "value": None, "correct": False}


def check_spf_record(domain: str) -> dict:
    """
    Check if the domain has an SPF record that authorizes this server.
    Returns dict with 'exists' (bool) and 'record' (str or None).
    """
    try:
        answers = dns.resolver.resolve(domain, "TXT")
        for rdata in answers:
            txt = rdata.to_text().strip('"')
            if txt.startswith("v=spf1"):
                return {"exists": True, "record": txt}
        return {"exists": False, "record": None}
    except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
        return {"exists": False, "record": None}
    except Exception as e:
        logger.warning("Failed to check SPF for %s: %s", domain, e)
        return {"exists": False, "record": None}


def check_dmarc_record(domain: str) -> bool:
    """Check if the domain has a DMARC record."""
    try:
        answers = dns.resolver.resolve(f"_dmarc.{domain}", "TXT")
        for rdata in answers:
            txt = rdata.to_text().strip('"')
            if "v=DMARC1" in txt:
                return True
        return False
    except Exception:
        return False


def check_verification_txt(domain: str, expected_token: str) -> dict:
    """
    Check if the domain has a TXT record matching the expected verification token.
    The token format is: crystal-verify=<hex>
    Returns dict with 'found' (bool) and 'token' (str or None).
    """
    if not expected_token:
        return {"found": False, "token": None}
    try:
        answers = dns.resolver.resolve(domain, "TXT")
        for rdata in answers:
            # Use raw bytes (rdata.strings) for reliable parsing —
            # rdata.to_text() can add quotes/escaping that break exact matches
            txt = b"".join(rdata.strings).decode("utf-8", errors="replace").strip()
            if expected_token.strip() in txt:
                return {"found": True, "token": txt}
        return {"found": False, "token": None}
    except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
        return {"found": False, "token": None}
    except Exception as e:
        logger.warning("Failed to check verification TXT for %s: %s", domain, e)
        return {"found": False, "token": None}


def check_all_dns(domain: str, server_ip: str, verification_token: str = "") -> dict:
    """
    Check all DNS records needed for full email functionality.
    Returns a detailed status dict for each record.
    """
    a = check_a_record(domain, server_ip)
    mx = check_mx_record(domain)
    spf = check_spf_record(domain)
    dmarc = check_dmarc_record(domain)
    verify_txt = check_verification_txt(domain, verification_token)

    return {
        "a_record": a,
        "mx_record": mx,
        "spf_record": spf,
        "dmarc_record": dmarc,
        "verify_txt": verify_txt,
        "receive_ready": a.get("correct", False) and mx.get("correct", False),
        "send_ready": spf["exists"] and dmarc,
        "verify_ready": verify_txt["found"],
        "all_ready": (
            a.get("correct", False) and mx.get("correct", False)
            and spf["exists"] and dmarc and verify_txt["found"]
        ),
    }




class EmailSender:
    """Send emails directly from the VPS to recipient mail servers."""

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

        # Try each MX host in priority order (limited attempts)
        last_error = None
        hosts_to_try = mx_hosts[:MAX_MX_ATTEMPTS]

        for mx_host in hosts_to_try:
            try:
                logger.info("Attempting delivery to %s via %s (timeout=%ds)", to_addr, mx_host, MX_CONNECT_TIMEOUT)

                await aiosmtplib.send(
                    msg,
                    hostname=mx_host,
                    port=25,
                    start_tls=True,
                    timeout=MX_CONNECT_TIMEOUT,
                )

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

            except (TimeoutError, OSError) as e:
                last_error = (
                    "Outbound port 25 appears to be blocked on this server. "
                    "Contact your VPS provider (e.g. AWS) to unblock SMTP outbound traffic."
                )
                logger.warning("Timeout/connection error with %s: %s", mx_host, e)
                # If port 25 is blocked, no point trying other MX hosts
                return {"success": False, "error": last_error}

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
