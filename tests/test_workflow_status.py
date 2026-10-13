# 2026-10-12：本次修改原因：覆盖当前内容回传状态、账号隔离和前置检查留档，不调用真实 ERP。
from beaddiff.config import Settings
from beaddiff.erp import ERPService
from beaddiff.models import Product, SKU
from beaddiff.storage import Repository
from beaddiff.workflow import transfer_status


def test_success_requires_same_account_and_same_content():
    product = Product(id="p", title="原标题", erp_account_id="account-a")
    product.erp_content_hash = product.content_hash
    assert transfer_status(product, "account-a", []) == "已传"
    product.revision += 1
    assert transfer_status(product, "account-a", []) == "已传"
    product.title = "加工标题"
    assert transfer_status(product, "account-a", []) == "需重传"
    assert transfer_status(product, "account-b", []) == "未传"


def test_unknown_result_remains_pending_after_edit_and_ignores_other_account():
    product = Product(id="p", title="原标题")
    record = {"product_id": "p", "content_hash": product.content_hash, "state": "unknown",
              "receipt": '{"account_id":"account-a"}'}
    product.title = "之后加工的标题"
    assert transfer_status(product, "account-a", [record]) == "待核对"
    assert transfer_status(product, "account-b", [record]) == "未传"


def test_preflight_records_do_not_send_or_clear_unknown(tmp_path):
    repository = Repository(tmp_path)
    product = repository.create_product(Product(source="upload", title="草稿", currency="CNY",
        images=["https://example.com/main.jpg"], skus=[SKU()]))
    service = ERPService(repository)
    assert service.record_preflight([(product.id, ["请先审核"])], "create", "account-a") == []
    records = repository.erp_transfers(product.id)
    assert records[0]["state"] == "blocked" and "请先审核" in records[0]["message"]
    record = repository.create_erp_transfer(product.id, "create", "sending")
    repository.finish_erp_transfer(record["id"], "unknown", "超时")
    assert service.record_preflight([(product.id, ["先核对"])], "create", "account-a") == []
    assert len(repository.erp_transfers(product.id)) == 2
    assert repository.erp_transfers(product.id)[0]["state"] == "unknown"


def test_route_settings_keep_other_configuration_and_default_to_api(tmp_path, monkeypatch):
    monkeypatch.setenv("BEADDIFF_DATA_DIR", str(tmp_path))
    settings = Settings.load()
    assert settings.capture_route == "miaoshou"
    settings.capture_route, settings.erp_transfer_mode, settings.port = "plugin", "update", 19876
    settings.save()
    restored = Settings.load()
    assert (restored.capture_route, restored.erp_transfer_mode, restored.port) == ("plugin", "update", 19876)
