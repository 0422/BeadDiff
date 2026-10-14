# 2026-10-13：本次修改原因：验证统一 AI 工作流的原子应用、候选保留、方案复用和退出保护；仅使用临时数据与模拟模型。
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from copy import deepcopy
from dataclasses import asdict
import json
from types import SimpleNamespace

import pytest
# from PySide6.QtCore import Qt, QSettings
# 2026-10-13：本次修改原因：离屏测试明确清理 Qt 延迟销毁事件，避免跨用例残留窗口。
from PySide6.QtCore import Qt, QSettings, QEvent
# from PySide6.QtNetwork import QNetworkAccessManager
# 2026-10-13：本次修改原因：离屏平台不枚举系统字体时显式加载中文字体，仅改善测试截图。
from PySide6.QtGui import QFontDatabase
from PySide6.QtNetwork import QNetworkAccessManager
from PySide6.QtWidgets import QApplication, QMessageBox

from beaddiff.ai.config import ModelConfigStore, ModelProfile
from beaddiff.ai.contracts import AIResult
from beaddiff.ai.jobs import JobStore
from beaddiff.ai.references import ReferenceStore
from beaddiff.ai.service import AIService
from beaddiff.ai.workflow import apply_changes, run_workflow, sku_locator
from beaddiff.assets import AssetStore
from beaddiff.content import description_images
from beaddiff.models import Product, SKU
from beaddiff.ui.ai_workbench import AIWorkbench
from beaddiff.ui.editor import ProductEditor
from beaddiff.ui.reference_analysis import ReferenceAnalysisPage, PackageTrackingPage
from beaddiff.ui.widgets import ImagePreview

URL = "https://example.com/"
def product():
    return Product(id="product-one", title="原始标题", main_code="DEMO",
                   description_html=f"<p>原始详情</p><img src={URL}old.jpg>",
                   images=[URL + "main.jpg"], detail_images=[URL + "old.jpg"],
                   skus=[SKU(source_sku_id="red", spec1="红色", image=URL + "red.jpg"),
                         SKU(source_sku_id="blue", spec1="蓝色")]).to_dict()

def text_change(p, field="title", value="新标题"):
    return {"target": {"field": field, "before": p.get(field, ""), "product_id": p["id"]}, "value": value}

def image_change(p, field="detail_images", mode="replace"):
    return {"target": {"field": field, "before": p[field], "mode": mode,
            "anchor": p[field][0] if p[field] else "", "html_before": p["description_html"], "product_id": p["id"]},
            "value": [URL + "new.jpg"],
            "assets": [{"uri": URL + "new.jpg", "width": 1024, "height": 768}]}

def test_apply_is_atomic_and_detects_stale_html():
    p = product()
    changes = [text_change(p), image_change(p)]
    p["description_html"] = "<p>生成后手动编辑</p>"
    before = deepcopy(p)
    with pytest.raises(ValueError, match="详情正文"):
        apply_changes(p, changes)
    assert p == before

def test_combined_text_and_image_application_is_order_independent():
    p = product()
    text = text_change(p, "description_html", "<p>新详情</p>")
    text["target"]["keep_images"] = True
    image = image_change(p)
    a = apply_changes(p, [text, image])
    b = apply_changes(p, [image, text])
    assert a == b
    assert description_images(a["description_html"]) == [URL + "new.jpg"]
    assert a["image_sizes"][URL + "new.jpg"] == "1024 × 768"
    assert p["title"] == "原始标题" and URL + "old.jpg" in p["description_html"]

def test_replace_set_removes_html_only_images_and_keeps_text():
    p = product()
    p["description_html"] += f"<img src='{URL}html-only.jpg'>"
    result = apply_changes(p, [image_change(p, mode="replace_set")])
    assert description_images(result["description_html"]) == [URL + "new.jpg"]
    assert "原始详情" in result["description_html"]

def test_sku_uses_identity_after_rows_are_reordered():
    p = product()
    sku = deepcopy(p["skus"][0])
    change = {"target": {"field": "sku", "locator": sku_locator(sku), "before": sku}, "value": [URL + "red-new.jpg"]}
    p["skus"].reverse()
    result = apply_changes(p, [change])
    assert result["skus"][1]["image"] == URL + "red-new.jpg"
    assert result["skus"][0]["image"] == ""

def test_apply_checks_product_and_final_image_limit():
    p = product()
    change = text_change(p)
    change["target"]["product_id"] = "other-product"
    with pytest.raises(ValueError, match="其他商品"):
        apply_changes(p, [change])
    p["images"] = [URL + f"{index}.jpg" for index in range(15)]
    with pytest.raises(ValueError, match="16 张"):
        apply_changes(p, [image_change(p, "images", "append")])

def test_reference_roundtrip_and_corruption_does_not_overwrite(tmp_path):
    store = ReferenceStore(tmp_path)
    first = store.save({"name": "柔光", "prompt": "保留主体，柔光背景", "images": []})
    second = store.save({"name": "简洁", "prompt": "简洁排布"})
    assert len(store.list()) == 2
    store.delete(first["id"])
    assert store.list()[0]["id"] == second["id"]
    store.path.write_text('{"version":1,"items":[{"id":"bad","name":"bad","prompt":"x","images":[null]}]}', encoding="utf-8")
    before = store.path.read_bytes()
    with pytest.raises(ValueError):
        store.save({"name": "不能覆盖", "prompt": "草稿"})
    assert store.path.read_bytes() == before

def test_failed_redo_keeps_candidate_and_its_actual_prompt(tmp_path):
    old = {"id": "image-one", "caption": "主图", "request": {"operation": "image", "product": product(), "instruction": "旧要求"},
           "target": image_change(product())["target"], "error": "",
           "result": {"assets": [{"uri": URL + "generated.jpg", "width": 20, "height": 20}], "candidates": []}}
    task = deepcopy(old)
    task["request"]["instruction"] = "新要求"
    def fail(*args):
        raise ValueError("模拟失败 secret-token")
    service = SimpleNamespace(config=SimpleNamespace(profiles=[SimpleNamespace(key="secret-token")]),
                              jobs=JobStore(tmp_path), generate=fail)
    result = run_workflow(service, [task], "product-one", lambda message: None, [old])
    entry = result["result"]["entries"][0]
    assert entry["result"] == old["result"]
    assert entry["request"]["instruction"] == "旧要求"
    assert entry["retry_request"]["instruction"] == "新要求"
    assert "secret-token" not in json.dumps(result)
    assert result["state"] == "partial"

def test_workflow_preserves_success_when_another_task_fails(tmp_path):
    tasks = [{"id": field, "caption": field, "target": {"field": field},
              "request": {"operation": field, "product": product()}} for field in ["title", "simple_description"]]
    def generate(request, report):
        if request.operation == "simple_description":
            raise ValueError("模拟失败")
        return AIResult("job", "title", candidates=["成功标题"])
    service = SimpleNamespace(config=SimpleNamespace(profiles=[]), jobs=JobStore(tmp_path), generate=generate)
    result = run_workflow(service, tasks, "product-one", lambda message: None)
    assert result["result"]["entries"][0]["result"]["candidates"] == ["成功标题"]
    assert result["result"]["entries"][1]["result"] is None
    assert service.jobs.list("product-one", "product_workflow")

class DeferredHub:
    def submit(self, work, done, failed, progress=None):
        self.work, self.done, self.failed, self.progress = work, done, failed, progress

# @pytest.fixture
# def ui(tmp_path, monkeypatch):
#     app = QApplication.instance() or QApplication([])
# 2026-10-13：本次修改原因：整个测试进程共用 QApplication，与软件生命周期一致。
@pytest.fixture(scope="session")
# def qt_app():
#     return QApplication.instance() or QApplication([])
# 2026-10-13：本次修改原因：整个离线检查共用已加载中文字体的应用，不改变软件字体设置。
def qt_app():
    app = QApplication.instance() or QApplication([])
    # 2026-10-13：本次修改原因：Windows 离屏平台可能没有字体；使用系统中文字体验证真实字宽与裁切。
    if not QFontDatabase.families() and os.name == "nt":
        font_root = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
        for filename in ("msyh.ttc", "msyhbd.ttc"):
            font_path = os.path.join(font_root, filename)
            if os.path.isfile(font_path):
                QFontDatabase.addApplicationFont(font_path)
    return app

@pytest.fixture
def ui(tmp_path, monkeypatch, qt_app):
    app = qt_app
    from beaddiff.ui import editor, layout_support, theme
    factory = lambda *args: QSettings(str(tmp_path / "display.ini"), QSettings.Format.IniFormat)
    for module in (editor, layout_support, theme):
        monkeypatch.setattr(module, "QSettings", factory)
    # monkeypatch.setattr(ImagePreview, "set_url", lambda self, url: self.setText("商品图片预览" if url else "暂无图片"))
    # 2026-10-13：本次修改原因：主题在创建控件前初始化，遵循软件启动顺序。
    if not app.property("beaddiffTheme"):
        theme.apply_theme(app, "light")
    monkeypatch.setattr(ImagePreview, "set_url", lambda self, url: self.setText("商品图片预览" if url else "暂无图片"))
    config = ModelConfigStore(tmp_path)
    for category in ("text", "image"):
        profile = ModelProfile(category, category, name="测试模型", provider="测试",
                               url="https://example.com/v1", key="fake-key", modelname="fake", supports_vision=True)
        config.save(profile)
        config.activate(category)
    service = AIService(config, AssetStore(tmp_path))
    network = QNetworkAccessManager(app)
    hub = DeferredHub()
    widgets = []
    def keep(widget):
        widgets.append(widget)
        return widget
    view = keep(AIWorkbench(service, hub, ReferenceStore(tmp_path), network))
    view.set_product(product())
    yield SimpleNamespace(app=app, service=service, network=network, hub=hub, view=view, keep=keep, tmp=tmp_path)
    for widget in widgets:
        widget.hide()
        widget.deleteLater()
    # app.sendPostedEvents()
    # 2026-10-13：本次修改原因：在下一用例前实际释放控件，避免已退出窗口参与全局样式刷新。
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)

def entries(p):
    title = {"id": "title", "caption": "标题", "target": text_change(p)["target"],
             "request": {"operation": "title", "product": p}, "error": "",
             "result": {"candidates": ["标题一", "标题二"], "assets": []}}
    images = [{"id": f"image-{index}", "caption": f"图片{index}", "target": image_change(p)["target"],
               "request": {"operation": "image", "product": p}, "error": "",
               "result": {"candidates": [], "assets": [{"uri": URL + f"new{index}.jpg", "width": 20, "height": 10}]}}
              for index in range(2)]
    return [title, *images]

# def test_refresh_preserves_inputs_and_does_not_dirty_initial_page(ui):
#     view = ui.view
#     assert not view.input_dirty
#     view.subjects.set_urls([URL + "chosen-one.jpg", URL + "chosen-two.jpg"])
#     view.instruction.setPlainText("保留真实颜色")
#     view.set_product(product())
#     assert view.subjects.toPlainText().splitlines() == [URL + "chosen-one.jpg", URL + "chosen-two.jpg"]
#     assert view.instruction.toPlainText() == "保留真实颜色"
#     assert view.input_dirty
# 2026-10-14：本次修改原因：测试切换到整商品阶段、批量任务和草稿恢复。
# 原两栏 UI 用例保留，整商品工作区由下方新用例验证。

# def test_empty_sku_clears_previous_subject_and_suite_visibility_follows_task(ui):
#     view = ui.view
#     view.target.setCurrentIndex(3)
#     assert view.subjects.toPlainText() == ""
#     view.target.setCurrentIndex(0)
#     view.image_kind.setCurrentIndex(1)
#     view.tasks["images"].setChecked(True)
#     assert not view.slot_box.isHidden()
#     view.tasks["images"].setChecked(False)
#     assert view.slot_box.isHidden()
# 2026-10-14：本次修改原因：测试切换到整商品阶段、批量任务和草稿恢复。
# 原两栏 UI 用例保留，整商品工作区由下方新用例验证。

# def test_text_only_generation_requires_only_text_model_and_can_reuse_prompt(ui):
#     view = ui.view
#     row = view.store.save({"name": "柔光", "prompt": "统一柔光与留白"})
#     view.reload_references()
#     view.saved_reference.setCurrentIndex(view.saved_reference.findData(row["id"]))
#     view.image_model.setCurrentIndex(-1)
#     tasks = view.build_tasks()
#     assert len(tasks) == 1
#     assert tasks[0]["request"]["reference_text"] == "统一柔光与留白"
#     assert tasks[0]["request"]["model_id"] == "text"
# 2026-10-14：本次修改原因：测试切换到整商品阶段、批量任务和草稿恢复。
# 原两栏 UI 用例保留，整商品工作区由下方新用例验证。

# def test_retry_preserves_selection_order_and_edited_text(ui):
#     view = ui.view
#     view.finished({"result": {"entries": entries(product())}})
#     view.text_candidate.setCurrentIndex(1)
#     view.text_result.setPlainText("手动润色标题二")
#     view.text_apply.setChecked(False)
#     view.image_candidates.setCurrentRow(1)
#     view.move_image(-1)
#     view.image_candidates.item(0).setCheckState(Qt.CheckState.Unchecked)
#     before = view.capture_view()
#     view.redo_image()
#     assert view.busy
#     ui.hub.done({"result": {"entries": deepcopy(view.entries)}})
#     after = view.capture_view()
#     assert after["order"] == before["order"] and after["checks"] == before["checks"]
#     assert after["text"] == before["text"]
#     assert view.text_result.toPlainText() == "手动润色标题二"
# 2026-10-14：本次修改原因：测试切换到整商品阶段、批量任务和草稿恢复。
# 原两栏 UI 用例保留，整商品工作区由下方新用例验证。

# def test_partial_application_keeps_remaining_candidates(ui):
#     view = ui.view
#     view.finished({"result": {"entries": entries(product())}})
#     view.applied([text_change(product())])
#     assert view.pending
#     assert view.apply_button.isEnabled()
#     assert view.entries[0]["applied"]
#     received = []
#     view.applyRequested.connect(received.append)
#     view.apply()
#     assert received and all(change["target"]["field"] != "title" for change in received[0])
# 2026-10-14：本次修改原因：测试切换到整商品阶段、批量任务和草稿恢复。
# 原两栏 UI 用例保留，整商品工作区由下方新用例验证。

# def test_editor_seeds_current_sku_and_protects_prompt_only_draft(ui, monkeypatch):
#     editor = ui.keep(ProductEditor(None, Product.from_dict(product()), ui.network,
#                                   ai_service=ui.service, ai_hub=ui.hub, reference_store=ui.view.store))
#     editor.tabs.setCurrentIndex(2)
#     editor.sku_table.selectRow(0)
#     editor.mode_tabs.setCurrentIndex(1)
#     assert editor.ai_workbench.target.currentData()["field"] == "sku"
#     assert editor.ai_workbench.subjects.toPlainText() == URL + "red.jpg"
#     editor.ai_workbench.instruction.setPlainText("仅调整光线")
#     questions = []
#     monkeypatch.setattr(QMessageBox, "question", lambda *args: questions.append(args[2]) or QMessageBox.StandardButton.Cancel)
#     assert editor.reject() is False
#     assert questions and not editor._finished
# 2026-10-14：本次修改原因：测试切换到整商品阶段、批量任务和草稿恢复。
# 原两栏 UI 用例保留，整商品工作区由下方新用例验证。

def test_reference_save_then_switch_keeps_list_and_content_in_sync(ui, monkeypatch):
    store = ui.view.store
    first = store.save({"name": "方案一", "prompt": "Prompt 一"})
    second = store.save({"name": "方案二", "prompt": "Prompt 二"})
    page = ui.keep(ReferenceAnalysisPage(ui.service, ui.hub, store))
    page.load(first)
    page.prompt.setPlainText("修改的 Prompt 一")
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Save)
    index = next(i for i in range(page.records.count()) if page.records.item(i).data(Qt.ItemDataRole.UserRole) == second["id"])
    page.records.setCurrentRow(index)
    assert page.identifier == second["id"] and page.prompt.toPlainText() == "Prompt 二"
    assert page.records.currentItem().data(Qt.ItemDataRole.UserRole) == second["id"]
    assert next(row for row in store.list() if row["id"] == first["id"])["prompt"] == "修改的 Prompt 一"

# def test_offscreen_layout_at_compact_size(ui):
#     from beaddiff.ui.theme import apply_theme
#     view = ui.view
#     apply_theme(ui.app, "light")
#     view.resize(920, 590)
#     view.show()
#     ui.app.processEvents()
#     assert view.width() <= 920
#     assert view.generate_button.isVisible() and view.apply_button.isVisible()
#     assert view.generate_button.geometry().bottom() < view.height()
#     path = ui.tmp / "ai-materials-light.png"
#     assert view.grab().save(str(path))
#     print("VISUAL:", path)
#     view.inputs.setCurrentIndex(1)
#     ui.app.processEvents()
#     path = ui.tmp / "ai-prompt-light.png"
#     assert view.grab().save(str(path))
#     print("VISUAL:", path)
#     apply_theme(ui.app, "dark")
#     path = ui.tmp / "ai-prompt-dark.png"
#     assert view.grab().save(str(path))
#     print("VISUAL:", path)
#     page = ui.keep(ReferenceAnalysisPage(ui.service, ui.hub, view.store))
#     page.resize(920, 590)
#     page.show()
#     ui.app.processEvents()
#     assert page.width() <= 920
#     path = ui.tmp / "reference-dark.png"
#     assert page.grab().save(str(path))
#     print("VISUAL:", path)
# 2026-10-13：本次修改原因：布局稳定后验证浅深主题、图片对照和商品编辑页，避免首帧截图误判留白。
# def test_offscreen_layout_at_compact_size(ui):
#     from beaddiff.ui.theme import apply_theme
#     # 2026-10-13：本次修改原因：表格行高通过零延时事件调整，截图等待后续布局事件完成。
#     def settle():
#         for _ in range(4):
#             ui.app.processEvents()
#     view = ui.view
#     apply_theme(ui.app, "light")
#     view.resize(920, 590)
#     view.show()
#     settle()
#     assert view.width() <= 920
#     assert view.generate_button.isVisible() and view.apply_button.isVisible()
#     assert view.generate_button.geometry().bottom() < view.height()
#     path = ui.tmp / "ai-materials-light.png"
#     assert view.grab().save(str(path))
#     print("VISUAL:", path)
#     view.inputs.setCurrentIndex(1)
#     settle()
#     path = ui.tmp / "ai-prompt-light.png"
#     assert view.grab().save(str(path))
#     print("VISUAL:", path)
#     apply_theme(ui.app, "dark")
#     settle()
#     path = ui.tmp / "ai-prompt-dark.png"
#     assert view.grab().save(str(path))
#     print("VISUAL:", path)
#     # 2026-10-13：本次修改原因：核对窄窗口图片候选、原图对照和编辑页模式入口。
#     view.inputs.setCurrentIndex(0)
#     view.tasks["images"].setChecked(True)
#     view.finished({"result": {"entries": entries(product())}})
#     view.outputs.setCurrentIndex(1)
#     settle()
#     path = ui.tmp / "ai-images-dark.png"
#     assert view.grab().save(str(path))
#     print("VISUAL:", path)
#     editor = ui.keep(ProductEditor(None, Product.from_dict(product()), ui.network,
#                                   ai_service=ui.service, ai_hub=ui.hub, reference_store=view.store))
#     editor.resize(920, 590)
#     editor.show()
#     editor.mode_tabs.setCurrentIndex(1)
#     settle()
#     # assert editor.width() <= 920 and editor.back_button.isVisible() and editor.mode_tabs.isVisible()
#     # 2026-10-13：本次修改原因：除入口可见外，验证最后一个模式标签完整落在控件内，不被箭头遮住。
#     assert editor.width() <= 920 and editor.back_button.isVisible() and editor.mode_tabs.isVisible()
#     assert editor.mode_tabs.tabRect(1).right() < editor.mode_tabs.width()
#     assert not editor.mode_tabs.usesScrollButtons()
#     path = ui.tmp / "editor-ai-dark.png"
#     assert editor.grab().save(str(path))
#     print("VISUAL:", path)
#     page = ui.keep(ReferenceAnalysisPage(ui.service, ui.hub, view.store))
#     page.resize(920, 590)
#     page.show()
#     settle()#
# #     assert page.width() <= 920
# #     path = ui.tmp / "reference-dark.png"
# # 2026-10-13：本次修改原因：验证爆款分析主操作在窄窗口页脚完整显示。
#
#     assert page.width() <= 920
#     # 2026-10-13：本次修改原因：爆款分析主操作须在窄窗口页脚完整显示。
#     assert page.rect().contains(page.analyze_button.mapTo(page, page.analyze_button.rect().topLeft()))
#     assert page.rect().contains(page.analyze_button.mapTo(page, page.analyze_button.rect().bottomRight()))
#     path = ui.tmp / "reference-dark.png"
#     assert page.grab().save(str(path))
#     print("VISUAL:", path)
# 2026-10-14：本次修改原因：测试切换到整商品阶段、批量任务和草稿恢复。
# 原两栏 UI 用例保留，整商品工作区由下方新用例验证。


# 2026-10-14：本次修改原因：整商品方案测试覆盖素材完整性、断点续做、最终图片组及编辑应用；全部使用模拟模型。
from threading import Event
from beaddiff.ai.product_plan import (
    ProcessingStore, accept_plan, chosen_version, compose_changes, final_value,
    image_row, new_draft, planning_request, prepare_tasks, relevant, resume_tasks,
    run_tasks, validate_draft,
)
from beaddiff.assets import ImageAsset
# from PySide6.QtWidgets import QPushButton, QDialog
# 2026-10-14：本次修改原因：布局断言检查版本选择控件的实际矩形。
from PySide6.QtWidgets import QPushButton, QDialog, QComboBox
from beaddiff.ui.product_ai_workbench import ImageCard

def member(draft, group):
    return next(row for row in draft["rows"] if row["group"] == group)

def variant(row, value, approve=False):
    asset = {"uri": value, "width": 1024, "height": 1024} if row["group"] != "text" else value
    version = {"id": "version-" + str(len(row["versions"])), "value": asset, "request": {}, "created_at": "", "model_caption": "Mock"}
    row["versions"].append(version)
    row.update(choice=version["id"], approved=approve)
    return version

def model_result(request, number=0):
    if request.operation == "image":
        return AIResult("job", "image", assets=[ImageAsset(URL + f"result-{number}.jpg", 1024, 1024)], model_caption="Mock")
    return AIResult("job", request.operation, candidates=["Draft copy"], model_caption="Mock")

def execute(ui, draft, generate=None, pause=None):
    ready, ids = prepare_tasks(ui.service, draft)
    ui.service.generate = generate or model_result
    return run_tasks(ui.service, ui.view.processing, ready, ids, lambda value: None, pause)

def test_inventory_includes_html_only_details_and_all_sku_bindings():
    p = product()
    p["description_html"] += f'<img src="{URL}html-only.jpg"><img src="{URL}old.jpg">'
    p["skus"].append(dict(p["skus"][0], source_sku_id="red-large", spec2="Large"))
    draft = new_draft(p)
    assert [row["original"] for row in draft["rows"] if row["group"] == "detail_images"] == [URL+"old.jpg", URL+"html-only.jpg"]
    assert len(member(draft, "sku")["bindings"]) == 2
    assert sum(len(row["bindings"]) for row in draft["rows"] if row["group"] == "sku") == len(p["skus"])
    validate_draft(draft, p["id"])

def test_planning_has_full_inventory_and_rejects_missing_ids(ui):
    draft = ui.view.draft
    request = planning_request(ui.service, draft)
    assert {row["id"] for row in draft["rows"]} <= set(json.loads(request.instruction.split("素材清单：")[1])[i]["id"] for i in range(len(draft["rows"])))
    assert URL+"red.jpg" in request.subject_images
    planned = [{"id": row["id"], "action": "keep", "purpose": row["purpose"], "instruction": ""} for row in reversed(draft["rows"])]
    accepted = accept_plan(draft, json.dumps({"summary": "Consistent set", "rows": planned}))
    assert accepted["stage"] == 1 and accepted["rows"][0]["id"] == draft["rows"][-1]["id"]
    before = deepcopy(draft)
    with pytest.raises(ValueError):
        accept_plan(draft, json.dumps({"rows": planned[:-1]}))
    assert draft == before

def test_planning_additions_use_only_known_product_sources(ui):
    draft = ui.view.draft
    planned = [{"id": row["id"], "action": "keep", "purpose": row["purpose"], "instruction": ""} for row in draft["rows"]]
    source = member(draft, "images")
    result = {"rows": planned, "additions": [{"group": "detail_images", "source_ids": [source["id"]], "purpose": "Detail", "instruction": "Use true product"}]}
    accepted = accept_plan(draft, json.dumps(result))
    assert accepted["rows"][-1]["sources"] == [source["original"]]
    result["additions"][0]["source_ids"] = ["invented"]
    with pytest.raises(ValueError):
        accept_plan(draft, json.dumps(result))

def test_text_only_tasks_need_no_image_profile(ui):
    draft = ui.view.draft
    member(draft, "text")["action"] = "rewrite"
    draft["options"]["vision"] = False
    ui.service.config.profiles = [profile for profile in ui.service.config.profiles if profile.category == "text"]
    ready, ids = prepare_tasks(ui.service, draft)
    assert len(ids) == 1
    request = ready["queue"][0]["request"]
    assert request["model_id"] == "text" and request["subject_images"] == []

def test_multiple_generated_versions_are_one_listing_placement(ui):
    draft = ui.view.draft
    row = member(draft, "images")
    row["action"] = "remake"
    draft["options"]["count"] = 3
    calls = []
    def generate(request):
        calls.append(request)
        return model_result(request, len(calls))
    result = execute(ui, draft, generate)
    row = member(result, "images")
    assert len(row["versions"]) == 3 and len(calls) == 3
    assert not row["approved"] and compose_changes(result) == []
    row["approved"] = True
    changes = compose_changes(result)
    assert changes[0]["value"] == [URL+"result-3.jpg"]
    assert len(changes[0]["value"]) == 1
    assert "fake-key" not in json.dumps(result)

def test_quota_failure_pauses_then_resumes_without_repeating_successes(ui):
    draft = ui.view.draft
    member(draft, "images")["action"] = "remake"
    member(draft, "detail_images")["action"] = "remake"
    member(draft, "text")["action"] = "rewrite"
    calls = []
    def fail_second(request):
        calls.append(request)
        if len(calls) == 2:
            raise ValueError("quota fake-key exhausted")
        return model_result(request)
    result = execute(ui, draft, fail_second)
    assert len(calls) == 2
    assert [task["state"] for task in result["queue"]] == ["completed", "failed", "waiting"]
    assert "fake-key" not in result["queue"][1]["error"]
    assert len(member(result, "images")["versions"]) == 1
    saved = ui.view.processing.load(draft["product_id"])
    saved["options"]["instruction"] = "New text is for a later generation"
    ready, ids = resume_tasks(ui.service, saved)
    assert len(ids) == 2 and ready["queue"][0]["state"] == "completed"
    assert "New text" not in ready["queue"][1]["request"]["instruction"]
    ui.service.generate = model_result
    result = run_tasks(ui.service, ui.view.processing, ready, ids, lambda text: None)
    assert all(task["state"] == "completed" for task in result["queue"])
    assert len(member(result, "images")["versions"]) == 1

def test_pause_waits_for_current_item_and_stores_remaining(ui):
    draft = ui.view.draft
    member(draft, "images")["action"] = "remake"
    member(draft, "detail_images")["action"] = "remake"
    pause = Event()
    def generate(request):
        pause.set()
        return model_result(request)
    result = execute(ui, draft, generate, pause)
    assert [task["state"] for task in result["queue"]] == ["completed", "waiting"]
    assert ui.service.jobs.list(product()["id"], "product_batch")[0]["state"] == "paused"

def test_switch_current_model_only_changes_unfinished_resume_requests(ui):
    draft = ui.view.draft
    member(draft, "images")["action"] = "remake"
    draft["options"]["count"] = 2
    ready, ids = prepare_tasks(ui.service, draft)
    ready["queue"][0]["state"] = "completed"
    # new = deepcopy(ui.service.config.get("image"))
    # new.id, new.name = "new-image", "New current model"
    # 2026-10-14：本次修改原因：模型配置为不可变 dataclass，切换模型测试使用副本构造。
    from dataclasses import replace
    new = replace(ui.service.config.get("image"), id="new-image", name="New current model")
    ui.service.config.save(new)
    ui.service.config.activate(new.id)
    resumed, ids = resume_tasks(ui.service, ready)
    assert len(ids) == 1
    assert resumed["queue"][0]["request"]["model_id"] == "image"
    assert resumed["queue"][1]["request"]["model_id"] == "new-image"

def test_processing_roundtrip_retains_copy_edits_choices_and_interrupted_tasks(ui):
    draft = ui.view.draft
    row = member(draft, "text")
    row["action"] = "rewrite"
    variant(row, "Manually revised copy", True)
    ready, ids = prepare_tasks(ui.service, draft)
    ready["queue"][0]["state"] = "running"
    ui.view.processing.save(ready)
    saved = ui.view.processing.load(draft["product_id"])
    assert saved["queue"][0]["state"] == "waiting"
    assert final_value(member(saved, "text")) == "Manually revised copy"

def test_corrupt_processing_file_is_never_overwritten(ui):
    store, draft = ui.view.processing, ui.view.draft
    store.save(draft)
    path = store.path(draft["product_id"])
    path.write_text("{broken", encoding="utf-8")
    with pytest.raises(ValueError):
        store.load(draft["product_id"])
    with pytest.raises(ValueError):
        store.save(draft)
    assert path.read_text(encoding="utf-8") == "{broken"

@pytest.mark.parametrize("field,value", [("group", "bad"), ("stage", 7), ("applied", 0)])
def test_processing_rejects_damaged_page_state(field, value):
    draft = new_draft(product())
    draft[field] = value
    with pytest.raises(ValueError):
        validate_draft(draft, draft["product_id"])

def test_whole_product_apply_is_atomic_and_uses_sku_identity():
    p = product()
    draft = new_draft(p)
    for group, value in (("images", URL+"new-main.jpg"), ("detail_images", URL+"new-detail.jpg"), ("sku", URL+"new-red.jpg"), ("text", "Edited title")):
        row = member(draft, group)
        row["action"] = "rewrite" if group == "text" else "remake"
        variant(row, value, True)
    changes = compose_changes(draft)
    current = deepcopy(p)
    current["skus"].reverse()
    updated = apply_changes(current, changes)
    assert updated["title"] == "Edited title" and updated["images"] == [URL+"new-main.jpg"]
    assert description_images(updated["description_html"]) == [URL+"new-detail.jpg"]
    assert updated["skus"][1]["image"] == URL+"new-red.jpg"
    current["images"].append(URL+"manual.jpg")
    before = deepcopy(current)
    with pytest.raises(ValueError):
        apply_changes(current, changes)
    assert current == before

def test_detail_compose_preserves_inline_words_and_reorders_only_when_requested():
    p = product()
    p["description_html"] = f'<p>Before</p><img src="{URL}old.jpg"><p>Between</p><img src="{URL}html.jpg"><p>After</p>'
    draft = new_draft(p)
    details = [row for row in draft["rows"] if row["group"] == "detail_images"]
    variant(details[0], URL+"replacement.jpg", True)
    updated = apply_changes(p, compose_changes(draft))
    html = updated["description_html"]
    assert html.index("Before") < html.index("replacement.jpg") < html.index("Between") < html.index("html.jpg") < html.index("After")
    a, b = draft["rows"].index(details[0]), draft["rows"].index(details[1])
    draft["rows"][a], draft["rows"][b] = draft["rows"][b], draft["rows"][a]
    updated = apply_changes(p, compose_changes(draft))
    assert description_images(updated["description_html"]) == [URL+"html.jpg", URL+"replacement.jpg"]
    assert all(word in updated["description_html"] for word in ["Before", "Between", "After"])

def test_omitted_detail_is_removed_from_both_field_and_html():
    p = product()
    draft = new_draft(p)
    row = member(draft, "detail_images")
    row.update(action="omit", choice="omit")
    updated = apply_changes(p, compose_changes(draft))
    assert updated["detail_images"] == [] and description_images(updated["description_html"]) == []

def test_bulk_plan_and_stage_navigation_preserve_full_inventory(ui):
    view = ui.view
    inventory = deepcopy(view.draft["rows"])
    view.bulk.setCurrentIndex(view.bulk.findData("remake"))
    assert member(view.draft, "images")["action"] == "remake"
    assert member(view.draft, "detail_images")["action"] == "keep"
    view.primary_action()
    assert view.stage == 1
    assert {row["id"] for row in view.draft["rows"]} == {row["id"] for row in inventory}
    assert ui.hub.__dict__ == {}
    view.group_tabs.setCurrentIndex(2)
    view.draft["stage"] = 2
    view.render()
    view.bulk.setCurrentIndex(view.bulk.findData("original"))
    assert all(row["action"] == "keep" for row in view.draft["rows"] if row["group"] == "sku")
    validate_draft(view.draft, view.product["id"])

def test_ui_prompt_copy_and_save_on_leave(ui, monkeypatch):
    view = ui.view
    reference = view.store.save({"name": "Saved plan", "prompt": "Soft lighting"})
    view.reload_references()
    view.saved_reference.setCurrentIndex(view.saved_reference.findData(reference["id"]))
    view.instruction.setPlainText("Preserve product colour")
    assert view.draft["options"]["reference_prompt"] == "Soft lighting"
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Save)
    assert view.confirm_leave() and not view.input_dirty
    restored = view.processing.load(view.product["id"])
    assert restored["options"]["instruction"] == "Preserve product colour"
    assert restored["options"]["reference_prompt"] == "Soft lighting"
    assert view.store.list()[0]["prompt"] == "Soft lighting"

def test_ui_review_requires_explicit_adoption_and_keeps_copy_revision(ui):
    view = ui.view
    row = member(view.draft, "text")
    row["action"] = "rewrite"
    version = variant(row, "Generated title")
    view.draft["stage"] = 2
    view.group_tabs.setCurrentIndex(3)
    view.render()
    assert compose_changes(view.draft) == []
    view.edit_text(row["id"], "Manual title")
    view.approve(row["id"], True)
    assert compose_changes(view.draft)[0]["value"] == "Manual title"
    view.save_draft(quiet=True)
    assert final_value(member(view.processing.load(view.product["id"]), "text")) == "Manual title"

def test_ui_reorder_applies_one_complete_group(ui):
    view = ui.view
    extra = image_row("images", URL+"second.jpg", "Second")
    view.product["images"].append(URL+"second.jpg")
    view.draft = new_draft(view.product)
    members = [row for row in view.draft["rows"] if row["group"] == "images"]
    view.reorder(members[1]["id"], members[0]["id"])
    changes = compose_changes(view.draft)
    assert changes[0]["value"] == [URL+"second.jpg", URL+"main.jpg"]

def test_shared_sku_can_split_without_losing_bindings(ui, monkeypatch):
    view = ui.view
    view.product["skus"].append(dict(view.product["skus"][0], source_sku_id="red-large", spec2="Large"))
    view.draft = new_draft(view.product)
    shared = member(view.draft, "sku")
    assert len(shared["bindings"]) == 2
    monkeypatch.setattr(QDialog, "exec", lambda self: 3)
    view.edit_image(shared["id"])
    skus = [row for row in view.draft["rows"] if row["group"] == "sku"]
    assert len(skus) == 3 and all(len(row["bindings"]) == 1 for row in skus)

def test_editor_focuses_sku_group_and_preserves_all_image_classes(ui, monkeypatch):
    editor = ui.keep(ProductEditor(None, Product.from_dict(product()), ui.network, ai_service=ui.service, ai_hub=ui.hub, reference_store=ui.view.store))
    editor.tabs.setCurrentIndex(2)
    editor.sku_table.selectRow(0)
    editor.mode_tabs.setCurrentIndex(1)
    view = editor.ai_workbench
    assert view.group == "sku"
    assert {row["group"] for row in view.draft["rows"]} == {"images", "detail_images", "sku", "text"}
    view.instruction.setPlainText("Preserve colour")
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Cancel)
    assert not editor.reject() and not editor._finished

def test_editor_apply_returns_to_manual_and_processing_survives_product_cancel(ui, monkeypatch):
    editor = ui.keep(ProductEditor(None, Product.from_dict(product()), ui.network, ai_service=ui.service, ai_hub=ui.hub, reference_store=ui.view.store))
    editor.mode_tabs.setCurrentIndex(1)
    view = editor.ai_workbench
    row = member(view.draft, "images")
    row["action"] = "remake"
    variant(row, URL+"edited.jpg", True)
    view.draft["stage"] = 2
    view.apply()
    assert editor.mode_tabs.currentIndex() == 0
    assert editor.collect().images == [URL+"edited.jpg"] and editor.dirty
    assert view.draft["applied"] and view.product["images"] == [URL+"edited.jpg"]
    restored = ui.keep(AIWorkbench(ui.service, ui.hub, view.store, ui.network))
    restored.set_product(product())
    assert not restored.draft["applied"]
    assert final_value(member(restored.draft, "images")) == URL+"edited.jpg"

def test_business_pages_have_no_model_settings_popup(ui):
    page = ui.keep(ReferenceAnalysisPage(ui.service, ui.hub, ui.view.store))
    for widget in (ui.view, page):
        assert not any("模型设置" in control.text() or "模型配置" in control.text() for control in widget.findChildren(QPushButton))
        assert "模型" in widget.models_label.text() if widget is ui.view else page.models.text()
    assert not hasattr(page, "configure_models")

def test_product_processing_layout_light_dark_and_integrated_editor(ui):
    from beaddiff.ui.theme import apply_theme
    # def settle():
    #     for _ in range(5):
    #         ui.app.processEvents()
    # 2026-10-14：本次修改原因：截图前完成上一批卡片的延迟销毁，避免旧卡片参与主题和几何检查。
    def settle():
        ui.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        for _ in range(5):
            ui.app.processEvents()
    view = ui.view
    # for name in ("light", "dark"):
    #     apply_theme(ui.app, name)
    # 2026-10-14：本次修改原因：切换主题前结束当前布局事件，模拟正常界面事件边界。
    for name in ("light", "dark"):
        settle()
        apply_theme(ui.app, name)
        view.resize(920, 590)
        view.show()
        settle()
        # assert view.width() <= 920
        # 2026-10-14：本次修改原因：离屏验证批量操作在窄窗口真实可见且可点击。
        assert view.width() <= 920
        assert view.bulk.isVisible() and view.bulk.width() >= 160
        assert view.controls.rect().contains(view.bulk.mapTo(view.controls, view.bulk.rect().bottomRight()))
        assert view.rect().contains(view.primary.mapTo(view, view.primary.rect().bottomRight()))
        assert view.group_tabs.tabRect(3).right() < view.group_tabs.width()
        assert view.steps.tabRect(2).right() < view.steps.width()
        assert view.grab().save(str(ui.tmp / f"product-plan-{name}.png"))
        print("VISUAL:", ui.tmp / f"product-plan-{name}.png")
    view.draft["stage"] = 2
    variant(member(view.draft, "images"), URL+"result.jpg", True)
    view.render()
    settle()
    assert view.grab().save(str(ui.tmp / "product-review-dark.png"))
    print("VISUAL:", ui.tmp / "product-review-dark.png")
    # view.group_tabs.setCurrentIndex(3)
    # settle()
    # assert view.grab()
    # 2026-10-14：本次修改原因：文案版本选择不能落在卡片右边界之外。
    view.group_tabs.setCurrentIndex(3)
    settle()
    for combo in view.text_body.findChildren(QComboBox):
        if combo.isVisible():
            assert combo.parentWidget().rect().contains(combo.geometry())
    assert view.grab().save(str(ui.tmp / "product-copy-dark.png"))
    print("VISUAL:", ui.tmp / "product-copy-dark.png")
    editor = ui.keep(ProductEditor(None, Product.from_dict(product()), ui.network, ai_service=ui.service, ai_hub=ui.hub, reference_store=view.store))
    editor.resize(920, 590)
    editor.show()
    editor.mode_tabs.setCurrentIndex(1)
    settle()
    assert editor.width() <= 920 and editor.ai_workbench.isVisible()
    assert editor.grab().save(str(ui.tmp / "product-editor-dark.png"))
    print("VISUAL:", ui.tmp / "product-editor-dark.png")

# 2026-10-14：本次修改原因：验证用户改为保留、放弃商品草稿以及较多素材时的加工恢复和布局边界。
def test_resume_omits_tasks_user_changed_to_keep(ui):
    draft = ui.view.draft
    row = member(draft, "images")
    row["action"] = "remake"
    ready, ids = prepare_tasks(ui.service, draft)
    member(ready, "images")["action"] = "keep"
    resumed, ids = resume_tasks(ui.service, ready)
    assert ids == [] and resumed["queue"][0]["state"] == "superseded"

def test_unsaved_manual_changes_do_not_lock_processing_after_cancel(ui):
    view = ui.view
    view.product["title"] = "Unsaved manual title"
    view.draft = new_draft(view.product)
    row = member(view.draft, "images")
    variant(row, URL+"final.jpg", True)
    view.applied(compose_changes(view.draft), dict(view.product, images=[URL+"final.jpg"]))
    reopened = ui.keep(AIWorkbench(ui.service, ui.hub, view.store, ui.network))
    reopened.set_product(product())
    assert not reopened.draft["applied"]
    assert final_value(member(reopened.draft, "images")) == URL+"final.jpg"

def test_many_material_cards_do_not_expand_viewport_or_hide_bulk_controls(ui):
    view = ui.view
    p = product()
    p["images"] = [URL+f"main-{i}.jpg" for i in range(15)]
    p["detail_images"] = [URL+f"detail-{i}.jpg" for i in range(8)]
    p["skus"] = [dict(p["skus"][0], source_sku_id=str(i), spec1="Very long specification name "*4, image=URL+f"sku-{i}.jpg") for i in range(25)]
    view.product, view.draft = p, new_draft(p)
    view.resize(920, 590)
    view.show()
    for group in range(3):
        view.group_tabs.setCurrentIndex(group)
        view.render()
        for _ in range(5):
            ui.app.processEvents()
        assert view.cards.width() <= view.scroller.viewport().width()
        assert view.bulk.width() >= 160 and view.width() <= 920
        assert view.cards.columns >= 3
        visible = [card for card in view.cards.cards if isinstance(card, ImageCard) and card.preview_loaded]
        # assert len(visible) <= 6
        # assert view.grab().save(str(ui.tmp / f"many-materials-{group}.png"))
        # print("VISUAL:", ui.tmp / f"many-materials-{group}.png")
        # 2026-10-14：本次修改原因：首屏必须实际加载图片且不请求屏外素材，滚动到底部后必须加载最后一张，避免空加载误判通过。
        assert 0 < len(visible) <= 6
        assert not view.cards.cards[-1].preview_loaded
        assert view.grab().save(str(ui.tmp / f"many-materials-{group}.png"))
        print("VISUAL:", ui.tmp / f"many-materials-{group}.png")
        view.scroller.verticalScrollBar().setValue(view.scroller.verticalScrollBar().maximum())
        for _ in range(8):
            ui.app.processEvents()
        assert view.cards.cards[-1].preview_loaded
        view.scroller.verticalScrollBar().setValue(0)

# 2026-10-14：本次修改原因：回归用户应用一次结果后整页不可操作的问题，覆盖重入、恢复、按钮与异常保护。
def test_editor_reenter_ai_after_apply_starts_editable_round(ui):
    editor = ui.keep(ProductEditor(None, Product.from_dict(product()), ui.network,
                    ai_service=ui.service, ai_hub=ui.hub, reference_store=ui.view.store))
    editor.mode_tabs.setCurrentIndex(1)
    view = editor.ai_workbench
    view.instruction.setPlainText("Preserve product and colour")
    old = deepcopy(view.draft)
    row = member(view.draft, "images")
    row["action"] = "remake"
    variant(row, URL+"applied-main.jpg", True)
    view.draft["stage"] = 2
    view.apply()
    assert editor.mode_tabs.currentIndex() == 0
    assert editor.dirty and view.draft["applied"]
    editor.mode_tabs.setCurrentIndex(1)
    assert not view.draft["applied"] and view.draft["id"] != old["id"]
    assert view.draft["base"]["images"] == [URL+"applied-main.jpg"]
    assert view.instruction.toPlainText() == "Preserve product and colour"
    assert view.primary.isEnabled() and view.bulk.isEnabled() and view.advanced_button.isEnabled()
    assert view.cards.cards[0].isEnabled()
    assert view.processing.load(view.product["id"])["id"] == view.draft["id"]
    jobs = view.service.jobs.list(view.product["id"], "product_batch")
    assert any(job["result"]["draft"]["id"] == old["id"] and job["result"]["draft"]["applied"] for job in jobs)
    from PySide6.QtTest import QTest
    editor.resize(1000, 750)
    editor.show()
    ui.app.processEvents()
    QTest.mouseClick(view.primary, Qt.MouseButton.LeftButton)
    assert view.stage == 1
    assert editor.collect().images == [URL+"applied-main.jpg"] and editor.dirty
    assert not hasattr(ui.hub, "work")

def test_saved_applied_round_reopens_with_current_product_and_reference(ui):
    view = ui.view
    view.draft["options"].update(reference_prompt="Soft lighting", count=2)
    row = member(view.draft, "images")
    row["action"] = "remake"
    variant(row, URL+"saved-main.jpg", True)
    updated = apply_changes(view.product, compose_changes(view.draft))
    old_id = view.draft["id"]
    view.applied(compose_changes(view.draft), updated)
    reopened = ui.keep(AIWorkbench(ui.service, ui.hub, view.store, ui.network))
    reopened.set_product(updated)
    assert not reopened.draft["applied"] and reopened.draft["id"] != old_id
    assert member(reopened.draft, "images")["original"] == URL+"saved-main.jpg"
    assert reopened.draft["options"]["reference_prompt"] == "Soft lighting"
    assert reopened.draft["options"]["count"] == 2
    assert reopened.primary.isEnabled() and reopened.bulk.isEnabled()
    assert not hasattr(ui.hub, "work")

def test_completed_record_has_clickable_continue_and_keeps_versions(ui):
    view = ui.view
    row = member(view.draft, "text")
    row["action"] = "rewrite"
    variant(row, "Updated title", True)
    old_id = view.draft["id"]
    changes = compose_changes(view.draft)
    view.applied(changes, apply_changes(view.product, changes))
    assert view.primary.text() == "继续加工当前商品" and view.primary.isEnabled()
    assert not view.advanced_button.isEnabled()
    view.primary.click()
    assert not view.draft["applied"] and view.draft["id"] != old_id
    assert view.draft["base"]["title"] == "Updated title"
    jobs = view.service.jobs.list(view.product["id"], "product_batch")
    saved = next(job["result"]["draft"] for job in jobs if job["result"]["draft"]["id"] == old_id)
    assert chosen_version(member(saved, "text"))["value"] == "Updated title"
    assert view.advanced_button.isEnabled() and view.primary.isEnabled()

def test_continue_round_save_failure_keeps_previous_results_and_can_retry(ui, monkeypatch):
    view = ui.view
    row = member(view.draft, "images")
    variant(row, URL+"safe.jpg", True)
    changes = compose_changes(view.draft)
    view.applied(changes, apply_changes(view.product, changes))
    before = deepcopy(view.draft)
    save = view.processing.save
    def fail_save(draft):
        raise OSError("Disk unavailable")
    monkeypatch.setattr(view.processing, "save", fail_save)
    view.primary.click()
    assert view.draft == before and view.primary.isEnabled()
    assert "下一轮尚未开始" in view.status.text()
    monkeypatch.setattr(view.processing, "save", save)
    view.primary.click()
    assert not view.draft["applied"] and view.draft["id"] != before["id"]


# 2026-10-14：本次修改原因：回归只填 Prompt 或切换分组后零任务跳审核的问题，并验证 SKU 请求、已有结果与纯排序审核。
@pytest.mark.parametrize("image_configured", [True, False])
def test_prompt_and_sku_tab_with_all_keep_stays_in_plan(ui, image_configured):
    view = ui.view
    if not image_configured:
        ui.service.config.profiles = [profile for profile in ui.service.config.profiles if profile.category == "text"]
    view.steps.setCurrentIndex(1)
    view.group_tabs.setCurrentIndex(2)
    view.instruction.setPlainText("Preserve SKU colour and replace the background")
    view.primary.click()
    assert view.stage == 1 and view.steps.currentIndex() == 1
    assert all(row["action"] == "keep" for row in view.draft["rows"])
    assert not view.busy and ui.hub.__dict__ == {}
    assert view.primary.text() == "开始生成（0 项）"
    assert "尚未选择" in view.status.text() and "调整 / 重做" in view.status.text()
    saved = view.processing.load(view.product["id"])
    assert saved["stage"] == 1 and saved["queue"] == []
    assert saved["options"]["instruction"] == view.instruction.toPlainText()


def test_sku_adjust_combo_and_start_button_send_prompt_and_only_that_sku(ui):
    view = ui.view
    view.steps.setCurrentIndex(1)
    view.group_tabs.setCurrentIndex(2)
    prompt = "Preserve the red SKU and replace its background with white"
    view.instruction.setPlainText(prompt)
    row = member(view.draft, "sku")
    card = next(card for card in view.cards.cards if isinstance(card, ImageCard) and card.row["id"] == row["id"])
    action = card.findChild(QComboBox)
    action.setCurrentIndex(action.findData("adjust"))
    assert view.primary.text() == "开始生成（1 项）"
    calls = []
    def generate(request):
        calls.append(request)
        return model_result(request)
    ui.service.generate = generate
    view.primary.click()
    assert view.stage == 2 and view.busy
    assert len(view.draft["queue"]) == 1
    assert view.draft["queue"][0]["row_id"] == row["id"]
    ui.hub.done(ui.hub.work(ui.hub.progress))
    assert len(calls) == 1 and not view.busy
    assert prompt in calls[0].instruction
    assert "处理方式：调整" in calls[0].instruction
    assert calls[0].subject_images == [URL + "red.jpg"]
    assert [sku["source_sku_id"] for sku in calls[0].product["skus"]] == ["red"]
    assert len(member(view.draft, "sku")["versions"]) == 1
    assert not member(view.draft, "sku")["approved"]
    assert all(not row["versions"] for row in view.draft["rows"] if row["id"] != member(view.draft, "sku")["id"])
    assert "生成完成" in view.status.text()


@pytest.mark.parametrize("operation", ["reorder", "omit"])
def test_no_generation_edits_still_enter_review(ui, operation):
    view = ui.view
    view.product["images"].append(URL + "second.jpg")
    view.draft = new_draft(view.product)
    view.render()
    view.steps.setCurrentIndex(1)
    rows = [row for row in view.draft["rows"] if row["group"] == "images"]
    if operation == "reorder":
        view.reorder(rows[1]["id"], rows[0]["id"])
        expected = [URL + "second.jpg", URL + "main.jpg"]
    else:
        view.set_action(rows[0]["id"], "omit")
        expected = [URL + "second.jpg"]
    assert view.primary.text() == "进入审核（无需生成）"
    view.primary.click()
    assert view.stage == 2 and not view.busy and ui.hub.__dict__ == {}
    assert compose_changes(view.draft)[0]["value"] == expected


def test_completed_generation_returns_to_review_without_duplicate_request(ui):
    view = ui.view
    view.steps.setCurrentIndex(1)
    view.set_action(member(view.draft, "images")["id"], "adjust")
    ui.service.generate = model_result
    view.primary.click()
    ui.hub.done(ui.hub.work(ui.hub.progress))
    versions = deepcopy(member(view.draft, "images")["versions"])
    ui.hub.__dict__.clear()
    view.steps.setCurrentIndex(1)
    view.primary.click()
    assert view.stage == 2 and not view.busy and ui.hub.__dict__ == {}
    assert member(view.draft, "images")["versions"] == versions
    assert "无需新增生成请求" in view.status.text()


def test_review_tab_switch_does_not_generate_and_explains_start(ui):
    view = ui.view
    view.set_action(member(view.draft, "sku")["id"], "adjust")
    view.steps.setCurrentIndex(2)
    assert not view.busy and ui.hub.__dict__ == {}
    assert not view.stage_hint.isHidden()
    assert "不会开始生成" in view.stage_hint.text() and "第二步" in view.stage_hint.text()


# 2026-10-14：本次修改原因：验证 Prompt 多行、自动换行和窗口缩放后的实际可见性，长文保留滚动且不遮挡操作按钮。
def settle_ui(app):
    for _ in range(8):
        app.processEvents()


def test_prompt_grows_shrinks_and_scrolls_only_for_long_text(ui):
    view = ui.view
    # view.resize(1000, 800)
    # 2026-10-14：本次修改原因：在 920×590 小窗口验证长 Prompt，不允许输入增高将底部操作挤出视图。
    view.resize(920, 590)
    view.show()
    settle_ui(ui.app)
    prompt = view.instruction
    short_height = prompt.height()
    prompt.setPlainText("\n".join(["Keep the actual colour and shape"] * 5))
    settle_ui(ui.app)
    medium_height = prompt.height()
    assert medium_height > short_height
    assert prompt.verticalScrollBar().maximum() == 0
    assert view.rect().contains(view.primary.mapTo(view, view.primary.rect().bottomRight()))
    prompt.setPlainText("\n".join(["Keep the actual colour and shape"] * 30))
    settle_ui(ui.app)
    assert prompt.height() > medium_height
    assert prompt.height() < medium_height * 2
    assert prompt.verticalScrollBar().maximum() > 0
    # 2026-10-14：本次修改原因：确认小窗口不会被控件最小高度强制扩张。
    assert view.height() <= 590 and view.width() <= 920
    assert view.rect().contains(view.primary.mapTo(view, view.primary.rect().bottomRight()))
    # 2026-10-14：本次修改原因：保留长 Prompt 界面截图，检查输入增长后底部按钮仍完整可见。
    assert view.grab().save(str(ui.tmp / "prompt-long.png"))
    prompt.clear()
    settle_ui(ui.app)
    assert prompt.height() == short_height
    assert prompt.verticalScrollBar().maximum() == 0
    assert not hasattr(ui.hub, "work")
    assert view.grab().save(str(ui.tmp / "prompt-cleared.png"))


def test_prompt_reflows_after_width_and_font_changes(ui):
    from PySide6.QtGui import QFont
    from beaddiff.ui.widgets import AutoHeightTextEdit
    prompt = ui.keep(AutoHeightTextEdit())
    prompt.resize(900, 60)
    prompt.show()
    # prompt.setPlainText("Preserve the subject and adjust the background. " * 5)
    # 2026-10-14：本次修改原因：字体增大用例保持在八行以内，单独验证重排而非长文滚动上限。
    prompt.setPlainText("Preserve the subject and adjust the background. " * 4)
    settle_ui(ui.app)
    wide_height = prompt.height()
    prompt.resize(310, prompt.height())
    settle_ui(ui.app)
    assert prompt.height() > wide_height
    assert prompt.verticalScrollBar().maximum() == 0
    font = QFont(prompt.font())
    # font.setPointSizeF(font.pointSizeF() + 3)
    # 2026-10-14：本次修改原因：主题按像素设字体时 pointSizeF 为 -1，测试按实际字体单位增大。
    if font.pixelSize() > 0:
        font.setPixelSize(font.pixelSize() + 4)
    else:
        font.setPointSizeF(font.pointSizeF() + 3)
    old_height = prompt.height()
    prompt.setFont(font)
    settle_ui(ui.app)
    assert prompt.height() > old_height
    assert prompt.verticalScrollBar().maximum() == 0
    prompt.resize(900, prompt.height())
    settle_ui(ui.app)
    assert prompt.height() < old_height


# 2026-10-14：本次修改原因：复现导入空主编号、主动补填与 AI 文案应用保存，防止隐式补号或已有编号被覆盖。
@pytest.mark.parametrize("initial_code", ["", "SELLER-MAIN-1"])
def test_main_code_explicit_fill_and_ai_copy_save_preserve_code(ui, initial_code):
    class RecordingRepository:
        def save_product(self, value, approve=False):
            self.saved = Product.from_dict(value.to_dict())
    repository = RecordingRepository()
    p = product()
    p.update(main_code=initial_code, source_id="606787591832014", erp_imported=True)
    editor = ui.keep(ProductEditor(repository, Product.from_dict(p), ui.network,
                    ai_service=ui.service, ai_hub=ui.hub, reference_store=ui.view.store))
    assert not editor.dirty
    assert editor.collect().main_code == initial_code
    assert editor.fill_main_code_button.isHidden() == bool(initial_code)
    # 2026-10-14：本次修改原因：确认空编号时补填按钮在小窗口表单中可见且无裁切。
    editor.resize(920, 590)
    editor.show()
    settle_ui(ui.app)
    if not initial_code:
        control = editor.fill_main_code_button
        assert control.isVisible() and control.parentWidget().rect().contains(control.geometry())
        assert editor.grab().save(str(ui.tmp / "main-code-empty.png"))
    if not initial_code:
        assert "未提供" in editor.main_code_help.text()
    else:
        editor.fill_main_code_from_source()
        assert editor.fields["main_code"].text() == initial_code
    editor.mode_tabs.setCurrentIndex(1)
    view = editor.ai_workbench
    for row in view.draft["rows"]:
        if row["group"] == "text" and row["field"] in ("title", "simple_description"):
            row["action"] = "rewrite"
            variant(row, "Revised " + row["field"], True)
    view.draft["stage"] = 2
    view.apply()
    assert editor.mode_tabs.currentIndex() == 0
    assert editor.collect().main_code == initial_code
    if not initial_code:
        editor.fill_main_code_button.click()
        assert editor.fields["main_code"].text() == p["source_id"]
        assert editor.fill_main_code_button.isHidden()
    expected = initial_code or p["source_id"]
    assert editor.collect().main_code == expected
    editor.save_product(False)
    assert repository.saved.main_code == expected
    assert repository.saved.title == "Revised title"
    assert repository.saved.simple_description == "Revised simple_description"


@pytest.mark.parametrize("source_id", ["", "x" * 256])
def test_missing_or_oversized_source_id_cannot_fill_main_code(ui, source_id):
    p = product()
    p.update(main_code="", source_id=source_id)
    editor = ui.keep(ProductEditor(None, Product.from_dict(p), ui.network,
                    ai_service=ui.service, ai_hub=ui.hub, reference_store=ui.view.store))
    assert editor.fill_main_code_button.isHidden() or not editor.fill_main_code_button.isEnabled()
    editor.fill_main_code_from_source()
    assert editor.fields["main_code"].text() == ""
    assert not editor.dirty


# 2026-10-14：本次修改原因：验证本机图从未采用候选到商品应用的状态提示，并确认换回公网链接后提示消失。
@pytest.mark.parametrize("group", ["images", "detail_images", "sku"])
def test_local_image_notice_tracks_candidate_apply_and_public_replacement(ui, group):
    # 2026-10-14：本次修改原因：测试与页面共用图片组顺序，避免分组切换引用未导入常量。
    from beaddiff.ai.product_plan import GROUPS
    from io import BytesIO
    from PIL import Image
    from PySide6.QtWidgets import QLabel
    raw = BytesIO()
    Image.new("RGB", (32, 32), "white").save(raw, format="PNG")
    asset = ui.service.assets.save(raw.getvalue())
    editor = ui.keep(ProductEditor(None, Product.from_dict(product()), ui.network,
                    ai_service=ui.service, ai_hub=ui.hub, reference_store=ui.view.store))
    # editor.resize(1000, 750)
    # 2026-10-14：本次修改原因：新增本机素材提示后，审核和商品编辑在小窗口仍可操作。
    editor.resize(920, 590)
    editor.show()
    editor.mode_tabs.setCurrentIndex(1)
    view = editor.ai_workbench
    row = member(view.draft, group)
    row["action"] = "adjust"
    variant(row, asset.uri)
    view.draft["stage"] = 2
    view.group_tabs.setCurrentIndex(list(GROUPS).index(group))
    view.render()
    settle_ui(ui.app)
    assert not view.media_notice.isHidden()
    assert "尚未采用" in view.media_notice.text()
    card = next(card for card in view.cards.cards if isinstance(card, ImageCard) and card.row["id"] == row["id"])
    assert any("本机图片" in control.text() for control in card.findChildren(QLabel))
    view.approve(row["id"], True)
    assert "最终素材" in view.media_notice.text()
    assert "HTTP/HTTPS" in view.media_notice.text()
    # 2026-10-14：本次修改原因：截图核对采用本机图时的卡片标记、回传提示和审核布局。
    settle_ui(ui.app)
    # 2026-10-14：本次修改原因：警告提示不得撑大窗口或遮挡应用按钮。
    assert editor.height() <= 590 and editor.width() <= 920
    assert view.rect().contains(view.primary.mapTo(view, view.primary.rect().bottomRight()))
    assert view.grab().save(str(ui.tmp / f"local-{group}-review.png"))
    view.apply()
    assert editor.mode_tabs.currentIndex() == 0
    assert not editor.local_media_hint.isHidden()
    assert "1 项本机素材" in editor.local_media_hint.text()
    assert "已应用" in editor.edit_feedback.text()
    editor.fields["title"].setText("Another manual edit")
    assert not editor.local_media_hint.isHidden()
    public = URL + "hosted.jpg"
    if group == "sku":
        editor.sku_table.item(0, 8).setText(public)
    elif group == "images":
        editor.images.set_urls([public])
        editor.images.textChanged.emit()
    else:
        editor.detail_images.set_urls([public])
        editor.detail_images.textChanged.emit()
        assert not editor.local_media_hint.isHidden()
        editor.rich_description.set_html(f'<p>Details</p><img src="{public}">')
    assert editor.local_media_hint.isHidden()
    assert editor.collect().main_code == "DEMO"
    settle_ui(ui.app)
    assert editor.grab().save(str(ui.tmp / f"local-{group}-replaced.png"))


# 2026-10-14：本次修改原因：复现白底图创建、整套自动任务、显式采用和保存审核，确保主编号及建档数值不被 AI 覆盖。
@pytest.mark.parametrize('generate', [False, True])
def test_white_creation_uses_settings_and_explicit_generation(ui, monkeypatch, generate):
    from PIL import Image
    from beaddiff.listing import ListingDefaults, ListingDefaultsStore
    from beaddiff.storage import Repository
    from beaddiff.ui.product_creation import ProductCreation
    from PySide6.QtWidgets import QMessageBox
    original = ui.tmp / 'source.png'
    Image.new('RGB', (32, 32), 'white').save(original)
    store = ListingDefaultsStore(ui.tmp)
    store.save(ListingDefaults(category='handmade beads', price='7.00', supply_price='2.00'))
    repository = Repository(ui.tmp)
    dialog = ui.keep(ProductCreation(repository, ui.service.assets, defaults_store=store, ai_service=ui.service))
    monkeypatch.setattr(QMessageBox, 'warning', lambda *_args: pytest.fail(str(_args)))
    dialog.paths = [str(original)]
    dialog.create(generate=generate)
    item = repository.product(dialog.created_product.id)
    assert dialog.generate_listing is generate
    assert item.main_code and item.skus[0].platform_sku
    assert item.category == 'handmade beads' and item.supply_price == '2.00'
    assert item.skus[0].price == '7.00'
    assert not hasattr(ui.hub, 'work')


def test_white_creation_without_model_never_creates_product(ui, monkeypatch):
    from PIL import Image
    from beaddiff.listing import ListingDefaults, ListingDefaultsStore
    from beaddiff.ui.product_creation import ProductCreation
    from PySide6.QtWidgets import QMessageBox
    class ForbiddenRepository:
        def create_product(self, _item):
            pytest.fail('Model failure must occur before saving a product')
    path = ui.tmp / 'source.png'
    Image.new('RGB', (32, 32), 'white').save(path)
    store = ListingDefaultsStore(ui.tmp)
    store.save(ListingDefaults(category='beads'))
    warnings = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda _parent, _title, text: warnings.append(text))
    dialog = ui.keep(ProductCreation(ForbiddenRepository(), ui.service.assets, defaults_store=store))
    dialog.paths = [str(path)]
    dialog.create(generate=True)
    assert dialog.created_product is None
    assert warnings and '设置 → AI 模型' in warnings[0]


def test_white_listing_auto_queue_adopt_and_save_preserves_defaults(ui, monkeypatch):
    from io import BytesIO
    from PIL import Image
    from beaddiff.listing import ListingDefaults, uploaded_product
    from beaddiff.storage import Repository
    from beaddiff.miaoshou_mapping import create_payload
    from beaddiff.miaoshou_config import MiaoshouConfig
    raw = BytesIO()
    Image.new('RGB', (32, 32), 'white').save(raw, format='PNG')
    source = ui.service.assets.save(raw.getvalue())
    defaults = ListingDefaults(category='handmade beads', main_count=3, detail_count=2, price='8.00', supply_price='2.00')
    repository = Repository(ui.tmp)
    item = repository.create_product(uploaded_product([source], {'color': 'white'}, defaults))
    before = item.to_dict()
    calls = []
    def generate(request):
        calls.append(request)
        return model_result(request, len(calls))
    monkeypatch.setattr(ui.service, 'generate', generate)
    editor = ui.keep(ProductEditor(repository, item, ui.network,
                    ai_service=ui.service, ai_hub=ui.hub, reference_store=ui.view.store))
    editor.start_white_listing(defaults)
    view = editor.ai_workbench
    assert view.busy and editor.mode_tabs.currentIndex() == 1
    assert len(view.draft['queue']) == 9
    assert {request['operation'] for request in [task['request'] for task in view.draft['queue']]} == {
        'title', 'simple_description', 'description_html', 'image'}
    assert repository.product(item.id).to_dict() == before
    result = ui.hub.work(lambda _message: None)
    ui.hub.done(result)
    assert len(calls) == 9 and not view.busy
    assert all('handmade beads' in request.instruction for request in calls)
    assert all(request.subject_images for request in calls)
    assert all(not row['approved'] for row in view.draft['rows'])
    for row in view.draft['rows']:
        view.approve(row['id'], True)
    view.apply()
    current = editor.collect()
    assert editor.mode_tabs.currentIndex() == 0
    assert current.main_code == item.main_code and current.skus[0].platform_sku == item.skus[0].platform_sku
    assert current.supply_price == '2.00' and current.skus[0].price == '8.00'
    assert current.package_weight == item.package_weight and current.skus[0].stock == '0'
    assert len(current.images) == 3 and len(current.detail_images) == 2
    assert current.skus[0].image != source.uri and source.uri not in current.description_html
    assert current.issues() == []
    assert not current.erp_transferred_at
    assert create_payload(current, MiaoshouConfig())['price'] == 2
    editor.save_product(True)
    saved = repository.product(item.id)
    assert saved.approved and saved.main_code == item.main_code
    assert saved.images == current.images and saved.skus[0].price == '8.00'


def test_row_prompt_and_upload_prompt_grow_and_keep_footer(ui):
    from beaddiff.ui.widgets import AutoHeightTextEdit
    from beaddiff.ui.product_creation import ProductCreation
    from PySide6.QtWidgets import QPushButton
    view = ui.view
    view.draft['stage'] = 1
    view.group_tabs.setCurrentIndex(3)
    view.resize(920, 590)
    view.show()
    view.render()
    settle_ui(ui.app)
    # prompts = view.text_body.findChildren(AutoHeightTextEdit, 'rowPrompt')
    # 2026-10-14：本次修改原因：只验证实际可见的输入框，排除重绘后隐藏并等待 Qt 延迟销毁的旧卡片。
    prompts = [control for control in view.text_body.findChildren(AutoHeightTextEdit, 'rowPrompt') if control.isVisible()]
    assert prompts
    prompt = prompts[0]
    short = prompt.height()
    prompt.setPlainText('\n'.join(['Use the confirmed facts'] * 6))
    settle_ui(ui.app)
    assert prompt.height() > short and prompt.verticalScrollBar().maximum() == 0
    prompt.setPlainText('\n'.join(['Use the confirmed facts'] * 40))
    settle_ui(ui.app)
    assert prompt.verticalScrollBar().maximum() > 0
    assert view.height() <= 590 and view.rect().contains(view.primary.mapTo(view, view.primary.rect().bottomRight()))
    dialog = ui.keep(ProductCreation(None, ui.service.assets))
    dialog.resize(700, 590)
    dialog.show()
    dialog.prompt.setPlainText('\n'.join(['Keep the shape and colours'] * 40))
    settle_ui(ui.app)
    assert dialog.prompt.verticalScrollBar().maximum() > 0
    for control in dialog.findChildren(QPushButton):
        if control.text() in ('仅创建草稿', '创建并生成完整 Listing'):
            assert control.isVisible() and dialog.rect().contains(control.mapTo(dialog, control.rect().bottomRight()))
    assert dialog.grab().save(str(ui.tmp / 'white-upload-long-prompt.png'))


def test_listing_settings_and_help_explain_current_workflow(ui):
    from beaddiff.listing import ListingDefaultsStore
    from beaddiff.ui.listing_settings import ListingSettingsPage
    from beaddiff.ui.workflow_pages import HelpPage
    from PySide6.QtWidgets import QLabel
    store = ListingDefaultsStore(ui.tmp)
    settings = ui.keep(ListingSettingsPage(store))
    settings.fields['category'].setText('handmade beads')
    settings.save()
    assert store.get().category == 'handmade beads'
    # owner = SimpleNamespace(SETTINGS_HOSTING=4, SETTINGS_LISTING=7, PAGE_PRODUCTS=0, PAGE_REFERENCES=4, PAGE_HOSTING=6,
    #                         open_settings=lambda *_args: None, navigate=lambda *_args: None, show_erp_records=lambda: None)
    # 2026-10-14：本次修改原因：帮助页父对象与实际主窗口一致，使用 QWidget 验证设置导航。
    from PySide6.QtWidgets import QWidget
    owner = ui.keep(QWidget())
    for key, value in dict(SETTINGS_HOSTING=4, SETTINGS_LISTING=7, PAGE_PRODUCTS=0, PAGE_REFERENCES=4, PAGE_HOSTING=6,
                          open_settings=lambda *_args: None, navigate=lambda *_args: None, show_erp_records=lambda: None).items():
        setattr(owner, key, value)
    page = ui.keep(HelpPage(owner))
    text = ' '.join(control.text() for control in page.findChildren(QLabel))
    assert '白底图 Listing' in text and '图床' in text
    assert 'SKU' in text and '保存并审核' in text and '未采用候选不上传' in text
