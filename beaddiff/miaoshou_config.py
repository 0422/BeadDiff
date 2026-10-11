# 2026-10-11：本次修改原因：单独保存妙手开放平台凭证和人工确认的人民币换算汇率，避免密钥进入源码或回传记录。
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import threading
from uuid import uuid4


API_BASE = "https://openapi-erp.91miaoshou.com"


@dataclass(frozen=True)
class MiaoshouConfig:
    app_key: str = field(default="", repr=False)
    app_secret: str = field(default="", repr=False)
    timeout: int = 30
    cny_rates: dict[str, str] = field(default_factory=lambda: {"CNY": "1"})

    @property
    def account_id(self) -> str:
        return hashlib.sha256(self.app_key.encode("utf-8")).hexdigest() if self.app_key else ""

    def problems(self) -> list[str]:
        result = []
        if not self.app_key.strip() or not self.app_secret.strip():
            result.append("请在设置 → 妙手回传填写并保存 AppKey、AppSecret（不是接口文档密码）。")
        if any(char in self.app_key + self.app_secret for char in "\r\n"):
            result.append("AppKey、AppSecret 不能包含换行。")
        if type(self.timeout) is not int or not 10 <= self.timeout <= 120:
            result.append("请求超时应在 10～120 秒之间。")
        if not isinstance(self.cny_rates, dict):
            return result + ["cny_rates 应为货币代码到人民币汇率的对象。"]
        for code, value in self.cny_rates.items():
            try:
                rate = Decimal(str(value))
                if (not isinstance(code, str) or len(code) != 3 or not code.isascii()
                        or not code.isalpha() or code != code.upper() or not rate.is_finite() or rate <= 0):
                    raise ValueError
                if code == "CNY" and rate != 1:
                    raise ValueError
            except (InvalidOperation, ValueError):
                result.append("汇率必须使用大写三位币种及大于零的数值，CNY 汇率固定为 1。")
                break
        return result


class MiaoshouConfigStore:
    def __init__(self, data_dir: Path):
        self.path = data_dir / "miaoshou.local.json"
        self.config = MiaoshouConfig()
        self.error = ""
        self._digest: str | None = None
        self._lock = threading.RLock()
        self.reload()

    def _fingerprint(self) -> str | None:
        return hashlib.sha256(self.path.read_bytes()).hexdigest() if self.path.exists() else None

    def reload(self) -> bool:
        with self._lock:
            try:
                raw = self.path.read_bytes() if self.path.exists() else None
                # data = json.loads(raw.decode("utf-8-sig")) if raw else {}
                # 2026-10-11：本次修改原因：空文件属于格式错误，不应被当成文件缺失后允许静默覆盖。
                data = json.loads(raw.decode("utf-8-sig")) if raw is not None else {}
                if not isinstance(data, dict) or data.get("version", 1) != 1:
                    raise ValueError
                values = {name: data[name] for name in MiaoshouConfig.__dataclass_fields__ if name in data}
                if any(not isinstance(values.get(name, ""), str) for name in ("app_key", "app_secret")):
                    raise ValueError
                config = MiaoshouConfig(**values)
                # 空凭证可以保存/加载，格式错误则关闭发送；不回显配置正文。
                errors = config.problems()
                if any(not error.startswith("请在设置") for error in errors):
                    raise ValueError
                self.config = config
                self._digest = hashlib.sha256(raw).hexdigest() if raw else None
                self.error = ""
                return True
            except (ValueError, TypeError, OSError):
                self.config = MiaoshouConfig()
                self.error = "妙手配置文件格式或读取权限不正确，请修正后重新加载；原文件已保留。"
                return False

    def save(self, config: MiaoshouConfig) -> None:
        with self._lock:
            if self.error or self._fingerprint() != self._digest:
                raise ValueError("配置已被外部修改或加载失败，请先重新加载，避免覆盖原文件。")
            errors = [error for error in config.problems() if not error.startswith("请在设置")]
            if errors:
                raise ValueError("；".join(errors))
            raw = (json.dumps({"version": 1, **asdict(config)}, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_name(self.path.name + f".{uuid4().hex}.tmp")
            try:
                temporary.write_bytes(raw)
                temporary.replace(self.path)
            finally:
                temporary.unlink(missing_ok=True)
            self.config = config
            self._digest = hashlib.sha256(raw).hexdigest()
            self.error = ""

    def get(self) -> MiaoshouConfig:
        with self._lock:
            if self.error:
                raise ValueError(self.error)
            # 每次任务取得独立快照，发送过程中设置变化不影响已签名的请求。
            return MiaoshouConfig(self.config.app_key, self.config.app_secret, self.config.timeout,
                                  dict(self.config.cny_rates))
