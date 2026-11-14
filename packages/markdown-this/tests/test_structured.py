"""Shared embedded formats must work for downloaded and supplied documents."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from markdown_this import extract_main_content, split_front_matter
from markdown_this.structured import extract_fusion_article
from pytest_mock import MockerFixture

FIXTURE = Path(__file__).parent / "fixtures" / "extraction" / "pagina12_fusion_article.html"


@pytest.mark.parametrize("url", ["https://www.pagina12.com.ar/story", "https://another-publisher.example/story"])
@pytest.mark.parametrize("download", [False, True])
def test_fusion_uses_shared_pipeline(url: str, download: bool, mocker: MockerFixture) -> None:
    html = FIXTURE.read_text(encoding="utf-8")
    fetch = mocker.patch("markdown_this.extractor.fetch_html", return_value=html)
    mocker.patch("markdown_this.extractor.Document", side_effect=AssertionError("Structured body is sufficient"))
    result = extract_main_content(url) if download else extract_main_content(html, source_url=url)
    metadata, body = split_front_matter(result[1])
    assert metadata["url"] == url
    assert metadata["author"] == "Pagina/12"
    assert "El proyecto oficial volvio a quedar lejos de las demandas sociales." in body
    assert "La oposicion cuestiono el recorte durante la sesion." in body
    assert "Copiar enlace" not in body
    assert "Ultimas noticias" not in body
    assert fetch.call_count == int(download)


def test_fusion_fragments_share_link_and_image_normalization() -> None:
    data = {
        "headlines": {"basic": 'An "escaped" {title}'},
        "content_elements": [
            {"type": "header", "level": 3, "content": '<a href="/section">Section</a>'},
            {"type": "header", "level": "bad", "content": "Default heading"},
            {"type": "text", "content": '<b>Body</b> with <a href="../related">a reference</a>.'},
            {
                "type": "image",
                "additional_properties": {"originalUrl": "/photo.jpg"},
                "alt_text": "<b>Photo</b>",
                "caption": '<a href="/credits">Credit</a>',
            },
            {"type": "image", "url": "data:image/png;base64,abc"},
        ],
    }
    html = f"<script>Fusion.globalContent = {json.dumps(data)}; nextCall();</script>"
    title, markdown, _fallback, _intro = extract_main_content(html, source_url="https://example.com/news/story")
    assert title == 'An "escaped" {title}'
    assert "### [Section](https://example.com/section)" in markdown
    assert "Default heading\n---" in markdown
    assert "[a reference](https://example.com/related)" in markdown
    assert "![Photo](https://example.com/photo.jpg)" in markdown
    assert "[Credit](https://example.com/credits)" in markdown
    assert "data:image" not in markdown


def test_fusion_treats_long_headers_as_article_paragraphs() -> None:
    long_header = (
        "Varios intendentes peronistas dicen que, frente a la dispersión nacional, desdoblar como un mecanismo "
        "para preservar la provincia y los municipios."
    )
    data = {
        "content_elements": [
            {"type": "header", "level": 2, "content": long_header},
            {"type": "header", "level": 2, "content": "Section heading"},
        ]
    }
    html = f"<script>Fusion.globalContent = {json.dumps(data)};</script>"

    _title, markdown, _fallback, _intro = extract_main_content(html)

    assert long_header in markdown
    assert f"## {long_header}" not in markdown
    assert "## Section heading" in markdown


@pytest.mark.parametrize(
    "data",
    [
        "null",
        "[]",
        "{}",
        "{'invalid': true}",
        '{"unterminated":',
        json.dumps({"content_elements": [None, {}, {"type": "text"}, {"type": "header"}, {"type": "image"}]}),
    ],
)
def test_unusable_embedded_data_falls_through(data: str) -> None:
    assert extract_fusion_article(f"<script>Fusion.globalContent = {data};</script>") is None


def test_fusion_reads_later_valid_script_and_handles_absent_headline() -> None:
    html = "<script>unrelated();</script><script>Fusion.globalContent = null;</script>"
    html += '<script>Fusion.globalContent = {"content_elements":[{"type":"text","content":"Body"}]};</script>'
    assert extract_fusion_article(html) == ("", "<p>Body</p>")
