# 2026-10-11：本次修改原因：按妙手组织属性简述和图文详情，只保留编辑器支持的静态 HTML。
from __future__ import annotations

from html import escape
from html.parser import HTMLParser
import re

from .models import SKU, valid_url


def attribute_description(attributes: dict[str, str]) -> str:
    return "\n".join(f"{name}:{value}" for name, value in attributes.items())


def detail_html(text: str, images: list[str]) -> str:
    paragraphs = [f"<p>{escape(line)}</p>" for line in text.splitlines() if line.strip()]
    paragraphs.extend(f'<p><img src="{escape(url, quote=True)}" width="640" /></p>'
                      for url in dict.fromkeys(images) if valid_url(url))
    return "\n".join(paragraphs)


class StaticDescription(HTMLParser):
    TAGS = {"p", "div", "br", "b", "strong", "i", "em", "u", "s", "span", "ul", "ol", "li",
            "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "table", "tr", "td", "th", "a", "img"}
    BLOCKED = {"script", "style", "iframe", "object", "embed", "svg"}
    STYLES = {"font-weight", "font-style", "text-decoration", "color", "background-color", "font-size",
              "text-align", "margin-top", "margin-bottom", "margin-left", "margin-right", "text-indent"}

    # 2026-10-11：本次修改原因：回填详情图时复用正文，避免恢复用户已移除的图片。
    def __init__(self, include_images: bool = True) -> None:
        super().__init__(convert_charrefs=True)
        self.include_images = include_images
        self.parts: list[str] = []
        self.blocked: list[str] = []

    def handle_starttag(self, tag, attrs) -> None:
        if self.blocked or tag in self.BLOCKED:
            self.blocked.append(tag)
            return
        if tag not in self.TAGS:
            return
        if tag == "img" and not self.include_images:
            return
        values = dict(attrs)
        kept = []
        for name in ("src", "href"):
            value = values.get(name) or ""
            if ((tag == "img" and name == "src") or (tag == "a" and name == "href")) and valid_url(value):
                kept.append(f'{name}="{escape(value, quote=True)}"')
        if tag == "img" and not any(value.startswith("src=") for value in kept):
            return
        for name in ("width", "height"):
            value = values.get(name) or ""
            if tag == "img" and value.isdecimal() and 0 < int(value) <= 4000:
                kept.append(f'{name}="{value}"')
        style = []
        for item in (values.get("style") or "").split(";"):
            key, separator, value = item.partition(":")
            if separator and key.strip().lower() in self.STYLES and re.fullmatch(r"[\w\s#.,%()+\-]+", value.strip()):
                if not re.search(r"url|expression", value, re.I):
                    style.append(f"{key.strip().lower()}:{value.strip()}")
        if style:
            kept.append(f'style="{escape(";".join(style), quote=True)}"')
        self.parts.append(f'<{tag}{" " + " ".join(kept) if kept else ""}>')

    def handle_startendtag(self, tag, attrs) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag) -> None:
        if self.blocked:
            if tag in self.blocked:
                self.blocked = self.blocked[:self.blocked.index(tag)]
            return
        if tag in self.TAGS and tag not in {"img", "br"}:
            self.parts.append(f"</{tag}>")

    def handle_data(self, text) -> None:
        if not self.blocked:
            self.parts.append(escape(text))


def clean_description(html: str) -> str:
    parser = StaticDescription()
    parser.feed(html)
    return "".join(parser.parts).strip()


# 2026-10-11：本次修改原因：自动详情按当前有效详情图重建，人工图文编辑由存储层保护。
def with_detail_images(html: str, images: list[str]) -> str:
    parser = StaticDescription(include_images=False)
    parser.feed(html)
    text = re.sub(r"<p>\s*</p>", "", "".join(parser.parts)).strip()
    return "\n".join(part for part in (text, detail_html("", images)) if part)


def sku_image_groups(skus: list[SKU], dimension: str, fallback: str) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    for sku in skus:
        value = sku.specs.get(dimension) or getattr(sku, fallback) or "未填写规格"
        urls = groups.setdefault(value, [])
        if valid_url(sku.image) and sku.image not in urls:
            urls.append(sku.image)
    return groups
