# 2026-10-11：本次修改原因：覆盖真实 Temu 同级字段结构与安全回填，样本只保留脱敏的代表性字段。
import json
from pathlib import Path

import pytest

from beaddiff.models import Product
from beaddiff.parsing import parse_capture
from beaddiff.service import CaptureService
from beaddiff.storage import Repository


def material():
    store = {
        "goods": {
            "goodsId": "SAMPLE-1", "goodsName": "浴室垫结构样本",
            "gallery": [
                {"url": "https://example.com/main.jpg", "video": {"videoUrl": "https://example.com/video.mp4"}},
                {"url": "https://example.com/main.jpg"},
                {"url": "https://example.com/other.jpg"},
            ],
        },
        "localInfo": {"currency": "USD"},
        "goodsProperty": [{"key": "材料", "values": ["硅藻泥（软）"]}, {"key": "形状", "values": ["矩形"]}],
        "crumbOptList": [{"optType": 0, "optName": "首页"}, {"optType": 1, "optName": "家居用品"},
                         {"optType": 2, "optName": "浴室用品"}],
        "productDetailFlatList": [{"url": "https://example.com/detail.jpg"}],
        "productDetail": {"floorList": [{"items": [{"url": "https://example.com/detail.jpg"}]}]},
        "sku": [
            {"skuId": "BLACK", "goodsId": "SAMPLE-1", "salePrice": 979, "normalPriceStr": "$19.99",
             "salePriceTextRich": {"ariaLabel": "$9.79"}, "stockQuantity": 1000, "limitQuantity": 99, "isOnsale": 1,
             "thumbUrl": "https://example.com/black.jpg",
             "specs": [{"specKey": "颜色", "specValue": "黑色"}, {"specKey": "尺码", "specValue": "15.75*23.62英寸"}]},
            {"skuId": "BLUE", "goodsId": "SAMPLE-1", "salePrice": 1495,
             "salePriceRich": [{"text": "$"}, {"text": "14.95"}], "stockQuantity": 0, "limitQuantity": 0, "isOnsale": 0,
             "specs": [{"specKey": "颜色", "specValue": "蓝色"}, {"specKey": "尺码", "specValue": "19.69*31.5英寸"}]},
            {"skuId": "FOREIGN", "goodsId": "OTHER-ITEM", "salePrice": 1},
        ],
    }
    return {"source": "temu", "itemId": "SAMPLE-1", "site": "US", "rawData": {"store": store}, "pageContent": ""}


def test_sibling_fields_and_explicit_price_units():
    product = parse_capture(material())
    assert product.currency == "USD"
    assert product.category == "家居用品 / 浴室用品"
    assert product.attributes == {"材料": "硅藻泥（软）", "形状": "矩形"}
    assert len(product.images) == 2
    assert product.detail_images == ["https://example.com/detail.jpg"]
    assert product.video == "https://example.com/video.mp4"
    assert len(product.skus) == 2
    assert (product.spec1_name, product.spec2_name) == ("颜色", "尺码")
    first, second = product.skus
    assert first.source_price == "$9.79" and second.source_price == "$14.95"
    assert first.source_currency == "USD"
    assert (first.source_stock, first.purchase_limit, first.availability) == ("1000", "99", "1")
    assert (second.source_stock, second.purchase_limit, second.availability) == ("0", "0", "0")
    assert first.spec2 == "15.75*23.62英寸"
    assert all(not sku.price and not sku.stock and not sku.weight and not sku.dimensions for sku in product.skus)


# 2026-10-11：本次修改原因：覆盖插件实际发送的内嵌 HTML JSON，排除其它商品上下文的币种和属性。
def test_html_sibling_context_is_attached_to_matching_goods():
    payload = material()
    raw = payload.pop("rawData")
    raw["recommended"] = {"goods": {"goodsId": "OTHER-ITEM", "goodsName": "推荐商品", "gallery": []},
                          "sku": [{"skuId": "OTHER-SKU"}], "localInfo": {"currency": "CNY"},
                          "goodsProperty": [{"key": "错误属性", "values": ["不可采用"]}]}
    payload["pageContent"] = "<script>window.rawData=" + json.dumps(raw, ensure_ascii=False) + ";</script>"
    product = parse_capture(payload)
    assert product.currency == "USD" and len(product.skus) == 2
    assert "错误属性" not in product.attributes
    assert product.video and len(product.detail_images) == 1


def test_explicit_sku_currency_does_not_require_site_guess():
    payload = material()
    store = payload["rawData"]["store"]
    store["localInfo"] = {}
    store["sku"] = store["sku"][:1]
    store["sku"][0]["salePriceTextRich"]["track"] = {"impr": {"curr": "USD"}}
    product = parse_capture(payload)
    assert product.currency == "USD" and product.skus[0].source_currency == "USD"


def legacy_product(repository, capture_id, payload):
    old = parse_capture(payload)
    old.currency, old.category, old.attributes, old.detail_images, old.video, old.skus = "", "", {}, [], "", []
    old.spec1_name, old.spec2_name = "规格1", "规格2"
    old.capture_id = capture_id
    old.warnings = ["未识别到实际 SKU，没有自动创建规格或库存。"]
    return repository.store_parsed(old)[0]


def test_reparse_backfills_existing_capture_and_is_idempotent(tmp_path: Path):
    repository = Repository(tmp_path)
    service = CaptureService(repository)
    payload = material()
    capture_id, _ = repository.create_capture({"payload": payload})
    old = legacy_product(repository, capture_id, payload)
    old.title = "人工编辑标题"
    repository.save_product(old)
    result = service.reparse(capture_id)
    saved = repository.product(old.id)
    assert saved.title == "人工编辑标题"
    assert saved.currency == "USD" and len(saved.skus) == 2
    assert saved.attributes and saved.video and saved.detail_images
    assert saved.spec1_name == "颜色" and saved.spec2_name == "尺码"
    assert result["updated"] and result["summary"]["skus"] == 2
    assert all(not sku.price and not sku.stock for sku in saved.skus)
    assert not saved.approved
    revision = saved.revision
    assert not service.reparse(capture_id)["updated"]
    assert repository.product(saved.id).revision == revision


def test_manual_clears_removed_skus_and_prices_survive_reparse(tmp_path: Path):
    repository = Repository(tmp_path)
    service = CaptureService(repository)
    capture = service.ingest({"payload": material()})
    product = repository.product(capture["productId"])
    product.currency = "CNY"
    product.skus = product.skus[:1]
    product.skus[0].price, product.skus[0].stock, product.skus[0].currency = "88.00", "5", "CNY"
    product.skus[0].image = ""
    product.detail_images, product.video = [], ""
    product.attributes.pop("材料")
    product.attributes["手工属性"] = "保留"
    repository.save_product(product)
    service.reparse(capture["captureId"])
    saved = repository.product(product.id)
    assert len(saved.skus) == 1
    assert (saved.currency, saved.skus[0].price, saved.skus[0].stock) == ("CNY", "88.00", "5")
    assert saved.skus[0].source_currency == "USD" and saved.skus[0].image == ""
    assert saved.detail_images == [] and saved.video == ""
    assert "材料" not in saved.attributes and saved.attributes["手工属性"] == "保留"


def test_backfill_requires_review_and_invalidates_stale_editor(tmp_path: Path):
    repository = Repository(tmp_path)
    service = CaptureService(repository)
    capture = service.ingest({"payload": material()})
    product = repository.product(capture["productId"])
    for sku in product.skus:
        sku.price = "20.00"
    approved = repository.save_product(product, approve=True)
    stale = Product.from_dict(approved.to_dict())
    extra = parse_capture(material())
    extra.detail_images.append("https://example.com/new-detail.jpg")
    saved, updated, summary = repository.backfill_parsed(capture["captureId"], extra)
    assert updated and summary["details"] == 1 and not saved.approved
    assert all(sku.price == "20.00" for sku in saved.skus)
    with pytest.raises(ValueError, match="其他操作"):
        repository.save_product(stale)


def test_legacy_history_preserves_manual_deletions(tmp_path: Path):
    repository = Repository(tmp_path)
    service = CaptureService(repository)
    capture = service.ingest({"payload": material()})
    original = repository.product(capture["productId"])
    edited = Product.from_dict(original.to_dict())
    edited.skus = edited.skus[:1]
    edited.video, edited.detail_images = "", []
    edited.revision += 1
    # 模拟升级前已保存的商品历史：没有新版的人工修改标记。
    body = json.dumps(edited.to_dict(), ensure_ascii=False)
    with repository.connection() as connection:
        connection.execute("UPDATE products SET body=? WHERE id=?", (body, edited.id))
        connection.execute("INSERT INTO product_versions VALUES (?,?,?,?)", (edited.id, edited.revision, body, edited.updated_at))
    service.reparse(capture["captureId"])
    saved = repository.product(edited.id)
    assert len(saved.skus) == 1 and saved.video == "" and saved.detail_images == []
