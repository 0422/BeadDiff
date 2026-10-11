# 2026-10-11：本次修改原因：接通官方公共采集箱 API，按原始 JSON 字节签名，明确区分未提交、拒绝及结果未知。
from __future__ import annotations

from copy import deepcopy
import hashlib
import hmac
import json
import time
# 2026-10-11：本次修改原因：HTML 图片链接可能带转义的查询参数，替换时须先解码再转义。
from html import escape, unescape

import httpx

from .erp import ERPNotSentError, ERPReceipt, ERPRejectedError, ERPRequest, ERPUncertainError
from .miaoshou_config import API_BASE, MiaoshouConfig, MiaoshouConfigStore
from .miaoshou_mapping import create_payload, edited_fields, picture_urls, update_payload, validate_payload
from .models import Product, valid_url


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
            with httpx.Client(timeout=self.config.timeout, transport=self.transport, follow_redirects=False) as client:
                # response = client.post(API_BASE + path, headers=headers, content=body.encode("utf-8"))
                # 2026-10-11：本次修改原因：直接复用预先校验的 UTF-8 字节，不再次编码或序列化。
                response = client.post(API_BASE + path, headers=headers, content=body_bytes)
        except httpx.HTTPError as error:
            # 网络异常可能在请求到达服务器以后发生，不自动重试商品保存。
            if saving_product:
                raise ERPUncertainError("保存请求出现网络异常/超时，结果未知。请先到妙手核对，避免重复新增。", context) from None
            raise ERPNotSentError("妙手查询或图片准备失败：网络异常/超时；商品尚未提交。", context) from error
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
        if not saving_product:
            raise ERPNotSentError(reason + "；商品尚未提交。", context)
        if data.get("result") == "fail" and code in REJECT_CODES:
            raise ERPRejectedError(reason, context)
        raise ERPUncertainError(reason + "；保存结果尚不能确认，请先在妙手核对，禁止自动重试新增。", context)

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

    @property
    def unavailable_reason(self) -> str:
        if self.store.error:
            return self.store.error
        return "；".join(self.store.get().problems())

    def client(self) -> MiaoshouClient:
        return MiaoshouClient(self.store.get(), self.transport)

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
        try:
            if request.mode == "update":
                detail = client.detail(request.original_id)
                remote = detail["editCommonCollectBoxDetail"]
                payload, links = update_payload(product, remote, client.config)
            elif request.mode == "create":
                payload = create_payload(product, client.config)
            else:
                raise ValueError("回传方式无效。")
            old_pictures = set(picture_urls(remote))
            replacements = {url: client.upload_picture(url) for url in picture_urls(payload) if url not in old_pictures}
            payload = _replace_pictures(deepcopy(payload), replacements)
            validate_payload(payload)
        except ValueError as error:
            raise ERPNotSentError(str(error)) from None
        if request.mode == "create":
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
