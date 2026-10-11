# 2026-10-11：本次修改原因：生成输入、模型公开配置和候选独立留档，关闭编辑后仍可找回结果，文件不保存 API Key。
from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from ..models import now_iso


class JobStore:
    def __init__(self, data_dir: Path):
        self.root = data_dir / "ai_jobs"

    def save(self, job: dict) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        job["updated_at"] = now_iso()
        target = self.root / (job["id"] + ".json")
        temporary = target.with_suffix(f".{uuid4().hex}.tmp")
        try:
            temporary.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)

    def list(self, product_id: str, operation: str) -> list[dict]:
        rows = []
        if self.root.exists():
            for path in self.root.glob("*.json"):
                try:
                    job = json.loads(path.read_text(encoding="utf-8"))
                    # if job.get("product_id") == product_id and job.get("operation") == operation and job.get("result"):
                    # 2026-10-11：本次修改原因：忽略损坏或被外部改成数组的历史文件。
                    if isinstance(job, dict) and job.get("product_id") == product_id and job.get("operation") == operation and job.get("result"):
                        rows.append(job)
                except (ValueError, OSError):
                    continue
        return sorted(rows, key=lambda row: row.get("updated_at", ""), reverse=True)[:50]
