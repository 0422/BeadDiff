# 2026-10-10：本次修改原因：集中管理本机数据目录与随机接入密钥，不将密钥写入项目源文件。
from __future__ import annotations

import json
import os
import secrets
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Settings:
    data_dir: Path
    token: str
    port: int = 18765

    @classmethod
    def load(cls) -> Settings:
        data_dir = Path(os.environ.get("BEADDIFF_DATA_DIR", PROJECT_ROOT / "data")).resolve()
        data_dir.mkdir(parents=True, exist_ok=True)
        config = data_dir / "settings.json"
        if config.exists():
            content = json.loads(config.read_text(encoding="utf-8"))
            port = int(content.get("port", 18765))
            token = str(content.get("token", ""))
            if not 1024 <= port <= 65535 or len(token) < 24:
                raise ValueError("settings.json 中的端口或接入密钥无效，请检查配置。")
            return cls(data_dir, token, port)
        result = cls(data_dir, secrets.token_urlsafe(32))
        result.save()
        return result

    def save(self) -> None:
        target = self.data_dir / "settings.json"
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps({"port": self.port, "token": self.token}, indent=2), encoding="utf-8")
        temporary.replace(target)

    @property
    def endpoint(self) -> str:
        return f"http://127.0.0.1:{self.port}/api/v1/captures"

