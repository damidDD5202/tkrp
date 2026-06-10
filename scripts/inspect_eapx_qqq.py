#!/usr/bin/env python3
"""Inspect EA Jet .eapx (qqq friend's file)."""
import pyodbc
from pathlib import Path


def main() -> None:
    p = Path(__file__).resolve().parents[1] / "reports" / "uml" / "qqq (2).eapx"
    conn = pyodbc.connect(
        f"DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={p};"
    )
    cur = conn.cursor()
    cur.execute("SELECT Name FROM t_package")
    print("packages:", [r[0] for r in cur.fetchall()])
    cur.execute("SELECT Diagram_Type, Name FROM t_diagram")
    print("diagrams:", cur.fetchall())

    cur.execute("SELECT DISTINCT Object_Type FROM t_object")
    print("object_types:", sorted(r[0] for r in cur.fetchall()))

    print("\nactors (repr):")
    cur.execute(
        "SELECT Name FROM t_object WHERE Object_Type='Actor' ORDER BY Object_ID"
    )
    for (name,) in cur.fetchall():
        print(" ", repr(name))

    print("\nuse cases (repr):")
    cur.execute(
        "SELECT Name FROM t_object WHERE Object_Type='UseCase' ORDER BY Object_ID"
    )
    for (name,) in cur.fetchall():
        print(" ", repr(name))

    cur.execute(
        """
        SELECT Name, Object_Type, Stereotype
        FROM t_object
        WHERE Object_Type NOT IN ('Package')
        ORDER BY Object_Type, Name
        """
    )
    print("\nelements (sample up to 80):")
    for i, r in enumerate(cur.fetchall()):
        if i >= 80:
            break
        print(f"  {r[1]} | {r[2] or '-'} | {r[0]!r}")

    cur.execute("SELECT Connector_Type, COUNT(*) FROM t_connector GROUP BY Connector_Type")
    print("\nconnectors by type:", cur.fetchall())
    conn.close()


if __name__ == "__main__":
    main()
