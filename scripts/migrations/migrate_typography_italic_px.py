"""
Migration: add H1Italic/H2Italic/H3Italic/H4Italic/BodyItalic columns and
convert existing rem/em typography sizes to px on BusinessWebsite.

Run once from the Backend directory:  python migrate_typography_italic_px.py
"""
import os
import re
import pymssql
from dotenv import load_dotenv

load_dotenv()

conn = pymssql.connect(
    server=os.getenv("DB_SERVER"),
    user=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD"),
    database=os.getenv("DB_NAME"),
)
cursor = conn.cursor(as_dict=True)

italic_columns = ["H1Italic", "H2Italic", "H3Italic", "H4Italic", "BodyItalic"]

for col_name in italic_columns:
    cursor.execute(
        """
        SELECT COUNT(*) AS cnt
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_NAME = 'BusinessWebsite'
          AND COLUMN_NAME = %s
        """,
        (col_name,),
    )
    row = cursor.fetchone()
    if row["cnt"] == 0:
        print(f"Adding column {col_name}...")
        cursor.execute(
            f"ALTER TABLE BusinessWebsite ADD {col_name} BIT NOT NULL CONSTRAINT DF_BusinessWebsite_{col_name} DEFAULT 0"
        )
        conn.commit()
        print(f"  OK: {col_name} added.")
    else:
        print(f"  - {col_name} already exists, skipping.")

# Convert any remaining rem/em values in size columns to px (1rem == 16px).
size_columns = ["H1Size", "H2Size", "H3Size", "H4Size", "BodySize"]
rem_rx = re.compile(r"^\s*([0-9]*\.?[0-9]+)\s*(rem|em)\s*$", re.I)

print("\nConverting rem/em typography sizes to px...")
for col in size_columns:
    cursor.execute(
        f"SELECT WebsiteID, {col} AS val FROM BusinessWebsite WHERE {col} LIKE '%rem' OR {col} LIKE '%em'"
    )
    rows = cursor.fetchall()
    updated = 0
    for r in rows:
        m = rem_rx.match(r["val"] or "")
        if not m:
            continue
        px = int(round(float(m.group(1)) * 16))
        cursor.execute(
            f"UPDATE BusinessWebsite SET {col} = %s WHERE WebsiteID = %s",
            (f"{px}px", r["WebsiteID"]),
        )
        updated += 1
    conn.commit()
    print(f"  {col}: converted {updated} row(s).")

cursor.close()
conn.close()
print("\nMigration complete.")
