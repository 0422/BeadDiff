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
    spec1: str = ""
    spec2: str = ""
    source_price: str = ""
    price: str = ""
    currency: str = ""
    image: str = ""
    stock: str = ""
    weight: str = ""
    dimensions: str = ""
    specs: dict[str, str] = field(default_factory=dict)


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
    category: str = ""
    attributes: dict[str, str] = field(default_factory=dict)
    images: list[str] = field(default_factory=list)
    detail_images: list[str] = field(default_factory=list)
    video: str = ""
    certificate: str = ""
    size_chart: str = ""
    spec1_name: str = "规格1"
    spec2_name: str = "规格2"
    skus: list[SKU] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    approved: bool = False
    revision: int = 1
    created_at: str = ""
    updated_at: str = ""
    capture_id: str = ""

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

