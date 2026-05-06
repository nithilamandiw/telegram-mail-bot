"""
Telegraph integration for publishing full HTML emails.

Uses Telegram's Telegraph API (telegra.ph) to create instant-view pages
for HTML emails. No domain or web server required — pages open directly
in Telegram's built-in browser.
"""

import json
import logging
import re
from html import escape as html_escape, unescape
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

# Allowed attributes per tag
ALLOWED_ATTRS = {"href", "src"}


class TelegraphHTMLParser(HTMLParser):
    """
    Parse HTML into Telegraph Node format.

    Telegraph nodes are either:
    - A plain string (text node)
    - A dict with "tag", optional "attrs", optional "children"
    """

    # Map unsupported tags to supported equivalents
    TAG_MAP = {
        "h1": "h3", "h2": "h3", "h5": "h4", "h6": "h4",
        "div": "p", "section": "p", "article": "p",
        "span": None,  # unwrap (keep children)
        "font": None,
        "center": None,
        "td": "p", "th": "p",
        "table": None, "tr": None, "thead": None,
        "tbody": None, "tfoot": None, "colgroup": None, "col": None,
        "nobr": None, "abbr": None, "small": None, "big": None,
        "sub": None, "sup": None, "label": None, "form": None,
        "input": None, "button": None, "select": None, "textarea": None,
        "nav": None, "header": None, "footer": None, "main": None,
        "dl": "ul", "dt": "li", "dd": "li",
    }

    # Tags whose entire content should be skipped
    SKIP_TAGS = {"head", "style", "script", "noscript", "meta", "link", "title"}

    def __init__(self):
        super().__init__()
        self.nodes = []       # Final top-level nodes
        self._stack = []      # Stack of (tag, node_dict) for nesting
        self._skip_depth = 0  # Depth inside a skipped tag

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()

        # Handle skip tags
        if tag in self.SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth > 0:
            self._skip_depth += 1
            return

        # Self-closing tags
        if tag == "br":
            self._add_node({"tag": "br"})
            return
        if tag == "hr":
            self._add_node({"tag": "hr"})
            return
        if tag == "img":
            attrs_dict = dict(attrs)
            src = attrs_dict.get("src", "")
            if src and src.startswith("http"):
                self._add_node({
                    "tag": "img",
                    "attrs": {"src": src},
                })
            return

        # Map unsupported tags
        mapped = self.TAG_MAP.get(tag, tag)

        if mapped is None:
            # Unwrap: treat as transparent (children go to parent)
            self._stack.append((tag, None))
            return

        if mapped not in SUPPORTED_TAGS:
            # Unknown tag — unwrap
            self._stack.append((tag, None))
            return

        # Build node
        node = {"tag": mapped}

        # Filter attributes
        attrs_dict = dict(attrs)
        filtered_attrs = {}
        if mapped == "a" and "href" in attrs_dict:
            href = attrs_dict["href"]
            if href and not href.startswith("javascript:"):
                filtered_attrs["href"] = href
        if "src" in attrs_dict:
            filtered_attrs["src"] = attrs_dict["src"]
        if filtered_attrs:
            node["attrs"] = filtered_attrs

        node["children"] = []
        self._stack.append((tag, node))

    def handle_endtag(self, tag):
        tag = tag.lower()

        if self._skip_depth > 0:
            self._skip_depth -= 1
            return

        if tag in self.SKIP_TAGS:
            return

        # Find matching tag on stack
        if not self._stack:
            return

        # Pop until we find our tag
        found_idx = None
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i][0] == tag:
                found_idx = i
                break

        if found_idx is None:
            return

        # Pop everything from found_idx to end
        popped = self._stack[found_idx:]
        self._stack = self._stack[:found_idx]

        # The first popped item is our matching tag
        orig_tag, node = popped[0]

        if node is not None:
            # Clean empty children
            if not node.get("children"):
                if node["tag"] not in ("br", "hr", "img"):
                    return  # Skip empty block elements
                node.pop("children", None)
            else:
                # Flatten single-text children
                node["children"] = self._clean_children(node["children"])
                if not node["children"]:
                    node.pop("children", None)

            self._add_node(node)

        # Any remaining popped transparent nodes — their children float up
        for _, child_node in popped[1:]:
            if child_node and child_node.get("children"):
                for child in child_node["children"]:
                    self._add_node(child)

    def handle_data(self, data):
        if self._skip_depth > 0:
            return

        # Clean whitespace but preserve meaningful text
        text = data
        if text:
            self._add_node(text)

    def _add_node(self, node):
        """Add a node to the current parent or top-level list."""
        if self._stack:
            # Find the nearest non-transparent parent
            for i in range(len(self._stack) - 1, -1, -1):
                _, parent_node = self._stack[i]
                if parent_node is not None:
                    if "children" not in parent_node:
                        parent_node["children"] = []
                    parent_node["children"].append(node)
                    return
        # Top level
        self.nodes.append(node)

    def _clean_children(self, children):
        """Remove empty strings and merge adjacent text nodes."""
        cleaned = []
        for child in children:
            if isinstance(child, str):
                if child.strip() or cleaned:  # Keep whitespace between elements
                    cleaned.append(child)
            else:
                cleaned.append(child)
        return cleaned

    def get_nodes(self):
        """Return the final list of Telegraph nodes."""
        return self._wrap_in_blocks(self.nodes)

    def _wrap_in_blocks(self, nodes):
        """Ensure top-level nodes are block elements (Telegraph requirement)."""
        result = []
        pending_inline = []

        for node in nodes:
            if isinstance(node, str):
                text = node.strip()
                if text:
                    pending_inline.append(node)
            elif isinstance(node, dict):
                tag = node.get("tag", "")
                if tag in ("p", "h3", "h4", "blockquote", "figure", "ul", "ol", "pre", "hr"):
                    # Flush inline
                    if pending_inline:
                        result.append({"tag": "p", "children": pending_inline})
                        pending_inline = []
                    result.append(node)
                else:
                    pending_inline.append(node)

        if pending_inline:
            result.append({"tag": "p", "children": pending_inline})

        return result if result else [{"tag": "p", "children": ["(No content)"]}]


def html_to_telegraph_nodes(html_text: str) -> list:
    """Convert HTML email to Telegraph Node array."""
    if not html_text:
        return [{"tag": "p", "children": ["(No content)"]}]

    # Pre-clean: remove comments
    html_text = re.sub(r"<!--.*?-->", "", html_text, flags=re.DOTALL)

    parser = TelegraphHTMLParser()
    try:
        parser.feed(html_text)
    except Exception:
        logger.exception("Failed to parse HTML for Telegraph")
        return [{"tag": "p", "children": ["(Failed to parse email content)"]}]

    return parser.get_nodes()


def text_to_telegraph_nodes(plain_text: str) -> list:
    """Convert plain text to Telegraph Node array."""
    if not plain_text:
        return [{"tag": "p", "children": ["(No content)"]}]

    paragraphs = plain_text.split("\n\n")
    nodes = []
    for para in paragraphs:
        text = para.strip()
        if text:
            # Convert single newlines to <br>
            parts = text.split("\n")
            children = []
            for i, part in enumerate(parts):
                if i > 0:
                    children.append({"tag": "br"})
                children.append(part)
            nodes.append({"tag": "p", "children": children})

    return nodes if nodes else [{"tag": "p", "children": ["(No content)"]}]


class TelegraphClient:
    """Async client for the Telegraph API."""

    def __init__(self):
        self.access_token = None
        self._session = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def create_account(self, short_name: str = "CrystalMailGateway") -> str:
        """Create a Telegraph account and return the access token."""
        session = await self._get_session()
        async with session.post(
            f"{TELEGRAPH_API}/createAccount",
            json={
                "short_name": short_name,
                "author_name": "Crystal MailGateway",
            },
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            data = await resp.json()
            if data.get("ok"):
                self.access_token = data["result"]["access_token"]
                logger.info("Telegraph account created")
                return self.access_token
            else:
                raise RuntimeError(f"Failed to create Telegraph account: {data}")

    async def ensure_account(self, stored_token: str | None = None) -> None:
        """Ensure we have a valid Telegraph access token."""
        if stored_token:
            self.access_token = stored_token
            return

        if not self.access_token:
            await self.create_account()

    async def create_page(
        self,
        title: str,
        content_nodes: list,
        author_name: str = "Crystal MailGateway",
    ) -> str | None:
        """
        Create a Telegraph page with the given Node content.
        Returns the page URL, or None on failure.
        """
        if not self.access_token:
            await self.ensure_account()

        session = await self._get_session()

        try:
            # Telegraph expects content as a JSON-encoded string
            content_json = json.dumps(content_nodes)

            # Use form-data POST (more reliable for large content)
            async with session.post(
                f"{TELEGRAPH_API}/createPage",
                data={
                    "access_token": self.access_token,
                    "title": (title or "Email")[:256],
                    "author_name": author_name,
                    "content": content_json,
                    "return_content": "false",
                },
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                data = await resp.json()
                if data.get("ok"):
                    url = data["result"]["url"]
                    logger.info("Telegraph page created: %s", url)
                    return url
                else:
                    logger.error("Telegraph createPage failed: %s", data)
                    return None
        except Exception:
            logger.exception("Failed to create Telegraph page")
            return None

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()


async def publish_email_to_telegraph(
    client: TelegraphClient,
    subject: str,
    from_addr: str,
    to_email: str,
    date: str,
    body_html: str | None,
    body_text: str | None,
) -> str | None:
    """
    Publish an email to Telegraph and return the page URL.

    Builds a nicely formatted Telegraph page with email header + body.
    """
    # Build the header nodes
    header_nodes = [
        {
            "tag": "p",
            "children": [
                {"tag": "strong", "children": ["From: "]},
                from_addr,
                {"tag": "br"},
                {"tag": "strong", "children": ["To: "]},
                to_email,
                {"tag": "br"},
                {"tag": "strong", "children": ["Date: "]},
                date,
            ],
        },
        {"tag": "hr"},
    ]

    # Convert body to Telegraph nodes
    if body_html:
        body_nodes = html_to_telegraph_nodes(body_html)
    elif body_text:
        body_nodes = text_to_telegraph_nodes(body_text)
    else:
        body_nodes = [{"tag": "p", "children": ["(No content)"]}]

    all_nodes = header_nodes + body_nodes

    # Telegraph has ~64KB content limit — truncate if needed
    content_json = json.dumps(all_nodes)
    if len(content_json) > 60000:
        # Truncate body nodes and add notice
        truncated = header_nodes + body_nodes[:10] + [
            {"tag": "p", "children": [
                {"tag": "em", "children": ["… [content truncated due to length]"]}
            ]}
        ]
        all_nodes = truncated

    title = subject or "(No subject)"

    return await client.create_page(
        title=title,
        content_nodes=all_nodes,
    )
