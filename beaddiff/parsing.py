# 2026-10-10：本次修改原因：解析 Temu 页面原始材料；不执行网页脚本、不猜测价格单位或库存。
from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from typing import Any

from .models import Product, SKU, valid_url
# 2026-10-11：本次修改原因：妙手简易描述来自属性，图文详情由正文和实际详情图构成。
from .content import attribute_description, detail_html


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
                # name = scalar(first(value, "parentSpecName", "parent_spec_name", "name", default=f"规格{index}"))
                # text = scalar(first(value, "specName", "spec_name", "value"))
                # 2026-10-11：本次修改原因：真实 Temu 规格使用 specKey/specValue，兼容原有结构。
                name = scalar(first(value, "specKey", "parentSpecName", "parent_spec_name", "name", default=f"规格{index}"))
                text = scalar(first(value, "specValue", "specName", "spec_name", "value"))
                if text:
                    result[name or f"规格{index}"] = text
    return result


def source_price(item: dict) -> str:
    # 2026-10-11：本次修改原因：优先读取当前售价的明确展示文本，不把分值或划线原价误当现价。
    rich = item.get("salePriceTextRich")
    if isinstance(rich, dict) and scalar(rich.get("ariaLabel")):
        return scalar(rich["ariaLabel"])
    rich_list = item.get("salePriceRich")
    if isinstance(rich_list, list):
        text = "".join(scalar(part.get("text")) for part in rich_list if isinstance(part, dict))
        if text:
            return text
    text = scalar(first(item, "salePriceStr", "priceStr", "priceDisplay", "formattedPrice"))
    if text:
        return text
    if "salePrice" not in item and scalar(item.get("normalPriceStr")):
        return scalar(item["normalPriceStr"])
    value = first(item, "priceStr", "priceDisplay", "formattedPrice", "salePrice", "price", "normalPrice")
    if isinstance(value, dict):
        return scalar(first(value, "priceStr", "formatted", "amount", "value"))
    return scalar(value)


# 2026-10-11：本次修改原因：SKU 售价展示元数据也可能明确提供币种，避免只依赖商品字段。
def source_currency(item: dict, fallback: str = "") -> str:
    direct = scalar(first(item, "currency", "currencyCode")).upper()
    if direct:
        return direct
    rich = item.get("salePriceTextRich", {})
    track = rich.get("track", {}) if isinstance(rich, dict) else {}
    impression = track.get("impr", {}) if isinstance(track, dict) else {}
    explicit = scalar(impression.get("curr")) if isinstance(impression, dict) else ""
    return explicit.upper() or fallback


# 2026-10-11：本次修改原因：在同一商品所属对象中取兄弟字段，避免跨商品抓取推荐 SKU 或类目。
def goods_context(docs: list[Any], goods: dict) -> dict:
    pending = [(document, 0) for document in docs]
    inspected = 0
    while pending and inspected < 100_000:
        value, depth = pending.pop()
        inspected += 1
        if depth > 30:
            continue
        if isinstance(value, dict):
            if value.get("goods") is goods:
                return value
            pending.extend((child, depth + 1) for child in reversed(list(value.values())) if isinstance(child, (dict, list)))
        elif isinstance(value, list):
            pending.extend((child, depth + 1) for child in reversed(value) if isinstance(child, (dict, list)))
    return {}


def attributes_for(values: Any) -> dict[str, str]:
    result = {}
    if not isinstance(values, list):
        return result
    for item in values:
        if not isinstance(item, dict):
            continue
        name = scalar(first(item, "key", "name", "propertyName"))
        parts = first(item, "values", "value", "propertyValue", default=[])
        parts = parts if isinstance(parts, list) else [parts]
        text = " / ".join(dict.fromkeys(scalar(part) for part in parts if scalar(part)))
        if name and text:
            result[name] = text
    return result


def detail_urls(goods: dict, context: dict) -> list[str]:
    values = image_urls(first(goods, "detailGallery", "detailImages", default=[]))
    values.extend(image_urls(context.get("productDetailFlatList", [])))
    detail = context.get("productDetail", {})
    floors = detail.get("floorList", []) if isinstance(detail, dict) else []
    if isinstance(floors, list):
        for floor in floors:
            if isinstance(floor, dict):
                values.extend(image_urls(floor.get("items", [])))
    return list(dict.fromkeys(values))


def video_url(goods: dict) -> str:
    url = scalar(first(goods, "videoUrl", "video_url"))
    if valid_url(url):
        return url
    gallery = first(goods, "gallery", "goodsGallery", default=[])
    if isinstance(gallery, list):
        for item in gallery:
            if not isinstance(item, dict):
                continue
            video = item.get("video", {})
            url = scalar(item.get("videoUrl")) or (scalar(video.get("videoUrl")) if isinstance(video, dict) else "")
            if valid_url(url):
                return url
    return ""


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
    # 2026-10-11：本次修改原因：真实采集材料的 SKU、详情和站点币种位于 store.goods 的同级。
    context = goods_context(docs, goods) if goods else {}
    local_info = context.get("localInfo", {})
    context_currency = scalar(local_info.get("currency")).upper() if isinstance(local_info, dict) else ""
    if goods_list and not exact and not unidentified:
        product.warnings.append("页面商品 ID 与采集 itemId 不匹配，未采用可能属于推荐商品的数据。")
    product.title = scalar(first(goods, "goodsName", "goods_name")) or meta.get("og:title", "")
    product.description = scalar(first(goods, "description", "goodsDesc")) or meta.get("og:description", "")
    # product.currency = scalar(first(goods, "currency", "currencyCode")).upper()
    product.currency = scalar(first(goods, "currency", "currencyCode")).upper() or context_currency
    product.images = image_urls(first(goods, "gallery", "goodsGallery", "images", default=[]))
    if not product.images:
        product.images = image_urls(meta.get("og:image", ""))
    # product.detail_images = image_urls(first(goods, "detailGallery", "detailImages", default=[]))
    product.detail_images = detail_urls(goods, context)
    product.attributes = attributes_for(first(goods, "goodsProperty", default=context.get("goodsProperty", [])))
    # 2026-10-11：本次修改原因：SEO 摘要继续保留，但不再充当妙手的属性简述和图文详情。
    product.simple_description = attribute_description(product.attributes)
    # product.description_html = detail_html(scalar(first(goods, "description", "goodsDesc")), product.detail_images)
    # 2026-10-11：本次修改原因：网页 SEO 摘要不属于妙手图文详情，详情字段只采用明确详情图。
    product.description_html = detail_html("", product.detail_images)
    for field, names in (("certificate", ("certificateUrl",)), ("instruction_manual", ("instructionManualUrl",)),
                         ("size_chart", ("sizeChartUrl",)), ("body_size_chart", ("bodySizeChartUrl",))):
        urls = image_urls(first(goods, *names))
        setattr(product, field, urls[0] if urls else "")
    # 2026-10-11：本次修改原因：保存明确提供的像素尺寸，仅用于图片核对，不转为包裹尺寸。
    galleries = first(goods, "gallery", "goodsGallery", default=[])
    details = context.get("productDetailFlatList", [])
    for items in (galleries, details):
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            urls = image_urls(item)
            width, height = scalar(item.get("width")), scalar(item.get("height"))
            if urls and width.isdecimal() and height.isdecimal() and int(width) > 0 and int(height) > 0:
                product.image_sizes[urls[0]] = f"{width} × {height}"
    product.video = video_url(goods)
    product.category = scalar(first(goods, "categoryName", "catName"))
    crumbs = context.get("crumbOptList", [])
    if not product.category and isinstance(crumbs, list):
        product.category = " / ".join(dict.fromkeys(
            scalar(first(item, "optName", "title")) for item in crumbs
            if isinstance(item, dict) and item.get("optType") in (1, 2, 3)
            and scalar(first(item, "optName", "title"))
        ))
    raw_skus = first(goods, "skuList", "sku_list", "skus", default=[])
    if not raw_skus and exact:
        raw_skus = context.get("sku", [])
    if isinstance(raw_skus, list):
        for item in raw_skus:
            if not isinstance(item, dict):
                continue
            item_goods_id = scalar(first(item, "goodsId", "goods_id"))
            if item_goods_id and item_goods_id != source_id:
                continue
            specs = specs_for(item)
            images = image_urls(first(item, "thumbUrl", "imageUrl", "image", "thumb_url"))
            product.skus.append(SKU(
                # platform_sku=scalar(first(item, "skuId", "sku_id", "id")), specs=specs,
                # 2026-10-11：本次修改原因：来源 skuId 与妙手的商家平台 SKU 是不同字段。
                source_sku_id=scalar(first(item, "skuId", "sku_id", "id")), specs=specs,
                # source_price=source_price(item), currency=scalar(first(item, "currency", "currencyCode")).upper(),
                # 2026-10-11：本次修改原因：来源价格、库存和限购单独留存；不自动填写自有库存、物流与售价。
                source_price=source_price(item),
                # currency=scalar(first(item, "currency", "currencyCode")).upper() or product.currency,
                # source_currency=scalar(first(item, "currency", "currencyCode")).upper() or product.currency,
                currency=source_currency(item, product.currency), source_currency=source_currency(item, product.currency),
                source_stock=scalar(item.get("stockQuantity")), purchase_limit=scalar(item.get("limitQuantity")),
                availability=scalar(item.get("isOnsale")),
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
