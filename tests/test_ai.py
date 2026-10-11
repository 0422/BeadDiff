# 2026-10-11：本次修改原因：覆盖配置保护、兼容协议、计费重试边界、部分成功和本地图片导出约束；不访问真实模型。
import base64
from dataclasses import replace
from io import BytesIO
import json
from types import SimpleNamespace

import httpx
from PIL import Image
import pytest

from beaddiff.ai import client as client_module
from beaddiff.ai import service as service_module
from beaddiff.ai.client import CompatibleClient, ModelCallError, endpoint, image_sources
from beaddiff.ai.config import ModelConfigStore, ModelProfile
from beaddiff.ai.contracts import AIRequest
from beaddiff.ai.service import AIService
from beaddiff.assets import AssetStore, local_asset_path
from beaddiff.content import clean_description, description_images
from beaddiff.exporter import export_products
from beaddiff.models import Product, SKU
from beaddiff.storage import Repository


def profile(category="text", identifier="text-one", **options):
    return ModelProfile(identifier, category, provider="兼容测试服务", url="https://model.example/v1",
                        key="test-secret-do-not-log", modelname="test-model", **options)


@pytest.fixture
def png():
    buffer = BytesIO()
    Image.new("RGB", (12, 8), "white").save(buffer, format="PNG")
    return buffer.getvalue()


def test_configuration_roundtrip_and_category_selection(tmp_path):
    store = ModelConfigStore(tmp_path)
    for item in (profile(), profile(identifier="text-two"), profile("image", "image-one")):
        store.save(item)
        store.activate(item.id)
    restored = ModelConfigStore(tmp_path)
    assert restored.get(category="text").id == "text-two"
    assert restored.get(category="image").id == "image-one"
    assert restored.get().key == "test-secret-do-not-log"
    restored.remove("text-two")
    assert restored.active == {"text": "", "image": "image-one"}
    assert ModelConfigStore(tmp_path).active == restored.active


def test_invalid_configuration_is_preserved_and_blocks_calls(tmp_path):
    store = ModelConfigStore(tmp_path)
    store.path.write_text('{"profiles": [broken', encoding="utf-8")
    before = store.path.read_bytes()
    assert not store.reload()
    assert store.error and not store.profiles
    with pytest.raises(ValueError):
        store.save(profile())
    with pytest.raises(ValueError):
        store.get()
    assert store.path.read_bytes() == before


def test_external_changes_require_reload_and_drafts_cannot_activate(tmp_path):
    store = ModelConfigStore(tmp_path)
    store.save(profile())
    content = json.loads(store.path.read_text(encoding="utf-8"))
    content["profiles"][0]["modelname"] = "external-model"
    store.path.write_text(json.dumps(content), encoding="utf-8")
    before = store.path.read_bytes()
    with pytest.raises(ValueError, match="外部修改"):
        store.activate("text-one")
    assert store.path.read_bytes() == before
    assert store.reload()
    assert store.get("text-one").modelname == "external-model"
    store.save(ModelProfile("draft", "text", provider="仅填厂商"))
    with pytest.raises(ValueError, match="缺少"):
        store.activate("draft")


@pytest.mark.parametrize("url,expected", [
    ("https://model.example", "https://model.example/v1/chat/completions"),
    ("https://model.example/v1/", "https://model.example/v1/chat/completions"),
    ("https://model.example/v1/images/edits", "https://model.example/v1/chat/completions"),
    ("https://model.example/proxy/chat/completions?api-version=1", "https://model.example/proxy/chat/completions?api-version=1"),
    ("https://model.example/chat/completions", "https://model.example/chat/completions"),
])
def test_endpoint_preserves_supplied_api_prefix(url, expected):
    assert endpoint(url, "chat/completions") == expected


def test_text_request_authentication_and_vision_format(monkeypatch, png):
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "test result"}}]})

    real_client = httpx.Client
    transport = httpx.MockTransport(handle)
    monkeypatch.setattr(client_module.httpx, "Client", lambda **options: real_client(transport=transport, **options))
    client = CompatibleClient(profile(supports_vision=True), SimpleNamespace(png=lambda _address: png))
    assert client.complete("facts first", "title request", ["subject"]) == "test result"
    assert requests[0].headers["Authorization"] == "Bearer test-secret-do-not-log"
    body = json.loads(requests[0].content)
    assert body["model"] == "test-model" and body["stream"] is False
    assert body["messages"][1]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert "test-secret-do-not-log" not in requests[0].content.decode()
    with pytest.raises(ValueError, match="图片理解"):
        CompatibleClient(profile(), client.assets).complete("", "", ["subject"])
    assert len(requests) == 1


def test_image_routes_and_joint_reference_images(monkeypatch, png):
    client = CompatibleClient(profile("image", "image-one"), SimpleNamespace(png=lambda _address: png))
    calls = []
    monkeypatch.setattr(client, "_request", lambda route, body=None, **options:
                        calls.append((route, body, options)) or {"data": [{"url": "https://result.example/image.png"}]})
    client.image("scene", [], "1024x1024")
    client.image("scene", ["subject"], "1024x1024")
    client.image("scene", ["subject", "reference"], "1024x1024")
    assert [call[0] for call in calls] == ["images/generations", "images/edits", "chat/completions"]
    assert calls[0][1]["n"] == 1
    assert calls[1][2]["files"][0][0] == "image"
    assert len(calls[2][1]["messages"][0]["content"]) == 3


@pytest.mark.parametrize("status,expected_calls", [(404, 2), (500, 1), (0, 1)])
def test_image_fallback_only_for_explicit_missing_endpoint(monkeypatch, png, status, expected_calls):
    calls = []

    def request(self, route, body=None, **options):
        calls.append(route)
        if route == "images/edits":
            raise ModelCallError("unknown outcome", status)
        return {"data": [{"url": "https://result.example/image.png"}]}

    monkeypatch.setattr(CompatibleClient, "_request", request)
    client = CompatibleClient(profile("image", "image-one"), SimpleNamespace(png=lambda _address: png))
    if status == 404:
        client.image("scene", ["subject"], "1024x1024")
    else:
        with pytest.raises(ModelCallError):
            client.image("scene", ["subject"], "1024x1024")
    assert len(calls) == expected_calls


def test_output_parser_ignores_echoed_input_and_handles_returned_images():
    result = {"request": {"image_url": "https://input.example/subject.png"},
              "choices": [{"message": {"content": "![result](https://result.example/new.png)",
                                         "images": [{"image_url": {"url": "data:image/png;base64,AAAA"}}]}}]}
    assert image_sources(result) == ["data:image/png;base64,AAAA", "https://result.example/new.png"]


def test_partial_image_set_keeps_successful_assets_and_excludes_key(monkeypatch, tmp_path, png):
    store = ModelConfigStore(tmp_path)
    store.save(profile("image", "image-one"))
    store.activate("image-one")
    assets = AssetStore(tmp_path)
    subject = assets.save(png)
    calls = []

    class FakeClient:
        def __init__(self, *_args):
            pass

        def image(self, prompt, references, size):
            calls.append((prompt, references))
            if len(calls) == 2:
                raise ModelCallError("second image failed")
            return {"data": [{"b64_json": base64.b64encode(png).decode()}]}

    monkeypatch.setattr(service_module, "CompatibleClient", FakeClient)
    service = AIService(store, assets)
    request = AIRequest("image_set", {"id": "product-1", "attributes": {"材质": "玻璃"}},
                        subject_images=[subject.uri], slots=["主图", "细节"])
    result = service.generate(request)
    assert len(result.assets) == 1 and len(result.errors) == 1
    assert result.purposes == ["主图"]
    job = service.jobs.list("product-1", "image_set")[0]
    assert job["state"] == "partial"
    assert "test-secret-do-not-log" not in json.dumps(job)
    assert service.restore(job).assets == result.assets
    assert calls[0][1] == [subject.uri]


def test_white_photo_text_uses_subject_and_reference_without_mutating_product(monkeypatch, tmp_path, png):
    store = ModelConfigStore(tmp_path)
    store.save(profile(supports_vision=True))
    store.activate("text-one")
    assets = AssetStore(tmp_path)
    subject = assets.save(png)
    seen = []

    class FakeClient:
        def __init__(self, *_args):
            pass

        def complete(self, system, prompt, images):
            seen.append(images)
            return '{"candidates":["Glass Beads"]}'

    monkeypatch.setattr(service_module, "CompatibleClient", FakeClient)
    product = {"id": "upload-1", "title": "", "attributes": {"材质": "玻璃"}}
    before = json.dumps(product)
    result = AIService(store, assets).generate(AIRequest("title", product, subject_images=[subject.uri],
                                                        reference_images=["https://reference.example/style.png"]))
    assert result.candidates == ["Glass Beads"]
    assert seen == [[subject.uri, "https://reference.example/style.png"]]
    assert json.dumps(product) == before


def test_managed_images_survive_editing_and_are_not_exported_as_file_paths(tmp_path, png):
    assets = AssetStore(tmp_path / "data")
    image = assets.save(png)
    assert local_asset_path(image.uri).read_bytes() == png
    outside = tmp_path / "outside.png"
    outside.write_bytes(png)
    assert local_asset_path(outside.as_uri()) is None
    html = clean_description(f'<p><img src="{image.uri}"></p><img src="{outside.as_uri()}"><script>bad()</script>')
    assert description_images(html) == [image.uri] and "bad()" not in html
    repository = Repository(tmp_path / "data")
    product = repository.create_product(Product(source="upload", title="Beads", currency="USD",
                                                images=[image.uri], skus=[SKU(price="9.90", currency="USD")]))
    product = repository.save_product(product, approve=True)
    assert product.approved
    with pytest.raises(ValueError, match="本地图片"):
        export_products(repository, [product.id], tmp_path / "export.xlsx")
    assert not (tmp_path / "export.xlsx").exists()
    assert repository.captures() == []


def test_public_model_metadata_does_not_leak_query_or_key():
    item = replace(profile(), url="https://model.example/v1?token=private-query")
    public = item.public_dict()
    assert public["url"] == "https://model.example/v1"
    assert "key" not in public and "private-query" not in json.dumps(public)
