# 2026-10-10：本次修改原因：提供仅绑定本机的采集入口，校验随机密钥并限制请求体大小。
from __future__ import annotations

import hmac
import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable

from .config import Settings
from .service import CaptureService, MAX_CAPTURE_BYTES


class LocalReceiver:
    def __init__(self, settings: Settings, service: CaptureService, on_change: Callable[[], None]):
        self.settings, self.service, self.on_change = settings, service, on_change
        self.server: ThreadingHTTPServer | None = None
        self.error = ""

    def start(self) -> bool:
        # 2026-10-12：本次修改原因：切换路线时防止重复绑定端口。
        if self.server is not None:
            return True
        self.error = ""
        receiver = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "BeadDiff/0.1"

            def setup(self) -> None:
                super().setup()
                self.connection.settimeout(20)

            def log_message(self, format_: str, *args) -> None:
                return

            def reply(self, code: int, body: dict) -> None:
                encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(encoded)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.close_connection = True
                try:
                    self.wfile.write(encoded)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def do_GET(self) -> None:
                if self.path == "/health":
                    self.reply(200, {"service": "BeadDiff", "version": "0.1.0", "ready": True})
                # 2026-10-11：本次修改原因：让扩展验证本机身份和密钥，无需创建虚构采集记录。
                elif self.path == "/api/v1/status":
                    origin = self.headers.get("Origin", "")
                    if origin and not origin.startswith("chrome-extension://"):
                        self.reply(403, {"error": "请从扩展后台测试连接"})
                        return
                    auth = self.headers.get("Authorization", "")
                    if not hmac.compare_digest(auth.encode(), ("Bearer " + receiver.settings.token).encode()):
                        self.reply(401, {"error": "接入密钥不正确"})
                        return
                    self.reply(200, {"service": "BeadDiff", "version": "0.1.0", "ready": True})
                else:
                    self.reply(404, {"error": "接口不存在"})

            def do_POST(self) -> None:
                # 2026-10-12：本次修改原因：切换路线后未处理的扩展请求明确提示暂停。
                if receiver.settings.capture_route != "plugin":
                    self.reply(503, {"error": "插件同步已暂停，请在设置 → 采集路线启用插件同步。"})
                    return
                if self.path != "/api/v1/captures":
                    self.reply(404, {"error": "接口不存在"})
                    return
                origin = self.headers.get("Origin", "")
                if origin and not origin.startswith("chrome-extension://"):
                    self.reply(403, {"error": "请从扩展后台发送采集材料"})
                    return
                auth = self.headers.get("Authorization", "")
                if not hmac.compare_digest(auth.encode(), ("Bearer " + receiver.settings.token).encode()):
                    self.reply(401, {"error": "接入密钥不正确"})
                    return
                if "application/json" not in self.headers.get("Content-Type", ""):
                    self.reply(415, {"error": "仅接收 application/json"})
                    return
                try:
                    size = int(self.headers.get("Content-Length", "0"))
                    if not 0 < size <= MAX_CAPTURE_BYTES or self.headers.get("Transfer-Encoding"):
                        self.reply(413, {"error": "请求必须带 Content-Length，且不得超过 32 MB"})
                        return
                    raw = self.rfile.read(size)
                    if len(raw) != size:
                        self.reply(400, {"error": "请求正文不完整"})
                        return
                    result = receiver.service.ingest(json.loads(raw.decode("utf-8")))
                    self.reply(200, {"accepted": True, **result})
                    receiver.on_change()
                except (ValueError, TypeError, UnicodeError) as error:
                    self.reply(400, {"error": str(error)[:500]})
                except Exception:
                    logging.exception("本地接收异常")
                    self.reply(500, {"error": "本地保存失败，请查看运行日志"})

        try:
            self.server = ThreadingHTTPServer(("127.0.0.1", self.settings.port), Handler)
            self.server.daemon_threads = True
            self.server.block_on_close = False
            threading.Thread(target=self.server.serve_forever, name="BeadDiffReceiver", daemon=True).start()
            return True
        except OSError as error:
            self.error = str(error)
            return False

    def stop(self) -> None:
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            # 2026-10-12：本次修改原因：释放运行状态，允许重新切回插件路线。
            self.server = None
