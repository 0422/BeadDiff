# 2026-10-15：本次修改原因：覆盖散珠 AI 的图片编号与视觉能力约束，所有模型请求均用本地替身，供用户自行执行。
import base64
# 2026-10-15：本次修改原因：失败且无结果的任务不进入候选列表，直接读取留档检查失败状态。
import json
from io import BytesIO

from PIL import Image
import pytest

from beaddiff.ai import service as service_module
from beaddiff.ai.client import CompatibleClient
from beaddiff.ai.config import ModelConfigStore, ModelProfile
from beaddiff.ai.contracts import AIRequest
from beaddiff.ai.service import AIService
from beaddiff.assets import AssetStore


def configured_service(tmp_path, *, category="text", vision=False):
    store = ModelConfigStore(tmp_path)
    profile = ModelProfile("bead-test", category, provider="测试替身", url="https://model.example/v1",
                           key="test", modelname="bead-test", supports_vision=vision)
    store.save(profile)
    store.activate(profile.id)
    return AIService(store, AssetStore(tmp_path))


@pytest.mark.parametrize("vision", [True, False])
def test_design_keeps_repeated_reference_numbers_or_explicitly_uses_text_only(tmp_path, monkeypatch, vision):
    seen = []

    class FakeClient:
        def __init__(self, *_args):
            pass

        def complete(self, system, prompt, images):
            seen.append((prompt, images))
            return '{"designs":[]}'

    monkeypatch.setattr(service_module, "CompatibleClient", FakeClient)
    service = configured_service(tmp_path, vision=vision)
    result = service.generate(AIRequest("bead_design", {"id": "d1"}, subject_images=["shared", "shared"]))
    assert result.candidates == ['{"designs":[]}']
    assert seen[0][1] == (["shared", "shared"] if vision else [])
    if not vision:
        assert "未读取原料图" in seen[0][0]


def test_material_observation_requires_vision_before_any_network_request(tmp_path, monkeypatch):
    service = configured_service(tmp_path)

    def unexpected_request(*_args, **_kwargs):
        raise AssertionError("视觉能力校验必须先于网络请求")

    monkeypatch.setattr(CompatibleClient, "_request", unexpected_request)
    with pytest.raises(ValueError, match="图片理解"):
        service.generate(AIRequest("material_observation", {"id": "m1"}, subject_images=["raw"]))
    # job = service.jobs.list("m1", "material_observation")[0]
    # 2026-10-15：本次修改原因：JobStore.list 只返回有结果的候选，失败观察应核对原始任务留档。
    job = json.loads(next(service.jobs.root.glob("*.json")).read_text(encoding="utf-8"))
    assert job["state"] == "failed"


def test_bead_image_preserves_shared_photo_order_and_keeps_partial_results(tmp_path, monkeypatch):
    raw = BytesIO()
    Image.new("RGB", (12, 8), "white").save(raw, format="PNG")
    seen = []

    class FakeClient:
        def __init__(self, *_args):
            pass

        def image(self, instruction, references, size):
            seen.append((instruction, references))
            if len(seen) == 2:
                raise ValueError("第二张生成失败")
            return {"data": [{"b64_json": base64.b64encode(raw.getvalue()).decode("ascii")}]}

    monkeypatch.setattr(service_module, "CompatibleClient", FakeClient)
    service = configured_service(tmp_path, category="image")
    result = service.generate(AIRequest("bead_image", {"id": "d1"},
                                        subject_images=["shared", "shared", "other"], slots=["主图", "SKU 图"]))
    assert all(row[1] == ["shared", "shared", "other"] for row in seen)
    assert "不是现成手链" in seen[0][0]
    assert len(result.assets) == 1 and len(result.errors) == 1
    assert result.purposes == ["主图"]
    assert service.jobs.list("d1", "bead_image")[0]["state"] == "partial"
