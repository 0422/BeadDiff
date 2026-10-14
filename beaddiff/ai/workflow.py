# 2026-10-13：本次修改原因：统一 AI 多字段任务、部分失败留档和草稿补丁，继续复用现有模型接口与 ERP 校验。
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from html import escape
import json
import re
from uuid import uuid4

# from ..content import clean_description, description_images, detail_html
# 2026-10-13：本次修改原因：详情整组替换覆盖正文独有图片，保持文案与图片应用一致。
from ..content import clean_description, description_images, detail_html, with_detail_images
from ..miaoshou_mapping import TEXT_LIMITS, draft_limit_issues
from ..models import Product, now_iso
from .contracts import AIRequest


TEXT_TASKS = {"title": "产品标题", "simple_description": "简易描述", "description_html": "详细描述"}


def safe_error(service, error) -> str:
    message = str(error)
    for profile in service.config.profiles:
        if profile.key:
            message = message.replace(profile.key, "[密钥已隐藏]")
    return message


def run_workflow(service, tasks: list[dict], product_id: str, progress, previous: list[dict] | None = None) -> dict:
    job = {"id": uuid4().hex, "operation": "product_workflow", "product_id": product_id,
           "created_at": now_iso(), "state": "running", "result": {"entries": deepcopy(previous or [])}}
    service.jobs.save(job)
    for index, task in enumerate(tasks):
        entry = deepcopy(task)
        def report(message):
            progress(json.dumps({"completed": index, "total": len(tasks), "message": message}, ensure_ascii=False))
        report(f"{index + 1}/{len(tasks)} · {entry['caption']}")
        try:
            result = service.generate(AIRequest(**entry["request"]), report)
            entry["result"] = asdict(result)
            # entry["error"] = "\n".join(result.errors)
            # 2026-10-13：本次修改原因：空响应按失败处理，避免清空原候选，异常留档统一隐藏密钥。
            entry["error"] = safe_error(service, "\n".join(result.errors))
            if not result.assets and not any(text.strip() for text in result.candidates):
                raise ValueError(entry["error"] or "模型未返回有效候选，请调整要求后重试。")
        except Exception as error:
            entry["error"] = safe_error(service, error)
            entry["result"] = None
        # rows = job["result"]["entries"]
        # 2026-10-13：本次修改原因：失败重试使用失败时的请求，不能把新 Prompt 冒充旧候选的来源。
        if entry.get("error"):
            entry["retry_request"] = deepcopy(entry["request"])
        else:
            entry.pop("retry_request", None)
        rows = job["result"]["entries"]
        found = next((position for position, row in enumerate(rows) if row["id"] == entry["id"]), None)
        if found is None:
            rows.append(entry)
        else:
            # 单张重做失败时保留原候选，错误提示仍可见。
            if not entry["result"] and rows[found].get("result"):
                # entry["result"] = rows[found]["result"]
                # 2026-10-13：本次修改原因：重做失败保留原候选对应的实际请求，另存失败请求便于重试与追溯。
                entry["result"] = rows[found]["result"]
                entry["request"] = rows[found]["request"]
            rows[found] = entry
        service.jobs.save(job)
        progress(json.dumps({"completed": index + 1, "total": len(tasks),
                             "message": f"已处理 {index + 1}/{len(tasks)} · {entry['caption']}"}, ensure_ascii=False))
    job["state"] = "partial" if any(row["error"] for row in job["result"]["entries"]) else "completed"
    service.jobs.save(job)
    return job


def sku_locator(sku: dict) -> dict:
    identity = sku.get("source_sku_id") or sku.get("platform_sku")
    return ({"identity": identity} if identity else
            {"spec1": sku.get("spec1", ""), "spec2": sku.get("spec2", ""), "specs": sku.get("specs", {})})


def resolve_sku(product: dict, locator: dict) -> tuple[int, dict]:
    matches = [(index, sku) for index, sku in enumerate(product.get("skus", [])) if sku_locator(sku) == locator]
    if len(matches) != 1:
        raise ValueError("目标 SKU 已删除或无法唯一识别，请核对规格后重新选择。")
    return matches[0]


def replace_html_image(html: str, address: str, values: list[str]) -> str:
    # 同时处理单/双引号和 HTML 实体，不重建其他正文。
    from html import unescape
    replacement = "".join(f'<img src="{escape(value, quote=True)}" width="640" />' for value in values)
    def substitute(match):
        # src = re.search(r'\bsrc\s*=\s*([\x22\x27])(.*?)\1', match.group(), re.I | re.S)
        # return replacement if src and unescape(src.group(2)) == address else match.group()
        # 2026-10-13：本次修改原因：图片替换复用链接解析，兼容未加引号的 src 与 HTML 实体。
        return replacement if address in description_images(match.group()) else match.group()
    return re.sub(r"<img\b[^>]*>", substitute, html, flags=re.I)


def apply_changes(current: dict, changes: list[dict]) -> dict:
    """先验证目标与最终内容，再返回副本；失败时表单不发生半应用。"""
    proposed = deepcopy(current)
    # for change in changes:
    #     target, value = change["target"], change["value"]
    # 2026-10-13：本次修改原因：先应用文案再合并图片，结果不依赖补丁顺序，并验证商品身份。
    ordered = sorted(changes, key=lambda change: change["target"]["field"] not in TEXT_TASKS)
    for change in ordered:
        target, value = change["target"], change["value"]
        if target.get("product_id") and target["product_id"] != current.get("id"):
            raise ValueError("候选属于其他商品，不能应用到当前草稿。")
        field = target["field"]
        if field in TEXT_TASKS:
            if current.get(field, "") != target["before"]:
                raise ValueError(f"{TEXT_TASKS[field]}在生成后已改变，请重新生成，避免覆盖手动修改。")
            value = str(value).strip()
            if not value:
                raise ValueError(f"{TEXT_TASKS[field]}候选为空。")
            if field == "description_html":
                value = clean_description(value)
                if target.get("keep_images"):
                    before_images = list(dict.fromkeys(description_images(target["before"]) + current.get("detail_images", [])))
                    value += detail_html("", [url for url in before_images if url not in description_images(value)])
            key = {"title": "title", "simple_description": "notesText", "description_html": "notes"}[field]
            if len(value) > TEXT_LIMITS[key]:
                raise ValueError(f"{TEXT_TASKS[field]}超过 {TEXT_LIMITS[key]} 字符，请缩短候选内容。")
            proposed[field] = value
        elif field == "sku":
            index, sku = resolve_sku(current, target["locator"])
            if sku != target["before"]:
                raise ValueError("目标 SKU 在生成后已修改，请重新选择并生成。")
            # if len(value) != 1:
            # 2026-10-13：本次修改原因：SKU 候选必须为非空单图列表，拒绝错误历史内容。
            if not isinstance(value, list) or len(value) != 1 or not value[0]:
                raise ValueError("一个 SKU 只能应用一张图，请仅勾选一个图片候选。")
            proposed["skus"][index]["image"] = value[0]
        elif field in {"images", "detail_images"}:
            # old = current.get(field, [])
            # if old != target["before"]:
            # 2026-10-13：本次修改原因：所有详情图操作均检查正文快照，防止更改生成后手动维护的正文。
            # if not isinstance(value, list) or not value or any(not isinstance(url, str) or not url.strip() for url in value):
            # 2026-10-14：本次修改原因：整商品方案可明确不采用某组全部图片；继续由最终保存校验必填要求。
            if not isinstance(value, list) or (not value and target.get("mode") != "compose") or any(not isinstance(url, str) or not url.strip() for url in value):
                raise ValueError("请选择有效的图片候选。")
            old = current.get(field, [])
            if field == "detail_images" and "html_before" in target and current.get("description_html", "") != target["html_before"]:
                raise ValueError("详情正文在生成后已修改，请重新生成，避免覆盖手动修改。")
            if old != target["before"]:
                raise ValueError("目标图片组在生成后已修改，请重新生成，避免替换错误位置。")
            mode, anchor = target["mode"], target.get("anchor", "")
            if mode == "replace":
                if target.get("html_only"):
                    if current.get("description_html", "") != target.get("html_before"):
                        raise ValueError("详情正文在生成后已修改，请重新选择正文图片。")
                    updated = old + value
                elif old.count(anchor) != 1:
                    raise ValueError("原图片已不存在或位置不唯一，请重新选择目标图。")
                else:
                    index = old.index(anchor)
                    updated = old[:index] + value + old[index + 1:]
            # elif mode == "replace_set":
            #     updated = value
            # 2026-10-14：本次修改原因：整组方案一次构造最终顺序，避免多张单图补丁互相覆盖。
            elif mode in {"replace_set", "compose"}:
                updated = value
            # else:
            #     updated = old + value
            # proposed[field] = list(dict.fromkeys(updated))
            # 2026-10-13：本次修改原因：只接受明确的追加或替换操作，错误模式不能默认为追加。
            elif mode == "append":
                updated = old + value
            else:
                raise ValueError("未知的图片应用方式，请重新选择。")
            proposed[field] = list(dict.fromkeys(updated))
            if field == "detail_images":
                html = proposed.get("description_html", "")
                # if mode == "replace":
                #     html = replace_html_image(html, anchor, value)
                # 2026-10-14：本次修改原因：未调序时就地替换详情图片保留图文位置；用户显式调序后按最终图片顺序重排。
                if mode == "compose":
                    placements = target.get("placements", [])
                    original_order = target.get("original_order", [])
                    retained = [item["source"] for item in placements if item["source"] and item["value"]]
                    expected = [url for url in original_order if url in retained]
                    sources = [item["source"] for item in placements]
                    new_at_end = not any(sources[index] for index in range(next((i for i, source in enumerate(sources) if not source), len(sources)), len(sources)))
                    if retained == expected and new_at_end:
                        replacements = {item["source"]: item["value"] for item in placements if item["source"]}
                        def replace_one(match):
                            urls = description_images(match.group())
                            if not urls or urls[0] not in replacements:
                                return match.group()
                            replacement = replacements[urls[0]]
                            if replacement == urls[0]:
                                return match.group()
                            return f'<img src="{escape(replacement, quote=True)}" width="640" />' if replacement else ""
                        html = re.sub(r"<img\b[^>]*>", replace_one, html, flags=re.I)
                    else:
                        html = with_detail_images(html, [])
                elif mode == "replace":
                    html = replace_html_image(html, anchor, value)
                # elif mode == "replace_set":
                #     for address in old:
                #         html = replace_html_image(html, address, [])
                # 2026-10-13：本次修改原因：整组替换同时移除正文独有旧图，避免新旧套图混排。
                elif mode == "replace_set":
                    html = with_detail_images(html, [])
                missing = [url for url in value if url not in description_images(html)]
                proposed["description_html"] = html + detail_html("", missing)
        else:
            raise ValueError("未知的 AI 应用目标。")
        for asset in change.get("assets", []):
            # proposed.setdefault("image_sizes", {})[asset["uri"]] = [asset["width"], asset["height"]]
            # 2026-10-13：本次修改原因：像素缓存沿用商品模型的字符串格式，避免后续图片列表类型不兼容。
            proposed.setdefault("image_sizes", {})[asset["uri"]] = f'{asset["width"]} × {asset["height"]}'
    before = Product.from_dict(current)
    after = Product.from_dict(proposed)
    existing = set(draft_limit_issues(before))
    # issues = [issue for issue in draft_limit_issues(after) if issue not in existing]
    # 2026-10-13：本次修改原因：按实际编辑前后差异校验回传正文，防止旧 manual_fields 影响长度判断。
    issues = [issue for issue in draft_limit_issues(after, before) if issue not in existing]
    if issues:
        raise ValueError("\n".join(issues))
    return proposed
