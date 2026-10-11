# 2026-10-11：本次修改原因：将模型配置及分类当前项保存在 Git 忽略的独立本地文件，支持安全重载与原子保存。
from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
import hashlib
import json
from pathlib import Path
import threading
from urllib.parse import urlsplit
from uuid import uuid4


@dataclass(frozen=True)
class ModelProfile:
    id: str
    category: str
    name: str = ""
    provider: str = ""
    url: str = ""
    key: str = field(default="", repr=False)
    modelname: str = ""
    image_mode: str = "auto"
    supports_vision: bool = False
    timeout: int = 300

    @property
    def caption(self) -> str:
        return self.name or self.modelname or self.provider or "未命名配置"

    def problems(self) -> list[str]:
        missing = [label for label, value in (("厂商", self.provider), ("URL", self.url),
                   ("API Key", self.key), ("模型名称", self.modelname)) if not value.strip()]
        result = ["缺少：" + "、".join(missing)] if missing else []
        if self.url:
            try:
                address = urlsplit(self.url)
                if address.scheme not in {"http", "https"} or not address.hostname or address.fragment:
                    result.append("URL 应为 HTTP/HTTPS 接口地址，不能包含片段标记。")
                if address.username or address.password:
                    result.append("请通过 API Key 字段填写凭证。")
            except ValueError:
                result.append("URL 格式不正确。")
        if "\n" in self.key or "\r" in self.key:
            result.append("API Key 不能包含换行。")
        return result

    def public_dict(self) -> dict:
        # return {name: value for name, value in asdict(self).items() if name != "key"}
        # 2026-10-11：本次修改原因：任务记录不保留 URL 查询凭证，也不回显 API Key。
        values = {name: value for name, value in asdict(self).items() if name != "key"}
        address = urlsplit(self.url)
        values["url"] = address._replace(query="", fragment="").geturl()
        if self.key:
            values = {name: value.replace(self.key, "[密钥已隐藏]") if isinstance(value, str) else value
                      for name, value in values.items()}
        return values


class ModelConfigStore:
    def __init__(self, data_dir: Path):
        self.path = data_dir / "ai_models.local.json"
        self.profiles: list[ModelProfile] = []
        self.active: dict[str, str] = {"text": "", "image": ""}
        self.error = ""
        self._digest: str | None = None
        self._lock = threading.RLock()
        self.reload()

    def _fingerprint(self) -> str | None:
        return hashlib.sha256(self.path.read_bytes()).hexdigest() if self.path.exists() else None

    def reload(self) -> bool:
        with self._lock:
            try:
                if not self.path.exists():
                    self._digest = None
                    self._commit([], {"text": "", "image": ""}, check_external=False)
                    return True
                raw = self.path.read_bytes()
                data = json.loads(raw.decode("utf-8-sig"))
                if not isinstance(data, dict) or data.get("version", 1) != 1:
                    raise ValueError("仅支持 version 为 1 的配置对象。")
                rows = data.get("profiles", [])
                if not isinstance(rows, list):
                    raise ValueError("profiles 必须为数组。")
                profiles = []
                ids = set()
                for row in rows:
                    if not isinstance(row, dict):
                        raise ValueError("每个配置项必须为对象。")
                    values = {key: row[key] for key in ModelProfile.__dataclass_fields__ if key in row}
                    for key in ("id", "category", "name", "provider", "url", "key", "modelname", "image_mode"):
                        if key in values and not isinstance(values[key], str):
                            raise ValueError(f"{key} 必须为字符串。")
                    profile = ModelProfile(**values)
                    if not profile.id or profile.id in ids or profile.category not in {"text", "image"}:
                        raise ValueError("配置 ID 必须唯一且非空，category 必须为 text 或 image。")
                    if profile.image_mode not in {"auto", "images", "chat"}:
                        raise ValueError("image_mode 必须为 auto、images 或 chat。")
                    if type(profile.supports_vision) is not bool or type(profile.timeout) is not int:
                        raise ValueError("supports_vision 应为布尔值，timeout 应为整数。")
                    if not 10 <= profile.timeout <= 1800:
                        raise ValueError("timeout 应在 10～1800 秒之间。")
                    profiles.append(profile)
                    ids.add(profile.id)
                active = {kind: data.get(f"active_{kind}_id", "") for kind in ("text", "image")}
                for kind, selected in active.items():
                    if not isinstance(selected, str) or (selected and not any(
                            p.id == selected and p.category == kind for p in profiles)):
                        raise ValueError(f"active_{kind}_id 必须引用同类别的已有配置或留空。")
                self.profiles, self.active = profiles, active
                self._digest = hashlib.sha256(raw).hexdigest()
                self.error = ""
                return True
            except (ValueError, TypeError, OSError) as error:
                # 格式错误时停止调用，保留原文件；错误信息不包含配置正文和密钥。
                self.profiles, self.active = [], {"text": "", "image": ""}
                detail = f"JSON 第 {error.lineno} 行格式错误" if isinstance(error, json.JSONDecodeError) else (
                    str(error) if isinstance(error, ValueError) else "文件结构或读取权限不正确")
                self.error = f"模型配置未加载：{detail}。请修正文件后重新加载。"
                return False

    def _commit(self, profiles: list[ModelProfile], active: dict[str, str], check_external: bool = True) -> None:
        if check_external and (self.error or self._fingerprint() != self._digest):
            raise ValueError("配置文件存在错误或已被外部修改，请先重新加载，避免覆盖原文件。")
        data = {"version": 1, "active_text_id": active["text"], "active_image_id": active["image"],
                "profiles": [asdict(profile) for profile in profiles]}
        raw = (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + f".{uuid4().hex}.tmp")
        try:
            temporary.write_bytes(raw)
            temporary.replace(self.path)
        finally:
            temporary.unlink(missing_ok=True)
        self.profiles, self.active = profiles, active
        self._digest = hashlib.sha256(raw).hexdigest()
        self.error = ""

    def save(self, profile: ModelProfile) -> None:
        with self._lock:
            if profile.category not in {"text", "image"} or not profile.id:
                raise ValueError("配置类别或 ID 不正确。")
            if profile.image_mode not in {"auto", "images", "chat"} or not 10 <= profile.timeout <= 1800:
                raise ValueError("接口模式或超时设置不正确。")
            rows = [profile if row.id == profile.id else row for row in self.profiles]
            if not any(row.id == profile.id for row in rows):
                rows.append(profile)
            active = dict(self.active)
            for kind, selected in active.items():
                if selected == profile.id and (kind != profile.category or profile.problems()):
                    active[kind] = ""
            self._commit(rows, active)

    def remove(self, profile_id: str) -> None:
        with self._lock:
            rows = [row for row in self.profiles if row.id != profile_id]
            active = {kind: "" if value == profile_id else value for kind, value in self.active.items()}
            self._commit(rows, active)

    def activate(self, profile_id: str) -> None:
        with self._lock:
            profile = self.get(profile_id)
            active = dict(self.active)
            active[profile.category] = profile.id
            self._commit(list(self.profiles), active)

    def get(self, profile_id: str = "", category: str = "text") -> ModelProfile:
        with self._lock:
            if self.error:
                raise ValueError(self.error)
            selected = profile_id or self.active.get(category, "")
            profile = next((row for row in self.profiles if row.id == selected), None)
            if profile is None:
                raise ValueError("请在设置 → AI 模型中新增配置，并点击“设为当前”。")
            if profile.problems():
                raise ValueError("模型配置不可使用：" + "；".join(profile.problems()))
            return replace(profile)
