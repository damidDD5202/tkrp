#!/usr/bin/env python3
"""Generate EA .eapx (Jet DB) for PZ section 3.4 — database ER diagram (classmate style)."""
from __future__ import annotations

import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

try:
    import pyodbc
except ImportError as exc:
    raise SystemExit("pyodbc required: pip install pyodbc") from exc

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "reports" / "uml" / "fig3_3_data_layer.eapx"
OUT = ROOT / "reports" / "uml" / "fig3_4_database.eapx"
ACCESS_DRIVER = "Microsoft Access Driver (*.mdb, *.accdb)"


def new_guid() -> str:
    return "{" + str(uuid.uuid4()).upper() + "}"


@dataclass
class DbColumn:
    name: str
    col_type: str
    pk: bool = False


@dataclass
class DbTable:
    name: str
    columns: list[DbColumn]
    fks: list[tuple[str, str]] = ()  # (constraint_name, column_type)
    indexes: list[tuple[str, str]] = ()  # (index_name, columns)
    pk_name: str = ""
    abstract: bool = False  # пунктир для логической сущности


@dataclass
class DbLink:
    src: str
    dst: str
    kind: str = "Association"  # Association = сплошная FK; Dependency = пунктир
    label: str = ""


# Макет как у одногруппника: users слева, bookings по центру, slot_overrides справа,
# parking_slot снизу по центру, observations слева снизу.
DB_MODEL = {
    "package": "03.4 Database — Slot Display",
    "diagram": "dm SlotDisplayScreen",
    "tables": [
        DbTable(
            "users",
            [
                DbColumn("id", "INTEGER", pk=True),
                DbColumn("username", "TEXT"),
                DbColumn("password_hash", "TEXT"),
                DbColumn("display_name", "TEXT"),
                DbColumn("role", "TEXT"),
                DbColumn("active", "INTEGER"),
                DbColumn("block_reason", "TEXT"),
                DbColumn("created_ts", "REAL"),
            ],
            pk_name="PK_users",
        ),
        DbTable(
            "bookings",
            [
                DbColumn("id", "INTEGER", pk=True),
                DbColumn("user_id", "INTEGER"),
                DbColumn("slot_id", "TEXT"),
                DbColumn("start_ts", "REAL"),
                DbColumn("end_ts", "REAL"),
                DbColumn("status", "TEXT"),
                DbColumn("note", "TEXT"),
                DbColumn("created_ts", "REAL"),
                DbColumn("plate", "TEXT"),
            ],
            fks=(("FK_bookings_users", "INTEGER"),),
            indexes=(
                (
                    "idx_bookings_slot_active",
                    "slot_id, status, start_ts, end_ts",
                ),
            ),
            pk_name="PK_bookings",
        ),
        DbTable(
            "slot_overrides",
            [
                DbColumn("slot_id", "TEXT", pk=True),
                DbColumn("status", "TEXT"),
                DbColumn("note", "TEXT"),
                DbColumn("updated_ts", "REAL"),
            ],
            pk_name="PK_slot_overrides",
        ),
        DbTable(
            "observations",
            [
                DbColumn("id", "INTEGER", pk=True),
                DbColumn("ts", "REAL"),
                DbColumn("dt_ms", "INTEGER"),
                DbColumn("total", "INTEGER"),
                DbColumn("free", "INTEGER"),
                DbColumn("occupied", "INTEGER"),
                DbColumn("slots_json", "TEXT"),
            ],
            pk_name="PK_observations",
        ),
        DbTable(
            "parking_slot",
            [
                DbColumn("slot_id", "TEXT", pk=True),
                DbColumn("label", "TEXT"),
                DbColumn("points_norm", "JSON"),
            ],
            pk_name="PK_parking_slot",
            abstract=True,
        ),
    ],
    "links": [
        DbLink("users", "bookings", "Association", "+FK_bookings_users"),
        DbLink("users", "bookings", "Dependency", "JWT"),
        DbLink("users", "slot_overrides", "Dependency", "JWT"),
        DbLink("bookings", "parking_slot", "Dependency", "logic"),
        DbLink("slot_overrides", "parking_slot", "Dependency", "logic"),
        DbLink("observations", "parking_slot", "Dependency", "slots_json"),
    ],
    "layout": {
        "users": (40, -80, 220, 320),
        "bookings": (320, -80, 240, 340),
        "slot_overrides": (620, -80, 230, 220),
        "observations": (40, -480, 230, 260),
        "parking_slot": (320, -520, 240, 180),
    },
}


class EaDbBuilder:
    def __init__(self, db_path: Path) -> None:
        self.conn = pyodbc.connect(f"DRIVER={{{ACCESS_DRIVER}}};DBQ={db_path};")
        self.cur = self.conn.cursor()
        self.now = datetime.now().replace(microsecond=0)

    def close(self) -> None:
        self.conn.commit()
        self.conn.close()

    def _exec(self, sql: str, params: tuple | None = None) -> None:
        self.cur.execute(sql, params if params else ())

    def clear_model(self) -> None:
        for tbl in (
            "t_diagramlinks",
            "t_diagramobjects",
            "t_connector",
            "t_operation",
            "t_attribute",
            "t_diagram",
            "t_object",
            "t_package",
        ):
            self._exec(f"DELETE FROM {tbl}")

    def insert_package(self, name: str, parent_id: int = 0) -> tuple[int, str]:
        guid = new_guid()
        self._exec(
            "INSERT INTO t_package (Name, Parent_ID, CreatedDate, ModifiedDate, ea_guid) "
            "VALUES (?, ?, ?, ?, ?)",
            (name, parent_id, self.now, self.now, guid),
        )
        self._exec("SELECT @@IDENTITY")
        return int(self.cur.fetchone()[0]), guid

    def insert_object(
        self,
        name: str,
        object_type: str,
        package_id: int,
        *,
        abstract: bool = False,
        note: str | None = None,
        pdata1: str | None = None,
        classifier_guid: str | None = None,
    ) -> tuple[int, str]:
        guid = new_guid()
        self._exec(
            """
            INSERT INTO t_object
            (Object_Type, Diagram_ID, Name, Author, Version, Package_ID, CreatedDate, ModifiedDate,
             Status, Abstract, Tagged, GenType, Phase, Scope, Classifier, ea_guid, ParentID, Classifier_guid, TPos)
            VALUES (?, 0, ?, 'TKRP2', '1.0', ?, ?, ?, 'Proposed', ?, 0, '<none>', '1.0', 'Public', 0, ?, 0, ?, ?)
            """,
            (
                object_type,
                name,
                package_id,
                self.now,
                self.now,
                "1" if abstract else "0",
                guid,
                classifier_guid,
                0 if object_type == "Class" else None,
            ),
        )
        self._exec("SELECT @@IDENTITY")
        obj_id = int(self.cur.fetchone()[0])
        if pdata1:
            self._exec("UPDATE t_object SET PDATA1=? WHERE Object_ID=?", (pdata1, obj_id))
        if note:
            self._exec("UPDATE t_object SET [Note]=? WHERE Object_ID=?", (note, obj_id))
        return obj_id, guid

    def insert_attr(
        self, object_id: int, name: str, typ: str, pos: int, stereotype: str = ""
    ) -> None:
        self._exec(
            """
            INSERT INTO t_attribute
            (Object_ID, Name, Scope, Stereotype, Containment, Pos, Type, ea_guid, Derived, LowerBound, UpperBound)
            VALUES (?, ?, 'Private', ?, 'Not Specified', ?, ?, ?, '0', '1', '1')
            """,
            (object_id, name, stereotype, pos, typ, new_guid()),
        )

    def insert_table_attrs(self, object_id: int, table: DbTable) -> None:
        pos = 0
        self.insert_attr(object_id, "column", "", pos, "column")
        pos += 1
        for col in table.columns:
            prefix = "*" if col.pk else ""
            self.insert_attr(
                object_id,
                f"{prefix}{col.name}: {col.col_type}",
                col.col_type,
                pos,
                "column",
            )
            pos += 1

        if table.fks:
            self.insert_attr(object_id, "FK", "", pos, "FK")
            pos += 1
            for fk_name, fk_type in table.fks:
                self.insert_attr(
                    object_id,
                    f"{fk_name}: {fk_type}",
                    fk_type,
                    pos,
                    "FK",
                )
                pos += 1

        if table.indexes:
            self.insert_attr(object_id, "index", "", pos, "index")
            pos += 1
            for idx_name, cols in table.indexes:
                self.insert_attr(
                    object_id,
                    f"{idx_name}: {cols}",
                    cols,
                    pos,
                    "index",
                )
                pos += 1

        if table.pk_name:
            pk_col = next(c for c in table.columns if c.pk)
            self.insert_attr(object_id, "PK", "", pos, "PK")
            pos += 1
            self.insert_attr(
                object_id,
                f"{table.pk_name}: {pk_col.col_type}",
                pk_col.col_type,
                pos,
                "PK",
            )

    def insert_diagram(self, package_id: int, name: str) -> int:
        guid = new_guid()
        self._exec(
            """
            INSERT INTO t_diagram
            (Package_ID, ParentID, Diagram_Type, Name, Version, Author, AttPub, AttPri, AttPro,
             Orientation, cx, cy, Scale, CreatedDate, ModifiedDate, ShowForeign, ShowBorder,
             ShowPackageContents, Locked, ea_guid)
            VALUES (?, 0, 'Logical', ?, '1.0', 'TKRP2', 1, 1, 1, 'P', 1200, 900, 100, ?, ?, 1, 1, 1, 0, ?)
            """,
            (package_id, name, self.now, self.now, guid),
        )
        self._exec("SELECT @@IDENTITY")
        return int(self.cur.fetchone()[0])

    def insert_diagram_object(
        self, diagram_id: int, object_id: int, left: int, top: int, width: int, height: int, seq: int
    ) -> None:
        self._exec(
            """
            INSERT INTO t_diagramobjects
            (Diagram_ID, Object_ID, RectTop, RectLeft, RectRight, RectBottom, Sequence, ObjectStyle, Instance_ID)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                diagram_id,
                object_id,
                top,
                left,
                left + width,
                top + height,
                seq,
                "NSL=0;BCol=-1;BFol=-1;LCol=-1;LWth=-1;fontsz=0;",
                seq,
            ),
        )

    def insert_connector(self, start_id: int, end_id: int, connector_type: str, label: str) -> int:
        self._exec(
            """
            INSERT INTO t_connector
            (Name, Direction, Connector_Type, Start_Object_ID, End_Object_ID, RouteStyle, LineColor,
             SourceIsNavigable, DestIsNavigable, SourceChangeable, DestChangeable, SourceTS, DestTS,
             IsRoot, IsLeaf, IsSpec, IsSignal, IsStimulus, Target2, ea_guid, PDATA5)
            VALUES (?, 'Source -> Destination', ?, ?, ?, 3, -1, 0, 1, 'none', 'none', 'instance', 'instance',
                    0, 0, 0, 0, 0, 0, ?, 'SX=0;SY=0;EX=0;EY=0;')
            """,
            (label or connector_type, connector_type, start_id, end_id, new_guid()),
        )
        self._exec("SELECT @@IDENTITY")
        return int(self.cur.fetchone()[0])

    def insert_diagram_link(self, diagram_id: int, connector_id: int, instance_id: int) -> None:
        self._exec(
            """
            INSERT INTO t_diagramlinks (DiagramID, ConnectorID, Geometry, Style, Hidden, Instance_ID)
            VALUES (?, ?, 'SX=0;SY=0;EX=0;EY=0;', 'Mode=3;Color=-1;LWidth=0;', 0, ?)
            """,
            (diagram_id, connector_id, instance_id),
        )

    def build(self) -> None:
        self.clear_model()
        model_pkg_id, _ = self.insert_package("Model")
        layer_pkg_id, layer_pkg_guid = self.insert_package(DB_MODEL["package"], model_pkg_id)

        self.insert_object("Model", "Package", model_pkg_id, pdata1=str(model_pkg_id))
        layer_obj_id, _ = self.insert_object(
            DB_MODEL["package"], "Package", model_pkg_id, pdata1=str(layer_pkg_id)
        )
        self._exec(
            "UPDATE t_object SET Classifier_guid=? WHERE Object_ID=?",
            (layer_pkg_guid, layer_obj_id),
        )

        diagram_id = self.insert_diagram(layer_pkg_id, DB_MODEL["diagram"])
        table_ids: dict[str, int] = {}
        seq = 1

        for table in DB_MODEL["tables"]:
            note = None
            if table.name == "parking_slot":
                note = "Логическая сущность: отдельной таблицы в SQLite нет.\nslot_id совпадает с id из конфига и детекции."
            obj_id, _ = self.insert_object(
                table.name,
                "Class",
                layer_pkg_id,
                abstract=table.abstract,
                note=note,
            )
            table_ids[table.name] = obj_id
            self.insert_table_attrs(obj_id, table)
            left, top, w, h = DB_MODEL["layout"][table.name]
            self.insert_diagram_object(diagram_id, obj_id, left, top, w, h, seq)
            seq += 1

        for link_idx, link in enumerate(DB_MODEL["links"], start=1):
            cid = self.insert_connector(
                table_ids[link.src],
                table_ids[link.dst],
                link.kind,
                link.label,
            )
            self.insert_diagram_link(diagram_id, cid, link_idx)


def generate() -> Path:
    if not TEMPLATE.exists():
        raise FileNotFoundError(f"Template not found: {TEMPLATE}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(TEMPLATE, OUT)
    builder = EaDbBuilder(OUT)
    try:
        builder.build()
    finally:
        builder.close()
    print(f"Created {OUT} ({OUT.stat().st_size} bytes)")

    conn = pyodbc.connect(f"DRIVER={{{ACCESS_DRIVER}}};DBQ={OUT};")
    cur = conn.cursor()
    cur.execute("SELECT Name FROM t_object WHERE Object_Type='Class'")
    tables = [r[0] for r in cur.fetchall()]
    cur.execute("SELECT Name, Connector_Type FROM t_connector")
    links = cur.fetchall()
    conn.close()
    print(f"  verify: {len(tables)} tables, {len(links)} links")
    for name, kind in links:
        print(f"    {kind}: {name}")
    return OUT


if __name__ == "__main__":
    generate()
