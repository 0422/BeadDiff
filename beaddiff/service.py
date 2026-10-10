# 2026-10-10：本次修改原因：统一文件导入和本机接收流程，先保存原始材料，再解析为可编辑商品。
from __future__ import annotations

import json
import threading
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .parsing import parse_capture
from .storage import Repository


MAX_CAPTURE_BYTES = 32 * 1024 * 1024


def normalize_envelope(value: dict) -> dict:
    if not isinstance(value, dict):
        raise ValueError("采集材料必须是 JSON 对象。")
    payload = value.get("payload", value)
    if not isinstance(payload, dict):
        raise ValueError("payload 必须是对象。")
    if not any(key in payload for key in ("pageContent", "rawData", "itemId")):
        raise ValueError("未发现 pageContent / rawData / itemId；请导入 pfti 的请求材料。")
    # 只接收业务材料，不收集 HAR 中的 Cookie、Authorization 等请求头。
    result = {"payload": payload, "requestUrl": str(value.get("requestUrl", ""))}
    if value.get("eventId"):
        result["eventId"] = str(value["eventId"])[:200]
    return result


def envelopes_from_file(path: Path) -> list[dict]:
    if path.stat().st_size > MAX_CAPTURE_BYTES:
        raise ValueError("文件超过 32 MB，请只保留该商品的 pfti 请求。")
    content = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() in {".html", ".htm"}:
        raise ValueError("仅有 HTML 无法可靠确认 itemId 和站点，请包装为含 itemId/source/site/pageContent 的 JSON。")
    try:
        data = json.loads(content)
    except ValueError:
        values = parse_qs(content.strip(), keep_blank_values=True)
        if "pageContent" not in values:
            raise ValueError("文件不是有效 JSON、HAR 或 URL 编码的 pfti 表单文本。") from None
        return [normalize_envelope({key: value[0] for key, value in values.items()})]
    if isinstance(data, dict) and isinstance(data.get("log"), dict):
        result = []
        for entry in data["log"].get("entries", []):
            request = entry.get("request", {})
            if not urlsplit(request.get("url", "")).path.endswith("/open/fetch/pfti"):
                continue
            post = request.get("postData", {})
            params = post.get("params", [])
            if params:
                payload = {item["name"]: item.get("value", "") for item in params if "name" in item}
            elif "json" in post.get("mimeType", ""):
                payload = json.loads(post.get("text", "{}"))
            else:
                payload = {key: value[0] for key, value in parse_qs(post.get("text", ""), keep_blank_values=True).items()}
            result.append(normalize_envelope({"requestUrl": request.get("url", ""), "payload": payload}))
        if not result:
            raise ValueError("HAR 中没有包含请求正文的 /open/fetch/pfti 记录。请导出包含内容的 HAR。")
        return result
    return [normalize_envelope(item) for item in (data if isinstance(data, list) else [data])]


class CaptureService:
    def __init__(self, repository: Repository):
        self.repository = repository
        self._lock = threading.Lock()

    def ingest(self, value: dict) -> dict:
        envelope = normalize_envelope(value)
        with self._lock:
            capture_id, created = self.repository.create_capture(envelope)
            if not created:
                record = self.repository.capture(capture_id)
                return {"captureId": capture_id, "state": record["state"], "duplicate": True}
            return self._parse(capture_id, envelope)

    # def _parse(self, capture_id: str, envelope: dict) -> dict:
    # 2026-10-11：本次修改原因：区分普通重复采集与用户主动重新解析的字段回填。
    def _parse(self, capture_id: str, envelope: dict, backfill: bool = False) -> dict:
        try:
            product = parse_capture(envelope["payload"])
            product.capture_id = capture_id
            # product, created = self.repository.store_parsed(product)
            # 2026-10-11：本次修改原因：重新解析时保留完整解析结果，补齐商品库缺失字段。
            parsed = product
            product, created = self.repository.store_parsed(parsed)
            updated, summary = False, {}
            if backfill and not created:
                product, updated, summary = self.repository.backfill_parsed(capture_id, parsed)
            state = "已解析" if product.title and product.skus else "待补充"
            message = "；".join(product.warnings) or "已提取商品信息，请核对后完善售价。"
            # if not created:
            if not created and not backfill:
                state = "重复商品"
                message = "原始材料已留档；保留商品库内已有编辑。"
            # 2026-10-11：本次修改原因：重新解析结果明确显示补齐数量，并告知审核状态变化。
            if backfill and not created:
                message = (f"已补齐：SKU {summary.get('skus', 0)} 条、属性 {summary.get('attributes', 0)} 项、"
                           f"主图 {summary.get('images', 0)} 张、详情图 {summary.get('details', 0)} 张、"
                           f"其他字段 {summary.get('fields', 0)} 项。人工修改已保留，商品需要重新审核。"
                           if updated else "没有可补齐的新字段；人工修改、主动清空的字段和已移除的 SKU 均已保留。")
            self.repository.finish_capture(capture_id, state, message, product.id)
            # return {"captureId": capture_id, "state": state, "productId": product.id, "duplicate": False}
            return {"captureId": capture_id, "state": state, "productId": product.id, "duplicate": False,
                    "updated": updated, "summary": summary, "message": message}
        except (ValueError, TypeError, KeyError, RecursionError) as error:
            self.repository.finish_capture(capture_id, "解析失败", str(error)[:1000])
            return {"captureId": capture_id, "state": "解析失败", "message": str(error)}

    def reparse(self, capture_id: str) -> dict:
        with self._lock:
            record = self.repository.capture(capture_id)
            if not record:
                raise ValueError("采集记录不存在。")
            envelope = json.loads(Path(record["raw_path"]).read_text(encoding="utf-8"))
            # return self._parse(capture_id, envelope)
            # 2026-10-11：本次修改原因：重新解析触发回填；普通接收继续保护已有商品。
            return self._parse(capture_id, envelope, backfill=True)

    def import_files(self, paths: list[str]) -> dict:
        results, errors = [], []
        for name in paths:
            try:
                for envelope in envelopes_from_file(Path(name)):
                    results.append(self.ingest(envelope))
            except Exception as error:
                errors.append(f"{Path(name).name}：{error}")
        return {"results": results, "errors": errors}
