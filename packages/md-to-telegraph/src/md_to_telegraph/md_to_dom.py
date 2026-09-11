import re

from mistletoe import Document, block_token, span_token
from mistletoe.base_renderer import BaseRenderer

type Node = dict[str, object] | str
type NodeList = list[Node]

HEADING_LEVEL_PRIMARY = 1
HEADING_LEVEL_SECONDARY = 2
HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


class TelegraphDomRenderer(BaseRenderer):
    """
    Convert a mistletoe AST into Telegraph DOM nodes.
    """

    def __init__(self, source_lines: list[str] | None = None) -> None:
        super().__init__(span_token.HTMLSpan, block_token.HTMLBlock)
        self.source_lines = source_lines or []

    def render_document(self, token: block_token.Document) -> NodeList:
        nodes: NodeList = []
        for child in token.children:
            rendered = self.render(child)
            if rendered is None:
                continue
            nodes.append(rendered)
        return nodes

    def render_paragraph(self, token: block_token.Paragraph) -> dict[str, object] | None:
        children = self.render_inner(token)
        children = [c for c in children if c != ""]
        if not children or all(isinstance(c, str) and not c.strip() for c in children):
            return None
        return {"tag": "p", "children": children}

    def render_heading(self, token: block_token.Heading) -> dict[str, object]:
        if token.level == HEADING_LEVEL_PRIMARY:
            return {"tag": "h3", "children": self.render_inner(token)}
        if token.level == HEADING_LEVEL_SECONDARY:
            return {"tag": "h4", "children": self.render_inner(token)}
        return {
            "tag": "p",
            "children": [{"tag": "strong", "children": self.render_inner(token)}],
        }

    def render_list(self, token: block_token.List) -> dict[str, object]:
        tag = "ol" if token.start is not None else "ul"
        return {
            "tag": tag,
            "children": [self.render(child) for child in token.children],
        }

    def render_list_item(self, token: block_token.ListItem) -> dict[str, object]:
        return {"tag": "li", "children": self.render_inner(token)}

    def render_strong(self, token: span_token.Strong) -> dict[str, object]:
        return {"tag": "strong", "children": self.render_inner(token)}

    def render_emphasis(self, token: span_token.Emphasis) -> dict[str, object]:
        return {"tag": "em", "children": self.render_inner(token)}

    def render_inline_code(self, token: span_token.InlineCode) -> dict[str, object]:
        return {"tag": "code", "children": [token.children[0].content]}

    def render_strikethrough(self, token: span_token.Strikethrough) -> dict[str, object]:
        return {"tag": "del", "children": self.render_inner(token)}

    def render_image(self, token: span_token.Image) -> dict[str, object]:
        attrs = {"src": token.src}
        alt_text = self.render_inner(token)
        if alt_text:
            attrs["alt"] = alt_text
        if token.title:
            attrs["title"] = token.title
        return {"tag": "img", "attrs": attrs}

    def render_link(self, token: span_token.Link) -> dict[str, object]:
        attrs = {"href": token.target}
        if token.title:
            attrs["title"] = token.title
        return {"tag": "a", "attrs": attrs, "children": self.render_inner(token)}

    def render_auto_link(self, token: span_token.AutoLink) -> dict[str, object]:
        return {"tag": "a", "attrs": {"href": token.target}, "children": [token.target]}

    def render_raw_text(self, token: span_token.RawText) -> str:
        return token.content

    def render_line_break(self, token: span_token.LineBreak) -> dict[str, object] | str:
        if token.soft:
            return " "
        return {"tag": "br"}

    def render_block_code(self, token: block_token.BlockCode) -> dict[str, object]:
        code_dict = {
            "tag": "code",
            "children": self.code_children_from_text(token.content),
        }
        if token.language:
            code_dict.setdefault("attrs", {})["class"] = "language-" + token.language
        return {"tag": "pre", "children": [code_dict]}

    def render_table(self, token: block_token.Table) -> dict[str, object]:
        """Preserve tables as raw Markdown because Telegraph has no table node."""
        last_line = token.children[-1].line_number if token.children else token.line_number + 1
        table_markdown = "\n".join(self.source_lines[token.line_number - 1 : last_line])
        return {
            "tag": "pre",
            "children": [{"tag": "code", "children": self.code_children_from_text(table_markdown)}],
        }

    def render_quote(self, token: block_token.Quote) -> dict[str, object]:
        return {"tag": "blockquote", "children": self.render_inner(token)}

    def render_thematic_break(self, token: block_token.ThematicBreak) -> dict[str, object]:
        return {"tag": "hr"}

    def render_html_block(self, token: block_token.HTMLBlock) -> str:
        return token.content

    def render_html_span(self, token: span_token.HTMLSpan) -> str:
        return token.content

    def render_inner(self, token: object) -> NodeList:
        result: NodeList = []
        for child in token.children:
            rendered = self.render(child)
            if rendered is None:
                continue
            if rendered != "":
                result.append(rendered)
        return result

    def code_children_from_text(self, text: str) -> NodeList:
        lines = text.rstrip("\n").split("\n")
        children: NodeList = []
        for idx, line in enumerate(lines):
            children.append(line)
            if idx != len(lines) - 1:
                children.append({"tag": "br"})
        return children


def md_to_telegraph(markdown_text: str) -> NodeList:
    markdown_without_comments = HTML_COMMENT_RE.sub(lambda match: "\n" * match.group().count("\n"), markdown_text)
    with TelegraphDomRenderer(markdown_without_comments.splitlines()) as renderer:
        return renderer.render(Document(markdown_without_comments))


def content_to_telegraph(markdown_text: str, fallback_text: str = "") -> NodeList:
    """Convert Markdown content, falling back to plain-text paragraphs."""
    nodes = md_to_telegraph(markdown_text.strip()) if markdown_text.strip() else []
    if nodes:
        return nodes

    paragraphs = [paragraph.strip() for paragraph in fallback_text.strip().split("\n\n") if paragraph.strip()]
    if paragraphs:
        return [{"tag": "p", "children": [paragraph]} for paragraph in paragraphs[:2000]]

    return [{"tag": "p", "children": ["(No content extracted)"]}]


def prepend_image(nodes: NodeList, image_url: str) -> NodeList:
    """Prepend a metadata image unless the same image is already in the content."""
    if not image_url or _contains_image(nodes, image_url):
        return nodes
    return [{"tag": "img", "attrs": {"src": image_url}}, *nodes]


def _contains_image(nodes: NodeList, image_url: str) -> bool:
    for node in nodes:
        if not isinstance(node, dict):
            continue
        attrs = node.get("attrs")
        if isinstance(attrs, dict) and attrs.get("src") == image_url and node.get("tag") == "img":
            return True
        children = node.get("children")
        if isinstance(children, list) and _contains_image(children, image_url):
            return True
    return False
