"""
Migration: add CopyrightBarBgColor and HeaderBannerBgColor to BusinessWebsite.
Run once from the Backend directory:  python migrate_website_columns.py
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
        "CopyrightBarBgColor",
        "ALTER TABLE BusinessWebsite ADD CopyrightBarBgColor NVARCHAR(20) NULL",
    ),
    (
        "HeaderBannerBgColor",
        "ALTER TABLE BusinessWebsite ADD HeaderBannerBgColor NVARCHAR(20) NULL",
    ),
]

for col_name, sql in migrations:
    # Check if the column already exists before trying to add it
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
        print(f"  — {col_name} already exists, skipping.")

cursor.close()
conn.close()
print("\nMigration complete.")
