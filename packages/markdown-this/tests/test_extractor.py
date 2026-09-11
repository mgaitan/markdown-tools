"""Tests for extracting content from multiple source types."""

from __future__ import annotations

import unittest.mock
from pathlib import Path

from markdown_this import extract_main_content, is_html_source, split_front_matter
from markdown_this import extractor as extractor_module
from pytest_mock import MockerFixture


def _document(*, mocker: MockerFixture) -> unittest.mock.Mock:
    return mocker.Mock(
        summary=mocker.Mock(return_value="<article><p>Readable body.</p></article>"),
        title=mocker.Mock(return_value="Readable title"),
    )


def test_is_html_source_recognizes_documents_and_structural_fragments() -> None:
    assert is_html_source("<!doctype html><html><body>Document</body></html>")
    assert is_html_source("  <article><p>Article</p></article>")
    assert is_html_source("<body>Body</body>")
    assert is_html_source("<main>Main</main>")
    assert is_html_source("<section>Section</section>")
    assert is_html_source("<div>Content</div>")
    assert not is_html_source("# Markdown\n\n<article>Embedded HTML</article>")
    assert not is_html_source("Text before <div>Embedded HTML</div>")


def test_extract_main_content_accepts_path_object(tmp_path: Path, *, mocker: MockerFixture) -> None:
    html_path = tmp_path / "article.html"
    html_path.write_text("<html><body>Source</body></html>", encoding="utf-8")
    mocker.patch.object(extractor_module, "Document", return_value=_document(mocker=mocker))
    title, markdown, fallback_text, intro = extract_main_content(html_path, min_content_length=0)

    assert title == "Readable title"
    metadata, body = split_front_matter(markdown)
    assert metadata == {"title": "Readable title"}
    assert body == "Readable body."
    assert fallback_text == "Readable body."
    assert intro == "Readable body."


def test_extract_main_content_accepts_path_string(tmp_path: Path, *, mocker: MockerFixture) -> None:
    html_path = tmp_path / "article.html"
    html_path.write_text("<html><body>Source</body></html>", encoding="utf-8")
    mocker.patch.object(extractor_module, "Document", return_value=_document(mocker=mocker))
    result = extract_main_content(str(html_path), min_content_length=0)

    assert result[0] == "Readable title"


def test_extract_main_content_accepts_raw_html(*, mocker: MockerFixture) -> None:
    mocker.patch.object(extractor_module, "Document", return_value=_document(mocker=mocker))
    result = extract_main_content("<html><body>Raw HTML</body></html>", min_content_length=0)

    metadata, body = split_front_matter(result[1])
    assert result[0] == "Readable title"
    assert metadata == {"title": "Readable title"}
    assert body == "Readable body."


def test_extract_main_content_emits_html_metadata(*, mocker: MockerFixture) -> None:
    html = (
        '<meta name="author" content="Author">'
        '<link rel="canonical" href="https://example.com/article">'
        '<meta property="article:published_time" content="2026-08-06">'
        '<meta property="og:image" content="https://cdn.example.com/hero.jpg">'
        "<p>Raw HTML</p>"
    )
    mocker.patch.object(extractor_module, "Document", return_value=_document(mocker=mocker))
    result = extract_main_content(html, min_content_length=0)

    metadata, _body = split_front_matter(result[1])
    assert metadata == {
        "title": "Readable title",
        "author": "Author",
        "url": "https://example.com/article",
        "date": "2026-08-06",
        "image": "https://cdn.example.com/hero.jpg",
    }


def test_extract_main_content_falls_back_when_special_url_extractor_fails(*, mocker: MockerFixture) -> None:
    broken_extractor = mocker.Mock(side_effect=RuntimeError("broken"))
    ignored_extractor = mocker.Mock(return_value=None)
    html = "<html><body><article><p>Fallback body.</p></article></body></html>"
    mocker.patch.object(extractor_module, "SPECIAL_URL_EXTRACTORS", (broken_extractor, ignored_extractor))
    mocker.patch.object(extractor_module, "fetch_html", return_value=html)
    mocker.patch.object(extractor_module, "Document", return_value=_document(mocker=mocker))
    title, markdown, fallback_text, intro = extract_main_content("https://example.com/article", min_content_length=0)

    assert title == "Readable title"
    assert "Readable body." in markdown
    assert fallback_text == "Readable body."
    assert intro == "Readable body."


def test_extract_main_content_uses_structured_article_when_readability_is_short(*, mocker: MockerFixture) -> None:
    html = """
    <html><head>
      <script type="application/ld+json">
        {
          "@type": "NewsArticle",
          "headline": "Schema title",
          "articleBody": "Schema body with linked source."
        }
      </script>
    </head><body>
      <article><p>Schema body with <a href="/source">linked source</a>.</p></article>
    </body></html>
    """
    document = mocker.Mock(
        summary=mocker.Mock(return_value="<p>Too short.</p>"),
        title=mocker.Mock(return_value=""),
    )
    mocker.patch.object(extractor_module, "Document", return_value=document)
    title, markdown, fallback_text, _intro = extract_main_content(
        html,
        min_content_length=50,
    )

    assert title == "Schema title"
    assert "[linked source](/source)" in markdown
    assert "Schema body with" in fallback_text
    assert "linked source" in fallback_text


def test_extract_main_content_uses_structured_text_when_no_dom_match_exists(*, mocker: MockerFixture) -> None:
    html = """
    <html><head>
      <script type="application/ld+json">
        {"@type": "Article", "headline": "Schema only", "articleBody": "First <line>\\n\\nSecond & line"}
      </script>
    </head><body><p>Chrome only.</p></body></html>
    """
    document = mocker.Mock(
        summary=mocker.Mock(return_value=""),
        title=mocker.Mock(return_value=""),
    )
    mocker.patch.object(extractor_module, "Document", return_value=document)
    title, markdown, fallback_text, _intro = extract_main_content(html)

    assert title == "Schema only"
    assert "First <line>" in markdown
    assert "Second & line" in markdown
    assert fallback_text == "First <line>\n\n\nSecond & line"


def test_extract_main_content_falls_back_to_original_html_when_structured_html_is_empty(
    *, mocker: MockerFixture
) -> None:
    html = """
    <html><head>
      <script type="application/ld+json">
        {"@type": "Article", "headline": "Schema only", "articleBody": "Structured body."}
      </script>
    </head><body><p>Original fallback body.</p></body></html>
    """
    document = mocker.Mock(
        summary=mocker.Mock(return_value=""),
        title=mocker.Mock(return_value=""),
    )
    mocker.patch.object(extractor_module, "Document", return_value=document)
    mocker.patch.object(extractor_module, "_html_for_structured_text", return_value="")
    title, markdown, fallback_text, _intro = extract_main_content(html)

    assert title == "Schema only"
    assert "Original fallback body." in markdown
    assert "Original fallback body." in fallback_text


def test_extract_main_content_does_not_replace_good_readability_with_schema(*, mocker: MockerFixture) -> None:
    html = """
    <html><head>
      <script type="application/ld+json">
        {"@type": "Article", "headline": "Schema title", "articleBody": "Schema body."}
      </script>
    </head><body><article><p>DOM body.</p></article></body></html>
    """
    document = mocker.Mock(
        summary=mocker.Mock(
            return_value="<article><p>Readable body long enough to keep as the selected content.</p></article>"
        ),
        title=mocker.Mock(return_value="Readable title"),
    )
    mocker.patch.object(extractor_module, "Document", return_value=document)
    title, markdown, _fallback_text, _intro = extract_main_content(html, min_content_length=20)

    assert title == "Readable title"
    assert "Readable body long enough" in markdown
    assert "Schema body" not in markdown


def test_extract_main_content_excludes_structural_ad_slots() -> None:
    html = """
    <html><head><title>Story</title></head><body><article>
      <p>Story text with enough content to be selected by readability.</p>
      <div class="c-ad advertising">
        <div class="c-ad__adzone"></div>
        <div class="c-ad__placeholder"><span>PUBLICIDAD</span></div>
      </div>
      <p>More story text after the ad.</p>
    </article></body></html>
    """

    _title, markdown, _fallback, _intro = extract_main_content(html, min_content_length=0)

    assert "Story text" in markdown
    assert "More story text" in markdown
    assert "PUBLICIDAD" not in markdown


def test_supplied_html_resolves_links_from_source_url() -> None:
    html = '<article><p>A reference to <a href="/other">another article</a>.</p></article>'
    _title, markdown, _fallback, _intro = extract_main_content(html, source_url="https://example.com/story")
    metadata, body = split_front_matter(markdown)
    assert metadata["url"] == "https://example.com/story"
    assert "[another article](https://example.com/other)" in body


def test_extract_main_content_excludes_wikipedia_infoboxes() -> None:
    html = """
    <html><head><title>Jorge Luis Borges</title></head><body><article>
      <table class="infobox biography vcard">
        <tr><th>Jorge Luis Borges</th></tr>
        <tr><td>Información personal</td></tr>
      </table>
      <p>Jorge Luis Borges fue un escritor, poeta y ensayista argentino.</p>
    </article></body></html>
    """

    _title, markdown, _fallback, _intro = extract_main_content(html, min_content_length=0)

    assert "Jorge Luis Borges fue" in markdown
    assert "Información personal" not in markdown
