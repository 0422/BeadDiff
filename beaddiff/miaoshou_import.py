# 2026-10-12：本次修改原因：直接读取官方公共采集箱详情，建立可编辑本地副本并保留远端原始字段及稳定 SKU 键。
from __future__ import annotations

from copy import deepcopy
# 2026-10-12：本次修改原因：单条查询/数据库失败应保留其他导入成功结果，允许用户逐条核对失败原因。
import sqlite3
# 2026-10-12：本次修改原因：同步批次编号用于追溯逐商品的处理结果。
import uuid

# 2026-10-12：本次修改原因：批量详情限制并发，主协调线程顺序写库与记录进度。
from concurrent.futures import ThreadPoolExecutor, as_completed

from .content import description_images
from .miaoshou import MiaoshouAdapter, MiaoshouClient, detail_id
from .models import Product, SKU
from .storage import Repository
from .erp import ERPNotSentError

def _text(value) -> str:
    return "" if value is None else str(value)


def _dimensions(values: dict) -> str:
    parts = [values.get(key) for key in ("packageLength", "packageWidth", "packageHeight")]
    return "*".join(map(_text, parts)) if all(value is not None and value != "" for value in parts) else ""


def parse_miaoshou_detail(detail: dict, account_id: str) -> Product:
    remote = detail.get("editCommonCollectBoxDetail")
    if not isinstance(remote, dict) or not account_id:
        raise ValueError("采集箱详情或账号标识不完整。")
    target = str(detail_id(remote.get("commonCollectBoxDetailId", "")))
    sources = remote.get("sourceList") or []
    attributes = remote.get("sourceAttrs") or []
    certifications = remote.get("productCertifications") or []
    for rows in (sources, attributes, certifications):
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValueError("妙手货源、属性或认证数据结构无法识别，已停止导入。")
    pictures = remote.get("imgUrls") or []
    if not isinstance(pictures, list) or any(not isinstance(url, str) for url in pictures):
        raise ValueError("妙手主图字段不是图片链接列表，已停止导入。")
    guide = remote.get("guideInfo") or {}
    if not isinstance(guide, dict):
        raise ValueError("妙手说明书字段无法识别。")
    source = sources[0] if sources else {}
    product = Product(
        source=_text(source.get("source")) or "miaoshou", source_id=_text(source.get("sourceItemId")),
        site=_text(source.get("sourceSite")), source_url=_text(source.get("sourceItemUrl")),
        source_remark=_text(source.get("remark")), main_code=_text(remote.get("itemNum")),
        title=_text(remote.get("title")), simple_description=_text(remote.get("notesText")),
        description_html=_text(remote.get("notes")), images=list(pictures), currency="CNY",
        video=_text(remote.get("mainImgVideoUrl")), size_chart=_text(remote.get("sizeChart")),
        supply_price=_text(remote.get("price")), package_weight=_text(remote.get("weight")),
        package_dimensions=_dimensions(remote), instruction_manual=_text(guide.get("productGuideFileUrl")),
        certificate=_text(certifications[0].get("fileUrl")) if certifications else "",
        spec1_name=_text(remote.get("colorPropName")), spec2_name=_text(remote.get("sizePropName")),
        erp_original_id=target, erp_original_account=account_id, erp_imported=True,
        erp_remote_snapshot=deepcopy(remote), edit_tracking=True,
    )
    product.detail_images = description_images(product.description_html)
    for row in attributes:
        name, value = _text(row.get("name")), _text(row.get("value"))
        if name in product.attributes:
            product.warnings.append("远端有同名属性，界面显示首项；完整属性列表已保留，修改该属性会替换同名项。")
        elif name:
            product.attributes[name] = value
    maps = [remote.get(key) or {} for key in ("colorMap", "sizeMap", "saleProp3Map")]
    skus = remote.get("skuMap") or {}
    if any(not isinstance(value, dict) for value in maps + [skus]):
        raise ValueError("妙手规格字段不是对象，已停止导入。")
    dimension_names = [product.spec1_name, product.spec2_name, _text(remote.get("saleProp3Name"))]
    for key, values in skus.items():
        if not isinstance(key, str) or not key.startswith(";") or not key.endswith(";") or not isinstance(values, dict):
            raise ValueError("妙手 SKU 组合键或字段结构无法识别，已停止导入，未猜测规格。")
        parts = key[1:-1].split(";")
        if not 1 <= len(parts) <= 3:
            raise ValueError("妙手 SKU 超过三维或组合键格式不支持，请先在妙手核对。")
        parts += [""] * (3 - len(parts))
        names = []
        for index, part in enumerate(parts):
            option = maps[index].get(part) or {}
            if not isinstance(option, dict):
                raise ValueError("妙手规格选项无法识别。")
            names.append(_text(option.get("name")) or part)
        color = maps[0].get(parts[0]) or {}
        images = color.get("imgUrls") or []
        if not isinstance(images, list):
            raise ValueError("妙手规格图片组无法识别。")
        identity = "MS-SKU:" + key
        product.skus.append(SKU(
            source_sku_id=identity, platform_sku=_text(values.get("itemNum")),
            spec1=names[0], spec2=names[1], price=_text(values.get("price")), currency="CNY",
            stock=_text(values.get("stock")), weight=_text(values.get("weight")), dimensions=_dimensions(values),
            image=_text(color.get("imgUrl")) or (_text(images[0]) if images else ""),
            specs={dimension_names[index] or f"规格{index + 1}": name for index, name in enumerate(names) if name},
        ))
        product.erp_sku_links[identity] = key
    # if not product.main_code:
    #     product.warnings.append("妙手未提供产品主编号，请在编辑页补填。")
    # 2026-10-12：本次修改原因：文本增量更新不要求填补原主编号，新增/表格导出仍需补齐。
    if not product.main_code:
        # 2026-10-12：本次修改原因：撤下表格导出后只说明新增与更新所需的主编号。
        product.warnings.append("妙手未提供产品主编号；更新未改动字段会保留，新增商品前需补全。")
    # if any(parts.get("saleProp3Name") for parts in [remote]) or any(len(sku.specs) > 2 for sku in product.skus):
    # 2026-10-12：本次修改原因：第三规格的保留提示直接读取远端维度名。
    if remote.get("saleProp3Name") or any(len(sku.specs) > 2 for sku in product.skus):
        product.warnings.append("第三规格已完整保留；本版可修改商品文本和主图，三维 SKU 的修改请在妙手完成。")
    if len(sources) > 1 or len(certifications) > 1:
        product.warnings.append("多货源、多认证完整保留；界面显示首条，未编辑的其他条目随写回保留。")
    product.erp_update_baseline = {key: value for key, value in product.to_dict().items() if not key.startswith("erp_")}
    # 2026-10-12：本次修改原因：首次导入基线独立于后续更新基线，更新原商品后再新增副本仍提交全部加工内容。
    product.erp_import_baseline = deepcopy(product.erp_update_baseline)
    product.warnings = list(dict.fromkeys(product.warnings))
    return product


class MiaoshouImportService:
    def __init__(self, repository: Repository, adapter: MiaoshouAdapter):
        self.repository, self.adapter = repository, adapter

    # def import_products(self, client: MiaoshouClient, targets: list[str]) -> dict:
        # results = []
        # for target in dict.fromkeys(targets):
            # try:
                # if self.adapter.store.get().account_id != client.config.account_id:
                    # raise ValueError("账号已改变，请用当前账号重新查询。")
                # detail = client.detail(target)
                # product = parse_miaoshou_detail(client._safe(detail), client.config.account_id)
                # stored, created = self.repository.store_miaoshou_import(product)
                # results.append({"target_id": str(target), "product_id": stored.id,
                                # "title": stored.title, "state": "imported" if created else "existing"})
            # # except (ValueError, OSError, RuntimeError) as error:
            # # 2026-10-12：本次修改原因：官方读取错误和 SQLite 失败都作为单条导入失败，不丢弃之前成功导入的摘要。
            # except (ValueError, OSError, RuntimeError, sqlite3.Error, ERPNotSentError) as error:
                # results.append({"target_id": str(target), "state": "failed", "message": str(error)})
        # return {"results": results}

    # 2026-10-12：本次修改原因：接口导入持久留档，失败不丢已导入结果，重复商品保留本机修改。
    # def import_products(self, client: MiaoshouClient, targets: list[str]) -> dict:
    #     results = []
    #     batch_id = uuid.uuid4().hex
    #     for target in dict.fromkeys(targets):
    #         detail = {}
    #         try:
    #             if self.adapter.store.get().account_id != client.config.account_id:
    #                 raise ValueError("账号已改变，请用当前账号重新查询。")
    #             detail = client._safe(client.detail(target))
    #             product = parse_miaoshou_detail(detail, client.config.account_id)
    #             stored, created = self.repository.store_miaoshou_import(product)
    #             row = {"target_id": str(target), "product_id": stored.id, "title": stored.title,
    #                    "state": "imported" if created else "existing",
    #                    "message": "已导入，可进入商品加工。" if created else "本机已有，保留加工内容。"}
    #         except (ValueError, OSError, RuntimeError, sqlite3.Error, ERPNotSentError) as error:
    #             row = {"target_id": str(target), "state": "failed", "message": str(error)}
    #         try:
    #             self.repository.record_miaoshou_import(batch_id, client.config.account_id, row, detail)
    #         except (OSError, sqlite3.Error) as error:
    #             row["record_error"] = "同步记录未保存，请检查本机数据目录：" + str(error)
    #         results.append(row)
    #     return {"batch_id": batch_id, "results": results}

    # 2026-10-12：本次修改原因：先跳过已导入身份，再以最多三个并发只读请求复用连接池；逐条报告实际完成进度。
    def import_products(self, client: MiaoshouClient, targets: list[str], progress=None, *, workers: int = 3) -> dict:
        # 2026-10-12：本次修改原因：即使整批都是已导入商品，账号改变后也不能继续使用旧查询结果。
        if self.adapter.store.get().account_id != client.config.account_id:
            raise ValueError("账号已改变，请用当前账号重新查询。")
        targets = list(dict.fromkeys(str(detail_id(target)) for target in targets))
        known = self.repository.miaoshou_import_index(client.config.account_id)
        batch_id, results = uuid.uuid4().hex, {}
        counts = {"imported": 0, "existing": 0, "failed": 0}

        def notify(stage: str) -> None:
            if progress:
                progress({"total": len(targets), "completed": len(results), **counts, "message": stage})

        def save_result(target: str, row: dict, detail: dict) -> None:
            try:
                self.repository.record_miaoshou_import(batch_id, client.config.account_id, row, detail)
            except (OSError, sqlite3.Error) as error:
                row["record_error"] = "同步记录未保存，请检查本机数据目录：" + str(error)
            results[target] = row
            counts[row["state"]] += 1
            notify("正在同步公共采集箱")

        def fetch(target: str):
            if self.adapter.store.get().account_id != client.config.account_id:
                raise ValueError("账号已改变，请用当前账号重新查询。")
            detail = client._safe(client.detail(target))
            return parse_miaoshou_detail(detail, client.config.account_id), detail

        notify("正在检查本机已有商品")
        pending = []
        for target in targets:
            previous = known.get(target)
            if previous:
                save_result(target, {"target_id": target,
                    "product_id": "" if previous["archived"] else previous["product_id"],
                    "title": previous["title"], "state": "existing",
                    "message": "本机回收站已有，恢复后可继续加工" if previous["archived"] else "本机已有，跳过详情请求，保留加工内容"}, {})
            else:
                pending.append(target)
        if pending:
            with client.read_session(), ThreadPoolExecutor(max_workers=max(1, min(3, workers))) as pool:
                futures = {pool.submit(fetch, target): target for target in pending}
                # for future in as_completed(futures):
                # 2026-10-12：本次修改原因：串行模式按选择顺序留档；并发模式按真实完成时间报告进度。
                completed_futures = as_completed(futures) if workers > 1 else futures
                for future in completed_futures:
                    target, detail = futures[future], {}
                    try:
                        product, detail = future.result()
                        stored, created = self.repository.store_miaoshou_import(product)
                        row = {"target_id": target, "product_id": stored.id, "title": stored.title,
                               "state": "imported" if created else "existing",
                               "message": "已导入，可进入商品加工" if created else "本机已有，保留加工内容"}
                    except (ValueError, OSError, RuntimeError, sqlite3.Error, ERPNotSentError) as error:
                        row = {"target_id": target, "state": "failed", "message": str(error)}
                    save_result(target, row, detail)
        notify("同步完成")
        return {"batch_id": batch_id, "results": [results[target] for target in targets], **counts}
