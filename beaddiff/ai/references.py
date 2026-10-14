# 2026-10-13：本次修改原因：独立保存爆款分析 Prompt，供商品加工复用，不修改商品数据库或模型配置。
from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from ..models import now_iso


# 内置分析指引，不冒充或自动安装第三方 ec-visual-skill。
VISUAL_GUIDE = """请拆解参考电商素材，输出可直接编辑、复用的中文 Prompt。
依次说明：1. 标题与卖点表达结构；2. 简易描述与详情信息层级；
3. 构图、主体占比、光感、配色、背景、字体态度与留白；
4. 主图、场景、细节、卖点图的用途、排布和次序；5. 可迁移的风格要求。
区分观察事实与推测，不声称知道销量或转化率。参考商品只提供视觉与表达方式，
不要把它的品牌、材质、数量、尺寸、性能、认证搬到待加工商品。
用“当前商品”“已确认卖点”等占位表达，避免绑定参考商品的身份。
素材不足时明确缺少什么；没有图片时不要臆测画面。"""


class ReferenceStore:
    def __init__(self, data_dir: Path):
        self.path = data_dir / "reference_analyses.local.json"

    def list(self) -> list[dict]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            # rows = data["items"]
            # 2026-10-13：本次修改原因：损坏或未来版本方案库禁止覆盖保存，保护已有方案。
            if not isinstance(data, dict) or data.get("version", 1) != 1:
                raise ValueError("方案库版本或结构不受支持")
            rows = data["items"]
            if not isinstance(rows, list) or any(
                not isinstance(row, dict) or not isinstance(row.get("id"), str)
                # or not isinstance(row.get("name"), str) or not isinstance(row.get("prompt"), str)
                # 2026-10-13：本次修改原因：读取时验证素材和时间类型，避免选择损坏方案导致界面异常。
                or not row.get("id") or not isinstance(row.get("name"), str) or not isinstance(row.get("prompt"), str)
                or not isinstance(row.get("material", ""), str) or not isinstance(row.get("updated_at", ""), str)
                or not isinstance(row.get("images", []), list)
                or any(not isinstance(url, str) for url in row.get("images", []))
                for row in rows
            ):
                raise ValueError("记录格式错误")
            return sorted(rows, key=lambda row: row.get("updated_at", ""), reverse=True)
        except (ValueError, KeyError, TypeError) as error:
            raise ValueError("爆款分析文件无法读取；请保留原文件，修复后再保存。") from error

    def _write(self, rows: list[dict]):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + "." + uuid4().hex + ".tmp")
        try:
            temporary.write_text(json.dumps({"version": 1, "items": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def save(self, record: dict) -> dict:
        rows = self.list()
        value = dict(record)
        value["name"] = str(value.get("name", "")).strip()
        value["prompt"] = str(value.get("prompt", "")).strip()
        if not value["name"] or not value["prompt"]:
            raise ValueError("请填写方案名称和参考 Prompt。")
        value["id"] = value.get("id") or uuid4().hex
        value["updated_at"] = now_iso()
        rows = [row for row in rows if row["id"] != value["id"]]
        self._write([value, *rows])
        return value

    def delete(self, identifier: str):
        self._write([row for row in self.list() if row["id"] != identifier])
