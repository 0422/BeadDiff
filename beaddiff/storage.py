# 2026-10-10：本次修改原因：提供线程独立连接的 SQLite 存储，持久化原始采集、商品版本和导出记录。
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

# from .models import Product, SKU, now_iso
# 2026-10-11：本次修改原因：回填直接使用解析结果，不需要额外导入 SKU 类型。
from .models import Product, now_iso
# 2026-10-11：本次修改原因：重新解析时把有效属性和详情图回填到妙手对应的描述字段。
from .content import attribute_description, detail_html, with_detail_images


class Repository:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.raw_dir = data_dir / "captures"
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = data_dir / "beaddiff.sqlite3"
        with self.connection() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS captures (
                    id TEXT PRIMARY KEY, event_key TEXT UNIQUE NOT NULL,
                    source TEXT NOT NULL, source_id TEXT NOT NULL, site TEXT NOT NULL,
                    received_at TEXT NOT NULL, request_url TEXT NOT NULL,
                    raw_path TEXT NOT NULL, state TEXT NOT NULL, message TEXT NOT NULL,
                    product_id TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS products (
                    id TEXT PRIMARY KEY, source TEXT NOT NULL, source_id TEXT NOT NULL,
                    site TEXT NOT NULL, body TEXT NOT NULL, updated_at TEXT NOT NULL,
                    UNIQUE(source, source_id, site)
                );
                CREATE TABLE IF NOT EXISTS product_versions (
                    product_id TEXT NOT NULL, revision INTEGER NOT NULL,
                    body TEXT NOT NULL, created_at TEXT NOT NULL,
                    PRIMARY KEY(product_id, revision)
                );
                CREATE TABLE IF NOT EXISTS exports (
                    id TEXT PRIMARY KEY, created_at TEXT NOT NULL, path TEXT NOT NULL,
                    product_count INTEGER NOT NULL, sku_count INTEGER NOT NULL,
                    versions TEXT NOT NULL
                );
            """)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path, timeout=15)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def create_capture(self, envelope: dict) -> tuple[str, bool]:
        payload = envelope["payload"]
        serialized = json.dumps(envelope, ensure_ascii=False, indent=2)
        source_id = str(payload.get("itemId", ""))
        event_key = str(envelope.get("eventId") or hashlib.sha256(serialized.encode()).hexdigest())
        capture_id = uuid.uuid4().hex
        raw_path = self.raw_dir / f"{capture_id}.json"
        with self.connection() as connection:
            # 2026-10-10：本次修改原因：先取得写锁，防止并发重试产生两个同一事件的原始文件。
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute("SELECT id FROM captures WHERE event_key=?", (event_key,)).fetchone()
            if existing:
                return existing["id"], False
            raw_path.write_text(serialized, encoding="utf-8")
            connection.execute(
                "INSERT INTO captures VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (capture_id, event_key, str(payload.get("source", "")).lower(), source_id,
                 str(payload.get("site", "")), now_iso(), str(envelope.get("requestUrl", "")),
                 str(raw_path), "已接收", "原始材料已保存", ""),
            )
        return capture_id, True

    def capture(self, capture_id: str) -> dict | None:
        with self.connection() as connection:
            row = connection.execute("SELECT * FROM captures WHERE id=?", (capture_id,)).fetchone()
            return dict(row) if row else None

    def captures(self) -> list[dict]:
        with self.connection() as connection:
            return [dict(row) for row in connection.execute("SELECT * FROM captures ORDER BY received_at DESC, rowid DESC")]

    def finish_capture(self, capture_id: str, state: str, message: str, product_id: str = "") -> None:
        with self.connection() as connection:
            connection.execute("UPDATE captures SET state=?,message=?,product_id=? WHERE id=?",
                               (state, message, product_id, capture_id))

    def product(self, product_id: str) -> Product | None:
        with self.connection() as connection:
            row = connection.execute("SELECT body FROM products WHERE id=?", (product_id,)).fetchone()
            return Product.from_dict(json.loads(row["body"])) if row else None

    def products(self) -> list[Product]:
        with self.connection() as connection:
            return [Product.from_dict(json.loads(row["body"])) for row in connection.execute(
                "SELECT body FROM products ORDER BY updated_at DESC, rowid DESC")]

    def store_parsed(self, product: Product) -> tuple[Product, bool]:
        with self.connection() as connection:
            # 2026-10-10：本次修改原因：把商品查重与首次写入放在同一个写事务内。
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT body FROM products WHERE source=? AND source_id=? AND site=?",
                (product.source, product.source_id, product.site),
            ).fetchone()
            if existing:
                # 2026-10-10：本次修改原因：重复采集保留已有人工编辑，原始快照仍单独保存。
                return Product.from_dict(json.loads(existing["body"])), False
            product.id = uuid.uuid4().hex
            product.created_at = product.updated_at = now_iso()
            product.main_code = f"BD-{product.source.upper()}-{product.source_id}"
            if product.site:
                product.main_code += f"-{product.site.upper()}"
            body = json.dumps(product.to_dict(), ensure_ascii=False)
            connection.execute("INSERT INTO products VALUES (?,?,?,?,?,?)",
                               (product.id, product.source, product.source_id, product.site, body, product.updated_at))
            connection.execute("INSERT INTO product_versions VALUES (?,?,?,?)",
                               (product.id, product.revision, body, product.updated_at))
        return product, True

    # 2026-10-11：本次修改原因：重新解析真实采集材料时只补齐缺失来源字段，不覆盖人工编辑。
    @staticmethod
    def _mark_manual_changes(existing: Product, product: Product) -> None:
        tracked = set(existing.manual_fields)
        # simple_fields = ("title", "main_code", "currency", "description", "category", "attributes",
        # 2026-10-11：本次修改原因：按属性名保护编辑，仍允许补入用户尚未处理的其它属性。
        # simple_fields = ("title", "main_code", "currency", "description", "category",
        #                  "images", "detail_images", "video", "certificate", "size_chart", "spec1_name", "spec2_name")
        # 2026-10-11：本次修改原因：八个栏目新增字段也记录人工修改和清空，重新解析不覆盖。
        simple_fields = ("title", "main_code", "currency", "description", "category", "simple_description", "description_html",
                         "images", "detail_images", "video", "certificate", "size_chart", "body_size_chart", "instruction_manual",
                         # 2026-10-11：本次修改原因：货源链接修改同样保留人工编辑痕迹。
                         "package_weight", "package_dimensions", "source_remark", "source_url", "spec1_name", "spec2_name")
        for name in simple_fields:
            if getattr(existing, name) != getattr(product, name):
                tracked.add(name)
        for name in set(existing.attributes) | set(product.attributes):
            if existing.attributes.get(name) != product.attributes.get(name):
                tracked.add(f"attribute:{name}")
        # old_ids = [sku.platform_sku for sku in existing.skus]
        # new_ids = [sku.platform_sku for sku in product.skus]
        # 2026-10-11：本次修改原因：编辑商家平台 SKU 时不丢失来源规格身份。
        old_ids = [sku.identity for sku in existing.skus]
        new_ids = [sku.identity for sku in product.skus]
        if old_ids != new_ids:
            tracked.add("skus")
        # old_by_id = {sku.platform_sku: sku for sku in existing.skus if sku.platform_sku}
        # 2026-10-11：本次修改原因：以来源 ID 对应同一规格的编辑保护。
        old_by_id = {sku.identity: sku for sku in existing.skus if sku.identity}
        for sku in product.skus:
            # old = old_by_id.get(sku.platform_sku)
            old = old_by_id.get(sku.identity)
            if not old:
                continue
            # for name in ("spec1", "spec2", "source_price", "price", "currency", "image", "stock", "weight", "dimensions",
            # 2026-10-11：本次修改原因：商家平台 SKU 是可编辑业务字段，单独保护其修改。
            for name in ("platform_sku", "spec1", "spec2", "source_price", "price", "currency", "image", "stock", "weight", "dimensions",
                         "source_currency", "source_stock", "purchase_limit", "availability", "specs"):
                if getattr(old, name) != getattr(sku, name):
                    # tracked.add(f"sku:{sku.platform_sku}:{name}")
                    tracked.add(f"sku:{sku.identity}:{name}")
        product.manual_fields = sorted(tracked)
        product.edit_tracking = True

    # 2026-10-11：本次修改原因：从旧版编辑历史恢复保护标记，不把解析升级产生的版本当成人工修改。
    def _load_manual_history(self, connection: sqlite3.Connection, product: Product) -> None:
        if product.edit_tracking:
            return
        previous = None
        for row in connection.execute("SELECT body FROM product_versions WHERE product_id=? AND revision<=? ORDER BY revision",
                                      (product.id, product.revision)):
            version = Product.from_dict(json.loads(row["body"]))
            if previous is not None:
                self._mark_manual_changes(previous, version)
            previous = version
        product.manual_fields = sorted(set(product.manual_fields) | set(previous.manual_fields if previous else []))
        product.edit_tracking = True

    # 2026-10-11：本次修改原因：为“重新解析”提供可重复的增量回填，并返回实际补齐数量。
    def backfill_parsed(self, capture_id: str, parsed: Product) -> tuple[Product, bool, dict[str, int]]:
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT id,body FROM products WHERE source=? AND source_id=? AND site=?",
                                     (parsed.source, parsed.source_id, parsed.site)).fetchone()
            if row is None:
                # stored, created = self.store_parsed(parsed)
                # return stored, created, {"fields": 1 if created else 0, "skus": len(stored.skus), "images": len(stored.images)}
                # 2026-10-11：本次修改原因：新商品由服务层先创建，禁止持有写锁时嵌套创建连接。
                raise ValueError("商品不存在，请重新解析或导入采集材料。")
            existing = Product.from_dict(json.loads(row["body"]))
            self._load_manual_history(connection, existing)
            manual = set(existing.manual_fields)
            changed = 0
            summary = {"fields": 0, "skus": 0, "images": 0, "details": 0, "attributes": 0}
            # scalar_fields = ("title", "description", "currency", "category", "video", "certificate", "size_chart",
            #                  "spec1_name", "spec2_name")
            # 2026-10-11：本次修改原因：只补明确提供的附件和物流，不使用默认提示或商品尺码猜测。
            scalar_fields = ("title", "description", "currency", "category", "video", "certificate", "size_chart", "body_size_chart",
                             "instruction_manual", "package_weight", "package_dimensions", "source_remark", "spec1_name", "spec2_name")
            for name in scalar_fields:
                # 2026-10-11：本次修改原因：旧版空 SKU 的通用规格名也要补齐为真实颜色、尺码名称。
                old_value, new_value = getattr(existing, name), getattr(parsed, name)
                default_spec = name in {"spec1_name", "spec2_name"} and old_value == getattr(Product(), name)
                if name not in manual and (not old_value or default_spec) and new_value and old_value != new_value:
                    setattr(existing, name, new_value)
                    changed += 1
                    summary["fields"] += 1
            for name, counter in (("images", "images"), ("detail_images", "details")):
                if name not in manual:
                    old = list(getattr(existing, name))
                    merged = list(dict.fromkeys(old + list(getattr(parsed, name))))
                    if merged != old:
                        setattr(existing, name, merged)
                        changed += 1
                        summary[counter] += len(merged) - len(old)
            if "attributes" not in manual:
                attrs = dict(existing.attributes)
                for key, value in parsed.attributes.items():
                    # if key not in attrs or not attrs[key]:
                    # 2026-10-11：本次修改原因：已删除或清空的单条属性不因重新解析恢复。
                    if f"attribute:{key}" not in manual and (key not in attrs or not attrs[key]):
                        attrs[key] = value
                        summary["attributes"] += 1
                        changed += 1
                existing.attributes = attrs
            # 2026-10-11：本次修改原因：描述依据有效属性/图片生成，旧版人工文案和清空操作也受保护。
            descriptions = {"simple_description": attribute_description(existing.attributes),
                            "description_html": with_detail_images(parsed.description_html, existing.detail_images)}
            if "description" in manual:
                if not existing.description_html and "description_html" not in manual:
                    descriptions["description_html"] = detail_html(existing.description, [])
                    manual.add("description_html")
                    existing.manual_fields = sorted(manual)
                    changed += 1
                else:
                    descriptions.pop("description_html")
            for name, value in descriptions.items():
                legacy_migration = name == "description_html" and "description" in manual and not existing.description_html
                if (name not in manual or legacy_migration) and getattr(existing, name) != value:
                    setattr(existing, name, value)
                    summary["fields"] += 1
                    changed += 1
            sizes = {**parsed.image_sizes, **existing.image_sizes}
            if sizes != existing.image_sizes:
                existing.image_sizes = sizes
                changed += 1
            # 2026-10-11：本次修改原因：移除的 SKU 不恢复，仍保留的 SKU 可以补齐来源字段。
            # old_by_id = {sku.platform_sku: sku for sku in existing.skus if sku.platform_sku}
            # 2026-10-11：本次修改原因：以来源 ID 回填，规格匹配只用于唯一的旧版 SKU。
            old_by_id = {sku.identity: sku for sku in existing.skus if sku.identity}
            matched = set()
            for source_sku in parsed.skus:
                # target = old_by_id.get(source_sku.platform_sku)
                target = old_by_id.get(source_sku.identity)
                if target is None:
                    legacy = [sku for sku in existing.skus if not sku.source_sku_id and id(sku) not in matched
                              and (sku.spec1, sku.spec2) == (source_sku.spec1, source_sku.spec2)]
                    if len(legacy) == 1:
                        target = legacy[0]
                if target is None:
                    # if "skus" not in manual and source_sku.platform_sku:
                    if "skus" not in manual and source_sku.identity:
                        source_sku.currency = existing.currency
                        existing.skus.append(source_sku)
                        # old_by_id[source_sku.platform_sku] = source_sku
                        old_by_id[source_sku.identity] = source_sku
                        summary["skus"] += 1
                        changed += 1
                    continue
                # 2026-10-11：本次修改原因：旧来源编号迁移到独立字段，保留已手工填写的平台 SKU。
                matched.add(id(target))
                if not target.source_sku_id and source_sku.source_sku_id:
                    old_identity = target.identity
                    target.source_sku_id = source_sku.source_sku_id
                    manual = {field.replace(f"sku:{old_identity}:", f"sku:{target.identity}:", 1)
                              if field.startswith(f"sku:{old_identity}:") else field for field in manual}
                    existing.manual_fields = sorted(manual)
                    if target.platform_sku == source_sku.source_sku_id and "skus" not in manual:
                        if f"sku:{target.identity}:platform_sku" not in manual:
                            target.platform_sku = ""
                    changed += 1
                for name in ("spec1", "spec2", "source_price", "source_currency", "image", "source_stock", "purchase_limit", "availability", "specs"):
                    # if f"sku:{target.platform_sku}:{name}" in manual:
                    if f"sku:{target.identity}:{name}" in manual:
                        continue
                    old_value, new_value = getattr(target, name), getattr(source_sku, name)
                    refresh_source = name in {"source_price", "source_currency", "source_stock", "purchase_limit", "availability"}
                    if (not old_value or refresh_source) and new_value and old_value != new_value:
                        setattr(target, name, new_value)
                        changed += 1
                        summary["fields"] += 1
            # warnings = list(dict.fromkeys(existing.warnings + parsed.warnings))
            # 2026-10-11：本次修改原因：已识别 SKU 与币种后清除旧版过期的解析警告。
            warnings = list(dict.fromkeys(parsed.warnings))
            if warnings != existing.warnings:
                existing.warnings = warnings
                changed += 1
            if not changed:
                return existing, False, summary
            existing.revision += 1
            existing.updated_at = now_iso()
            existing.approved = False
            existing.capture_id = capture_id
            body = json.dumps(existing.to_dict(), ensure_ascii=False)
            connection.execute("UPDATE products SET body=?,updated_at=? WHERE id=?", (body, existing.updated_at, existing.id))
            connection.execute("INSERT INTO product_versions VALUES (?,?,?,?)", (existing.id, existing.revision, body, existing.updated_at))
            return existing, True, summary

    def save_product(self, product: Product, approve: bool = False) -> Product:
        with self.connection() as connection:
            # 2026-10-10：本次修改原因：并发保存时先锁定事务，再比较版本号以防覆盖。
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT body FROM products WHERE id=?", (product.id,)).fetchone()
            if row is None:
                raise ValueError("商品不存在，请刷新列表。")
            existing = Product.from_dict(json.loads(row["body"]))
            if existing.revision != product.revision:
                raise ValueError("商品已被其他操作更新，请关闭编辑窗口并重新打开。")
            if approve and product.issues():
                raise ValueError("请先完善商品：\n" + "\n".join(product.issues()[:12]))
            # 2026-10-11：本次修改原因：保存人工编辑痕迹，重新解析时保护主动修改和删除。
            self._load_manual_history(connection, existing)
            self._mark_manual_changes(existing, product)
            product.approved = approve
            product.revision += 1
            product.updated_at = now_iso()
            body = json.dumps(product.to_dict(), ensure_ascii=False)
            connection.execute("UPDATE products SET body=?,updated_at=? WHERE id=?",
                               (body, product.updated_at, product.id))
            connection.execute("INSERT INTO product_versions VALUES (?,?,?,?)",
                               (product.id, product.revision, body, product.updated_at))
        return product

    def record_export(self, path: Path, products: list[Product]) -> None:
        with self.connection() as connection:
            # connection.execute("INSERT INTO exports VALUES (?,?,?,?,?,?,?)", (
            # 2026-10-10：本次修改原因：导出记录表实际为六列，修正占位符数量。
            connection.execute("INSERT INTO exports VALUES (?,?,?,?,?,?)", (
                uuid.uuid4().hex, now_iso(), str(path), len(products), sum(len(p.skus) for p in products),
                json.dumps({p.id: p.revision for p in products}),
            ))

    def exports(self) -> list[dict]:
        with self.connection() as connection:
            return [dict(row) for row in connection.execute("SELECT * FROM exports ORDER BY created_at DESC")]
