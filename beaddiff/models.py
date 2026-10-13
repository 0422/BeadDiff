# 2026-10-10：本次修改原因：定义来源数据、商品和 SKU 的统一结构，保留采集价与待确认售价的区别。
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
# 2026-10-11：本次修改原因：按商品业务内容计算回传指纹，审核和图片尺寸缓存不影响已传状态。
import hashlib
import json
import re
from typing import Any
from urllib.parse import urlsplit

# 2026-10-11：本次修改原因：商品工作区允许受管理的本地白底图和生成图；发布链接另在导出时校验。
from .assets import valid_media_url


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
    # 2026-10-11：本次修改原因：明确记录保存的内容修改及 ERP 成功回执，不用版本号或导出记录猜测状态。
    content_modified: bool = False
    modified_at: str = ""
    erp_content_hash: str = ""
    erp_transferred_at: str = ""
    erp_transfer_mode: str = ""
    erp_target_id: str = ""
    erp_transfer_id: str = ""
    erp_original_id: str = ""
    # 2026-10-11：本次修改原因：原商品绑定开放平台账号，保存已验证 SKU 映射和上次成功更新快照。
    erp_original_account: str = ""
    erp_sku_links: dict[str, str] = field(default_factory=dict)
    erp_update_baseline: dict[str, Any] = field(default_factory=dict)
    erp_account_id: str = ""
    # 2026-10-11：本次修改原因：单规格新增需要独立货源价，不能拿销售金额冒充货源价。
    supply_price: str = ""

    # 2026-10-12：本次修改原因：API 导入保留完整详情及来源标记，界面未覆盖的字段不从原始网页重新推断。
    erp_imported: bool = False
    erp_remote_snapshot: dict[str, Any] = field(default_factory=dict)
    erp_imported_at: str = ""
    # 2026-10-12：本次修改原因：新增副本始终比较首次导入基线，不能被成功更新后的增量基线抹掉已加工字段。
    erp_import_baseline: dict[str, Any] = field(default_factory=dict)

    # 2026-10-12：本次修改原因：获取方式与货源平台分开展示，兼容现有商品而不改写原数据。
    @property
    def acquisition_route(self) -> str:
        if self.erp_imported:
            return "miaoshou"
        return "upload" if self.source == "upload" else "plugin"

    @property
    def acquisition_label(self) -> str:
        return {"miaoshou": "妙手接口", "plugin": "插件同步", "upload": "自上传"}[self.acquisition_route]

    # 2026-10-11：本次修改原因：文本、图片顺序、属性和可编辑 SKU 共用实际内容比较；排除预览缓存和来源只读价格。
    def business_content(self) -> dict[str, Any]:
        names = (
            "main_code", "title", "currency", "description", "simple_description", "description_html",
            "category", "attributes", "images", "detail_images", "video", "certificate", "size_chart",
            "body_size_chart", "instruction_manual", "package_weight", "package_dimensions", "source_remark",
            "source_url", "spec1_name", "spec2_name",
            # 2026-10-11：本次修改原因：人工补充的货源价纳入修改及回传指纹，币种沿用当前商品币种。
            "supply_price",
        )
        sku_names = ("platform_sku", "spec1", "spec2", "price", "currency", "image", "stock", "weight", "dimensions", "specs")
        result = {name: getattr(self, name) for name in names}
        result["skus"] = [{name: getattr(sku, name) for name in sku_names} for sku in self.skus]
        return result

    @property
    def content_hash(self) -> str:
        serialized = json.dumps(self.business_content(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    @property
    def modification_status(self) -> str:
        return "已修改" if self.content_modified else "未修改"

    @property
    def erp_status(self) -> str:
        return "已传" if self.erp_content_hash and self.erp_content_hash == self.content_hash else "未传"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Product:
        values = {key: value for key, value in data.items() if key in cls.__dataclass_fields__}
        values["skus"] = [SKU(**{k: v for k, v in sku.items() if k in SKU.__dataclass_fields__})
                          for sku in data.get("skus", [])]
        # 2026-10-11：本次修改原因：旧记录仅依据已留存的编辑痕迹恢复修改状态，不把重新解析增加的版本算成人工修改。
        if "content_modified" not in data:
            names = set(cls().business_content())
            sku_names = {"platform_sku", "spec1", "spec2", "price", "currency", "image", "stock", "weight", "dimensions", "specs"}
            tracked = data.get("manual_fields", [])
            values["content_modified"] = any(
                name in names or name.startswith("attribute:")
                or (name.startswith("sku:") and name.rsplit(":", 1)[-1] in sku_names)
                for name in tracked
            )
        return cls(**values)

    # def issues(self) -> list[str]:
    # 2026-10-12：本次修改原因：API 增量审核可传入导入基线，只校验改动字段；表格导出仍使用完整检查。
    def issues(self, original: Product | None = None) -> list[str]:
        result = []
        def changed(name: str) -> bool:
            return original is None or getattr(self, name) != getattr(original, name)
        original_skus = {sku.identity: sku for sku in original.skus} if original else {}
        structure_changed = original is None or (
            [(sku.identity, sku.spec1, sku.spec2, sku.specs) for sku in self.skus]
            != [(sku.identity, sku.spec1, sku.spec2, sku.specs) for sku in original.skus]
        )
        # if not self.main_code.strip():
        # 2026-10-12：本次修改原因：保留原商品未填字段，不能因只修改标题而要求补齐无关数据。
        if changed("main_code") and not self.main_code.strip():
            result.append("缺少产品主编号")
        if not self.title.strip():
            result.append("缺少产品名称")
        # if len(self.currency.strip()) != 3 or not self.currency.isascii() or not self.currency.isalpha():
        # 2026-10-12：本次修改原因：人民币导入数据保留原币种，仅在改动币种时校验。
        if changed("currency") and (len(self.currency.strip()) != 3 or not self.currency.isascii() or not self.currency.isalpha()):
            result.append("请确认三位货币代码，例如 USD、CNY")
        # if not self.images:
        # 2026-10-12：本次修改原因：原主图不因文本编辑被连带要求补齐，主动清空仍检查。
        if changed("images") and not self.images:
            result.append("缺少产品主图")
        # if any(not valid_url(url) for url in self.images + self.detail_images):
        #     result.append("产品图片必须是有效的 HTTP/HTTPS 链接")
        # 2026-10-11：本次修改原因：本地素材可编辑审核，丢失素材仍提示修复。
        # if any(not valid_media_url(url) for url in self.images + self.detail_images):
        # 2026-10-12：本次修改原因：只检查改动的图片列表，不把原详情图片问题归到标题修改。
        if any(not valid_media_url(url) for name in ("images", "detail_images") if changed(name) for url in getattr(self, name)):
            result.append("产品图片链接无效或本地素材已被移动")
        # if not self.skus:
        # 2026-10-12：本次修改原因：增量审核不强制补齐原商品空 SKU；新增及导出仍完整检查。
        if structure_changed and not self.skus:
            result.append("尚未取得实际 SKU，请补充规格")
        # 2026-10-11：本次修改原因：物流栏目按包装单位校验，尺码规格和页面默认提示不填入物流字段。
        # if self.package_weight and not positive_decimal(self.package_weight):
        # 2026-10-12：本次修改原因：妙手未填物流的 0 占位保留，改动后的物流仍检查。
        if changed("package_weight") and self.package_weight and not positive_decimal(self.package_weight):
            result.append("包裹重量应为大于 0 的 KG 数值或留空")
        # if self.package_dimensions:
        # 2026-10-12：本次修改原因：只有编辑包裹尺寸时才要求有效长宽高。
        if changed("package_dimensions") and self.package_dimensions:
            sizes = re.split(r"\s*[xX×*]\s*", self.package_dimensions.strip())
            if len(sizes) != 3 or not all(positive_decimal(size) for size in sizes):
                result.append("包裹尺寸应为长*宽*高，三个数值均大于 0，单位 CM")
        # 2026-10-10：本次修改原因：导出前校验来源链接、规格名称和尺寸，避免模板字段歧义。
        # if self.source_url and not valid_url(self.source_url):
        # 2026-10-12：本次修改原因：原货源字段保留，改动链接仍检查格式。
        if changed("source_url") and self.source_url and not valid_url(self.source_url):
            result.append("货源链接须为有效的 HTTP/HTTPS 链接或留空")
        # if any(sku.spec1 for sku in self.skus) and not self.spec1_name.strip():
        # 2026-10-12：本次修改原因：原规格名称缺失不阻碍文本修改，结构改动仍检查。
        if (structure_changed or changed("spec1_name")) and any(sku.spec1 for sku in self.skus) and not self.spec1_name.strip():
            result.append("请填写规格 1 的维度名称")
        # if any(sku.spec2 for sku in self.skus) and not self.spec2_name.strip():
        # 2026-10-12：本次修改原因：第二规格名称同样按实际结构改动校验。
        if (structure_changed or changed("spec2_name")) and any(sku.spec2 for sku in self.skus) and not self.spec2_name.strip():
            result.append("请填写规格 2 的维度名称")
        # if self.spec1_name == self.spec2_name and any(sku.spec2 for sku in self.skus):
        # 2026-10-12：本次修改原因：已有同名规格保留，编辑规格时禁止歧义。
        if (structure_changed or changed("spec1_name") or changed("spec2_name")) and self.spec1_name == self.spec2_name and any(sku.spec2 for sku in self.skus):
            result.append("两个规格维度不能使用相同名称")
        seen = set()
        for index, sku in enumerate(self.skus, 1):
            prefix = f"SKU {index}："
            # 2026-10-12：本次修改原因：以稳定远端身份逐字段比较，修改 SKU 的价格不能借原占位值绕过审核。
            previous = original_skus.get(sku.identity)
            def sku_changed(name: str) -> bool:
                return previous is None or getattr(sku, name) != getattr(previous, name)
            # if not positive_decimal(sku.price):
            # 2026-10-12：本次修改原因：只改商品文本时允许保留原 SKU 空售价，改售价仍须大于零。
            if (changed("currency") or sku_changed("price") or sku_changed("currency")) and not positive_decimal(sku.price):
                result.append(prefix + "请填写大于 0 的售价")
            # if sku.currency and sku.currency.upper() != self.currency.upper():
            # 2026-10-12：本次修改原因：只检查改动的商品/SKU 币种一致性。
            if (changed("currency") or sku_changed("currency")) and sku.currency and sku.currency.upper() != self.currency.upper():
                result.append(prefix + "币种与商品币种不一致")
            # if sku.image and not valid_url(sku.image):
            # 2026-10-11：本次修改原因：SKU 同样支持本地生成图。
            # if sku.image and not valid_media_url(sku.image):
            # 2026-10-12：本次修改原因：既有规格图片不因文本编辑重新要求修复。
            if sku_changed("image") and sku.image and not valid_media_url(sku.image):
                result.append(prefix + "规格图片链接无效")
            # if len(sku.specs) > 2:
            # 2026-10-12：本次修改原因：API 原商品的第三维度保存在远端快照，允许编辑文本；规格重构仍由回传层阻止。
            if len(sku.specs) > 2 and not self.erp_imported:
                result.append(prefix + "来源超过两个规格维度，需要先调整规格映射")
            # if len(self.skus) > 1 and not (sku.spec1.strip() or sku.spec2.strip()):
            # 2026-10-12：本次修改原因：只在结构变动时检查前两维，保留只用第三维的远端 SKU。
            if structure_changed and len(self.skus) > 1 and not (sku.spec1.strip() or sku.spec2.strip()):
                result.append(prefix + "多规格商品需要规格值")
            # key = (sku.spec1.strip(), sku.spec2.strip())
            # 2026-10-12：本次修改原因：API 三维规格不能因前两维相同被误判为重复；使用导入时验证的完整远端键。
            key = self.erp_sku_links.get(sku.identity, "") if self.erp_imported else (sku.spec1.strip(), sku.spec2.strip())
            if key in seen:
                result.append(prefix + "规格组合重复")
            seen.add(key)
            # if sku.stock and (not sku.stock.isdecimal() or int(sku.stock) < 0):
            # 2026-10-12：本次修改原因：原库存保持原值，改动库存仍要求非负整数。
            if sku_changed("stock") and sku.stock and (not sku.stock.isdecimal() or int(sku.stock) < 0):
                result.append(prefix + "库存须为非负整数或留空")
            # if sku.weight and not positive_decimal(sku.weight):
            # 2026-10-12：本次修改原因：原 SKU 的 0 重量占位保留，改动重量仍检查。
            if sku_changed("weight") and sku.weight and not positive_decimal(sku.weight):
                result.append(prefix + "重量须为大于 0 的 KG 数值或留空")
            # if sku.dimensions:
            # 2026-10-12：本次修改原因：未编辑的 SKU 尺寸占位保留，改动尺寸仍检查。
            if sku_changed("dimensions") and sku.dimensions:
                sizes = re.split(r"\s*[xX×*]\s*", sku.dimensions.strip())
                if len(sizes) != 3 or not all(positive_decimal(size) for size in sizes):
                    result.append(prefix + "尺寸须为长*宽*高，三个数值均大于 0，单位 CM")
        return result

    # 2026-10-12：本次修改原因：API 原商品审核以固定导入基线检查全部本机编辑，不要求补齐未改动的远端默认字段。
    # def review_issues(self) -> list[str]:
    # 2026-10-12：本次修改原因：未保存的编辑可提供原表单值，正确检查主动改动后的图文输出。
    def review_issues(self, form_original: Product | None = None) -> list[str]:
        baseline = self.erp_import_baseline if self.erp_imported else {}
        # return self.issues(Product.from_dict(baseline) if baseline else None)
        # 2026-10-12：本次修改原因：审核、速览与旧商品状态纳入全部长度/数量/格式限制，16 张主图即使未编辑也显示待完善。
        from .miaoshou_mapping import draft_limit_issues
        original = Product.from_dict(baseline) if baseline else None
        # return list(dict.fromkeys(self.issues(original) + draft_limit_issues(self, original)))
        # 2026-10-12：本次修改原因：完整性基于固定导入基线，图文限额基于当前编辑前的数据；两者不混用。
        return list(dict.fromkeys(self.issues(original) + draft_limit_issues(self, form_original or original)))

    @property
    def status(self) -> str:
        # if self.issues():
        # 2026-10-12：本次修改原因：商品库审核状态与增量审核规则一致，完整表格导出仍另做检查。
        if self.review_issues():
            return "待完善"
        return "已审核" if self.approved else "待审核"

