"""
One-shot backfill: compute Field.FieldSizeHectares from Field.BoundaryGeoJSON
for every field that has a drawn boundary. Existing non-null values are
overwritten when --force is passed; otherwise only NULL/0 rows are filled.

Usage (run from inside Backend/oatmealfarmnetworkbackend):
    python scripts/backfill_field_size_from_boundary.py            # fill blanks
    python scripts/backfill_field_size_from_boundary.py --force    # recompute all
    python scripts/backfill_field_size_from_boundary.py --dry-run  # preview only
"""
import argparse
import os
import sys

# Allow running as `python scripts/...` from the package root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import SessionLocal  # type: ignore
import models                      # type: ignore
from geo_utils import polygon_area_hectares  # type: ignore


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force",   action="store_true", help="Overwrite existing sizes")
    ap.add_argument("--dry-run", action="store_true", help="Print changes without saving")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        rows = (
            db.query(models.Field)
            .filter(models.Field.BoundaryGeoJSON.isnot(None))
            .filter(models.Field.DeletedAt.is_(None))
            .all()
        )
        print(f"Inspecting {len(rows)} field(s) with a drawn boundary.")

        updated = skipped = invalid = 0
        for f in rows:
            ha = polygon_area_hectares(f.BoundaryGeoJSON)
            if ha is None:
                invalid += 1
                continue
            current = float(f.FieldSizeHectares) if f.FieldSizeHectares is not None else None
            if current and not args.force:
                skipped += 1
                continue
            print(f"  Field #{f.FieldID:>5} {f.Name!r:35s} {current!s:>8} ha → {ha} ha")
            if not args.dry_run:
                f.FieldSizeHectares = ha
                updated += 1

        if not args.dry_run:
            db.commit()
        print(f"\nDone. updated={updated} skipped={skipped} invalid_boundary={invalid}"
              + (" (dry-run)" if args.dry_run else ""))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
