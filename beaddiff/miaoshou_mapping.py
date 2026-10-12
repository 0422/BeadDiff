# 2026-10-11：本次修改原因：按官方公共采集箱契约映射字段，更新只覆盖人工/AI 已保存的改动，保留远端未编辑字段。
from __future__ import annotations

# from copy import deepcopy
# 2026-10-12：本次修改原因：数量/格式校验只需浅副本调整文案标记，避免反复复制完整 ERP 快照。
from copy import copy, deepcopy
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re
from urllib.parse import unquote, urlsplit
# 2026-10-12：本次修改原因：从 Temu 商品链接读取明确的商品 ID，去除超长追踪参数而不截断链接。
from urllib.parse import parse_qs

# from .content import description_images, detail_html, with_detail_images
# 2026-10-11：本次修改原因：替换远端详情图片时保留未编辑正文和样式，不对整段远端 HTML 再次清洗。
from .content import description_images, detail_html
from .models import Product, SKU, valid_url
from .miaoshou_config import MiaoshouConfig
# 2026-10-12：本次修改原因：草稿校验允许受管理的白底图/AI 本机素材，回传阶段仍要求网络图片。
from .assets import valid_media_url


# 2026-10-12：本次修改原因：仅改变表单中实际编辑的字段，防止 Qt 规范化 HTML/空格/规格字典连带覆盖远端数据。
def preserve_unedited_form(original: Product, initial: Product, current: Product) -> Product:
    old, displayed, changed = original.business_content(), initial.business_content(), current.business_content()
    for name in old:
        if name != "skus" and changed[name] == displayed[name]:
            setattr(current, name, deepcopy(getattr(original, name)))
    originals = {sku.identity: sku for sku in original.skus if sku.identity}
    initials = {sku.identity: sku for sku in initial.skus if sku.identity}
    for sku in current.skus:
        previous, form = originals.get(sku.identity), initials.get(sku.identity)
        if previous and form:
            for name in SKU.__dataclass_fields__:
                if getattr(sku, name) == getattr(form, name):
                    setattr(sku, name, deepcopy(getattr(previous, name)))
    return current


# 2026-10-12：本次修改原因：保留旧的“只检查本次改动字段”实现供追溯；它会漏过采集时已有的 16 张主图。
# def draft_limit_issues(product: Product, original: Product | None = None) -> list[str]:
#     result = []
#     def edited(name: str) -> bool:
#         return original is None or getattr(product, name) != getattr(original, name)
#     limits = {"title": ("产品标题", 255), "main_code": ("产品主编号", 255),
#               "simple_description": ("简易描述", 65536), "description_html": ("详细描述 HTML", 100000),
#               "spec1_name": ("规格1维度名称", 255), "spec2_name": ("规格2维度名称", 255),
#               "source_remark": ("货源备注", 255)}
#     for name, (caption, limit) in limits.items():
#         count = len(getattr(product, name))
#         if edited(name) and count > limit:
#             result.append(f"{caption}为 {count} 个字符，公共采集箱最多支持 {limit} 个字符")
#     if edited("images") and len(product.images) > 15:
#         result.append(f"主图共 {len(product.images)} 张，公共采集箱最多支持 15 张，请调整数量和顺序")
#     if edited("source_url") and len(_source_item_url(product.source_url)) > 255:
#         result.append("货源链接超过 255 个字符，请填写可访问的商品短链接")
#     if edited("attributes") and any(len(key) > 255 or len(value) > 255 for key, value in product.attributes.items()):
#         result.append("属性名称和属性值最多支持 255 个字符")
#     if edited("supply_price") and product.supply_price:
#         try:
#             number(product.supply_price, "回传货源价", "0.01")
#         except ValueError as error:
#             result.append(str(error))
#     if edited("skus"):
#         for sku in product.skus:
#             if any(len(value) > 255 for value in (sku.platform_sku, sku.spec1, sku.spec2)):
#                 result.append("SKU 编号及规格名称最多支持 255 个字符")
#                 break
#         groups: dict[str, set[str]] = {}
#         for sku in product.skus:
#             if sku.image:
#                 groups.setdefault(sku.spec1, set()).add(sku.image)
#         for name, urls in groups.items():
#             if len(urls) > 10:
#                 result.append(f"规格1「{name}」有 {len(urls)} 张图片，每组最多支持 10 张")
#     return result


# 2026-10-12：本次修改原因：保存、审核、回传和图片数量提示共用接口上限，避免多个入口规则不一致。
MAX_MAIN_IMAGES = 15
MAX_SPEC_IMAGES = 10
MAX_SOURCE_ROWS = 10
MAX_CERTIFICATES = 10
TEXT_LIMITS = {"title": 255, "itemNum": 255, "notesText": 65536, "notes": 100000,
               "sizeChart": 255, "mainImgVideoUrl": 255, "colorPropName": 255, "sizePropName": 255,
               "saleProp3Name": 255}


# 2026-10-12：本次修改原因：所有当前字段每次保存均检查；仅保留 API 原有空值/零物流占位，不豁免超限长度和数量。
def draft_limit_issues(product: Product, original: Product | None = None) -> list[str]:
    result = []
    baseline = Product.from_dict(product.erp_import_baseline) if product.erp_imported and product.erp_import_baseline else None
    original_skus = {sku.identity: sku for sku in baseline.skus} if baseline else {}

    def length(value: str, caption: str, limit: int = 255) -> None:
        if len(value) > limit:
            result.append(f"{caption}为 {len(value)} 个字符，公共采集箱最多支持 {limit} 个字符")

    def media(value: str, caption: str) -> None:
        # if value and not valid_media_url(value):
        # 2026-10-12：本次修改原因：隐藏远端字段的非字符串地址应产生提示，不能导致商品库状态计算失败。
        if value and (not isinstance(value, str) or not valid_media_url(value)):
            result.append(f"{caption}地址无效或本机素材已被移动，请使用 HTTP/HTTPS 链接或受管理的本机图片")

    def numeric(value: str, caption: str, minimum: str, maximum: str | None, old: str | None = None) -> None:
        if not value:
            return
        try:
            amount = Decimal(value)
            preserved_zero = old is not None and value == old and amount == 0
            lower = Decimal("0") if preserved_zero else Decimal(minimum)
            if not amount.is_finite() or amount < lower or maximum is not None and amount > Decimal(maximum):
                raise ValueError
        except (InvalidOperation, ValueError):
            boundary = f"～{maximum}" if maximum is not None else " 及以上"
            result.append(f"{caption}须为 {minimum}{boundary} 的有效数值")

    def logistics(value: str, caption: str, old: str | None = None) -> None:
        if not value:
            return
        try:
            parts = re.split(r"\s*[xX×*]\s*", value.strip())
            numbers = [Decimal(part) for part in parts]
            allow_zero = old is not None and old == value
            if len(parts) != 3 or any(not item.is_finite() or item < 0 or item > 99999
                                      or item == 0 and not allow_zero for item in numbers):
                raise ValueError
        except (InvalidOperation, ValueError):
            result.append(f"{caption}须为长*宽*高，三个数值大于 0 且不超过 99999，单位 CM")

    captions = {"title": ("产品标题", "title"), "main_code": ("产品主编号", "itemNum"),
                "simple_description": ("简易描述", "notesText"), "description_html": ("详细描述 HTML", "notes"),
                "spec1_name": ("规格1维度名称", "colorPropName"), "spec2_name": ("规格2维度名称", "sizePropName"),
                "video": ("视频链接", "mainImgVideoUrl"), "size_chart": ("产品尺码表链接", "sizeChart")}
    for name, (caption, remote_key) in captions.items():
        length(getattr(product, name), caption, TEXT_LIMITS[remote_key])
    if len(product.images) > MAX_MAIN_IMAGES:
        result.append(f"主图共 {len(product.images)} 张，公共采集箱最多支持 {MAX_MAIN_IMAGES} 张，超出 {len(product.images) - MAX_MAIN_IMAGES} 张，请在产品图片中移除或调整用途")
    for name, caption in (("source_id", "货源 ID"), ("source", "货源平台"), ("site", "货源站点"),
                          ("source_remark", "货源备注"), ("certificate", "认证附件链接"),
                          ("instruction_manual", "说明书链接")):
        length(getattr(product, name), caption)
    length(_source_item_url(product.source_url), "货源链接")
    if product.source_url and not valid_url(product.source_url):
        result.append("货源链接须为有效的 HTTP/HTTPS 地址或留空")
    for name, value in product.attributes.items():
        length(name, f"属性「{name[:30]}」名称")
        length(value, f"属性「{name[:30]}」值")
    # 2026-10-12：本次修改原因：检查实际图文输出长度，避免正文和详情图单独不过长但组合后超过接口上限。
    # notes_product = Product.from_dict(product.to_dict())
    # 2026-10-12：本次修改原因：仅替换副本的 manual_fields，不复制未修改的远端附件和原始字段。
    notes_product = copy(product)
    if original:
        if product.description_html != original.description_html:
            notes_product.manual_fields = [*notes_product.manual_fields, "description_html"]
        elif product.detail_images != original.detail_images:
            notes_product.manual_fields = [name for name in notes_product.manual_fields if name != "description_html"] + ["detail_images"]
    notes = _notes(notes_product)
    if notes != product.description_html:
        length(notes, "回传图文详情（正文及图片合并后）", TEXT_LIMITS["notes"])
    for index, url in enumerate(product.images, 1):
        media(url, f"主图 {index}")
    for index, url in enumerate(list(dict.fromkeys(product.detail_images + description_images(notes))), 1):
        media(url, f"详情图 {index}")
    for name, caption in (("size_chart", "产品尺码表"), ("body_size_chart", "身体尺码表")):
        media(getattr(product, name), caption)
    for name, caption in (("video", "视频"), ("certificate", "认证附件"), ("instruction_manual", "说明书")):
        value = getattr(product, name)
        if value and not valid_url(value):
            result.append(f"{caption}须为有效的 HTTP/HTTPS 链接或留空")
    if product.currency and (len(product.currency) != 3 or not product.currency.isascii() or not product.currency.isalpha()):
        result.append("商品币种须为三位英文字母，例如 USD、CNY")
    numeric(product.supply_price, "回传货源价", "0.01", "99999.99" if product.currency.upper() == "CNY" else None,
            baseline.supply_price if baseline else None)
    numeric(product.package_weight, "包裹重量 KG", "0.01", "99999.99", baseline.package_weight if baseline else None)
    logistics(product.package_dimensions, "包裹尺寸", baseline.package_dimensions if baseline else None)
    groups: dict[str, set[str]] = {}
    for index, sku in enumerate(product.skus, 1):
        prefix = f"SKU {index}"
        previous = original_skus.get(sku.identity)
        for value, caption in ((sku.platform_sku, "商家编号"), (sku.spec1, "规格1值"), (sku.spec2, "规格2值")):
            length(value, prefix + caption)
        if not product.erp_imported and any(";" in value for value in (sku.spec1, sku.spec2)):
            result.append(prefix + "规格值不能包含分号，分号用于妙手 SKU 组合标识")
        if sku.currency and (len(sku.currency) != 3 or not sku.currency.isascii() or not sku.currency.isalpha()
                             or product.currency and sku.currency.upper() != product.currency.upper()):
            result.append(prefix + "币种须为三位英文字母并与商品币种一致")
        numeric(sku.price, prefix + "售价", "0.01", "99999.99" if (sku.currency or product.currency).upper() == "CNY" else None,
                previous.price if previous else None)
        numeric(sku.weight, prefix + "重量 KG", "0.01", "99999.99", previous.weight if previous else None)
        logistics(sku.dimensions, prefix + "尺寸", previous.dimensions if previous else None)
        if sku.stock:
            try:
                stock(sku.stock)
            except ValueError as error:
                result.append(prefix + str(error))
        media(sku.image, prefix + "图片")
        if sku.image:
            groups.setdefault(sku.spec1.strip(), set()).add(sku.image)
            if not product.erp_imported and not sku.spec1.strip():
                result.append(prefix + "图片需要规格1才能回传，请补充规格1或将图片加入主图")
    if not product.erp_imported and product.skus and all(sku.stock and sku.stock.isdecimal() for sku in product.skus):
        if sum(int(sku.stock) for sku in product.skus) > 99999:
            result.append("SKU 库存合计超过商品库存上限 99999，请调整库存")
    for name, urls in groups.items():
        if len(urls) > MAX_SPEC_IMAGES:
            result.append(f"规格1「{name}」有 {len(urls)} 张图片，每组最多支持 {MAX_SPEC_IMAGES} 张")
    # 2026-10-12：本次修改原因：API 完整快照中的隐藏套图、多货源和多附件也检查，避免仅验证界面显示的首项。
    if product.erp_imported and product.erp_remote_snapshot:
        snapshot = deepcopy(product.erp_remote_snapshot)
        changes: dict[str, list[SKU]] = {}
        for sku in product.skus:
            previous = original_skus.get(sku.identity)
            if previous and sku.image != previous.image:
                key = product.erp_sku_links.get(sku.identity, "")
                if len(_remote_sku_parts(key)) == 2:
                    changes.setdefault(_remote_sku_parts(key)[0], []).append(sku)
        try:
            image_product = Product.from_dict(product.to_dict())
            image_product.erp_update_baseline = deepcopy(product.erp_import_baseline)
            _update_color_images(image_product, snapshot, product.erp_sku_links, changes)
        except ValueError as error:
            result.append(str(error))
        for map_key, caption in (("colorMap", "规格1"), ("sizeMap", "规格2"), ("saleProp3Map", "规格3")):
            for option in (snapshot.get(map_key) or {}).values():
                # 2026-10-12：本次修改原因：远端未使用的规格选项也可能结构异常，状态列表应提示而非崩溃。
                if not isinstance(option, dict):
                    result.append(caption + "选项结构无法识别，请在妙手检查原商品")
                    continue
                length(str(option.get("name") or ""), caption + "名称")
                if map_key == "colorMap":
                    # 2026-10-12：本次修改原因：远端未显示的图片数组结构也校验，异常项不会造成 len/list 操作崩溃。
                    if not isinstance(option.get("imgUrls") or [], list):
                        result.append("原商品规格图片组不是图片列表，请在妙手检查原商品")
                        continue
                    count = len(option.get("imgUrls") or [])
                    if count > MAX_SPEC_IMAGES:
                        result.append(f"规格1「{str(option.get('name') or '')[:40]}」远端图片组合并后共 {count} 张，每组最多支持 {MAX_SPEC_IMAGES} 张，请在妙手整理图片组")
                    for address in list(option.get("imgUrls") or []) + [option.get("imgUrl") or ""]:
                        media(address, "远端规格图片")
        length(str(snapshot.get("saleProp3Name") or ""), "规格3维度名称", TEXT_LIMITS["saleProp3Name"])
        sources = snapshot.get("sourceList") or []
        if len(sources) > MAX_SOURCE_ROWS:
            result.append(f"货源共 {len(sources)} 条，公共采集箱最多支持 {MAX_SOURCE_ROWS} 条")
        for index, row in enumerate(sources, 1):
            first = index == 1
            for key, value in row.items():
                if first and key in {"sourceItemUrl", "remark"}:
                    continue
                text = str(value or "")
                length(_source_item_url(text) if key == "sourceItemUrl" else text, f"第 {index} 条货源 {key}")
        certificates = snapshot.get("productCertifications") or []
        if len(certificates) > MAX_CERTIFICATES:
            result.append(f"认证附件共 {len(certificates)} 条，公共采集箱最多支持 {MAX_CERTIFICATES} 条")
        for index, row in enumerate(certificates, 1):
            if len(certificates) == 1 and product.certificate != (baseline.certificate if baseline else ""):
                continue
            length(str(row.get("fileName") or ""), f"认证附件 {index} 名称")
            length(str(row.get("fileUrl") or ""), f"认证附件 {index} 链接")
            # if row.get("fileUrl") and not valid_url(row["fileUrl"]):
            # 2026-10-12：本次修改原因：未显示附件的类型异常转为可理解校验提示。
            if row.get("fileUrl") and not valid_url(str(row["fileUrl"])):
                result.append(f"认证附件 {index} 链接无效")
        # 2026-10-12：本次修改原因：原属性重复/空名称和说明书元数据不会全部显示在 UI，仍要校验实际保留的内容。
        attributes = snapshot.get("sourceAttrs") or []
        changed_attributes = {name for name in set(product.attributes) | set(baseline.attributes if baseline else {})
                              if baseline is None or product.attributes.get(name) != baseline.attributes.get(name)}
        for row in attributes:
            if row.get("name") not in changed_attributes:
                length(str(row.get("name") or ""), "原商品属性名称")
                length(str(row.get("value") or ""), "原商品属性值")
        if baseline is None or product.instruction_manual == baseline.instruction_manual:
            for key, value in (snapshot.get("guideInfo") or {}).items():
                length(str(value or ""), f"说明书 {key}")
    return list(dict.fromkeys(result))


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


# 2026-10-12：本次修改原因：保留远端组合键原文，空第三槽位不应被误认成实际第三规格而阻止既有 SKU 修改。
def _remote_sku_parts(key: str) -> list[str]:
    if not key.startswith(";") or not key.endswith(";"):
        return []
    parts = key[1:-1].split(";")
    if len(parts) == 3 and not parts[2]:
        parts = parts[:2]
    if len(parts) == 1:
        parts.append("")
    return parts


def attachment_name(url: str, fallback: str) -> str:
    return unquote(urlsplit(url).path.rsplit("/", 1)[-1])[:255] or fallback


# 2026-10-12：本次修改原因：仅缩短可识别的 Temu 超长商品链接，保留地区/语言和商品 ID；不改写本地原链接。
def _source_item_url(url: str) -> str:
    if len(url) <= 255:
        return url
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
    except ValueError:
        return url
    if parts.scheme not in {"http", "https"} or not (host == "temu.com" or host.endswith(".temu.com")):
        return url
    identifiers = parse_qs(parts.query, keep_blank_values=True).get("goods_id", [])
    path_id = re.search(r"(?:/|-)g-([0-9]+)\.html$", unquote(parts.path))
    if path_id:
        identifiers.append(path_id.group(1))
    if not identifiers or any(not re.fullmatch(r"[0-9]+", value) for value in identifiers):
        return url
    if len(set(identifiers)) != 1:
        return url
    locale = re.match(r"/([a-z]{2}(?:-[a-z]{2,4}){0,2})/", parts.path, flags=re.I)
    prefix = f"/{locale.group(1)}" if locale else ""
    return f"https://{host}{prefix}/goods.html?goods_id={identifiers[0]}"


# 2026-10-12：本次修改原因：新增和更新共用货源链接规范化，只修改待提交的请求副本。
def _prepare_source_links(payload: dict) -> None:
    for row in payload.get("sourceList") or []:
        value = row.get("sourceItemUrl")
        if isinstance(value, str):
            row["sourceItemUrl"] = _source_item_url(value)


# 2026-10-12：本次修改原因：图片仍按规格1绑定；更新合并不同尺码图片并保留远端附图，只删除可明确识别且未被其他 SKU 使用的旧图。
def _update_color_images(product: Product, payload: dict, links: dict[str, str], changes: dict[str, list[SKU]]) -> None:
    baseline = Product.from_dict(product.erp_update_baseline) if product.erp_update_baseline else None
    old_skus = {sku.identity: sku for sku in baseline.skus} if baseline else {}
    for color_key, changed_skus in changes.items():
        color = payload["colorMap"][color_key]
        name = str(color.get("name", color_key))
        peers = [sku for sku in product.skus if sku.spec1.strip() == name]
        for peer in peers:
            key = links.get(peer.identity, "")
            # parts = key[1:-1].split(";") if key.startswith(";") and key.endswith(";") else []
            # 2026-10-12：本次修改原因：颜色图关联识别远端空第三槽位，仍原样使用远端 SKU 键。
            parts = _remote_sku_parts(key)
            if (not peer.identity or sum(sku.identity == peer.identity for sku in product.skus) != 1
                    or len(parts) != 2 or parts[0] != color_key or key not in (payload.get("skuMap") or {})
                    or str(((payload.get("sizeMap") or {}).get(parts[1]) or {}).get("name", parts[1])) != peer.spec2.strip()):
                raise ValueError("同一规格1的 SKU 未可靠关联原商品规格，请重新核对关联后更新图片。")
        local_images = list(dict.fromkeys(sku.image for sku in peers if sku.image))
        remote_images = list(dict.fromkeys(
            ([color["imgUrl"]] if color.get("imgUrl") else []) + list(color.get("imgUrls") or [])))
        replacements = {}
        for sku in changed_skus:
            old = old_skus.get(sku.identity)
            if not sku.image and (old is None or old.image and old.image not in remote_images):
                raise ValueError("无法可靠识别该 SKU 对应的远端旧图，不能单独清空；妙手图片按规格1共享，请先在妙手处理图片组。")
            if old and old.image and old.image in remote_images and old.image not in local_images:
                replacements.setdefault(old.image, []).append(sku.image)
        gallery = []
        for image in remote_images:
            gallery.extend(replacements.get(image, [image]))
        gallery.extend(local_images)
        gallery = list(dict.fromkeys(image for image in gallery if image))
        primary = color.get("imgUrl") or (remote_images[0] if remote_images else "")
        if primary in replacements:
            primary = next((image for image in replacements[primary] if image), "")
        # 2026-10-12：本次修改原因：没有旧图精确对应时将明确编辑的新图用作共享主图，旧远端图仍保留为附图。
        untracked_changes = [sku.image for sku in changed_skus if sku.image
                             and (sku.identity not in old_skus or old_skus[sku.identity].image not in remote_images)]
        if untracked_changes:
            primary = untracked_changes[0]
        primary = primary or (gallery[0] if gallery else "")
        gallery = list(dict.fromkeys(([primary] if primary else []) + gallery))
        color.update(imgUrl=primary, imgUrls=gallery)


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
    # raise ValueError("单规格新增必须有货源价；请在编辑商品 → 货源链接填写货源价（使用商品当前币种）。")
    # 2026-10-12：本次修改原因：实际多规格新增也要求顶层价格，不能用 SKU 销售价或区间最低价冒充货源价。
    raise ValueError("新增商品必须有独立货源价；请在编辑商品 → 货源链接填写回传货源价（使用商品当前币种），SKU 售价不能代填。")


def create_payload(product: Product, config: MiaoshouConfig) -> dict:
    # 2026-10-12：本次修改原因：API 商品新增副本以完整远端字段为基础，保留第三规格、图片组、多货源及多附件。
    if product.erp_imported:
        if product.erp_original_account != config.account_id or not product.erp_remote_snapshot:
            raise ValueError("API 导入商品只能通过导入时的账号创建副本，请切回原账号。")
        # result, _ = update_payload(product, product.erp_remote_snapshot, config)
        # 2026-10-12：本次修改原因：新增副本基于首次导入原文合并全部加工字段，不使用上次更新后的增量基线。
        copy_product = Product.from_dict(product.to_dict())
        copy_product.erp_update_baseline = deepcopy(product.erp_import_baseline or product.erp_update_baseline)
        result, _ = update_payload(copy_product, product.erp_remote_snapshot, config)
        if result.get("price") in (None, ""):
            result["price"] = _supply_price(product, config)
        validate_payload(result, require_price=True)
        return result
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
                # if color.get("imgUrl") and color["imgUrl"] != sku.image:
                #     raise ValueError("同一规格1的 SKU 图片不同，请先统一规格图片；妙手图片按规格1绑定。")
                # color.update(imgUrl=sku.image, imgUrls=[sku.image])
                # 2026-10-12：本次修改原因：不同尺码可以有不同图片，同规格1按 SKU 顺序去重合并，首张作为共享主图。
                images = color.setdefault("imgUrls", [])
                if sku.image not in images:
                    images.append(sku.image)
                color.setdefault("imgUrl", images[0])
        elif sku.image:
            raise ValueError("SKU 图片需要规格1才能映射到妙手颜色图；请补充规格1或将图片加入主图。")
        if sku.spec2:
            result["sizeMap"][sku.spec2.strip()] = {"name": sku.spec2.strip()}
    # if product.supply_price or len(product.skus) == 1:
    #     result["price"] = _supply_price(product, config)
    # 2026-10-12：本次修改原因：在任何图片上传前校验新增顶层货源价，防止多 SKU 有售价却漏传商品 price。
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
    # 2026-10-12：本次修改原因：校验前缩短可识别的 Temu 货源链接，原商品及数据库不变。
    _prepare_source_links(result)
    # validate_payload(result)
    # 2026-10-12：本次修改原因：新增请求必须有顶层 price，与更新保留远端原值的校验分开。
    validate_payload(result, require_price=True)
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
    # 2026-10-12：本次修改原因：同一规格1只合并一次图片，避免多个已编辑 SKU 相互覆盖图片组。
    color_image_changes: dict[str, list[SKU]] = {}
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
        # 2026-10-12：本次修改原因：三维规格完整保留但本版两列编辑器不能可靠修改该 SKU，商品文本/主图仍可独立更新。
        # if product.erp_imported and len(key[1:-1].split(";")) > 2:
        # 2026-10-12：本次修改原因：仅实际第三规格阻止 SKU 编辑，空槽位格式允许既有两维修改。
        if product.erp_imported and len(_remote_sku_parts(key)) > 2:
            raise ValueError("该商品包含第三规格；本版保留三维 SKU 原数据，请在妙手修改该 SKU，或仅编辑商品文本和主图。")
        # 2026-10-11：本次修改原因：远端规格在关联后发生更名时须重新核对，不能沿用被重新使用的键更新错 SKU。
        # parts = key[1:-1].split(";")
        # parts += [""] * (2 - len(parts))
        # 2026-10-12：本次修改原因：规格名核对共用空槽位处理，不改变用于提交的真实组合键。
        parts = _remote_sku_parts(key)
        if len(parts) != 2:
            raise ValueError("妙手原商品规格键无法可靠识别，请核对原商品后回传。")
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
            # peers = [other for other in product.skus if links.get(other.identity, "")[1:-1].split(";")[0] == color_key]
            # if any(other.image != sku.image for other in peers):
            #     raise ValueError("同一颜色规格的 SKU 图片不同，请统一后回传。")
            # colors[color_key].update(imgUrl=sku.image, imgUrls=[sku.image] if sku.image else [])
            # 2026-10-12：本次修改原因：先验证关联并收集明确编辑的图片，随后合并本地规格图及远端未编辑附图。
            color_image_changes.setdefault(color_key, []).append(sku)
    # 2026-10-12：本次修改原因：仅更新有图片改动的规格1，并对请求副本中的超长 Temu 链接应用同一规则。
    _update_color_images(product, result, links, color_image_changes)
    _prepare_source_links(result)
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


# def validate_payload(payload: dict) -> None:
# 2026-10-12：本次修改原因：新增必填价独立校验，更新不因远端历史数据缺项阻断无关字段修改。
def validate_payload(payload: dict, require_price: bool = False) -> None:
    if not isinstance(payload.get("title"), str) or not payload["title"].strip():
        raise ValueError("公共采集箱产品标题不能为空。")
    # limits = {"title": 255, "itemNum": 255, "notesText": 65536, "notes": 100000,
    #           "sizeChart": 255, "mainImgVideoUrl": 255, "colorPropName": 255, "sizePropName": 255}
    # 2026-10-12：本次修改原因：实际回传与保存共用字段长度上限。
    limits = TEXT_LIMITS
    for key, limit in limits.items():
        if len(str(payload.get(key, ""))) > limit:
            # raise ValueError(f"{key} 超过妙手允许的 {limit} 个字符。")
            # 2026-10-12：本次修改原因：超限提示包含字段及实际长度，方便用户针对性调整。
            raise ValueError(f"{key} 为 {len(str(payload[key]))} 个字符，超过妙手允许的 {limit} 个字符。")
    # if len(payload.get("imgUrls") or []) > 15:
    #     raise ValueError("公共采集箱最多支持 15 张主图，请调整顺序和数量。")
    # 2026-10-12：本次修改原因：回传提示实际张数，和编辑器的主图计数共用同一上限。
    if len(payload.get("imgUrls") or []) > MAX_MAIN_IMAGES:
        raise ValueError(f"公共采集箱最多支持 {MAX_MAIN_IMAGES} 张主图，当前 {len(payload['imgUrls'])} 张，请调整顺序和数量。")
    # if len(payload.get("sourceList") or []) > 10 or len(payload.get("productCertifications") or []) > 10:
    # 2026-10-12：本次修改原因：多货源/附件列表上限与保存校验一致。
    if len(payload.get("sourceList") or []) > MAX_SOURCE_ROWS or len(payload.get("productCertifications") or []) > MAX_CERTIFICATES:
        raise ValueError("货源/认证列表最多支持 10 条。")
    for row in payload.get("sourceAttrs") or []:
        if len(str(row.get("name", ""))) > 255 or len(str(row.get("value", ""))) > 255:
            raise ValueError("商品属性名和属性值最多 255 个字符。")
    for color in (payload.get("colorMap") or {}).values():
        # if len(color.get("imgUrls") or []) > 10 or len(str(color.get("name", ""))) > 255:
        #     raise ValueError("颜色规格名称最多 255 字，每组最多 10 张图片。")
        # 2026-10-12：本次修改原因：图片合并后仍遵守接口上限，明确提示哪一组超限，不静默丢弃图片。
        name = str(color.get("name", ""))
        if len(name) > 255:
            raise ValueError(f"规格1名称为 {len(name)} 个字符，妙手最多支持 255 个字符。")
        count = len(color.get("imgUrls") or [])
        # if count > 10:
        #     raise ValueError(f"规格1「{name[:40]}」有 {count} 张不同图片，妙手每组最多支持 10 张；请先整理该规格的图片组。")
        # 2026-10-12：本次修改原因：回传和保存共用规格图片上限。
        if count > MAX_SPEC_IMAGES:
            raise ValueError(f"规格1「{name[:40]}」有 {count} 张不同图片，妙手每组最多支持 {MAX_SPEC_IMAGES} 张；请先整理该规格的图片组。")
    # 2026-10-12：本次修改原因：第二/第三规格名称也按保存时的字段上限检查。
    for key in ("sizeMap", "saleProp3Map"):
        if any(len(str(option.get("name") or "")) > 255 for option in (payload.get(key) or {}).values()):
            raise ValueError("规格名称最多支持 255 个字符。")
    urls = picture_urls(payload)
    urls += [payload[key] for key in ("mainImgVideoUrl",) if payload.get(key)]
    urls += [row.get("fileUrl", "") for row in payload.get("productCertifications") or []]
    guide = payload.get("guideInfo") or {}
    # 2026-10-11：本次修改原因：校验来源和附件字符串长度，在发送前给出可理解的原因。
    # if any(len(str(value)) > 255 for row in payload.get("sourceList") or [] for value in row.values()):
    #     raise ValueError("货源 ID、平台、站点、链接、备注最多 255 个字符。")
    # 2026-10-12：本次修改原因：未识别的平台或超长备注不能靠截断处理，提示具体货源条目、字段及长度。
    source_labels = {"sourceItemId": "货源 ID", "source": "货源平台", "sourceSite": "货源站点",
                     "sourceItemUrl": "货源链接", "remark": "货源备注"}
    for index, row in enumerate(payload.get("sourceList") or [], 1):
        for key, value in row.items():
            count = len(str(value))
            if count > 255:
                action = "请填写可访问的商品短链接。" if key == "sourceItemUrl" else "请缩短该字段内容。"
                raise ValueError(f"第 {index} 条货源的{source_labels.get(key, key)}（{key}）为 {count} 个字符，妙手最多支持 255 个字符；{action}")
    if any(len(str(value)) > 255 for value in guide.values()):
        raise ValueError("说明书名称和链接最多 255 个字符。")
    if any(len(str(row.get("fileName", ""))) > 255 for row in payload.get("productCertifications") or []):
        raise ValueError("认证附件名称最多 255 个字符。")
    if guide.get("productGuideFileUrl"):
        urls.append(guide["productGuideFileUrl"])
    if any(not valid_url(url) for url in urls if url):
        raise ValueError("图片/附件必须是妙手可访问的 HTTP/HTTPS 链接；本机白底图和 AI 生成图请先托管并替换链接。")
    # 单规格货源价在文字说明中为必填，不能因为 JSON required 仅写 title 就遗漏。
    # if len(payload.get("skuMap") or {}) == 1 and "price" not in payload:
    #     raise ValueError("单规格商品缺少货源价，请在货源链接栏目填写后回传。")
    # 2026-10-12：本次修改原因：新增多规格同样需要商品级价格；空串、None、非法数值不能绕过检查。
    if require_price:
        if payload.get("price") in (None, ""):
            raise ValueError("新增商品缺少独立货源价，请在货源链接栏目填写后回传。")
        number(payload["price"], "货源价（CNY）", "0.01")
