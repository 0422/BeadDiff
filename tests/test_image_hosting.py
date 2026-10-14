# 2026-10-14：本次修改原因：离线核对 GitHub 图片托管、缓存验证与同步失败阻断，不访问真实仓库。
from io import BytesIO
import hashlib
import json
import sqlite3

import httpx
from PIL import Image
import pytest

from beaddiff.assets import AssetStore
from beaddiff.image_hosting import GitHubImageHosting, ImageHostingConfig, ImageHostingStore


def test_github_hosting_uploads_once_and_revalidates_cached_link(tmp_path, monkeypatch):
    buffer = BytesIO()
    Image.new("RGB", (16, 16), "green").save(buffer, format="PNG")
    asset = AssetStore(tmp_path).save(buffer.getvalue())
    store = ImageHostingStore(tmp_path)
    store.save(ImageHostingConfig(enabled=True, owner="owner", repository="images", token="secret"))
    calls = []
    available = True
    # 2026-10-14：本次修改原因：模拟仓库只读检查及已上传内容，验证失败重试不会重复写入 GitHub。
    uploaded = False
    raw = buffer.getvalue()
    blob_sha = hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw).hexdigest()

    def handler(request):
        nonlocal uploaded
        calls.append((request.method, str(request.url)))
        if request.url.host == "api.github.com":
            if request.url.path == "/repos/owner/images":
                return httpx.Response(200, json={"private": False, "default_branch": "main"})
            if request.url.path == "/repos/owner/images/branches/main":
                return httpx.Response(200, json={"name": "main"})
            if request.method == "GET":
                assert request.url.params["ref"] == "main"
                # return httpx.Response(404)
                return httpx.Response(200, json={"type": "file", "sha": blob_sha}) if uploaded else httpx.Response(404)
            assert request.method == "PUT"
            assert request.headers["Authorization"] == "Bearer secret"
            uploaded = True
            return httpx.Response(201, json={"content": {"sha": "saved"}})
        assert request.url.host == "cdn.jsdelivr.net" and request.method == "HEAD"
        return httpx.Response(200 if available else 404, headers={"content-type": "image/png"})

    real_client = httpx.Client
    monkeypatch.setattr("beaddiff.image_hosting.httpx.Client",
                        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs))
    hosting = GitHubImageHosting(store, AssetStore(tmp_path))
    url = hosting.ensure_public(asset.uri)
    assert url.startswith("https://cdn.jsdelivr.net/gh/owner/images@main/beaddiff-images/")
    assert hosting.ensure_public(asset.uri) == url
    assert sum(method == "PUT" for method, _url in calls) == 1
    assert len(store.records()) == 1
    available = False
    with pytest.raises(ValueError, match="公网链接暂时无法访问"):
        hosting.ensure_public(asset.uri)
    assert sum(method == "PUT" for method, _url in calls) == 1
    assert "secret" not in repr(store.get())
    assert store.records()[0]["status"] == "failed"
    available = True
    assert hosting.ensure_public(asset.uri) == url
    assert store.records()[0]["status"] == "ready"
    assert sum(method == "PUT" for method, _url in calls) == 1


# 2026-10-14：本次修改原因：空仓库分支 404 是正常初始化状态，测试不写文件，首传省略未创建的 branch。
def test_empty_repository_initializes_only_on_first_upload(tmp_path, monkeypatch):
    buffer = BytesIO()
    Image.new("RGB", (16, 16), "blue").save(buffer, format="PNG")
    assets = AssetStore(tmp_path)
    asset = assets.save(buffer.getvalue())
    store = ImageHostingStore(tmp_path)
    store.save(ImageHostingConfig(enabled=True, owner="owner", repository="images", token="test-token"))
    writes = []

    def handler(request):
        if request.url.host == "cdn.jsdelivr.net":
            return httpx.Response(200, headers={"content-type": "image/png"})
        if request.url.path == "/repos/owner/images":
            return httpx.Response(200, json={"private": False, "default_branch": "main"})
        if request.url.path.endswith("/branches/main"):
            return httpx.Response(404, json={"message": "Branch not found"})
        if request.url.path.endswith("/branches"):
            return httpx.Response(200, json=[])
        if request.method == "GET":
            return httpx.Response(404)
        writes.append(json.loads(request.content))
        assert "branch" not in writes[-1]
        return httpx.Response(201, json={"content": {"sha": "saved"}})

    real_client = httpx.Client
    monkeypatch.setattr("beaddiff.image_hosting.httpx.Client",
                        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs))
    hosting = GitHubImageHosting(store, assets)
    assert "尚无提交" in hosting.test_connection()
    assert not writes and not store.cache_path.exists()
    assert hosting.ensure_public(asset.uri).startswith("https://cdn.jsdelivr.net/")
    assert len(writes) == 1 and not hosting._empty_repository


# 2026-10-14：本次修改原因：已有其他分支的仓库不可当作空仓库初始化，错误分支应保留明确提示。
def test_existing_repository_rejects_missing_branch(tmp_path, monkeypatch):
    store = ImageHostingStore(tmp_path)
    store.save(ImageHostingConfig(enabled=True, owner="owner", repository="images", token="test-token"))
    def handler(request):
        assert request.method == "GET"
        if request.url.path == "/repos/owner/images":
            return httpx.Response(200, json={"private": False, "default_branch": "master"})
        if request.url.path.endswith("/branches/main"):
            return httpx.Response(404)
        return httpx.Response(200, json=[{"name": "master"}])
    real_client = httpx.Client
    monkeypatch.setattr("beaddiff.image_hosting.httpx.Client",
                        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs))
    with pytest.raises(ValueError, match="main 不存在"):
        GitHubImageHosting(store, AssetStore(tmp_path)).test_connection()


# 2026-10-14：本次修改原因：损坏配置可备份重建；启用配置缺项仍可读回设置页修复。
def test_hosting_config_recovers_and_preserves_incomplete_fields(tmp_path):
    store = ImageHostingStore(tmp_path)
    store.path.write_text('{"enabled":true,"owner":"owner","repository":"images"}', encoding="utf-8")
    assert store.reload() and store.config.owner == "owner"
    assert store.config.problems()
    store.path.write_text("invalid-json", encoding="utf-8")
    assert not store.reload()
    backup = store.recover(ImageHostingConfig())
    assert backup.read_text(encoding="utf-8") == "invalid-json"
    assert not store.error and ImageHostingStore(tmp_path).get() == ImageHostingConfig()
    assert ImageHostingConfig(enabled=False, owner=None).problems()


# 2026-10-14：本次修改原因：旧版缓存升级后仍保留已托管链接，并支持新增失败原因。
def test_legacy_cache_migrates_failure_status(tmp_path):
    store = ImageHostingStore(tmp_path)
    with sqlite3.connect(store.cache_path) as connection:
        connection.execute("CREATE TABLE image_hosts (source_hash TEXT, source_uri TEXT, provider_key TEXT, public_url TEXT, status TEXT, updated_at TEXT, PRIMARY KEY(source_hash, provider_key))")
        connection.execute("INSERT INTO image_hosts VALUES ('hash', 'file:///old.png', 'github:old', 'https://example.com/old.png', 'ready', '2026-10-14')")
    store.cache_put("new-hash", "file:///new.png", "github:new", "https://example.com/new.png", status="failed", last_error="连接失败")
    assert store.cache_get("hash", "github:old") == "https://example.com/old.png"
    assert any(row["last_error"] == "连接失败" for row in store.records())


# 2026-10-14：本次修改原因：网络诊断保留错误类型，并排除原始异常中可能包含的凭证。
@pytest.mark.parametrize("kind,caption", [(httpx.ConnectTimeout, "连接超时"), (httpx.ProxyError, "代理连接失败")])
def test_hosting_network_diagnostic_redacts_original_error(kind, caption, monkeypatch):
    monkeypatch.setattr("beaddiff.image_hosting.getproxies", lambda: {})
    message = GitHubImageHosting._network_failure(kind("sensitive-token"), "GitHub 连接检查", 30)
    assert caption in message and kind.__name__ in message and "sensitive-token" not in message


# 2026-10-14：本次修改原因：离屏初始化配置与管理页，避免新增导航打开时因控件或信号签名错误卡住。
def test_hosting_pages_initialize_offscreen(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    # 2026-10-14：本次修改原因：实际点击保存按钮并展示失败记录，核对信号参数及状态渲染。
    from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton
    from beaddiff.ui.ai_runner import TaskHub
    from beaddiff.ui.image_hosting import ImageHostingConfigPage, ImageHostingPage

    app = QApplication.instance() or QApplication([])
    store = ImageHostingStore(tmp_path)
    hosting = GitHubImageHosting(store, AssetStore(tmp_path))
    hub = TaskHub()
    settings = ImageHostingConfigPage(store, hosting, hub)
    page = ImageHostingPage(store, hosting, hub)
    page.refresh()
    assert settings.test_button.isEnabled() and page.table.rowCount() == 0
    messages = []
    monkeypatch.setattr(QMessageBox, "information", lambda *_args: messages.append(True))
    monkeypatch.setattr(QMessageBox, "warning", lambda *_args: pytest.fail("保存按钮不应出现错误"))
    save_button = next(item for item in settings.findChildren(QPushButton) if item.text() == "保存配置")
    save_button.click()
    assert messages and store.path.exists()
    store.cache_put("hash", "file:///missing.png", "github:test", "https://example.com/missing.png", status="failed", last_error="公网验证失败")
    page.refresh()
    assert page.table.rowCount() == 1 and page.table.item(0, 3).text() == "失败"
    settings.close()
    page.close()


# 2026-10-14：本次修改原因：代理网页和坏分支 JSON 不得误判为空仓库，测试连接全程不写远端。
@pytest.mark.parametrize('body', [b'<html>proxy error</html>', b'{}', b'[{}]', b'null'])
def test_bad_branch_response_never_initializes_empty_repository(tmp_path, monkeypatch, body):
    store = ImageHostingStore(tmp_path)
    store.save(ImageHostingConfig(enabled=True, owner='owner', repository='images', token='fake-token'))
    writes = []
    def handler(request):
        if request.method != 'GET':
            writes.append(request)
            pytest.fail('Connection checks must not write')
        if request.url.path == '/repos/owner/images':
            return httpx.Response(200, json={'private': False, 'default_branch': 'main'})
        if request.url.path.endswith('/branches/main'):
            return httpx.Response(404)
        return httpx.Response(200, content=body)
    real_client = httpx.Client
    monkeypatch.setattr('beaddiff.image_hosting.httpx.Client',
                        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs))
    with pytest.raises(ValueError, match='GitHub 分支列表响应'):
        GitHubImageHosting(store, AssetStore(tmp_path)).test_connection()
    assert not writes
