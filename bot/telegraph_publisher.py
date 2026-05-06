"""
Telegraph integration for publishing full email content.

Uses Telegram's Telegraph API (telegra.ph) to create instant-view pages.
No domain or web server needed — pages open in Telegram's built-in browser.
"""

import json
import logging
import re
import uuid

import aiohttp

logger = logging.getLogger(__name__)

TELEGRAPH_API = "https://api.telegra.ph"


def extract_images_from_html(html_text: str) -> list:
    """Extract image URLs from HTML email content."""
    if not html_text:
        return []

    images = []
    # Find all <img> tags with src attributes
    for match in re.finditer(r'<img[^>]+src=["\']([^"\']+)["\']', html_text, re.IGNORECASE):
        src = match.group(1)
        # Only include absolute HTTP URLs (skip data URIs, CID refs, etc.)
        if src.startswith("http"):
            # Skip tiny tracking pixels (1x1)
            width = re.search(r'width=["\']?(\d+)', match.group(0), re.IGNORECASE)
            height = re.search(r'height=["\']?(\d+)', match.group(0), re.IGNORECASE)
            if width and height:
                w, h = int(width.group(1)), int(height.group(1))
                if w <= 3 and h <= 3:
                    continue  # Skip tracking pixels
            images.append(src)

    return images


def text_to_nodes(plain_text: str) -> list:
    """Convert plain text to Telegraph Node array."""
    if not plain_text or not plain_text.strip():
        return [{"tag": "p", "children": ["(No content)"]}]

    nodes = []
    for para in plain_text.split("\n\n"):
        text = para.strip()
        if not text:
            continue
        parts = text.split("\n")
        children = []
        for i, part in enumerate(parts):
            if i > 0:
                children.append({"tag": "br"})
            children.append(part)
        nodes.append({"tag": "p", "children": children})

    return nodes or [{"tag": "p", "children": ["(No content)"]}]


def images_to_nodes(image_urls: list) -> list:
    """Convert image URLs to Telegraph figure nodes."""
    nodes = []
    for url in image_urls:
        nodes.append({
            "tag": "figure",
            "children": [
                {"tag": "img", "attrs": {"src": url}},
            ],
        })
    return nodes


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
    body_html: str | None = None,
) -> str | None:
    """Publish an email to Telegraph and return the page URL."""

    # Random title → unguessable URL
    random_title = uuid.uuid4().hex

    # Header with real subject
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

    # Text body
    body_nodes = text_to_nodes(body_text)

    # Extract images from HTML and add them
    image_nodes = []
    if body_html:
        image_urls = extract_images_from_html(body_html)
        if image_urls:
            image_nodes = images_to_nodes(image_urls)

    all_nodes = header_nodes + image_nodes + body_nodes

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
