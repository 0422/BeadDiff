# 2026-10-12：本次修改原因：统一商品加工的来源、回传状态和失败后操作建议，供列表与记录页面共用。
from __future__ import annotations

import json

from .content import description_images
from .models import Product


ROUTE_LABELS = {"miaoshou": "妙手接口", "plugin": "插件同步", "upload": "自上传"}
TARGET_LABEL = "公共采集箱"


def receipt_data(record: dict) -> dict:
    try:
        value = json.loads(record.get("receipt", "{}"))
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError):
        return {}


def transfer_status(product: Product, account_id: str, records: list[dict]) -> str:
    if not account_id:
        return "未传"
    relevant = [row for row in records if row["product_id"] == product.id
                and receipt_data(row).get("account_id", account_id) == account_id]
    if any(row["state"] == "unknown" for row in relevant):
        return "待核对"
    if any(row["state"] == "sending" for row in relevant):
        return "回传中"
    if product.erp_account_id == account_id and product.erp_content_hash:
        return "已传" if product.erp_content_hash == product.content_hash else "需重传"
    current = next((row for row in relevant if row["content_hash"] == product.content_hash), None)
    if current and current["state"] == "failed":
        return "失败"
    if current and current["state"] == "blocked":
        return "未发送"
    return "未传"


def local_picture_count(product: Product) -> int:
    pictures = product.images + product.detail_images + [sku.image for sku in product.skus]
    pictures += [product.size_chart, product.body_size_chart] + description_images(product.description_html)
    return len({url for url in pictures if url.startswith("file:")})


def record_guidance(record: dict) -> str:
    state, message = record["state"], record.get("message", "")
    detail = receipt_data(record)
    if state == "unknown":
        return "先在妙手按标题、来源和发送时间核对，找到确切商品 ID 后点击“只读核对”；核对前不要重复新增。"
    if state == "sending":
        return "请等待本次回传完成。回传中不重复提交，也不切换账号。"
    if state == "succeeded":
        return "已写入公共采集箱；请在妙手完成认领、渠道编辑和发布。"
    if detail.get("failure_reason") == "picture_space_capacity" or "容量不足" in message:
        return "在妙手查看图片空间容量，清理未使用图片或扩容后重试。清除本地缓存不会释放远端容量。"
    if "本机素材" in message or "本地图片" in message or "file:" in message:
        return "将本机图片上传至可公开访问的图片存储，替换为公网链接后保存审核，再回传。"
    if "关联" in message:
        return "选择更新时先关联妙手原商品；自上传商品首次回传选择新增。"
    if "超时" in message or "网络" in message or "代理" in message:
        return "在设置测试只读连接并检查超时或代理；如图片转存超时，先核对图片空间，再决定是否重试。"
    if state == "blocked":
        return "按下方原因检查配置或进入商品加工补齐字段，保存并审核后重试。"
    return "查看下方接口回执及失败原因，修正问题后再操作；商品发布在妙手完成。"
