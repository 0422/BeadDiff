# 2026-10-14：本次修改原因：为 AI 采用图片提供“同步 ERP 时再托管”的 GitHub + jsDelivr 能力，并为后续 OSS/COS 保留统一服务边界。
from __future__ import annotations

import base64
from contextlib import closing
from dataclasses import asdict, dataclass, field
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from threading import RLock
from urllib.parse import quote
from urllib.request import getproxies
from uuid import uuid4

import httpx

from .assets import AssetStore, local_asset_path
from .content import description_images
from .models import Product, now_iso, valid_url


@dataclass(frozen=True)
class ImageHostingConfig:
    enabled: bool = False
    provider: str = "github"
    owner: str = ""
    repository: str = ""
    branch: str = "main"
    base_path: str = "beaddiff-images"
    token: str = field(default="", repr=False)
    timeout: int = 30

    def problems(self) -> list[str]:
        # 2026-10-14：本次修改原因：配置文件可能被手工编辑，先校验类型，避免设置页或同步预检因非字符串字段崩溃。
        text_fields = (self.provider, self.owner, self.repository, self.branch, self.base_path, self.token)
        if not isinstance(self.enabled, bool) or any(not isinstance(value, str) for value in text_fields):
            return ["图床配置字段类型不正确，请在设置中重新填写。"]
        if type(self.timeout) is not int or not 10 <= self.timeout <= 120:
            return ["图床请求超时应在 10～120 秒之间。"]
        if not self.enabled:
            return []
        result = []
        if self.provider != "github":
            result.append("当前仅支持 GitHub + jsDelivr 图床。")
        for value, caption in ((self.owner, "GitHub 用户名"), (self.repository, "GitHub 仓库"),
                               (self.branch, "GitHub 分支"), (self.base_path, "图片目录"),
                               (self.token, "GitHub Token")):
            if not str(value).strip():
                result.append(f"请填写{caption}。")
            elif any(char in str(value) for char in "\r\n"):
                result.append(f"{caption}不能包含换行。")
        # if not isinstance(self.timeout, int) or not 10 <= self.timeout <= 120:
        #     result.append("图床请求超时应在 10～120 秒之间。")
        if "/" in self.owner or "/" in self.repository:
            result.append("GitHub 用户名和仓库名只填写名称，不要填写 URL 或斜杠。")
        # 2026-10-14：本次修改原因：防止无效仓库路径、分支或相对目录生成错误的 CDN 图片链接。
        for value, caption in ((self.owner, "GitHub 用户名"), (self.repository, "GitHub 仓库")):
            if value and not re.fullmatch(r"[A-Za-z0-9_.-]+", value):
                result.append(f"{caption}只允许字母、数字、点、下划线和连字符。")
        for value, caption in ((self.branch, "GitHub 分支"), (self.base_path, "图片目录")):
            segments = str(value).split("/")
            if any(part in {"", ".", ".."} or not re.fullmatch(r"[A-Za-z0-9_.-]+", part) for part in segments):
                result.append(f"{caption}必须是有效的相对路径。")
        return result

    @property
    def repository_key(self) -> str:
        return f"{self.provider}:{self.owner}/{self.repository}@{self.branch}/{self.base_path.strip('/')}"


class ImageHostingStore:
    """保存连接配置和本机的本地图片→公网链接映射。"""

    def __init__(self, data_dir: Path):
        self.path = data_dir / "image_hosting.local.json"
        self.cache_path = data_dir / "image_hosting.sqlite3"
        self.config = ImageHostingConfig()
        self.error = ""
        self._digest: str | None = None
        self.reload()

    def _fingerprint(self) -> str | None:
        return hashlib.sha256(self.path.read_bytes()).hexdigest() if self.path.exists() else None

    def reload(self) -> bool:
        try:
            raw = self.path.read_bytes() if self.path.exists() else None
            data = json.loads(raw.decode("utf-8-sig")) if raw is not None else {}
            if not isinstance(data, dict) or data.get("version", 1) != 1:
                raise ValueError
            values = {name: data[name] for name in ImageHostingConfig.__dataclass_fields__ if name in data}
            config = ImageHostingConfig(**values)
            # if config.problems():
            #     if config.enabled:
            #         raise ValueError
            # 2026-10-14：本次修改原因：有缺项的配置仍在设置页展示供修复，非法字段类型则安全降级。
            if not isinstance(config.enabled, bool) or any(not isinstance(value, str) for value in (
                    config.provider, config.owner, config.repository, config.branch, config.base_path, config.token)) \
                    or type(config.timeout) is not int:
                raise ValueError
            self.config = config
            self._digest = hashlib.sha256(raw).hexdigest() if raw else None
            self.error = ""
            return True
        except (ValueError, TypeError, OSError):
            self.config = ImageHostingConfig()
            self.error = "图床配置文件格式或读取权限不正确，请重新保存配置。"
            return False

    def save(self, config: ImageHostingConfig) -> None:
        if self.error or self._fingerprint() != self._digest:
            raise ValueError("图床配置已被外部修改或读取失败，请重新加载后再保存。")
        problems = config.problems()
        if problems:
            raise ValueError("\n".join(problems))
        raw = (json.dumps({"version": 1, **asdict(config)}, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + f".{uuid4().hex}.tmp")
        try:
            temporary.write_bytes(raw)
            temporary.replace(self.path)
        finally:
            temporary.unlink(missing_ok=True)
        self.config = config
        self._digest = hashlib.sha256(raw).hexdigest()
        self.error = ""

    # 2026-10-14：本次修改原因：配置文件损坏时保留原件备份，并允许用户在设置页确认后重建。
    def recover(self, config: ImageHostingConfig) -> Path | None:
        if not self.error:
            raise ValueError("当前配置文件无需重建。")
        problems = config.problems()
        if problems:
            raise ValueError("\n".join(problems))
        backup = self.path.with_name(self.path.name + f".{uuid4().hex}.bak") if self.path.exists() else None
        if backup:
            self.path.replace(backup)
        self._digest = None
        self.error = ""
        try:
            self.save(config)
        except (OSError, ValueError):
            if backup and not self.path.exists():
                backup.replace(self.path)
            self.reload()
            raise
        return backup

    def get(self) -> ImageHostingConfig:
        if self.error:
            raise ValueError(self.error)
        return self.config

    def cache_get(self, source_hash: str, provider_key: str) -> str | None:
        if not self.cache_path.is_file():
            return None
        try:
            with closing(sqlite3.connect(self.cache_path.resolve().as_uri() + "?mode=ro", uri=True, timeout=15)) as connection:
                row = connection.execute(
                    "SELECT public_url FROM image_hosts WHERE source_hash=? AND provider_key=? AND status='ready'",
                    (source_hash, provider_key)).fetchone()
        except sqlite3.Error as error:
            # return None
            # 2026-10-14：本次修改原因：缓存文件损坏时阻止可能的重复上传，不将损坏误当成缓存未命中。
            raise ValueError("图床缓存读取失败，请检查数据目录中的 image_hosting.sqlite3。") from error
        return row[0] if row and isinstance(row[0], str) else None

    # def cache_put(self, source_hash: str, source_uri: str, provider_key: str, public_url: str) -> None:
    # 2026-10-14：本次修改原因：上传前记录待处理、失败后留可重试条目，成功状态才供 ERP 同步复用。
    def cache_put(self, source_hash: str, source_uri: str, provider_key: str, public_url: str, *,
                  status: str = "ready", last_error: str = "") -> None:
        if status not in {"pending", "failed", "ready"}:
            raise ValueError("图床缓存状态无效。")
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.cache_path, timeout=15)) as connection, connection:
            # CREATE TABLE IF NOT EXISTS image_hosts (... public_url TEXT NOT NULL, status TEXT NOT NULL, updated_at TEXT NOT NULL, ...)
            # 2026-10-14：本次修改原因：失败原因保存在本机缓存，图床页刷新后仍可查看和重试。
            connection.execute("""
                CREATE TABLE IF NOT EXISTS image_hosts (
                    source_hash TEXT NOT NULL, source_uri TEXT NOT NULL, provider_key TEXT NOT NULL,
                    public_url TEXT NOT NULL, status TEXT NOT NULL, updated_at TEXT NOT NULL,
                    last_error TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (source_hash, provider_key)
                )
            """)
            if "last_error" not in {row[1] for row in connection.execute("PRAGMA table_info(image_hosts)")}:
                connection.execute("ALTER TABLE image_hosts ADD COLUMN last_error TEXT NOT NULL DEFAULT ''")
            # INSERT INTO image_hosts (source_hash, source_uri, provider_key, public_url, status, updated_at) ...
            # 2026-10-14：本次修改原因：同一素材在待处理、失败、成功之间原位更新，避免重复条目。
            connection.execute("""
                INSERT INTO image_hosts (source_hash, source_uri, provider_key, public_url, status, updated_at, last_error)
                VALUES (?,?,?,?,?,?,?)
                ON CONFLICT(source_hash, provider_key) DO UPDATE SET
                    source_uri=excluded.source_uri, public_url=excluded.public_url,
                    status=excluded.status, updated_at=excluded.updated_at, last_error=excluded.last_error
            """, (source_hash, source_uri, provider_key, public_url, status, now_iso(), last_error[:500]))

    def records(self, provider_key: str | None = None) -> list[dict]:
        if not self.cache_path.is_file():
            return []
        try:
            with closing(sqlite3.connect(self.cache_path.resolve().as_uri() + "?mode=ro", uri=True, timeout=15)) as connection:
                connection.row_factory = sqlite3.Row
                if provider_key:
                    rows = connection.execute("SELECT * FROM image_hosts WHERE provider_key=? ORDER BY updated_at DESC", (provider_key,)).fetchall()
                else:
                    rows = connection.execute("SELECT * FROM image_hosts ORDER BY updated_at DESC").fetchall()
        except sqlite3.Error as error:
            # return []
            # 2026-10-14：本次修改原因：管理页应显示缓存故障，避免误以为此前图片记录消失。
            raise ValueError("图床缓存读取失败，请检查数据目录中的 image_hosting.sqlite3。") from error
        return [dict(row) for row in rows]


def local_media_urls(product: Product) -> list[str]:
    values = list(product.images) + list(product.detail_images) + [sku.image for sku in product.skus]
    values += [product.certificate, product.size_chart, product.body_size_chart, product.instruction_manual]
    values += description_images(product.description_html)
    return list(dict.fromkeys(value for value in values if isinstance(value, str) and value.startswith("file:")))


class GitHubImageHosting:
    """GitHub Contents API 上传器；接口形状可由后续 OSS/COS provider 复用。"""

    def __init__(self, store: ImageHostingStore, assets: AssetStore):
        self.store = store
        self.assets = assets
        # 2026-10-14：本次修改原因：同步与手动上传并发时，同内容图片的查询、上传和缓存写入串行处理。
        self.lock = RLock()
        # 2026-10-14：本次修改原因：首次上传前核对公开仓库；空仓库仅在首次写入时初始化默认分支。
        self._checked_config: ImageHostingConfig | None = None
        self._empty_repository = False

    def validate_product(self, product: Product) -> list[str]:
        return self.validate_addresses(local_media_urls(product))

    # 2026-10-14：本次修改原因：按实际提交的图片预检图床，更新文案不受无关本机素材影响。
    def validate_addresses(self, addresses: list[str]) -> list[str]:
        # if not any(isinstance(value, str) and value.startswith("file:") for value in addresses):
        # 2026-10-14：本次修改原因：缺失的已采用图片在上传前明确阻止，避免误以为仅缺图床配置。
        local = [value for value in addresses if isinstance(value, str) and value.startswith("file:")]
        if not local:
            return []
        if any(local_asset_path(value) is None for value in local):
            return ["待提交的本机图片不存在或已移出素材目录，请重新生成或导入后保存审核。"]
        if self.store.error:
            return [self.store.error]
        config = self.store.config
        if not config.enabled:
            return ["商品包含本机图片，请先到设置 → 图床启用 GitHub + jsDelivr，或改用公网图片链接。"]
        return config.problems()

    def _config(self) -> ImageHostingConfig:
        config = self.store.get()
        if not config.enabled:
            raise ValueError("图床未启用，请到设置 → 图床保存 GitHub 配置后重试。")
        problems = config.problems()
        if problems:
            raise ValueError("\n".join(problems))
        return config

    @staticmethod
    def _extension(raw: bytes) -> str:
        format_name, _, _ = AssetStore.dimensions(raw)
        return {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp", "GIF": ".gif"}.get(format_name, ".png")

    def _github_url(self, config: ImageHostingConfig, path: str) -> str:
        return f"https://api.github.com/repos/{quote(config.owner)}/{quote(config.repository)}/contents/{quote(path, safe='/')}"

    def _headers(self, config: ImageHostingConfig) -> dict[str, str]:
        return {"Accept": "application/vnd.github+json", "Authorization": f"Bearer {config.token}",
                "X-GitHub-Api-Version": "2022-11-28"}

    # 2026-10-14：本次修改原因：区分 HTTP 配置错误与网络异常，诊断信息不包含 Token 或代理地址。
    @staticmethod
    def _http_failure(response: httpx.Response, operation: str) -> str:
        status = response.status_code
        hints = {401: "Token 无效或已过期。", 403: "请检查 Token 权限、组织审批和 GitHub API 限流。",
                 404: "请检查用户名、仓库名称及 Token 对该仓库的访问权限。"}
        if status == 403 and response.headers.get("x-ratelimit-remaining") == "0":
            hint = "GitHub API 调用已限流，请稍后重试。"
        else:
            hint = hints.get(status, "请稍后重试或检查 GitHub 服务状态。")
        return f"{operation}失败（HTTP {status}）。{hint}"

    @staticmethod
    def _network_failure(error: httpx.HTTPError, operation: str, timeout: int) -> str:
        causes = []
        current = error
        while current is not None and len(causes) < 8:
            causes.append(str(current).lower())
            current = current.__cause__
        detail = " ".join(causes)
        if "certificate" in detail or "cert_verify" in detail:
            reason = "TLS 证书验证失败，请检查系统时间和代理证书。"
        elif isinstance(error, httpx.ProxyError):
            reason = "代理连接失败，请检查代理端口及 VPN。"
        elif isinstance(error, httpx.ConnectTimeout):
            reason = "建立连接超时，请检查网络及代理，也可调高超时。"
        elif isinstance(error, httpx.ReadTimeout):
            reason = "等待服务响应超时，可调高超时后重试。"
        elif "getaddrinfo" in detail or "name resolution" in detail:
            reason = "域名解析失败，请检查 DNS 和网络。"
        elif isinstance(error, httpx.ConnectError):
            reason = "连接建立失败，请检查网络、防火墙及代理。"
        else:
            reason = "网络传输异常，请检查网络及代理。"
        try:
            proxy = "已检测到系统或环境代理。" if any(getproxies().get(key) for key in ("https", "all")) else ""
        except OSError:
            proxy = ""
        return f"{operation}失败（{type(error).__name__}，超时 {timeout} 秒）。{reason}{proxy}"

    # 2026-10-14：本次修改原因：空仓库的默认分支尚无提交，不能把正常初始化状态误报为分支配置错误。
    def _check_repository(self, config: ImageHostingConfig) -> bool:
        endpoint = f"https://api.github.com/repos/{quote(config.owner)}/{quote(config.repository)}"
        with httpx.Client(timeout=config.timeout, follow_redirects=False, headers=self._headers(config)) as client:
            response = client.get(endpoint)
            if not response.is_success:
                raise ValueError(self._http_failure(response, "GitHub 仓库检查"))
            try:
                repository = response.json()
            except ValueError:
                raise ValueError("GitHub 仓库检查返回了无效响应，请稍后重试。") from None
            if not isinstance(repository, dict):
                raise ValueError("GitHub 仓库检查返回了无效响应，请稍后重试。")
            if repository.get("private") is not False:
                raise ValueError("GitHub 仓库必须设为 Public，私有仓库无法通过 jsDelivr 提供图片。")
            branch = client.get(endpoint + "/branches/" + quote(config.branch, safe=""))
            if branch.is_success:
                return False
            if branch.status_code == 404:
                branches = client.get(endpoint + "/branches", params={"per_page": 1})
                if not branches.is_success:
                    raise ValueError(self._http_failure(branches, "GitHub 分支列表检查"))
                # if branches.json() == []:
                # 2026-10-14：本次修改原因：空仓库识别先检查响应类型，代理网页或坏 JSON 不当作正常分支列表。
                try:
                    branch_rows = branches.json()
                    if not isinstance(branch_rows, list) or any(not isinstance(row, dict) or not isinstance(row.get("name"), str) for row in branch_rows):
                        raise ValueError
                except ValueError:
                    raise ValueError("GitHub 分支列表响应不是有效 JSON 列表；请检查网络或代理后，在设置 → 图床重新测试连接。") from None
                if branch_rows == []:
                    default = repository.get("default_branch", "main")
                    if config.branch == default:
                        return True
                    raise ValueError(f"仓库尚无提交，请将分支填写为默认分支 {default}，或先在 GitHub 创建 {config.branch} 分支。")
                raise ValueError(f"GitHub 分支 {config.branch} 不存在；请按仓库的实际分支名称填写。")
            raise ValueError(self._http_failure(branch, "GitHub 分支检查"))

    def _upload(self, config: ImageHostingConfig, path: str, raw: bytes) -> None:
        # 2026-10-14：本次修改原因：无须先点击测试连接，首次上传也能验证仓库并识别未初始化的默认分支。
        if self._checked_config != config:
            self._empty_repository = self._check_repository(config)
            self._checked_config = config
        endpoint = self._github_url(config, path)
        payload = {"message": f"Upload product image {hashlib.sha256(raw).hexdigest()[:12]}",
                   "content": base64.b64encode(raw).decode("ascii"), "branch": config.branch}
        if self._empty_repository:
            # 2026-10-14：本次修改原因：空仓库首次创建文件使用默认分支，不指定尚不存在的 branch；目录随文件自动创建。
            payload.pop("branch")
        with httpx.Client(timeout=config.timeout, follow_redirects=False, headers=self._headers(config)) as client:
            # existing = client.get(endpoint)
            # 2026-10-14：本次修改原因：查询与写入同一分支，防止默认分支同名文件导致错误覆盖。
            existing = client.get(endpoint, params={"ref": config.branch})
            if existing.status_code == 200:
                try:
                    # payload["sha"] = existing.json().get("sha", "")
                    # 2026-10-14：本次修改原因：内容哈希文件已存在即复用，不重复提交或覆盖远端图片。
                    git_blob = hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw).hexdigest()
                    if existing.json().get("type") == "file" and existing.json().get("sha") == git_blob:
                        self._empty_repository = False
                        return
                except (ValueError, AttributeError):
                    raise ValueError("GitHub 已有同名图片，但无法确认文件内容，请检查仓库。") from None
                raise ValueError("GitHub 已有同名图片但内容不一致，请检查仓库，避免覆盖旧图。")
            if existing.status_code != 404:
                raise ValueError(f"GitHub 图片检查失败（HTTP {existing.status_code}），商品尚未提交。")
            response = client.put(endpoint, json=payload)
            if not response.is_success:
                # raise ValueError(f"GitHub 图片上传失败（HTTP {response.status_code}），请检查仓库、分支和 Token 权限。")
                raise ValueError(self._http_failure(response, "GitHub 图片上传"))
            self._empty_repository = False

    def _verify(self, url: str, timeout: int) -> None:
        try:
            with httpx.Client(timeout=timeout, follow_redirects=True) as client:
                response = client.head(url)
                if response.status_code in {405, 501}:
                    response = client.get(url, headers={"Range": "bytes=0-32"})
                if not response.is_success or not response.headers.get("content-type", "").lower().startswith(("image/", "application/octet-stream")):
                    raise ValueError
        # except (httpx.HTTPError, ValueError):
        #     raise ValueError("GitHub 上传成功，但 jsDelivr 公网链接暂时无法访问，请稍后重试。") from None
        # 2026-10-14：本次修改原因：公网验证提示保留失败类型，避免 CDN 网络故障与仓库上传配置混淆。
        except httpx.HTTPError as error:
            raise ValueError("jsDelivr 公网链接暂时无法访问。" + self._network_failure(error, "公网验证", timeout)) from None
        except ValueError:
            raise ValueError(f"jsDelivr 公网链接暂时无法访问（HTTP {response.status_code} 或返回内容不是图片），请稍后重试。") from None

    # def ensure_public(self, address: str) -> str:
    # 2026-10-14：本次修改原因：图床页可强制验证缓存链接，离线重试不重复上传同一内容。
    def ensure_public(self, address: str, *, verify_cached: bool = True) -> str:
        if not isinstance(address, str) or not address.strip():
            raise ValueError("图片地址为空，无法上传到图床。")
        if not address.startswith("file:"):
            return address
        if local_asset_path(address) is None:
            raise ValueError("本机图片不存在或不在受管理素材目录中，请重新生成或导入图片。")
        config = self._config()
        with self.lock:
            raw = self.assets.read(address)
            source_hash = hashlib.sha256(raw).hexdigest()
            cached = self.store.cache_get(source_hash, config.repository_key)
            if cached:
                if verify_cached:
                    # self._verify(cached, config.timeout)
                    # 2026-10-14：本次修改原因：已托管链接失效也留下失败状态，避免图床页刷新后仍显示“已托管”。
                    try:
                        self._verify(cached, config.timeout)
                    except ValueError as error:
                        self.store.cache_put(source_hash, address, config.repository_key, cached,
                                             status="failed", last_error=str(error))
                        raise
                return cached
            extension = self._extension(raw)
            relative = f"{config.base_path.strip('/')}/{source_hash[:2]}/{source_hash}{extension}"
            public_url = f"https://cdn.jsdelivr.net/gh/{quote(config.owner)}/{quote(config.repository)}@{quote(config.branch)}/{quote(relative, safe='/')}"
            # 2026-10-14：本次修改原因：先落待处理记录再访问外部接口，异常中断后可在图床页继续重试。
            self.store.cache_put(source_hash, address, config.repository_key, public_url, status="pending")
            try:
                self._upload(config, relative, raw)
                self._verify(public_url, config.timeout)
            except (httpx.HTTPError, ValueError) as error:
                # except httpx.HTTPError: raise ValueError("GitHub 图片上传失败，请检查网络、仓库权限和 Token。") from None
                # 2026-10-14：本次修改原因：上传或 CDN 验证失败保留原因；重试先查询同名内容，不覆盖远端图片。
                # message = ("GitHub 图片上传失败，请检查网络、仓库权限和 Token。"
                # 2026-10-14：本次修改原因：同一上传链路报告具体网络类型，不输出原始异常中的敏感信息。
                message = (self._network_failure(error, "GitHub 图片上传", config.timeout)
                           if isinstance(error, httpx.HTTPError) else str(error))
                self.store.cache_put(source_hash, address, config.repository_key, public_url,
                                     status="failed", last_error=message)
                raise ValueError(message) from None
            # self.store.cache_put(source_hash, address, config.repository_key, public_url)
            # 2026-10-14：本次修改原因：只有已验证可访问的公网链接才能成为同步时的成功缓存。
            self.store.cache_put(source_hash, address, config.repository_key, public_url)
            return public_url

    # 2026-10-14：本次修改原因：图床页只读检测公网链接并落检测状态，不在检测操作中上传或覆盖远端文件。
    def verify_record(self, record: dict) -> None:
        url = record.get("public_url", "")
        if not valid_url(url):
            raise ValueError("该记录尚无有效的公网链接，请点击重试。")
        with self.lock:
            try:
                self._verify(url, self.store.config.timeout)
            except ValueError as error:
                self.store.cache_put(record["source_hash"], record["source_uri"], record["provider_key"], url,
                                     status="failed", last_error=str(error))
                raise
            self.store.cache_put(record["source_hash"], record["source_uri"], record["provider_key"], url)

    # def test_connection(self) -> None:
    # 2026-10-14：本次修改原因：连接测试不写远端文件，允许空仓库通过并说明首次上传会初始化。
    def test_connection(self) -> str:
        config = self._config()
        # endpoint = f"https://api.github.com/repos/{quote(config.owner)}/{quote(config.repository)}"
        try:
            # with httpx.Client(...) as client:
            #     response = client.get(endpoint)
            #     if not response.is_success: raise ValueError(f"GitHub 连接检查失败（HTTP {response.status_code}）。")
            #     if response.json().get("private") is not False: raise ValueError("GitHub 仓库必须设为 Public。")
            #     branch = client.get(endpoint + "/branches/" + quote(config.branch, safe=""))
            #     if not branch.is_success: raise ValueError(f"GitHub 分支无法访问（HTTP {branch.status_code}）。")
            with self.lock:
                self._empty_repository = self._check_repository(config)
                self._checked_config = config
            if self._empty_repository:
                return "已成功访问公开仓库。仓库尚无提交，首次上传图片时会自动创建默认分支和图片目录。"
            return "已成功访问公开仓库及配置分支。"
        except httpx.HTTPError as error:
            # raise ValueError("GitHub 连接检查失败，请检查网络或代理设置。") from error
            raise ValueError(self._network_failure(error, "GitHub 连接检查", config.timeout)) from None

