# 2026-10-10：本次修改原因：定义来源数据、商品和 SKU 的统一结构，保留采集价与待确认售价的区别。
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import re
from typing import Any
from urllib.parse import urlsplit


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def valid_url(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        return parsed.scheme in {"http", "https"} and bool(parsed.hostname)
    except ValueError:
        return False


def positive_decimal(value: str) -> bool:
    try:
        number = Decimal(str(value))
        return number.is_finite() and number > 0
    except (InvalidOperation, ValueError):
        return False


@dataclass
class SKU:
    platform_sku: str = ""
    # 2026-10-11：本次修改原因：区分来源平台的规格 ID 与妙手编辑页的商家平台 SKU。
    source_sku_id: str = ""
    spec1: str = ""
    spec2: str = ""
    source_price: str = ""
    price: str = ""
    currency: str = ""
    # 2026-10-11：本次修改原因：来源币种单独留存，人工选择导出售价币种时不改写来源信息。
    source_currency: str = ""
    image: str = ""
    stock: str = ""
    # 2026-10-11：本次修改原因：保留来源平台的库存与限购信息，避免误填为店铺自有库存。
    source_stock: str = ""
    purchase_limit: str = ""
    availability: str = ""
    weight: str = ""
    dimensions: str = ""
    specs: dict[str, str] = field(default_factory=dict)
    # 2026-10-11：本次修改原因：SKU 编辑痕迹集中记录在 Product.manual_fields 中。
    # manual_fields: list[str] = field(default_factory=list)

    # 2026-10-11：本次修改原因：回填使用稳定的来源 ID，兼容旧版把来源 ID 放在平台 SKU 的记录。
    @property
    def identity(self) -> str:
        return self.source_sku_id or self.platform_sku


@dataclass
class Product:
    id: str = ""
    source: str = "temu"
    source_id: str = ""
    site: str = ""
    source_url: str = ""
    main_code: str = ""
    title: str = ""
    currency: str = ""
    description: str = ""
    # 2026-10-11：本次修改原因：按妙手区分属性简述、图文详细描述，原 description 保留兼容旧文案。
    simple_description: str = ""
    description_html: str = ""
    category: str = ""
    attributes: dict[str, str] = field(default_factory=dict)
    images: list[str] = field(default_factory=list)
    detail_images: list[str] = field(default_factory=list)
    video: str = ""
    certificate: str = ""
    size_chart: str = ""
    # 2026-10-11：本次修改原因：补齐妙手的身体尺码表、说明书、产品级物流和货源备注字段。
    body_size_chart: str = ""
    instruction_manual: str = ""
    package_weight: str = ""
    package_dimensions: str = ""
    source_remark: str = ""
    image_sizes: dict[str, str] = field(default_factory=dict)
    spec1_name: str = "规格1"
    spec2_name: str = "规格2"
    skus: list[SKU] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    approved: bool = False
    revision: int = 1
    created_at: str = ""
    updated_at: str = ""
    capture_id: str = ""
    # 2026-10-11：本次修改原因：记录人工编辑字段，并兼容旧版本历史以保护主动删除的数据。
    manual_fields: list[str] = field(default_factory=list)
    edit_tracking: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Product:
        values = {key: value for key, value in data.items() if key in cls.__dataclass_fields__}
        values["skus"] = [SKU(**{k: v for k, v in sku.items() if k in SKU.__dataclass_fields__})
                          for sku in data.get("skus", [])]
        return cls(**values)

    def issues(self) -> list[str]:
        result = []
        if not self.main_code.strip():
            result.append("缺少产品主编号")
        if not self.title.strip():
            result.append("缺少产品名称")
        if len(self.currency.strip()) != 3 or not self.currency.isascii() or not self.currency.isalpha():
            result.append("请确认三位货币代码，例如 USD、CNY")
        if not self.images:
            result.append("缺少产品主图")
        if any(not valid_url(url) for url in self.images + self.detail_images):
            result.append("产品图片必须是有效的 HTTP/HTTPS 链接")
        if not self.skus:
            result.append("尚未取得实际 SKU，请补充规格")
        # 2026-10-11：本次修改原因：物流栏目按包装单位校验，尺码规格和页面默认提示不填入物流字段。
        if self.package_weight and not positive_decimal(self.package_weight):
            result.append("包裹重量应为大于 0 的 KG 数值或留空")
        if self.package_dimensions:
            sizes = re.split(r"\s*[xX×*]\s*", self.package_dimensions.strip())
            if len(sizes) != 3 or not all(positive_decimal(size) for size in sizes):
                result.append("包裹尺寸应为长*宽*高，三个数值均大于 0，单位 CM")
        # 2026-10-10：本次修改原因：导出前校验来源链接、规格名称和尺寸，避免模板字段歧义。
        if self.source_url and not valid_url(self.source_url):
            result.append("货源链接须为有效的 HTTP/HTTPS 链接或留空")
        if any(sku.spec1 for sku in self.skus) and not self.spec1_name.strip():
            result.append("请填写规格 1 的维度名称")
        if any(sku.spec2 for sku in self.skus) and not self.spec2_name.strip():
            result.append("请填写规格 2 的维度名称")
        if self.spec1_name == self.spec2_name and any(sku.spec2 for sku in self.skus):
            result.append("两个规格维度不能使用相同名称")
        seen = set()
        for index, sku in enumerate(self.skus, 1):
            prefix = f"SKU {index}："
            if not positive_decimal(sku.price):
                result.append(prefix + "请填写大于 0 的售价")
            if sku.currency and sku.currency.upper() != self.currency.upper():
                result.append(prefix + "币种与商品币种不一致")
            if sku.image and not valid_url(sku.image):
                result.append(prefix + "规格图片链接无效")
            if len(sku.specs) > 2:
                result.append(prefix + "来源超过两个规格维度，需要先调整规格映射")
            if len(self.skus) > 1 and not (sku.spec1.strip() or sku.spec2.strip()):
                result.append(prefix + "多规格商品需要规格值")
            key = (sku.spec1.strip(), sku.spec2.strip())
            if key in seen:
                result.append(prefix + "规格组合重复")
            seen.add(key)
            if sku.stock and (not sku.stock.isdecimal() or int(sku.stock) < 0):
                result.append(prefix + "库存须为非负整数或留空")
            if sku.weight and not positive_decimal(sku.weight):
                result.append(prefix + "重量须为大于 0 的 KG 数值或留空")
            if sku.dimensions:
                sizes = re.split(r"\s*[xX×*]\s*", sku.dimensions.strip())
                if len(sizes) != 3 or not all(positive_decimal(size) for size in sizes):
                    result.append(prefix + "尺寸须为长*宽*高，三个数值均大于 0，单位 CM")
        return result

    @property
    def status(self) -> str:
        if self.issues():
            return "待完善"
        return "已审核" if self.approved else "待审核"

