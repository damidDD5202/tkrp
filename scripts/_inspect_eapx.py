import sys
import pyodbc

p = sys.argv[1]
conn = pyodbc.connect(f"DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={p};")
cur = conn.cursor()
cur.execute("SELECT Diagram_Type, Name FROM t_diagram")
print("diagrams:", cur.fetchall())
cur.execute("SELECT Name, Object_Type, Stereotype FROM t_object")
print("objects:")
for r in cur.fetchall():
    print(" ", r)
cur.execute("SELECT Name, Connector_Type FROM t_connector")
print("connectors:", cur.fetchall())
conn.close()
