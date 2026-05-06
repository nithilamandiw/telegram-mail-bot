"""
Webmail Viewer — Lightweight web server for viewing full HTML emails.

Serves email content at /view/<uuid> with a styled dark-themed wrapper.
Uses aiohttp (already a project dependency) for the web server.
"""

import asyncio
import logging
import threading
from html import escape as html_escape

from aiohttp import web

from database import Database

logger = logging.getLogger(__name__)


VIEWER_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{subject} — Crystal MailGateway</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}

        body {{
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            background: #0a0e17;
            color: #e0e6f0;
            min-height: 100vh;
        }}

        .header {{
            background: linear-gradient(135deg, #0f1724 0%, #141d2f 100%);
            border-bottom: 1px solid rgba(56, 189, 248, 0.15);
            padding: 20px 0;
            position: sticky;
            top: 0;
            z-index: 100;
            backdrop-filter: blur(20px);
        }}

        .header-inner {{
            max-width: 960px;
            margin: 0 auto;
            padding: 0 24px;
        }}

        .brand {{
            display: flex;
            align-items: center;
            gap: 10px;
            margin-bottom: 20px;
        }}

        .brand-icon {{
            width: 32px;
            height: 32px;
            background: linear-gradient(135deg, #38bdf8, #818cf8);
            border-radius: 8px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 18px;
        }}

        .brand-name {{
            font-size: 16px;
            font-weight: 600;
            color: #94a3b8;
            letter-spacing: 0.5px;
        }}

        .meta-grid {{
            display: grid;
            grid-template-columns: auto 1fr;
            gap: 6px 16px;
            font-size: 14px;
        }}

        .meta-label {{
            color: #64748b;
            font-weight: 500;
        }}

        .meta-value {{
            color: #cbd5e1;
            word-break: break-word;
        }}

        .subject-line {{
            margin-top: 14px;
            padding-top: 14px;
            border-top: 1px solid rgba(100, 116, 139, 0.2);
            font-size: 18px;
            font-weight: 600;
            color: #f1f5f9;
        }}

        .email-frame-wrapper {{
            max-width: 960px;
            margin: 0 auto;
            padding: 24px;
        }}

        .email-frame {{
            background: #ffffff;
            border-radius: 12px;
            overflow: hidden;
            box-shadow:
                0 0 0 1px rgba(56, 189, 248, 0.1),
                0 20px 60px rgba(0, 0, 0, 0.5);
            min-height: 400px;
        }}

        .email-frame iframe {{
            width: 100%;
            min-height: 600px;
            border: none;
            display: block;
        }}

        .text-fallback {{
            padding: 32px;
            background: #ffffff;
            color: #1e293b;
            font-size: 15px;
            line-height: 1.7;
            white-space: pre-wrap;
            word-wrap: break-word;
            border-radius: 12px;
            box-shadow:
                0 0 0 1px rgba(56, 189, 248, 0.1),
                0 20px 60px rgba(0, 0, 0, 0.5);
        }}

        .footer {{
            text-align: center;
            padding: 24px;
            color: #475569;
            font-size: 13px;
        }}

        .footer a {{
            color: #38bdf8;
            text-decoration: none;
        }}

        @media (max-width: 640px) {{
            .header-inner, .email-frame-wrapper {{
                padding: 0 16px;
            }}
            .subject-line {{
                font-size: 16px;
            }}
            .meta-grid {{
                font-size: 13px;
            }}
        }}
    </style>
</head>
<body>
    <div class="header">
        <div class="header-inner">
            <div class="brand">
                <div class="brand-icon">📧</div>
                <div class="brand-name">Crystal MailGateway</div>
            </div>
            <div class="meta-grid">
                <span class="meta-label">From</span>
                <span class="meta-value">{from_addr}</span>
                <span class="meta-label">To</span>
                <span class="meta-value">{to_email}</span>
                <span class="meta-label">Date</span>
                <span class="meta-value">{date}</span>
            </div>
            <div class="subject-line">{subject}</div>
        </div>
    </div>

    <div class="email-frame-wrapper">
        {content_block}
    </div>

    <div class="footer">
        Crystal MailGateway &mdash; Powered by Telegram
    </div>

    <script>
        // Auto-resize iframe to fit content
        function resizeIframe() {{
            const iframe = document.getElementById('email-iframe');
            if (iframe) {{
                try {{
                    const h = iframe.contentWindow.document.body.scrollHeight;
                    iframe.style.height = Math.max(h + 40, 400) + 'px';
                }} catch(e) {{}}
            }}
        }}
    </script>
</body>
</html>"""


NOT_FOUND_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Email Not Found — Crystal MailGateway</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600&display=swap" rel="stylesheet">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Inter', sans-serif;
            background: #0a0e17;
            color: #e0e6f0;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .card {
            text-align: center;
            padding: 48px;
            background: linear-gradient(135deg, #0f1724, #141d2f);
            border: 1px solid rgba(56, 189, 248, 0.15);
            border-radius: 16px;
            max-width: 420px;
        }
        .icon { font-size: 48px; margin-bottom: 16px; }
        h1 { font-size: 22px; margin-bottom: 8px; color: #f1f5f9; }
        p { color: #94a3b8; font-size: 15px; line-height: 1.6; }
    </style>
</head>
<body>
    <div class="card">
        <div class="icon">📭</div>
        <h1>Email Not Found</h1>
        <p>This email may have expired or the link is invalid.</p>
    </div>
</body>
</html>"""


class WebMailServer:
    """Async web server for viewing full HTML emails."""

    def __init__(self, db: Database, host: str = "0.0.0.0", port: int = 8025):
        self.db = db
        self.host = host
        self.port = port
        self._runner = None

    async def _handle_view(self, request: web.Request) -> web.Response:
        """Render the full email viewer page."""
        email_id = request.match_info["email_id"]
        record = self.db.get_email_by_id(email_id)

        if not record:
            return web.Response(
                text=NOT_FOUND_HTML,
                content_type="text/html",
                status=404,
            )

        # Build the content block — iframe for HTML, pre-formatted for text
        if record["body_html"]:
            content_block = (
                '<div class="email-frame">'
                f'<iframe id="email-iframe" src="/raw/{email_id}" '
                f'sandbox="allow-same-origin" onload="resizeIframe()"></iframe>'
                '</div>'
            )
        elif record["body_text"]:
            content_block = f'<div class="text-fallback">{html_escape(record["body_text"])}</div>'
        else:
            content_block = '<div class="text-fallback">(No content)</div>'

        html = VIEWER_HTML.format(
            subject=html_escape(record["subject"]),
            from_addr=html_escape(record["from_addr"]),
            to_email=html_escape(record["to_email"]),
            date=html_escape(record["date"]),
            content_block=content_block,
        )

        return web.Response(text=html, content_type="text/html")

    async def _handle_raw(self, request: web.Request) -> web.Response:
        """Serve the raw HTML email content (for iframe src)."""
        email_id = request.match_info["email_id"]
        record = self.db.get_email_by_id(email_id)

        if not record or not record["body_html"]:
            return web.Response(text="Not found", status=404)

        return web.Response(
            text=record["body_html"],
            content_type="text/html",
        )

    async def _start(self):
        """Start the aiohttp web server."""
        app = web.Application()
        app.router.add_get("/view/{email_id}", self._handle_view)
        app.router.add_get("/raw/{email_id}", self._handle_raw)

        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self.host, self.port)
        await site.start()
        logger.info("Webmail server listening on %s:%d", self.host, self.port)

    async def _stop(self):
        if self._runner:
            await self._runner.cleanup()


def start_web_server(db: Database, host: str = "0.0.0.0", port: int = 8025):
    """Start the webmail server in a background thread with its own event loop."""
    server = WebMailServer(db, host, port)

    def _run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(server._start())
        loop.run_forever()

    thread = threading.Thread(target=_run, daemon=True, name="webmail-server")
    thread.start()
    logger.info("Webmail server thread started")
    return server
