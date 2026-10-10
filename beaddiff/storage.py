# 2026-10-10：本次修改原因：提供线程独立连接的 SQLite 存储，持久化原始采集、商品版本和导出记录。
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .models import Product, now_iso


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
