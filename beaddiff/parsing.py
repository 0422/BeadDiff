# 2026-10-10：本次修改原因：解析 Temu 页面原始材料；不执行网页脚本、不猜测价格单位或库存。
from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from typing import Any

from .models import Product, SKU, valid_url


class PageMaterial(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.scripts: list[str] = []
        self.meta: dict[str, str] = {}
        self._script: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "script":
            self._script = []
        elif tag == "meta":
            key = attributes.get("property") or attributes.get("name")
            if key:
                self.meta[key] = attributes.get("content") or ""

    def handle_data(self, data: str) -> None:
        if self._script is not None:
            self._script.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._script is not None:
            self.scripts.append("".join(self._script))
            self._script = None


def first(data: dict, *keys: str, default: Any = "") -> Any:
    for key in keys:
        if data.get(key) is not None and data[key] != "":
            return data[key]
    return default


def scalar(value: Any) -> str:
    return str(value).strip() if isinstance(value, (str, int, float)) and not isinstance(value, bool) else ""


def image_urls(value: Any) -> list[str]:
    values = value if isinstance(value, list) else [value]
    result = []
    for item in values:
        if isinstance(item, dict):
            item = first(item, "url", "imageUrl", "image_url", "thumbUrl", "src", "originUrl")
        url = scalar(item)
        if url.startswith("//"):
            url = "https:" + url
        if valid_url(url) and url not in result:
            result.append(url)
    return result


def documents(page: str) -> tuple[list[Any], dict[str, str]]:
    material = PageMaterial()
    material.feed(page)
    decoder = json.JSONDecoder()
    found = []
    for script in material.scripts + [page if not material.scripts else ""]:
        content = script.strip()
        if content.startswith(("{", "[")):
            try:
                found.append(decoder.raw_decode(content)[0])
            except (ValueError, RecursionError):
                pass
        for match in re.finditer(r"(?:window\.)?(?:rawData|__INITIAL_STATE__|__NEXT_DATA__)\s*=\s*", content):
            try:
                found.append(decoder.raw_decode(content[match.end():].lstrip())[0])
            except (ValueError, RecursionError):
                pass
    return found, material.meta


def candidates(documents_: list[Any]) -> list[dict]:
    result = []
    pending = [(document, 0) for document in documents_]
    inspected = 0
    while pending and inspected < 100_000:
        value, depth = pending.pop()
        inspected += 1
        if depth > 30:
            continue
        if isinstance(value, dict):
            if (value.get("goodsName") or value.get("goods_name")) and any(
                key in value for key in ("goodsId", "goods_id", "skuList", "sku_list", "gallery")
            ):
                result.append(value)
            # pending.extend((child, depth + 1) for child in value.values() if isinstance(child, (dict, list)))
            # 2026-10-10：本次修改原因：遍历优先保持页面 JSON 中的原始字段顺序。
            pending.extend((child, depth + 1) for child in reversed(list(value.values())) if isinstance(child, (dict, list)))
        elif isinstance(value, list):
            # pending.extend((child, depth + 1) for child in value if isinstance(child, (dict, list)))
            pending.extend((child, depth + 1) for child in reversed(value) if isinstance(child, (dict, list)))
    return result


def specs_for(item: dict) -> dict[str, str]:
    values = first(item, "specs", "specList", "spec_list", default=[])
    if isinstance(values, dict):
        return {str(key): scalar(value) for key, value in values.items() if scalar(value)}
    result = {}
    if isinstance(values, list):
        for index, value in enumerate(values, 1):
            if isinstance(value, dict):
                name = scalar(first(value, "parentSpecName", "parent_spec_name", "name", default=f"规格{index}"))
                text = scalar(first(value, "specName", "spec_name", "value"))
                if text:
                    result[name or f"规格{index}"] = text
    return result


def source_price(item: dict) -> str:
    value = first(item, "priceStr", "priceDisplay", "formattedPrice", "salePrice", "price", "normalPrice")
    if isinstance(value, dict):
        return scalar(first(value, "priceStr", "formatted", "amount", "value"))
    return scalar(value)


def parse_capture(payload: dict) -> Product:
    source = scalar(payload.get("source")).lower() or "temu"
    source_id = scalar(first(payload, "itemId", "goodsId", "sourceId"))
    source_url = scalar(first(payload, "afterUrl", "url", "sourceUrl"))
    if not source_id:
        match = re.search(r"(?:goods_id=|[/-]g-)(\d+)", source_url)
        source_id = match.group(1) if match else ""
    if not source_id:
        raise ValueError("缺少 itemId，无法可靠识别商品。请提供包含 itemId 的采集请求材料。")
    product = Product(source=source, source_id=source_id, site=scalar(payload.get("site")), source_url=source_url)
    page = payload.get("pageContent", "")
    if not isinstance(page, str):
        raise ValueError("pageContent 应为网页 HTML 字符串。")
    if payload.get("isZip") in (True, 1, "1", "true"):
        product.warnings.append("pageContent 标记为压缩材料，当前版本需转发压缩前的原始 HTML。")
        return product
    if source != "temu":
        product.warnings.append(f"当前版本仅提供 Temu 解析器；{source} 原始材料已保存，请手动补充商品。")
        return product
    docs, meta = documents(page)
    # 支持直接保存 rawData 的调试样本；仍使用同一套静态字段映射。
    if isinstance(payload.get("rawData"), dict):
        docs.append(payload["rawData"])
    goods_list = candidates(docs)
    exact = [goods for goods in goods_list if scalar(first(goods, "goodsId", "goods_id")) == source_id]
    unidentified = [goods for goods in goods_list if not scalar(first(goods, "goodsId", "goods_id"))]
    goods = (exact or unidentified or [{}])[0]
    if goods_list and not exact and not unidentified:
        product.warnings.append("页面商品 ID 与采集 itemId 不匹配，未采用可能属于推荐商品的数据。")
    product.title = scalar(first(goods, "goodsName", "goods_name")) or meta.get("og:title", "")
    product.description = scalar(first(goods, "description", "goodsDesc")) or meta.get("og:description", "")
    product.currency = scalar(first(goods, "currency", "currencyCode")).upper()
    product.images = image_urls(first(goods, "gallery", "goodsGallery", "images", default=[]))
    if not product.images:
        product.images = image_urls(meta.get("og:image", ""))
    product.detail_images = image_urls(first(goods, "detailGallery", "detailImages", default=[]))
    product.category = scalar(first(goods, "categoryName", "catName"))
    raw_skus = first(goods, "skuList", "sku_list", "skus", default=[])
    if isinstance(raw_skus, list):
        for item in raw_skus:
            if not isinstance(item, dict):
                continue
            specs = specs_for(item)
            images = image_urls(first(item, "thumbUrl", "imageUrl", "image", "thumb_url"))
            product.skus.append(SKU(
                platform_sku=scalar(first(item, "skuId", "sku_id", "id")), specs=specs,
                source_price=source_price(item), currency=scalar(first(item, "currency", "currencyCode")).upper(),
                image=images[0] if images else "",
            ))
    names = list(dict.fromkeys(name for sku in product.skus for name in sku.specs))
    if names:
        product.spec1_name = names[0]
        product.spec2_name = names[1] if len(names) > 1 else "规格2"
    for sku in product.skus:
        sku.spec1 = sku.specs.get(product.spec1_name, "")
        sku.spec2 = sku.specs.get(product.spec2_name, "")
    currencies = {sku.currency for sku in product.skus if sku.currency}
    if not product.currency and len(currencies) == 1:
        product.currency = next(iter(currencies))
    if not goods:
        product.warnings.append("未识别到 Temu 商品 JSON；目前仅保留页面公开摘要，请补充完整原始材料。")
    if not product.skus:
        product.warnings.append("未识别到实际 SKU，没有自动创建规格或库存。")
    if any(sku.source_price for sku in product.skus):
        product.warnings.append("来源价格仅供核对，原始单位可能为分或格式化文本；请自行填写实际导出售价。")
    if not product.currency:
        product.warnings.append("材料中没有明确币种，请人工确认，不能仅凭站点推定。")
    return product
