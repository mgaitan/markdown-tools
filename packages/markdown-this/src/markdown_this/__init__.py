"""Convert web pages and supported special URLs to Markdown."""

from markdown_this.extractor import ContentDownloadError, extract_main_content, is_html_source
from markdown_this.fetchers import (
    _github_repo_match,
    fetch_arxiv_abstract,
    fetch_github_blob_markdown,
    fetch_github_readme,
    fetch_html,
    fetch_media_oembed,
    fetch_url,
    fetch_youtube_video,
)
from markdown_this.html import make_images_absolute, preprocess_figures, strip_chrome
from markdown_this.markdown import (
    _extract_leading_heading,
    _is_html_badge_block,
    _make_markdown_images_absolute,
    _make_markdown_links_absolute,
    _normalize_markdown_links,
    _strip_badge_paragraphs,
    extract_intro,
    markdown_to_text,
)
from markdown_this.metadata import (
    add_front_matter,
    extract_html_metadata,
    extract_structured_article,
    split_front_matter,
)
from markdown_this.rules import DomainRule, apply_domain_rule

__all__ = [
    "ContentDownloadError",
    "DomainRule",
    "_extract_leading_heading",
    "_github_repo_match",
    "_is_html_badge_block",
    "_make_markdown_images_absolute",
    "_make_markdown_links_absolute",
    "_normalize_markdown_links",
    "_strip_badge_paragraphs",
    "add_front_matter",
    "apply_domain_rule",
    "extract_html_metadata",
    "extract_intro",
    "extract_main_content",
    "extract_structured_article",
    "fetch_arxiv_abstract",
    "fetch_github_blob_markdown",
    "fetch_github_readme",
    "fetch_html",
    "fetch_media_oembed",
    "fetch_url",
    "fetch_youtube_video",
    "is_html_source",
    "make_images_absolute",
    "markdown_to_text",
    "preprocess_figures",
    "split_front_matter",
    "strip_chrome",
]
