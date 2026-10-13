# 2026-10-11：本次修改原因：接通官方公共采集箱 API，按原始 JSON 字节签名，明确区分未提交、拒绝及结果未知。
from __future__ import annotations

from copy import deepcopy
import hashlib
import hmac
import json
import time
# 2026-10-12：本次修改原因：批量只读同步复用连接池，减少逐商品 DNS/TLS 握手开销。
from contextlib import contextmanager
# 2026-10-11：本次修改原因：HTML 图片链接可能带转义的查询参数，替换时须先解码再转义。
from html import escape, unescape
# 2026-10-12：本次修改原因：记录网络异常类型和代理是否配置，不输出代理地址、凭证或异常中的请求正文。
import sqlite3
from urllib.request import getproxies

import httpx

from .erp import ERPNotSentError, ERPReceipt, ERPRejectedError, ERPRequest, ERPUncertainError
from .miaoshou_config import API_BASE, MiaoshouConfig, MiaoshouConfigStore
from .miaoshou_mapping import create_payload, edited_fields, picture_urls, update_payload, validate_payload
from .models import Product, valid_url
# 2026-10-12：本次修改原因：接入独立图片缓存，成功的每张图立即落库，不依赖整条商品回传成功。
from .miaoshou_picture_cache import MiaoshouPictureCache


PUBLIC_PATH = "/open/v1/product/common_collect_box/common_collect_box/"
LIST_PATH = PUBLIC_PATH + "get_common_collect_box_list"
DETAIL_PATH = PUBLIC_PATH + "get_common_collect_box_detail"
CREATE_PATH = PUBLIC_PATH + "add_common_collect_box_detail"
UPDATE_PATH = PUBLIC_PATH + "edit_common_collect_box_detail"
PICTURE_PATH = "/open/v1/product/picture/picture_space/upload_picture_link"
ERROR_HELP = {
    "appNotFound": "AppKey 无效或应用尚未获批。", "signMissing": "签名缺失。",
    "signExpired": "签名已过期，请检查电脑时间是否准确。", "signInvalid": "签名无效，请核对 AppKey/AppSecret。",
    "appNoPermission": "当前应用没有该接口权限，请向妙手申请公共采集箱权限。",
    "ipNotInWhitelist": "当前出口 IP 不在妙手开放平台白名单。",
}
REJECT_CODES = frozenset(ERROR_HELP) | {
    "paramInvalid", "parameterInvalid", "invalidParam", "paramError", "parameterError", "validationError",
    "tooManyRequests", "rateLimitExceeded", "appRateLimitExceeded", "apiRateLimitExceeded",
    "requestLimitExceeded", "productNotFound", "commonCollectBoxDetailNotFound",
}


def detail_id(value: str | int) -> int:
    text = str(value).strip()
    if not text.isascii() or not text.isdecimal() or not 0 < int(text) < 2**63:
        raise ValueError("请填写妙手公共采集箱商品的正整数 ID，不是 Temu 商品 ID。")
    return int(text)


class MiaoshouClient:
    def __init__(self, config: MiaoshouConfig, transport: httpx.BaseTransport | None = None):
        self.config = config
        self.transport = transport
        # 2026-10-12：本次修改原因：批量只读会话只用于查询，商品写回保持独立请求及原结果判定。
        self._read_http = None

    # 2026-10-12：本次修改原因：HTTPX 连接池可供有限数量的读取线程复用，批次结束保证释放资源。
    @contextmanager
    def read_session(self):
        if self._read_http is not None:
            raise RuntimeError("该客户端已有读取批次正在运行。")
        with httpx.Client(timeout=self.config.timeout, transport=self.transport, follow_redirects=False,
                          limits=httpx.Limits(max_connections=3, max_keepalive_connections=3)) as session:
            self._read_http = session
            try:
                yield
            finally:
                self._read_http = None

    def _safe(self, value):
        if isinstance(value, dict):
            return {str(key): self._safe(item) for key, item in value.items()
                    if str(key).lower() not in {"appsecret", "app_secret", "appkey", "app_key", "x-sign", "x-app-key", "authorization"}}
        if isinstance(value, list):
            return [self._safe(item) for item in value]
        if isinstance(value, str):
            for secret in (self.config.app_secret, self.config.app_key):
                if secret:
                    value = value.replace(secret, "[凭证已隐藏]")
        return value

    def call(self, path: str, payload: dict, saving_product: bool = False) -> dict:
        errors = self.config.problems()
        if errors:
            raise ERPNotSentError("；".join(errors))
        if path not in {LIST_PATH, DETAIL_PATH, CREATE_PATH, UPDATE_PATH, PICTURE_PATH}:
            raise ERPNotSentError("请求路径不属于已适配的官方接口。")
        timestamp = str(int(time.time()))
        # 同一份 UTF-8 JSON 同时用于签名和发送，不交给 httpx 再次序列化。
        # body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        # 2026-10-11：本次修改原因：无法序列化的内容在调用接口前停止，不误记为可能已保存。
        try:
            body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
            body_bytes = body.encode("utf-8")
        except (ValueError, TypeError, UnicodeEncodeError):
            raise ERPNotSentError("提交内容包含非法数值或字符，商品尚未提交。") from None
        secret = self.config.app_secret
        message = secret + path + timestamp + self.config.app_key + body + secret
        signature = hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()
        headers = {"Content-Type": "application/json", "x-app-key": self.config.app_key,
                   "x-timestamp": timestamp, "x-sign": signature}
        context = {"endpoint": path, "account_id": self.config.account_id}
        # 2026-10-11：本次修改原因：未知结果保存实际提交内容，以便之后只读核对，避免人工随意标成已传。
        if saving_product:
            context["submitted"] = self._safe(payload)
        try:
            # with httpx.Client(timeout=self.config.timeout, transport=self.transport, follow_redirects=False) as client:
            #     response = client.post(API_BASE + path, headers=headers, content=body_bytes)
            # 2026-10-12：本次修改原因：仅列表/详情读取使用批次连接池，绝不并发复用商品保存流程。
            if self._read_http is not None and path in {LIST_PATH, DETAIL_PATH}:
                response = self._read_http.post(API_BASE + path, headers=headers, content=body_bytes)
            else:
                with httpx.Client(timeout=self.config.timeout, transport=self.transport, follow_redirects=False) as client:
                    response = client.post(API_BASE + path, headers=headers, content=body_bytes)
        except httpx.HTTPError as error:
            # 网络异常可能在请求到达服务器以后发生，不自动重试商品保存。
            # 2026-10-12：本次修改原因：区分连接/响应超时、代理失败和连接失败，保留脱敏诊断以判断 VPN 是否相关。
            description = self._network_error(error, context)
            if saving_product:
                # raise ERPUncertainError("保存请求出现网络异常/超时，结果未知。请先到妙手核对，避免重复新增。", context) from None
                # 2026-10-12：本次修改原因：补充具体异常而仍保留商品保存结果未知，禁止自动新增重试。
                raise ERPUncertainError("保存请求出现网络异常/超时：" + description + "；结果未知，请先到妙手核对，避免重复新增。", context) from None
            # raise ERPNotSentError("妙手查询或图片准备失败：网络异常/超时；商品尚未提交。", context) from error
            # 2026-10-12：本次修改原因：图片超时不代表商品提交，亦不把未收到的图片结果误记为缓存成功。
            stage = "图片上传" if path == PICTURE_PATH else "查询"
            reason = f"妙手{stage}失败：{description}；商品尚未提交。"
            if path == PICTURE_PATH and isinstance(error, httpx.TimeoutException):
                reason += "妙手可能仍在转存该图片，请先核对图片空间；本次未收到其上传成功回执。"
            raise ERPNotSentError(reason, context) from None
        try:
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError
        except ValueError:
            error_type = ERPUncertainError if saving_product else ERPNotSentError
            raise error_type(f"妙手返回无法识别的响应（HTTP {response.status_code}）；" +
                             ("保存结果未知，请在妙手核对。" if saving_product else "商品尚未提交。"), context) from None
        context.update(http_status=response.status_code, response=self._safe(data))
        if response.is_success and data.get("result") == "success" and data.get("code") == "success":
            return data
        code = str(data.get("code", "unknown"))
        message = str(self._safe(str(data.get("message") or "未返回具体原因")))[:1200]
        reason = f"妙手接口 {code}（HTTP {response.status_code}）：{ERROR_HELP.get(code, message)}"
        # 2026-10-12：本次修改原因：图片空间容量不足属于服务器业务拒绝，给出可操作的容量处理提示，不能当成 VPN 超时。
        if path == PICTURE_PATH and data.get("result") == "fail" and "图片空间容量不足" in message:
            reason += "；请在妙手查看图片空间可用容量，清理未使用图片或扩容后重试"
            context["failure_reason"] = "picture_space_capacity"
        if not saving_product:
            raise ERPNotSentError(reason + "；商品尚未提交。", context)
        if data.get("result") == "fail" and code in REJECT_CODES:
            raise ERPRejectedError(reason, context)
        raise ERPUncertainError(reason + "；保存结果尚不能确认，请先在妙手核对，禁止自动重试新增。", context)

    # 2026-10-12：本次修改原因：网络诊断只记录异常类、超时和代理配置存在性，不泄露原始异常消息中的密钥/代理信息。
    def _network_error(self, error: httpx.HTTPError, context: dict) -> str:
        proxy_configured = None
        try:
            proxies = getproxies() if self.transport is None else {}
            proxy_configured = any(proxies.get(scheme) for scheme in ("https", "all"))
        except OSError:
            pass
        context["network_error"] = {"type": type(error).__name__, "timeout_seconds": self.config.timeout,
                                    "proxy_configured": proxy_configured}
        descriptions = (
            (httpx.ConnectTimeout, "连接妙手超时"),
            (httpx.ReadTimeout, "等待妙手响应超时"),
            (httpx.WriteTimeout, "发送请求超时"),
            (httpx.PoolTimeout, "等待可用连接超时"),
            (httpx.ProxyError, "代理连接失败"),
            (httpx.ConnectError, "连接建立失败，可能涉及 DNS、TLS 或网络连接"),
        )
        description = next((text for kind, text in descriptions if isinstance(error, kind)), "网络传输异常")
        description += f"（{type(error).__name__}，配置超时 {self.config.timeout} 秒）"
        if isinstance(error, httpx.ReadTimeout):
            description += "，可在设置 → 妙手回传调高请求超时并保存"
        if proxy_configured or isinstance(error, httpx.ProxyError):
            description += "，请检查系统/环境代理及 VPN，也可在关闭代理后对比只读连接测试"
        return description

    def list_products(self, source_id: str = "", page: int = 1, size: int = 100) -> dict:
        if not 1 <= size <= 500 or page < 1:
            raise ValueError("查询分页参数无效。")
        filter_values = {"tabPaneName": "all"}
        if source_id.strip():
            filter_values["sourceItemIdKeyword"] = source_id.strip()
        data = self.call(LIST_PATH, {"pageNo": page, "pageSize": size, "filter": filter_values}).get("data")
        if not isinstance(data, dict) or not isinstance(data.get("detailList"), list):
            raise ERPNotSentError("妙手列表响应缺少 detailList；商品尚未提交。")
        return data

    def detail(self, target_id: str | int) -> dict:
        target = detail_id(target_id)
        data = self.call(DETAIL_PATH, {"commonCollectBoxDetailId": target}).get("data")
        if not isinstance(data, dict) or not isinstance(data.get("editCommonCollectBoxDetail"), dict):
            raise ERPNotSentError("妙手详情响应不完整；商品尚未提交。")
        remote = data["editCommonCollectBoxDetail"]
        try:
            actual = detail_id(remote.get("commonCollectBoxDetailId", ""))
        except ValueError:
            raise ERPNotSentError("详情响应没有可核实的公共采集箱商品 ID。") from None
        if actual != target or not isinstance(data.get("ossMd5"), str) or not data["ossMd5"]:
            raise ERPNotSentError("详情商品 ID 不一致或缺少必需 ossMd5，已停止更新。")
        return data

    def upload_picture(self, url: str) -> str:
        if not valid_url(url):
            raise ERPNotSentError("图片上传接口只支持网络链接；请先托管本机图片。")
        data = self.call(PICTURE_PATH, {"imgUrl": url, "scene": "product"}).get("data")
        address = data.get("picturePath", "") if isinstance(data, dict) else ""
        if not isinstance(address, str) or not valid_url(address):
            raise ERPNotSentError("妙手图片接口未返回可访问的 picturePath；商品尚未提交。")
        return address


def _replace_pictures(value, replacements: dict[str, str], key: str = ""):
    if isinstance(value, dict):
        return {name: _replace_pictures(item, replacements, name) for name, item in value.items()}
    if isinstance(value, list):
        return [_replace_pictures(item, replacements, key) for item in value]
    if isinstance(value, str):
        if key in {"imgUrl", "imgUrls", "sizeChart"}:
            return replacements.get(value, value)
        if key == "notes":
            # 只替换 HTML 图片属性中的链接，正文里相同文本保留。
            import re
            return re.sub(r'(<img\b[^>]*\bsrc\s*=\s*["\x27])([^"\x27]+)(["\x27])',
                          # lambda match: match[1] + replacements.get(match[2], match[2]) + match[3], value, flags=re.I)
                          # 2026-10-11：本次修改原因：保留未替换属性原文，正确处理 URL 中的 &amp;。
                          lambda match: match[1] + (escape(replacements[unescape(match[2])], quote=True)
                                                    if unescape(match[2]) in replacements else match[2]) + match[3], value, flags=re.I)
    return value


# 2026-10-11：本次修改原因：核对只要求已提交字段一致，允许服务器补充默认字段；规格集合及列表顺序仍须相同。
def _matches_submitted(actual, expected, key: str = "") -> bool:
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return False
        if key in {"skuMap", "colorMap", "sizeMap", "saleProp3Map"} and set(actual) != set(expected):
            return False
        return all(name in actual and _matches_submitted(actual[name], value, name) for name, value in expected.items())
    if isinstance(expected, list):
        return isinstance(actual, list) and len(actual) == len(expected) and all(
            _matches_submitted(left, right, key) for left, right in zip(actual, expected))
    return actual == expected


class MiaoshouAdapter:
    def __init__(self, store: MiaoshouConfigStore, transport: httpx.BaseTransport | None = None):
        self.store = store
        self.transport = transport
        # 2026-10-12：本次修改原因：缓存跟随当前数据目录，初始化不创建文件或更改商品记录。
        self.picture_cache = MiaoshouPictureCache(store.path.parent)

    @property
    def unavailable_reason(self) -> str:
        if self.store.error:
            return self.store.error
        return "；".join(self.store.get().problems())

    def client(self) -> MiaoshouClient:
        return MiaoshouClient(self.store.get(), self.transport)

    # 2026-10-12：本次修改原因：逐张读取/保存账号隔离的成功缓存，后续图片失败或应用重启不丢失已经取得的上传回执。
    # def _prepare_pictures(self, client: MiaoshouClient, payload: dict, remote: dict) -> tuple[dict, dict]:
    # 2026-10-12：本次修改原因：图片转存及缓存复用按实际图片序号报告阶段。
    def _prepare_pictures(self, client: MiaoshouClient, payload: dict, remote: dict, notify=None) -> tuple[dict, dict]:
        urls = picture_urls(payload)
        old_pictures = set(picture_urls(remote))
        progress = {"total": len(urls), "uploaded": 0, "cache_saved": 0, "cache_reused": 0, "remote_reused": 0}
        replacements = {}
        try:
            for index, url in enumerate(urls, 1):
                # 2026-10-12：本次修改原因：界面可区分图片准备与商品提交，避免长等待没有反馈。
                if notify:
                    notify(f"准备图片 {index}/{len(urls)}")
                if url in old_pictures:
                    progress["remote_reused"] += 1
                    continue
                try:
                    # 2026-10-12：本次修改原因：同一应用并发任务的查缓存/上传/写缓存串行处理，避免相同图片同时重复转存。
                    with self.picture_cache.lock:
                        cached = self.picture_cache.get(client.config.account_id, url)
                        if cached:
                            replacements[url] = cached
                            progress["cache_reused"] += 1
                            continue
                        address = client.upload_picture(url)
                        progress["uploaded"] += 1
                        self.picture_cache.put(client.config.account_id, url, address)
                        progress["cache_saved"] += 1
                        replacements[url] = address
                except (OSError, sqlite3.Error, ValueError) as error:
                    operation = "已成功上传图片，但缓存保存失败" if progress["uploaded"] > progress["cache_saved"] else "读取图片上传缓存失败"
                    raise ERPNotSentError(operation + "；请检查数据目录权限和缓存文件，商品尚未提交。", {
                        "endpoint": PICTURE_PATH, "account_id": client.config.account_id,
                        "cache_error_type": type(error).__name__,
                    }) from None
        except ERPNotSentError as error:
            details = {**error.details, "picture_progress": {**progress, "failed_index": index}}
            summary = (f"图片进度：本次上传 {progress['uploaded']} 张，已保存缓存 {progress['cache_saved']} 张，"
                       f"复用缓存 {progress['cache_reused']} 张，复用远端 {progress['remote_reused']} 张（共 {progress['total']} 张）。")
            raise ERPNotSentError(str(error) + "\n" + summary + "已保存的缓存会在再次回传时复用。", details) from None
        return _replace_pictures(deepcopy(payload), replacements), progress

    # 2026-10-12：本次修改原因：在远端图片已删除或原链接内容改变时，允许用户仅清除当前已保存账号的本地映射。
    def clear_picture_cache(self, account_id: str) -> int:
        if not account_id or self.store.get().account_id != account_id:
            raise ValueError("已保存的 AppKey 已变化，请重新确认当前账号后清除缓存。")
        try:
            return self.picture_cache.clear(account_id)
        except (OSError, sqlite3.Error) as error:
            raise ValueError("清除本地图片缓存失败，请检查缓存文件和数据目录权限。") from error

    def validate(self, product: Product, mode: str) -> list[str]:
        if self.unavailable_reason:
            return [self.unavailable_reason]
        config = self.store.get()
        fields = edited_fields(product)
        if fields & {"category", "body_size_chart"}:
            return ["公共采集箱 API 不支持已修改的类目/身体尺码表；请先在妙手处理这些字段。"]
        if mode == "update":
            if product.erp_original_account != config.account_id:
                return ["原商品尚未关联当前 AppKey 对应账号，请点击“关联妙手原商品”重新查询确认。"]
            return []
        try:
            create_payload(product, config)
        except ValueError as error:
            return [str(error)]
        return []

    def send(self, request: ERPRequest) -> ERPReceipt:
        errors = self.validate(request.product, request.mode)
        if errors:
            raise ERPNotSentError("；".join(errors))
        client = self.client()
        product = request.product
        remote = {}
        links = {}
        # 2026-10-12：本次修改原因：成功回执也记录图片上传/复用数量，便于用户核对缓存是否生效。
        picture_progress = {}
        try:
            if request.mode == "update":
                # 2026-10-12：本次修改原因：更新先读最新原商品，阶段提示与实际请求保持一致。
                if request.progress:
                    request.progress("读取妙手原商品")
                detail = client.detail(request.original_id)
                remote = detail["editCommonCollectBoxDetail"]
                payload, links = update_payload(product, remote, client.config)
            elif request.mode == "create":
                payload = create_payload(product, client.config)
                # 2026-10-12：本次修改原因：同账号 API 商品副本直接复用原详情中已存入妙手的图片，新增图片仍经过上传。
                if product.erp_imported:
                    remote = product.erp_remote_snapshot
            else:
                raise ValueError("回传方式无效。")
            # old_pictures = set(picture_urls(remote))
            # replacements = {url: client.upload_picture(url) for url in picture_urls(payload) if url not in old_pictures}
            # payload = _replace_pictures(deepcopy(payload), replacements)
            # 2026-10-12：本次修改原因：替换一次性上传推导式；每张成功图立即缓存，失败后的重试保留已有进度。
            # payload, picture_progress = self._prepare_pictures(client, payload, remote)
            # 2026-10-12：本次修改原因：向任务界面报告图片阶段，失败和缓存逻辑保持原契约。
            payload, picture_progress = self._prepare_pictures(client, payload, remote, request.progress)
            validate_payload(payload)
        except ValueError as error:
            raise ERPNotSentError(str(error)) from None
        if request.mode == "create":
            # 2026-10-12：本次修改原因：仅准备及校验完成后显示商品提交阶段。
            if request.progress:
                request.progress("提交新增商品至公共采集箱")
            response = client.call(CREATE_PATH, payload, saving_product=True)
            data = response.get("data")
            try:
                target = str(detail_id(data.get("commonCollectBoxDetailId", "") if isinstance(data, dict) else ""))
            except ValueError:
                raise ERPUncertainError("妙手报告成功但未返回新商品 ID，请到公共采集箱核对，避免重复新增。",
                                        # {"endpoint": CREATE_PATH, "response": client._safe(response)}) from None
                                        # 2026-10-11：本次修改原因：保留实际提交内容及账号，支持只读核对未知结果。
                                        {"endpoint": CREATE_PATH, "response": client._safe(response),
                                         "account_id": client.config.account_id, "submitted": client._safe(payload)}) from None
            acknowledgment = target
        else:
            target = str(detail_id(request.original_id))
            body = {"commonCollectBoxDetailId": int(target), "editCommonCollectBoxDetail": payload, "ossMd5": detail["ossMd5"]}
            # 2026-10-12：本次修改原因：明确更新原商品的实际提交阶段。
            if request.progress:
                request.progress("提交更新商品至公共采集箱")
            response = client.call(UPDATE_PATH, body, saving_product=True)
            data = response.get("data")
            acknowledgment = data.get("ossMd5", "") if isinstance(data, dict) else ""
            if not isinstance(acknowledgment, str) or not acknowledgment:
                raise ERPUncertainError("妙手报告成功但缺少更新响应 ossMd5，请到公共采集箱核对。",
                                        # {"endpoint": UPDATE_PATH, "response": client._safe(response)})
                                        # 2026-10-11：本次修改原因：缺失更新回执时保留可核对的实际提交内容。
                                        {"endpoint": UPDATE_PATH, "response": client._safe(response),
                                         "account_id": client.config.account_id, "submitted": client._safe(body)})
        warnings = []
        if product.category:
            warnings.append("来源类目仅在本机保留；该公共采集箱接口没有可写类目字段。")
        if product.body_size_chart:
            warnings.append("来源身体尺码表仅在本机保留；该公共采集箱接口没有对应字段。")
        details = {"endpoint": CREATE_PATH if request.mode == "create" else UPDATE_PATH,
                   "account_id": client.config.account_id, "response": client._safe(response),
                   "sku_links": links, "warnings": warnings}
        # 2026-10-12：本次修改原因：回传记录展示图片缓存复用进度，不保存原图链接或任何 API 凭证。
        details["picture_progress"] = picture_progress
        return ERPReceipt(request.mode, target, acknowledgment, details)

    # 2026-10-11：本次修改原因：未知保存结果只能在真实详情与已提交字段完全一致后确认成功，不提供强行解锁重发。
    def reconcile(self, record: dict, target_id: str) -> ERPReceipt:
        receipt = json.loads(record["receipt"])
        client = self.client()
        if receipt.get("account_id") != client.config.account_id:
            raise ERPNotSentError("核对必须使用原发送账号的 AppKey。")
        submitted = receipt.get("submitted")
        if not isinstance(submitted, dict):
            raise ERPNotSentError("此旧记录未保存可核对的实际提交内容，不能自动确认；请保留记录并人工核查。")
        target = str(detail_id(target_id))
        if record["mode"] == "update":
            if str(submitted.get("commonCollectBoxDetailId", "")) != target:
                raise ERPNotSentError("更新核对的目标必须是当时提交的原商品 ID。")
            expected = submitted.get("editCommonCollectBoxDetail")
        else:
            expected = submitted
        if not isinstance(expected, dict) or not expected:
            raise ERPNotSentError("没有可信的提交字段，不能确认保存结果。")
        detail = client.detail(target)
        actual = detail["editCommonCollectBoxDetail"]
        # differences = [key for key, value in expected.items() if actual.get(key) != value]
        # 2026-10-11：本次修改原因：不能因服务端新增只读/默认信息误判保存失败，同时逐字段比较请求中明确提交的值。
        differences = [key for key, value in expected.items() if key not in actual or not _matches_submitted(actual[key], value, key)]
        if differences:
            raise ERPNotSentError("远端数据与实际提交内容未完全一致，记录仍为结果未知。差异字段：" + "、".join(differences[:12]))
        snapshot = Product.from_dict(json.loads(record["snapshot"]))
        return ERPReceipt(record["mode"], target, detail["ossMd5"], {
            "endpoint": DETAIL_PATH, "account_id": client.config.account_id, "reconciled": True,
            "response": client._safe({"result": "success", "code": "success", "data": detail}),
            "sku_links": snapshot.erp_sku_links,
        })
