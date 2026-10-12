# 2026-10-12：本次修改原因：按开放平台账号及原图片链接持久缓存已确认成功的图片上传，失败或重启后复用，避免重复转存。
from __future__ import annotations

from contextlib import closing
import hashlib
from pathlib import Path
import sqlite3
import threading

from .models import now_iso, valid_url


class MiaoshouPictureCache:
    def __init__(self, data_dir: Path):
        self.path = data_dir / "miaoshou_picture_cache.sqlite3"
        self.lock = threading.RLock()

    @staticmethod
    def url_key(url: str) -> str:
        return hashlib.sha256(url.encode("utf-8")).hexdigest()

    def get(self, account_id: str, source_url: str) -> str | None:
        with self.lock:
            if not self.path.is_file():
                return None
            with closing(sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True, timeout=15)) as connection:
                row = connection.execute(
                    "SELECT picture_path FROM picture_uploads WHERE account_id=? AND source_url_hash=?",
                    (account_id, self.url_key(source_url)),
                ).fetchone()
            if row is None:
                return None
            if not isinstance(row[0], str) or not valid_url(row[0]):
                raise ValueError("图片上传缓存记录无效，请在设置 → 妙手回传清除当前账号图片缓存后重试。")
            return row[0]

    def put(self, account_id: str, source_url: str, picture_path: str) -> None:
        if not account_id or not valid_url(source_url) or not valid_url(picture_path):
            raise ValueError("不能缓存未确认成功的图片上传结果。")
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(self.path, timeout=15)) as connection, connection:
                connection.execute("""
                    CREATE TABLE IF NOT EXISTS picture_uploads (
                        account_id TEXT NOT NULL, source_url_hash TEXT NOT NULL,
                        picture_path TEXT NOT NULL, uploaded_at TEXT NOT NULL,
                        PRIMARY KEY (account_id, source_url_hash)
                    )
                """)
                connection.execute("""
                    INSERT INTO picture_uploads (account_id, source_url_hash, picture_path, uploaded_at)
                    VALUES (?,?,?,?)
                    ON CONFLICT(account_id, source_url_hash) DO UPDATE SET
                        picture_path=excluded.picture_path, uploaded_at=excluded.uploaded_at
                """, (account_id, self.url_key(source_url), picture_path, now_iso()))

    def clear(self, account_id: str) -> int:
        if not account_id:
            raise ValueError("请先保存需要清除图片缓存的 AppKey。")
        with self.lock:
            if not self.path.is_file():
                return 0
            with closing(sqlite3.connect(self.path, timeout=15)) as connection, connection:
                return connection.execute("DELETE FROM picture_uploads WHERE account_id=?", (account_id,)).rowcount
