# 2026-10-14：本次修改原因：独立保存白底图类目、整套生成配置与可核对的建档预设，避免缺编号、SKU 和货源价。
from __future__ import annotations
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import re
from uuid import uuid4
from .models import Product, SKU

@dataclass
class ListingDefaults:
    category: str = ''
    language: str = 'English'
    main_count: int = 5
    detail_count: int = 4
    instruction: str = '基于实物图生成完整商品 Listing，保持真实结构、颜色和款式；统一视觉风格，主图背景简洁。'
    currency: str = 'CNY'
    price: str = '1.00'
    supply_price: str = '1.00'
    stock: str = '0'
    weight: str = '0.10'
    dimensions: str = '10*10*2'
    spec1: str = '默认款'
    code_prefix: str = 'BD-LOCAL'

    def problems(self, *, require_category=False):
        errors = []
        if require_category and not self.category.strip():
            errors.append('设置 → 白底图 Listing → 生成方案：填写并保存产品类目；也可在上传窗口填写本次类目。')
        if not self.language.strip():
            errors.append('目标语言不能为空。')
        for key, caption, maximum in (('main_count', '主图数量', 15), ('detail_count', '详情图数量', 12)):
            value = getattr(self, key)
            if type(value) is not int or not 1 <= value <= maximum:
                errors.append(f'{caption}须为 1～{maximum}。')
        if not re.fullmatch(r'[A-Z]{3}', self.currency):
            errors.append('币种须为三位大写代码，例如 CNY。')
        for key, caption in (('price', 'SKU 售价'), ('supply_price', '独立货源价'), ('weight', '包裹重量 KG')):
            try:
                number = Decimal(getattr(self, key))
                if not number.is_finite() or not Decimal('0.01') <= number <= Decimal('99999.99'):
                    raise ValueError
            except (InvalidOperation, ValueError):
                errors.append(f'{caption}须为 0.01～99999.99 的数值。')
        if not self.stock.isdecimal() or not 0 <= int(self.stock) <= 99999:
            errors.append('库存须为 0～99999 的整数。')
        values = re.split(r'\s*[xX×*]\s*', self.dimensions.strip())
        try:
            if len(values) != 3 or any(not Decimal(value).is_finite() or not 0 < Decimal(value) <= 99999 for value in values):
                raise ValueError
        except (InvalidOperation, ValueError):
            errors.append('包装尺寸须为长*宽*高，三个数值均大于零，单位 CM。')
        if not self.spec1.strip() or len(self.spec1) > 40 or any(char in self.spec1 for char in ';\r\n'):
            errors.append('默认规格1须为 1～40 字符，不含分号或换行。')
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,24}', self.code_prefix):
            errors.append('主编号前缀须为 1～24 位字母、数字、下划线或短横线。')
        return errors

class ListingDefaultsStore:
    def __init__(self, data_dir: Path):
        self.path = Path(data_dir) / 'listing_defaults.local.json'

    def get(self):
        if not self.path.exists():
            return ListingDefaults()
        try:
            data = json.loads(self.path.read_text(encoding='utf-8-sig'))
            if not isinstance(data, dict) or data.get('version') != 1 or not isinstance(data.get('defaults'), dict):
                raise ValueError
            values = data['defaults']
            keys = asdict(ListingDefaults())
            if any(key not in keys for key in values) or any(type(value) is not type(keys[key]) for key, value in values.items()):
                raise ValueError
            defaults = ListingDefaults(**values)
            if defaults.problems():
                raise ValueError
            return defaults
        except (ValueError, TypeError) as error:
            raise ValueError('白底图配置格式损坏。请在设置 → 白底图 Listing 检查并重新保存配置；原文件保留。') from error

    def save(self, defaults):
        issues = defaults.problems(require_category=True)
        if issues:
            raise ValueError('\n'.join(issues))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps({'version': 1, 'defaults': asdict(defaults)}, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        temporary.replace(self.path)

def uploaded_product(images, facts, defaults):
    issues = defaults.problems(require_category=True)
    if issues:
        raise ValueError('\n'.join(issues))
    if not images:
        raise ValueError('上传白底图窗口 → 选择白底图 / 实物图：至少添加一张当前商品的图片。')
    if len(images) > 15:
        raise ValueError('上传白底图窗口 → 图片列表：最多保留 15 张主体图片，其余可在编辑 → 图片中添加为详情素材。')
    code = defaults.code_prefix + '-' + uuid4().hex[:12].upper()
    attributes = {caption: facts[key].strip() for key, caption in
                  (('material', '材质'), ('color', '颜色'), ('length', '尺寸 / 长度'), ('quantity', '数量'), ('package', '包装'))
                  if facts.get(key, '').strip()}
    return Product(source='upload', main_code=code, title=facts.get('title', '').strip() or defaults.category + ' ' + code,
        category=defaults.category, attributes=attributes, currency=defaults.currency,
        supply_price=defaults.supply_price, package_weight=defaults.weight, package_dimensions=defaults.dimensions,
        images=[image.uri for image in images], image_sizes={image.uri: f'{image.width} × {image.height}' for image in images},
        skus=[SKU(platform_sku=code + '-01', spec1=defaults.spec1, price=defaults.price, currency=defaults.currency,
                  stock=defaults.stock, image=images[0].uri, weight=defaults.weight, dimensions=defaults.dimensions)],
        warnings=['白底图建档预设：售价、货源价、库存、重量、包装尺寸及默认款来自设置；保存并审核前请核对。'])
