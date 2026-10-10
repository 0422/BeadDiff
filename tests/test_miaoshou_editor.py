# 2026-10-11：本次修改原因：覆盖八栏目编辑、图片分组双向保存和新建 SKU，不访问真实采集数据。
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtNetwork import QNetworkAccessManager
from PySide6.QtWidgets import QApplication

from beaddiff.models import Product, SKU
from beaddiff.ui.editor import ProductEditor


@pytest.fixture
def editor():
    app = QApplication.instance() or QApplication([])
    network = QNetworkAccessManager(app)
    product = Product(main_code="TEST", title="编辑测试", currency="USD", spec1_name="颜色", spec2_name="尺码",
                      attributes={"材料": "硅藻泥"},
                      simple_description="材料:硅藻泥",
                      description_html="<p>手工详情</p>",
                      skus=[SKU(source_sku_id="ONE", spec1="黑", spec2="小"),
                            SKU(source_sku_id="TWO", spec1="黑", spec2="大")])
    dialog = ProductEditor(None, product, network)
    yield dialog
    dialog.dirty = False
    dialog.close()
    dialog.deleteLater()
    app.sendPostedEvents()


def test_editor_uses_eight_miaoshou_sections_and_roundtrips(editor):
    assert [editor.tabs.tabText(index).split("（")[0] for index in range(editor.tabs.count())] == [
        "基本信息", "产品属性", "销售属性", "产品图片", "产品视频", "认证说明", "物流信息", "货源链接"]
    saved = editor.collect()
    assert saved.attributes == {"材料": "硅藻泥"}
    assert saved.simple_description == "材料:硅藻泥"
    assert saved.description_html == "<p>手工详情</p>"
    assert saved.skus[0].source_sku_id == "ONE" and not saved.skus[0].platform_sku


def test_group_image_edit_updates_sku_and_collect(editor):
    # 编辑非选中的 SKU；隐藏图片页不发起远程预览。
    editor.sku_group_table.item(1, 1).setText("https://example.com/large.jpg")
    assert editor.sku_table.item(1, 8).text() == "https://example.com/large.jpg"
    assert editor.collect().skus[1].image == "https://example.com/large.jpg"
    assert editor.sku_groups == {"黑": ["https://example.com/large.jpg"]}


def test_add_and_remove_sku_updates_count_without_incomplete_row_access(editor):
    editor.add_sku()
    assert editor.sku_table.rowCount() == 3
    assert len(editor.collect().skus) == 3
    editor.sku_table.clearSelection()
    editor.sku_table.selectRow(2)
    editor.remove_sku()
    assert editor.sku_table.rowCount() == 2
    assert "2" in editor.tabs.tabText(editor.sku_tab_index)


def test_new_attachments_and_shipping_fields_are_saved(editor):
    values = {"instruction_manual": "https://example.com/manual.pdf", "package_weight": "0.35",
              "package_dimensions": "30*20*3", "source_remark": "采购备注"}
    for name, value in values.items():
        editor.fields[name].setText(value)
    editor.attribute_table.item(0, 1).setText("天然石")
    editor.describe_attributes()
    saved = editor.collect()
    assert saved.attributes == {"材料": "天然石"} and saved.simple_description == "材料:天然石"
    assert all(getattr(saved, name) == value for name, value in values.items())
