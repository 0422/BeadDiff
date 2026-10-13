# 2026-10-11：本次修改原因：覆盖妙手字段语义、旧版本迁移与重新解析保护；测试由用户自行运行。
import json
from pathlib import Path

from beaddiff.content import clean_description, sku_image_groups
from beaddiff.models import Product
from beaddiff.parsing import parse_capture
from beaddiff.service import CaptureService
from beaddiff.storage import Repository


def material():
    return {"source": "temu", "itemId": "ALIGN-1", "site": "US",
            "pageContent": '<meta property="og:description" content="用于搜索引擎的摘要">',
            "rawData": {"store": {
                "goods": {"goodsId": "ALIGN-1", "goodsName": "字段对照样本",
                          "gallery": [{"url": "https://example.com/main.jpg", "width": 800, "height": 800}]},
                "localInfo": {"currency": "USD"},
                "goodsProperty": [{"key": "材料", "values": ["硅藻泥"]}, {"key": "形状", "values": ["矩形"]}],
                "productDetailFlatList": [{"url": "https://example.com/detail.jpg", "width": 900, "height": 1200}],
                "sku": [{"skuId": "SOURCE-1", "salePriceStr": "$9.79", "stockQuantity": 1000, "limitQuantity": 99,
                         "thumbUrl": "https://example.com/black-small.jpg", "specs": {"颜色": "黑", "尺码": "小"}},
                        {"skuId": "SOURCE-2", "thumbUrl": "https://example.com/black-large.jpg",
                         "specs": {"颜色": "黑", "尺码": "大"}}]}}}


def test_simple_description_and_rich_detail_have_miaoshou_semantics():
    product = parse_capture(material())
    assert product.simple_description == "材料:硅藻泥\n形状:矩形"
    assert '<img src="https://example.com/detail.jpg"' in product.description_html
    assert product.description == "用于搜索引擎的摘要"
    assert "搜索引擎" not in product.description_html
    assert product.image_sizes["https://example.com/detail.jpg"] == "900 × 1200"
    assert product.skus[0].source_sku_id == "SOURCE-1"
    assert not product.skus[0].platform_sku
    assert sku_image_groups(product.skus, "颜色", "spec1") == {
        "黑": ["https://example.com/black-small.jpg", "https://example.com/black-large.jpg"]}
    assert not product.package_weight and not product.package_dimensions
    assert not product.certificate and not product.instruction_manual and not product.size_chart


def test_rich_detail_removes_executable_and_local_resources():
    html = ('<p onclick="run()">正常 <b>文字</b></p><script>hidden()</script>'
            '<img src="file:///C:/secret.jpg"><img src="https://example.com/detail.jpg" onerror="run()">'
            '<a href="javascript:run()">链接</a>')
    cleaned = clean_description(html)
    assert "<b>文字</b>" in cleaned and "正常" in cleaned
    assert 'src="https://example.com/detail.jpg"' in cleaned
    assert all(value not in cleaned for value in ("script", "hidden", "onclick", "onerror", "file:", "javascript:"))


def test_added_fields_roundtrip():
    product = parse_capture(material())
    product.instruction_manual = "https://example.com/manual.pdf"
    product.body_size_chart = "https://example.com/body.jpg"
    product.package_weight, product.package_dimensions, product.source_remark = "0.35", "30*20*3", "采购备注"
    product.skus[0].platform_sku = "SHOP-001"
    copy = Product.from_dict(product.to_dict())
    assert copy == product


def test_old_source_id_migrates_without_overwriting_merchant_code(tmp_path: Path):
    repository = Repository(tmp_path)
    old = parse_capture(material())
    old.simple_description, old.description_html = "", ""
    for sku in old.skus:
        sku.platform_sku, sku.source_sku_id = sku.source_sku_id, ""
    stored, _ = repository.store_parsed(old)
    stored.skus[0].platform_sku = "MY-SHOP-CODE"
    repository.save_product(stored)
    migrated, updated, _ = repository.backfill_parsed("CAPTURE", parse_capture(material()))
    assert updated and len(migrated.skus) == 2
    assert migrated.skus[0].source_sku_id == "SOURCE-1"
    assert migrated.skus[0].platform_sku == "MY-SHOP-CODE"
    assert migrated.simple_description and migrated.description_html
    assert not repository.backfill_parsed("CAPTURE", parse_capture(material()))[1]


def test_reparse_respects_removed_attribute_and_detail_image(tmp_path: Path):
    repository = Repository(tmp_path)
    service = CaptureService(repository)
    result = service.ingest({"payload": material()})
    product = repository.product(result["productId"])
    product.attributes.pop("材料")
    product.detail_images = []
    product.instruction_manual = "https://example.com/own-manual.pdf"
    repository.save_product(product)
    service.reparse(result["captureId"])
    saved = repository.product(product.id)
    assert saved.simple_description == "形状:矩形"
    assert "<img " not in saved.description_html
    assert saved.instruction_manual == "https://example.com/own-manual.pdf"
    assert not service.reparse(result["captureId"])["updated"]


def test_reparse_keeps_manual_rich_description_and_deliberate_clear(tmp_path: Path):
    repository = Repository(tmp_path)
    service = CaptureService(repository)
    result = service.ingest({"payload": material()})
    product = repository.product(result["productId"])
    product.description_html = "<p><b>手工图文</b></p>"
    product.simple_description = ""
    product.skus[0].platform_sku = "SHOP-01"
    repository.save_product(product)
    service.reparse(result["captureId"])
    saved = repository.product(product.id)
    assert saved.description_html == "<p><b>手工图文</b></p>"
    assert saved.simple_description == ""
    assert saved.skus[0].platform_sku == "SHOP-01"
    saved.description_html = ""
    repository.save_product(saved)
    service.reparse(result["captureId"])
    saved = repository.product(product.id)
    # 2026-10-12：本次修改原因：撤下表格导出后保留主动清空详情的存储回归覆盖。
    assert saved.description_html == ""


def test_old_manual_text_migrates_to_rich_detail_once(tmp_path: Path):
    repository = Repository(tmp_path)
    old = parse_capture(material())
    old.simple_description, old.description_html = "", ""
    product, _ = repository.store_parsed(old)
    product.description = "旧版手工文字 <需要保留>"
    repository.save_product(product)
    saved, updated, _ = repository.backfill_parsed("CAPTURE", parse_capture(material()))
    assert updated and "旧版手工文字" in saved.description_html
    assert "&lt;需要保留&gt;" in saved.description_html
    assert "description_html" in saved.manual_fields
    assert not repository.backfill_parsed("CAPTURE", parse_capture(material()))[1]


def test_shipping_validation_does_not_use_spec_dimensions():
    product = parse_capture(material())
    assert product.skus[0].spec2 == "小"
    product.package_weight = "-1"
    product.package_dimensions = "15.75*23.62英寸"
    issues = product.issues()
    assert any("包裹重量" in issue for issue in issues)
    assert any("包裹尺寸" in issue for issue in issues)
    product.package_weight, product.package_dimensions = "0.35", "30*20*3"
    assert not any("包裹" in issue for issue in product.issues())


def test_legacy_body_without_new_fields_still_loads():
    body = {"source_id": "OLD", "description": "旧文案", "skus": [{"platform_sku": "001"}]}
    product = Product.from_dict(json.loads(json.dumps(body)))
    assert product.description == "旧文案" and not product.description_html
    assert product.skus[0].identity == "001"
