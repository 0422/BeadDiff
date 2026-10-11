# 2026-10-11：本次修改原因：提供离线 HTTP 回归用例，验证签名、字段增量合并、账号隔离和未知结果；不连接真实 ERP。
from copy import deepcopy
import hashlib
import hmac
import json

import httpx
import pytest

from beaddiff.erp import ERPNotSentError, ERPRejectedError, ERPRequest, ERPService, ERPUncertainError
from beaddiff.miaoshou import CREATE_PATH, DETAIL_PATH, LIST_PATH, PICTURE_PATH, UPDATE_PATH, MiaoshouAdapter, MiaoshouClient
from beaddiff.miaoshou_config import API_BASE, MiaoshouConfig, MiaoshouConfigStore
from beaddiff.miaoshou_mapping import create_payload, edited_fields, match_sku_links, update_payload
from beaddiff.models import Product, SKU
from beaddiff.storage import Repository


def config():
    return MiaoshouConfig("test-app-key", "test-app-secret", cny_rates={"CNY": "1", "USD": "7.20"})


def product():
    return Product(title="测试商品", main_code="BD-1", currency="USD", source_id="SOURCE-1",
        images=["https://example.com/main.jpg"], simple_description="简述", description_html="<p>详情</p>",
        skus=[SKU(source_sku_id="SKU-A", platform_sku="SELL-A", spec1="蓝色", spec2="M", price="2.50",
                  source_price="$1.00", source_currency="USD", stock="4", weight="0.15", dimensions="10*8*2")])


def remote():
    return {"commonCollectBoxDetailId": 123, "title": "远端标题", "itemNum": "REMOTE-1", "price": 8,
        "notes": '<div style="color:red">远端详情<img src="https://example.com/old.jpg" /></div>',
        "notesText": "远端简述", "imgUrls": ["https://example.com/old.jpg"],
        "colorMap": {"COLOR-ID": {"name": "蓝色", "imgUrls": ["https://example.com/color.jpg"]}},
        "sizeMap": {"SIZE-ID": {"name": "M"}}, "colorPropName": "颜色", "sizePropName": "尺码",
        "skuMap": {";COLOR-ID;SIZE-ID;": {"itemNum": "SELL-A", "price": 12, "stock": 20, "oriPrice": 10, "weight": 0.2}},
        "sourceAttrs": [{"name": "材质", "value": "棉"}, {"name": "仅妙手有", "value": "保留"}],
        "sourceList": [{"sourceItemId": "SOURCE-1", "source": "temu", "sourceItemUrl": "https://example.com/source"}],
        "productCertifications": [{"fileName": "附件1", "fileUrl": "https://example.com/cert.pdf"}],
        "cateList": [{"cateId": 99}], "sourceMataInfo": {"readOnly": True}}


def success(data):
    return httpx.Response(200, json={"result": "success", "code": "success", "data": data})


def adapter(tmp_path, handler):
    store = MiaoshouConfigStore(tmp_path)
    store.save(config())
    return MiaoshouAdapter(store, httpx.MockTransport(handler))


def test_exact_unicode_request_bytes_are_signed(monkeypatch):
    monkeypatch.setattr("beaddiff.miaoshou.time.time", lambda: 1791648000)
    captured = []
    def handler(request):
        captured.append(request)
        return success({"commonCollectBoxDetailId": 321})
    client = MiaoshouClient(config(), httpx.MockTransport(handler))
    client.call(CREATE_PATH, {"title": "蓝色珠串", "price": 12.34}, saving_product=True)
    request = captured[0]
    body = request.content.decode("utf-8")
    assert "蓝色珠串" in body and "\\u" not in body
    secret = config().app_secret
    expected = hmac.new(secret.encode(), (secret + CREATE_PATH + "1791648000" + config().app_key + body + secret).encode(), hashlib.sha256).hexdigest()
    assert request.headers["x-sign"] == expected
    assert str(request.url) == API_BASE + CREATE_PATH


# 2026-10-11：本次修改原因：连接测试及来源查询必须使用只读列表接口，关键词不代表精确命中。
def test_list_query_uses_source_filter_and_pagination():
    def handler(request):
        assert request.url.path == LIST_PATH
        assert json.loads(request.content) == {"pageNo": 2, "pageSize": 100,
            "filter": {"tabPaneName": "all", "sourceItemIdKeyword": "SOURCE-1"}}
        return success({"detailList": [], "total": 0})
    assert MiaoshouClient(config(), httpx.MockTransport(handler)).list_products("SOURCE-1", 2)["total"] == 0


def test_settings_load_no_startup_write_and_detect_external_change(tmp_path):
    store = MiaoshouConfigStore(tmp_path)
    assert not store.path.exists()
    store.save(config())
    loaded = MiaoshouConfigStore(tmp_path)
    assert loaded.get().app_secret == config().app_secret
    store.path.write_text('{"version":1}', encoding="utf-8")
    with pytest.raises(ValueError, match="外部修改"):
        loaded.save(config())
    assert "test-app-secret" not in repr(config())


def test_create_maps_cny_units_html_and_keeps_source_cost_separate():
    item = product()
    item.detail_images = ["https://example.com/detail.jpg"]
    item.package_weight = "0.35"
    item.package_dimensions = "30*20*3"
    payload = create_payload(item, config())
    assert payload["skuMap"][";蓝色;M;"]["price"] == 18
    assert payload["price"] == 7.2
    assert payload["weight"] == 0.35 and payload["packageLength"] == 30
    assert "detail.jpg" in payload["notes"]
    assert payload["notesText"] == "简述"
    assert "cateList" not in payload and "detail_images" not in payload


def test_single_sku_manual_supply_cost_is_independent_of_sale_price():
    item = product()
    item.skus[0].source_price = ""
    with pytest.raises(ValueError, match="货源价"):
        create_payload(item, config())
    item.supply_price = "3"
    assert create_payload(item, config())["price"] == 21.6


def test_unknown_currency_and_local_pictures_block_before_submit():
    item = product()
    with pytest.raises(ValueError, match="CNY"):
        create_payload(item, MiaoshouConfig("key", "secret"))
    item.images = ["file:///C:/generated.png"]
    with pytest.raises(ValueError, match="本机"):
        create_payload(item, config())


def test_update_only_edited_fields_keeps_remote_skus_source_and_attachments():
    item = product()
    original = remote()
    preserved = deepcopy(original)
    item.manual_fields = ["title", "simple_description", "sku:SKU-A:price", "attribute:材质"]
    item.attributes = {"材质": "玻璃"}
    item.erp_sku_links = match_sku_links(item, item, original)
    payload, links = update_payload(item, original, config())
    assert payload["title"] == item.title and payload["notesText"] == item.simple_description
    assert payload["notes"] == original["notes"] and payload["imgUrls"] == original["imgUrls"]
    sku = payload["skuMap"][";COLOR-ID;SIZE-ID;"]
    assert sku["price"] == 18 and sku["oriPrice"] == 10 and sku["stock"] == 20 and sku["weight"] == 0.2
    assert payload["productCertifications"] == original["productCertifications"]
    assert {row["name"]: row["value"] for row in payload["sourceAttrs"]} == {"材质": "玻璃", "仅妙手有": "保留"}
    assert payload["sourceList"] == original["sourceList"]
    assert "cateList" not in payload and "sourceMataInfo" not in payload
    assert original == preserved and links["SKU-A"] == ";COLOR-ID;SIZE-ID;"


def test_detail_image_only_change_keeps_remote_text_and_style():
    item = product()
    item.manual_fields = ["detail_images"]
    item.detail_images = ["https://example.com/new-detail.jpg"]
    payload, _ = update_payload(item, remote(), config())
    assert 'style="color:red"' in payload["notes"] and "远端详情" in payload["notes"]
    assert "new-detail.jpg" in payload["notes"] and "old.jpg" not in payload["notes"]


# 2026-10-11：本次修改原因：删除富文本中的图片后，旧详情图列表不能在回传时自动将其恢复。
def test_explicit_html_edit_and_clear_do_not_restore_removed_images():
    item = product()
    item.detail_images = ["https://example.com/removed.jpg"]
    item.manual_fields = ["description_html"]
    item.description_html = "<p>保留当前正文</p>"
    assert create_payload(item, config())["notes"] == item.description_html
    assert update_payload(item, remote(), config())[0]["notes"] == item.description_html
    item.description_html = ""
    assert update_payload(item, remote(), config())[0]["notes"] == ""


def test_baseline_does_not_resend_old_changes():
    item = product()
    item.manual_fields = ["title", "sku:SKU-A:price"]
    item.erp_update_baseline = item.to_dict()
    item.simple_description = "新简述"
    item.manual_fields.append("simple_description")
    assert edited_fields(item) == {"simple_description"}
    payload, _ = update_payload(item, remote(), config())
    assert payload["title"] == "远端标题" and payload["skuMap"][";COLOR-ID;SIZE-ID;"]["price"] == 12


# 2026-10-11：本次修改原因：带冒号/共同前缀的来源 SKU ID 不能互相覆盖售价。
def test_sku_identity_with_colon_does_not_match_shorter_prefix():
    item = product()
    item.skus[0].source_sku_id = "A"
    item.skus.append(SKU(source_sku_id="A:B", spec1="红色", spec2="M", price="3", currency="USD"))
    original = remote()
    original["colorMap"]["RED-ID"] = {"name": "红色"}
    original["skuMap"][";RED-ID;SIZE-ID;"] = {"price": 15}
    item.erp_sku_links = {"A": ";COLOR-ID;SIZE-ID;", "A:B": ";RED-ID;SIZE-ID;"}
    item.manual_fields = ["sku:A:B:price"]
    payload, _ = update_payload(item, original, config())
    assert payload["skuMap"][";COLOR-ID;SIZE-ID;"]["price"] == 12
    assert payload["skuMap"][";RED-ID;SIZE-ID;"]["price"] == 21.6


@pytest.mark.parametrize("field", ["category", "body_size_chart", "skus", "spec1_name"])
def test_unsupported_or_unverified_structure_changes_cannot_be_marked_transferred(field):
    item = product()
    item.manual_fields = [field]
    with pytest.raises(ValueError):
        update_payload(item, remote(), config())


@pytest.mark.parametrize("code,exception", [("signInvalid", ERPRejectedError), ("appNoPermission", ERPRejectedError),
                                          ("upstreamReadTimeout", ERPUncertainError), ("systemError", ERPUncertainError)])
def test_rejection_and_ambiguous_save_errors_are_different(code, exception):
    def handler(request):
        return httpx.Response(200, json={"result": "fail", "code": code, "message": config().app_secret})
    client = MiaoshouClient(config(), httpx.MockTransport(handler))
    with pytest.raises(exception) as caught:
        client.call(CREATE_PATH, {"title": "产品"}, saving_product=True)
    assert config().app_secret not in str(caught.value)
    assert config().app_secret not in json.dumps(caught.value.details)


def test_query_timeout_is_not_an_unknown_product_save():
    def handler(request):
        raise httpx.ReadTimeout("timeout", request=request)
    client = MiaoshouClient(config(), httpx.MockTransport(handler))
    with pytest.raises(ERPNotSentError):
        client.list_products()
    with pytest.raises(ERPUncertainError):
        client.call(CREATE_PATH, {"title": "产品"}, saving_product=True)


def test_real_create_and_update_use_documented_envelopes(tmp_path):
    calls = []
    def handler(request):
        path, body = request.url.path, json.loads(request.content)
        calls.append((path, body))
        if path == PICTURE_PATH:
            return success({"picturePath": "https://cdn.example.com/main.jpg", "appPictureId": 10})
        if path == CREATE_PATH:
            assert body["imgUrls"] == ["https://cdn.example.com/main.jpg"]
            return success({"commonCollectBoxDetailId": 456})
        if path == DETAIL_PATH:
            return success({"editCommonCollectBoxDetail": remote(), "ossMd5": "fresh-md5"})
        if path == UPDATE_PATH:
            assert body["commonCollectBoxDetailId"] == 123 and body["ossMd5"] == "fresh-md5"
            assert body["editCommonCollectBoxDetail"]["title"] == "新标题"
            return success({"ossMd5": "saved-md5"})
        raise AssertionError(path)
    service = adapter(tmp_path, handler)
    item = product()
    created = service.send(ERPRequest("T1", "create", item, ""))
    assert created.target_id == "456" and created.receipt_id == "456"
    item.erp_original_id = "123"
    item.erp_original_account = config().account_id
    item.manual_fields = ["title"]
    item.title = "新标题"
    updated = service.send(ERPRequest("T2", "update", item, "123"))
    assert updated.target_id == "123" and updated.receipt_id == "saved-md5"
    assert [path for path, _ in calls] == [PICTURE_PATH, CREATE_PATH, DETAIL_PATH, UPDATE_PATH]


def test_binding_preserves_old_edits_and_success_uses_sent_baseline(tmp_path):
    repository = Repository(tmp_path)
    item, _ = repository.store_parsed(product())
    item.title = "已编辑标题"
    item = repository.save_product(item, approve=True)
    item = repository.bind_erp_original(item.id, "123", config().account_id, {"SKU-A": ";COLOR-ID;SIZE-ID;"}, item.revision)
    assert "title" in edited_fields(item) and not item.erp_update_baseline
    def handler(request):
        if request.url.path == DETAIL_PATH:
            return success({"editCommonCollectBoxDetail": remote(), "ossMd5": "fresh"})
        assert request.url.path == UPDATE_PATH
        return success({"ossMd5": "saved"})
    results = ERPService(repository, adapter(tmp_path, handler)).transfer([item.id], "update")
    assert results[0]["state"] == "succeeded"
    saved = repository.product(item.id)
    assert saved.erp_status == "已传" and not edited_fields(saved)
    assert "erp_update_baseline" not in saved.erp_update_baseline
    saved.simple_description = "下一次修改"
    saved = repository.save_product(saved, approve=True)
    assert edited_fields(saved) == {"simple_description"}


def test_wrong_account_cannot_update_or_resolve_unknown(tmp_path):
    service = adapter(tmp_path, lambda request: pytest.fail("不应请求服务器"))
    item = product()
    item.erp_original_id = "123"
    item.erp_original_account = "different-account"
    assert "账号" in service.validate(item, "update")[0]


def test_unknown_update_can_only_resolve_from_matching_real_detail(tmp_path):
    repository = Repository(tmp_path)
    item, _ = repository.store_parsed(product())
    item.title = "已提交标题"
    item = repository.save_product(item, approve=True)
    item = repository.bind_erp_original(item.id, "123", config().account_id, {}, item.revision)
    server = remote()
    def handler(request):
        if request.url.path == DETAIL_PATH:
            return success({"editCommonCollectBoxDetail": deepcopy(server), "ossMd5": "verified"})
        if request.url.path == UPDATE_PATH:
            server.update(json.loads(request.content)["editCommonCollectBoxDetail"])
            # 2026-10-11：本次修改原因：服务器补充默认字段不应使已提交内容无法核对。
            server["skuMap"][";COLOR-ID;SIZE-ID;"]["oriStock"] = 0
            raise httpx.ReadTimeout("saved but timed out", request=request)
        raise AssertionError("核对不应写入远端")
    service = ERPService(repository, adapter(tmp_path, handler))
    assert service.transfer([item.id], "update")[0]["state"] == "unknown"
    record = repository.erp_transfers()[0]
    with pytest.raises(ERPNotSentError, match="原商品"):
        service.reconcile(record["id"], "999")
    service.reconcile(record["id"], "123")
    assert repository.erp_transfers()[0]["state"] == "succeeded"
    assert repository.product(item.id).erp_status == "已传"
