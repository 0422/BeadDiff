# 2026-10-11：本次修改原因：按官方公共采集箱契约映射字段，更新只覆盖人工/AI 已保存的改动，保留远端未编辑字段。
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re
from urllib.parse import unquote, urlsplit

# from .content import description_images, detail_html, with_detail_images
# 2026-10-11：本次修改原因：替换远端详情图片时保留未编辑正文和样式，不对整段远端 HTML 再次清洗。
from .content import description_images, detail_html
from .models import Product, SKU, valid_url
from .miaoshou_config import MiaoshouConfig


EDITABLE_KEYS = frozenset((
    "title", "itemNum", "notesText", "notes", "sourceAttrs", "price", "stock", "imgUrls", "weight",
    "packageLength", "packageWidth", "packageHeight", "colorPropName", "colorMap", "sizePropName", "sizeMap",
    "saleProp3Name", "saleProp3Map", "skuMap", "sizeChart", "mainImgVideoUrl", "mainImgAppVideoId",
    "productCertifications", "guideInfo", "sourceList",
))
SKU_FIELDS = {"platform_sku": "itemNum", "price": "price", "stock": "stock", "weight": "weight"}


def edited_fields(product: Product) -> set[str]:
    fields = set(product.manual_fields)
    if not product.erp_update_baseline:
        return fields
    baseline = Product.from_dict(product.erp_update_baseline)
    old_skus = {sku.identity: sku for sku in baseline.skus}
    current_skus = {sku.identity: sku for sku in product.skus}
    result = set()
    for name in fields:
        if name.startswith("attribute:"):
            key = name[len("attribute:"):]
            changed = baseline.attributes.get(key) != product.attributes.get(key)
        elif name.startswith("sku:"):
            identity, key = name[4:].rsplit(":", 1)
            old, new = old_skus.get(identity), current_skus.get(identity)
            changed = not old or not new or getattr(old, key, None) != getattr(new, key, None)
        elif name == "skus":
            changed = [sku.identity for sku in baseline.skus] != [sku.identity for sku in product.skus]
        else:
            changed = getattr(baseline, name, None) != getattr(product, name, None)
        if changed:
            result.add(name)
    return result


def number(value: str, label: str, minimum: str = "0", maximum: str = "99999.99") -> float:
    try:
        amount = Decimal(str(value).strip())
        if not amount.is_finite() or not Decimal(minimum) <= amount <= Decimal(maximum):
            raise ValueError
        return float(amount)
    except (InvalidOperation, ValueError):
        raise ValueError(f"{label}应为 {minimum}～{maximum} 的数值。") from None


def money(value: str, currency: str, config: MiaoshouConfig, label: str) -> float:
    code = currency.strip().upper()
    rate = config.cny_rates.get(code, "1" if code == "CNY" else "")
    if not rate:
        raise ValueError(f"{label}币种为 {code or '未知'}；请在妙手回传设置填写 1 {code or '该币种'} 对应多少 CNY。")
    try:
        amount = Decimal(str(value).strip()) * Decimal(str(rate))
        amount = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except InvalidOperation:
        raise ValueError(f"{label}不是明确数值，请填写数值金额。") from None
    return number(str(amount), label + "（换算人民币后）", "0.01")


def stock(value: str) -> int:
    if not str(value).isdecimal() or not 0 <= int(value) <= 99999:
        raise ValueError("库存须为 0～99999 的整数。")
    return int(value)


def dimensions(value: str) -> dict:
    values = re.split(r"\s*[xX×*]\s*", value.strip())
    if len(values) != 3:
        raise ValueError("包装尺寸应为长*宽*高，单位 CM。")
    return {key: number(part, "包装尺寸", "0", "99999") for key, part in zip(
        ("packageLength", "packageWidth", "packageHeight"), values)}


def sku_key(sku: SKU) -> str:
    if any(";" in value for value in (sku.spec1, sku.spec2)):
        raise ValueError("规格值不能包含分号，分号用于妙手 SKU 组合标识。")
    return ";" + ";".join((sku.spec1.strip(), sku.spec2.strip())) + ";"


def attachment_name(url: str, fallback: str) -> str:
    return unquote(urlsplit(url).path.rsplit("/", 1)[-1])[:255] or fallback


def _notes(product: Product) -> str:
    # 2026-10-11：本次修改原因：人工/AI 已保存的富文本是当前正文，不能把旧详情图重新追加，破坏主动删除和排布。
    if "description_html" in product.manual_fields:
        return product.description_html
    html = product.description_html or detail_html(product.description, [])
    # 2026-10-11：本次修改原因：仅修改独立详情图列表时按列表重建图片，保留现有正文。
    if "detail_images" in product.manual_fields:
        return re.sub(r"<img\b[^>]*>", "", html, flags=re.I) + detail_html("", product.detail_images)
    present = set(description_images(html))
    return html + detail_html("", [url for url in product.detail_images if url not in present])


def _supply_price(product: Product, config: MiaoshouConfig) -> float:
    if product.supply_price:
        return money(product.supply_price, product.currency, config, "货源价")
    if len(product.skus) == 1:
        sku = product.skus[0]
        raw = sku.source_price.strip()
        code = sku.source_currency.strip().upper()
        # 只识别明确的货币前缀和纯数值，不从销售币种猜测来源币种，不取区间最低价。
        prefixes = {"USD": ("USD", "US$", "$"), "CNY": ("CNY", "RMB", "¥", "￥")}
        for prefix in prefixes.get(code, (code,) if code else ()):
            if raw.upper().startswith(prefix):
                raw = raw[len(prefix):].strip()
                break
        if raw and code and re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", raw):
            return money(raw, code, config, "采集货源价")
    raise ValueError("单规格新增必须有货源价；请在编辑商品 → 货源链接填写货源价（使用商品当前币种）。")


def create_payload(product: Product, config: MiaoshouConfig) -> dict:
    result = {
        "title": product.title, "itemNum": product.main_code, "notesText": product.simple_description,
        "notes": _notes(product), "imgUrls": list(product.images),
        "sourceAttrs": [{"name": key, "value": value} for key, value in product.attributes.items()],
        "colorPropName": product.spec1_name if any(sku.spec1 for sku in product.skus) else "",
        "sizePropName": product.spec2_name if any(sku.spec2 for sku in product.skus) else "",
        "colorMap": {}, "sizeMap": {}, "skuMap": {},
    }
    for sku in product.skus:
        key = sku_key(sku)
        if key in result["skuMap"]:
            raise ValueError("规格组合重复，无法创建公共采集箱商品。")
        values = {"itemNum": sku.platform_sku, "price": money(sku.price, sku.currency or product.currency, config, "SKU 售价")}
        if sku.stock:
            values["stock"] = stock(sku.stock)
        if sku.weight:
            values["weight"] = number(sku.weight, "SKU 重量 KG", "0.01")
        if sku.dimensions:
            values.update(dimensions(sku.dimensions))
        result["skuMap"][key] = values
        if sku.spec1:
            color = result["colorMap"].setdefault(sku.spec1.strip(), {"name": sku.spec1.strip()})
            if sku.image:
                if color.get("imgUrl") and color["imgUrl"] != sku.image:
                    raise ValueError("同一规格1的 SKU 图片不同，请先统一规格图片；妙手图片按规格1绑定。")
                color.update(imgUrl=sku.image, imgUrls=[sku.image])
        elif sku.image:
            raise ValueError("SKU 图片需要规格1才能映射到妙手颜色图；请补充规格1或将图片加入主图。")
        if sku.spec2:
            result["sizeMap"][sku.spec2.strip()] = {"name": sku.spec2.strip()}
    if product.supply_price or len(product.skus) == 1:
        result["price"] = _supply_price(product, config)
    if product.skus and all(sku.stock for sku in product.skus):
        result["stock"] = stock(str(sum(stock(sku.stock) for sku in product.skus)))
    if product.package_weight:
        result["weight"] = number(product.package_weight, "包裹重量 KG", "0.01")
    if product.package_dimensions:
        result.update(dimensions(product.package_dimensions))
    for local, remote in (("size_chart", "sizeChart"), ("video", "mainImgVideoUrl")):
        if getattr(product, local):
            result[remote] = getattr(product, local)
    if product.certificate:
        result["productCertifications"] = [{"fileName": attachment_name(product.certificate, "产品认证"), "fileUrl": product.certificate}]
    if product.instruction_manual:
        result["guideInfo"] = {"productGuideFileName": attachment_name(product.instruction_manual, "产品说明书"),
                               "productGuideFileUrl": product.instruction_manual}
    if product.source_id or product.source_url:
        result["sourceList"] = [{"sourceItemId": product.source_id, "source": product.source, "sourceSite": product.site,
                                 "sourceItemUrl": product.source_url, "remark": product.source_remark}]
    validate_payload(result)
    return result


def match_sku_links(product: Product, origin: Product, remote: dict) -> dict[str, str]:
    links = {}
    used = set()
    original = {sku.identity: sku for sku in origin.skus if sku.identity}
    candidates = remote.get("skuMap") or {}
    colors, sizes = remote.get("colorMap") or {}, remote.get("sizeMap") or {}
    for sku in product.skus:
        source = original.get(sku.identity, sku)
        matches = []
        for key, value in candidates.items():
            if not isinstance(key, str) or not key.startswith(";") or not key.endswith(";"):
                continue
            parts = key[1:-1].split(";")
            if len(parts) > 2:
                continue
            parts += [""] * (2 - len(parts))
            names = (str((colors.get(parts[0]) or {}).get("name", parts[0])),
                     str((sizes.get(parts[1]) or {}).get("name", parts[1])))
            if names == (source.spec1.strip(), source.spec2.strip()):
                matches.append(key)
            elif source.platform_sku and value.get("itemNum") == source.platform_sku:
                matches.append(key)
        unique = list(dict.fromkeys(matches))
        if len(unique) == 1 and unique[0] not in used and sku.identity:
            links[sku.identity] = unique[0]
            used.add(unique[0])
    return links


def update_payload(product: Product, remote: dict, config: MiaoshouConfig) -> tuple[dict, dict[str, str]]:
    result = {key: deepcopy(value) for key, value in remote.items() if key in EDITABLE_KEYS}
    fields = edited_fields(product)
    unsupported = fields & {"category", "body_size_chart"}
    if unsupported:
        raise ValueError("公共采集箱写入契约不支持已修改的字段：" + "、".join(sorted(unsupported)) + "；本次未提交。")
    for local, target in (("title", "title"), ("main_code", "itemNum"), ("simple_description", "notesText"),
                          ("images", "imgUrls"), ("video", "mainImgVideoUrl"), ("size_chart", "sizeChart")):
        if local in fields:
            result[target] = deepcopy(getattr(product, local))
    if fields & {"description", "description_html", "detail_images"}:
        if "description_html" in fields:
            # result["notes"] = _notes(product) if product.description_html else detail_html("", product.detail_images)
            # 2026-10-11：本次修改原因：明确编辑/清空富文本时完全尊重当前 HTML，不从旧图片列表恢复被删除内容。
            result["notes"] = product.description_html
        elif "description" in fields:
            images = product.detail_images if "detail_images" in fields else description_images(result.get("notes", ""))
            result["notes"] = detail_html(product.description, images)
        else:
            # result["notes"] = with_detail_images(result.get("notes", ""), product.detail_images)
            # 2026-10-11：本次修改原因：只替换图片标签，正文和样式完整保留。
            result["notes"] = re.sub(r"<img\b[^>]*>", "", result.get("notes") or "", flags=re.I) + detail_html("", product.detail_images)
    attrs = [name[len("attribute:"):] for name in fields if name.startswith("attribute:")]
    if attrs or "attributes" in fields:
        attrs = list(set(attrs) | (set(product.attributes) if "attributes" in fields else set()))
        rows = [row for row in result.get("sourceAttrs", []) if row.get("name") not in attrs]
        rows.extend({"name": key, "value": product.attributes[key]} for key in attrs if key in product.attributes)
        result["sourceAttrs"] = rows
    for local, target in (("package_weight", "weight"), ("supply_price", "price")):
        if local in fields:
            value = getattr(product, local)
            if not value:
                # result.pop(target, None)
                # 2026-10-11：本次修改原因：官方数值字段没有明确的清空契约，不能遗漏字段后误报已清空。
                raise ValueError("已清空货源价或重量；当前接口要求有效数值，请填写后回传。")
            else:
                result[target] = money(value, product.currency, config, "货源价") if local == "supply_price" else number(value, "重量 KG", "0.01")
    if "package_dimensions" in fields:
        # 2026-10-11：本次修改原因：不把省略字段冒充远端已清空。
        if not product.package_dimensions:
            raise ValueError("已清空包裹尺寸，请填写有效长*宽*高后回传。")
        for key in ("packageLength", "packageWidth", "packageHeight"):
            result.pop(key, None)
        if product.package_dimensions:
            result.update(dimensions(product.package_dimensions))
    if "certificate" in fields:
        # 2026-10-11：本次修改原因：本机只有单附件编辑入口，多附件原商品必须先在妙手处理，避免覆盖隐藏附件。
        if len(result.get("productCertifications") or []) > 1:
            raise ValueError("妙手原商品包含多份认证附件，请先在妙手处理；不能用本机单附件入口覆盖全部认证。")
        result["productCertifications"] = ([{"fileName": attachment_name(product.certificate, "产品认证"), "fileUrl": product.certificate}]
                                            if product.certificate else [])
    if "instruction_manual" in fields:
        result["guideInfo"] = {"productGuideFileName": attachment_name(product.instruction_manual, "产品说明书"),
                               # "productGuideFileUrl": product.instruction_manual} if product.instruction_manual else {}
                               # 2026-10-11：本次修改原因：明确提交空字符串清空单附件信息，不以缺省对象代替。
                               "productGuideFileUrl": product.instruction_manual}
    if fields & {"source_url", "source_remark"}:
        rows = result.get("sourceList", [])
        matches = [row for row in rows if str(row.get("sourceItemId", "")) == product.source_id]
        if len(matches) != 1:
            raise ValueError("原商品货源条目无法唯一匹配，不能覆盖其货源链接/备注；本次未提交。")
        if "source_url" in fields:
            matches[0]["sourceItemUrl"] = product.source_url
        if "source_remark" in fields:
            matches[0]["remark"] = product.source_remark
    links = dict(product.erp_sku_links)
    # 未核实的规格重构不以猜测的键替换全部 SKU；售价、库存、物流和颜色图使用已关联键增量更新。
    restructure = "skus" in fields or bool(fields & {"spec1_name", "spec2_name"}) or any(
        # name.startswith("sku:") and name.rsplit(":", 1)[-1] in {"spec1", "spec2", "specs"} for name in fields)
        # 2026-10-11：本次修改原因：编辑器规范化 specs 字典不一定改变实际规格；以维度名及规格值识别结构修改。
        name.startswith("sku:") and name.rsplit(":", 1)[-1] in {"spec1", "spec2"} for name in fields)
    if restructure:
        raise ValueError("已修改规格结构/维度；当前回传仅支持既有规格的售价、库存、物流和规格图片，请先在妙手调整规格并重新关联。")
    for sku in product.skus:
        # selected = {name.rsplit(":", 1)[-1] for name in fields if name.startswith(f"sku:{sku.identity}:")}
        # 2026-10-11：本次修改原因：来源 SKU ID 可以带冒号，必须按最后一个冒号分离字段，避免前缀相似 SKU 误匹配。
        selected = {name.rsplit(":", 1)[-1] for name in fields
                    if name.startswith("sku:") and name[4:].rsplit(":", 1)[0] == sku.identity}
        if "currency" in fields or "currency" in selected:
            selected.add("price")
        selected &= {"platform_sku", "price", "stock", "weight", "dimensions", "image"}
        if not selected:
            continue
        # 2026-10-11：本次修改原因：稳定来源身份不唯一时不能可靠对应一条远端 SKU。
        if not sku.identity or sum(other.identity == sku.identity for other in product.skus) != 1:
            raise ValueError("SKU 缺少唯一的来源身份，无法安全更新。")
        key = links.get(sku.identity, "")
        if not key or key not in (result.get("skuMap") or {}):
            raise ValueError(f"SKU {sku.identity or sku.platform_sku} 未可靠关联原商品规格，请重新关联并核对规格；本次未提交。")
        values = result["skuMap"][key]
        # 2026-10-11：本次修改原因：远端规格在关联后发生更名时须重新核对，不能沿用被重新使用的键更新错 SKU。
        parts = key[1:-1].split(";")
        parts += [""] * (2 - len(parts))
        names = (str(((result.get("colorMap") or {}).get(parts[0]) or {}).get("name", parts[0])),
                 str(((result.get("sizeMap") or {}).get(parts[1]) or {}).get("name", parts[1])))
        if len(parts) != 2 or names != (sku.spec1.strip(), sku.spec2.strip()):
            raise ValueError("妙手原商品规格与本机不一致，请重新核对关联后回传。")
        for local, target in SKU_FIELDS.items():
            if local not in selected:
                continue
            value = getattr(sku, local)
            if not value and local != "platform_sku":
                # values.pop(target, None)
                # 2026-10-11：本次修改原因：空库存不等于 0，重量/售价不能用省略字段冒充清空。
                raise ValueError(f"SKU 的 {local} 已清空，请填写有效数值（无库存填 0）。")
            elif local == "price":
                values[target] = money(value, sku.currency or product.currency, config, "SKU 售价")
            elif local == "stock":
                values[target] = stock(value)
            elif local == "weight":
                values[target] = number(value, "SKU 重量 KG", "0.01")
            else:
                values[target] = value
        if "dimensions" in selected:
            # 2026-10-11：本次修改原因：当前接口未明确数值字段省略是否清空，阻止不确定的清空回传。
            if not sku.dimensions:
                raise ValueError("SKU 尺寸已清空，请填写有效长*宽*高。")
            for target in ("packageLength", "packageWidth", "packageHeight"):
                values.pop(target, None)
            if sku.dimensions:
                values.update(dimensions(sku.dimensions))
        if "image" in selected:
            color_key = key[1:-1].split(";")[0]
            colors = result.get("colorMap") or {}
            if not color_key or color_key not in colors:
                raise ValueError("该 SKU 未关联颜色规格，不能更新颜色图。")
            peers = [other for other in product.skus if links.get(other.identity, "")[1:-1].split(";")[0] == color_key]
            if any(other.image != sku.image for other in peers):
                raise ValueError("同一颜色规格的 SKU 图片不同，请统一后回传。")
            colors[color_key].update(imgUrl=sku.image, imgUrls=[sku.image] if sku.image else [])
    if "video" in fields:
        result.pop("mainImgAppVideoId", None)
    if "currency" in fields and product.supply_price:
        result["price"] = money(product.supply_price, product.currency, config, "货源价")
    validate_payload(result)
    return result, links


def picture_urls(payload: dict) -> list[str]:
    # urls = list(payload.get("imgUrls") or []) + description_images(payload.get("notes", ""))
    # 2026-10-11：本次修改原因：兼容远端空的富文本描述。
    urls = list(payload.get("imgUrls") or []) + description_images(payload.get("notes") or "")
    for color in (payload.get("colorMap") or {}).values():
        urls.extend(color.get("imgUrls") or [])
        if color.get("imgUrl"):
            urls.append(color["imgUrl"])
    if payload.get("sizeChart"):
        urls.append(payload["sizeChart"])
    return list(dict.fromkeys(urls))


def validate_payload(payload: dict) -> None:
    if not isinstance(payload.get("title"), str) or not payload["title"].strip():
        raise ValueError("公共采集箱产品标题不能为空。")
    limits = {"title": 255, "itemNum": 255, "notesText": 65536, "notes": 100000,
              "sizeChart": 255, "mainImgVideoUrl": 255, "colorPropName": 255, "sizePropName": 255}
    for key, limit in limits.items():
        if len(str(payload.get(key, ""))) > limit:
            raise ValueError(f"{key} 超过妙手允许的 {limit} 个字符。")
    if len(payload.get("imgUrls") or []) > 15:
        raise ValueError("公共采集箱最多支持 15 张主图，请调整顺序和数量。")
    if len(payload.get("sourceList") or []) > 10 or len(payload.get("productCertifications") or []) > 10:
        raise ValueError("货源/认证列表最多支持 10 条。")
    for row in payload.get("sourceAttrs") or []:
        if len(str(row.get("name", ""))) > 255 or len(str(row.get("value", ""))) > 255:
            raise ValueError("商品属性名和属性值最多 255 个字符。")
    for color in (payload.get("colorMap") or {}).values():
        if len(color.get("imgUrls") or []) > 10 or len(str(color.get("name", ""))) > 255:
            raise ValueError("颜色规格名称最多 255 字，每组最多 10 张图片。")
    urls = picture_urls(payload)
    urls += [payload[key] for key in ("mainImgVideoUrl",) if payload.get(key)]
    urls += [row.get("fileUrl", "") for row in payload.get("productCertifications") or []]
    guide = payload.get("guideInfo") or {}
    # 2026-10-11：本次修改原因：校验来源和附件字符串长度，在发送前给出可理解的原因。
    if any(len(str(value)) > 255 for row in payload.get("sourceList") or [] for value in row.values()):
        raise ValueError("货源 ID、平台、站点、链接、备注最多 255 个字符。")
    if any(len(str(value)) > 255 for value in guide.values()):
        raise ValueError("说明书名称和链接最多 255 个字符。")
    if any(len(str(row.get("fileName", ""))) > 255 for row in payload.get("productCertifications") or []):
        raise ValueError("认证附件名称最多 255 个字符。")
    if guide.get("productGuideFileUrl"):
        urls.append(guide["productGuideFileUrl"])
    if any(not valid_url(url) for url in urls if url):
        raise ValueError("图片/附件必须是妙手可访问的 HTTP/HTTPS 链接；本机白底图和 AI 生成图请先托管并替换链接。")
    # 单规格货源价在文字说明中为必填，不能因为 JSON required 仅写 title 就遗漏。
    if len(payload.get("skuMap") or {}) == 1 and "price" not in payload:
        raise ValueError("单规格商品缺少货源价，请在货源链接栏目填写后回传。")
