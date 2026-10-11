# 2026-10-11：本次修改原因：视频暂不接厂商，预留统一提交、查询和结果接口，避免后续修改商品调用入口。
from typing import Protocol

from .contracts import AIRequest, AIResult


class VideoProvider(Protocol):
    def submit(self, request: AIRequest) -> str: ...
    def status(self, task_id: str) -> dict: ...
    def result(self, task_id: str) -> AIResult: ...


class UnavailableVideoProvider:
    def submit(self, request: AIRequest) -> str:
        raise NotImplementedError("AI 视频生成功能暂未开放。")

    def status(self, task_id: str) -> dict:
        raise NotImplementedError("AI 视频生成功能暂未开放。")

    def result(self, task_id: str) -> AIResult:
        raise NotImplementedError("AI 视频生成功能暂未开放。")
