"""Captured post sequences share selection and media normalization."""

from pathlib import Path

import pytest
import requests
from markdown_this import DomainRule, apply_domain_rule, extract_main_content, split_front_matter
from markdown_this.html import preprocess_media
from pytest_mock import MockerFixture

FIXTURE = Path(__file__).parent / "fixtures" / "extraction" / "x_thread.html"


@pytest.mark.parametrize("host", ["x.com", "twitter.com", "www.x.com", "m.twitter.com"])
@pytest.mark.parametrize("download", [True, False])
def test_captured_thread_and_media(host: str, download: bool, mocker: MockerFixture) -> None:
    url = f"https://{host}/alice/status/1002"
    html = FIXTURE.read_text()
    fetch = mocker.patch("markdown_this.extractor.fetch_html", return_value=html)
    mocker.patch("markdown_this.fetchers.requests.get", side_effect=requests.RequestException("No oEmbed"))
    title, markdown, _fallback, _intro = (
        extract_main_content(url) if download else extract_main_content(html, source_url=url)
    )
    metadata, body = split_front_matter(markdown)
    assert title == "Alice's research thread"
    assert metadata["extraction_scope"] == "captured-posts"
    assert body.index("First observation") < body.index("Second observation") < body.index("Third observation")
    assert "[the paper](https://example.org/paper)" in body
    assert "https://pbs.twimg.com/media/chart.jpg" in body
    assert body.count("https://video.twimg.com/demo.mp4") == 1
    assert "https://pbs.twimg.com/media/final.jpg" in body
    for noise in [
        "Trending",
        "profile_images",
        "Reply Repost",
        "Duplicate",
        "reader response",
        "separate reply",
        "Discover more",
        "recommended",
        "Subscribe",
        "blob:",
        "/alice/status/1003",
    ]:
        assert noise not in body
    assert fetch.call_count == int(download)


def test_same_collection_algorithm_accepts_another_markup() -> None:
    rule = DomainRule(
        hosts=("forum.example",),
        body_selectors=("main",),
        item_selector=".post",
        permalink_selector="a.permalink",
        boundary_selector="h3",
    )
    html = '<main><h3>Thread</h3><div class="post"><a class="permalink" href="/alice/1">One</a></div>'
    html += '<div class="post"><a class="permalink" href="/alice/2">Two</a></div></main>'
    result = apply_domain_rule(html, "https://tenant.forum.example/alice/1", (rule,))
    assert result and "One" in result and "Two" in result


def test_collection_target_ignores_x_media_suffix() -> None:
    html = FIXTURE.read_text()
    result = apply_domain_rule(html, "https://x.com/alice/status/1002/photo/1")
    assert result and "Second observation" in result and "Discover more" not in result


def test_x_collection_supports_current_post_markup_without_test_ids_or_time() -> None:
    html = """
    <main><h2>Post</h2>
      <article><a href="/alice/status/1001">4 September</a><p>First current post</p></article>
      <article><a href="/alice/status/1002">4 September</a><p>Second current post</p></article>
      <article><a href="/bob/status/2000">4 September</a><p>Reader response</p></article>
    </main>
    """

    result = apply_domain_rule(html, "https://x.com/alice/status/1001")

    assert result and "First current post" in result and "Second current post" in result
    assert "Reader response" not in result


def test_current_x_markup_keeps_only_thread_text() -> None:
    html = """
    <main>
      <article>
        <img src="https://pbs.twimg.com/profile_images/alice.jpg" alt="@alice">
        <a href="https://x.com/alice">Alice</a><a href="/alice/status/1001">4 September</a>
        <div dir="auto">
          First current post with <a href="https://example.org/source">a source</a>
          and <a href="https://x.com/FastAPIcloud"><span>https://x.com/FastAPIcloud</span></a>
          for the hosting.
        </div>
        <a href="https://t.co/card"><img src="https://pbs.twimg.com/card_img/preview.jpg" alt="Card preview"></a>
        <a href="/alice/status/1001">500 Views</a><button>Reply Repost Like</button>
      </article>
      <article>
        <a href="https://x.com/alice">Alice</a><a href="/alice/status/1002">4 September</a>
        <div dir="auto">Second current post.</div>
      </article>
      <article><a href="/alice/status/1003">4 September</a></article>
    </main>
    """

    result = apply_domain_rule(html, "https://x.com/alice/status/1001")

    assert result and "First current post" in result and "Second current post" in result
    assert "a source" in result
    assert ">@FastAPIcloud</a>" in result
    markdown = extract_main_content(html, source_url="https://x.com/alice/status/1001")[1]
    assert "[@FastAPIcloud](https://x.com/FastAPIcloud)" in markdown
    assert "[@https://x.com/FastAPIcloud]" not in markdown
    assert "[@FastAPIcloud](https://x.com/FastAPIcloud)\n\nfor" not in markdown
    for noise in ["profile_images", "Card preview", "500 Views", "Reply Repost Like", "4 September"]:
        assert noise not in result


def test_collection_requires_requested_post_and_skips_unusable_cells() -> None:
    rule = DomainRule(hosts=("forum.example",), body_selectors=("main",), item_selector="article")
    html = '<main><article>No permalink</article><article><a href="javascript:bad"><time>Bad</time></a></article>'
    html += '<article><a href="https://outside.example/a/3"><time>Outside</time></a></article>'
    html += '<article><a href="/"><time>Missing ID</time></a></article></main>'
    assert apply_domain_rule(html, "https://forum.example/alice/1", (rule,)) is None


def test_nested_post_is_not_a_thread_member() -> None:
    rule = DomainRule(hosts=("forum.example",), body_selectors=("main",), item_selector="article")
    html = '<main><article><a href="/alice/1"><time>One</time></a><blockquote><article>'
    html += '<a href="/bob/2"><time>Quoted</time></a></article></blockquote></article></main>'
    result = apply_domain_rule(html, "https://forum.example/alice/1", (rule,))
    assert result and result.count("Quoted") == 1
    assert apply_domain_rule(html, "https://forum.example/bob/2", (rule,)) is None


def test_shared_media_normalizer_preserves_audio_and_relative_sources() -> None:
    html = '<audio src="/episode.ogg"><source><source src="javascript:bad"></audio><video></video>'
    result = preprocess_media(html, "https://example.com/story")
    assert '<a href="https://example.com/episode.ogg">Audio</a>' in result
    assert "javascript:" not in result
