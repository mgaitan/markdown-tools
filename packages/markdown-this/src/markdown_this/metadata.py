"""YAML front matter and HTML metadata helpers."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any
from urllib.parse import urljoin, urlparse

import yaml
from bs4 import BeautifulSoup

METADATA_FIELDS = ("title", "author", "url", "date", "image", "type", "extraction_scope")
ARTICLE_SCHEMA_TYPES = {"article", "blogposting", "newsarticle", "socialmediaposting"}


def _json_ld_objects(soup: BeautifulSoup) -> list[Mapping[str, Any]]:
    objects: list[Mapping[str, Any]] = []

    def collect(value: object) -> None:
        if isinstance(value, Mapping):
            objects.append(value)
            for child in value.values():
                collect(child)
        elif isinstance(value, list):
            for item in value:
                collect(item)

    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            collect(json.loads(script.string or script.get_text()))
        except (TypeError, json.JSONDecodeError):
            continue
    return objects


def _schema_type(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        types = [item.strip() for item in value if isinstance(item, str) and item.strip()]
        return next((item for item in types if item.lower() in ARTICLE_SCHEMA_TYPES), next(iter(types), ""))
    return ""


def _schema_text(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return "\n\n".join(item.strip() for item in value if isinstance(item, str) and item.strip())
    return ""


def _schema_name(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, Mapping):
        return _schema_text(value.get("name"))
    if isinstance(value, list):
        return ", ".join(name for item in value if (name := _schema_name(item)))
    return ""


def _schema_image(value: object, base_url: str) -> str:
    if isinstance(value, str):
        image = value.strip()
    elif isinstance(value, Mapping):
        image = _schema_text(value.get("url"))
    elif isinstance(value, list):
        image = ""
        for item in value:
            if image := _schema_image(item, base_url):
                break
    else:
        image = ""
    image = urljoin(base_url, image) if image else ""
    parsed_image = urlparse(image)
    return image if parsed_image.scheme in {"http", "https"} and parsed_image.netloc else ""


def _extract_json_ld_page_type(soup: BeautifulSoup) -> str:
    for candidate in _json_ld_objects(soup):
        value = candidate.get("pagetype") or candidate.get("pageType")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def extract_structured_article(content_html: str, base_url: str = "") -> tuple[str, dict[str, str]] | None:
    """Extract schema.org article/social text and metadata from JSON-LD."""
    soup = BeautifulSoup(content_html, "html.parser")
    for candidate in _json_ld_objects(soup):
        page_type = _schema_type(candidate.get("@type"))
        if page_type.lower() not in ARTICLE_SCHEMA_TYPES:
            continue
        content = _schema_text(candidate.get("articleBody")) or _schema_text(candidate.get("text"))
        if not content:
            continue
        metadata = {
            field: value
            for field, value in (
                ("title", _schema_text(candidate.get("headline")) or _schema_text(candidate.get("name"))),
                ("author", _schema_name(candidate.get("author"))),
                ("publisher", _schema_name(candidate.get("publisher"))),
                ("date", _schema_text(candidate.get("datePublished"))),
                ("image", _schema_image(candidate.get("image"), base_url)),
                ("type", page_type),
            )
            if value
        }
        return content, metadata
    return None


def split_front_matter(markdown: str) -> tuple[dict[str, str], str]:
    """Return front matter metadata and the Markdown body."""
    lines = markdown.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, markdown

    try:
        end = lines.index("---", 1)
    except ValueError:
        return {}, markdown

    try:
        loaded = yaml.safe_load("\n".join(lines[1:end])) or {}
    except yaml.YAMLError:
        return {}, markdown
    if not isinstance(loaded, Mapping):
        return {}, markdown
    metadata = {
        field: str(value)
        for field in METADATA_FIELDS
        if (value := loaded.get(field)) is not None and not isinstance(value, (dict, list))
    }
    body = "\n".join(lines[end + 1 :]).lstrip("\n")
    return metadata, body


def add_front_matter(markdown: str, metadata: Mapping[str, str]) -> str:
    """Prepend non-empty metadata fields as YAML front matter."""
    fields = {field: metadata[field] for field in METADATA_FIELDS if metadata.get(field)}
    if not fields:
        return markdown
    header = yaml.safe_dump(fields, allow_unicode=True, sort_keys=False).strip()
    return f"---\n{header}\n---\n\n{markdown}" if markdown else f"---\n{header}\n---"


def extract_html_metadata(content_html: str, base_url: str = "") -> dict[str, str]:
    """Extract common document metadata, including the page type when declared."""
    soup = BeautifulSoup(content_html, "html.parser")

    def first_meta(*queries: dict[str, str]) -> str:
        for query in queries:
            tag = soup.find("meta", attrs=query)
            if tag and tag.get("content"):
                return str(tag["content"]).strip()
        return ""

    author = first_meta(
        {"name": "author"},
        {"property": "article:author"},
        {"name": "byline"},
        {"itemprop": "author"},
        {"property": "og:site_name"},
        {"name": "publisher"},
    )
    date = first_meta(
        {"property": "article:published_time"},
        {"name": "date"},
        {"itemprop": "datePublished"},
    )
    image = first_meta(
        {"property": "og:image"},
        {"property": "og:image:url"},
        {"name": "twitter:image"},
        {"property": "twitter:image"},
        {"itemprop": "image"},
    )
    image = urljoin(base_url, image) if image else ""
    parsed_image = urlparse(image)
    if parsed_image.scheme not in {"http", "https"} or not parsed_image.netloc:
        image = ""
    canonical = soup.find("link", rel=lambda value: value and "canonical" in value)
    url = str(canonical.get("href", "")).strip() if canonical else ""
    url = url or first_meta({"property": "og:url"})
    if not date:
        time_tag = soup.find("time", attrs={"datetime": True})
        date = str(time_tag["datetime"]).strip() if time_tag else ""
    page_type = first_meta({"property": "og:type"}, {"name": "pagetype"}, {"name": "page-type"})
    page_type = page_type or _extract_json_ld_page_type(soup)
    return {
        field: value
        for field, value in (
            ("author", author),
            ("url", url),
            ("date", date),
            ("image", image),
            ("type", page_type),
            ("extraction_scope", first_meta({"name": "extraction_scope"})),
        )
        if value
    }
