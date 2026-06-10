#!/usr/bin/env python3
"""Generate XMI 2.1 for Enterprise Architect 15.2 import (Parking Eye UML)."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from xml.dom import minidom

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "reports" / "uml"
OUT = OUT_DIR / "parking_eye_ea152.xmi"

NS = {
    "xmi": "http://schema.omg.org/spec/XMI/2.1",
    "uml": "http://schema.omg.org/spec/UML/2.0",
}

# Register for output (avoid duplicate xmlns on root)
for prefix, uri in NS.items():
    ET.register_namespace(prefix, uri)


def to_xml(elem: ET.Element) -> str:
    rough = ET.tostring(elem, encoding="unicode")
    parsed = minidom.parseString(rough)
    body = parsed.toprettyxml(indent="  ", encoding="UTF-8").decode("utf-8")
    # minidom adds its own declaration; keep a single header below
    lines = [ln for ln in body.splitlines() if not ln.strip().startswith("<?xml")]
    return "\n".join(lines)


class XmiBuilder:
    def __init__(self) -> None:
        self._id = 0
        self.ids: dict[str, str] = {}

    def nid(self, key: str) -> str:
        if key not in self.ids:
            self._id += 1
            self.ids[key] = f"id_{self._id}"
        return self.ids[key]

    def enum(self, parent: ET.Element, pkg_key: str, name: str, literals: list[str]) -> None:
        e = ET.SubElement(
            parent,
            "{%s}packagedElement" % NS["uml"],
            {
                "{%s}type" % NS["xmi"]: "uml:Enumeration",
                "{%s}id" % NS["xmi"]: self.nid(f"{pkg_key}:enum:{name}"),
                "name": name,
            },
        )
        for lit in literals:
            ET.SubElement(
                e,
                "{%s}ownedLiteral" % NS["uml"],
                {
                    "{%s}type" % NS["xmi"]: "uml:EnumerationLiteral",
                    "{%s}id" % NS["xmi"]: self.nid(f"{pkg_key}:enum:{name}:{lit}"),
                    "name": lit,
                },
            )

    def cls(self, parent: ET.Element, pkg_key: str, name: str, attrs: list[tuple[str, str]]) -> str:
        cid = self.nid(f"{pkg_key}:class:{name}")
        c = ET.SubElement(
            parent,
            "{%s}packagedElement" % NS["uml"],
            {
                "{%s}type" % NS["xmi"]: "uml:Class",
                "{%s}id" % NS["xmi"]: cid,
                "name": name,
            },
        )
        for aname, atype in attrs:
            ET.SubElement(
                c,
                "{%s}ownedAttribute" % NS["uml"],
                {
                    "{%s}type" % NS["xmi"]: "uml:Property",
                    "{%s}id" % NS["xmi"]: self.nid(f"{pkg_key}:class:{name}:attr:{aname}"),
                    "name": aname,
                    "visibility": "public",
                    "type": atype,
                },
            )
        return cid

    def association(
        self,
        parent: ET.Element,
        pkg_key: str,
        name: str,
        end1_class: str,
        end2_class: str,
        mult1: str,
        mult2: str,
        role1: str,
        role2: str,
        agg1: str = "none",
        agg2: str = "none",
    ) -> None:
        aid = self.nid(f"{pkg_key}:assoc:{name}")
        a = ET.SubElement(
            parent,
            "{%s}packagedElement" % NS["uml"],
            {
                "{%s}type" % NS["xmi"]: "uml:Association",
                "{%s}id" % NS["xmi"]: aid,
                "name": name,
            },
        )
        e1 = self.nid(f"{pkg_key}:assoc:{name}:e1")
        e2 = self.nid(f"{pkg_key}:assoc:{name}:e2")
        a.set("memberEnd", f"{e1} {e2}")
        for eid, cname, mult, role, agg, assoc_end in (
            (e1, end1_class, mult1, role1, agg1, aid),
            (e2, end2_class, mult2, role2, agg2, aid),
        ):
            low, up = self._parse_mult(mult)
            pe = ET.SubElement(
                a,
                "{%s}ownedEnd" % NS["uml"],
                {
                    "{%s}type" % NS["xmi"]: "uml:Property",
                    "{%s}id" % NS["xmi"]: eid,
                    "name": role,
                    "visibility": "public",
                    "aggregation": agg,
                    "association": assoc_end,
                    "type": self.nid(f"{pkg_key}:class:{cname}"),
                },
            )
            if low is not None:
                ET.SubElement(
                    pe,
                    "{%s}lowerValue" % NS["uml"],
                    {"{%s}type" % NS["xmi"]: "uml:LiteralInteger", "{%s}id" % NS["xmi"]: self.nid(f"{eid}:lo"), "value": str(low)},
                )
            if up is not None:
                uv = ET.SubElement(
                    pe,
                    "{%s}upperValue" % NS["uml"],
                    {"{%s}type" % NS["xmi"]: "uml:LiteralUnlimitedNatural", "{%s}id" % NS["xmi"]: self.nid(f"{eid}:up")},
                )
                uv.set("value", up)

    def dependency(self, parent: ET.Element, pkg_key: str, name: str, src: str, dst: str) -> None:
        ET.SubElement(
            parent,
            "{%s}packagedElement" % NS["uml"],
            {
                "{%s}type" % NS["xmi"]: "uml:Dependency",
                "{%s}id" % NS["xmi"]: self.nid(f"{pkg_key}:dep:{name}"),
                "name": name,
                "client": self.nid(f"{pkg_key}:class:{src}"),
                "supplier": self.nid(f"{pkg_key}:class:{dst}"),
            },
        )

    @staticmethod
    def _parse_mult(mult: str) -> tuple[int | None, str | None]:
        if mult == "1":
            return 1, "1"
        if mult == "0..1":
            return 0, "1"
        if mult == "0..*":
            return 0, "*"
        if mult == "1..*":
            return 1, "*"
        if mult == "*":
            return 0, "*"
        return None, None


def build_package_only(b: XmiBuilder, pkg_name: str, pkg_key: str, builder_fn) -> ET.Element:
    """Single root package — EA 15.2 often flattens nested packages on import."""
    xmi = ET.Element("{%s}XMI" % NS["xmi"], {"{%s}version" % NS["xmi"]: "2.1"})
    model = ET.SubElement(
        xmi,
        "{%s}Model" % NS["uml"],
        {"{%s}type" % NS["xmi"]: "uml:Model", "{%s}id" % NS["xmi"]: b.nid(f"{pkg_key}:model"), "name": pkg_name},
    )
    pkg = ET.SubElement(
        model,
        "{%s}packagedElement" % NS["uml"],
        {"{%s}type" % NS["xmi"]: "uml:Package", "{%s}id" % NS["xmi"]: b.nid(f"{pkg_key}:root"), "name": pkg_name},
    )
    builder_fn(b, pkg, pkg_key)
    return xmi


def build_pkg1(b: XmiBuilder, p1: ET.Element, pk1: str) -> None:
    for en, lits in [
        ("Role", ["user", "admin"]),
        ("BookingStatus", ["active", "cancelled", "completed"]),
        ("SlotVisualStatus", ["slot_free", "slot_occupied"]),
        ("PaymentStatus", ["paid", "refunded"]),
    ]:
        b.enum(p1, pk1, en, lits)

    classes1 = {
        "User": [("user_id", "int"), ("username", "string"), ("password_hash", "string"), ("display_name", "string"), ("role", "Role"), ("active", "bool"), ("block_reason", "string"), ("created_ts", "datetime")],
        "AuthSession": [("session_id", "int"), ("token_hash", "string"), ("user_id", "int"), ("created_ts", "datetime"), ("expires_ts", "datetime")],
        "Booking": [("booking_id", "int"), ("user_id", "int"), ("slot_id", "string"), ("plate", "string"), ("start_ts", "datetime"), ("end_ts", "datetime"), ("status", "BookingStatus"), ("note", "string"), ("created_ts", "datetime")],
        "Payment": [("payment_id", "int"), ("user_id", "int"), ("booking_id", "int"), ("amount_rub", "float"), ("status", "PaymentStatus"), ("receipt_id", "string"), ("created_ts", "datetime")],
        "ParkingSlot": [("slot_id", "string"), ("label", "string"), ("current_status", "SlotVisualStatus"), ("points_norm", "float[][]"), ("confidence", "float")],
        "SlotOverride": [("slot_id", "string"), ("status", "string"), ("note", "string"), ("updated_ts", "datetime")],
        "Observation": [("observation_id", "int"), ("ts", "datetime"), ("dt_ms", "int"), ("total", "int"), ("free", "int"), ("occupied", "int"), ("slots_json", "string")],
        "Snapshot": [("snapshot_id", "int"), ("ts", "datetime"), ("event_id", "int"), ("name", "string"), ("data", "blob")],
        "TariffSettings": [("hour_rub", "float"), ("currency", "string")],
        "YoloModel": [("model_id", "string"), ("weights_path", "string"), ("conf_threshold", "float"), ("is_active", "bool")],
        "TrafficIndicator": [("level", "string"), ("free", "int"), ("occupied", "int"), ("total", "int")],
    }
    for cn, attrs in classes1.items():
        b.cls(p1, pk1, cn, attrs)

    b.association(p1, pk1, "opens", "User", "AuthSession", "1", "0..*", "user", "session")
    b.association(p1, pk1, "creates", "User", "Booking", "1", "0..*", "user", "booking")
    b.association(p1, pk1, "pays", "User", "Payment", "1", "0..*", "user", "payment")
    b.association(p1, pk1, "belongs_to", "Booking", "User", "0..*", "1", "booking", "user")
    b.association(p1, pk1, "reserves", "Booking", "ParkingSlot", "0..*", "1", "booking", "slot")
    b.association(p1, pk1, "paid_by", "Booking", "Payment", "1", "0..*", "booking", "payment")
    b.association(p1, pk1, "overrides", "SlotOverride", "ParkingSlot", "0..1", "1", "override", "slot")
    b.dependency(p1, pk1, "infers", "YoloModel", "Observation")
    b.dependency(p1, pk1, "describes", "Observation", "ParkingSlot")
    b.dependency(p1, pk1, "derives", "Observation", "TrafficIndicator")
    b.dependency(p1, pk1, "stores_frame_of", "Snapshot", "Observation")
    b.dependency(p1, pk1, "prices", "TariffSettings", "Booking")
    b.dependency(p1, pk1, "calculates", "TariffSettings", "Payment")


def build_pkg2(b: XmiBuilder, p2: ET.Element, pk2: str) -> None:
    for cn, attrs in {
        "Booking": [("booking_id", "int"), ("slot_id", "string"), ("start_ts", "datetime"), ("end_ts", "datetime")],
        "Payment": [("payment_id", "int"), ("amount_rub", "float"), ("receipt_id", "string")],
        "ParkingSlot": [("slot_id", "string"), ("current_status", "string")],
        "Observation": [("observation_id", "int"), ("slots_json", "string"), ("ts", "datetime")],
    }.items():
        b.cls(p2, pk2, cn, attrs)
    b.association(p2, pk2, "has_payments", "Booking", "Payment", "1", "0..*", "booking", "payment")
    b.association(p2, pk2, "for_slot", "Booking", "ParkingSlot", "*", "1", "booking", "slot")
    b.association(p2, pk2, "detects", "Observation", "ParkingSlot", "1", "0..*", "observation", "slot")


def build_pkg3(b: XmiBuilder, p3: ET.Element, pk3: str) -> None:
    for cn, attrs in {
        "ParkingMonitor": [("name", "string"), ("sse_endpoint", "string")],
        "YoloModel": [("model_id", "string"), ("weights_path", "string")],
        "ParkingSlot": [("slot_id", "string")],
        "Booking": [("booking_id", "int")],
        "Payment": [("payment_id", "int")],
        "Observation": [("observation_id", "int")],
    }.items():
        b.cls(p3, pk3, cn, attrs)
    b.association(p3, pk3, "uses_models", "ParkingMonitor", "YoloModel", "1", "1..*", "monitor", "model", agg1="shared")
    b.association(p3, pk3, "contains_slots", "ParkingMonitor", "ParkingSlot", "1", "1..*", "monitor", "slot", agg1="composite")
    b.association(p3, pk3, "includes", "Booking", "Payment", "1", "0..*", "booking", "payment", agg1="composite")
    b.association(p3, pk3, "logs", "ParkingMonitor", "Observation", "1", "0..*", "monitor", "observation", agg1="composite")


def build() -> ET.Element:
    b = XmiBuilder()
    xmi = ET.Element("{%s}XMI" % NS["xmi"], {"{%s}version" % NS["xmi"]: "2.1"})
    model = ET.SubElement(
        xmi,
        "{%s}Model" % NS["uml"],
        {"{%s}type" % NS["xmi"]: "uml:Model", "{%s}id" % NS["xmi"]: b.nid("model"), "name": "ParkingEye"},
    )
    root_pkg = ET.SubElement(
        model,
        "{%s}packagedElement" % NS["uml"],
        {"{%s}type" % NS["xmi"]: "uml:Package", "{%s}id" % NS["xmi"]: b.nid("root_pkg"), "name": "Parking Eye"},
    )
    p1 = ET.SubElement(
        root_pkg,
        "{%s}packagedElement" % NS["uml"],
        {"{%s}type" % NS["xmi"]: "uml:Package", "{%s}id" % NS["xmi"]: b.nid("pkg1"), "name": "01 Domain Class Diagram"},
    )
    build_pkg1(b, p1, "pkg1")
    p2 = ET.SubElement(
        root_pkg,
        "{%s}packagedElement" % NS["uml"],
        {"{%s}type" % NS["xmi"]: "uml:Package", "{%s}id" % NS["xmi"]: b.nid("pkg2"), "name": "02 Association Specification"},
    )
    build_pkg2(b, p2, "pkg2")
    p3 = ET.SubElement(
        root_pkg,
        "{%s}packagedElement" % NS["uml"],
        {"{%s}type" % NS["xmi"]: "uml:Package", "{%s}id" % NS["xmi"]: b.nid("pkg3"), "name": "03 Aggregation Composition"},
    )
    build_pkg3(b, p3, "pkg3")
    return xmi


def write_xmi(path: Path, xmi: ET.Element) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n' + to_xml(xmi)
    path.write_text(xml, encoding="utf-8")
    print(f"Written: {path}")


def main() -> None:
    write_xmi(OUT, build())
    singles = [
        ("ea152_fig1_domain.xmi", "01 Domain Class Diagram", "s1", build_pkg1),
        ("ea152_fig2_associations.xmi", "02 Association Specification", "s2", build_pkg2),
        ("ea152_fig3_aggregation.xmi", "03 Aggregation Composition", "s3", build_pkg3),
    ]
    for fname, pname, pkey, fn in singles:
        b = XmiBuilder()
        write_xmi(OUT_DIR / fname, build_package_only(b, pname, pkey, fn))


if __name__ == "__main__":
    main()
