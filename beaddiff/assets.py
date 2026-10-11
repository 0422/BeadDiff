# 2026-10-11：本次修改原因：统一白底图、采集图和生成图的素材读取与本机留档，图文编辑只访问受管理的本地图片。
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from io import BytesIO
import os
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import url2pathname
from uuid import uuid4

import httpx
from PIL import Image, ImageOps

from .config import PROJECT_ROOT

# 2026-10-11：本次修改原因：支持自定义数据目录；只允许已注册素材目录中的本地图片进入图文编辑。
_ASSET_ROOTS: set[Path] = set()


def local_asset_path(address: str) -> Path | None:
    try:
        url = urlsplit(address)
        if url.scheme != "file" or url.netloc not in {"", "localhost"}:
            return None
        root = Path(os.environ.get("BEADDIFF_DATA_DIR", PROJECT_ROOT / "data")).resolve() / "assets"
        path = Path(url2pathname(url.path)).resolve()
        # return path if path.is_relative_to(root) and path.is_file() else None
        # 2026-10-11：本次修改原因：素材管理器注册的自定义目录也可安全加载。
        return path if any(path.is_relative_to(allowed) for allowed in {root, *_ASSET_ROOTS}) and path.is_file() else None
    except (ValueError, OSError):
        return None


def valid_media_url(address: str) -> bool:
    from .models import valid_url
    return valid_url(address) or local_asset_path(address) is not None


@dataclass(frozen=True)
class ImageAsset:
    uri: str
    width: int
    height: int


class AssetStore:
    MAX_BYTES = 24 * 1024 * 1024

    def __init__(self, data_dir: Path):
        self.root = data_dir.resolve() / "assets"
        # 2026-10-11：本次修改原因：统一登记受管理素材根路径。
        _ASSET_ROOTS.add(self.root)

    @staticmethod
    def dimensions(raw: bytes) -> tuple[str, int, int]:
        with Image.open(BytesIO(raw)) as image:
            if image.width * image.height > 40_000_000:
                raise ValueError("图片像素过大，请先缩小到 4000 万像素以内。")
            image.verify()
            return image.format or "PNG", image.width, image.height

    def save(self, raw: bytes) -> ImageAsset:
        if len(raw) > self.MAX_BYTES:
            raise ValueError("图片文件超过 24 MB，请缩小图片后重试。")
        try:
            format_name, width, height = self.dimensions(raw)
        except (OSError, SyntaxError, Image.DecompressionBombError) as error:
            raise ValueError("素材不是可解码的图片文件。") from error
        extension = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp", "GIF": ".gif"}.get(format_name)
        if extension is None:
            raise ValueError("请使用 PNG、JPEG、WebP 或 GIF 图片。")
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / (hashlib.sha256(raw).hexdigest() + extension)
        if not path.exists():
            # path.write_bytes(raw)
            # 2026-10-11：本次修改原因：并发生成相同图片时也不会读取到半写入文件。
            temporary = path.with_name(path.name + f".{uuid4().hex}.tmp")
            try:
                temporary.write_bytes(raw)
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
        return ImageAsset(path.as_uri(), width, height)

    def import_file(self, path: Path) -> ImageAsset:
        if not path.is_file() or path.stat().st_size > self.MAX_BYTES:
            raise ValueError("图片不存在或超过 24 MB。")
        return self.save(path.read_bytes())

    def read(self, address: str) -> bytes:
        local = local_asset_path(address)
        if local:
            # 2026-10-11：本次修改原因：本地素材被外部替换后仍遵守图片体积限制。
            if local.stat().st_size > self.MAX_BYTES:
                raise ValueError("本地图片超过 24 MB，请缩小素材后重试。")
            return local.read_bytes()
        from .models import valid_url
        if not valid_url(address):
            raise ValueError("图片链接无效或本地素材已被移动。")
        try:
            # 下载素材不携带模型 API Key，生成链接可能位于独立的存储域名。
            with httpx.Client(timeout=60, follow_redirects=True) as client:
                with client.stream("GET", address) as response:
                    response.raise_for_status()
                    data = bytearray()
                    for chunk in response.iter_bytes():
                        data.extend(chunk)
                        if len(data) > self.MAX_BYTES:
                            raise ValueError("图片超过 24 MB，请提供较小的素材。")
            return bytes(data)
        except httpx.HTTPError as error:
            raise ValueError("图片下载失败，请检查素材链接和网络连接。") from error

    def png(self, address: str) -> bytes:
        raw = self.read(address)
        self.dimensions(raw)
        with Image.open(BytesIO(raw)) as image:
            normalized = ImageOps.exif_transpose(image).convert("RGBA")
            buffer = BytesIO()
            normalized.save(buffer, format="PNG")
        if buffer.tell() > self.MAX_BYTES:
            raise ValueError("转换后的图片过大，请先缩小主体图或参考图。")
        return buffer.getvalue()
