# 2026-10-12：本次修改原因：离线覆盖列表清理/恢复、原始材料去重、未核对回传保护及成功状态留存；由用户自行运行。
from pathlib import Path

from beaddiff.models import Product
from beaddiff.storage import Repository


def test_product_removal_is_recoverable_and_keeps_dedup(tmp_path):
    repository = Repository(tmp_path)
    item, _ = repository.store_parsed(Product(source="temu", source_id="123", title="原商品"))
    result = repository.hide_local_items("products", [item.id, item.id])
    assert result == {"hidden": 1, "blocked": 0}
    assert not repository.products() and repository.product(item.id).title == "原商品"
    repeated, created = repository.store_parsed(Product(source="temu", source_id="123", title="不能覆盖"))
    assert not created and repeated.id == item.id
    assert Repository(tmp_path).restore_local_items("products") == 1
    assert repository.products()[0].title == "原商品"


def test_unknown_or_sending_records_and_their_product_cannot_be_hidden(tmp_path):
    repository = Repository(tmp_path)
    item, _ = repository.store_parsed(Product(source="temu", source_id="123"))
    transfer = repository.create_erp_transfer(item.id, "create", "sending")
    assert repository.hide_local_items("products", [item.id])["blocked"] == 1
    assert repository.hide_local_items("transfers", [transfer["id"]])["blocked"] == 1
    repository.finish_erp_transfer(transfer["id"], "unknown", "超时，待核对")
    assert repository.hide_local_items("transfers", [transfer["id"]])["blocked"] == 1
    assert repository.hide_local_items("products", [item.id])["blocked"] == 1
    assert not repository.hidden_local_ids("transfers")


def test_clear_resolved_history_preserves_success_receipt_and_product_status(tmp_path):
    repository = Repository(tmp_path)
    item, _ = repository.store_parsed(Product(source="temu", source_id="123"))
    transfer = repository.create_erp_transfer(item.id, "create", "sending")
    repository.finish_erp_transfer(transfer["id"], "succeeded", "完成", "456", {"account_id": "test"})
    assert repository.hide_local_items("transfers", [transfer["id"]])["hidden"] == 1
    assert repository.erp_transfers()[0]["state"] == "succeeded"
    assert repository.product(item.id).erp_status == "已传"
    assert Repository(tmp_path).restore_local_items("transfers") == 1


def test_capture_cleanup_keeps_raw_file_and_event_identity(tmp_path):
    repository = Repository(tmp_path)
    envelope = {"eventId": "same-event", "payload": {"source": "temu", "itemId": "123"}}
    capture_id, _ = repository.create_capture(envelope)
    assert repository.hide_local_items("captures", [capture_id])["blocked"] == 1
    repository.finish_capture(capture_id, "解析失败", "留存原文")
    assert repository.hide_local_items("captures", [capture_id])["hidden"] == 1
    assert not repository.captures()
    assert Path(repository.capture(capture_id)["raw_path"]).is_file()
    assert repository.create_capture(envelope) == (capture_id, False)
    assert Repository(tmp_path).restore_local_items("captures") == 1


# 2026-10-13：本次修改原因：回收站选择恢复不应恢复其他未勾选商品。
def test_recycle_bin_restores_only_selected_products(tmp_path):
    repository = Repository(tmp_path)
    first, _ = repository.store_parsed(Product(source="temu", source_id="1", title="选择恢复"))
    second, _ = repository.store_parsed(Product(source="temu", source_id="2", title="继续留存"))
    repository.hide_local_items("products", [first.id, second.id])
    assert {row["id"] for row in repository.recycle_items("products")} == {first.id, second.id}
    assert repository.restore_local_items("products", [first.id]) == 1
    assert [row.id for row in repository.products()] == [first.id]
    assert [row["id"] for row in Repository(tmp_path).recycle_items("products")] == [second.id]


# 2026-10-13：本次修改原因：永久删除 API 商品解除身份去重并删除版本，独立同步记录保留。
def test_purge_product_releases_erp_identity_and_removes_versions(tmp_path):
    repository = Repository(tmp_path)
    def imported():
        return Product(erp_imported=True, erp_original_account="account", erp_original_id="123", title="妙手商品")
    first, _ = repository.store_miaoshou_import(imported())
    repository.record_miaoshou_import("batch", "account", {"target_id": "123", "product_id": first.id,
        "state": "imported", "title": first.title}, {"original": True})
    assert repository.purge_local_items("products", [first.id]) == {"deleted": 0, "blocked": 0}
    repository.hide_local_items("products", [first.id])
    assert repository.purge_local_items("products", [first.id]) == {"deleted": 1, "blocked": 0}
    assert repository.product(first.id) is None and not repository.miaoshou_import_index("account")
    assert repository.miaoshou_import_records()[0]["product_id"] == ""
    with repository.connection() as connection:
        assert not connection.execute("SELECT 1 FROM product_versions WHERE product_id=?", (first.id,)).fetchone()
    again, created = repository.store_miaoshou_import(imported())
    assert created and again.id != first.id


# 2026-10-13：本次修改原因：永久删除重新核查当前发送状态，隐藏后变成待核对也不能删除。
def test_purge_rechecks_unresolved_transfer_before_deleting_archived_product(tmp_path):
    repository = Repository(tmp_path)
    item, _ = repository.store_parsed(Product(source="temu", source_id="123"))
    repository.hide_local_items("products", [item.id])
    transfer = repository.create_erp_transfer(item.id, "create", "sending")
    repository.finish_erp_transfer(transfer["id"], "unknown", "待核对")
    assert repository.purge_local_items("products", [item.id]) == {"deleted": 0, "blocked": 1}
    assert repository.product(item.id) and repository.recycle_items("products")


# 2026-10-13：本次修改原因：删除同步任务不删除商品，且旧版快照回退条目不得重新出现。
def test_purge_import_record_keeps_product_identity_and_suppresses_legacy_fallback(tmp_path):
    repository = Repository(tmp_path)
    item, _ = repository.store_miaoshou_import(Product(erp_imported=True, erp_original_account="account", erp_original_id="123"))
    repository.record_miaoshou_import("batch", "account", {"target_id": "123", "product_id": item.id, "state": "imported"}, {})
    record = repository.miaoshou_import_records()[0]
    repository.hide_local_items("imports", [record["id"]])
    assert repository.purge_local_items("imports", [record["id"]])["deleted"] == 1
    assert not repository.recycle_items("imports") and not repository.miaoshou_import_records(include_hidden=True)
    assert "legacy:" + item.id in repository.hidden_local_ids("purged-import")
    assert repository.miaoshou_import_index("account")["123"]["product_id"] == item.id
