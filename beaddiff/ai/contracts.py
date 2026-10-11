# 2026-10-11：本次修改原因：两条商品路线使用一致的任务与候选结构，厂商请求细节不进入商品界面。
from __future__ import annotations

from dataclasses import dataclass, field

from ..assets import ImageAsset


@dataclass
class AIRequest:
    operation: str
    product: dict
    model_id: str = ""
    instruction: str = ""
    language: str = "English"
    reference_text: str = ""
    subject_images: list[str] = field(default_factory=list)
    reference_images: list[str] = field(default_factory=list)
    size: str = "1024x1024"
    count: int = 1
    slots: list[str] = field(default_factory=list)


@dataclass
class AIResult:
    job_id: str
    operation: str
    candidates: list[str] = field(default_factory=list)
    assets: list[ImageAsset] = field(default_factory=list)
    purposes: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    model_caption: str = ""
