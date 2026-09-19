"""Tests for YAML and HTML metadata handling."""

from __future__ import annotations

import json

import pytest
from markdown_this import add_front_matter, extract_html_metadata, extract_structured_article, split_front_matter


@pytest.mark.parametrize("types", [["Thing", "NewsArticle"], ["NewsArticle", "Thing"]])
def test_nested_multityped_article(types: list[str]) -> None:
    data = {"@type": "WebPage", "mainEntity": [{"@type": types, "articleBody": "Nested article body."}]}
    html = f'<script type="application/ld+json">{json.dumps(data)}</script>'
    assert extract_structured_article(html) == ("Nested article body.", {"type": "NewsArticle"})


def test_front_matter_round_trip() -> None:
    markdown = add_front_matter(
        "Body",
        {
            "title": "An article",
            "author": "Author",
            "url": "https://example.com/article",
            "date": "2026-08-06",
            "image": "https://example.com/image.jpg",
        },
    )

    metadata, body = split_front_matter(markdown)
    assert metadata == {
        "title": "An article",
        "author": "Author",
        "url": "https://example.com/article",
        "date": "2026-08-06",
        "image": "https://example.com/image.jpg",
    }
    assert body == "Body"


def test_front_matter_ignores_unknown_and_nested_values() -> None:
    metadata, body = split_front_matter("---\ntitle: Title\nunknown: ignored\nextra:\n  value: ignored\n---\n\nBody")
    assert metadata == {"title": "Title"}
    assert body == "Body"


def test_front_matter_returns_original_markdown_when_invalid() -> None:
    markdown = "---\ntitle: Title\n"
    assert split_front_matter(markdown) == ({}, markdown)
    assert split_front_matter("---\n- one\n---\n\nBody") == ({}, "---\n- one\n---\n\nBody")
    invalid_yaml = "---\ntitle: [invalid\n---\n\nBody"
    assert split_front_matter(invalid_yaml) == ({}, invalid_yaml)
    assert add_front_matter("Body", {}) == "Body"


def test_extract_html_metadata_reads_meta_tags_and_canonical_url() -> None:
    html = """
    <link rel="canonical" href="https://example.com/canonical">
    <meta name="author" content="Author">
    <meta property="article:published_time" content="2026-08-06">
    """
    assert extract_html_metadata(html) == {
        "author": "Author",
        "url": "https://example.com/canonical",
        "date": "2026-08-06",
    }


def test_extract_html_metadata_reads_open_graph_and_time_fallback() -> None:
    html = (
        '<meta property="og:url" content="https://example.com">'
        '<meta property="og:image" content="/images/hero.jpg">'
        '<time datetime="2026-08-05">Yesterday</time>'
    )
    assert extract_html_metadata(html, "https://example.com/article") == {
        "url": "https://example.com",
        "date": "2026-08-05",
        "image": "https://example.com/images/hero.jpg",
    }


def test_extract_html_metadata_reads_page_type() -> None:
    html = '<meta property="og:type" content="website">'

    assert extract_html_metadata(html) == {"type": "website"}


def test_extract_html_metadata_reads_json_ld_page_type() -> None:
    html = '<script type="application/ld+json">[1, {"pagetype": "home"}]</script>'

    assert extract_html_metadata(html) == {"type": "home"}


def test_extract_html_metadata_ignores_invalid_json_ld() -> None:
    html = '<script type="application/ld+json">not json</script>'

    assert extract_html_metadata(html) == {}


def test_extract_html_metadata_uses_site_name_when_author_is_missing() -> None:
    html = '<meta name="author" content=""><meta property="og:site_name" content="Página|12">'

    assert extract_html_metadata(html) == {"author": "Página|12"}


def test_extract_html_metadata_returns_empty_for_missing_values() -> None:
    assert extract_html_metadata("<html></html>") == {}


def test_extract_structured_article_reads_article_body_and_metadata() -> None:
    html = """
    <script type="application/ld+json">
    {
      "@type": ["NewsArticle", "Thing"],
      "headline": "Schema title",
      "articleBody": "Schema body.",
      "author": [{"name": "One"}, {"name": "Two"}],
      "datePublished": "2026-08-06",
      "image": {"url": "/hero.jpg"}
    }
    </script>
    """

    assert extract_structured_article(html, "https://example.com/article") == (
        "Schema body.",
        {
            "title": "Schema title",
            "author": "One, Two",
            "date": "2026-08-06",
            "image": "https://example.com/hero.jpg",
            "type": "NewsArticle",
        },
    )


def test_extract_structured_article_reads_string_author() -> None:
    html = """
    <script type="application/ld+json">
      {"@type": "Article", "headline": "Title", "articleBody": "Body.", "author": "Plain Author"}
    </script>
    """

    assert extract_structured_article(html) == (
        "Body.",
        {"title": "Title", "author": "Plain Author", "type": "Article"},
    )


def test_extract_structured_article_reads_graph_and_social_text() -> None:
    html = """
    <script type="application/ld+json">
    {
      "@context": "https://schema.org",
      "@graph": [
        {"@type": "WebPage", "name": "Ignored"},
        {
          "@type": "SocialMediaPosting",
          "name": "Thread title",
          "text": ["First post.", "Second post."],
          "publisher": {"name": "Example social"},
          "image": ["ftp://invalid/image.jpg", "https://example.com/thread.jpg"]
        }
      ]
    }
    </script>
    """

    assert extract_structured_article(html) == (
        "First post.\n\nSecond post.",
        {
            "title": "Thread title",
            "publisher": "Example social",
            "image": "https://example.com/thread.jpg",
            "type": "SocialMediaPosting",
        },
    )


def test_extract_structured_article_ignores_invalid_or_unusable_json_ld() -> None:
    assert extract_structured_article('<script type="application/ld+json">not json</script>') is None
    assert extract_structured_article('<script type="application/ld+json">{"@type":"NewsArticle"}</script>') is None
    assert (
        extract_structured_article(
            '<script type="application/ld+json">{"@type":"ImageObject","text":"Ignored"}</script>'
        )
        is None
    )
