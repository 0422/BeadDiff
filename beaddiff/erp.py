# 2026-10-11：本次修改原因：两条商品路线共用 ERP 回传服务，区分新增、更新、明确失败及结果未知；不猜测妙手写回接口。
from __future__ import annotations

import json
# 2026-10-12：本次修改原因：发送前的检查记录失败也向用户反馈。
import sqlite3
# from dataclasses import dataclass
# 2026-10-11：本次修改原因：回执保存真实开放平台响应，供本地核查。
from dataclasses import dataclass, field
# from typing import Protocol
# 2026-10-12：本次修改原因：回传服务通过可选回调报告实际阶段，界面与无界面调用共用发送逻辑。
from typing import Callable, Protocol

from .content import description_images
from .models import Product
from .storage import Repository


MODE_LABELS = {"create": "新增加工后的商品", "update": "更新原采集商品"}
STATE_LABELS = {"blocked": "未发送", "sending": "发送中", "succeeded": "已传",
                "failed": "发送失败", "unknown": "结果未知"}
NOT_CONNECTED = (
    "妙手回传尚未接通。当前已验证的接口仅用于采集提交，不能写入修改后的商品。"
    "需要先确认对应采集箱的新增、更新及图片上传接口，再接入适配器。"
)


@dataclass(frozen=True)
class ERPRequest:
    transfer_id: str
    mode: str
    product: Product
    original_id: str
    # 2026-10-12：本次修改原因：适配器可报告查详情、图片准备和商品提交阶段，不改写商品快照。
    progress: Callable[[str], None] | None = None


@dataclass(frozen=True)
class ERPReceipt:
    mode: str
    target_id: str
    receipt_id: str
    # 2026-10-11：本次修改原因：标识来自真实响应，并附带账号指纹及成功更新的 SKU 对应关系。
    details: dict = field(default_factory=dict)


class ERPRejectedError(Exception):
    """适配器已确认妙手拒绝请求，且没有保存商品。"""
    # 2026-10-11：本次修改原因：失败也保留脱敏响应；凭证和签名不写入记录。
    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message)
        self.details = details or {}


# 2026-10-11：本次修改原因：读取详情/映射失败与可能已经保存的超时分开处理，避免发送前失败阻塞重试。
class ERPNotSentError(ERPRejectedError):
    """尚未调用商品新增/更新接口。"""


class ERPUncertainError(Exception):
    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message)
        self.details = details or {}


# 2026-10-11：本次修改原因：只有经过验证的渠道适配器才负责字段映射、登录态和实际发送；禁止复用 pfti 冒充写回。
class ERPAdapter(Protocol):
    @property
    def unavailable_reason(self) -> str: ...

    def validate(self, product: Product, mode: str) -> list[str]: ...

    def send(self, request: ERPRequest) -> ERPReceipt: ...


# class MiaoshouAdapter:
#     unavailable_reason = NOT_CONNECTED
#
#     def validate(self, product: Product, mode: str) -> list[str]:
#         return [self.unavailable_reason]
#
#     def send(self, request: ERPRequest) -> ERPReceipt:
#         raise ERPRejectedError(self.unavailable_reason)
# 2026-10-11：本次修改原因：保留旧占位实现，实际适配器移至 miaoshou.py，并延迟导入以避免循环依赖。


class ERPService:
    def __init__(self, repository: Repository, adapter: ERPAdapter | None = None):
        self.repository = repository
        # self.adapter = adapter if adapter is not None else MiaoshouAdapter()
        # 2026-10-11：本次修改原因：默认加载官方公共采集箱适配器；UI 与无界面调用共用配置。
        if adapter is None:
            from .miaoshou import MiaoshouAdapter
            from .miaoshou_config import MiaoshouConfigStore
            adapter = MiaoshouAdapter(MiaoshouConfigStore(repository.data_dir))
        self.adapter = adapter

    @property
    def unavailable_reason(self) -> str:
        return self.adapter.unavailable_reason

    # 2026-10-11：本次修改原因：回传预检查覆盖审核、原商品关联和本地素材；采集来源 ID 不能冒充妙手商品 ID。
    def issues(self, product: Product, mode: str) -> list[str]:
        result = []
        if not product.approved:
            result.append("请先保存并审核商品。")
        # result.extend(product.issues())
        # 2026-10-12：本次修改原因：API 更新只校验实际改动字段，新增商品仍需完整检查，避免原物流占位阻挡标题写回。
        result.extend(product.review_issues() if mode == "update" else product.issues())
        if mode == "update" and not product.erp_original_id:
            result.append("尚未关联妙手中的原采集商品；来源平台商品 ID 不能作为妙手商品 ID。")
        media = product.images + product.detail_images + [sku.image for sku in product.skus]
        media += [product.video, product.certificate, product.size_chart, product.body_size_chart, product.instruction_manual]
        media += description_images(product.description_html)
        # if any(address.startswith("file:") for address in media):
        # 2026-10-11：本次修改原因：更新只检查实际提交素材，未修改的本地字段不应阻塞其他字段增量写入。
        if mode == "create" and any(address.startswith("file:") for address in media):
            result.append("含本机素材，请先接通图片上传或替换为妙手可访问的链接。")
        result.extend(self.adapter.validate(product, mode))
        return list(dict.fromkeys(result))

    # 2026-10-11：本次修改原因：按钮创建可追溯记录；快照重检后才发送，超时或无效回执不能标为已传或自动重发。
    # def transfer(self, product_ids: list[str], mode: str) -> list[dict]:
    # 2026-10-12：本次修改原因：批量回传报告实际商品序号及阶段，不把开始任务当成保存成功。
    def transfer(self, product_ids: list[str], mode: str, progress: Callable[[str], None] | None = None) -> list[dict]:
        if mode not in MODE_LABELS:
            raise ValueError("请选择有效的回传方式。")
        results = []
        # for product_id in dict.fromkeys(product_ids):
        # 2026-10-12：本次修改原因：进度按去重后的真实商品数计算。
        targets = list(dict.fromkeys(product_ids))
        for index, product_id in enumerate(targets, 1):
            # 2026-10-11：本次修改原因：发送后本地落库失败也属于结果未知，不能向用户报告成未发送。
            record = None
            sent = False
            try:
                product = self.repository.product(product_id)
                if product is None:
                    raise ValueError("商品不存在。")
                # 2026-10-12：本次修改原因：每个商品携带独立阶段前缀，供后台任务安全发送 Qt 信号。
                report = (lambda stage: progress(f"{index}/{len(targets)} · {(product.title or product.main_code)[:45]} · {stage}")) if progress else None
                if report:
                    report("检查当前版本、审核与回传条件")
                errors = self.issues(product, mode)
                record = self.repository.create_erp_transfer(product_id, mode, "blocked", "\n".join(errors))
                # 冻结后重新校验，避免预检查和取快照之间商品已经改变。
                snapshot = Product.from_dict(json.loads(record["snapshot"]))
                errors = self.issues(snapshot, mode)
                if errors:
                    self._blocked(record["id"], "\n".join(errors))
                    results.append({"id": record["id"], "product_id": product_id, "state": "blocked", "message": "\n".join(errors)})
                    continue
                self._sending(record["id"])
                sent = True
                # request = ERPRequest(record["id"], mode, snapshot, snapshot.erp_original_id)
                # 2026-10-12：本次修改原因：将进度回调传给适配器，原有适配器仍可忽略该可选字段。
                request = ERPRequest(record["id"], mode, snapshot, snapshot.erp_original_id, report)
                try:
                    receipt = self.adapter.send(request)
                    if (not isinstance(receipt, ERPReceipt) or receipt.mode != mode
                            or not receipt.target_id.strip() or not receipt.receipt_id.strip()):
                        raise ValueError("妙手回执不完整，无法确认保存结果。")
                    if mode == "update" and receipt.target_id != request.original_id:
                        raise ValueError("回执目标与原采集商品不一致，需人工核对。")
                except ERPRejectedError as error:
                    state, message = "failed", str(error)
                    # self.repository.finish_erp_transfer(record["id"], state, message)
                    # 2026-10-11：本次修改原因：保存明确失败的脱敏响应。
                    self.repository.finish_erp_transfer(record["id"], state, message, receipt=error.details)
                # 2026-10-11：本次修改原因：发送后超时显示实际原因并保留响应，禁止自动新增重试。
                except ERPUncertainError as error:
                    state, message = "unknown", str(error)
                    self.repository.finish_erp_transfer(record["id"], state, message, receipt=error.details)
                except Exception:
                    state, message = "unknown", "未取得可信的成功回执，结果未知。请先在妙手核对，避免重复新增。"
                    self.repository.finish_erp_transfer(record["id"], state, message)
                else:
                    # 2026-10-12：本次修改原因：取得成功回执后才提示保存本机结果。
                    if report:
                        report("已取得回执，保存本机记录")
                    # state, message = "succeeded", "妙手已确认保存。"
                    # 2026-10-11：本次修改原因：明确写入公共采集箱，发布仍由妙手执行。
                    state, message = "succeeded", "妙手公共采集箱已确认保存，发布请在妙手完成。"
                    # 2026-10-11：本次修改原因：明确提示官方接口未覆盖的来源字段，避免把接口成功解释为所有素材均已写回。
                    if receipt.details.get("warnings"):
                        message += "\n" + "\n".join(receipt.details["warnings"])
                    self.repository.finish_erp_transfer(record["id"], state, message, receipt.target_id,
                                                        # {"receipt_id": receipt.receipt_id, "mode": receipt.mode})
                                                        # 2026-10-11：本次修改原因：保存真实回执及账号指纹，支持后续增量合并。
                                                        {**receipt.details, "receipt_id": receipt.receipt_id, "mode": receipt.mode})
                results.append({"id": record["id"], "product_id": product_id, "state": state, "message": message})
            except Exception as error:
                # results.append({"product_id": product_id, "state": "blocked", "message": str(error)})
                # 2026-10-11：本次修改原因：区分发送前异常与已经可能产生外部保存的异常。
                state = "unknown" if sent else "blocked"
                message = "发送结果未能保存到本机，请先在妙手核对后再处理。" if sent else str(error)
                # 2026-10-11：本次修改原因：尽可能持久化发送后落库异常；无法写入时保留 sending 状态继续阻止重复发送。
                if record:
                    try:
                        if sent:
                            self.repository.finish_erp_transfer(record["id"], "unknown", message)
                        else:
                            self._blocked(record["id"], message)
                    except Exception:
                        pass
                results.append({"id": record["id"] if record else "", "product_id": product_id,
                                "state": state, "message": message})
        return results

    # 2026-10-12：本次修改原因：界面预检查失败写本机记录，已有未知任务继续保留。
    def record_preflight(self, problems: list[tuple[str, list[str]]], mode: str, account_id: str) -> list[str]:
        errors = []
        for product_id, issues in problems:
            try:
                if any(row["state"] in {"sending", "unknown"} for row in self.repository.erp_transfers(product_id)):
                    continue
                record = self.repository.create_erp_transfer(product_id, mode, "blocked", "\n".join(issues))
                # self.repository.finish_erp_transfer(record["id"], "blocked", "\n".join(issues),
                #                                     receipt={"account_id": account_id, "preflight": True})
                # 2026-10-12：本次修改原因：前置检查未进入发送态，只补充账号元数据，不调用发送回执终结方法。
                with self.repository.connection() as connection:
                    connection.execute("UPDATE erp_transfers SET receipt=? WHERE id=? AND state='blocked'",
                        (json.dumps({"account_id": account_id, "preflight": True}), record["id"]))
            except (ValueError, OSError, sqlite3.Error) as error:
                errors.append(str(error))
        return errors

    def _blocked(self, transfer_id: str, message: str) -> None:
        with self.repository.connection() as connection:
            connection.execute("UPDATE erp_transfers SET message=? WHERE id=? AND state='blocked'", (message, transfer_id))

    # 2026-10-11：本次修改原因：通过适配器读取详情核对未知结果，成功也绑定旧发送快照，不上传、不重发。
    def reconcile(self, transfer_id: str, target_id: str) -> str:
        record = next((row for row in self.repository.erp_transfers() if row["id"] == transfer_id), None)
        if not record or record["state"] != "unknown":
            raise ValueError("该记录不是待核对的未知结果。")
        method = getattr(self.adapter, "reconcile", None)
        if method is None:
            raise ValueError("此适配器不支持只读核对。")
        receipt = method(record, target_id)
        if not isinstance(receipt, ERPReceipt) or receipt.mode != record["mode"] or not receipt.target_id or not receipt.receipt_id:
            raise ValueError("核对回执不完整，原记录保持结果未知。")
        snapshot = Product.from_dict(json.loads(record["snapshot"]))
        if receipt.mode == "update" and receipt.target_id != snapshot.erp_original_id:
            raise ValueError("核对目标与当时的原商品不一致。")
        message = "已通过妙手详情只读核对，提交字段与远端一致。"
        self.repository.finish_erp_transfer(record["id"], "succeeded", message, receipt.target_id,
                                            {**receipt.details, "receipt_id": receipt.receipt_id, "mode": receipt.mode},
                                            resolved_unknown=True)
        return message

    def _sending(self, transfer_id: str) -> None:
        with self.repository.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT product_id FROM erp_transfers WHERE id=? AND state='blocked'", (transfer_id,)).fetchone()
            if row is None:
                raise ValueError("回传记录已处理。")
            active = connection.execute("SELECT id FROM erp_transfers WHERE product_id=? AND state IN ('sending','unknown')", (row["product_id"],)).fetchone()
            if active:
                raise ValueError("该商品已有未确认结果，不能重复发送。")
            connection.execute("UPDATE erp_transfers SET state='sending',message='' WHERE id=?", (transfer_id,))
