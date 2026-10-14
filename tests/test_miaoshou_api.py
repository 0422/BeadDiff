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
# 2026-10-12：本次修改原因：验证缓存启动不写文件、账号隔离、重启复用和网络失败不误缓存。
from beaddiff.miaoshou_picture_cache import MiaoshouPictureCache


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


# 2026-10-12：本次修改原因：复现采集到的 Temu 超长 SEO/追踪链接，校验商品身份与地区保留且本地内容不被改写。
@pytest.mark.parametrize("path,query,prefix", [
    ("/us-zh-Hans/" + "%E5%95%86" * 50 + "-g-601099651743804.html", "track=" + "x" * 300, "/us-zh-Hans"),
    ("/goods.html", "goods_id=601099651743804&track=" + "x" * 300, ""),
    ("/us/goods.html", "goods_id=601099651743804&goods_id=601099651743804&track=" + "x" * 300, "/us"),
])
def test_long_temu_source_url_is_shortened_only_in_payload(path, query, prefix):
    item = product()
    item.source_url = "https://www.temu.com" + path + "?" + query
    preserved = item.to_dict()
    payload = create_payload(item, config())
    assert payload["sourceList"][0]["sourceItemUrl"] == (
        "https://www.temu.com" + prefix + "/goods.html?goods_id=601099651743804")
    assert payload["sourceList"][0]["sourceItemId"] == item.source_id
    assert item.to_dict() == preserved


# 2026-10-12：本次修改原因：不能猜测其他平台、伪装域名或相互冲突的商品 ID，也不能截断未知链接。
@pytest.mark.parametrize("url", [
    "https://example.com/goods.html?goods_id=601099651743804&track=" + "x" * 300,
    "https://www.temu.com.example.com/goods.html?goods_id=601099651743804&track=" + "x" * 300,
    "https://www.temu.com/g-601099651743804.html?goods_id=601100949444099&track=" + "x" * 300,
    "https://www.temu.com/goods.html?goods_id=&track=" + "x" * 300,
    "https://www.temu.com/goods.html?track=" + "x" * 300,
])
def test_unrecognized_long_source_url_has_specific_length_error(url):
    item = product()
    item.source_url = url
    with pytest.raises(ValueError) as caught:
        create_payload(item, config())
    assert "第 1 条货源的货源链接（sourceItemUrl）" in str(caught.value)
    assert str(len(url)) in str(caught.value) and "255" in str(caught.value)
    assert item.source_url == url


# 2026-10-12：本次修改原因：合规短链接不丢失既有参数；超长备注仍需用户处理，提示应指出具体字段。
def test_short_source_url_is_preserved_and_long_remark_is_identified():
    item = product()
    item.source_url = "https://www.temu.com/goods.html?goods_id=601099651743804&sku_id=123"
    assert create_payload(item, config())["sourceList"][0]["sourceItemUrl"] == item.source_url
    item.source_remark = "备注" * 128
    with pytest.raises(ValueError, match=r"货源备注（remark）为 256 个字符"):
        create_payload(item, config())


# 2026-10-12：本次修改原因：更新处理远端长链接和人工新链接时都取 URL 自身商品 ID，不改写其他货源或输入对象。
@pytest.mark.parametrize("edit_url", [False, True])
def test_update_normalizes_source_copy_without_using_local_source_id_as_url_id(edit_url):
    item = product()
    original = remote()
    long_url = "https://www.temu.com/us-zh-Hans/" + "%E5%95%86" * 50 + "-g-601100949444099.html?track=" + "x" * 300
    original["sourceList"].append({"sourceItemId": "OTHER", "sourceItemUrl": "https://example.com/other", "remark": "保留"})
    if edit_url:
        item.source_url = long_url
        item.manual_fields = ["source_url"]
    else:
        original["sourceList"][0]["sourceItemUrl"] = long_url
        item.manual_fields = ["title"]
    preserved = deepcopy(original)
    local = item.to_dict()
    payload, _ = update_payload(item, original, config())
    assert payload["sourceList"][0]["sourceItemUrl"] == "https://www.temu.com/us-zh-Hans/goods.html?goods_id=601100949444099"
    assert payload["sourceList"][1] == preserved["sourceList"][1]
    assert original == preserved and item.to_dict() == local


# 2026-10-12：本次修改原因：复现同颜色多个尺码和不同图片，去重保留顺序且不混入其他颜色，不修改本地 SKU。
def test_create_groups_distinct_size_pictures_by_spec1_and_deduplicates():
    item = product()
    # 2026-10-12：本次修改原因：多规格图片回归提供独立必填货源价，使测试仍验证图片组行为。
    item.supply_price = "1"
    item.skus[0].image = "https://example.com/blue-M.jpg"
    item.skus.extend([
        SKU(source_sku_id="SKU-B", spec1="蓝色", spec2="L", price="3", image="https://example.com/blue-L.jpg"),
        SKU(source_sku_id="SKU-C", spec1="蓝色", spec2="XL", price="4", image="https://example.com/blue-XL.jpg"),
        SKU(source_sku_id="SKU-D", spec1="蓝色", spec2="XXL", price="5", image="https://example.com/blue-M.jpg"),
        SKU(source_sku_id="SKU-E", spec1="红色", spec2="M", price="3", image="https://example.com/red-M.jpg"),
    ])
    preserved = item.to_dict()
    payload = create_payload(item, config())
    assert payload["colorMap"]["蓝色"] == {"name": "蓝色", "imgUrl": "https://example.com/blue-M.jpg",
        "imgUrls": ["https://example.com/blue-M.jpg", "https://example.com/blue-L.jpg", "https://example.com/blue-XL.jpg"]}
    assert payload["colorMap"]["红色"]["imgUrls"] == ["https://example.com/red-M.jpg"]
    assert len(payload["skuMap"]) == 5 and payload["skuMap"][";蓝色;M;"]["price"] == 18
    assert item.to_dict() == preserved


# 2026-10-12：本次修改原因：超过接口图片数量时明确失败，不能静默丢弃采集的尺码图片。
def test_create_rejects_over_ten_distinct_images_in_one_spec1_group():
    item = product()
    # 2026-10-12：本次修改原因：补齐新增必填货源价后再验证同规格图片数量上限。
    item.supply_price = "1"
    item.skus = [SKU(source_sku_id=f"SKU-{index}", spec1="蓝色", spec2=str(index), price="3",
                     image=f"https://example.com/blue-{index}.jpg") for index in range(11)]
    with pytest.raises(ValueError, match="蓝色.*11 张不同图片.*10 张"):
        create_payload(item, config())


# 2026-10-12：本次修改原因：构造有两个尺码及额外附图的远端商品，验证更新时不会覆盖未编辑图片或其他颜色。
def image_update_pair():
    item = product()
    item.skus[0].image = "https://example.com/blue-M.jpg"
    item.skus.append(SKU(source_sku_id="SKU-B", spec1="蓝色", spec2="L", price="3", image="https://example.com/blue-L.jpg"))
    original = remote()
    original["colorMap"]["COLOR-ID"].update(imgUrl=item.skus[0].image,
        imgUrls=[item.skus[0].image, item.skus[1].image, "https://example.com/remote-extra.jpg"])
    original["colorMap"]["RED-ID"] = {"name": "红色", "imgUrl": "https://example.com/red.jpg", "imgUrls": ["https://example.com/red.jpg"]}
    original["sizeMap"]["L-ID"] = {"name": "L"}
    original["skuMap"][";COLOR-ID;L-ID;"] = {"itemNum": "SELL-B", "price": 20}
    item.erp_sku_links = {"SKU-A": ";COLOR-ID;SIZE-ID;", "SKU-B": ";COLOR-ID;L-ID;"}
    return item, original


# 2026-10-12：本次修改原因：有明确旧图时替换该图片，保留另一尺码及远端附图，且一次合并多个 SKU 改图。
@pytest.mark.parametrize("both", [False, True])
def test_update_replaces_identifiable_images_and_preserves_remote_extras(both):
    item, original = image_update_pair()
    item.erp_update_baseline = item.to_dict()
    item.skus[0].image = "https://example.com/new-M.jpg"
    item.manual_fields = ["sku:SKU-A:image"]
    if both:
        item.skus[1].image = "https://example.com/new-L.jpg"
        item.manual_fields.append("sku:SKU-B:image")
    preserved = deepcopy(original)
    local = item.to_dict()
    payload, links = update_payload(item, original, config())
    color = payload["colorMap"]["COLOR-ID"]
    assert color["imgUrl"] == item.skus[0].image
    assert color["imgUrls"] == [item.skus[0].image, item.skus[1].image, "https://example.com/remote-extra.jpg"]
    assert payload["colorMap"]["RED-ID"] == original["colorMap"]["RED-ID"]
    assert payload["skuMap"] == original["skuMap"] and links == item.erp_sku_links
    assert original == preserved and item.to_dict() == local


# 2026-10-12：本次修改原因：旧图片仍被另一 SKU 使用时必须保留；无法匹配的 ERP 托管旧图也不能误删。
@pytest.mark.parametrize("use_baseline", [False, True])
def test_update_keeps_unidentifiable_remote_images_and_uses_edited_image_as_primary(use_baseline):
    item, original = image_update_pair()
    if use_baseline:
        item.erp_update_baseline = item.to_dict()
    original["colorMap"]["COLOR-ID"]["imgUrl"] = "https://cdn.example.com/hosted-M.jpg"
    original["colorMap"]["COLOR-ID"]["imgUrls"][0] = "https://cdn.example.com/hosted-M.jpg"
    item.skus[0].image = "https://example.com/new-M.jpg"
    item.manual_fields = ["sku:SKU-A:image"]
    payload, _ = update_payload(item, original, config())
    color = payload["colorMap"]["COLOR-ID"]
    assert color["imgUrl"] == item.skus[0].image and color["imgUrls"][0] == item.skus[0].image
    assert set(original["colorMap"]["COLOR-ID"]["imgUrls"]) <= set(color["imgUrls"])
    assert item.skus[1].image in color["imgUrls"]


# 2026-10-12：本次修改原因：一张旧图被多个尺码共享时，修改其中一个不能删除另一个仍在使用的图片。
def test_update_keeps_old_image_still_used_by_another_sku():
    item, original = image_update_pair()
    item.skus[1].image = item.skus[0].image
    item.erp_update_baseline = item.to_dict()
    item.skus[0].image = "https://example.com/new-M.jpg"
    item.manual_fields = ["sku:SKU-A:image"]
    payload, _ = update_payload(item, original, config())
    gallery = payload["colorMap"]["COLOR-ID"]["imgUrls"]
    assert item.skus[1].image in gallery and item.skus[0].image in gallery
    assert "https://example.com/remote-extra.jpg" in gallery


# 2026-10-12：本次修改原因：只允许清空有可靠旧图对应的 SKU，不能用本机空值删除无法归属的远端附图。
@pytest.mark.parametrize("identifiable", [False, True])
def test_update_clear_image_requires_identifiable_old_picture(identifiable):
    item, original = image_update_pair()
    if identifiable:
        item.erp_update_baseline = item.to_dict()
    item.skus[0].image = ""
    item.manual_fields = ["sku:SKU-A:image"]
    if not identifiable:
        with pytest.raises(ValueError, match="无法可靠识别.*不能单独清空"):
            update_payload(item, original, config())
    else:
        payload, _ = update_payload(item, original, config())
        assert payload["colorMap"]["COLOR-ID"]["imgUrls"] == [item.skus[1].image, "https://example.com/remote-extra.jpg"]
        assert payload["colorMap"]["COLOR-ID"]["imgUrl"] == item.skus[1].image


# 2026-10-12：本次修改原因：合并图片仍需可靠规格关联且不能越过远端图片上限，失败时不得改动输入数据。
def test_update_rejects_stale_peer_mapping_and_image_overflow():
    item, original = image_update_pair()
    item.skus[0].image = "https://example.com/new-M.jpg"
    item.manual_fields = ["sku:SKU-A:image"]
    original["sizeMap"]["L-ID"]["name"] = "远端已改尺码"
    with pytest.raises(ValueError, match="重新核对关联"):
        update_payload(item, original, config())
    original["sizeMap"]["L-ID"]["name"] = "L"
    original["colorMap"]["COLOR-ID"]["imgUrls"] = [f"https://example.com/remote-{index}.jpg" for index in range(9)]
    preserved = deepcopy(original)
    with pytest.raises(ValueError, match="蓝色.*12 张不同图片.*10 张"):
        update_payload(item, original, config())
    assert original == preserved


# 2026-10-12：本次修改原因：仅修改标题时，本地不同尺码图片不得触发远端颜色图片组重建。
def test_update_without_image_edits_keeps_remote_color_groups_exactly():
    item, original = image_update_pair()
    item.manual_fields = ["title"]
    payload, _ = update_payload(item, original, config())
    assert payload["colorMap"] == original["colorMap"]


# 2026-10-12：本次修改原因：成功的第一张图在第二张容量不足时仍必须持久保存，重启重试只能补传未成功的图片。
def test_picture_cache_survives_partial_failure_and_adapter_restart(tmp_path):
    uploaded = []
    item = product()
    item.detail_images = ["https://example.com/detail.jpg"]
    def first_handler(request):
        assert request.url.path == PICTURE_PATH
        url = json.loads(request.content)["imgUrl"]
        uploaded.append(url)
        if url.endswith("detail.jpg"):
            return httpx.Response(200, json={"result": "fail", "code": "fail", "message": "图片空间容量不足", "data": None})
        return success({"picturePath": "https://cdn.example.com/main.jpg"})
    first = adapter(tmp_path, first_handler)
    assert not first.picture_cache.path.exists()
    with pytest.raises(ERPNotSentError, match="查看图片空间可用容量") as caught:
        first.send(ERPRequest("T1", "create", item, ""))
    assert first.picture_cache.path.exists()
    assert caught.value.details["failure_reason"] == "picture_space_capacity"
    assert caught.value.details["picture_progress"] == {"total": 2, "uploaded": 1, "cache_saved": 1,
        "cache_reused": 0, "remote_reused": 0, "failed_index": 2}
    assert first.picture_cache.get(config().account_id, item.images[0]) == "https://cdn.example.com/main.jpg"
    assert first.picture_cache.get(config().account_id, item.detail_images[0]) is None
    calls = []
    def second_handler(request):
        calls.append(request.url.path)
        if request.url.path == PICTURE_PATH:
            assert json.loads(request.content)["imgUrl"] == item.detail_images[0]
            return success({"picturePath": "https://cdn.example.com/detail.jpg"})
        assert request.url.path == CREATE_PATH
        body = json.loads(request.content)
        assert body["imgUrls"] == ["https://cdn.example.com/main.jpg"]
        assert "https://cdn.example.com/detail.jpg" in body["notes"]
        return success({"commonCollectBoxDetailId": 456})
    restarted = MiaoshouAdapter(MiaoshouConfigStore(tmp_path), httpx.MockTransport(second_handler))
    receipt = restarted.send(ERPRequest("T2", "create", item, ""))
    assert calls == [PICTURE_PATH, CREATE_PATH] and len(uploaded) == 2
    assert receipt.details["picture_progress"]["cache_reused"] == 1
    assert receipt.details["picture_progress"]["uploaded"] == 1


# 2026-10-14：本次修改原因：验证仅已应用到商品的本机主图、详情图和 SKU 图在同步时托管，候选图不上传且草稿不改写。
@pytest.mark.parametrize("mode", ["create", "update"])
def test_sync_hosts_only_submitted_local_images_and_keeps_draft(tmp_path, mode):
    from io import BytesIO
    from PIL import Image
    from beaddiff.assets import AssetStore

    assets = AssetStore(tmp_path)
    def picture(color):
        buffer = BytesIO()
        Image.new("RGB", (16, 16), color).save(buffer, format="PNG")
        return assets.save(buffer.getvalue()).uri

    # main, detail, sku, unused_candidate = (picture(color) for color in ("red", "green", "blue", "yellow"))
    # 2026-10-14：本次修改原因：新增和更新都验证尺码图托管及 payload 替换，未采用候选不上传。
    main, detail, sku, unused_candidate, size_chart = (picture(color) for color in ("red", "green", "blue", "yellow", "purple"))
    item = product()
    item.images = [main]
    item.detail_images = [detail]
    item.description_html = f"<p>详情</p><img src={detail}>"
    item.skus[0].image = sku
    # item.manual_fields = ["images", "description_html", "sku:SKU-A:image"]
    # 2026-10-14：本次修改原因：更新尺码图需显式记录对应修改字段。
    item.size_chart = size_chart
    item.manual_fields = ["images", "description_html", "sku:SKU-A:image", "size_chart"]
    item.erp_original_id = "123"
    item.erp_original_account = config().account_id
    item.erp_sku_links = {"SKU-A": ";COLOR-ID;SIZE-ID;"}
    before = item.to_dict()

    class RecordingHosting:
        def __init__(self):
            self.used = []

        def ensure_public(self, address):
            self.used.append(address)
            return "https://cdn.jsdelivr.net/gh/owner/images@main/" + address.rsplit("/", 1)[-1]

    hosting = RecordingHosting()
    sent = []
    def handler(request):
        if request.url.path == DETAIL_PATH:
            return success({"editCommonCollectBoxDetail": remote(), "ossMd5": "fresh-md5"})
        if request.url.path == PICTURE_PATH:
            sent.append(json.loads(request.content)["imgUrl"])
            return success({"picturePath": f"https://erp.example.com/image-{len(sent)}.png"})
        assert request.url.path in {CREATE_PATH, UPDATE_PATH}
        body = json.loads(request.content)
        payload = body if mode == "create" else body["editCommonCollectBoxDetail"]
        assert payload["itemNum"] == (item.main_code if mode == "create" else remote()["itemNum"])
        assert all(not url.startswith("file:") for url in payload["imgUrls"])
        assert "file:" not in payload["notes"]
        assert "file:" not in json.dumps(payload["colorMap"])
        # 2026-10-14：本次修改原因：尺码图与主图、详情图及 SKU 图均必须替换为转存成功的新链接。
        assert payload["sizeChart"] == f"https://erp.example.com/image-{len(sent)}.png"
        return success({"commonCollectBoxDetailId": 456} if mode == "create" else {"ossMd5": "saved-md5"})

    service = adapter(tmp_path, handler)
    service.hosting = hosting
    service.send(ERPRequest("T1", mode, item, "123" if mode == "update" else ""))
    # assert set(hosting.used) == {main, detail, sku}
    # 2026-10-14：本次修改原因：尺码图同样进入实际提交图片集合。
    assert set(hosting.used) == {main, detail, sku, size_chart}
    assert unused_candidate not in hosting.used
    # assert len(sent) == 3
    # 2026-10-14：本次修改原因：新增尺码图只增加一次托管与转存。
    assert len(sent) == 4
    assert item.to_dict() == before


# 2026-10-14：本次修改原因：图床失败必须在商品提交前中止，原商品主编号和本机图片维持原样。
def test_hosting_failure_prevents_erp_submission(tmp_path):
    from io import BytesIO
    from PIL import Image
    from beaddiff.assets import AssetStore

    buffer = BytesIO()
    Image.new("RGB", (16, 16), "white").save(buffer, format="PNG")
    item = product()
    item.images = [AssetStore(tmp_path).save(buffer.getvalue()).uri]
    before = item.to_dict()
    service = adapter(tmp_path, lambda _request: pytest.fail("图床失败后不应请求妙手"))
    class FailingHosting:
        def ensure_public(self, _address):
            raise ValueError("公网链接不可访问")
    service.hosting = FailingHosting()
    with pytest.raises(ERPNotSentError, match="图床托管图片失败"):
        service.send(ERPRequest("T1", "create", item, ""))
    assert item.to_dict() == before


# 2026-10-12：本次修改原因：相同图片只在同一 AppKey 下复用，跨商品复用但不能串用其他账号的图片空间地址。
def test_picture_cache_reuses_across_products_and_isolates_app_keys(tmp_path):
    calls = []
    def handler(request):
        calls.append(request.url.path)
        if request.url.path == PICTURE_PATH:
            account = "first" if request.headers["x-app-key"] == config().app_key else "second"
            return success({"picturePath": f"https://cdn.example.com/{account}.jpg"})
        assert request.url.path == CREATE_PATH
        return success({"commonCollectBoxDetailId": 123})
    service = adapter(tmp_path, handler)
    service.send(ERPRequest("T1", "create", product(), ""))
    another = product()
    another.title = "另一商品"
    receipt = service.send(ERPRequest("T2", "create", another, ""))
    assert receipt.details["picture_progress"]["cache_reused"] == 1
    assert calls == [PICTURE_PATH, CREATE_PATH, CREATE_PATH]
    other = MiaoshouConfig("other-app-key", "other-secret", cny_rates=config().cny_rates)
    service.store.save(other)
    service.send(ERPRequest("T3", "create", product(), ""))
    assert calls[-2:] == [PICTURE_PATH, CREATE_PATH]
    assert service.picture_cache.get(config().account_id, product().images[0]) == "https://cdn.example.com/first.jpg"
    assert service.picture_cache.get(other.account_id, product().images[0]) == "https://cdn.example.com/second.jpg"
    assert service.clear_picture_cache(other.account_id) == 1
    assert service.picture_cache.get(config().account_id, product().images[0]) == "https://cdn.example.com/first.jpg"
    assert service.picture_cache.get(other.account_id, product().images[0]) is None


# 2026-10-12：本次修改原因：缓存初始化及空清理不落盘，不缓存原图带参链接、凭证或无效地址。
def test_picture_cache_is_lazy_and_stores_hashed_source_urls(tmp_path):
    folder = tmp_path / "not-created"
    cache = MiaoshouPictureCache(folder)
    url = "https://example.com/image.jpg?token=image-link-token"
    assert cache.get(config().account_id, url) is None
    assert cache.clear(config().account_id) == 0 and not folder.exists()
    with pytest.raises(ValueError, match="未确认成功"):
        cache.put(config().account_id, url, "file:///C:/image.png")
    assert not folder.exists()
    cache.put(config().account_id, url, "https://cdn.example.com/image.jpg")
    assert cache.get(config().account_id, url) == "https://cdn.example.com/image.jpg"
    assert b"image-link-token" not in cache.path.read_bytes()
    assert config().app_key.encode() not in cache.path.read_bytes()
    assert config().app_secret.encode() not in cache.path.read_bytes()


# 2026-10-12：本次修改原因：网络诊断显示具体异常但不输出原始敏感文本；商品保存异常仍保持结果未知。
@pytest.mark.parametrize("error_type,label", [
    (httpx.ConnectTimeout, "连接妙手超时"),
    (httpx.ReadTimeout, "等待妙手响应超时"),
    (httpx.ProxyError, "代理连接失败"),
    (httpx.ConnectError, "连接建立失败"),
])
def test_network_error_classification_is_safe_and_preserves_save_uncertainty(error_type, label):
    def handler(request):
        raise error_type("proxy-credential " + config().app_secret, request=request)
    client = MiaoshouClient(config(), httpx.MockTransport(handler))
    for path, exception, saving in ((PICTURE_PATH, ERPNotSentError, False), (CREATE_PATH, ERPUncertainError, True)):
        with pytest.raises(exception) as caught:
            client.call(path, {"title": "商品"}, saving_product=saving)
        assert label in str(caught.value)
        assert caught.value.details["network_error"]["type"] == error_type.__name__
        assert caught.value.details["network_error"]["timeout_seconds"] == 30
        assert config().app_secret not in str(caught.value) and "proxy-credential" not in str(caught.value)
        assert config().app_secret not in json.dumps(caught.value.details)


# 2026-10-12：本次修改原因：超时或缺少有效 picturePath 都不能缓存，后续明确重试要再次申请图片转存。
@pytest.mark.parametrize("timeout", [True, False])
def test_unconfirmed_picture_upload_is_not_cached_and_product_is_not_submitted(tmp_path, timeout):
    calls = []
    def handler(request):
        assert request.url.path == PICTURE_PATH
        calls.append(request.url.path)
        if timeout:
            raise httpx.ReadTimeout("timeout", request=request)
        return success({"picturePath": ""})
    service = adapter(tmp_path, handler)
    for index in range(2):
        with pytest.raises(ERPNotSentError) as caught:
            service.send(ERPRequest(f"T{index}", "create", product(), ""))
        assert caught.value.details["picture_progress"]["uploaded"] == 0
    assert len(calls) == 2 and not service.picture_cache.path.exists()


# 2026-10-12：本次修改原因：缓存保存失败后必须提示已经有一张图转存，不能误报商品已提交或整批缓存成功。
def test_picture_cache_write_failure_stops_product_submission(tmp_path, monkeypatch):
    def handler(request):
        assert request.url.path == PICTURE_PATH
        return success({"picturePath": "https://cdn.example.com/main.jpg"})
    service = adapter(tmp_path, handler)
    def deny_save(*args):
        raise PermissionError("模拟缓存无写入权限")
    monkeypatch.setattr(service.picture_cache, "put", deny_save)
    with pytest.raises(ERPNotSentError, match="已成功上传图片，但缓存保存失败") as caught:
        service.send(ERPRequest("T1", "create", product(), ""))
    assert caught.value.details["picture_progress"]["uploaded"] == 1
    assert caught.value.details["picture_progress"]["cache_saved"] == 0
    assert not service.picture_cache.path.exists()


# 2026-10-14：本次修改原因：图床缓存读写故障在商品提交前终止，报告真实故障位置且不暴露底层异常。
@pytest.mark.parametrize('phase', ['read', 'write'])
def test_image_host_cache_error_stops_before_erp_and_keeps_product(tmp_path, monkeypatch, phase):
    import sqlite3
    from io import BytesIO
    from PIL import Image
    from beaddiff.assets import AssetStore
    from beaddiff.image_hosting import ImageHostingConfig, ImageHostingStore, GitHubImageHosting
    assets = AssetStore(tmp_path)
    raw = BytesIO()
    Image.new('RGB', (32, 32), 'white').save(raw, format='PNG')
    image = assets.save(raw.getvalue())
    item = product()
    item.images = [image.uri]
    before = item.to_dict()
    store = ImageHostingStore(tmp_path)
    store.save(ImageHostingConfig(enabled=True, owner='owner', repository='images', token='fake-token'))
    if phase == 'read':
        store.cache_path.write_bytes(b'not a sqlite database')
    else:
        def broken_write(*_args, **_kwargs):
            raise sqlite3.OperationalError('secret-token in raw exception')
        monkeypatch.setattr(store, 'cache_put', broken_write)
    service = adapter(tmp_path, lambda _request: pytest.fail('Cache failure must prevent any ERP request'))
    service.hosting = GitHubImageHosting(store, assets)
    with pytest.raises(ERPNotSentError) as caught:
        service.send(ERPRequest('T-cache', 'create', item, ''))
    message = str(caught.value)
    assert '图床' in message and '缓存' in message and '商品尚未提交' in message
    assert 'secret-token' not in message and '妙手缓存' not in message
    assert item.to_dict() == before
