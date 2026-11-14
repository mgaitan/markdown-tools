"""Parse embedded article formats independently of a site's hostname."""

from __future__ import annotations

import json
import re
from html import escape
from typing import Any

from bs4 import BeautifulSoup


def extract_fusion_article(html: str) -> tuple[str, str] | None:
    """Return title and HTML from Arc Fusion's shared article format."""
    for script in BeautifulSoup(html, "html.parser").find_all("script"):
        source = script.get_text()
        assignment = re.search(r"\bFusion\.globalContent\s*=\s*", source)
        if not assignment:
            continue
        try:
            data, _end = json.JSONDecoder().raw_decode(source[assignment.end() :])
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict) or not isinstance(data.get("content_elements"), list):
            continue
        parts = [_fusion_element_html(element) for element in data["content_elements"] if isinstance(element, dict)]
        body = "\n".join(part for part in parts if part)
        if body:
            headlines = data.get("headlines")
            title = str(headlines.get("basic") or "") if isinstance(headlines, dict) else ""
            return title, body
    return None


def _fusion_element_html(element: dict[str, Any]) -> str:
    content = str(element.get("content") or "")
    match element.get("type"):
        case "text":
            return f"<p>{content}</p>" if content.strip() else ""
        case "header":
            if len(BeautifulSoup(content, "html.parser").get_text(" ", strip=True)) > 120:
                return f"<p>{content}</p>"
            level = str(element.get("level"))
            level = level if level in {"2", "3", "4", "5", "6"} else "2"
            return f"<h{level}>{content}</h{level}>" if content.strip() else ""
        case "image":
            properties = element.get("additional_properties")
            original = properties.get("originalUrl") if isinstance(properties, dict) else ""
            src = escape(str(element.get("url") or original or ""))
            if not src:
                return ""
            alt = BeautifulSoup(str(element.get("alt_text") or ""), "html.parser").get_text(" ", strip=True)
            caption = str(element.get("caption") or "")
            return f'<figure><img src="{src}" alt="{escape(alt)}"><figcaption>{caption}</figcaption></figure>'
        case _:
            return ""
