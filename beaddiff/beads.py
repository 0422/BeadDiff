# 2026-10-15：本次修改原因：为散珠数据库和类目设计工作流提供可审计的原料事实、版本快照和库存预留。
from __future__ import annotations

from dataclasses import dataclass, field
from copy import deepcopy
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

from .models import now_iso

# 2026-10-15：本次修改原因：确保 with 使用的 SQLite 连接离开作用域时释放句柄。
class _Connection(sqlite3.Connection):
    def __exit__(self, kind, value, traceback):
        try:
            return super().__exit__(kind, value, traceback)
        finally:
            self.close()

MATERIAL_CATEGORIES = ("bead", "spacer", "pendant", "cord", "clasp", "packaging", "other")
MATERIAL_CATEGORY_LABELS = {"bead": "主珠", "spacer": "隔片", "pendant": "吊坠", "cord": "线材", "clasp": "扣件", "packaging": "包装", "other": "其他"}
FACT_SOURCES = ("user", "vision", "supplier", "human", "unknown")
FACT_STATUSES = ("confirmed", "observed", "pending", "conflict")
# 2026-10-15：本次修改原因：照片只能确认可见外观，精确规格和成分必须有资料或实测来源。
VISIBLE_FACT_FIELDS = {"color", "shape", "texture", "transparency"}


def _json(value, fallback):
    try:
        parsed = json.loads(value or "")
        return parsed if isinstance(parsed, type(fallback)) else fallback
    except (TypeError, ValueError):
        return fallback


def _money(value: str) -> Decimal | None:
    try:
        amount = Decimal(str(value).strip())
        return amount if amount.is_finite() and amount >= 0 else None
    except (InvalidOperation, ValueError, TypeError):
        return None


@dataclass
class MaterialItem:
    id: str = ""
    code: str = ""
    category: str = "bead"
    library_category: str = "beads"
    name: str = ""
    material_type: str = ""
    images: list[str] = field(default_factory=list)
    facts: dict[str, str] = field(default_factory=dict)
    fact_sources: dict[str, str] = field(default_factory=dict)
    fact_statuses: dict[str, str] = field(default_factory=dict)
    observations: dict[str, str] = field(default_factory=dict)
    observation_notes: str = ""
    unit_cost: str = ""
    currency: str = "CNY"
    quantity: int = 0
    reserved_quantity: int = 0
    # track_inventory: bool = True
    # 2026-10-15：本次修改原因：库存为可选资料，未填写时不能误认为零库存。
    track_inventory: bool = False
    supplier: str = ""
    supplier_url: str = ""
    notes: str = ""
    state: str = "draft"
    revision: int = 1
    created_at: str = ""
    updated_at: str = ""
    # 2026-10-15：本次修改原因：保存资料表右侧新增的属性列，按列名记录各字段值，空列也可重新打开。
    fact_attributes: dict[str, dict[str, str]] = field(default_factory=dict)

    @property
    def available_quantity(self) -> int:
        return max(0, self.quantity - self.reserved_quantity) if self.track_inventory else 0

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "MaterialItem":
        values = {"id": row["id"], "code": row["code"], "category": row["category"],
                  "library_category": row["library_category"] if "library_category" in row.keys() else "beads",
                  "name": row["name"], "material_type": row["material_type"], "images": _json(row["images"], []),
                  "facts": _json(row["facts"], {}), "fact_sources": _json(row["fact_sources"], {}),
                  "fact_statuses": _json(row["fact_statuses"], {}), "observations": _json(row["observations"], {}),
                  "observation_notes": row["observation_notes"] if "observation_notes" in row.keys() else "",
                  "unit_cost": row["unit_cost"], "currency": row["currency"], "quantity": row["quantity"],
                  "reserved_quantity": row["reserved_quantity"], "track_inventory": bool(row["track_inventory"]) if "track_inventory" in row.keys() else True,
                  "supplier": row["supplier"], "supplier_url": row["supplier_url"], "notes": row["notes"],
                  "state": row["state"], "revision": row["revision"], "created_at": row["created_at"], "updated_at": row["updated_at"]}
        # 2026-10-15：本次修改原因：旧原料没有自定义属性列时使用空表，兼容已有记录。
        values["fact_attributes"] = _json(row["fact_attributes"], {}) if "fact_attributes" in row.keys() else {}
        return cls(**values)

    def snapshot(self) -> dict:
        return {"id": self.id, "code": self.code, "category": self.category, "library_category": self.library_category,
                "name": self.name, "material_type": self.material_type, "images": list(self.images), "facts": dict(self.facts),
                "fact_sources": dict(self.fact_sources), "fact_statuses": dict(self.fact_statuses), "observations": dict(self.observations),
                "unit_cost": self.unit_cost, "currency": self.currency, "quantity": self.quantity,
                "available_quantity": self.available_quantity, "revision": self.revision,
                # "track_inventory": self.track_inventory, "observation_notes": self.observation_notes}
                # 2026-10-15：本次修改原因：设计快照同时保留补充属性，后续修改原料不改变已有快照。
                "track_inventory": self.track_inventory, "observation_notes": self.observation_notes,
                "fact_attributes": deepcopy(self.fact_attributes)}


@dataclass
class BeadDesign:
    id: str = ""
    category: str = "beads"
    title: str = ""
    material_ids: list[str] = field(default_factory=list)
    material_snapshot: dict[str, dict] = field(default_factory=dict)
    requirements: dict[str, str] = field(default_factory=dict)
    candidates: list[dict] = field(default_factory=list)
    selected_candidate_id: str = ""
    locked_bom: list[dict] = field(default_factory=list)
    locked_material_revisions: dict[str, int] = field(default_factory=dict)
    listing: dict = field(default_factory=dict)
    listing_product_id: str = ""
    state: str = "draft"
    revision: int = 1
    created_at: str = ""
    updated_at: str = ""

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "BeadDesign":
        return cls(id=row["id"], category=row["category"], title=row["title"], material_ids=_json(row["material_ids"], []),
                   material_snapshot=_json(row["material_snapshot"], {}), requirements=_json(row["requirements"], {}),
                   candidates=_json(row["candidates"], []), selected_candidate_id=row["selected_candidate_id"],
                   locked_bom=_json(row["locked_bom"], []), locked_material_revisions=_json(row["locked_material_revisions"], {}),
                   listing=_json(row["listing"], {}), listing_product_id=row["listing_product_id"], state=row["state"],
                   revision=row["revision"], created_at=row["created_at"], updated_at=row["updated_at"])


class BeadStore:
    """材料和设计共享数据库；每次锁定均保存当时的事实与版本。"""

    def __init__(self, data_dir: Path):
        Path(data_dir).mkdir(parents=True, exist_ok=True)
        self.db_path = Path(data_dir) / "beaddiff.sqlite3"
        self._ensure_schema()

    def _connection(self):
        connection = sqlite3.connect(self.db_path, timeout=15, factory=_Connection)
        connection.row_factory = sqlite3.Row
        return connection

    def _ensure_schema(self):
        connection = self._connection()
        try:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS material_items (
                    id TEXT PRIMARY KEY, code TEXT UNIQUE NOT NULL, category TEXT NOT NULL,
                    library_category TEXT NOT NULL DEFAULT 'beads', name TEXT NOT NULL, material_type TEXT NOT NULL DEFAULT '',
                    images TEXT NOT NULL, facts TEXT NOT NULL, fact_sources TEXT NOT NULL, fact_statuses TEXT NOT NULL,
                    observations TEXT NOT NULL DEFAULT '{}', observation_notes TEXT NOT NULL DEFAULT '',
                    unit_cost TEXT NOT NULL DEFAULT '', currency TEXT NOT NULL DEFAULT 'CNY', quantity INTEGER NOT NULL DEFAULT 0,
                    reserved_quantity INTEGER NOT NULL DEFAULT 0, track_inventory INTEGER NOT NULL DEFAULT 1,
                    supplier TEXT NOT NULL DEFAULT '', supplier_url TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '',
                    state TEXT NOT NULL DEFAULT 'draft', revision INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS bead_designs (
                    id TEXT PRIMARY KEY, category TEXT NOT NULL, title TEXT NOT NULL, material_ids TEXT NOT NULL,
                    material_snapshot TEXT NOT NULL DEFAULT '{}', requirements TEXT NOT NULL, candidates TEXT NOT NULL,
                    selected_candidate_id TEXT NOT NULL DEFAULT '', locked_bom TEXT NOT NULL, locked_material_revisions TEXT NOT NULL DEFAULT '{}',
                    listing TEXT NOT NULL DEFAULT '{}', listing_product_id TEXT NOT NULL DEFAULT '', state TEXT NOT NULL DEFAULT 'draft',
                    revision INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS material_libraries (id TEXT PRIMARY KEY,title TEXT NOT NULL UNIQUE);
                INSERT OR IGNORE INTO material_libraries VALUES ('beads','散珠 / 配件');
                CREATE TABLE IF NOT EXISTS bead_design_versions (
                    design_id TEXT NOT NULL,revision INTEGER NOT NULL,body TEXT NOT NULL,created_at TEXT NOT NULL,
                    PRIMARY KEY(design_id,revision)
                );
            """)
            # 2026-10-15：本次修改原因：旧版散珠数据库升级时保留原数据并补齐新字段。
            existing = {row["name"] for row in connection.execute("PRAGMA table_info(material_items)")}
            for name, definition in (("library_category", "TEXT NOT NULL DEFAULT 'beads'"), ("observations", "TEXT NOT NULL DEFAULT '{}'"), ("observation_notes", "TEXT NOT NULL DEFAULT ''"), ("track_inventory", "INTEGER NOT NULL DEFAULT 1")):
                if name not in existing: connection.execute(f"ALTER TABLE material_items ADD COLUMN {name} {definition}")
            # 2026-10-15：本次修改原因：为新旧数据库补齐自定义属性列的 JSON 存储，保留原有资料结构。
            if "fact_attributes" not in existing:
                connection.execute("ALTER TABLE material_items ADD COLUMN fact_attributes TEXT NOT NULL DEFAULT '{}'")
            existing = {row["name"] for row in connection.execute("PRAGMA table_info(bead_designs)")}
            for name, definition in (("material_snapshot", "TEXT NOT NULL DEFAULT '{}'"), ("locked_material_revisions", "TEXT NOT NULL DEFAULT '{}'"), ("listing", "TEXT NOT NULL DEFAULT '{}'")):
                if name not in existing: connection.execute(f"ALTER TABLE bead_designs ADD COLUMN {name} {definition}")
            connection.execute("CREATE INDEX IF NOT EXISTS material_items_library ON material_items(library_category,state)")
            # 2026-10-15：本次修改原因：分页列表按类目和更新时间读取有效原料，使用索引减少大量表项的排序开销。
            connection.execute("CREATE INDEX IF NOT EXISTS material_items_paging ON material_items(library_category,updated_at DESC,code) WHERE state != 'archived'")
            connection.commit()
        finally: connection.close()

    # 2026-10-15：本次修改原因：全量选择和分页列表共用筛选条件，保证类目、原料类型与资料搜索的查询范围一致。
    @staticmethod
    def _material_filter(search: str, category: str, library_category: str) -> tuple[str, list[str]]:
        where = "state != 'archived' AND library_category=?"
        values = [library_category]
        if category:
            where += " AND category=?"
            values.append(category)
        if search:
            where += " AND (code LIKE ? OR name LIKE ? OR material_type LIKE ? OR facts LIKE ? OR observations LIKE ? OR fact_attributes LIKE ?)"
            values.extend([f"%{search}%"] * 6)
        return where, values

    def list_materials(self, search: str = "", category: str = "", library_category: str = "beads") -> list[MaterialItem]:
        connection = self._connection()
        try:
            # query = "SELECT * FROM material_items WHERE state != 'archived' AND library_category=?"; values = [library_category]
            # if category: query += " AND category=?"; values.append(category)
            # if search:
                # query += " AND (code LIKE ? OR name LIKE ? OR material_type LIKE ? OR facts LIKE ? OR observations LIKE ?)"; values.extend([f"%{search}%"] * 5)
                # 2026-10-15：本次修改原因：新增属性列中的资料也可通过数据库搜索找到。
                # query += " AND (code LIKE ? OR name LIKE ? OR material_type LIKE ? OR facts LIKE ? OR observations LIKE ? OR fact_attributes LIKE ?)"
                # values.extend([f"%{search}%"] * 6)
            # 2026-10-15：本次修改原因：保留设计模块的全量原料查询接口，筛选条件与新增分页接口共用。
            where, values = self._material_filter(search, category, library_category)
            query = "SELECT * FROM material_items WHERE " + where
            query += " ORDER BY updated_at DESC, code"
            return [MaterialItem.from_row(row) for row in connection.execute(query, values)]
        finally: connection.close()

    # 2026-10-15：本次修改原因：数据库页面只加载当前页，统计与读取使用同一快照，并在总页数减少时自动回退到最后一页。
    def page_materials(self, search: str = "", category: str = "", library_category: str = "beads",
                       *, page: int = 1, page_size: int = 50) -> tuple[list[MaterialItem], int, int]:
        if isinstance(page, bool) or not isinstance(page, int) or page < 1:
            raise ValueError("页码必须是正整数")
        if isinstance(page_size, bool) or not isinstance(page_size, int) or page_size < 1:
            raise ValueError("每页条数必须是正整数")
        where, values = self._material_filter(search, category, library_category)
        connection = self._connection()
        try:
            connection.execute("BEGIN")
            total = connection.execute("SELECT COUNT(*) FROM material_items WHERE " + where, values).fetchone()[0]
            page = min(page, max(1, (total + page_size - 1) // page_size))
            offset = (page - 1) * page_size
            query = "SELECT * FROM material_items WHERE " + where + " ORDER BY updated_at DESC, code LIMIT ? OFFSET ?"
            rows = [MaterialItem.from_row(row) for row in connection.execute(query, values + [page_size, offset])]
            return rows, total, page
        finally:
            connection.close()

    def material(self, item_id: str) -> MaterialItem | None:
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM material_items WHERE id=?", (item_id,)).fetchone()
            return MaterialItem.from_row(row) if row else None

    # 2026-10-15：本次修改原因：新增原料按全库流水自动起号，包含其他类目和归档记录，避免原料追溯编号重复。
    @staticmethod
    def _next_material_code(connection) -> str:
        highest = 0
        for row in connection.execute("SELECT code FROM material_items WHERE code GLOB 'M[0-9]*'"):
            suffix = row["code"][1:]
            if suffix.isascii() and suffix.isdecimal():
                highest = max(highest, int(suffix))
        return f"M{highest + 1:06d}"

    def save_material(self, item: MaterialItem, expected_revision: int | None = None) -> MaterialItem:
        # 2026-10-15：本次修改原因：事务提交成功前不改变调用者的编号和版本，失败后可直接重试。
        original = item
        item = deepcopy(item)
        # if not item.code.strip() or item.category not in MATERIAL_CATEGORIES: raise ValueError("原料编号和类别不能为空")
        # 2026-10-15：本次修改原因：新增原料允许留空自动编号，编辑已有原料仍禁止清空编号。
        item.code = item.code.strip()
        if item.category not in MATERIAL_CATEGORIES: raise ValueError("原料类别无效")
        if item.id and not item.code: raise ValueError("已有原料编号不能为空")
        if item.quantity < 0 or item.reserved_quantity < 0 or item.reserved_quantity > item.quantity: raise ValueError("库存和预留库存无效")
        if item.unit_cost and _money(item.unit_cost) is None: raise ValueError("单位成本必须是非负数字")
        # 2026-10-15：本次修改原因：自定义属性按列名和字段名保存纯文本，防止无效结构造成重开丢失。
        if not isinstance(item.fact_attributes, dict):
            raise ValueError("补充属性列资料无效")
        for title, cells in item.fact_attributes.items():
            if not isinstance(title, str) or not title.strip() or not isinstance(cells, dict):
                raise ValueError("补充属性列需要名称和有效的字段值")
            if any(not isinstance(key, str) or not key.strip() or not isinstance(value, str) for key, value in cells.items()):
                raise ValueError("补充属性的字段和值必须是文本")
        for key in item.facts:
            source, state = item.fact_sources.get(key, "unknown"), item.fact_statuses.get(key, "pending")
            if source not in FACT_SOURCES or state not in FACT_STATUSES:
                raise ValueError("资料来源或确认状态无效")
            if state == "confirmed" and (source == "unknown" or (source == "vision" and key not in VISIBLE_FACT_FIELDS)):
                raise ValueError("已确认的成分、尺寸等资料需要用户、供应商资料或人工实测来源")
            if key in {"diameter_mm", "hole_mm", "axial_mm"}:
                number = _money(item.facts[key])
                if number is None or number <= 0:
                    raise ValueError("直径、孔径和沿线占长请填大于零的毫米数；文字说明请填入尺寸说明")
        connection = self._connection()
        try:
            connection.execute("BEGIN IMMEDIATE")
            if not connection.execute("SELECT 1 FROM material_libraries WHERE id=?", (item.library_category,)).fetchone():
                raise ValueError("原料类目库不存在")
            # 2026-10-15：本次修改原因：在写事务内分配编号，并发新增或自定义编号均不会覆盖既有记录。
            if not item.code:
                item.code = self._next_material_code(connection)
            if item.id:
                previous = connection.execute("SELECT revision,created_at FROM material_items WHERE id=?", (item.id,)).fetchone()
                if previous is None: raise ValueError("原料记录不存在")
                if expected_revision is not None and int(previous["revision"]) != expected_revision: raise ValueError("原料已被更新，请重新打开")
                item.revision = int(previous["revision"]) + 1; item.created_at = previous["created_at"]
            else: item.id, item.created_at = uuid4().hex, now_iso()
            item.updated_at = now_iso()
            connection.execute("""INSERT INTO material_items
                (id,code,category,library_category,name,material_type,images,facts,fact_sources,fact_statuses,observations,observation_notes,unit_cost,currency,quantity,reserved_quantity,track_inventory,supplier,supplier_url,notes,state,revision,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET code=excluded.code,category=excluded.category,library_category=excluded.library_category,name=excluded.name,material_type=excluded.material_type,images=excluded.images,facts=excluded.facts,fact_sources=excluded.fact_sources,fact_statuses=excluded.fact_statuses,observations=excluded.observations,observation_notes=excluded.observation_notes,unit_cost=excluded.unit_cost,currency=excluded.currency,quantity=excluded.quantity,reserved_quantity=excluded.reserved_quantity,track_inventory=excluded.track_inventory,supplier=excluded.supplier,supplier_url=excluded.supplier_url,notes=excluded.notes,state=excluded.state,revision=excluded.revision,updated_at=excluded.updated_at""",
                (item.id,item.code.strip(),item.category,item.library_category or "beads",item.name.strip(),item.material_type.strip(),json.dumps(item.images,ensure_ascii=False),json.dumps(item.facts,ensure_ascii=False),json.dumps(item.fact_sources,ensure_ascii=False),json.dumps(item.fact_statuses,ensure_ascii=False),json.dumps(item.observations,ensure_ascii=False),item.observation_notes,item.unit_cost.strip(),item.currency.strip().upper() or "CNY",item.quantity,item.reserved_quantity,int(item.track_inventory),item.supplier.strip(),item.supplier_url.strip(),item.notes,item.state,item.revision,item.created_at,item.updated_at))
            # 2026-10-15：本次修改原因：补充属性列与原料资料在同一事务保存，任一步失败都不会只保存一半。
            connection.execute("UPDATE material_items SET fact_attributes=? WHERE id=?",
                               (json.dumps(item.fact_attributes, ensure_ascii=False), item.id))
            # connection.commit(); return item
            connection.commit()
            original.__dict__.update(item.__dict__)
            return original
        except sqlite3.IntegrityError as error: raise ValueError("原料编号已存在") from error
        finally: connection.close()

    def archive_material(self, item_id: str) -> None:
        # with self._connection() as connection: connection.execute("UPDATE material_items SET state='archived',updated_at=? WHERE id=?", (now_iso(), item_id)); connection.commit()
        # 2026-10-15：本次修改原因：归档也更新版本，使已生成的配方能够检测原料失效。
        with self._connection() as connection:
            connection.execute("UPDATE material_items SET state='archived',revision=revision+1,updated_at=? WHERE id=?", (now_iso(), item_id))

    def save_design(self, design: BeadDesign, expected_revision: int | None = None) -> BeadDesign:
        # 2026-10-15：本次修改原因：写入失败时保留原草稿的可重试版本号。
        original = design
        design = deepcopy(design)
        connection = self._connection()
        try:
            connection.execute("BEGIN IMMEDIATE")
            if design.id:
                previous = connection.execute("SELECT revision,created_at FROM bead_designs WHERE id=?", (design.id,)).fetchone()
                if previous is None: raise ValueError("设计项目不存在")
                if expected_revision is not None and int(previous["revision"]) != expected_revision: raise ValueError("设计项目已被更新，请重新打开")
                design.revision = int(previous["revision"]) + 1; design.created_at = previous["created_at"]
            else: design.id, design.created_at = uuid4().hex, now_iso()
            design.updated_at = now_iso()
            connection.execute("""INSERT INTO bead_designs (id,category,title,material_ids,material_snapshot,requirements,candidates,selected_candidate_id,locked_bom,locked_material_revisions,listing,listing_product_id,state,revision,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET category=excluded.category,title=excluded.title,material_ids=excluded.material_ids,material_snapshot=excluded.material_snapshot,requirements=excluded.requirements,candidates=excluded.candidates,selected_candidate_id=excluded.selected_candidate_id,locked_bom=excluded.locked_bom,locked_material_revisions=excluded.locked_material_revisions,listing=excluded.listing,listing_product_id=excluded.listing_product_id,state=excluded.state,revision=excluded.revision,updated_at=excluded.updated_at""",
                (design.id,design.category,design.title.strip(),json.dumps(design.material_ids),json.dumps(design.material_snapshot,ensure_ascii=False),json.dumps(design.requirements,ensure_ascii=False),json.dumps(design.candidates,ensure_ascii=False),design.selected_candidate_id,json.dumps(design.locked_bom,ensure_ascii=False),json.dumps(design.locked_material_revisions),json.dumps(design.listing,ensure_ascii=False),design.listing_product_id,design.state,design.revision,design.created_at,design.updated_at))
            # 2026-10-15：本次修改原因：项目覆盖保存时仍留存所有历史快照，追溯配方和采用的图片。
            from dataclasses import asdict
            connection.execute("INSERT INTO bead_design_versions VALUES (?,?,?,?)",(design.id,design.revision,json.dumps(asdict(design),ensure_ascii=False),design.updated_at))
            # connection.commit(); return design
            connection.commit()
            original.__dict__.update(design.__dict__)
            return original
        finally: connection.close()

    def designs(self, category: str = "beads") -> list[BeadDesign]:
        with self._connection() as connection: return [BeadDesign.from_row(row) for row in connection.execute("SELECT * FROM bead_designs WHERE category=? ORDER BY updated_at DESC", (category,))]

    def design(self, design_id: str) -> BeadDesign | None:
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM bead_designs WHERE id=?", (design_id,)).fetchone(); return BeadDesign.from_row(row) if row else None

    # 2026-10-15：本次修改原因：类目库独立于原料类型，未来设计模块可复用相同数据库。
    def libraries(self) -> list[tuple[str,str]]:
        with self._connection() as connection:
            return [(row["id"],row["title"]) for row in connection.execute("SELECT * FROM material_libraries ORDER BY CASE WHEN id='beads' THEN 0 ELSE 1 END,title")]

    def add_library(self, title: str) -> str:
        title = title.strip()
        if not title:
            raise ValueError("类目名称不能为空")
        key = uuid4().hex
        try:
            with self._connection() as connection: connection.execute("INSERT INTO material_libraries VALUES (?,?)",(key,title))
        except sqlite3.IntegrityError as error: raise ValueError("类目名称已存在") from error
        return key

    def versions(self, design_id: str) -> list[dict]:
        with self._connection() as connection:
            return [json.loads(row["body"]) for row in connection.execute("SELECT body FROM bead_design_versions WHERE design_id=? ORDER BY revision DESC",(design_id,))]

    def reserve_bom(self, bom: list[dict], release: list[dict] | None = None) -> None:
        """原子调整预留；生成 Listing 不会扣减或预留库存。"""
        release = release or []; delta: dict[str, int] = {}
        for line in release: delta[str(line.get("material_id"))] = delta.get(str(line.get("material_id")), 0) - int(line.get("quantity", 0))
        for line in bom: delta[str(line.get("material_id"))] = delta.get(str(line.get("material_id")), 0) + int(line.get("quantity", 0))
        connection = self._connection()
        try:
            connection.execute("BEGIN IMMEDIATE")
            for item_id, amount in delta.items():
                row = connection.execute("SELECT quantity,reserved_quantity,track_inventory FROM material_items WHERE id=?", (item_id,)).fetchone()
                if row is None: raise ValueError("BOM 引用了不存在的原料")
                # 2026-10-15：本次修改原因：预留接口仅供后续生产环节使用，不能预留未知库存或释放超过原预留量。
                if amount > 0 and not row["track_inventory"]: raise ValueError("请先登记库存再预留")
                reserved = int(row["reserved_quantity"]) + amount
                if not 0 <= reserved <= int(row["quantity"]): raise ValueError("原料可用库存或释放数量无效")
                connection.execute("UPDATE material_items SET reserved_quantity=?,revision=revision+1,updated_at=? WHERE id=?", (reserved, now_iso(), item_id))
            connection.commit()
        finally: connection.close()
