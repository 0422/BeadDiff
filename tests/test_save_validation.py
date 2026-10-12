# 2026-10-12：本次修改原因：覆盖“原来已超限、只改货源价仍能保存”的回归及保存失败不落库，测试由用户自行运行。
from copy import deepcopy

import pytest

from beaddiff.miaoshou_mapping import draft_limit_issues
from beaddiff.models import Product, SKU
from beaddiff.storage import Repository


def product():
    return Product(source="temu", source_id="SAVE-LIMIT", site="US", title="保存限制样本", currency="CNY",
                   supply_price="8", images=["https://example.com/main.jpg"],
                   skus=[SKU(source_sku_id="A", spec1="白", price="20", currency="CNY")])


# 2026-10-12：本次修改原因：旧数据 16 张主图不需要重新编辑图片，保存与审核都应拦住且保持旧数据和版本。
@pytest.mark.parametrize("approve", [False, True])
def test_unchanged_oversized_gallery_cannot_save_even_when_other_field_changes(tmp_path, approve):
    repository = Repository(tmp_path)
    material = product()
    material.images = [f"https://example.com/{index}.jpg" for index in range(16)]
    material.approved = True
    stored, _ = repository.store_parsed(material)
    before = deepcopy(stored.to_dict())
    assert stored.status == "待完善"
    stored.supply_price = "200"
    with pytest.raises(ValueError, match="16 张.*15 张.*超出 1 张"):
        repository.save_product(stored, approve=approve)
    assert repository.product(stored.id).to_dict() == before
    stored.images.pop()
    saved = repository.save_product(stored, approve=True)
    assert len(saved.images) == 15 and saved.status == "已审核"
    assert saved.revision == before["revision"] + 1


# 2026-10-12：本次修改原因：一次提示全部已填字段的问题，不让数量错误掩盖长文本、库存及规格格式问题。
def test_save_reports_all_known_constraint_errors_without_writing_any_changes(tmp_path):
    repository = Repository(tmp_path)
    item, _ = repository.store_parsed(product())
    before = deepcopy(item.to_dict())
    item.title = "字" * 256
    item.source_remark = "字" * 256
    item.video = "javascript:invalid"
    item.images = [f"https://example.com/{index}.jpg" for index in range(16)]
    item.skus[0].spec1 = "白;黑"
    item.skus[0].stock = "100000"
    item.skus[0].weight = "-1"
    item.skus[0].dimensions = "1*2"
    with pytest.raises(ValueError) as captured:
        repository.save_product(item)
    text = str(captured.value)
    assert all(value in text for value in ("产品标题", "货源备注", "视频", "16 张", "分号", "库存", "重量", "尺寸"))
    assert repository.product(item.id).to_dict() == before


# 2026-10-12：本次修改原因：规格图片组按完整当前商品检查，未变化的 11 张也不能被其他字段保存绕过。
def test_unchanged_spec_gallery_is_checked_for_all_skus():
    original = product()
    original.skus = [SKU(source_sku_id=str(index), spec1="白", spec2=str(index),
                         price="20", currency="CNY", image=f"https://example.com/spec{index}.jpg") for index in range(11)]
    edited = deepcopy(original)
    edited.title = "只改标题"
    assert any("白" in issue and "11" in issue and "10" in issue for issue in draft_limit_issues(edited, original))


# 2026-10-12：本次修改原因：草稿仍允许未填写的业务必填项，已填写的非法值必须当场拒绝。
def test_partial_draft_can_save_but_invalid_filled_values_cannot(tmp_path):
    repository = Repository(tmp_path)
    material = product()
    material.title, material.images, material.skus[0].price = "", [], ""
    item, _ = repository.store_parsed(material)
    item.simple_description = "等待补全的草稿"
    saved = repository.save_product(item)
    assert saved.simple_description == item.simple_description and saved.status == "待完善"
    saved.skus[0].price = "NaN"
    with pytest.raises(ValueError, match="售价"):
        repository.save_product(saved)
