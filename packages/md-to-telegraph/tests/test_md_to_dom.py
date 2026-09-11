"""Tests for md_to_telegraph — Markdown → Telegraph DOM conversion."""

from __future__ import annotations

from md_to_telegraph import content_to_telegraph, md_to_telegraph
from md_to_telegraph.md_to_dom import prepend_image

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def text_content(nodes: list) -> str:  # type: ignore[type-arg]
    """Recursively extract all text strings from a DOM node list."""
    parts: list[str] = []
    for node in nodes:
        if isinstance(node, str):
            parts.append(node)
        elif isinstance(node, dict):
            parts.extend(text_content(node.get("children") or []))
    return "".join(parts)


# ---------------------------------------------------------------------------
# Soft line-break spacing (the core bug that was fixed)
# ---------------------------------------------------------------------------


def test_soft_break_space_preserved_after_link() -> None:
    """Soft line break after a link must produce a space node."""
    md = "This is [some link](http://example.com)\nand more text."
    result = md_to_telegraph(md)
    assert len(result) == 1
    children = result[0]["children"]
    assert " " in children
    assert "and more text." in children
    assert text_content(result) == "This is some link and more text."


def test_soft_break_space_preserved_before_link() -> None:
    """Soft line break before a link must produce a space node."""
    md = "Read more\n[here](http://example.com) for details."
    result = md_to_telegraph(md)
    assert text_content(result) == "Read more here for details."


def test_soft_break_space_preserved_after_bold() -> None:
    """Soft line break after bold text must produce a space node."""
    md = "Hello **world**\nfoo bar."
    result = md_to_telegraph(md)
    assert len(result) == 1
    children = result[0]["children"]
    assert " " in children
    assert text_content(result) == "Hello world foo bar."


def test_soft_break_space_preserved_after_emphasis() -> None:
    """Soft line break after italic text must produce a space node."""
    md = "An *important*\nconcept."
    result = md_to_telegraph(md)
    assert text_content(result) == "An important concept."


def test_soft_break_space_preserved_after_inline_code() -> None:
    """Soft line break after inline code must produce a space node."""
    md = "Run `git status`\nto check."
    result = md_to_telegraph(md)
    assert text_content(result) == "Run git status to check."


def test_soft_break_space_preserved_between_link_and_code() -> None:
    """Soft line break between a link and inline code must produce spaces."""
    md = "See [docs](http://example.com)\n`ssh -L`\nfor details."
    result = md_to_telegraph(md)
    assert text_content(result) == "See docs ssh -L for details."


def test_soft_break_no_duplicate_spaces() -> None:
    """When the original text already has a space, no double space."""
    md = "Hello **world** foo bar."
    result = md_to_telegraph(md)
    full = text_content(result)
    assert "  " not in full
    assert full == "Hello world foo bar."


def test_soft_break_hiding_ssh_case() -> None:
    """Regression: 'hidingSSH' concatenation from bofh.it-style articles.

    readability+markdownify can emit newlines around inline code instead of
    spaces (e.g. 'hiding\\n`SSH`\\nin HTTPS').  render_inner used to filter
    out the ' ' produced by render_line_break for soft breaks, joining words
    without a separator.
    """
    md = "hiding\n`SSH`\nin HTTPS"
    result = md_to_telegraph(md)
    children = result[0]["children"]
    assert " " in children
    assert text_content(result) == "hiding SSH in HTTPS"


def test_soft_break_inline_code_at_start_of_line() -> None:
    """Soft line break before inline code at the start of a line."""
    md = "`SSH`\ntraffic hiding"
    result = md_to_telegraph(md)
    assert text_content(result) == "SSH traffic hiding"
    children = result[0]["children"]
    assert " " in children


# ---------------------------------------------------------------------------
# Inline rendering (spaces already present in the source text)
# ---------------------------------------------------------------------------


def test_inline_link_with_surrounding_text() -> None:
    md = "The [link text](http://example.com) is here."
    result = md_to_telegraph(md)
    assert result == [
        {
            "tag": "p",
            "children": [
                "The ",
                {"tag": "a", "attrs": {"href": "http://example.com"}, "children": ["link text"]},
                " is here.",
            ],
        }
    ]


def test_inline_bold_text() -> None:
    md = "This is **bold** text."
    result = md_to_telegraph(md)
    assert text_content(result) == "This is bold text."
    assert result[0]["children"][1] == {"tag": "strong", "children": ["bold"]}


def test_inline_italic_text() -> None:
    md = "This is *italic* text."
    result = md_to_telegraph(md)
    assert text_content(result) == "This is italic text."
    assert result[0]["children"][1] == {"tag": "em", "children": ["italic"]}


def test_inline_code() -> None:
    md = "Use `print()` to output."
    result = md_to_telegraph(md)
    assert text_content(result) == "Use print() to output."
    assert result[0]["children"][1] == {"tag": "code", "children": ["print()"]}


def test_inline_strikethrough() -> None:
    md = "This is ~~wrong~~ right."
    result = md_to_telegraph(md)
    assert text_content(result) == "This is wrong right."
    assert result[0]["children"][1] == {"tag": "del", "children": ["wrong"]}


def test_inline_autolink() -> None:
    md = "<https://example.com>"
    result = md_to_telegraph(md)
    link = result[0]["children"][0]
    assert link == {"tag": "a", "attrs": {"href": "https://example.com"}, "children": ["https://example.com"]}


def test_inline_link_with_title() -> None:
    md = '[text](http://example.com "My title")'
    result = md_to_telegraph(md)
    link = result[0]["children"][0]
    assert link["tag"] == "a"
    assert link["attrs"]["title"] == "My title"
    assert link["attrs"]["href"] == "http://example.com"


def test_inline_bold_inside_link() -> None:
    """Nested inline: bold text inside a link."""
    md = "[**bold**](http://example.com)"
    result = md_to_telegraph(md)
    link = result[0]["children"][0]
    assert link["tag"] == "a"
    assert link["children"] == [{"tag": "strong", "children": ["bold"]}]


def test_inline_code_inside_link() -> None:
    """Nested inline: inline code inside a link."""
    md = "[`code`](http://example.com)"
    result = md_to_telegraph(md)
    link = result[0]["children"][0]
    assert link["tag"] == "a"
    assert link["children"] == [{"tag": "code", "children": ["code"]}]


def test_embedded_html_heading_maps_to_telegraph_heading() -> None:
    result = md_to_telegraph('<h1 align="center">WhisperX</h1>')

    assert result == [{"tag": "h3", "children": ["WhisperX"]}]


def test_embedded_html_image_keeps_supported_attributes_only() -> None:
    result = md_to_telegraph(
        '<img width="1216" align="center" alt="whisperx-arch" src="https://example.com/pipeline.png">'
    )

    assert result == [
        {
            "tag": "img",
            "attrs": {"src": "https://example.com/pipeline.png", "alt": "whisperx-arch"},
        }
    ]


def test_embedded_html_heading_with_attributes_maps_to_telegraph_heading() -> None:
    result = md_to_telegraph('<h2 align="left" id="setup">Setup</h2>')

    assert result == [{"tag": "h4", "children": ["Setup"]}]


def test_embedded_html_deep_heading_maps_to_strong_paragraph() -> None:
    assert md_to_telegraph("<h3>Details</h3>") == [
        {"tag": "p", "children": [{"tag": "strong", "children": ["Details"]}]}
    ]


def test_embedded_html_container_keeps_supported_children() -> None:
    assert md_to_telegraph('<div><a href="https://example.com">Read</a><br><hr></div>') == [
        {"tag": "a", "attrs": {"href": "https://example.com"}, "children": ["Read"]},
        {"tag": "br"},
        {"tag": "hr"},
    ]


def test_embedded_html_self_closing_image_without_alt() -> None:
    assert md_to_telegraph('<img src="https://example.com/pipeline.png"/>') == [
        {"tag": "img", "attrs": {"src": "https://example.com/pipeline.png"}}
    ]


def test_unsupported_html_block_is_left_unchanged() -> None:
    assert md_to_telegraph("<aside>Note</aside>") == ["<aside>Note</aside>"]


# ---------------------------------------------------------------------------
# Block-level rendering
# ---------------------------------------------------------------------------


def test_block_heading_h1_maps_to_h3() -> None:
    md = "# Title"
    result = md_to_telegraph(md)
    assert result == [{"tag": "h3", "children": ["Title"]}]


def test_block_heading_h2_maps_to_h4() -> None:
    md = "## Subtitle"
    result = md_to_telegraph(md)
    assert result == [{"tag": "h4", "children": ["Subtitle"]}]


def test_block_heading_h3_maps_to_strong_paragraph() -> None:
    md = "### Section"
    result = md_to_telegraph(md)
    assert result == [{"tag": "p", "children": [{"tag": "strong", "children": ["Section"]}]}]


def test_table_is_preserved_as_raw_markdown_code() -> None:
    markdown = "| Name | Score |\n| :--- | ---: |\n| Alice | 10 |\n| Bob | 9 |"

    assert md_to_telegraph(markdown) == [
        {
            "tag": "pre",
            "children": [
                {
                    "tag": "code",
                    "children": [
                        "| Name | Score |",
                        {"tag": "br"},
                        "| :--- | ---: |",
                        {"tag": "br"},
                        "| Alice | 10 |",
                        {"tag": "br"},
                        "| Bob | 9 |",
                    ],
                }
            ],
        }
    ]


def test_table_without_rows_is_preserved_as_raw_markdown_code() -> None:
    assert text_content(md_to_telegraph("| Name |\n| --- |")) == "| Name || --- |"


def test_block_heading_h4_and_deeper_map_to_strong_paragraph() -> None:
    """h4 and deeper headings are also rendered as strong paragraphs."""
    for prefix in ("#### ", "##### ", "###### "):
        result = md_to_telegraph(f"{prefix}Deep heading")
        assert result[0] == {"tag": "p", "children": [{"tag": "strong", "children": ["Deep heading"]}]}


def test_block_unordered_list() -> None:
    md = "- item one\n- item two"
    result = md_to_telegraph(md)
    assert len(result) == 1
    assert result[0]["tag"] == "ul"
    assert len(result[0]["children"]) == 2  # noqa: PLR2004


def test_block_ordered_list() -> None:
    md = "1. first\n2. second"
    result = md_to_telegraph(md)
    assert result[0]["tag"] == "ol"


def test_block_nested_list() -> None:
    """A list item may contain a nested sub-list."""
    md = "- outer\n    - inner"
    result = md_to_telegraph(md)
    outer_item = result[0]["children"][0]
    nested_tags = [c["tag"] for c in outer_item["children"] if isinstance(c, dict)]
    assert "ul" in nested_tags


def test_block_list_item_with_inline_elements() -> None:
    """List items may contain inline markup."""
    md = "- item with **bold** text"
    result = md_to_telegraph(md)
    full = text_content(result)
    assert full == "item with bold text"


def test_block_blockquote() -> None:
    md = "> A quote"
    result = md_to_telegraph(md)
    assert result[0]["tag"] == "blockquote"


def test_block_blockquote_with_link() -> None:
    """Blockquotes may contain inline elements like links."""
    md = "> A [linked](http://example.com) quote"
    result = md_to_telegraph(md)
    assert result[0]["tag"] == "blockquote"
    assert text_content(result) == "A linked quote"


def test_block_thematic_break() -> None:
    md = "---"
    result = md_to_telegraph(md)
    assert result == [{"tag": "hr"}]


def test_block_code() -> None:
    md = "```python\nprint('hi')\n```"
    result = md_to_telegraph(md)
    assert result[0]["tag"] == "pre"


def test_block_code_language_class() -> None:
    """Code block with a language hint gets the appropriate CSS class."""
    md = "```python\nprint()\n```"
    result = md_to_telegraph(md)
    code_node = result[0]["children"][0]
    assert code_node["tag"] == "code"
    assert code_node["attrs"]["class"] == "language-python"


def test_block_code_no_language() -> None:
    """Code block without language hint has no attrs."""
    md = "```\nplain code\n```"
    result = md_to_telegraph(md)
    code_node = result[0]["children"][0]
    assert code_node["tag"] == "code"
    assert "attrs" not in code_node


def test_block_code_multiline_has_br_nodes() -> None:
    """Multi-line code blocks use <br> to separate lines."""
    md = "```\nline1\nline2\nline3\n```"
    result = md_to_telegraph(md)
    code_children = result[0]["children"][0]["children"]
    assert code_children[0] == "line1"
    assert code_children[1] == {"tag": "br"}
    assert code_children[2] == "line2"


def test_block_multiple_paragraphs() -> None:
    md = "First paragraph.\n\nSecond paragraph."
    result = md_to_telegraph(md)
    assert len(result) == 2  # noqa: PLR2004
    assert result[0] == {"tag": "p", "children": ["First paragraph."]}
    assert result[1] == {"tag": "p", "children": ["Second paragraph."]}


def test_block_hard_line_break_produces_br() -> None:
    md = "Line one  \nLine two"  # two trailing spaces → hard break
    result = md_to_telegraph(md)
    assert {"tag": "br"} in result[0]["children"]


# ---------------------------------------------------------------------------
# Empty / whitespace-only content
# ---------------------------------------------------------------------------


def test_empty_document() -> None:
    assert md_to_telegraph("") == []


def test_whitespace_only_document() -> None:
    assert md_to_telegraph("   \n  \n  ") == []


def test_content_to_telegraph_prefers_markdown_nodes() -> None:
    result = content_to_telegraph("# Title\n\nBody", "Fallback")
    assert result == [
        {"tag": "h3", "children": ["Title"]},
        {"tag": "p", "children": ["Body"]},
    ]


def test_content_to_telegraph_uses_fallback_paragraphs() -> None:
    result = content_to_telegraph("", "First paragraph.\n\nSecond paragraph.")
    assert result == [
        {"tag": "p", "children": ["First paragraph."]},
        {"tag": "p", "children": ["Second paragraph."]},
    ]


def test_content_to_telegraph_uses_empty_content_placeholder() -> None:
    assert content_to_telegraph("", "   \n  ") == [{"tag": "p", "children": ["(No content extracted)"]}]


def test_html_comments_are_not_published() -> None:
    assert content_to_telegraph("<!-- Page 50 -->\n\nVisible text") == [{"tag": "p", "children": ["Visible text"]}]


def test_prepend_image_adds_metadata_image() -> None:
    assert prepend_image([{"tag": "p", "children": ["Body"]}], "https://example.com/hero.jpg") == [
        {"tag": "img", "attrs": {"src": "https://example.com/hero.jpg"}},
        {"tag": "p", "children": ["Body"]},
    ]


def test_prepend_image_does_not_duplicate_content_image() -> None:
    nodes = md_to_telegraph("![Hero](https://example.com/hero.jpg)")
    assert prepend_image(nodes, "https://example.com/hero.jpg") == nodes


def test_nbsp_only_paragraph_is_skipped() -> None:
    """A paragraph containing only &nbsp; (non-breaking space) is treated as empty."""
    assert md_to_telegraph("&nbsp;") == []


def test_nbsp_only_paragraph_in_blockquote_is_skipped() -> None:
    """A blockquote whose only content is an &nbsp; paragraph gets empty children."""
    result = md_to_telegraph("> &nbsp;")
    assert result == [{"tag": "blockquote", "children": []}]


# ---------------------------------------------------------------------------
# Raw HTML passthrough
# ---------------------------------------------------------------------------


def test_html_block_is_converted_to_telegraph_node() -> None:
    """An HTML block (e.g. <pre>…</pre>) maps to its Telegraph equivalent."""
    md = "<pre>\ncode here\n</pre>"
    result = md_to_telegraph(md)
    assert result == [{"tag": "pre", "children": ["\ncode here\n"]}]


def test_html_span_passthrough() -> None:
    """Inline HTML tags within a paragraph are passed through as raw strings."""
    md = "text <em>emphasis</em> end"
    result = md_to_telegraph(md)
    full = text_content(result)
    assert "text" in full
    assert "emphasis" in full
    assert "end" in full
    children = result[0]["children"]
    assert any(isinstance(c, str) and "<em>" in c for c in children)


# ---------------------------------------------------------------------------
# Image rendering
# ---------------------------------------------------------------------------


def test_image_tag() -> None:
    md = "![alt text](http://example.com/img.png)"
    result = md_to_telegraph(md)
    assert result[0]["children"][0] == {
        "tag": "img",
        "attrs": {"src": "http://example.com/img.png", "alt": ["alt text"]},
    }


def test_image_with_title() -> None:
    md = '![alt](http://example.com/img.png "Caption")'
    result = md_to_telegraph(md)
    img = result[0]["children"][0]
    assert img["tag"] == "img"
    assert img["attrs"]["src"] == "http://example.com/img.png"
    assert img["attrs"]["title"] == "Caption"


def test_image_no_alt_text() -> None:
    md = "![](http://example.com/img.png)"
    result = md_to_telegraph(md)
    img = result[0]["children"][0]
    assert img["tag"] == "img"
    assert img["attrs"]["src"] == "http://example.com/img.png"
    assert not img["attrs"].get("alt")
