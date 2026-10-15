# 2026-10-15：本次修改原因：覆盖原料事实、配方核算、商品交接与重新确认；供用户自行执行，不调用模型或 ERP。
from copy import deepcopy

import pytest

from beaddiff.beads import BeadDesign, BeadStore, MaterialItem
from beaddiff.bead_workflow import (
    confirmed_facts, evaluate, image_request, make_product, normalize_candidate,
    normalize_listing, snapshot_key,
)
from beaddiff.storage import Repository


def material(identifier="m1", code="B01", **options):
    values = dict(id=identifier, code=code, name="测试原料", unit_cost="0.20",
                  facts={"material": "玻璃", "axial_mm": "8"},
                  fact_sources={"material": "supplier", "axial_mm": "human"},
                  fact_statuses={"material": "confirmed", "axial_mm": "confirmed"},
                  images=["https://example.com/raw.jpg"])
    values.update(options)
    return MaterialItem(**values)


def candidate(sequence=None, components=None):
    return {"name": "浅绿手链", "sequence": sequence if sequence is not None else [
        {"material_id": "m1", "quantity": 2}], "components": components or []}


@pytest.fixture
def locked_design():
    item = material()
    selected = normalize_candidate(candidate(), {item.id})
    return BeadDesign(
        id="design-fixture", title="测试设计", material_ids=[item.id],
        material_snapshot={item.id: item.snapshot()}, candidates=[selected],
        selected_candidate_id=selected["id"],
        locked_bom=evaluate(selected, {item.id: item}, {})["bom"],
        locked_material_revisions={item.id: item.revision},
        listing={"title": "Glass bracelet", "bullets": ["Glass beads"],
                 "description_html": "<p>Glass bracelet</p>", "images_confirmed": True,
                 "images": [{"uri": "https://example.com/main.jpg", "role": "main_sku",
                             "purpose": "主图", "selected": True, "origin": "upload"}]},
    )


def test_duplicate_code_and_stale_save_leave_caller_identity_unchanged(tmp_path):
    store = BeadStore(tmp_path)
    original = store.save_material(material(identifier=""))
    duplicate = material(identifier="")
    before = deepcopy(duplicate)
    with pytest.raises(ValueError, match="编号已存在"):
        store.save_material(duplicate)
    assert duplicate == before
    stale = deepcopy(original)
    original.name = "已更新名称"
    store.save_material(original, expected_revision=original.revision)
    stale.name = "旧窗口修改"
    stale_before = deepcopy(stale)
    with pytest.raises(ValueError, match="已被更新"):
        store.save_material(stale, expected_revision=stale.revision)
    assert stale == stale_before
    assert store.material(original.id).name == "已更新名称"


# 2026-10-15：本次修改原因：自动编号须跨类目、归档和多窗口保存保持唯一，同时保留自定义编号及旧记录编号约束。
def test_blank_material_codes_are_allocated_globally_at_save_time(tmp_path):
    store = BeadStore(tmp_path)
    first_draft = MaterialItem(name="第一种原料")
    second_draft = MaterialItem(name="另一窗口原料")
    store.save_material(first_draft)
    assert first_draft.code == "M000001"
    store.archive_material(first_draft.id)
    library = store.add_library("布料")
    store.save_material(MaterialItem(code="M000010", name="自定义编号", library_category=library))
    store.save_material(MaterialItem(code="M11-custom", name="非流水编号"))
    store.save_material(second_draft)
    assert second_draft.code == "M000011"
    other = store.save_material(MaterialItem(name="其他类目原料", library_category=library))
    assert other.code == "M000012"
    assert store.material(first_draft.id).code == "M000001"
    second_draft.name = "改名保留编号"
    store.save_material(second_draft, expected_revision=second_draft.revision)
    assert second_draft.code == "M000011"


def test_material_validation_failure_does_not_assign_code_or_clear_existing_code(tmp_path):
    store = BeadStore(tmp_path)
    invalid = MaterialItem(unit_cost="invalid")
    with pytest.raises(ValueError, match="单位成本"):
        store.save_material(invalid)
    assert invalid.id == invalid.code == ""
    saved = store.save_material(MaterialItem(name="正常原料"))
    assert saved.code == "M000001"
    saved.code = ""
    with pytest.raises(ValueError, match="已有原料编号不能为空"):
        store.save_material(saved, expected_revision=saved.revision)
    assert store.material(saved.id).code == "M000001"


@pytest.mark.parametrize("source,key", [("vision", "material"), ("vision", "hole_mm"),
                                        ("unknown", "color")])
def test_exact_or_unattributed_facts_cannot_be_confirmed(tmp_path, source, key):
    store = BeadStore(tmp_path)
    item = material(identifier="", facts={key: "1"}, fact_sources={key: source},
                    fact_statuses={key: "confirmed"})
    with pytest.raises(ValueError, match="资料需要"):
        store.save_material(item)
    assert item.id == ""
    assert store.list_materials() == []


def test_visible_observation_and_trusted_facts_remain_distinct(tmp_path):
    store = BeadStore(tmp_path)
    item = material(identifier="", facts={"color": "浅绿", "material": "玻璃", "hole_mm": "1"},
                    fact_sources={"color": "vision", "material": "supplier", "hole_mm": "human"},
                    fact_statuses={"color": "confirmed", "material": "confirmed", "hole_mm": "pending"})
    store.save_material(item)
    assert confirmed_facts(store.material(item.id)) == {"color": "浅绿", "material": "玻璃"}
    legacy = item.snapshot()
    legacy["facts"].update({"axial_mm": "8", "meaning": "文化寓意"})
    legacy["fact_sources"].update({"axial_mm": "vision", "meaning": "unknown"})
    legacy["fact_statuses"].update({"axial_mm": "confirmed", "meaning": "confirmed"})
    assert confirmed_facts(legacy) == {"color": "浅绿", "material": "玻璃"}


def test_category_libraries_and_design_versions_are_independent(tmp_path):
    store = BeadStore(tmp_path)
    category = store.add_library("布料")
    item = store.save_material(material(identifier="", library_category=category))
    assert store.list_materials() == []
    assert store.list_materials(library_category=category)[0].id == item.id
    design = store.save_design(BeadDesign(title="初稿"))
    stale = deepcopy(design)
    design.title = "二稿"
    store.save_design(design, expected_revision=design.revision)
    before = deepcopy(stale)
    with pytest.raises(ValueError, match="已被更新"):
        store.save_design(stale, expected_revision=stale.revision)
    assert stale == before
    assert [row["title"] for row in store.versions(design.id)] == ["二稿", "初稿"]


@pytest.mark.parametrize("quantity", [True, False, 1.5, "2", 0, -1, 1001])
def test_candidate_rejects_non_integer_or_out_of_range_quantity(quantity):
    with pytest.raises(ValueError, match="整数"):
        normalize_candidate(candidate([{"material_id": "m1", "quantity": quantity}]), {"m1"})


def test_candidate_rejects_unselected_empty_or_unbounded_sequence():
    with pytest.raises(ValueError, match="未选择"):
        normalize_candidate(candidate(), {"m2"})
    with pytest.raises(ValueError, match="缺少串珠排列"):
        normalize_candidate(candidate([]), {"m1"})
    with pytest.raises(ValueError, match="数量过多"):
        normalize_candidate(candidate([{"material_id": "m1", "quantity": 1000},
                                       {"material_id": "m1", "quantity": 1}]), {"m1"})


@pytest.mark.parametrize("kind", ["cord", "packaging"])
def test_cord_and_packaging_cannot_be_sequence_segments(kind):
    with pytest.raises(ValueError, match="不能作为串珠排列"):
        evaluate(candidate(), {"m1": material(category=kind)}, {})


def test_bom_merges_segments_and_keeps_decimal_currencies_and_unknown_stock():
    bead = material(track_inventory=True, quantity=30)
    cord = material("m2", "C01", category="cord", unit_cost="0.10", currency="USD")
    selected = candidate([{"material_id": "m1", "quantity": 1},
                          {"material_id": "m1", "quantity": 2}],
                         [{"material_id": "m2", "quantity": 1}])
    result = evaluate(selected, {bead.id: bead, cord.id: cord},
                      {"cost_limit": "1", "cost_currency": "CNY"})
    assert [(row["code"], row["quantity"]) for row in result["bom"]] == [("B01", 3), ("C01", 1)]
    assert result["cost"] == "0.60 CNY + 0.10 USD"
    assert result["stock"] == "部分原料可做 10 件，其余未知"
    assert result["length"] == "24 mm（沿线占长，非腕围）"
    assert any("无法校验成本上限" in warning for warning in result["warnings"])
    assert bead.quantity == 30 and bead.reserved_quantity == 0


def test_unknown_cost_and_diameter_do_not_become_total_cost_or_wrist_size():
    item = material(unit_cost="", facts={"diameter_mm": "8"},
                    fact_sources={"diameter_mm": "human"}, fact_statuses={"diameter_mm": "confirmed"})
    result = evaluate(candidate(), {item.id: item}, {"cost_limit": "1", "cost_currency": "CNY"})
    assert result["cost"] == result["stock"] == "未知"
    assert result["length"] == "待实测"
    assert any("缺少成本" in warning for warning in result["warnings"])


def test_image_references_use_only_adopted_materials_and_require_their_photos(locked_design):
    unused = material("m2", "B02")
    locked_design.material_snapshot = {unused.id: unused.snapshot(), **locked_design.material_snapshot}
    request = image_request(locked_design, ["主图"])
    assert request.subject_images == ["https://example.com/raw.jpg"]
    assert '"reference_image_number": 1' in request.instruction
    assert '"code": "B02"' not in request.instruction
    locked_design.material_snapshot["m1"]["images"] = []
    with pytest.raises(ValueError, match="缺少图片"):
        image_request(locked_design, ["主图"])


def test_adopted_image_roles_map_to_product_and_listing_html_is_cleaned(locked_design):
    locked_design.listing["images"] += [
        {"uri": "https://example.com/detail.jpg", "role": "detail", "selected": True},
        {"uri": "https://example.com/unused.jpg", "role": "main", "selected": False},
    ]
    product = make_product(locked_design, "12", "CNY")
    assert product.images == ["https://example.com/main.jpg"]
    assert product.detail_images == ["https://example.com/detail.jpg"]
    assert product.skus[0].image == product.images[0]
    assert product.source_route == "bead_chain"
    assert product.bom_snapshot["version"] == snapshot_key(locked_design)
    assert product.skus[0].stock == product.skus[0].weight == ""
    listing = normalize_listing({"title": "Glass", "bullets": [],
                                 "description_html": "<p>Glass</p><script>bad()</script>"})
    assert "bad()" not in listing["description_html"]
    assert listing["images_confirmed"] is False


@pytest.mark.parametrize("invalid", ["unconfirmed", "no_sku", "two_skus", "wrong_bom", "too_many_main"])
def test_product_handoff_blocks_inconsistent_or_unreviewed_assets(locked_design, invalid):
    if invalid == "unconfirmed":
        locked_design.listing["images_confirmed"] = False
    elif invalid == "no_sku":
        locked_design.listing["images"][0]["role"] = "main"
    elif invalid == "two_skus":
        locked_design.listing["images"].append(
            {"uri": "https://example.com/sku2.jpg", "role": "sku", "selected": True})
    elif invalid == "wrong_bom":
        locked_design.locked_bom[0]["quantity"] += 1
    else:
        locked_design.listing["images"] += [
            {"uri": f"https://example.com/{index}.jpg", "role": "main", "selected": True}
            for index in range(15)]
    with pytest.raises(ValueError):
        make_product(locked_design, "12", "CNY")


def test_repeated_handoff_returns_existing_edits_and_does_not_restore_recycle_bin(tmp_path, locked_design):
    repository = Repository(tmp_path)
    original = repository.create_design_product(make_product(locked_design, "12", "CNY"))
    original.title = "人工编辑标题"
    saved = repository.save_product(original, confirm_design_images=True)
    repeated = repository.create_design_product(make_product(locked_design, "20", "USD"))
    assert repeated.id == saved.id and repeated.title == saved.title
    assert repeated.skus[0].price == "12" and repeated.revision == saved.revision
    assert len(repository.products()) == 1 and repository.captures() == []
    assert repository.hide_local_items("products", [saved.id])["hidden"] == 1
    with pytest.raises(ValueError, match="回收站"):
        repository.create_design_product(make_product(locked_design, "12", "CNY"))


@pytest.mark.parametrize("field", ["title", "images", "detail_images", "description_html", "sku_image", "sku_spec"])
def test_content_changes_require_explicit_review_before_approval(tmp_path, locked_design, field):
    repository = Repository(tmp_path)
    product = repository.create_design_product(make_product(locked_design, "12", "CNY"))
    if field == "sku_image":
        product.skus[0].image = "https://example.com/new.jpg"
    elif field == "sku_spec":
        product.skus[0].spec1 = "修改规格"
    elif field in {"images", "detail_images"}:
        setattr(product, field, ["https://example.com/new.jpg"])
    else:
        setattr(product, field, "修改图文")
    saved = repository.save_product(product)
    assert saved.bom_snapshot["images_confirmed"] is False
    saved.bom_snapshot["images_confirmed"] = True
    with pytest.raises(ValueError, match="尚未人工核对"):
        repository.save_product(saved, approve=True)
    assert repository.product(saved.id).approved is False
    approved = repository.save_product(repository.product(saved.id), approve=True, confirm_design_images=True)
    assert approved.approved and approved.bom_snapshot["images_confirmed"] is True


def test_regular_edits_cannot_replace_provenance_or_bom_and_price_edits_keep_review(tmp_path, locked_design):
    repository = Repository(tmp_path)
    product = repository.create_design_product(make_product(locked_design, "12", "CNY"))
    expected = deepcopy(product.bom_snapshot)
    product.source_route, product.source_ref_id, product.design_version_id = "", "forged", "forged"
    product.bom_snapshot = {"bom": []}
    product.skus[0].price, product.skus[0].stock = "15", "10"
    saved = repository.save_product(product, approve=True)
    assert saved.source_route == "bead_chain" and saved.source_ref_id == locked_design.id
    assert saved.design_version_id == snapshot_key(locked_design)
    assert saved.bom_snapshot == expected and saved.approved
