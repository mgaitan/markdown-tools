"""The main URL-to-Markdown extraction pipeline."""

from __future__ import annotations

import re
import urllib.parse
from collections.abc import Callable
from html import escape as html_escape
from logging import getLogger
from pathlib import Path

from bs4 import BeautifulSoup
from readability import Document

from markdown_this.fetchers import (
    DEFAULT_REQUEST_TIMEOUT,
    fetch_arxiv_abstract,
    fetch_github_blob_markdown,
    fetch_github_readme,
    fetch_html,
    fetch_media_oembed,
    fetch_youtube_video,
)
from markdown_this.html import convert_html
from markdown_this.markdown import (
    extract_intro,
    markdown_to_text,
)
from markdown_this.metadata import (
    add_front_matter,
    extract_html_metadata,
    extract_structured_article,
    split_front_matter,
)
from markdown_this.rules import apply_domain_rule
from markdown_this.structured import extract_fusion_article

logger = getLogger(__name__)
HTML_SOURCE_RE = re.compile(r"^\s*<(?:!doctype\s+html\b|html\b|article\b|body\b|main\b|section\b|div\b)", re.IGNORECASE)
SpecialUrlExtractor = Callable[[str, int], tuple[str, str] | None]

AD_NEGATIVE_KEYWORDS = re.compile(
    r"(?:^|[-_ ])(?:ad|ads|advert|advertising|advertisement|sponsor|sponsored|promo|infobox)(?:$|[-_ ])",
    re.IGNORECASE,
)
SPECIAL_URL_EXTRACTORS: tuple[SpecialUrlExtractor, ...] = (
    fetch_github_blob_markdown,
    fetch_github_readme,
    fetch_arxiv_abstract,
    fetch_media_oembed,
    fetch_youtube_video,
)


class ContentDownloadError(RuntimeError):
    """Raised when a content source cannot provide HTML content."""

    def __init__(self) -> None:
        super().__init__("Failed to download content")


def _finalize_content(
    title: str,
    markdown: str,
    fallback_text: str | None,
    intro_min_length: int,
    metadata: dict[str, str] | None = None,
) -> tuple[str, str, str, str]:
    """Normalize extracted Markdown and derive its fallback text and intro."""
    front_matter, content_markdown = split_front_matter(markdown.strip())
    resolved_title = front_matter.get("title") or title
    content_metadata = {**front_matter, **(metadata or {}), "title": resolved_title}
    content_fallback = fallback_text if fallback_text is not None else markdown_to_text(content_markdown)
    intro = extract_intro(content_markdown, content_fallback, intro_min_length)
    return resolved_title, add_front_matter(content_markdown, content_metadata), content_fallback, intro


def _is_http_url(source: str) -> bool:
    parsed = urllib.parse.urlparse(source)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def is_html_source(source: str) -> bool:
    """Return whether *source* starts with an HTML document or structural fragment."""
    return bool(HTML_SOURCE_RE.match(source))


def _existing_path(source: str) -> Path | None:
    if source.lstrip().startswith("<"):
        return None
    path = Path(source)
    return path if path.is_file() else None


def _extract_html_content(  # noqa: PLR0913
    content_html: str,
    source_label: str,
    base_url: str,
    source_url: str,
    min_content_length: int,
    intro_min_length: int,
) -> tuple[str, str, str, str]:
    if not content_html:
        raise ContentDownloadError

    metadata = extract_html_metadata(content_html, base_url)
    base_url = source_url or metadata.get("url") or base_url
    structured_article = extract_structured_article(content_html, base_url)
    if structured_article:
        _structured_text, structured_metadata = structured_article
        metadata = {**structured_metadata, **metadata}
    article = extract_fusion_article(content_html)
    rule_html = apply_domain_rule(content_html, base_url)
    if rule_html:
        metadata["extraction_scope"] = extract_html_metadata(rule_html).get("extraction_scope", "")
    content_html_for_markdown = ""
    title = source_label
    try:
        if article:
            title, content_html_for_markdown = article
            title = title or metadata.get("title") or source_label
        else:
            document = Document(content_html, negative_keywords=AD_NEGATIVE_KEYWORDS)
            content_html_for_markdown = rule_html or document.summary() or ""
            document_title = document.title()
            title = (
                document_title
                if document_title and document_title != "[no-title]"
                else metadata.get("title") or source_label
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("readability failed error=%s", exc)

    if (
        not article
        and not rule_html
        and (not content_html_for_markdown or len(content_html_for_markdown.strip()) < min_content_length)
    ):
        if structured_article:
            structured_text, structured_metadata = structured_article
            content_html_for_markdown = _html_for_structured_text(content_html, structured_text)
            title = structured_metadata.get("title") or title
        else:
            content_html_for_markdown = content_html

    content_html_for_markdown = content_html_for_markdown or content_html
    extracted_markdown, fallback_text = convert_html(content_html_for_markdown, base_url)
    if source_url:
        metadata["url"] = source_url
    return _finalize_content(title, extracted_markdown, fallback_text, intro_min_length, metadata)


def _html_for_structured_text(content_html: str, structured_text: str) -> str:
    soup = BeautifulSoup(content_html, "html.parser")
    needle = _compact_text(structured_text)
    candidates = []
    for tag in soup.find_all(["article", "main", "section", "div", "p"]):
        text = _compact_text(tag.get_text(" ", strip=True))
        if needle and needle in text:
            candidates.append((len(text), tag))
    if candidates:
        return str(min(candidates, key=lambda item: item[0])[1])

    paragraphs = [
        f"<p>{html_escape(part.strip())}</p>" for part in re.split(r"\n{2,}", structured_text) if part.strip()
    ]
    return "\n".join(paragraphs)


def _compact_text(text: str) -> str:
    return re.sub(r"\s+([.,;:!?])", r"\1", " ".join(text.split()))


def _extract_url_content(
    url: str,
    request_timeout: int,
    min_content_length: int,
    intro_min_length: int,
) -> tuple[str, str, str, str]:
    for special_extractor in SPECIAL_URL_EXTRACTORS:
        try:
            special_result = special_extractor(url, request_timeout)
        except Exception as exc:  # noqa: BLE001
            logger.warning("special URL extractor failed url=%s error=%s", url, exc)
            continue
        if special_result:
            title, markdown = special_result
            return _finalize_content(title, markdown, None, intro_min_length, {"url": url})

    downloaded = fetch_html(url, request_timeout)
    return _extract_html_content(downloaded or "", url, url, url, min_content_length, intro_min_length)


def extract_main_content(
    source: Path | str,
    request_timeout: int = DEFAULT_REQUEST_TIMEOUT,
    min_content_length: int = 200,
    intro_min_length: int = 40,
    *,
    source_url: str = "",
) -> tuple[str, str, str, str]:
    """Extract a URL, path or HTML; ``source_url`` resolves supplied HTML links."""
    if isinstance(source, str) and _is_http_url(source):
        return _extract_url_content(source, request_timeout, min_content_length, intro_min_length)

    path = source if isinstance(source, Path) else _existing_path(source)
    if path is not None:
        return _extract_html_content(
            path.read_text(encoding="utf-8"),
            path.stem,
            source_url or path.resolve().as_uri(),
            source_url,
            min_content_length,
            intro_min_length,
        )

    return _extract_html_content(source, "HTML content", source_url, source_url, min_content_length, intro_min_length)
