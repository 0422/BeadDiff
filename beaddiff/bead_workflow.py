# 2026-10-15：本次修改原因：校验真实 AI 方案，按确认原料核算配方和成本，防止虚构原料进入商品。
from __future__ import annotations

from collections import Counter
from decimal import Decimal
import hashlib
import json
import re
from uuid import uuid4

from .ai.contracts import AIRequest
# from .beads import BeadDesign, MaterialItem, _money
# 2026-10-15：本次修改原因：读取历史快照时同样校验事实来源，旧资料不能仅凭确认标记将照片推断作为成分或尺寸。
from .beads import BeadDesign, MaterialItem, VISIBLE_FACT_FIELDS, _money
from .content import clean_description
from .models import Product, SKU

# 2026-10-15：本次修改原因：成品图片分别映射到 ERP 主图、详情和当前 SKU，允许单张实拍兼作主图及 SKU 图。
IMAGE_ROLES = {"main": "商品主图", "detail": "详情 / 佩戴图", "sku": "当前 SKU 图", "main_sku": "主图及当前 SKU"}


def parse_object(raw: str) -> dict:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
    try: value = json.loads(text)
    except (TypeError,ValueError) as error: raise ValueError("模型没有返回有效 JSON，请检查模型响应后重新生成") from error
    if not isinstance(value,dict): raise ValueError("模型结果必须为 JSON 对象")
    return value


def confirmed_facts(item: MaterialItem | dict) -> dict:
    facts = item.facts if isinstance(item,MaterialItem) else item.get("facts",{})
    states = item.fact_statuses if isinstance(item,MaterialItem) else item.get("fact_statuses",{})
    # return {key:value for key,value in facts.items() if states.get(key) == "confirmed"}
    sources = item.fact_sources if isinstance(item,MaterialItem) else item.get("fact_sources",{})
    return {key:value for key,value in facts.items() if states.get(key) == "confirmed" and value
            and (sources.get(key) in {"user", "supplier", "human"}
                 or (sources.get(key) == "vision" and key in VISIBLE_FACT_FIELDS))}


def design_request(design: BeadDesign, materials: list[MaterialItem]) -> AIRequest:
    inventory = [{"material_id":item.id,"code":item.code,"name":item.name,"kind":item.category,
                  "confirmed_facts":confirmed_facts(item),"observations":item.observations,
                  "unresolved":{key:value for key,value in item.facts.items() if item.fact_statuses.get(key) != "confirmed"},
                  "unit_cost":item.unit_cost or None,"currency":item.currency,
                  "available_quantity":item.available_quantity if item.track_inventory else None} for item in materials]
    reference_number = 0
    for row, item in zip(inventory, materials):
        if item.images:
            reference_number += 1
            row["reference_image_number"] = reference_number
    payload = {"requirements":design.requirements,"inventory":inventory}
    instruction = ('根据所选散珠和配件设计 3 个可实际打样、有辨识度的手链方向，说明配色、佩戴和展示建议。'
                   '只使用 inventory 的 material_id，不要求每种都用。不得添加未选线材和配件。名称仅是内部标签，不能当成已核实材质。区分确认事实和外观观察；不猜测石种、尺寸、孔径、认证或疗效。'
                   '顺序必须明确，sequence 按从线头开始的顺序列出沿线珠子/隔片，各段 quantity 为正整数；其他配件和按份计量的线材列在 components。'
                   '不得以估算值冒充腕围，未知连接方式列为风险。不要自行计算成本或库存。仅返回 JSON：'
                   '{"designs":[{"name":"方案名","rationale":"设计理由、配色、佩戴和视觉建议","sequence":[{"material_id":"ID","quantity":1}],"components":[{"material_id":"ID","quantity":1}],"warnings":["需打样核对"]}]}\n'
                   +json.dumps(payload,ensure_ascii=False))
    return AIRequest("bead_design",{"id":design.id,"category":"手链"},instruction=instruction,language="中文",
                     subject_images=[uri for item in materials for uri in item.images[:1]])


def normalize_candidate(value: dict, allowed: set[str]) -> dict:
    if not isinstance(value,dict) or not isinstance(value.get("name"),str) or not value["name"].strip(): raise ValueError("方案名称格式无效")
    normalized = {"id":uuid4().hex,"name":value["name"][:200],"rationale":str(value.get("rationale","")),"warnings":value.get("warnings",[])}
    for field in ("sequence","components"):
        lines = value.get(field,[])
        if not isinstance(lines,list) or len(lines) > 300: raise ValueError("排列段数无效")
        normalized[field] = []
        for line in lines:
            if not isinstance(line,dict) or line.get("material_id") not in allowed: raise ValueError("方案引用了未选择的原料")
            qty = line.get("quantity")
            if type(qty) is not int or not 1 <= qty <= 1000: raise ValueError("原料用量必须为 1～1000 的整数")
            normalized[field].append({"material_id":line["material_id"],"quantity":qty})
    if not normalized["sequence"]: raise ValueError("方案缺少串珠排列")
    if sum(line["quantity"] for line in normalized["sequence"]) > 1000: raise ValueError("单条手链的串珠数量过多")
    if not isinstance(normalized["warnings"],list): normalized["warnings"] = [str(normalized["warnings"])]
    normalized["warnings"] = [str(item) for item in normalized["warnings"]]
    return normalized


def evaluate(candidate: dict, materials: dict[str,MaterialItem], requirements: dict) -> dict:
    # 2026-10-15：本次修改原因：人工编辑或旧草稿同样经过结构校验，空排列和错误用量不能进入锁定配方。
    candidate = normalize_candidate(candidate, set(materials))
    for line in candidate["sequence"]:
        if materials[line["material_id"]].category in {"cord", "packaging"}:
            raise ValueError("线材和包装请放入配件用量，不能作为串珠排列段")
    quantities = Counter()
    for line in candidate.get("sequence",[]) + candidate.get("components",[]): quantities[line["material_id"]] += line["quantity"]
    if not quantities: raise ValueError("配方不能为空")
    costs: dict[str,Decimal] = {}; missing_cost = []; warnings = list(candidate.get("warnings",[])); stock = []; unknown_stock = []
    bom = []
    for item_id,qty in quantities.items():
        item = materials.get(item_id)
        if not item or item.state == "archived": raise ValueError("配方中原料已不存在或已归档")
        amount = _money(item.unit_cost)
        if amount is None: missing_cost.append(item.code)
        else: costs[item.currency] = costs.get(item.currency,Decimal(0)) + amount*qty
        if item.track_inventory:
            stock.append(item.available_quantity//qty)
            if item.available_quantity < qty: warnings.append(item.code+" 库存不足")
        else: unknown_stock.append(item.code)
        for key,state in item.fact_statuses.items():
            if state != "confirmed" and (item.facts.get(key) or item.observations.get(key)): warnings.append(item.code+" 的 "+key+" 尚未确认")
        if not item.images: warnings.append(item.code+" 缺少原料图")
        bom.append({"material_id":item_id,"code":item.code,"quantity":qty,"unit_cost":item.unit_cost,"currency":item.currency,"revision":item.revision})
    length = Decimal(0); complete_length = True
    for line in candidate["sequence"]:
        item = materials[line["material_id"]]; facts = confirmed_facts(item)
        axial = _money(facts.get("axial_mm",""))
        if axial is None or axial <= 0: complete_length = False
        else: length += axial*line["quantity"]
    if missing_cost: warnings.append("缺少成本："+"、".join(missing_cost))
    if unknown_stock: warnings.append("库存未记录："+"、".join(unknown_stock))
    if not complete_length: warnings.append("沿线占长资料不全，需打样确认长度")
    if not any(materials[key].category in {"cord", "clasp"} for key in quantities):
        warnings.append("未登记连接材料，请补充线材或扣件并核实组装方式")
    limit = _money(requirements.get("cost_limit","")); limit_currency = requirements.get("cost_currency","CNY")
    if limit is not None:
        if missing_cost or set(costs) != {limit_currency}: warnings.append("成本缺失或币种不同，无法校验成本上限")
        elif costs.get(limit_currency,Decimal(0)) > limit: warnings.append("材料成本超过设定上限")
    cost_text = " + ".join(f"{amount:.2f} {code}" for code,amount in sorted(costs.items())) or "未知"
    if missing_cost and costs: cost_text += "（部分成本）"
    return {"bom":bom,"cost":cost_text,"length":f"{length:f} mm（沿线占长，非腕围）" if complete_length else "待实测",
            "stock":("部分原料可做 "+str(min(stock))+" 件，其余未知") if stock and unknown_stock else (f"可做 {min(stock)} 件" if stock else "未知"),
            "warnings":list(dict.fromkeys(warnings))}


def snapshot_key(design: BeadDesign) -> str:
    value = {"candidate":design.selected_candidate_id,"bom":design.locked_bom,"materials":design.material_snapshot,
             "requirements":design.requirements,"sequence":next((c for c in design.candidates if c["id"] == design.selected_candidate_id),{})}
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:24]


def listing_request(design: BeadDesign) -> AIRequest:
    candidate = next(c for c in design.candidates if c["id"] == design.selected_candidate_id)
    facts = {key:{"code":value["code"],"confirmed_facts":confirmed_facts(value)} for key,value in design.material_snapshot.items() if key in {line["material_id"] for line in design.locked_bom}}
    instruction = ('为锁定手链生成电商 Listing 参考。仅使用确认事实；配方是设计，尚未实物验证。不得宣称疗效、天然石、贵金属、环保或认证，除非确认资料明确提供；寓意仅作文化表达。'
                   '不要编造售价、库存、腕围、包装和性能。DIY 与成品必须符合指定形式。输出 JSON {"title":"","bullets":[""],"description_html":"静态HTML段落","image_briefs":["主图","细节图","佩戴概念图","SKU图"],"warnings":["需核实信息"]}。\n'
                   +json.dumps({"requirements":design.requirements,"candidate":candidate,"bom":design.locked_bom,"materials":facts},ensure_ascii=False))
    return AIRequest("bead_listing",{"id":design.id,"category":"手链"},instruction=instruction,language=design.requirements.get("language") or "English")


def normalize_listing(value: dict) -> dict:
    if not isinstance(value.get("title"),str) or not value["title"].strip(): raise ValueError("Listing 缺少标题")
    if not isinstance(value.get("bullets"),list) or any(not isinstance(x,str) for x in value["bullets"]): raise ValueError("卖点格式无效")
    if not isinstance(value.get("description_html"),str): raise ValueError("详情格式无效")
    return {"title":value["title"].strip(),"bullets":value["bullets"],"description_html":clean_description(value["description_html"]),
            "image_briefs":[str(x) for x in value.get("image_briefs",[])[:8]] if isinstance(value.get("image_briefs"),list) else [],
            "warnings":[str(x) for x in value.get("warnings",[])] if isinstance(value.get("warnings",[]),list) else [str(value["warnings"])],
            "images":[],"images_confirmed":False}


def image_request(design: BeadDesign, purposes: list[str]) -> AIRequest:
    candidate = next(c for c in design.candidates if c["id"] == design.selected_candidate_id)
    # mapping = [{"material_id":key,"code":value["code"],"confirmed_facts":confirmed_facts(value),"reference_image_number":index+1} for index,(key,value) in enumerate(design.material_snapshot.items()) if value.get("images")]
    # images = [value["images"][0] for value in design.material_snapshot.values() if value.get("images")]
    # 2026-10-15：本次修改原因：只传实际采用的原料，跳过无图片原料后重新编号，防止图文错配。
    used = {line["material_id"] for line in design.locked_bom}
    references = [(key,value) for key,value in design.material_snapshot.items() if key in used and value.get("images")]
    mapping = [{"material_id":key,"code":value["code"],"confirmed_facts":confirmed_facts(value),"reference_image_number":index+1} for index,(key,value) in enumerate(references)]
    images = [value["images"][0] for _,value in references]
    missing = [value["code"] for key,value in design.material_snapshot.items() if key in used and not value.get("images")]
    if missing: raise ValueError("采用的原料缺少图片："+"、".join(missing)+"。请补图后重新锁定配方，或上传实物打样图")
    return AIRequest("bead_image",{"id":design.id,"category":"手链"},language=design.requirements.get("language") or "English",
                     instruction="按锁定配方将原料参考图组装为手链设计概念图。严格遵循原料编号、数量和排列，不添加未选配件，不改变原料颜色和表面质感。原料图不是成品图。"+json.dumps({"materials":mapping,"candidate":candidate,"bom":design.locked_bom,"mode":design.requirements.get("mode")},ensure_ascii=False),
                     subject_images=images,slots=purposes)


def make_product(design: BeadDesign, price: str, currency: str) -> Product:
    listing = design.listing
    # images = [row["uri"] for row in listing.get("images",[]) if row.get("selected")]
    # 2026-10-15：本次修改原因：明确商品主图、详情和 SKU 的交接字段，并在汇总前校验配方快照。
    selected = [row for row in listing.get("images",[]) if row.get("selected")]
    images = list(dict.fromkeys(row["uri"] for row in selected if row.get("role") in {"main", "main_sku"}))
    details = list(dict.fromkeys(row["uri"] for row in selected if row.get("role") == "detail"))
    sku_images = list(dict.fromkeys(row["uri"] for row in selected if row.get("role") in {"sku", "main_sku"}))
    if not listing.get("title") or not images: raise ValueError("请先完成 Listing，并勾选至少一张成品图")
    if len(images) > 15: raise ValueError("商品主图最多 15 张，请减少采用数量或改为详情图")
    if len(sku_images) != 1: raise ValueError("请采用一张当前 SKU 图，或将一张主图设为“主图及当前 SKU”")
    if any(row.get("role") not in IMAGE_ROLES for row in selected): raise ValueError("请为采用图片选择用途")
    if price and (_money(price) is None or _money(price) <= 0): raise ValueError("售价请填写正数或留空")
    if not re.fullmatch(r"[A-Z]{3}", currency): raise ValueError("销售币种请填写三位大写代码，例如 USD 或 CNY")
    if not design.id or not design.locked_bom or not design.selected_candidate_id: raise ValueError("请先保存设计并锁定配方")
    candidate = next((c for c in design.candidates if c.get("id") == design.selected_candidate_id), None)
    if not candidate: raise ValueError("锁定方案不存在，请重新核对配方")
    normalized = normalize_candidate(candidate, set(design.material_snapshot))
    expected = Counter()
    actual = Counter()
    for line in normalized["sequence"] + normalized["components"]: expected[line["material_id"]] += line["quantity"]
    for line in design.locked_bom: actual[line["material_id"]] += line["quantity"]
    if expected != actual: raise ValueError("锁定配方与排列不一致，请重新核对")
    if not listing.get("images_confirmed"): raise ValueError("请先人工核对采用图中的原料、数量、排列和 SKU 一致性")
    key = snapshot_key(design)
    attrs = {}
    for line in design.locked_bom:
        value = design.material_snapshot[line["material_id"]]
        attrs[value["code"]] = "；".join(k+"："+str(v) for k,v in confirmed_facts(value).items())
    return Product(source="design",source_route="bead_chain",source_ref_id=design.id,design_version_id=key,
                   main_code="BD-CHAIN-"+design.id[:8].upper(),title=listing["title"],currency=currency,
                   category="手链",simple_description="\n".join(listing.get("bullets",[])),description_html=clean_description(listing.get("description_html","")),
                   images=images,detail_images=details,attributes=attrs,spec1_name="款式",skus=[SKU(platform_sku="BC-"+key[:8].upper(),spec1=design.requirements.get("mode","成品手链"),price=price,currency=currency,image=sku_images[0])],
                   warnings=["设计概念图需通过实物打样核实；售价、库存和宣传信息须在商品审核时确认"],
                   bom_snapshot={"version":key,"bom":design.locked_bom,"materials":design.material_snapshot,"candidate":candidate,"requirements":design.requirements,"images_confirmed":True,"adopted_images":selected})
