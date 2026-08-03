"""
One-off import: parse public/images/sfProducts.txt (MySQL-table dump format,
51 pipe-delimited columns with wrapped-text continuation rows) and load into
the SFProducts / productsizes / productcolor tables for BusinessID = 14
(Alpacas at Lone Ranch).

Run from Backend/ with the venv active:
    ./venv/Scripts/python scripts/import_sfproducts.py
"""
from __future__ import annotations

import os
import re
import sys
from datetime import datetime
from decimal import Decimal, InvalidOperation

# make Backend/ importable (so `database` resolves when run from scripts/)
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import text  # noqa: E402
from database import engine  # noqa: E402


SOURCE_PATH = (
    r"f:/Oatmeal AI/OatmealFarmNetwork Repo/OatmealFarmNetwork"
    r"/public/images/sfProducts.txt"
)
BUSINESS_ID = 14
PEOPLE_ID = 39  # Alpacas at Lone Ranch — Contact1PeopleID

COL_NAMES = [
    "prodCategoryId", "prodSubCategoryId", "prodManufacturerId", "prodVendorId",
    "prodName", "prodNamePlural", "prodShortDescription", "prodDescription", "prodMessage",
    "prodImageSmallPath", "prodImageLargePath", "prodLink",
    "prodPrice", "prodWeight", "prodShip", "prodShipIsActive", "prodCountryTaxIsActive",
    "prodStateTaxIsActive", "prodEnabledIsActive", "prodAttrNum", "prodSaleIsActive",
    "prodSalePrice", "prodDateAdded", "prodDateModified", "prodLength", "prodWidth", "prodHeight",
    "prodFileName", "ProdQuantityAvailable", "ProdSize", "ProdDimensions",
    "ProdSize1", "ProdSize2", "ProdSize3", "ProdSize4", "ProdSize5",
    "ProdSize6", "ProdSize7", "ProdSize8", "ProdSize9", "ProdSize10",
    "Color1", "Color2", "Color3", "Color4", "Color5",
    "Color6", "Color7", "Color8", "Color9", "Color10",
]


def parse_dump(path: str) -> list[dict]:
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    records: list[dict] = []
    cur: dict | None = None
    for line in lines:
        if not line.startswith("|"):
            continue
        parts = [p.strip() for p in line.split("|")[1:-1]]
        if not parts:
            continue
        if parts[0] == "prodCategoryId":
            continue
        if parts[0]:
            if cur is not None:
                records.append(cur)
            cur = {COL_NAMES[i]: parts[i] for i in range(len(COL_NAMES))}
        else:
            if cur is None:
                continue
            for i, val in enumerate(parts):
                if val:
                    if cur[COL_NAMES[i]]:
                        cur[COL_NAMES[i]] += " " + val
                    else:
                        cur[COL_NAMES[i]] = val
    if cur is not None:
        records.append(cur)
    return records


def to_decimal(s: str | None) -> Decimal | None:
    if not s:
        return None
    cleaned = re.sub(r"[^0-9.\-]", "", s)
    if cleaned in ("", "-", "."):
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def to_int(s: str | None) -> int | None:
    d = to_decimal(s)
    return int(d) if d is not None else None


def to_bit(s: str | None) -> int:
    d = to_int(s)
    return 1 if d and d > 0 else 0


def to_datetime(s: str | None) -> datetime | None:
    if not s:
        return None
    for fmt in (
        "%m/%d/%Y %I:%M:%S %p",
        "%m/%d/%Y %H:%M:%S",
        "%m/%d/%Y",
    ):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def main() -> None:
    records = parse_dump(SOURCE_PATH)
    print(f"Parsed {len(records)} records from dump")

    inserted = 0
    sizes_inserted = 0
    colors_inserted = 0
    skipped = 0

    with engine.begin() as conn:
        # safety: verify target business has zero rows before inserting
        existing = conn.execute(
            text("SELECT COUNT(*) FROM SFProducts WHERE BusinessID = :bid"),
            {"bid": BUSINESS_ID},
        ).scalar()
        if existing:
            print(f"ABORT: BusinessID={BUSINESS_ID} already has {existing} SFProducts rows.")
            return

        # ProdID is NOT IDENTITY on this table — supply explicit values starting
        # after the current MAX across all businesses.
        max_prod = conn.execute(text("SELECT ISNULL(MAX(ProdID), 0) FROM SFProducts")).scalar()
        next_prod_id = int(max_prod) + 1

        for r in records:
            name = (r.get("prodName") or "").strip()
            if not name:
                skipped += 1
                continue

            params = {
                "ProdID": next_prod_id,
                "BusinessID": BUSINESS_ID,
                "PeopleID": PEOPLE_ID,
                "prodName": name[:200],
                "prodShortDescription": (r.get("prodShortDescription") or None),
                "prodDescription": (r.get("prodDescription") or None),
                "prodMessage": (r.get("prodMessage") or None),
                "prodPrice": to_decimal(r.get("prodPrice")) or Decimal("0"),
                "prodSalePrice": to_decimal(r.get("prodSalePrice")),
                "prodSaleIsActive": to_bit(r.get("prodSaleIsActive")),
                "prodWeight": to_decimal(r.get("prodWeight")),
                "prodShip": to_bit(r.get("prodShip")),
                "prodShipIsActive": to_bit(r.get("prodShipIsActive")),
                "prodCountryTaxIsActive": to_bit(r.get("prodCountryTaxIsActive")),
                "prodStateTaxIsActive": to_bit(r.get("prodStateTaxIsActive")),
                "prodEnabledIsActive": 1,
                "prodLength": to_decimal(r.get("prodLength")),
                "prodWidth": to_decimal(r.get("prodWidth")),
                "prodHeight": to_decimal(r.get("prodHeight")),
                "ProdDimensions": (r.get("ProdDimensions") or None),
                "ProdQuantityAvailable": to_int(r.get("ProdQuantityAvailable")) or 0,
                "prodDateAdded": to_datetime(r.get("prodDateAdded")) or datetime.utcnow(),
                "prodDateModified": to_datetime(r.get("prodDateModified")),
                "Publishproduct": 1,
                "ProdForSale": 1,
            }
            # ProdSize1-10
            for i in range(1, 11):
                params[f"ProdSize{i}"] = r.get(f"ProdSize{i}") or None
            # Color1-10
            for i in range(1, 11):
                params[f"Color{i}"] = r.get(f"Color{i}") or None

            conn.execute(
                text("""
                    INSERT INTO SFProducts (
                        ProdID, BusinessID, PeopleID,
                        prodName, prodShortDescription, prodDescription, prodMessage,
                        prodPrice, prodSalePrice, prodSaleIsActive,
                        prodWeight, prodShip, prodShipIsActive,
                        prodCountryTaxIsActive, prodStateTaxIsActive, prodEnabledIsActive,
                        prodLength, prodWidth, prodHeight, ProdDimensions,
                        ProdQuantityAvailable, prodDateAdded, prodDateModified,
                        ProdSize1, ProdSize2, ProdSize3, ProdSize4, ProdSize5,
                        ProdSize6, ProdSize7, ProdSize8, ProdSize9, ProdSize10,
                        Color1, Color2, Color3, Color4, Color5,
                        Color6, Color7, Color8, Color9, Color10,
                        Publishproduct, ProdForSale
                    ) VALUES (
                        :ProdID, :BusinessID, :PeopleID,
                        :prodName, :prodShortDescription, :prodDescription, :prodMessage,
                        :prodPrice, :prodSalePrice, :prodSaleIsActive,
                        :prodWeight, :prodShip, :prodShipIsActive,
                        :prodCountryTaxIsActive, :prodStateTaxIsActive, :prodEnabledIsActive,
                        :prodLength, :prodWidth, :prodHeight, :ProdDimensions,
                        :ProdQuantityAvailable, :prodDateAdded, :prodDateModified,
                        :ProdSize1, :ProdSize2, :ProdSize3, :ProdSize4, :ProdSize5,
                        :ProdSize6, :ProdSize7, :ProdSize8, :ProdSize9, :ProdSize10,
                        :Color1, :Color2, :Color3, :Color4, :Color5,
                        :Color6, :Color7, :Color8, :Color9, :Color10,
                        :Publishproduct, :ProdForSale
                    )
                """),
                params,
            )
            prod_id = next_prod_id
            next_prod_id += 1
            inserted += 1

            for i in range(1, 11):
                sz = r.get(f"ProdSize{i}")
                if sz:
                    conn.execute(
                        text("""
                            INSERT INTO productsizes (PeopleID, ProductID, Size, ExtraCost)
                            VALUES (:pid, :prod_id, :size, 0)
                        """),
                        {"pid": PEOPLE_ID, "prod_id": prod_id, "size": sz},
                    )
                    sizes_inserted += 1

            for i in range(1, 11):
                cl = r.get(f"Color{i}")
                if cl:
                    conn.execute(
                        text("""
                            INSERT INTO productcolor (PeopleID, ProductID, Color)
                            VALUES (:pid, :prod_id, :color)
                        """),
                        {"pid": PEOPLE_ID, "prod_id": prod_id, "color": cl},
                    )
                    colors_inserted += 1

    print(f"Inserted products: {inserted}")
    print(f"Inserted sizes:    {sizes_inserted}")
    print(f"Inserted colors:   {colors_inserted}")
    print(f"Skipped (no name): {skipped}")


if __name__ == "__main__":
    main()
