# 2026-10-14：本次修改原因：整商品素材清单、加工方案、断点任务和最终图片组共同保存，统一使用设置中的当前模型。
from __future__ import annotations
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import re
from uuid import uuid4
from .contracts import AIRequest
from .workflow import TEXT_TASKS, safe_error, sku_locator
from ..content import description_images
from ..models import now_iso

GROUPS = {"images": "主图 / 轮播", "detail_images": "详情图", "sku": "SKU 图", "text": "商品文案"}
ACTIONS = {"keep": "保留", "adjust": "调整", "remake": "重做", "omit": "不采用", "new": "补充新图", "rewrite": "改写"}
GENERATE = {"adjust", "remake", "new", "rewrite"}

def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()

def relevant(product):
    return {key: deepcopy(product.get(key)) for key in
            ("id", "title", "simple_description", "description_html", "images", "detail_images", "skus", "attributes", "category")}

def image_row(group, address, purpose, bindings=None):
    return {"id": uuid4().hex, "group": group, "original": address, "sources": [address] if address else [],
            "purpose": purpose, "action": "keep", "instruction": "", "bindings": bindings or [],
            "versions": [], "choice": "original", "approved": False}

def new_draft(product):
    rows = []
    for group in ("images", "detail_images"):
        addresses = list(product.get(group, []))
        if group == "detail_images":
            addresses = description_images(product.get("description_html", "")) + addresses
        for index, address in enumerate(dict.fromkeys(filter(None, addresses))):
            purpose = "首图" if group == "images" and index == 0 else f"{GROUPS[group]} {index + 1}"
            rows.append(image_row(group, address, purpose))
    shared = {}
    for index, sku in enumerate(product.get("skus", [])):
        address = sku.get("image", "")
        key = address or f"empty-{index}"
        binding = {"locator": sku_locator(sku), "before": deepcopy(sku),
                   "caption": " / ".join(filter(None, [sku.get("spec1"), sku.get("spec2"), sku.get("platform_sku")])) or f"规格 {index + 1}"}
        if key not in shared:
            shared[key] = image_row("sku", address, binding["caption"])
            rows.append(shared[key])
        shared[key]["bindings"].append(binding)
    for row in shared.values():
        if len(row["bindings"]) > 1:
            row["purpose"] = row["bindings"][0]["caption"] + f" 等 {len(row['bindings'])} 个规格"
    for field, caption in TEXT_TASKS.items():
        rows.append({"id": uuid4().hex, "group": "text", "field": field, "original": product.get(field, ""),
                     "purpose": caption, "action": "keep", "instruction": "", "sources": [], "bindings": [],
                     "versions": [], "choice": "original", "approved": False})
    return {"version": 1, "id": uuid4().hex, "product_id": product["id"], "base": deepcopy(product), "rows": rows,
            "queue": [], "stage": 0, "group": 0, "applied": False, "plan_summary": "",
            "options": {"instruction": "", "reference_prompt": "", "reference_id": "", "language": "English",
                        "size": "1024x1024", "count": 1, "vision": True, "reference_images": []}}


# 2026-10-14：本次修改原因：白底图按类目模板直接准备完整 Listing，复用现有队列、失败续做与审核应用，不再要求逐张手工选调整。
def white_listing_draft(product, defaults):
    issues = defaults.problems(require_category=True)
    if issues:
        raise ValueError('\n'.join(issues))
    sources = list(dict.fromkeys(product.get('images', [])))
    if not sources:
        raise ValueError('上传白底图窗口 → 选择白底图 / 实物图：添加当前商品主体图。')
    draft = new_draft(product)
    guard = ('只使用商品已确认的实物事实，不推测材质、数量、认证、品牌或尺寸。'
             '建档的默认款、物流尺寸、重量、价格和库存是占位预设，不作为文案或尺寸图事实。'
             '保持商品本体结构和颜色，不虚构配件、功能、透视角度或包装清单。')
    draft['options'].update(instruction=defaults.instruction + '\n' + guard, language=defaults.language, count=1, vision=True)
    draft['plan_summary'] = ('白底图完整 Listing；类目：' + defaults.category +
        f'；主图 {max(defaults.main_count, len(sources))} 张、详情图 {defaults.detail_count} 张、全部 SKU 图、标题、简述和详情正文。')
    draft['origin'] = 'white_listing'
    main_purposes = ['白底首图：清楚呈现商品主体', '主体细节：展示可见结构与质感', '用途展示：基于已确认用途',
                     '外观展示：不改变真实款式', '卖点展示：仅使用已确认信息']
    detail_purposes = ['详情开篇：产品整体与用途', '细节展示：实际结构与质感', '使用说明：仅使用已确认信息',
                       '商品信息：仅展示已确认属性']
    for row in draft['rows']:
        if row['group'] == 'text':
            row.update(action='rewrite', instruction=guard)
        elif row['group'] == 'sku':
            row.update(action='adjust', instruction='按绑定 SKU 的实物保持款式和颜色；统一白底、构图与光线。')
        elif row['group'] == 'images':
            index = sum(1 for item in draft['rows'][:draft['rows'].index(row)] if item['group'] == 'images')
            row.update(action='remake', purpose=main_purposes[index % len(main_purposes)], instruction=guard)
        else:
            row.update(action='remake', instruction=guard)
    existing_main = sum(row['group'] == 'images' for row in draft['rows'])
    for index in range(existing_main, defaults.main_count):
        row = image_row('images', '', main_purposes[index % len(main_purposes)])
        row.update(action='new', sources=sources[:], instruction=guard)
        draft['rows'].append(row)
    existing_detail = sum(row['group'] == 'detail_images' for row in draft['rows'])
    for index in range(existing_detail, defaults.detail_count):
        row = image_row('detail_images', '', detail_purposes[index % len(detail_purposes)])
        row.update(action='new', sources=sources[:], instruction=guard)
        draft['rows'].append(row)
    draft['stage'] = 1
    validate_draft(draft, product['id'])
    return draft


def validate_draft(draft, product_id):
    if (not isinstance(draft, dict) or draft.get("version") != 1 or draft.get("product_id") != product_id
            or not isinstance(draft.get("id"), str) or not isinstance(draft.get("base"), dict)
            or draft["base"].get("id") != product_id or not isinstance(draft.get("options"), dict)
            or not isinstance(draft.get("rows"), list) or not isinstance(draft.get("queue"), list)):
        raise ValueError("加工草稿格式或版本不受支持。")
    ids = set()
    for row in draft["rows"]:
        if (not isinstance(row, dict) or not isinstance(row.get("id"), str) or row["id"] in ids
                or row.get("group") not in GROUPS or row.get("action") not in ACTIONS
                or not all(isinstance(row.get(key), str) for key in ("original", "purpose", "instruction", "choice"))
                or not isinstance(row.get("sources"), list) or not all(isinstance(url, str) for url in row["sources"])
                or not isinstance(row.get("bindings"), list) or not isinstance(row.get("versions"), list)):
            raise ValueError("加工草稿包含损坏的素材记录。")
        if row["group"] == "text" and row.get("field") not in TEXT_TASKS:
            raise ValueError("加工草稿中的文案字段无效。")
        for binding in row["bindings"]:
            if not isinstance(binding, dict) or not isinstance(binding.get("locator"), dict) or not isinstance(binding.get("before"), dict):
                raise ValueError("加工草稿中的规格绑定无效。")
        for version in row["versions"]:
            if (not isinstance(version, dict) or not isinstance(version.get("id"), str) or not isinstance(version.get("request"), dict)
                    or (row["group"] == "text" and not isinstance(version.get("value"), str))
                    or (row["group"] != "text" and (not isinstance(version.get("value"), dict)
                        or not isinstance(version["value"].get("uri"), str)))):
                raise ValueError("加工草稿中的候选版本无效。")
        ids.add(row["id"])
    queue_ids = set()
    for task in draft["queue"]:
        if (not isinstance(task, dict) or not isinstance(task.get("id"), str) or task["id"] in queue_ids
                or task.get("row_id") not in ids or not isinstance(task.get("request"), dict)
                or task.get("state") not in {"waiting", "running", "completed", "failed", "superseded"}):
            raise ValueError("加工草稿中的任务记录无效。")
        queue_ids.add(task["id"])
    options = draft["options"]
    if (not all(isinstance(options.get(key), str) for key in ("instruction", "reference_prompt", "reference_id", "language", "size"))
            or type(options.get("count")) is not int or not 1 <= options["count"] <= 4
            or not isinstance(options.get("reference_images"), list)
            or not all(isinstance(url, str) for url in options["reference_images"])
            or type(draft.get("stage")) is not int or draft["stage"] not in (0, 1, 2)):
        raise ValueError("加工草稿的参数无效。")

    # 2026-10-14：本次修改原因：恢复前验证界面必需字段和操作类别，损坏文件保留原样且不覆盖商品。
    if (type(draft.get("group")) is not int or draft["group"] not in range(len(GROUPS))
            or type(draft.get("applied")) is not bool or not isinstance(draft.get("plan_summary"), str)
            or type(options.get("vision")) is not bool):
        raise ValueError("加工草稿的页面状态无效。")
    for row in draft["rows"]:
        allowed = {"keep", "rewrite"} if row["group"] == "text" else ({"keep", "adjust", "remake"} if row["group"] == "sku" else {"keep", "adjust", "remake", "new", "omit"})
        version_ids = [version["id"] for version in row["versions"]]
        if (row["action"] not in allowed or type(row.get("approved")) is not bool
                or len(set(version_ids)) != len(version_ids)
                or row["choice"] not in {"original", "omit", *version_ids}
                or row["group"] == "sku" and (not row["bindings"] or row["choice"] == "omit")):
            raise ValueError("加工草稿的处理方式或版本选择无效。")
        for binding in row["bindings"]:
            if not isinstance(binding.get("caption"), str):
                raise ValueError("加工草稿的规格名称无效。")
        for version in row["versions"]:
            if row["group"] != "text" and any(type(version["value"].get(key)) is not int for key in ("width", "height")):
                raise ValueError("加工草稿的图片尺寸无效。")
    fields = [row["field"] for row in draft["rows"] if row["group"] == "text"]
    if sorted(fields) != sorted(TEXT_TASKS):
        raise ValueError("加工草稿没有准确覆盖商品文案字段。")
    for task in draft["queue"]:
        try:
            AIRequest(**task["request"])
        except TypeError as error:
            raise ValueError("加工草稿中的请求格式无效。") from error
        if not isinstance(task.get("signature"), str) or type(task.get("slot")) is not int or not isinstance(task.get("error"), str):
            raise ValueError("加工草稿中的任务进度无效。")
    return draft

class ProcessingStore:
    def __init__(self, data_dir):
        self.root = Path(data_dir) / "ai_processing"
    def path(self, product_id):
        return self.root / (digest(product_id) + ".json")
    def load(self, product_id):
        path = self.path(product_id)
        if not path.exists():
            return None
        try:
            draft = validate_draft(json.loads(path.read_text(encoding="utf-8")), product_id)
        except (ValueError, TypeError, KeyError) as error:
            raise ValueError("加工草稿无法读取；原文件已保留，修复后再保存。") from error
        for task in draft["queue"]:
            if task["state"] == "running":
                task["state"] = "waiting"
        return draft
    def save(self, draft):
        validate_draft(draft, draft["product_id"])
        self.load(draft["product_id"])
        self.root.mkdir(parents=True, exist_ok=True)
        value = deepcopy(draft)
        value["updated_at"] = now_iso()
        target = self.path(draft["product_id"])
        temporary = target.with_name(target.name + "." + uuid4().hex + ".tmp")
        try:
            temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)

def active_model(service, category, vision=False):
    profile = service.config.get(category=category)
    if profile.category != category:
        raise ValueError("请在设置 → AI 模型中为对应类别设定当前模型。")
    if vision and category == "text" and not profile.supports_vision:
        raise ValueError("当前文本模型未启用图片理解。请到设置 → AI 模型调整，或在高级参数中关闭看图。")
    return profile

def model_summary(service):
    names = []
    for category, caption in (("text", "文本"), ("image", "图片")):
        try:
            names.append(caption + "：" + active_model(service, category).caption)
        except ValueError:
            names.append(caption + "：未配置")
    return " · ".join(names)

def planning_request(service, draft):
    options = draft["options"]
    images = list(dict.fromkeys(row["original"] for row in draft["rows"] if row["group"] != "text" and row["original"])) if options["vision"] else []
    refs = options["reference_images"] if options["vision"] else []
    profile = active_model(service, "text", bool(images or refs))
    inventory = [{"id": row["id"], "group": row["group"], "purpose": row["purpose"], "action": row["action"],
                  "instruction": row["instruction"], "image_number": images.index(row["original"]) + 1 if row["original"] in images else None,
                  "sku_names": [item["caption"] for item in row["bindings"]],
                  "current_text": row["original"] if row["group"] == "text" else ""} for row in draft["rows"]]
    guide = """为当前商品制定可审核的整套加工方案，先规划，不生成图片。
逐项检查素材；同一商品保持颜色、形状、结构、数量和规格一致。参考只借鉴表达和视觉风格。
尺寸、认证、包装数量等不明信息不要猜；信息图以已确认事实为准。不要把不同 SKU 的图互换。
没有图片输入时只依据文案和现有用途规划，不声称看到了画面。尊重用户已填写的单项要求。
仅返回 JSON 对象：
{"summary":"整体思路和需人工核实的信息","rows":[{"id":"清单原ID","action":"keep/adjust/remake/omit，文案仅keep/rewrite","purpose":"用途","instruction":"本项要求"}],
"additions":[{"group":"images或detail_images","source_ids":["清单中的图片ID"],"purpose":"补图用途","instruction":"生成要求"}]}
rows 必须恰好覆盖每个原ID一次，不得增加、遗漏、改写ID；顺序即各组展示顺序。
SKU 不能 omit，不能新增或修改规格绑定。只建议必要的补图，additions 最多12项；不输出URL。
"""
    instruction = guide + "\n本次要求：" + options["instruction"] + "\n素材清单：" + json.dumps(inventory, ensure_ascii=False)
    return AIRequest("product_plan", deepcopy(draft["base"]), model_id=profile.id, instruction=instruction,
                     language="中文", reference_text=options["reference_prompt"], subject_images=images, reference_images=refs)

def accept_plan(draft, raw):
    fence = chr(96) * 3
    value = json.loads(re.sub("^" + fence + r"(?:json)?\s*|\s*" + fence + "$", "", raw.strip()))
    if not isinstance(value, dict) or not isinstance(value.get("rows"), list):
        raise ValueError("模型没有返回完整加工方案，当前计划已保留。")
    source = {row["id"]: row for row in draft["rows"]}
    proposed = value["rows"]
    if any(not isinstance(item, dict) for item in proposed):
        raise ValueError("方案条目格式不正确。")
    identifiers = [item.get("id") for item in proposed]
    if any(not isinstance(key, str) for key in identifiers) or len(identifiers) != len(source) or len(set(identifiers)) != len(identifiers) or set(identifiers) != set(source):
        raise ValueError("方案没有准确覆盖全部素材，当前计划已保留。")
    output, rows = deepcopy(draft), []
    for item in proposed:
        row = deepcopy(source[item["id"]])
        allowed = {"keep", "rewrite"} if row["group"] == "text" else ({"keep", "adjust", "remake"} if row["group"] == "sku" else {"keep", "adjust", "remake", "omit", "new"})
        if item.get("action") not in allowed or not all(isinstance(item.get(key), str) for key in ("purpose", "instruction")):
            raise ValueError("方案操作或生成要求无效。")
        row.update({key: item[key] for key in ("action", "purpose", "instruction")})
        row["approved"], row["choice"] = False, "omit" if row["action"] == "omit" else "original"
        rows.append(row)
    additions = value.get("additions", [])
    if not isinstance(additions, list) or len(additions) > 12:
        raise ValueError("方案补图数量或格式不正确。")
    for item in additions:
        if (not isinstance(item, dict) or item.get("group") not in {"images", "detail_images"}
                or not isinstance(item.get("source_ids"), list) or not item["source_ids"]
                or not all(isinstance(item.get(key), str) and item[key].strip() for key in ("purpose", "instruction"))):
            raise ValueError("补图必须指定用途、要求和商品素材。")
        ids = item["source_ids"]
        if any(not isinstance(key, str) or key not in source or source[key]["group"] == "text" or not source[key]["original"] for key in ids):
            raise ValueError("补图引用了未知素材。")
        row = image_row(item["group"], "", item["purpose"])
        row.update(action="new", instruction=item["instruction"], sources=list(dict.fromkeys(source[key]["original"] for key in ids)))
        rows.append(row)
    output.update(rows=rows, plan_summary=str(value.get("summary", "")), stage=1)
    return output

def make_request(service, draft, row):
    options, product = draft["options"], deepcopy(draft["base"])
    is_text = row["group"] == "text"
    sources = list(dict.fromkeys(row["sources"]))
    if is_text:
        sources = list(dict.fromkeys(item["original"] for item in draft["rows"] if item["group"] == "images" and item["original"])) if options["vision"] else []
    elif not sources:
        raise ValueError(f"「{row['purpose']}」缺少商品主体图，请打开卡片补充素材。")
    if row["group"] == "sku":
        product["skus"] = [deepcopy(binding["before"]) for binding in row["bindings"]]
    refs = options["reference_images"] if not is_text or options["vision"] else []
    profile = active_model(service, "text" if is_text else "image", bool(sources or refs))
    instruction = "\n".join(filter(None, [options["instruction"], "整体方案：" + draft.get("plan_summary", ""),
                  "本项用途：" + row["purpose"], "处理方式：" + ACTIONS[row["action"]], row["instruction"]]))
    if row.get("field") == "description_html":
        instruction += "\n只生成详情文字的静态 HTML，不输出图片标签，图片由已确认的图片组单独管理。"
    return AIRequest(row["field"] if is_text else "image", product, model_id=profile.id,
                     instruction=instruction, language=options["language"], reference_text=options["reference_prompt"],
                     subject_images=sources, reference_images=refs, size=options["size"], count=options["count"] if is_text else 1)

def prepare_tasks(service, draft, row_ids=None, redo=False):
    output, scheduled = deepcopy(draft), []
    if output.get("applied"):
        raise ValueError("此方案已应用，请按当前商品开始新方案。")
    # chosen = set(row_ids) if row_ids is not None else None
    # for row in output["rows"]:
    # 2026-10-14：本次修改原因：改为保留或不采用后取消旧的未完成请求，防止过期任务反复提示可续做。
    chosen = set(row_ids) if row_ids is not None else None
    actions = {row["id"]: row["action"] for row in output["rows"]}
    for task in output["queue"]:
        if actions[task["row_id"]] not in GENERATE and task["state"] in {"waiting", "running", "failed"}:
            task["state"] = "superseded"
    for row in output["rows"]:
        if row["action"] not in GENERATE or chosen is not None and row["id"] not in chosen:
            continue
        request = asdict(make_request(service, output, row))
        count = 1 if row["group"] == "text" else output["options"]["count"]
        signature = digest(request)
        matching = [task for task in output["queue"] if task["row_id"] == row["id"] and task.get("signature") == signature and task["state"] != "superseded"] if not redo else []
        if not matching:
            for task in output["queue"]:
                if task["row_id"] == row["id"] and task["state"] in {"waiting", "failed", "running"}:
                    task["state"] = "superseded"
        for slot in range(count):
            task = next((item for item in matching if item.get("slot") == slot), None)
            if task is None:
                # task = {"id": uuid4().hex, "row_id": row["id"], "request": request, "signature": signature,
                # 2026-10-14：本次修改原因：每个版本独立保存请求快照，续做时更换模型不影响已完成版本的来源。
                task = {"id": uuid4().hex, "row_id": row["id"], "request": deepcopy(request), "signature": signature,
                        "slot": slot, "state": "waiting", "error": ""}
                output["queue"].append(task)
            if task["state"] != "completed":
                task["state"], task["error"] = "waiting", ""
                scheduled.append(task["id"])
    output["stage"] = 2
    return output, scheduled


# 2026-10-14：本次修改原因：续做仅重试未完成的快照任务，切换当前模型也不重复生成已成功的项目。
def resume_tasks(service, draft):
    output, scheduled = deepcopy(draft), []
    if output.get("applied"):
        raise ValueError("此方案已应用，请按当前商品开始新方案。")
    rows = {row["id"]: row for row in output["rows"]}
    for task in output["queue"]:
        row = rows[task["row_id"]]
        # if task["state"] not in {"waiting", "running", "failed"} or row["action"] not in GENERATE:
        #     continue
        # 2026-10-14：本次修改原因：续做尊重用户最新的保留选择，旧任务只保留历史。
        if task["state"] not in {"waiting", "running", "failed"}:
            continue
        if row["action"] not in GENERATE:
            task["state"] = "superseded"
            continue
        request = task["request"]
        category = "text" if row["group"] == "text" else "image"
        profile = active_model(service, category, bool(request.get("subject_images") or request.get("reference_images")))
        request["model_id"] = profile.id
        task.update(state="waiting", error="", signature=digest(request))
        scheduled.append(task["id"])
    output["stage"] = 2
    return output, scheduled

def run_tasks(service, store, draft, task_ids, report, pause=None):
    output, run_id = deepcopy(draft), uuid4().hex
    rows = {row["id"]: row for row in output["rows"]}
    def checkpoint(state):
        store.save(output)
        service.jobs.save({"id": run_id, "operation": "product_batch", "product_id": output["product_id"],
                           "created_at": output.get("updated_at", now_iso()), "state": state,
                           "result": {"draft": deepcopy(output)}})
    checkpoint("running")
    total, completed = len(task_ids), 0
    for identifier in task_ids:
        if pause is not None and pause.is_set():
            break
        task = next(item for item in output["queue"] if item["id"] == identifier)
        if task["state"] == "completed":
            continue
        row = rows[task["row_id"]]
        task["state"] = "running"
        checkpoint("running")
        report(json.dumps({"draft": output, "completed": completed, "total": total,
                           "message": f"正在处理 {completed + 1}/{total} · {row['purpose']}"}, ensure_ascii=False))
        try:
            result = service.generate(AIRequest(**task["request"]))
            values = result.candidates if row["group"] == "text" else [asdict(asset) for asset in result.assets]
            values = [value for value in values if value.strip()] if row["group"] == "text" else [value for value in values if value.get("uri")]
            if not values:
                raise ValueError("\n".join(result.errors) or "模型没有返回有效结果。")
            new_versions = []
            for value in values:
                version = {"id": uuid4().hex, "value": value, "request": deepcopy(task["request"]),
                           "model_caption": result.model_caption, "created_at": now_iso()}
                row["versions"].append(version)
                new_versions.append(version)
            row["choice"], row["approved"] = new_versions[0]["id"], False
            task["state"], task["error"] = "completed", ""
            completed += 1
        except Exception as error:
            task["state"], task["error"] = "failed", safe_error(service, error)
            checkpoint("partial")
            report(json.dumps({"draft": output, "completed": completed, "total": total,
                               "message": f"「{row['purpose']}」失败，已暂停后续任务；成功结果已保存。"}, ensure_ascii=False))
            return output
        checkpoint("running")
        report(json.dumps({"draft": output, "completed": completed, "total": total,
                           "message": f"已完成 {completed}/{total} · {row['purpose']}"}, ensure_ascii=False))
    checkpoint("completed" if completed == total else "paused")
    return output

def chosen_version(row):
    return next((version for version in row["versions"] if version["id"] == row["choice"]), None)

def final_value(row):
    if row["action"] == "omit" or row["choice"] == "omit":
        return ""
    version = chosen_version(row)
    if version and row["approved"]:
        return version["value"] if row["group"] == "text" else version["value"]["uri"]
    return row["original"]

def compose_changes(draft):
    if draft.get("applied"):
        raise ValueError("此方案已应用，请在手动修改页核对并保存。")
    base, rows, changes, product_id = draft["base"], draft["rows"], [], draft["product_id"]
    for row in rows:
        value = final_value(row)
        if row["group"] == "text" and value != row["original"]:
            changes.append({"target": {"field": row["field"], "before": base.get(row["field"], ""),
                                       "keep_images": True, "product_id": product_id}, "value": value})
        if row["group"] == "sku" and value != row["original"]:
            if not value:
                raise ValueError("SKU 图不能在加工方案中清空。")
            version = chosen_version(row)
            for binding in row["bindings"]:
                changes.append({"target": {"field": "sku", "locator": binding["locator"], "before": binding["before"],
                                           "product_id": product_id}, "value": [value],
                                "assets": [version["value"]] if version and row["approved"] else []})
    for group in ("images", "detail_images"):
        members = [row for row in rows if row["group"] == group]
        values = list(dict.fromkeys(filter(None, [final_value(row) for row in members])))
        before_urls = list(base.get(group, []))
        original_order = list(dict.fromkeys(description_images(base.get("description_html", "")) + before_urls)) if group == "detail_images" else before_urls
        if values == original_order:
            continue
        target = {"field": group, "before": before_urls, "mode": "compose", "product_id": product_id,
                  "html_before": base.get("description_html", ""),
                  "placements": [{"source": row["original"], "value": final_value(row)} for row in members],
                  "original_order": original_order}
        assets = [version["value"] for row in members if row["approved"] and (version := chosen_version(row))]
        changes.append({"target": target, "value": values, "assets": assets})
    return changes

def summary(draft):
    counts = {"keep": 0, "generate": 0, "omit": 0, "text": 0}
    for row in draft["rows"]:
        if row["action"] == "omit":
            counts["omit"] += 1
        elif row["group"] == "text":
            counts["text"] += row["action"] == "rewrite"
        elif row["action"] in GENERATE:
            counts["generate"] += 1
        else:
            counts["keep"] += 1
    return f"保留 {counts['keep']} 张 · 处理 {counts['generate']} 张 · 不采用 {counts['omit']} 张 · 改写 {counts['text']} 项文案"
