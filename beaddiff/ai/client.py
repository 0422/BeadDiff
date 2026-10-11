# 2026-10-11：本次修改原因：依据米醋工具的兼容协议实现文本、图片生成、编辑和多图参考调用，并统一解析输出。
from __future__ import annotations

import base64
from html.parser import HTMLParser
# import json
# 2026-10-11：本次修改原因：JSON 由 HTTP 客户端处理，注释未使用的导入。
import re
from urllib.parse import urlsplit, urlunsplit

import httpx

from ..assets import AssetStore
from .config import ModelProfile


class ModelCallError(ValueError):
    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.status = status


def endpoint(base: str, route: str) -> str:
    """Accept a host, a /v1 base, or a full compatible endpoint without duplicating /v1."""
    url = urlsplit(base.strip())
    path = url.path.rstrip("/")
    # 2026-10-11：本次修改原因：完整接口地址保留其实际路径前缀，支持兼容服务的自定义反向代理路径。
    full_endpoint = False
    for suffix in ("/chat/completions", "/images/generations", "/images/edits", "/models"):
        if path.endswith(suffix):
            path = path[:-len(suffix)]
            full_endpoint = True
            break
    # if not path.endswith("/v1"):
    #     path += "/v1"
    # 2026-10-11：本次修改原因：仅裸域名默认补 v1；明确提供的前缀或完整接口不改写。
    if not path and not full_endpoint:
        path = "/v1"
    return urlunsplit((url.scheme, url.netloc, path + "/" + route, url.query, ""))


def text_content(response: dict) -> str:
    parts = []
    for choice in response.get("choices", []):
        content = (choice.get("message") or {}).get("content", "")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            parts.extend(part["text"] for part in content if isinstance(part, dict) and isinstance(part.get("text"), str))
    if not parts and isinstance(response.get("output_text"), str):
        parts.append(response["output_text"])
    if not parts:
        for item in response.get("output", []):
            if isinstance(item, dict):
                parts.extend(part["text"] for part in item.get("content", [])
                             if isinstance(part, dict) and isinstance(part.get("text"), str))
    return "\n".join(parts).strip()


class _ImageTags(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "img":
            value = dict(attrs).get("src", "")
            if value:
                self.urls.append(value)


def image_sources(response: dict) -> list[str]:
    """Only inspect returned output fields, never the echoed request or the whole JSON."""
    sources: list[str] = []

    def image_value(value):
        if isinstance(value, str) and value:
            sources.append(value)
        elif isinstance(value, dict):
            for key in ("url", "image_url", "b64_json", "image", "src"):
                if key in value:
                    image_value(value[key])
                    break

    def in_text(value):
        if not isinstance(value, str):
            return
        parser = _ImageTags()
        parser.feed(value)
        sources.extend(parser.urls)
        sources.extend(re.findall(r"!\[[^\]]*\]\((https?://[^\s)]+|data:image/[^\s)]+)\)", value))
        sources.extend(re.findall(r"data:image/[\w.+-]+;base64,[A-Za-z0-9+/=]+", value))
        sources.extend(re.findall(r"https?://[^\s\"'<>)]+\.(?:png|jpe?g|webp|gif)(?:\?[^\s\"'<>)]*)?", value, re.I))
        stripped = value.strip()
        if len(stripped) > 200 and re.fullmatch(r"[A-Za-z0-9+/=\s]+", stripped):
            sources.append(stripped)

    for item in response.get("data", []):
        image_value(item)
    for choice in response.get("choices", []):
        message = choice.get("message") or {}
        for key in ("images", "attachments"):
            for item in message.get(key, []) or []:
                image_value(item)
        if message.get("image"):
            image_value(message["image"])
        content = message.get("content", "")
        if isinstance(content, str):
            in_text(content)
        elif isinstance(content, list):
            for part in content:
                if not isinstance(part, dict):
                    continue
                if part.get("type") in {"image_url", "output_image"}:
                    image_value(part)
                in_text(part.get("text", ""))
    for item in response.get("output", []):
        if not isinstance(item, dict):
            continue
        if item.get("type") == "image_generation_call":
            image_value(item.get("result"))
        for part in item.get("content", []):
            if not isinstance(part, dict):
                continue
            if part.get("type") in {"output_image", "image_url"}:
                image_value(part)
            in_text(part.get("text", ""))
    return list(dict.fromkeys(sources))


def image_bytes(source: str, assets: AssetStore) -> bytes:
    if source.startswith(("http://", "https://")):
        return assets.read(source)
    encoded = source.partition(",")[2] if source.startswith("data:") else source
    try:
        return base64.b64decode(re.sub(r"\s", "", encoded), validate=True)
    except (ValueError, base64.binascii.Error) as error:
        raise ValueError("返回的图片 Base64 数据无效。") from error


class CompatibleClient:
    def __init__(self, profile: ModelProfile, assets: AssetStore):
        self.profile, self.assets = profile, assets

    def _safe(self, text: str) -> str:
        text = text.replace(self.profile.key, "[密钥已隐藏]") if self.profile.key else text
        text = re.sub(r"(?i)(?:bearer\s+|sk-)[A-Za-z0-9_\-\.]+", "[密钥已隐藏]", text)
        return text[:600]

    def _request(self, route: str, body: dict | None = None, files=None, form=None, method: str = "POST") -> dict:
        headers = {"Authorization": "Bearer " + self.profile.key, "Accept": "application/json"}
        try:
            # 不自动重试生成 POST；超时可能意味着服务端已完成并计费。
            with httpx.Client(timeout=httpx.Timeout(self.profile.timeout, connect=15), follow_redirects=False) as client:
                response = client.request(method, endpoint(self.profile.url, route), headers=headers,
                                          json=body, files=files, data=form)
            if not response.is_success:
                try:
                    data = response.json()
                    detail = (data.get("error") or {}).get("message", "") if isinstance(data.get("error"), dict) else data.get("message", "")
                except (ValueError, AttributeError):
                    detail = "接口未返回可解析的错误信息"
                raise ModelCallError(f"模型接口返回 HTTP {response.status_code}：{self._safe(str(detail))}", response.status_code)
            try:
                result = response.json()
            except ValueError as error:
                raise ModelCallError("接口未返回 JSON，请确认 URL 指向模型 API。") from error
            if not isinstance(result, dict):
                raise ModelCallError("接口返回的 JSON 结构不是对象。")
            return result
        except httpx.TimeoutException as error:
            raise ModelCallError("请求超时，服务端结果未知。请先检查厂商任务或账单，再决定是否重新生成。") from error
        except httpx.HTTPError as error:
            raise ModelCallError("网络连接失败，请检查模型 URL、网络及代理。请求已提交时请先核对厂商结果。") from error

    def check(self) -> str:
        try:
            response = self._request("models", method="GET")
        except ModelCallError as error:
            if error.status in {404, 405, 501}:
                return "此服务不提供模型列表；实际生成能力仍需在商品编辑中验证。"
            raise
        models = {item.get("id") for item in response.get("data", []) if isinstance(item, dict)}
        if self.profile.modelname in models:
            return "鉴权及模型列表访问成功，找到了所填模型；生成能力以实际调用为准。"
        return "模型列表访问成功，但未找到所填名称；部分服务不会列出所有可调用模型。"

    def complete(self, system: str, prompt: str, images: list[str] | None = None) -> str:
        references = images or []
        if references and not self.profile.supports_vision:
            raise ValueError("当前文本配置未启用图片理解。请在高级选项中启用，或使用文字参考。")
        content: str | list[dict] = prompt
        if references:
            content = [{"type": "text", "text": prompt}]
            for address in references:
                raw = self.assets.png(address)
                content.append({"type": "image_url", "image_url": {
                    "url": "data:image/png;base64," + base64.b64encode(raw).decode("ascii")}})
        response = self._request("chat/completions", {"model": self.profile.modelname, "stream": False,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}]})
        text = text_content(response)
        if not text:
            raise ModelCallError("接口没有返回文本内容，请检查模型与接口类型。")
        return text

    def image(self, prompt: str, images: list[str], size: str) -> dict:
        mode = self.profile.image_mode
        if mode == "auto" and urlsplit(self.profile.url).path.rstrip("/").endswith("/chat/completions"):
            mode = "chat"
        if mode == "auto":
            mode = "chat" if len(images) > 1 else "images"
        if mode == "chat":
            content = [{"type": "text", "text": prompt + f"\n输出一张图片，期望尺寸 {size}；除非要求，不要拼接参考图。"}]
            for address in images:
                content.append({"type": "image_url", "image_url": {"url": "data:image/png;base64," +
                    base64.b64encode(self.assets.png(address)).decode("ascii")}})
            return self._request("chat/completions", {"model": self.profile.modelname, "stream": False,
                "messages": [{"role": "user", "content": content}]})
        if not images:
            return self._request("images/generations", {"model": self.profile.modelname, "prompt": prompt,
                "size": size, "n": 1, "response_format": "url"})
        files = [("image" if len(images) == 1 else "image[]", (f"reference-{i}.png", self.assets.png(address), "image/png"))
                 for i, address in enumerate(images)]
        try:
            return self._request("images/edits", files=files, form={"model": self.profile.modelname,
                "prompt": prompt, "size": size, "n": "1", "response_format": "url"})
        except ModelCallError as error:
            # 只在明确无此接口时允许同模型聊天生图；网络失败或 5xx 不盲目再次计费。
            if self.profile.image_mode == "auto" and error.status in {404, 405, 501}:
                from dataclasses import replace
                return CompatibleClient(replace(self.profile, image_mode="chat"), self.assets).image(prompt, images, size)
            raise
