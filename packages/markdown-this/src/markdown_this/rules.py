"""Small declarative extraction rules for high-value domains."""

from __future__ import annotations

import re
import urllib.parse
from collections.abc import Iterable
from dataclasses import dataclass
from itertools import groupby
from logging import getLogger

from bs4 import BeautifulSoup
from bs4.element import Tag
from soupsieve import SelectorSyntaxError, closest, match

logger = getLogger(__name__)


@dataclass(frozen=True)
class DomainRule:
    hosts: tuple[str, ...]
    body_selectors: tuple[str, ...]
    strip_selectors: tuple[str, ...] = ()
    item_selector: str = ""
    permalink_selector: str = "a:has(time)"
    boundary_selector: str = "h2"


DOMAIN_RULES: tuple[DomainRule, ...] = (
    DomainRule(
        hosts=("substack.com",),
        body_selectors=(".available-content",),
        strip_selectors=(".image-link-expand:not(:has(img))",),
    ),
    DomainRule(
        hosts=("x.com", "twitter.com"),
        body_selectors=('[data-testid="primaryColumn"]', "main"),
        item_selector="article",
        permalink_selector='a[href*="/status/"]',
        strip_selectors=('[role="group"]', '[data-testid="UserAvatar-Container"]', '[data-testid="caret"]'),
    ),
)


def _host_matches(host: str, candidates: tuple[str, ...]) -> bool:
    return any(host == candidate or host.endswith(f".{candidate}") for candidate in candidates)


def _target_from_url(url: str) -> str:
    parts = [part for part in urllib.parse.urlparse(url).path.split("/") if part]
    if "status" in parts and parts.index("status") + 1 < len(parts):
        return parts[parts.index("status") + 1]
    return parts[-1] if parts else ""


def apply_domain_rule(
    content_html: str,
    url: str,
    rules: Iterable[DomainRule] = DOMAIN_RULES,
) -> str | None:
    """Return selected HTML for a URL when a declarative rule matches."""
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    if not host:
        return None

    rule = next(
        (rule for rule in rules if _host_matches(host, rule.hosts)),
        None,
    )
    if rule is None:
        return None

    soup = BeautifulSoup(content_html, "html.parser")
    try:
        for selector in rule.body_selectors:
            body = soup.select_one(selector)
            if body is None:
                continue
            for strip in rule.strip_selectors:
                for element in body.select(strip):
                    element.decompose()
            if body.get_text(strip=True):
                return _collect_posts(body, rule, url) if rule.item_selector else str(body)
    except SelectorSyntaxError as exc:
        logger.warning("domain rule selector failed error=%s", exc)
    return None


def _collect_posts(body: Tag, rule: DomainRule, url: str) -> str | None:
    """Select the captured, contiguous author sequence around the requested post."""
    posts = {}
    for node in body.select(f"{rule.item_selector}, {rule.boundary_selector}"):
        if not match(rule.item_selector, node):
            if posts and closest(rule.item_selector, node) is None:
                break
            continue
        if closest(rule.item_selector, node.parent) is not None:
            continue
        link = node.select_one(rule.permalink_selector)
        if link is None:
            continue
        permalink = urllib.parse.urljoin(url, str(link.get("href") or ""))
        parsed = urllib.parse.urlparse(permalink)
        host = (parsed.hostname or "").removeprefix("www.").removeprefix("m.")
        if parsed.scheme not in {"http", "https"} or not _host_matches(host, rule.hosts):
            continue
        path = parsed.path.rstrip("/")
        author, _, post_id = path.rpartition("/")
        if post_id and post_id not in posts:
            posts[post_id] = (author, node)

    target = _target_from_url(url)
    for _author, group in groupby(posts.items(), key=lambda item: item[1][0]):
        captured = dict(group)
        if target in captured:
            parts = (
                [_x_post_html(node) for _author, node in captured.values()]
                if "x.com" in rule.hosts
                else [str(node) for _author, node in captured.values()]
            )
            # ponytail: a DOM snapshot cannot prove that unseen replies do not exist.
            return '<meta name="extraction_scope" content="captured-posts">' + "\n".join(part for part in parts if part)
    return None


def _x_post_html(node: Tag) -> str:
    """Keep an X post's written content and attached media, not its interface chrome."""
    text = node.select_one('[data-testid="tweetText"]') or node.select_one('div[dir="auto"]') or node.find("p")
    if text is None:
        return ""

    for link in text.select("a[href]"):
        visible = link.get_text(strip=True)
        parsed = urllib.parse.urlparse(urllib.parse.urljoin("https://x.com", str(link["href"])))
        host = (parsed.hostname or "").removeprefix("www.").removeprefix("m.")
        handle = parsed.path.strip("/")
        if (
            visible.startswith(("http://", "https://"))
            and _host_matches(host, ("x.com", "twitter.com"))
            and re.fullmatch(r"[A-Za-z0-9_]{1,15}", handle)
        ):
            link.string = f"@{handle}"

    parts = [str(text)]
    images = list(node.select('[data-testid="tweetPhoto"] img'))
    images.extend(image for link in node.select('a[href*="/status/"][href*="/photo/"]') if (image := link.find("img")))
    parts.extend(str(image) for image in dict.fromkeys(images))
    parts.extend(str(video) for video in node.find_all("video"))
    return "<section>" + "".join(parts) + "</section>"
