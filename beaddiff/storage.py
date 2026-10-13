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
            """)
            # 2026-10-11：本次修改原因：回传记录保存操作方式和确切内容快照；数据库升级不改原商品或原始材料。
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS erp_transfers (
                    id TEXT PRIMARY KEY, product_id TEXT NOT NULL, revision INTEGER NOT NULL,
                    mode TEXT NOT NULL, content_hash TEXT NOT NULL, snapshot TEXT NOT NULL,
                    state TEXT NOT NULL, target_id TEXT NOT NULL DEFAULT '',
                    receipt TEXT NOT NULL DEFAULT '{}', message TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS erp_transfers_product ON erp_transfers(product_id, created_at);
            """)
            # 2026-10-12：本次修改原因：接口同步逐商品留档，成功、重复及失败可从采集记录追溯。
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS miaoshou_import_records (
                    id TEXT PRIMARY KEY, batch_id TEXT NOT NULL, account_id TEXT NOT NULL,
                    target_id TEXT NOT NULL, product_id TEXT NOT NULL DEFAULT '',
                    title TEXT NOT NULL DEFAULT '', state TEXT NOT NULL, message TEXT NOT NULL,
                    detail TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS miaoshou_import_records_time
                    ON miaoshou_import_records(created_at);
            """)
            # 2026-10-12：本次修改原因：本机列表可清理并恢复，保留去重身份、原始材料及回传证据。
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS local_hidden (
                    kind TEXT NOT NULL, item_id TEXT NOT NULL, hidden_at TEXT NOT NULL,
                    PRIMARY KEY(kind, item_id)
                );
                CREATE INDEX IF NOT EXISTS miaoshou_import_identity
                    ON miaoshou_import_records(account_id, target_id, created_at);
            """)
            # 2026-10-11：本次修改原因：进程中断时不能把正在发送当成失败后自动重试，以免新增重复商品。
            connection.execute(
                "UPDATE erp_transfers SET state='unknown',message=? WHERE state='sending'",
                ("上次发送被中断，结果未知。请先在妙手核对，避免重复新增。",),
            )

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
            # return [dict(row) for row in connection.execute("SELECT * FROM captures ORDER BY received_at DESC, rowid DESC")]
            # 2026-10-12：本次修改原因：清空采集列表仅隐藏本机记录，插件重试仍按原事件去重。
            return [dict(row) for row in connection.execute("""SELECT c.* FROM captures c
                WHERE NOT EXISTS (SELECT 1 FROM local_hidden h WHERE h.kind='captures' AND h.item_id=c.id)
                ORDER BY received_at DESC, rowid DESC""")]

    # 2026-10-12：本次修改原因：同步结果与插件材料分开存储，不把接口 JSON 交给网页解析器。
    def record_miaoshou_import(self, batch_id: str, account_id: str, result: dict, detail: dict) -> None:
        with self.connection() as connection:
            connection.execute("INSERT INTO miaoshou_import_records VALUES (?,?,?,?,?,?,?,?,?,?)", (
                uuid.uuid4().hex, batch_id, account_id, result["target_id"], result.get("product_id", ""),
                result.get("title", ""), result["state"], result.get("message", ""),
                json.dumps(detail, ensure_ascii=False), now_iso(),
            ))

    # 2026-10-12：本次修改原因：隐藏记录仍参与旧版快照判断，清理后不重新冒出相同历史。
    def miaoshou_import_records(self, include_hidden: bool = False) -> list[dict]:
        with self.connection() as connection:
            # return [dict(row) for row in connection.execute(
            #     "SELECT * FROM miaoshou_import_records ORDER BY created_at DESC, rowid DESC")]
            # 2026-10-12：本次修改原因：同步记录可单独清理，商品及历史同步时间仍保留。
            return [dict(row) for row in connection.execute("""SELECT r.* FROM miaoshou_import_records r
                WHERE ? OR NOT EXISTS (SELECT 1 FROM local_hidden h WHERE h.kind='imports' AND h.item_id=r.id)
                ORDER BY created_at DESC, rowid DESC""", (include_hidden,))]

    # 2026-10-12：本次修改原因：回传状态继续读取全部证据，记录页面独立过滤已清理条目。
    def hidden_local_ids(self, kind: str) -> set[str]:
        with self.connection() as connection:
            return {row[0] for row in connection.execute("SELECT item_id FROM local_hidden WHERE kind=?", (kind,))}

    # 2026-10-12：本次修改原因：一次读取账号级导入索引，重复同步不再逐条请求详情；时间只辅助展示。
    def miaoshou_import_index(self, account_id: str) -> dict[str, dict]:
        with self.connection() as connection:
            rows = connection.execute("""SELECT p.source_id, p.id, p.body,
                EXISTS(SELECT 1 FROM local_hidden h WHERE h.kind='products' AND h.item_id=p.id) AS archived
                FROM products p WHERE p.source='miaoshou-api' AND p.site=?""", (account_id,))
            result = {}
            for row in rows:
                product = Product.from_dict(json.loads(row["body"]))
                result[row["source_id"]] = {"product_id": row["id"], "title": product.title,
                    "imported_at": product.erp_imported_at or product.created_at,
                    "last_sync_at": product.erp_imported_at or product.created_at, "archived": bool(row["archived"])}
            for row in connection.execute("""SELECT target_id, MAX(created_at) AS last_sync_at
                FROM miaoshou_import_records WHERE account_id=? AND state IN ('imported','existing')
                GROUP BY target_id""", (account_id,)):
                if row["target_id"] in result:
                    result[row["target_id"]]["last_sync_at"] = row["last_sync_at"]
            return result

    # 2026-10-12：本次修改原因：统一可恢复的本机清理，未确认回传及正在解析材料不可移除。
    def hide_local_items(self, kind: str, item_ids: list[str]) -> dict:
        tables = {"products": "products", "captures": "captures", "imports": "miaoshou_import_records", "transfers": "erp_transfers"}
        if kind not in tables:
            raise ValueError("不支持清理此类记录。")
        changed, blocked = 0, 0
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            for item_id in dict.fromkeys(item_ids):
                # 2026-10-12：本次修改原因：旧版无同步任务的导入快照也可清理，隐藏标记仍可恢复。
                if kind == "imports" and item_id.startswith("legacy:"):
                    if connection.execute("SELECT 1 FROM products WHERE id=?", (item_id.removeprefix("legacy:"),)).fetchone():
                        changed += connection.execute("INSERT OR IGNORE INTO local_hidden VALUES (?,?,?)", (kind, item_id, now_iso())).rowcount
                    continue
                row = connection.execute(f"SELECT * FROM {tables[kind]} WHERE id=?", (item_id,)).fetchone()
                if not row:
                    continue
                unsafe = kind == "transfers" and row["state"] in {"sending", "unknown"}
                if kind == "products":
                    unsafe = bool(connection.execute("SELECT 1 FROM erp_transfers WHERE product_id=? AND state IN ('sending','unknown')", (item_id,)).fetchone())
                if kind == "captures":
                    unsafe = row["state"] in {"已接收", "解析中"}
                if unsafe:
                    blocked += 1
                    continue
                changed += connection.execute("INSERT OR IGNORE INTO local_hidden VALUES (?,?,?)", (kind, item_id, now_iso())).rowcount
        return {"hidden": changed, "blocked": blocked}

    # 2026-10-12：本次修改原因：清理操作可恢复，恢复不会请求或修改妙手远端数据。
    # def restore_local_items(self, kind: str) -> int:
    # 2026-10-13：本次修改原因：回收站允许勾选恢复，不再只能恢复同类全部条目。
    def restore_local_items(self, kind: str, item_ids: list[str] | None = None) -> int:
        if kind not in {"products", "captures", "imports", "transfers"}:
            raise ValueError("不支持恢复此类记录。")
        with self.connection() as connection:
            # return connection.execute("DELETE FROM local_hidden WHERE kind=?", (kind,)).rowcount
            if item_ids is None:
                return connection.execute("DELETE FROM local_hidden WHERE kind=?", (kind,)).rowcount
            return sum(connection.execute("DELETE FROM local_hidden WHERE kind=? AND item_id=?", (kind, item_id)).rowcount
                       for item_id in dict.fromkeys(item_ids))

    # 2026-10-13：本次修改原因：提供可浏览的回收站列表，关联标题、来源和删除时间；只返回已移除数据。
    def recycle_items(self, kind: str) -> list[dict]:
        tables = {"products": "products", "captures": "captures", "imports": "miaoshou_import_records", "transfers": "erp_transfers"}
        if kind not in tables:
            raise ValueError("回收站类型无效。")
        result = []
        with self.connection() as connection:
            for hidden in connection.execute("SELECT * FROM local_hidden WHERE kind=? ORDER BY hidden_at DESC, rowid DESC", (kind,)):
                item_id = hidden["item_id"]
                legacy = kind == "imports" and item_id.startswith("legacy:")
                row = connection.execute(f"SELECT * FROM {'products' if legacy else tables[kind]} WHERE id=?",
                                         (item_id.removeprefix("legacy:") if legacy else item_id,)).fetchone()
                if row is None:
                    continue
                record = dict(row)
                product_row = row if kind == "products" or legacy else connection.execute(
                    "SELECT body FROM products WHERE id=?", (record.get("product_id", ""),)).fetchone()
                data = json.loads(product_row["body"]) if product_row else json.loads(record.get("snapshot", "{}"))
                title = data.get("title") or record.get("title") or "未获取标题"
                source = data.get("source") or record.get("source") or "—"
                identity = data.get("main_code") or record.get("target_id") or record.get("source_id") or item_id
                state = Product.from_dict(data).status if kind == "products" or legacy else record.get("state", "")
                result.append({"id": item_id, "hidden_at": hidden["hidden_at"], "title": title,
                    "identity": identity, "source": source, "state": state, "message": record.get("message", ""),
                    "product_id": item_id if kind == "products" else record.get("product_id", "")})
        return result

    # 2026-10-13：本次修改原因：明确回收站永久删除/清空语义；只删除已移除条目，未核对回执始终受保护。
    def purge_local_items(self, kind: str, item_ids: list[str]) -> dict:
        tables = {"products": "products", "captures": "captures", "imports": "miaoshou_import_records", "transfers": "erp_transfers"}
        if kind not in tables:
            raise ValueError("回收站类型无效。")
        deleted, blocked = 0, 0
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            for item_id in dict.fromkeys(item_ids):
                if not connection.execute("SELECT 1 FROM local_hidden WHERE kind=? AND item_id=?", (kind, item_id)).fetchone():
                    continue
                # 首次导入快照仍属于商品元数据；清空其记录入口时永久隐藏该旧版回退项。
                if kind == "imports" and item_id.startswith("legacy:"):
                    # connection.execute("UPDATE local_hidden SET kind='purged-import' WHERE kind=? AND item_id=?", (kind, item_id))
                    # 2026-10-13：本次修改原因：旧版记录已有永久隐藏标记时也能清空，避免唯一键冲突。
                    connection.execute("INSERT OR IGNORE INTO local_hidden VALUES ('purged-import',?,?)", (item_id, now_iso()))
                    connection.execute("DELETE FROM local_hidden WHERE kind=? AND item_id=?", (kind, item_id))
                    deleted += 1
                    continue
                row = connection.execute(f"SELECT * FROM {tables[kind]} WHERE id=?", (item_id,)).fetchone()
                unsafe = bool(row and kind == "transfers" and row["state"] in {"sending", "unknown"})
                if row and kind == "products":
                    unsafe = bool(connection.execute("SELECT 1 FROM erp_transfers WHERE product_id=? AND state IN ('sending','unknown')", (item_id,)).fetchone())
                if row and kind == "captures":
                    unsafe = row["state"] in {"已接收", "解析中"}
                if unsafe:
                    blocked += 1
                    continue
                if kind == "imports" and row and row["product_id"]:
                    # 删除任务记录不能让旧版快照回退入口重新冒出。
                    connection.execute("INSERT OR IGNORE INTO local_hidden VALUES ('purged-import',?,?)", ("legacy:" + row["product_id"], now_iso()))
                if kind == "products":
                    connection.execute("DELETE FROM product_versions WHERE product_id=?", (item_id,))
                    connection.execute("UPDATE captures SET product_id='' WHERE product_id=?", (item_id,))
                    connection.execute("UPDATE miaoshou_import_records SET product_id='' WHERE product_id=?", (item_id,))
                    # 2026-10-13：本次修改原因：商品不存在后移除其旧版回退标记，避免回收站统计留下空记录。
                    connection.execute("DELETE FROM local_hidden WHERE kind IN ('imports','purged-import') AND item_id=?", ("legacy:" + item_id,))
                    # 回传快照和回执独立保留，永久删除商品不会删除发送证据。
                deleted += connection.execute(f"DELETE FROM {tables[kind]} WHERE id=?", (item_id,)).rowcount
                connection.execute("DELETE FROM local_hidden WHERE kind=? AND item_id=?", (kind, item_id))
        return {"deleted": deleted, "blocked": blocked}

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
            # return [Product.from_dict(json.loads(row["body"])) for row in connection.execute(
            #     "SELECT body FROM products ORDER BY updated_at DESC, rowid DESC")]
            # 2026-10-12：本次修改原因：商品移入回收站后腾出工作列表，完整版本及 ERP 身份仍留存。
            return [Product.from_dict(json.loads(row["body"])) for row in connection.execute("""SELECT p.body FROM products p
                WHERE NOT EXISTS (SELECT 1 FROM local_hidden h WHERE h.kind='products' AND h.item_id=p.id)
                ORDER BY updated_at DESC, rowid DESC""")]

    # 2026-10-12：本次修改原因：API 导入按账号和 ERP ID 独立去重，数据库索引与平台来源分开，绝不覆盖插件商品的编辑。
    def store_miaoshou_import(self, product: Product) -> tuple[Product, bool]:
        if not product.erp_imported or not product.erp_original_account or not product.erp_original_id:
            raise ValueError("API 导入商品缺少经过验证的账号或商品 ID。")
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            identity = ("miaoshou-api", product.erp_original_id, product.erp_original_account)
            row = connection.execute("SELECT body FROM products WHERE source=? AND source_id=? AND site=?", identity).fetchone()
            if row:
                return Product.from_dict(json.loads(row["body"])), False
            product.id = uuid.uuid4().hex
            product.created_at = product.updated_at = product.erp_imported_at = now_iso()
            product.revision = 1
            product.approved = False
            body = json.dumps(product.to_dict(), ensure_ascii=False)
            connection.execute("INSERT INTO products VALUES (?,?,?,?,?,?)", (product.id, *identity, body, product.updated_at))
            connection.execute("INSERT INTO product_versions VALUES (?,?,?,?)", (product.id, 1, body, product.created_at))
        return product, True

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

    # 2026-10-11：本次修改原因：自拍白底图建立独立商品草稿，不伪造插件采集载荷或采集记录。
    def create_product(self, product: Product) -> Product:
        if product.source != "upload" or not product.images:
            raise ValueError("白底图建档需要至少一张已上传的商品图片。")
        product.id = uuid.uuid4().hex
        product.source_id = uuid.uuid4().hex
        product.main_code = product.main_code or f"BD-LOCAL-{product.source_id[:10].upper()}"
        product.created_at = product.updated_at = now_iso()
        product.revision = 1
        product.approved = False
        product.edit_tracking = True
        body = json.dumps(product.to_dict(), ensure_ascii=False)
        with self.connection() as connection:
            connection.execute("INSERT INTO products VALUES (?,?,?,?,?,?)",
                               (product.id, product.source, product.source_id, product.site, body, product.updated_at))
            connection.execute("INSERT INTO product_versions VALUES (?,?,?,?)",
                               (product.id, product.revision, body, product.updated_at))
        return product

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
        # 2026-10-11：本次修改原因：单规格货源价也支持保存、清空及增量回传。
        if existing.supply_price != product.supply_price:
            tracked.add("supply_price")
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
            # 2026-10-12：本次修改原因：手动/AI 保存检查商品全部已知格式、长度、数量及已填数值，原采集材料仍留档。
            from .miaoshou_mapping import draft_limit_issues
            limits = draft_limit_issues(product, existing)
            # if limits:
            #     raise ValueError("\n".join(limits))
            # if approve and product.issues():
            #     raise ValueError("请先完善商品：\n" + "\n".join(product.issues()[:12]))
            # 2026-10-12：本次修改原因：API 原商品文本编辑按导入基线审核，未改动的空值/0 物流不阻碍保存审核。
            # issues = product.review_issues()
            # 2026-10-12：本次修改原因：实际 HTML/详情图更改需与保存前版本比较，避免旧图片追加影响字数校验。
            issues = product.review_issues(existing) if approve else []
            # if approve and issues:
            #     raise ValueError("请先完善商品：\n" + "\n".join(issues[:12]))
            # 2026-10-12：本次修改原因：一次汇总全部硬限制和审核必填问题；失败前不写新版本，也不把旧已审核商品当成合规。
            errors = list(dict.fromkeys(limits + (issues if approve else [])))
            if errors:
                raise ValueError("请调整商品后再保存：\n" + "\n".join(f"• {message}" for message in errors))
            # 2026-10-11：本次修改原因：保存人工编辑痕迹，重新解析时保护主动修改和删除。
            self._load_manual_history(connection, existing)
            self._mark_manual_changes(existing, product)
            # 2026-10-11：本次修改原因：手动和 AI 应用后保存共用内容比较；预览尺寸、审核、空保存不算商品修改。
            changed = existing.content_hash != product.content_hash
            product.content_modified = existing.content_modified or changed
            product.modified_at = now_iso() if changed else existing.modified_at
            # 2026-10-11：本次修改原因：编辑器可能早于回执打开，保存时保留数据库中的最新回传信息。
            # for name in ("erp_content_hash", "erp_transferred_at", "erp_transfer_mode", "erp_target_id",
            #              "erp_transfer_id", "erp_original_id"):
            # 2026-10-11：本次修改原因：旧编辑窗口不能覆盖最新账号关联、SKU 对应关系或增量基线。
            for name in ("erp_content_hash", "erp_transferred_at", "erp_transfer_mode", "erp_target_id",
                         "erp_transfer_id", "erp_original_id", "erp_original_account", "erp_sku_links",
                         "erp_update_baseline", "erp_account_id"):
                setattr(product, name, getattr(existing, name))
            # 2026-10-12：本次修改原因：普通编辑不能更换 API 导入身份或完整远端快照，避免旧窗口覆盖导入元数据。
            # for name in ("erp_imported", "erp_remote_snapshot", "erp_imported_at"):
            # 2026-10-12：本次修改原因：原始导入基线也不受普通表单保存覆盖。
            for name in ("erp_imported", "erp_remote_snapshot", "erp_imported_at", "erp_import_baseline"):
                setattr(product, name, getattr(existing, name))
            product.approved = approve
            product.revision += 1
            product.updated_at = now_iso()
            body = json.dumps(product.to_dict(), ensure_ascii=False)
            connection.execute("UPDATE products SET body=?,updated_at=? WHERE id=?",
                               (body, product.updated_at, product.id))
            connection.execute("INSERT INTO product_versions VALUES (?,?,?,?)",
                               (product.id, product.revision, body, product.updated_at))
        return product

    # 2026-10-11：本次修改原因：在同一事务中冻结回传内容及配置方式，防止发送途中编辑影响该次回执。
    def create_erp_transfer(self, product_id: str, mode: str, state: str, message: str = "") -> dict:
        if mode not in {"create", "update"} or state not in {"blocked", "sending"}:
            raise ValueError("回传方式或初始状态无效。")
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT body FROM products WHERE id=?", (product_id,)).fetchone()
            if row is None:
                raise ValueError("商品不存在，请刷新列表。")
            product = Product.from_dict(json.loads(row["body"]))
            unresolved = connection.execute(
                "SELECT id FROM erp_transfers WHERE product_id=? AND state IN ('sending','unknown') LIMIT 1",
                (product_id,),
            ).fetchone()
            if unresolved:
                raise ValueError("该商品已有正在发送或结果未知的记录，请先核对回传结果。")
            transfer_id, timestamp = uuid.uuid4().hex, now_iso()
            snapshot = json.dumps(product.to_dict(), ensure_ascii=False)
            connection.execute("INSERT INTO erp_transfers VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (
                transfer_id, product.id, product.revision, mode, product.content_hash, snapshot,
                state, "", "{}", message, timestamp, timestamp,
            ))
            return dict(connection.execute("SELECT * FROM erp_transfers WHERE id=?", (transfer_id,)).fetchone())

    # 2026-10-11：本次修改原因：只有经过适配器确认的成功回执才能标记已传，绑定发送快照而非当前编辑版本。
    def finish_erp_transfer(self, transfer_id: str, state: str, message: str,
                            # target_id: str = "", receipt: dict | None = None) -> None:
                            # 2026-10-11：本次修改原因：仅允许经过真实只读核对的未知记录转为成功。
                            target_id: str = "", receipt: dict | None = None, *, resolved_unknown: bool = False) -> None:
        if state not in {"succeeded", "failed", "unknown"}:
            raise ValueError("回传结果状态无效。")
        if state == "succeeded" and (not target_id.strip() or not receipt):
            raise ValueError("成功回传必须有妙手目标商品 ID 和经过适配器确认的回执。")
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM erp_transfers WHERE id=?", (transfer_id,)).fetchone()
            # if row is None or row["state"] != "sending":
            # 2026-10-11：本次修改原因：核对分支须有可信回执；发送分支仍只接受 sending 状态。
            expected_state = "unknown" if resolved_unknown else "sending"
            if resolved_unknown and (state != "succeeded" or not (receipt or {}).get("reconciled")):
                raise ValueError("未知结果只能通过只读核对确认成功。")
            if row is None or row["state"] != expected_state:
                raise ValueError("回传记录不存在或已处理，不能重复提交回执。")
            timestamp = now_iso()
            connection.execute("UPDATE erp_transfers SET state=?,target_id=?,receipt=?,message=?,updated_at=? WHERE id=?",
                               (state, target_id, json.dumps(receipt or {}, ensure_ascii=False), message, timestamp, transfer_id))
            if state == "succeeded":
                current = connection.execute("SELECT body FROM products WHERE id=?", (row["product_id"],)).fetchone()
                if current is None:
                    raise ValueError("商品已不存在，无法保存回传成功信息。")
                product = Product.from_dict(json.loads(current["body"]))
                product.erp_content_hash = row["content_hash"]
                product.erp_transferred_at = timestamp
                product.erp_transfer_mode = row["mode"]
                product.erp_target_id = target_id
                product.erp_transfer_id = transfer_id
                # 2026-10-11：本次修改原因：成功回执绑定发送账号，设置页切换账号后不误认已经传到新账号。
                product.erp_account_id = (receipt or {}).get("account_id", "")
                # 2026-10-11：本次修改原因：新增草稿的 ID 不替换原采集商品 ID，避免切换更新方式后更新错对象。
                if row["mode"] == "update":
                    product.erp_original_id = target_id
                    # 2026-10-11：本次修改原因：仅以成功发送的快照作为下一次增量基线，不把并发的新编辑当作已发送。
                    # product.erp_update_baseline = json.loads(row["snapshot"])
                    # 2026-10-11：本次修改原因：剥离旧基线及回执元数据，避免每次成功更新都递归嵌套历史快照。
                    baseline = json.loads(row["snapshot"])
                    for name in list(baseline):
                        if name.startswith("erp_"):
                            baseline.pop(name)
                    product.erp_update_baseline = baseline
                    product.erp_sku_links = (receipt or {}).get("sku_links", product.erp_sku_links)
                connection.execute("UPDATE products SET body=? WHERE id=?",
                                   (json.dumps(product.to_dict(), ensure_ascii=False), product.id))

    # 2026-10-11：本次修改原因：关联操作只写本地元数据，经过详情查询与人工确认后才允许更新原商品。
    def bind_erp_original(self, product_id: str, target_id: str, account_id: str,
                          sku_links: dict[str, str], expected_revision: int) -> Product:
        if not target_id.isdecimal() or int(target_id) <= 0 or not account_id:
            raise ValueError("必须使用经妙手详情接口验证的公共采集箱商品 ID 和账号。")
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT body FROM products WHERE id=?", (product_id,)).fetchone()
            if row is None:
                raise ValueError("商品不存在。")
            product = Product.from_dict(json.loads(row["body"]))
            if product.revision != expected_revision:
                raise ValueError("商品在查询期间已被编辑，请关闭关联窗口后重新操作。")
            # 2026-10-12：本次修改原因：API 导入账号/目标与完整快照不可被重新绑定到另一商品。
            if product.erp_imported and (product.erp_original_account, product.erp_original_id) != (account_id, target_id):
                raise ValueError("API 导入商品已关联其来源商品，不能改绑其他目标；请从目标账号重新导入另一条商品。")
            if connection.execute("SELECT id FROM erp_transfers WHERE product_id=? AND state IN ('sending','unknown')",
                                  (product_id,)).fetchone():
                raise ValueError("商品存在未确认的回传结果，请先在妙手核对。")
            self._load_manual_history(connection, product)
            if (product.erp_original_id, product.erp_original_account) != (target_id, account_id):
                product.erp_update_baseline = {}
                product.erp_content_hash = ""
                product.erp_account_id = ""
            product.erp_original_id = target_id
            product.erp_original_account = account_id
            product.erp_sku_links = dict(sku_links)
            # 关联不改变商品业务内容及审核状态，但递增版本以防旧窗口覆盖关联。
            product.revision += 1
            product.updated_at = now_iso()
            body = json.dumps(product.to_dict(), ensure_ascii=False)
            connection.execute("UPDATE products SET body=?,updated_at=? WHERE id=?", (body, product.updated_at, product.id))
            connection.execute("INSERT INTO product_versions VALUES (?,?,?,?)", (product.id, product.revision, body, product.updated_at))
            return product

    # 2026-10-11：本次修改原因：关联 SKU 时参考首次采集规格，不用修改后的规格猜测原 ERP SKU。
    def erp_origin_product(self, product_id: str) -> Product | None:
        with self.connection() as connection:
            row = connection.execute("SELECT body FROM product_versions WHERE product_id=? ORDER BY revision LIMIT 1",
                                     (product_id,)).fetchone()
            return Product.from_dict(json.loads(row["body"])) if row else self.product(product_id)

    # 2026-10-11：本次修改原因：设置页和商品速览可查询失败原因、回传方式及确切发送版本。
    def erp_transfers(self, product_id: str = "") -> list[dict]:
        with self.connection() as connection:
            if product_id:
                rows = connection.execute("SELECT * FROM erp_transfers WHERE product_id=? ORDER BY created_at DESC,rowid DESC", (product_id,))
            else:
                rows = connection.execute("SELECT * FROM erp_transfers ORDER BY created_at DESC,rowid DESC")
            return [dict(row) for row in rows]
