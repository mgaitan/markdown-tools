"""Tests for declarative domain extraction rules."""

from __future__ import annotations

from markdown_this import DomainRule, apply_domain_rule, extract_main_content


def test_apply_domain_rule_selects_substack_available_content() -> None:
    html = """
    <html><body>
      <p>Chrome</p>
      <div class="available-content">
        <p>Article body.</p>
        <a class="image-link-expand">Expand image</a>
      </div>
    </body></html>
    """

    result = apply_domain_rule(html, "https://example.substack.com/p/post")

    assert result is not None
    assert "Article body." in result
    assert "Chrome" not in result
    assert "Expand image" not in result


def test_openwall_extraction_uses_message_body_not_page_navigation() -> None:
    html = """
    <html>
      <head><title>oss-security - Example</title></head>
      <body>
        <a href="17">[&lt;prev]</a>
        <a href="19">[next&gt;]</a>
        <pre>Subject: Example vulnerability

The message body.
        </pre>
        <p>Powered by blists</p>
      </body>
    </html>
    """

    result = apply_domain_rule(html, "https://www.openwall.com/lists/oss-security/2026/10/21/18")

    assert result is not None
    assert "Subject: Example vulnerability" in result
    assert "The message body." in result
    assert "[&lt;prev]" not in result
    assert "Powered by blists" not in result

    _title, markdown, _fallback, _intro = extract_main_content(
        html,
        source_url="https://www.openwall.com/lists/oss-security/2026/10/21/18",
    )

    assert "The message body." in markdown
    assert "[<prev]" not in markdown
    assert "Powered by blists" not in markdown


def test_apply_domain_rule_returns_none_without_matching_host_or_body() -> None:
    rule = DomainRule(hosts=("example.com",), body_selectors=(".missing",))

    assert apply_domain_rule("<article>Body</article>", "https://other.test/post", (rule,)) is None
    assert apply_domain_rule("<article>Body</article>", "https://example.com/post", (rule,)) is None
    assert apply_domain_rule("<article>Body</article>", "not a url", (rule,)) is None


def test_apply_domain_rule_ignores_bad_selectors() -> None:
    rule = DomainRule(hosts=("example.com",), body_selectors=("[bad",), strip_selectors=("[also-bad",))

    assert apply_domain_rule("<article>Body</article>", "https://example.com/post", (rule,)) is None


def test_rule_uses_first_nonempty_body_without_nested_duplicates() -> None:
    rule = DomainRule(hosts=("example.com",), body_selectors=(".empty", "article", "article p"))
    html = '<div class="empty"></div><article><p>Once only.</p></article>'
    assert (
        apply_domain_rule(html, "https://blog.example.com:443/post", (rule,)) == "<article><p>Once only.</p></article>"
    )
    assert apply_domain_rule(html, "https://notexample.com/post", (rule,)) is None


def test_supplied_html_uses_same_declarative_rule() -> None:
    html = '<title>Essay</title><div class="available-content"><p>Short but complete.</p></div><p>Subscribe</p>'
    title, markdown, _fallback, _intro = extract_main_content(html, source_url="https://example.substack.com/p/post")
    assert title == "Essay"
    assert "Short but complete." in markdown
    assert "Subscribe" not in markdown
