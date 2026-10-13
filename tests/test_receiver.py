# 2026-10-11：本次修改原因：为插件连接测试的密钥验证及接收持久化提供用户可运行的回归覆盖。
import json
from http.client import HTTPConnection

from beaddiff.config import Settings
from beaddiff.receiver import LocalReceiver
from beaddiff.service import CaptureService
from beaddiff.storage import Repository


def test_connection_authentication_and_capture_ack(tmp_path):
    repository = Repository(tmp_path)
    # settings = Settings(tmp_path, "test-token-that-is-long-enough", port=0)
    # 2026-10-12：本次修改原因：插件测试显式启用备用路线，新安装默认接口取数。
    settings = Settings(tmp_path, "test-token-that-is-long-enough", port=0, capture_route="plugin")
    changes = []
    receiver = LocalReceiver(settings, CaptureService(repository), lambda: changes.append(True))
    assert receiver.start()
    port = receiver.server.server_address[1]

    def request(method, path, payload=None, token=""):
        connection = HTTPConnection("127.0.0.1", port, timeout=5)
        headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
        try:
            connection.request(method, path, body=json.dumps(payload) if payload else None, headers=headers)
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    try:
        status, body = request("GET", "/api/v1/status", token="wrong")
        assert status == 401
        status, body = request("GET", "/api/v1/status", token=settings.token)
        assert status == 200 and body["service"] == "BeadDiff" and body["ready"]
        assert repository.captures() == []
        capture = {"eventId": "receiver-test", "payload": {"itemId": "TEST", "source": "temu", "site": "US", "pageContent": ""}}
        assert request("POST", "/api/v1/captures", capture, token="wrong")[0] == 401
        assert repository.captures() == []
        status, body = request("POST", "/api/v1/captures", capture, token=settings.token)
        assert status == 200 and body["accepted"] and body["captureId"]
        assert len(repository.captures()) == 1
        assert request("POST", "/api/v1/captures", capture, token=settings.token)[1]["duplicate"]
        # 2026-10-12：本次修改原因：切换路线后拒绝新材料，历史记录保留，停止后仍可重新启用。
        settings.capture_route = "miaoshou"
        status, body = request("POST", "/api/v1/captures", capture, token=settings.token)
        assert status == 503 and "暂停" in body["error"]
        assert len(repository.captures()) == 1
        settings.capture_route = "plugin"
        receiver.stop()
        assert receiver.server is None and receiver.start()
    finally:
        receiver.stop()
