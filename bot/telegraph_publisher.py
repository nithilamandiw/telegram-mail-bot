"""
Telegraph integration for publishing full HTML emails.

Uses Telegram's Telegraph API (telegra.ph) to create instant-view pages
for HTML emails. No domain or web server required — pages open directly
in Telegram's built-in browser.
"""

import json
import logging
import re
from html import escape as html_escape
from html.parser import HTMLParser

import aiohttp

logger = logging.getLogger(__name__)

TELEGRAPH_API = "https://api.telegra.ph"

# Tags supported by Telegraph
SUPPORTED_TAGS = {
    "a", "aside", "b", "blockquote", "br", "code", "em",
    "figcaption", "figure", "h3", "h4", "hr", "i", "iframe",
    "img", "li", "ol", "p", "pre", "s", "strong", "u", "ul",
    "video",
}


class TelegraphHTMLParser(HTMLParser):
    """Parse HTML into Telegraph Node format (list of dicts/strings)."""

    TAG_MAP = {
        "h1": "h3", "h2": "h3", "h5": "h4", "h6": "h4",
        "div": "p", "section": "p", "article": "p",
        "td": "p", "th": "p",
    }

    UNWRAP_TAGS = {
        "span", "font", "center", "nobr", "abbr", "small", "big",
        "sub", "sup", "label", "form", "input", "button", "select",
        "textarea", "nav", "header", "footer", "main", "table",
        "tr", "thead", "tbody", "tfoot", "colgroup", "col",
    }

    SKIP_TAGS = {"head", "style", "script", "noscript", "meta", "link", "title"}

    def __init__(self):
        super().__init__()
        self.nodes = []
        self._stack = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()

        if tag in self.SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth > 0:
            self._skip_depth += 1
            return

        if tag in ("br", "hr"):
            self._add_node({"tag": tag})
            return

        if tag == "img":
            src = dict(attrs).get("src", "")
            if src and src.startswith("http"):
                self._add_node({"tag": "img", "attrs": {"src": src}})
            return

        mapped = self.TAG_MAP.get(tag, tag)

        if tag in self.UNWRAP_TAGS or mapped not in SUPPORTED_TAGS:
            self._stack.append((tag, None))
            return

        node = {"tag": mapped, "children": []}
        a_dict = dict(attrs)
        if mapped == "a" and "href" in a_dict:
            href = a_dict["href"]
            if href and not href.startswith("javascript:"):
                node["attrs"] = {"href": href}
        self._stack.append((tag, node))

    def handle_endtag(self, tag):
        tag = tag.lower()
        if self._skip_depth > 0:
            self._skip_depth -= 1
            return
        if tag in self.SKIP_TAGS or not self._stack:
            return

        found = None
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i][0] == tag:
                found = i
                break
        if found is None:
            return

        popped = self._stack[found:]
        self._stack = self._stack[:found]
        _, node = popped[0]

        if node is not None:
            children = [c for c in node.get("children", [])
                        if not (isinstance(c, str) and not c.strip())]
            if children:
                node["children"] = children
            else:
                node.pop("children", None)
                if node["tag"] not in ("br", "hr", "img"):
                    return
            self._add_node(node)

        for _, child_node in popped[1:]:
            if child_node and child_node.get("children"):
                for child in child_node["children"]:
                    self._add_node(child)

    def handle_data(self, data):
        if self._skip_depth > 0:
            return
        if data:
            self._add_node(data)

    def _add_node(self, node):
        for i in range(len(self._stack) - 1, -1, -1):
            _, parent = self._stack[i]
            if parent is not None:
                parent.setdefault("children", []).append(node)
                return
        self.nodes.append(node)

    def get_nodes(self):
        result = []
        inline_buf = []
        for node in self.nodes:
            if isinstance(node, str):
                if node.strip():
                    inline_buf.append(node)
            elif isinstance(node, dict):
                tag = node.get("tag", "")
                if tag in ("p", "h3", "h4", "blockquote", "figure",
                           "ul", "ol", "pre", "hr"):
                    if inline_buf:
                        result.append({"tag": "p", "children": inline_buf})
                        inline_buf = []
                    result.append(node)
                else:
                    inline_buf.append(node)
        if inline_buf:
            result.append({"tag": "p", "children": inline_buf})
        return result or [{"tag": "p", "children": ["(No content)"]}]


def html_to_nodes(html_text: str) -> list:
    """Convert HTML email to Telegraph Node array."""
    if not html_text:
        return [{"tag": "p", "children": ["(No content)"]}]

    html_text = re.sub(r"<!--.*?-->", "", html_text, flags=re.DOTALL)
    parser = TelegraphHTMLParser()
    try:
        parser.feed(html_text)
    except Exception:
        logger.exception("Failed to parse HTML for Telegraph")
        return [{"tag": "p", "children": ["(Could not parse email)"]}]
    return parser.get_nodes()


def text_to_nodes(plain_text: str) -> list:
    """Convert plain text to Telegraph Node array."""
    if not plain_text:
        return [{"tag": "p", "children": ["(No content)"]}]

    nodes = []
    for para in plain_text.split("\n\n"):
        text = para.strip()
        if text:
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
    body_html: str | None,
    body_text: str | None,
) -> str | None:
    """Publish an email to Telegraph and return the page URL."""

    header_nodes = [
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

    body_nodes = html_to_nodes(body_html) if body_html else text_to_nodes(body_text)
    all_nodes = header_nodes + body_nodes

    # Telegraph ~64KB limit — truncate if needed
    if len(json.dumps(all_nodes)) > 60000:
        all_nodes = header_nodes + body_nodes[:10] + [
            {"tag": "p", "children": [
                {"tag": "em", "children": ["… [truncated]"]}
            ]}
        ]

    return await client.create_page(
        title=subject or "(No subject)",
        content_nodes=all_nodes,
    )
