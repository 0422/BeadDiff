# 2026-10-12：本次修改原因：离线覆盖 API 导入完整字段留存、账号去重、CNY 金额、增量更新和新增副本，不调用真实 ERP。
from copy import deepcopy
import json

import httpx
import pytest

# from beaddiff.erp import ERPNotSentError, ERPRequest
# 2026-10-12：本次修改原因：覆盖服务层增量审核，防止标题更新被未编辑的物流占位阻挡。
from beaddiff.erp import ERPNotSentError, ERPRequest, ERPService
from beaddiff.miaoshou import CREATE_PATH, DETAIL_PATH, UPDATE_PATH, MiaoshouAdapter
from beaddiff.miaoshou_config import MiaoshouConfig, MiaoshouConfigStore
from beaddiff.miaoshou_import import MiaoshouImportService, parse_miaoshou_detail
from beaddiff.miaoshou_mapping import create_payload, draft_limit_issues, preserve_unedited_form, update_payload
from beaddiff.models import Product, SKU
from beaddiff.storage import Repository


def config():
    return MiaoshouConfig("import-key", "import-secret", cny_rates={"CNY": "1", "USD": "7.2"})


def detail(target=123):
    return {"ossMd5": "import-md5", "editCommonCollectBoxDetail": {
        "commonCollectBoxDetailId": target, "title": "ERP 标题", "itemNum": "ERP-CODE", "price": 8.5,
        "notesText": "简述", "notes": '<div class="original" style="color:red"><p>原文</p><img src="https://cdn.example.com/detail.jpg"></div>',
        "imgUrls": ["https://cdn.example.com/main.jpg"], "colorPropName": "颜色", "sizePropName": "尺码",
        "colorMap": {"C1": {"name": "白色", "imgUrl": "https://cdn.example.com/color.jpg",
                                "imgUrls": ["https://cdn.example.com/color.jpg", "https://cdn.example.com/extra.jpg"]}},
        "sizeMap": {"S1": {"name": "M"}},
        "skuMap": {";C1;S1;": {"itemNum": "SELL-1", "price": 20, "stock": 0, "oriPrice": 18, "weight": 0.2}},
        "sourceAttrs": [{"name": "材质", "value": "塑料"}],
        "sourceList": [{"source": "temu", "sourceSite": "US", "sourceItemId": "SOURCE-1", "sourceItemUrl": "https://example.com/product", "remark": "采购"}],
        "productCertifications": [{"fileName": "a.pdf", "fileUrl": "https://example.com/a.pdf"},
                                  {"fileName": "b.pdf", "fileUrl": "https://example.com/b.pdf"}],
        "guideInfo": {"productGuideFileUrl": "https://example.com/guide.pdf"},
        "sourceMataInfo": {"notEditable": True}, "weight": 0.3, "packageLength": 30, "packageWidth": 20, "packageHeight": 3,
    }}


def service(tmp_path, handler):
    store = MiaoshouConfigStore(tmp_path)
    store.save(config())
    adapter = MiaoshouAdapter(store, httpx.MockTransport(handler))
    return MiaoshouImportService(Repository(tmp_path), adapter)


def success(data):
    return httpx.Response(200, json={"result": "success", "code": "success", "data": data})


def test_import_keeps_complete_remote_detail_and_separate_prices():
    material = detail()
    item = parse_miaoshou_detail(material, config().account_id)
    assert item.currency == item.skus[0].currency == "CNY"
    assert item.supply_price == "8.5" and item.skus[0].price == "20"
    assert item.skus[0].stock == "0" and not item.skus[0].source_price
    assert item.erp_sku_links[item.skus[0].identity] == ";C1;S1;"
    assert item.package_dimensions == "30*20*3"
    assert item.description_html == material["editCommonCollectBoxDetail"]["notes"]
    assert item.erp_remote_snapshot == material["editCommonCollectBoxDetail"]
    assert not item.content_modified and not item.approved and not item.erp_content_hash
    item.erp_remote_snapshot["title"] = "copy"
    assert material["editCommonCollectBoxDetail"]["title"] == "ERP 标题"


def test_import_dedup_is_account_and_erp_id_and_keeps_plugin_work(tmp_path):
    repository = Repository(tmp_path)
    plugin, _ = repository.store_parsed(Product(source="temu", source_id="SOURCE-1", site="US", title="插件自解析"))
    plugin.title = "保留插件编辑"
    repository.save_product(plugin)
    item, created = repository.store_miaoshou_import(parse_miaoshou_detail(detail(), config().account_id))
    assert created and item.id != plugin.id
    item.title = "本机新标题"
    repository.save_product(item)
    again, created = repository.store_miaoshou_import(parse_miaoshou_detail(detail(), config().account_id))
    assert not created and again.id == item.id and again.title == "本机新标题"
    other = MiaoshouConfig("another-key", "secret").account_id
    second, created = repository.store_miaoshou_import(parse_miaoshou_detail(detail(), other))
    assert created and second.id != item.id
    third, created = repository.store_miaoshou_import(parse_miaoshou_detail(detail(456), config().account_id))
    assert created and third.id != item.id
    assert repository.product(plugin.id).title == "保留插件编辑"
    assert len(repository.products()) == 4


def test_partial_import_returns_success_and_failure_and_only_reads_api(tmp_path):
    calls = []
    def handler(request):
        calls.append(request.url.path)
        assert request.url.path == DETAIL_PATH
        target = json.loads(request.content)["commonCollectBoxDetailId"]
        if target == 456:
            return httpx.Response(200, json={"result": "fail", "code": "fail", "message": "无权限"})
        return success(detail(target))
    importer = service(tmp_path, handler)
    result = importer.import_products(importer.adapter.client(), ["123", "456", "123"])
    assert [row["state"] for row in result["results"]] == ["imported", "failed"]
    assert len(importer.repository.products()) == 1 and calls == [DETAIL_PATH, DETAIL_PATH]
    assert importer.import_products(importer.adapter.client(), ["123"])["results"][0]["state"] == "existing"


def test_api_update_fetches_fresh_detail_preserves_untouched_fields_and_does_not_upload(tmp_path):
    requests = []
    fresh = detail()
    fresh["ossMd5"] = "fresh-md5"
    fresh["editCommonCollectBoxDetail"]["notesText"] = "妙手后来修改"
    def handler(request):
        requests.append(request.url.path)
        if request.url.path == DETAIL_PATH:
            return success(fresh)
        assert request.url.path == UPDATE_PATH
        body = json.loads(request.content)
        assert body["ossMd5"] == "fresh-md5" and body["commonCollectBoxDetailId"] == 123
        payload = body["editCommonCollectBoxDetail"]
        assert payload["title"] == "本机加工标题" and payload["notesText"] == "妙手后来修改"
        assert payload["price"] == 8.5 and payload["skuMap"][";C1;S1;"]["price"] == 20
        assert payload["colorMap"] == fresh["editCommonCollectBoxDetail"]["colorMap"]
        assert len(payload["productCertifications"]) == 2 and "sourceMataInfo" not in payload
        return success({"ossMd5": "saved-md5"})
    importer = service(tmp_path, handler)
    item, _ = importer.repository.store_miaoshou_import(parse_miaoshou_detail(detail(), config().account_id))
    item.title = "本机加工标题"
    item = importer.repository.save_product(item, approve=True)
    receipt = importer.adapter.send(ERPRequest("test", "update", item, "123"))
    assert receipt.receipt_id == "saved-md5" and requests == [DETAIL_PATH, UPDATE_PATH]
    assert receipt.details["picture_progress"]["uploaded"] == 0


def test_api_create_copy_keeps_price_images_and_extra_fields(tmp_path):
    def handler(request):
        assert request.url.path == CREATE_PATH
        payload = json.loads(request.content)
        assert "commonCollectBoxDetailId" not in payload
        assert payload["title"] == "复制后的加工标题" and payload["price"] == 8.5
        assert payload["skuMap"][";C1;S1;"]["price"] == 20
        assert len(payload["productCertifications"]) == 2
        return success({"commonCollectBoxDetailId": 999})
    importer = service(tmp_path, handler)
    item, _ = importer.repository.store_miaoshou_import(parse_miaoshou_detail(detail(), config().account_id))
    item.title = "复制后的加工标题"
    item = importer.repository.save_product(item, approve=True)
    receipt = importer.adapter.send(ERPRequest("test", "create", item, ""))
    assert receipt.target_id == "999" and receipt.details["picture_progress"]["uploaded"] == 0


def test_multi_sku_new_product_requires_top_price_before_any_api_call(tmp_path):
    item = Product(title="多规格", main_code="CODE", currency="CNY", images=["https://example.com/main.jpg"],
                   skus=[SKU(source_sku_id="A", spec1="白", price="20"), SKU(source_sku_id="B", spec1="黑", price="25")])
    with pytest.raises(ValueError, match="独立货源价"):
        create_payload(item, config())
    importer = service(tmp_path, lambda request: pytest.fail("缺价格不能调用任何接口"))
    with pytest.raises(ERPNotSentError, match="独立货源价"):
        importer.adapter.send(ERPRequest("test", "create", item, ""))
    item.supply_price = "8"
    assert create_payload(item, config())["price"] == 8


def test_unedited_form_html_and_whitespace_are_preserved_when_only_title_changes():
    original = parse_miaoshou_detail(detail(), config().account_id)
    original.simple_description = "  原有空格  "
    initial = Product.from_dict(original.to_dict())
    initial.description_html = "<p>Qt 规范化显示</p>"
    initial.simple_description = "原有空格"
    current = Product.from_dict(initial.to_dict())
    current.title = "真正编辑的标题"
    saved = preserve_unedited_form(original, initial, current)
    assert saved.description_html == original.description_html and saved.simple_description == original.simple_description
    assert saved.title == "真正编辑的标题" and saved.skus == original.skus


def test_three_dimensions_can_edit_text_without_collapsing_skus():
    material = detail()
    remote = material["editCommonCollectBoxDetail"]
    remote["saleProp3Name"] = "包装"
    remote["saleProp3Map"] = {"P1": {"name": "单件"}, "P2": {"name": "双件"}}
    sku = remote["skuMap"].pop(";C1;S1;")
    remote["skuMap"] = {";C1;S1;P1;": deepcopy(sku), ";C1;S1;P2;": deepcopy(sku)}
    item = parse_miaoshou_detail(material, config().account_id)
    assert not item.issues()
    item.title = "三维商品改标题"
    item.manual_fields = ["title"]
    payload, _ = update_payload(item, remote, config())
    assert payload["skuMap"] == remote["skuMap"] and payload["saleProp3Map"] == remote["saleProp3Map"]
    assert create_payload(item, config())["skuMap"] == remote["skuMap"]
    item.skus[0].price = "99"
    item.manual_fields.append(f"sku:{item.skus[0].identity}:price")
    with pytest.raises(ValueError, match="第三规格"):
        update_payload(item, remote, config())


def test_saved_edits_and_ai_candidates_use_same_limits(tmp_path):
    repository = Repository(tmp_path)
    item, _ = repository.store_miaoshou_import(parse_miaoshou_detail(detail(), config().account_id))
    item.title = "字" * 256
    assert "255" in draft_limit_issues(item)[0]
    with pytest.raises(ValueError, match="255"):
        repository.save_product(item)
    assert repository.product(item.id).title == "ERP 标题"
    item.title = "合规标题"
    item.images = [f"https://example.com/{number}.jpg" for number in range(16)]
    with pytest.raises(ValueError, match="15 张"):
        repository.save_product(item)


# 2026-10-12：本次修改原因：已成功更新过的加工内容，再创建副本时不能被旧远端快照和更新基线覆盖掉。
def test_create_copy_after_successful_update_still_includes_all_processed_fields():
    item = parse_miaoshou_detail(detail(), config().account_id)
    item.title = "已成功更新的标题"
    item.simple_description = "已加工简述"
    item.skus[0].price = "33"
    item.manual_fields = ["title", "simple_description", f"sku:{item.skus[0].identity}:price"]
    item.erp_update_baseline = {key: value for key, value in item.to_dict().items() if not key.startswith("erp_")}
    payload = create_payload(item, config())
    assert payload["title"] == item.title and payload["notesText"] == item.simple_description
    assert payload["skuMap"][";C1;S1;"]["price"] == 33


# 2026-10-12：本次修改原因：原空编号/售价及零物流不能阻挡只改标题，修改后的非法数值仍须被审核拦截。
def test_incremental_review_preserves_remote_placeholders_and_checks_changed_values(tmp_path):
    material = detail()
    remote = material["editCommonCollectBoxDetail"]
    remote.update(itemNum="", weight=0, packageLength=0, packageWidth=0, packageHeight=0)
    remote["skuMap"][";C1;S1;"].update(price=None, weight=0, packageLength=0, packageWidth=0, packageHeight=0)
    requests = []
    def handler(request):
        requests.append(request.url.path)
        if request.url.path == DETAIL_PATH:
            return success(material)
        assert request.url.path == UPDATE_PATH
        body = json.loads(request.content)["editCommonCollectBoxDetail"]
        assert body["title"] == "只修改标题" and body["weight"] == 0 and body["itemNum"] == ""
        assert body["skuMap"] == remote["skuMap"]
        return success({"ossMd5": "saved-md5"})
    importer = service(tmp_path, handler)
    item, _ = importer.repository.store_miaoshou_import(parse_miaoshou_detail(material, config().account_id))
    assert item.issues() and not item.review_issues()
    item.title = "只修改标题"
    saved = importer.repository.save_product(item, approve=True)
    erp = ERPService(importer.repository, importer.adapter)
    assert saved.status == "已审核" and not erp.issues(saved, "update")
    assert erp.issues(saved, "create")
    assert erp.transfer([saved.id], "update")[0]["state"] == "succeeded"
    assert requests == [DETAIL_PATH, UPDATE_PATH]
    changed = importer.repository.product(saved.id)
    changed.skus[0].price = "-1"
    with pytest.raises(ValueError, match="售价"):
        importer.repository.save_product(changed, approve=True)
    assert importer.repository.product(saved.id).skus[0].price == ""


# 2026-10-12：本次修改原因：空第三槽位保留原组合键，既有两维价格和规格图仍可修改。
def test_empty_third_slot_preserves_exact_key_when_editing_existing_sku():
    material = detail()
    remote = material["editCommonCollectBoxDetail"]
    key = ";C1;S1;;"
    remote["skuMap"] = {key: remote["skuMap"].pop(";C1;S1;")}
    item = parse_miaoshou_detail(material, config().account_id)
    item.skus[0].price = "29"
    item.skus[0].image = "https://example.com/new-color.jpg"
    item.manual_fields = [f"sku:{item.skus[0].identity}:price", f"sku:{item.skus[0].identity}:image"]
    payload, links = update_payload(item, remote, config())
    assert list(payload["skuMap"]) == [key] and payload["skuMap"][key]["price"] == 29
    assert links[item.skus[0].identity] == key
    assert payload["colorMap"]["C1"]["imgUrl"] == item.skus[0].image


# 2026-10-12：本次修改原因：API 隐藏的远端套图超限也需要在保存前提示，原始详情快照保留供核查。
def test_hidden_remote_gallery_limits_cannot_be_bypassed_by_title_edit(tmp_path):
    material = detail()
    material["editCommonCollectBoxDetail"]["colorMap"]["C1"]["imgUrls"] = [
        f"https://example.com/gallery{index}.jpg" for index in range(11)]
    repository = Repository(tmp_path)
    item, _ = repository.store_miaoshou_import(parse_miaoshou_detail(material, config().account_id))
    assert len(item.skus) == 1 and item.status == "待完善"
    item.title = "只改标题不能绕过"
    with pytest.raises(ValueError, match="11 张.*10 张"):
        repository.save_product(item)
    saved = repository.product(item.id)
    assert saved.title == "ERP 标题" and saved.revision == 1
    assert len(saved.erp_remote_snapshot["colorMap"]["C1"]["imgUrls"]) == 11
