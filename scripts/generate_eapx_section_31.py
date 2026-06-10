#!/usr/bin/env python3
"""Generate three EA .eapx (Jet DB) projects for PZ section 3.1 class diagrams."""
from __future__ import annotations

import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

try:
    import pyodbc
except ImportError as exc:
    raise SystemExit("pyodbc required: pip install pyodbc") from exc

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "reports" / "uml" / "qq1 (2).eapx"
OUT_DIR = ROOT / "reports" / "uml"
ACCESS_DRIVER = "Microsoft Access Driver (*.mdb, *.accdb)"


def new_guid() -> str:
    return "{" + str(uuid.uuid4()).upper() + "}"


@dataclass
class UmlClass:
    name: str
    attrs: list[tuple[str, str]] = field(default_factory=list)  # (name, type)
    ops: list[tuple[str, str]] = field(default_factory=list)  # (name, return_type)


@dataclass
class UmlLink:
    src: str
    dst: str
    kind: str = "Dependency"  # Dependency | Association
    label: str = ""


@dataclass
class LayerModel:
    filename: str
    package_name: str
    diagram_name: str
    classes: list[UmlClass]
    links: list[UmlLink]


UI_MODEL = LayerModel(
    filename="fig3_1_ui_layer.eapx",
    package_name="01 UI Layer — Slot Display",
    diagram_name="Рис 3.1 UI — Slot Display",
    classes=[
        UmlClass(
            "MonitorOverlayScreen",
            [("api", "ParkingApiAdapter"), ("videoEl", "HTMLVideoElement"), ("overlayCanvas", "HTMLCanvasElement")],
            [("drawAutoSlots", "void"), ("updateStats", "void"), ("captureAndDetect", "void")],
        ),
        UmlClass(
            "SlotMapPanelScreen",
            [("api", "ParkingApiAdapter"), ("selectedSlotId", "string")],
            [("loadSlotMap", "void"), ("onSlotSelect", "void"), ("renderTraffic", "void")],
        ),
        UmlClass(
            "AdminSlotMapPanelScreen",
            [("api", "ParkingApiAdapter"), ("highlightSlotId", "string")],
            [("loadAdminMap", "void"), ("toggleSlotOverride", "void"), ("findByPlate", "void")],
        ),
        UmlClass("TrafficIndicatorWidget", [], [("renderTraffic", "void")]),
        UmlClass(
            "ParkingApiAdapter",
            [("baseUrl", "string")],
            [
                ("getSlotsMap", "Promise"),
                ("getTraffic", "Promise"),
                ("postDetect", "Promise"),
                ("putSlotOverride", "Promise"),
                ("findByPlate", "Promise"),
            ],
        ),
    ],
    links=[
        UmlLink("MonitorOverlayScreen", "ParkingApiAdapter"),
        UmlLink("SlotMapPanelScreen", "ParkingApiAdapter"),
        UmlLink("AdminSlotMapPanelScreen", "ParkingApiAdapter"),
        UmlLink("SlotMapPanelScreen", "TrafficIndicatorWidget"),
        UmlLink("MonitorOverlayScreen", "TrafficIndicatorWidget"),
    ],
)

BUSINESS_MODEL = LayerModel(
    filename="fig3_2_business_layer.eapx",
    package_name="02 Business Layer — Slot Display",
    diagram_name="Рис 3.2 Business — Slot Display",
    classes=[
        UmlClass(
            "SlotDisplayOrchestrator",
            [
                ("stateService", "SlotStateService"),
                ("trafficService", "TrafficIndicatorService"),
                ("overrideService", "SlotOverrideService"),
                ("detectionStore", "DetectionStateStore"),
            ],
            [
                ("getSlotsMapPayload", "object"),
                ("getTraffic", "object"),
                ("applyAdminOverride", "void"),
                ("findActiveByPlate", "list"),
            ],
        ),
        UmlClass(
            "SlotStateService",
            [("bookingRepo", "BookingRepository"), ("overrideService", "SlotOverrideService")],
            [("mergeState", "string"), ("isBookable", "boolean"), ("buildSlotsMapItems", "list")],
        ),
        UmlClass("TrafficIndicatorService", [], [("calcPctFree", "float"), ("classifyLevel", "string")]),
        UmlClass(
            "DetectionPipelineService",
            [("detectionStore", "DetectionStateStore")],
            [("runDetectOnFrame", "list"), ("debounceLabels", "list")],
        ),
        UmlClass(
            "SlotOverrideService",
            [("overrideRepo", "SlotOverrideRepository")],
            [("getOverrideMap", "map"), ("setOverride", "void"), ("validateStatus", "boolean")],
        ),
        UmlClass(
            "PlateLookupService",
            [("bookingRepo", "BookingRepository")],
            [("searchActiveByPlate", "list")],
        ),
        UmlClass(
            "User",
            [("id", "int"), ("username", "string"), ("role", "string")],
            [("getRole", "string"), ("isAdmin", "boolean")],
        ),
        UmlClass(
            "BookingRepository",
            [("db", "DbConnection")],
            [("findActiveBySlot", "set"), ("findActiveByPlate", "list")],
        ),
        UmlClass(
            "SlotOverrideRepository",
            [("db", "DbConnection")],
            [("findAll", "map"), ("upsert", "void")],
        ),
        UmlClass(
            "DetectionStateStore",
            [("lastSlots", "list"), ("lastTs", "float")],
            [("getLastSlots", "list"), ("setLastSlots", "void")],
        ),
    ],
    links=[
        UmlLink("SlotDisplayOrchestrator", "SlotStateService", "Association"),
        UmlLink("SlotDisplayOrchestrator", "TrafficIndicatorService", "Association"),
        UmlLink("SlotDisplayOrchestrator", "SlotOverrideService", "Association"),
        UmlLink("SlotDisplayOrchestrator", "DetectionStateStore", "Association"),
        UmlLink("SlotStateService", "BookingRepository", "Dependency"),
        UmlLink("SlotStateService", "SlotOverrideService", "Association"),
        UmlLink("SlotOverrideService", "SlotOverrideRepository", "Dependency"),
        UmlLink("DetectionPipelineService", "DetectionStateStore", "Dependency"),
        UmlLink("PlateLookupService", "BookingRepository", "Dependency"),
        UmlLink("SlotOverrideService", "User", "Dependency", "JWT / роль"),
        UmlLink("SlotDisplayOrchestrator", "User", "Dependency", "require_login"),
    ],
)

DATA_MODEL = LayerModel(
    filename="fig3_3_data_layer.eapx",
    package_name="03 Data Layer — Slot Display",
    diagram_name="Рис 3.3 Data — Slot Display",
    classes=[
        UmlClass(
            "BookingRepository",
            [("db", "DbConnection")],
            [("findActiveBySlot", "set"), ("findActiveByPlate", "list")],
        ),
        UmlClass(
            "SlotOverrideRepository",
            [("db", "DbConnection")],
            [("findAll", "map"), ("upsert", "void")],
        ),
        UmlClass(
            "DetectionStateStore",
            [("lastSlots", "list"), ("lastTs", "float")],
            [("getLastSlots", "list"), ("setLastSlots", "void")],
        ),
        UmlClass(
            "DbConnection",
            [("dbPath", "string"), ("lock", "Lock")],
            [("execute", "Row"), ("query", "list")],
        ),
    ],
    links=[
        UmlLink("BookingRepository", "DbConnection", "Dependency", "использует"),
        UmlLink("SlotOverrideRepository", "DbConnection", "Dependency", "использует"),
    ],
)

MODELS = [UI_MODEL, BUSINESS_MODEL, DATA_MODEL]


class EaProjectBuilder:
    def __init__(self, db_path: Path) -> None:
        self.path = db_path
        self.conn = pyodbc.connect(f"DRIVER={{{ACCESS_DRIVER}}};DBQ={db_path};")
        self.cur = self.conn.cursor()
        self.now = datetime.now().replace(microsecond=0)

    def close(self) -> None:
        self.conn.commit()
        self.conn.close()

    def _exec(self, sql: str, params: tuple | None = None) -> None:
        if params:
            self.cur.execute(sql, params)
        else:
            self.cur.execute(sql)

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
            "INSERT INTO t_package (Name, Parent_ID, CreatedDate, ModifiedDate, ea_guid) VALUES (?, ?, ?, ?, ?)",
            (name, parent_id, self.now, self.now, guid),
        )
        self._exec("SELECT @@IDENTITY")
        pkg_id = int(self.cur.fetchone()[0])
        return pkg_id, guid

    def insert_object(
        self,
        name: str,
        object_type: str,
        package_id: int,
        *,
        classifier_guid: str | None = None,
        parent_id: int = 0,
        pdata1: str | None = None,
    ) -> tuple[int, str]:
        guid = new_guid()
        self._exec(
            """
            INSERT INTO t_object
            (Object_Type, Diagram_ID, Name, Author, Version, Package_ID, CreatedDate, ModifiedDate,
             Status, Abstract, Tagged, GenType, Phase, Scope, Classifier, ea_guid, ParentID, Classifier_guid, TPos)
            VALUES (?, 0, ?, 'TKRP2', '1.0', ?, ?, ?, 'Proposed', '0', 0, '<none>', '1.0', 'Public', 0, ?, ?, ?, ?)
            """,
            (
                object_type,
                name,
                package_id,
                self.now,
                self.now,
                guid,
                parent_id,
                classifier_guid,
                0 if object_type == "Class" else None,
            ),
        )
        self._exec("SELECT @@IDENTITY")
        obj_id = int(self.cur.fetchone()[0])
        if pdata1:
            self._exec("UPDATE t_object SET PDATA1=? WHERE Object_ID=?", (pdata1, obj_id))
        return obj_id, guid

    def insert_attribute(self, object_id: int, name: str, typ: str, pos: int) -> None:
        self._exec(
            """
            INSERT INTO t_attribute
            (Object_ID, Name, Scope, Containment, Pos, Type, ea_guid, Derived, LowerBound, UpperBound)
            VALUES (?, ?, 'Private', 'Not Specified', ?, ?, ?, '0', '1', '1')
            """,
            (object_id, f"-{name}: {typ}", pos, typ, new_guid()),
        )

    def insert_operation(self, object_id: int, name: str, ret: str, pos: int) -> None:
        self._exec(
            """
            INSERT INTO t_operation
            (Object_ID, Name, Scope, Type, Pos, ea_guid, Concurrency, Pure, IsRoot, IsLeaf, IsQuery)
            VALUES (?, ?, 'Public', ?, ?, ?, 'Sequential', 0, 0, 0, 0)
            """,
            (object_id, f"+{name}(): {ret}", ret, pos, new_guid()),
        )

    def insert_diagram(self, package_id: int, name: str) -> tuple[int, str]:
        guid = new_guid()
        self._exec(
            """
            INSERT INTO t_diagram
            (Package_ID, ParentID, Diagram_Type, Name, Version, Author, AttPub, AttPri, AttPro,
             Orientation, cx, cy, Scale, CreatedDate, ModifiedDate, ShowForeign, ShowBorder,
             ShowPackageContents, Locked, ea_guid)
            VALUES (?, 0, 'Logical', ?, '1.0', 'TKRP2', 1, 1, 1, 'P', 826, 1169, 100, ?, ?, 1, 1, 1, 0, ?)
            """,
            (package_id, name, self.now, self.now, guid),
        )
        self._exec("SELECT @@IDENTITY")
        return int(self.cur.fetchone()[0]), guid

    def insert_diagram_object(self, diagram_id: int, object_id: int, left: int, top: int, width: int, height: int, seq: int) -> None:
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
                "NSL=0;BCol=-1;BFol=-1;LCol=-1;LWth=-1;fontsz=0;bold=0;black=0;italic=0;ul=0;",
                seq,
            ),
        )

    def insert_connector(
        self,
        start_id: int,
        end_id: int,
        connector_type: str,
        label: str = "",
    ) -> int:
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

    def build_layer(self, model: LayerModel) -> None:
        self.clear_model()

        model_pkg_id, _ = self.insert_package("Model")
        layer_pkg_id, layer_pkg_guid = self.insert_package(model.package_name, model_pkg_id)

        # Package object in t_object (required by EA hierarchy)
        self.insert_object(
            "Model",
            "Package",
            model_pkg_id,
            pdata1=str(model_pkg_id),
        )
        layer_obj_id, _ = self.insert_object(
            model.package_name,
            "Package",
            model_pkg_id,
            parent_id=0,
            pdata1=str(layer_pkg_id),
        )
        self._exec("UPDATE t_object SET Classifier_guid=? WHERE Object_ID=?", (layer_pkg_guid, layer_obj_id))

        diagram_id, _ = self.insert_diagram(layer_pkg_id, model.diagram_name)

        class_ids: dict[str, int] = {}
        n = len(model.classes)
        cols = max(3, min(4, n))
        cell_w, cell_h = 260, 220
        margin_x, margin_y = 80, -120

        for idx, cls in enumerate(model.classes):
            row, col = divmod(idx, cols)
            left = margin_x + col * (cell_w + 60)
            top = margin_y - row * (cell_h + 80)
            obj_id, _ = self.insert_object(cls.name, "Class", layer_pkg_id)
            class_ids[cls.name] = obj_id
            for pos, (aname, atype) in enumerate(cls.attrs):
                self.insert_attribute(obj_id, aname, atype, pos)
            for pos, (oname, oret) in enumerate(cls.ops):
                self.insert_operation(obj_id, oname, oret, pos)
            self.insert_diagram_object(diagram_id, obj_id, left, top, cell_w, cell_h, idx + 1)

        for link_idx, link in enumerate(model.links, start=1):
            cid = self.insert_connector(
                class_ids[link.src],
                class_ids[link.dst],
                link.kind,
                link.label,
            )
            self.insert_diagram_link(diagram_id, cid, link_idx)


def generate_all() -> list[Path]:
    if not TEMPLATE.exists():
        raise FileNotFoundError(f"Template not found: {TEMPLATE}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []

    for model in MODELS:
        out_path = OUT_DIR / model.filename
        shutil.copy2(TEMPLATE, out_path)
        builder = EaProjectBuilder(out_path)
        try:
            builder.build_layer(model)
        finally:
            builder.close()
        outputs.append(out_path)
        print(f"Created {out_path} ({out_path.stat().st_size} bytes)")

    return outputs


if __name__ == "__main__":
    paths = generate_all()
    for path in paths:
        conn = pyodbc.connect(f"DRIVER={{{ACCESS_DRIVER}}};DBQ={path};")
        cur = conn.cursor()
        cur.execute("SELECT Name FROM t_diagram")
        diagrams = [r[0] for r in cur.fetchall()]
        cur.execute("SELECT Name FROM t_object WHERE Object_Type='Class'")
        classes = [r[0] for r in cur.fetchall()]
        cur.execute("SELECT COUNT(*) FROM t_connector")
        links = cur.fetchone()[0]
        conn.close()
        print(f"  verify {path.name}: {len(classes)} classes, {links} links, diagram={diagrams}")
