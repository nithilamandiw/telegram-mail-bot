"""
Telegraph integration for publishing full email content.

Uses Telegram's Telegraph API (telegra.ph) to create instant-view pages.
No domain or web server needed — pages open in Telegram's built-in browser.
"""

import json
import logging
import uuid
from html import escape as html_escape

import aiohttp

logger = logging.getLogger(__name__)

TELEGRAPH_API = "https://api.telegra.ph"


def text_to_nodes(plain_text: str) -> list:
    """Convert plain text to Telegraph Node array."""
    if not plain_text or not plain_text.strip():
        return [{"tag": "p", "children": ["(No content)"]}]

    nodes = []
    for para in plain_text.split("\n\n"):
        text = para.strip()
        if not text:
            continue
        # Convert single newlines within a paragraph to <br>
        parts = text.split("\n")
        children = []
        for i, part in enumerate(parts):
            if i > 0:
                children.append({"tag": "br"})
            children.append(part)
        nodes.append({"tag": "p", "children": children})

    return nodes or [{"tag": "p", "children": ["(No content)"]}]


class TelegraphClient:
    """Async client for the Telegraph API. Thread/loop safe."""

    def __init__(self):
        self.access_token = None

    async def _create_account(self) -> None:
        """Create a Telegraph account and store the access token."""
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{TELEGRAPH_API}/createAccount",
                json={
                    "short_name": "CrystalMail",
                    "author_name": "Crystal MailGateway",
                },
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                data = await resp.json()
                if data.get("ok"):
                    self.access_token = data["result"]["access_token"]
                    logger.info("Telegraph account created")
                else:
                    raise RuntimeError(f"Telegraph createAccount failed: {data}")

    async def ensure_account(self) -> None:
        """Ensure we have a valid access token."""
        if not self.access_token:
            await self._create_account()

    async def create_page(self, title: str, content_nodes: list) -> str | None:
        """Create a Telegraph page. Returns the URL, or None on failure."""
        if not self.access_token:
            await self.ensure_account()

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{TELEGRAPH_API}/createPage",
                    data={
                        "access_token": self.access_token,
                        "title": (title or "Email")[:256],
                        "author_name": "Crystal MailGateway",
                        "content": json.dumps(content_nodes),
                        "return_content": "false",
                    },
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    data = await resp.json()
                    if data.get("ok"):
                        url = data["result"]["url"]
                        logger.info("Telegraph page: %s", url)
                        return url
                    else:
                        logger.error("Telegraph createPage error: %s", data)
                        return None
        except Exception:
            logger.exception("Failed to create Telegraph page")
            return None


async def publish_email_to_telegraph(
    client: TelegraphClient,
    subject: str,
    from_addr: str,
    to_email: str,
    date: str,
    body_text: str,
) -> str | None:
    """Publish an email to Telegraph and return the page URL."""

    # Use random UUID as page title so URL is unguessable
    random_title = uuid.uuid4().hex

    # Show real subject + metadata inside the page content
    header_nodes = [
        {"tag": "h3", "children": [subject or "(No subject)"]},
        {
            "tag": "p",
            "children": [
                {"tag": "strong", "children": ["From: "]}, from_addr,
                {"tag": "br"},
                {"tag": "strong", "children": ["To: "]}, to_email,
                {"tag": "br"},
                {"tag": "strong", "children": ["Date: "]}, date,
            ],
        },
        {"tag": "hr"},
    ]

    body_nodes = text_to_nodes(body_text)
    all_nodes = header_nodes + body_nodes

    # Telegraph ~64KB limit
    content_json = json.dumps(all_nodes)
    if len(content_json) > 60000:
        all_nodes = header_nodes + body_nodes[:10] + [
            {"tag": "p", "children": [
                {"tag": "em", "children": ["… [truncated]"]}
            ]}
        ]

    return await client.create_page(
        title=random_title,
        content_nodes=all_nodes,
    )
