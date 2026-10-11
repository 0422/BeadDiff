# 2026-10-11：本次修改原因：覆盖修改状态、开关持久化、回传快照并发、成功回执与未知结果保护；测试不连接真实妙手。
import json

import pytest

from beaddiff.config import Settings
from beaddiff.erp import ERPReceipt, ERPRejectedError, ERPService
from beaddiff.models import Product, SKU
from beaddiff.storage import Repository


def stored_product(repository, source_id="ITEM-1"):
    product, _ = repository.store_parsed(Product(
        source="temu", source_id=source_id, title="原始商品", currency="USD",
        images=["https://example.com/main.jpg"],
        skus=[SKU(source_sku_id="SOURCE-SKU", platform_sku="SELLER-SKU", price="20.00")],
    ))
    return product


class TestAdapter:
    __test__ = False
    unavailable_reason = ""

    def __init__(self, outcome=None):
        self.requests = []
        self.outcome = outcome

    def validate(self, product, mode):
        return []

    def send(self, request):
        self.requests.append(request)
        if self.outcome:
            return self.outcome(request)
        return ERPReceipt(request.mode, request.original_id or "ERP-NEW-1", "RECEIPT-1")


def test_settings_default_switch_and_other_values_survive(tmp_path, monkeypatch):
    monkeypatch.setenv("BEADDIFF_DATA_DIR", str(tmp_path))
    settings = Settings.load()
    assert settings.erp_transfer_mode == "create"
    content = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    content["custom_setting"] = "preserve"
    (tmp_path / "settings.json").write_text(json.dumps(content), encoding="utf-8")
    settings.erp_transfer_mode = "update"
    settings.save()
    assert Settings.load().erp_transfer_mode == "update"
    assert json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))["custom_setting"] == "preserve"
    settings.port = 19876
    settings.save()
    assert Settings.load().erp_transfer_mode == "update"


def test_approval_preview_cache_and_source_refresh_are_not_manual_edits(tmp_path):
    repository = Repository(tmp_path)
    product = stored_product(repository)
    product.image_sizes[product.images[0]] = "800 × 800"
    product.warnings = ["预览提示"]
    product.skus[0].source_price = "$5.00"
    saved = repository.save_product(product, approve=True)
    assert saved.modification_status == "未修改"
    refreshed = Product.from_dict(saved.to_dict())
    refreshed.detail_images = ["https://example.com/detail.jpg"]
    repository.backfill_parsed("CAPTURE", refreshed)
    assert repository.product(product.id).modification_status == "未修改"


def test_manual_or_ai_applied_content_only_counts_after_save(tmp_path):
    repository = Repository(tmp_path)
    product = stored_product(repository)
    product.title = "AI 候选应用后的标题"
    assert repository.product(product.id).modification_status == "未修改"
    saved = repository.save_product(product)
    assert saved.modification_status == "已修改" and saved.modified_at
    saved.simple_description = "人工修改的描述"
    repository.save_product(saved)
    assert repository.product(product.id).modification_status == "已修改"


def test_default_adapter_records_unavailable_without_false_success(tmp_path):
    repository = Repository(tmp_path)
    product = repository.save_product(stored_product(repository), approve=True)
    result = ERPService(repository).transfer([product.id], "create")
    assert result[0]["state"] == "blocked"
    # assert "尚未接通" in result[0]["message"]
    # 2026-10-11：本次修改原因：默认适配器已接入真实 API，但未填写本地凭证仍须阻止发送。
    assert "AppKey" in result[0]["message"]
    record = repository.erp_transfers()[0]
    assert record["mode"] == "create" and record["state"] == "blocked"
    assert json.loads(record["snapshot"])["revision"] == product.revision
    assert repository.product(product.id).erp_status == "未传"


def test_success_remains_valid_on_review_but_edit_invalidates_content(tmp_path):
    repository = Repository(tmp_path)
    product = repository.save_product(stored_product(repository), approve=True)
    adapter = TestAdapter()
    assert ERPService(repository, adapter).transfer([product.id], "create")[0]["state"] == "succeeded"
    saved = repository.product(product.id)
    assert saved.erp_status == "已传" and saved.erp_target_id == "ERP-NEW-1"
    assert not saved.erp_original_id  # 新增目标不能代替原采集商品。
    saved = repository.save_product(saved, approve=True)
    assert saved.erp_status == "已传" and saved.modification_status == "未修改"
    saved.images.append("https://example.com/second.jpg")
    saved = repository.save_product(saved)
    assert saved.erp_status == "未传" and saved.modification_status == "已修改"


def test_edit_while_transmitting_does_not_mark_new_content_transmitted(tmp_path):
    repository = Repository(tmp_path)
    product = repository.save_product(stored_product(repository), approve=True)

    def concurrent_edit(request):
        current = repository.product(product.id)
        current.title = "发送期间保存的新标题"
        repository.save_product(current)
        return ERPReceipt("create", "ERP-1", "ACK-1")

    adapter = TestAdapter(concurrent_edit)
    assert ERPService(repository, adapter).transfer([product.id], "create")[0]["state"] == "succeeded"
    saved = repository.product(product.id)
    assert saved.erp_status == "未传"
    assert saved.title == "发送期间保存的新标题"
    assert adapter.requests[0].product.title == "原始商品"


def test_editor_open_before_receipt_preserves_receipt_on_save(tmp_path):
    repository = Repository(tmp_path)
    product = repository.save_product(stored_product(repository), approve=True)
    old_editor = repository.product(product.id)
    ERPService(repository, TestAdapter()).transfer([product.id], "create")
    saved = repository.save_product(old_editor, approve=True)
    assert saved.erp_status == "已传" and saved.erp_transfer_id


def test_update_requires_original_id_and_passes_frozen_mode(tmp_path):
    repository = Repository(tmp_path)
    product = repository.save_product(stored_product(repository), approve=True)
    adapter = TestAdapter()
    service = ERPService(repository, adapter)
    assert service.transfer([product.id], "update")[0]["state"] == "blocked"
    assert not adapter.requests
    # 模拟经已验证接口关联的妙手原商品 ID，不用来源 ID 推断。
    product.erp_original_id = "ERP-ORIGINAL"
    with repository.connection() as connection:
        connection.execute("UPDATE products SET body=? WHERE id=?", (json.dumps(product.to_dict()), product.id))
    assert service.transfer([product.id], "update")[0]["state"] == "succeeded"
    assert adapter.requests[0].mode == "update" and adapter.requests[0].original_id == "ERP-ORIGINAL"
    assert repository.product(product.id).erp_target_id == "ERP-ORIGINAL"


@pytest.mark.parametrize("invalid_receipt", [None, ERPReceipt("update", "ERP-1", "ACK"), ERPReceipt("create", "", "ACK")])
def test_unknown_results_block_retries_without_calling_adapter_again(tmp_path, invalid_receipt):
    repository = Repository(tmp_path)
    product = repository.save_product(stored_product(repository), approve=True)
    adapter = TestAdapter(lambda request: invalid_receipt)
    service = ERPService(repository, adapter)
    assert service.transfer([product.id], "create")[0]["state"] == "unknown"
    assert repository.product(product.id).erp_status == "未传"
    assert service.transfer([product.id], "create")[0]["state"] == "blocked"
    assert len(adapter.requests) == 1


def test_confirmed_rejection_is_not_success(tmp_path):
    repository = Repository(tmp_path)
    product = repository.save_product(stored_product(repository), approve=True)

    def rejected(request):
        raise ERPRejectedError("妙手明确拒绝保存")

    results = ERPService(repository, TestAdapter(rejected)).transfer([product.id], "create")
    assert results[0]["state"] == "failed"
    assert repository.erp_transfers()[0]["state"] == "failed"
    assert repository.product(product.id).erp_status == "未传"


def test_old_revision_alone_does_not_mark_modified():
    assert Product.from_dict({"revision": 7}).modification_status == "未修改"
    assert Product.from_dict({"revision": 7, "manual_fields": ["title"]}).modification_status == "已修改"


# 2026-10-11：本次修改原因：进程中断后的发送记录不能自动重试新增，必须保留结果未知状态。
def test_restart_keeps_interrupted_transfer_unknown(tmp_path):
    repository = Repository(tmp_path)
    product = repository.save_product(stored_product(repository), approve=True)
    repository.create_erp_transfer(product.id, "create", "sending")
    restarted = Repository(tmp_path)
    assert restarted.erp_transfers()[0]["state"] == "unknown"
    adapter = TestAdapter()
    result = ERPService(restarted, adapter).transfer([product.id], "create")
    assert result[0]["state"] == "blocked" and not adapter.requests
