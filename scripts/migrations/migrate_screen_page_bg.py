"""
Migration: add ScreenBackgroundColor and PageBackgroundColor to BusinessWebsite.
- ScreenBackgroundColor = outer viewport background (seeded from existing BgColor)
- PageBackgroundColor   = inner page content background (nullable, no default)

Run once from the Backend directory:  python migrate_screen_page_bg.py
"""
import os
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

migrations = [
    (
        "ScreenBackgroundColor",
        "ALTER TABLE BusinessWebsite ADD ScreenBackgroundColor NVARCHAR(20) NULL",
    ),
    (
        "PageBackgroundColor",
        "ALTER TABLE BusinessWebsite ADD PageBackgroundColor NVARCHAR(20) NULL",
    ),
]

for col_name, sql in migrations:
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
        cursor.execute(sql)
        conn.commit()
        print(f"  OK: {col_name} added.")
    else:
        print(f"  - {col_name} already exists, skipping.")

# Seed ScreenBackgroundColor from the existing BgColor for rows that don't have one yet.
print("Seeding ScreenBackgroundColor from BgColor where NULL...")
cursor.execute(
    """
    UPDATE BusinessWebsite
    SET ScreenBackgroundColor = BgColor
    WHERE ScreenBackgroundColor IS NULL
    """
)
conn.commit()
print(f"  OK: seeded {cursor.rowcount} row(s).")

cursor.close()
conn.close()
print("\nMigration complete.")
