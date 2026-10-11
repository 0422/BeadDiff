# 2026-10-11：本次修改原因：为两条路线统一组织文案、风格分析、单图及套图任务，候选先留档再由运营应用。
from __future__ import annotations

from dataclasses import asdict
import json
import re
from typing import Callable
from uuid import uuid4

from ..assets import AssetStore, ImageAsset
from ..content import clean_description
from ..models import now_iso
from .client import CompatibleClient, image_bytes, image_sources
from .config import ModelConfigStore
from .contracts import AIRequest, AIResult
from .jobs import JobStore


SYSTEM = ("你是电商商品内容助手。只使用提供的商品事实；参考素材用于学习表达、构图、背景和光影。"
          "不要将参考商品的材质、颜色、尺寸、数量、品牌或包装移植给当前商品。"
          "不清楚的信息省略，不虚构性能、认证或物料。")


def facts(product: dict) -> dict:
    return {"title": product.get("title", ""), "category": product.get("category", ""),
            "attributes": product.get("attributes", {}),
            "skus": [{"spec1": sku.get("spec1", ""), "spec2": sku.get("spec2", ""),
                      "specs": sku.get("specs", {})} for sku in product.get("skus", [])]}


class AIService:
    def __init__(self, config: ModelConfigStore, assets: AssetStore):
        self.config, self.assets = config, assets
        self.jobs = JobStore(config.path.parent)

    def generate(self, request: AIRequest, progress: Callable[[str], None] | None = None) -> AIResult:
        category = "image" if request.operation in {"image", "image_set"} else "text"
        profile = self.config.get(request.model_id, category)
        if profile.category != category:
            raise ValueError("所选模型类别与当前任务不一致。")
        client = CompatibleClient(profile, self.assets)
        job_id = uuid4().hex
        result = AIResult(job_id, request.operation, model_caption=profile.caption)
        job = {"id": job_id, "created_at": now_iso(), "state": "running", "operation": request.operation,
               "product_id": request.product.get("id", ""), "request": asdict(request),
               "model": profile.public_dict()}
        self.jobs.save(job)
        context = json.dumps(facts(request.product), ensure_ascii=False)
        prompt = (f"商品事实：{context}\n目标语言：{request.language}\n"
                  f"用户要求：{request.instruction}\n参考文案/风格：{request.reference_text}")
        try:
            if category == "text":
                if progress:
                    progress("正在生成文本…")
                tasks = {"title": "生成产品标题", "simple_description": "生成简易描述，使用纯文本卖点",
                         "description_html": "生成详细描述，只使用静态 HTML 段落、标题和列表",
                         "reference_analysis": "分析参考素材的表达、构图、光影、版式和图片用途次序，输出可复用的风格 Prompt"}
                if request.operation not in tasks:
                    raise ValueError("当前 AI 功能尚未开放。")
                old = request.product.get(request.operation, "")
                prompt += f"\n任务：{tasks[request.operation]}\n当前内容：{old}\n"
                count = max(1, min(request.count, 4))
                prompt += f'输出 {count} 个候选，仅返回 JSON：{{"candidates":["候选内容"]}}。'
                # images = request.reference_images
                # if request.operation == "reference_analysis":
                #     images = list(dict.fromkeys(request.subject_images + images))
                # 2026-10-11：本次修改原因：文本任务也支持主体图，明确主体与爆款参考的身份。
                images = list(dict.fromkeys(request.subject_images + request.reference_images))
                if images:
                    prompt += (f"\n前 {len(request.subject_images)} 张为当前商品主体；其余为爆款风格参考。"
                               "只能从主体图提取可见事实；参考图只用于风格，不代表当前商品属性。")
                raw = client.complete(SYSTEM, prompt, images)
                stripped = re.sub(r"^```(?:json|html)?\s*|\s*```$", "", raw.strip())
                try:
                    parsed = json.loads(stripped)
                    candidates = parsed.get("candidates", []) if isinstance(parsed, dict) else []
                except ValueError:
                    candidates = []
                # result.candidates = [str(value).strip() for value in candidates[:count] if isinstance(value, str) and value.strip()] or [stripped]
                # 2026-10-11：本次修改原因：兼容服务返回错误 candidates 类型时回退纯文本，避免迭代对象键。
                candidates = candidates if isinstance(candidates, list) else []
                result.candidates = [value.strip() for value in candidates[:count] if isinstance(value, str) and value.strip()] or [stripped]
                if request.operation == "description_html":
                    result.candidates = [clean_description(text) for text in result.candidates]
            else:
                if not request.subject_images:
                    raise ValueError("请指定商品主体图，确保生成内容基于当前实物。")
                references = list(dict.fromkeys(request.subject_images + request.reference_images))
                slots = request.slots if request.operation == "image_set" else [request.instruction or "商品图片"] * max(1, min(request.count, 4))
                if not slots or len(slots) > 12:
                    raise ValueError("套图需要 1～12 个图片用途，每行一个；可按行调整生成顺序。")
                for index, purpose in enumerate(slots):
                    if progress:
                        progress(f"正在生成 {index + 1}/{len(slots)}：{purpose[:35]}")
                    try:
                        instruction = (SYSTEM + "\n" + prompt + f"\n本张用途与排布：{purpose}\n"
                            f"前 {len(request.subject_images)} 张为当前商品主体；其余为风格参考。"
                            "保留主体的实物形状、颜色、材质和数量。不要把参考图中的商品主体混入结果。")
                        response = client.image(instruction, references, request.size)
                        sources = image_sources(response)
                        if not sources:
                            raise ValueError("响应中没有找到生成图片；请检查模型是否支持生图及接口模式。")
                        # 每次请求 n=1，只取一个经解码校验的结果，防止服务回显输入图被当作候选。
                        asset = self.assets.save(image_bytes(sources[0], self.assets))
                        result.assets.append(asset)
                        result.purposes.append(purpose)
                    except (ValueError, OSError) as error:
                        result.errors.append(f"第 {index + 1} 张：{error}")
                    job["result"] = asdict(result)
                    self.jobs.save(job)
                if not result.assets:
                    raise ValueError("\n".join(result.errors) or "没有生成图片。")
            job["state"] = "partial" if result.errors else "completed"
            job["result"] = asdict(result)
            self.jobs.save(job)
            return result
        except Exception as error:
            job["state"] = "failed"
            # 不保存异常对象或 HTTP 请求头，防止将凭证写进日志。
            job["error"] = str(error).replace(profile.key, "[密钥已隐藏]") if profile.key else str(error)
            self.jobs.save(job)
            raise

    @staticmethod
    def restore(job: dict) -> AIResult:
        values = dict(job["result"])
        values["assets"] = [ImageAsset(**row) for row in values.get("assets", [])]
        return AIResult(**values)
