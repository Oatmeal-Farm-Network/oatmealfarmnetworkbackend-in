"""
Migration: add site-wide image styling columns to BusinessWebsite.
    ImageBorderRadius   INT            DEFAULT 0    (percent, 0-50)
    ImageShadowEnabled  BIT            DEFAULT 0
    ImageShadowColor    NVARCHAR(40)   DEFAULT 'rgba(0,0,0,0.35)'
    ImageShadowDistance INT            DEFAULT 4    (px)
    ImageShadowBlur     INT            DEFAULT 8    (px)
    ImageShadowAngle    INT            DEFAULT 135  (degrees)

Run once from Backend/oatmealfarmnetworkbackend:  python migrate_image_styling.py
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

columns = [
    ("ImageBorderRadius",   "INT NOT NULL CONSTRAINT DF_BusinessWebsite_ImageBorderRadius DEFAULT 0"),
    ("ImageShadowEnabled",  "BIT NOT NULL CONSTRAINT DF_BusinessWebsite_ImageShadowEnabled DEFAULT 0"),
    ("ImageShadowColor",    "NVARCHAR(40) NOT NULL CONSTRAINT DF_BusinessWebsite_ImageShadowColor DEFAULT 'rgba(0,0,0,0.35)'"),
    ("ImageShadowDistance", "INT NOT NULL CONSTRAINT DF_BusinessWebsite_ImageShadowDistance DEFAULT 4"),
    ("ImageShadowBlur",     "INT NOT NULL CONSTRAINT DF_BusinessWebsite_ImageShadowBlur DEFAULT 8"),
    ("ImageShadowAngle",    "INT NOT NULL CONSTRAINT DF_BusinessWebsite_ImageShadowAngle DEFAULT 135"),
]

for col_name, col_def in columns:
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
        cursor.execute(f"ALTER TABLE BusinessWebsite ADD {col_name} {col_def}")
        conn.commit()
        print(f"  OK: {col_name} added.")
    else:
        print(f"  - {col_name} already exists, skipping.")

cursor.close()
conn.close()
print("\nMigration complete.")
