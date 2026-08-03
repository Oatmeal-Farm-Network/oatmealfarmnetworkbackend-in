from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session
from typing import Optional, List
from database import get_db

router = APIRouter(prefix="/api/precision-ag/crop-summary", tags=["crop-summary"])


# ── SQL building helpers ────────────────────────────────────────────────
# All dashboard data is driven by PlantVariety rows. The filter set narrows
# the scope; the visuals are aggregates over that scope.

def _apply_filters(
    clauses: List[str],
    params: dict,
    *,
    field: Optional[str],
    crop: Optional[str],
    plant_type: Optional[str],
    soil_texture: Optional[str],
    zone: Optional[str],
    ph_range: Optional[str],
):
    if field:
        clauses.append("PV.PlantVarietyName = :field")
        params["field"] = field
    if crop:
        clauses.append("P.PlantName = :crop")
        params["crop"] = crop
    if plant_type:
        clauses.append("PT.PlantType = :plant_type")
        params["plant_type"] = plant_type
    if soil_texture:
        clauses.append("ST.SoilTexture = :soil_texture")
        params["soil_texture"] = soil_texture
    if zone:
        clauses.append("PHZ.Zone = :zone")
        params["zone"] = zone
    if ph_range:
        clauses.append("PH.PHRange = :ph_range")
        params["ph_range"] = ph_range


def _base_join() -> str:
    return """
        FROM PlantVariety PV
        LEFT JOIN Plant P ON PV.PlantID = P.PlantID
        LEFT JOIN PlantTypeLookup PT ON P.PlantTypeID = PT.PlantTypeID
        LEFT JOIN SoilTextureLookup ST ON PV.SoilTextureID = ST.SoilTextureID
        LEFT JOIN PHRangeLookup PH ON PV.PHRangeID = PH.PHRangeID
        LEFT JOIN OrganicMatterLookup OM ON PV.OrganicMatterID = OM.OrganicMatterID
        LEFT JOIN SalinityLookup SL ON PV.SalinityLevelID = SL.SalinityLevelID
        LEFT JOIN PlantHardinessZoneLookup PHZ ON PV.ZoneID = PHZ.ZoneID
        LEFT JOIN HumidityLookup H ON PV.HumidityID = H.HumidityID
    """


# ── Endpoints ────────────────────────────────────────────────────────────

@router.get("/options")
def filter_options(
    db: Session = Depends(get_db),
    crop: Optional[str] = Query(None),
):
    """Distinct values for each slicer.

    When ``crop`` is provided, the ``fields`` list (varieties) is scoped to
    varieties of that crop only. ``cropPlantTypes`` is a lookup mapping
    every crop name to its PlantType, so the UI can auto-fill Plant Type.
    """
    try:
        def _list(sql_text: str, col: str, params: dict = None) -> List[str]:
            rows = db.execute(text(sql_text), params or {}).fetchall()
            return [getattr(r, col) for r in rows if getattr(r, col) is not None]

        if crop:
            fields = _list(
                "SELECT DISTINCT PV.PlantVarietyName FROM PlantVariety PV "
                "LEFT JOIN Plant P ON PV.PlantID = P.PlantID "
                "WHERE PV.PlantVarietyName IS NOT NULL AND P.PlantName = :crop "
                "ORDER BY PV.PlantVarietyName",
                "PlantVarietyName",
                {"crop": crop},
            )
        else:
            fields = _list(
                "SELECT DISTINCT PlantVarietyName FROM PlantVariety "
                "WHERE PlantVarietyName IS NOT NULL ORDER BY PlantVarietyName",
                "PlantVarietyName",
            )

        crop_plant_types_rows = db.execute(text(
            "SELECT P.PlantName, PT.PlantType "
            "FROM Plant P LEFT JOIN PlantTypeLookup PT ON P.PlantTypeID = PT.PlantTypeID "
            "WHERE P.PlantName IS NOT NULL"
        )).fetchall()
        crop_plant_types = {
            r.PlantName: r.PlantType for r in crop_plant_types_rows if r.PlantType
        }

        return {
            "fields": fields,
            "crops": _list(
                "SELECT DISTINCT PlantName FROM Plant WHERE PlantName IS NOT NULL ORDER BY PlantName",
                "PlantName",
            ),
            "plantTypes": _list(
                "SELECT DISTINCT PlantType FROM PlantTypeLookup "
                "WHERE PlantType IS NOT NULL ORDER BY PlantType",
                "PlantType",
            ),
            "soilTextures": _list(
                "SELECT DISTINCT SoilTexture FROM SoilTextureLookup "
                "WHERE SoilTexture IS NOT NULL ORDER BY SoilTexture",
                "SoilTexture",
            ),
            "zones": _list(
                "SELECT DISTINCT Zone FROM PlantHardinessZoneLookup "
                "WHERE Zone IS NOT NULL ORDER BY Zone",
                "Zone",
            ),
            "phRanges": _list(
                "SELECT DISTINCT PHRange FROM PHRangeLookup "
                "WHERE PHRange IS NOT NULL ORDER BY PHRange",
                "PHRange",
            ),
            "cropPlantTypes": crop_plant_types,
        }
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/my-fields")
def my_fields(business_id: int, db: Session = Depends(get_db)):
    """Return the user's Field rows enriched with site conditions
    (soil texture, pH range) looked up via Field.SoilID → SoilType, so the
    Crop Analysis page can auto-fill filters when the user picks a field.

    Zone stays null for now — derivation from lat/long needs a USDA zone
    polygon lookup we don't ship yet.
    """
    try:
        rows = db.execute(text("""
            SELECT F.FieldID, F.Name, F.Address, F.CropType,
                   F.Latitude, F.Longitude, F.FieldSizeHectares,
                   ST.SoilTexture, ST.SoilpH
            FROM Field F
            LEFT JOIN SoilType ST ON F.SoilID = ST.SoilTypeId
            WHERE F.BusinessID = :bid AND F.DeletedAt IS NULL
            ORDER BY F.Name
        """), {"bid": business_id}).fetchall()

        ph_ranges = db.execute(text(
            "SELECT PHRange FROM PHRangeLookup ORDER BY PHRangeID"
        )).fetchall()
        ph_range_labels = [r.PHRange for r in ph_ranges]

        def bucket_ph(val) -> Optional[str]:
            if val is None:
                return None
            try:
                p = float(val)
            except (TypeError, ValueError):
                return None
            if p < 5.0:   return "< 5.0"
            if p <= 5.5:  return "5.1 - 5.5"
            if p <= 6.0:  return "5.6 - 6.0"
            if p <= 6.5:  return "6.1 - 6.5"
            if p <= 7.3:  return "6.6 - 7.3"
            if p <= 7.8:  return "7.4 - 7.8"
            if p <= 8.4:  return "7.9 - 8.4"
            if p <= 9.0:  return "8.5 - 9.0"
            return "> 9.0"

        result = []
        for r in rows:
            ph_label = bucket_ph(r.SoilpH)
            if ph_label and ph_label not in ph_range_labels:
                ph_label = None
            result.append({
                "fieldId":           r.FieldID,
                "name":              r.Name,
                "address":           r.Address,
                "cropType":          r.CropType,
                "latitude":          float(r.Latitude) if r.Latitude is not None else None,
                "longitude":         float(r.Longitude) if r.Longitude is not None else None,
                "fieldSizeHectares": float(r.FieldSizeHectares) if r.FieldSizeHectares is not None else None,
                "siteConditions": {
                    "soilTexture": r.SoilTexture,
                    "phRange":     ph_label,
                    "zone":        None,
                },
            })
        return result
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("")
def crop_summary(
    db: Session = Depends(get_db),
    field: Optional[str] = Query(None),
    crop: Optional[str] = Query(None),
    plantType: Optional[str] = Query(None),
    soilTexture: Optional[str] = Query(None),
    zone: Optional[str] = Query(None),
    phRange: Optional[str] = Query(None),
):
    """Returns the complete Crop Analysis Summary payload for the given filter set."""
    try:
        clauses: List[str] = []
        params: dict = {}
        _apply_filters(
            clauses, params,
            field=field, crop=crop, plant_type=plantType,
            soil_texture=soilTexture, zone=zone, ph_range=phRange,
        )
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        base = _base_join()

        # ── KPIs ───────────────────────────────────────────────────────
        kpi_sql = text(f"""
            SELECT
                COUNT(DISTINCT P.PlantID) AS TotalCrops,
                COUNT(DISTINCT PV.PlantVarietyID) AS TotalFieldOptions,
                AVG(CAST(PV.WaterRequirementMin AS FLOAT)) AS AvgWaterMin,
                AVG(CAST(PV.WaterRequirementMax AS FLOAT)) AS AvgWaterMax
            {base} {where}
        """)
        kpi_row = db.execute(kpi_sql, params).fetchone()

        nutrients_sql = text(f"""
            SELECT COUNT(DISTINCT PNT.NutrientID) AS UniqueNutrients
            {base}
            LEFT JOIN PlantNutrient PNT ON PNT.PlantVarietyID = PV.PlantVarietyID
            {where}
        """)
        nutrient_row = db.execute(nutrients_sql, params).fetchone()

        kpis = {
            "totalCrops": int(kpi_row.TotalCrops or 0),
            "totalFieldOptions": int(kpi_row.TotalFieldOptions or 0),
            "avgWaterMin": round(float(kpi_row.AvgWaterMin), 2) if kpi_row.AvgWaterMin is not None else None,
            "avgWaterMax": round(float(kpi_row.AvgWaterMax), 2) if kpi_row.AvgWaterMax is not None else None,
            "uniqueNutrients": int(nutrient_row.UniqueNutrients or 0),
        }

        # ── Bar/column charts ──────────────────────────────────────────
        def _group_count(group_col: str, alias: str):
            sql = text(f"""
                SELECT {group_col} AS GroupName, COUNT(DISTINCT PV.PlantVarietyID) AS Cnt
                {base} {where}
                {"AND" if where else "WHERE"} {group_col} IS NOT NULL
                GROUP BY {group_col}
                ORDER BY Cnt DESC
            """)
            rows = db.execute(sql, params).fetchall()
            return [{"name": r.GroupName, "value": int(r.Cnt)} for r in rows]

        fields_by_plant_type = _group_count("PT.PlantType", "PlantType")
        fields_by_soil = _group_count("ST.SoilTexture", "SoilTexture")
        fields_by_salinity = _group_count("SL.Classification", "SalinityClassification")
        fields_by_humidity = _group_count("H.Classification", "HumidityClassification")

        # ── Pivot: field × nutrient ────────────────────────────────────
        matrix_sql = text(f"""
            SELECT PV.PlantVarietyName AS FieldName, NL.Nutrient AS NutrientName
            {base}
            JOIN PlantNutrient PNT ON PNT.PlantVarietyID = PV.PlantVarietyID
            JOIN NutrientLookup NL ON PNT.NutrientID = NL.NutrientID
            {where}
            {"AND" if where else "WHERE"} PV.PlantVarietyName IS NOT NULL
            ORDER BY PV.PlantVarietyName, NL.Nutrient
        """)
        pair_rows = db.execute(matrix_sql, params).fetchall()
        nutrients_set = []
        seen_n = set()
        rows_map: dict = {}
        for r in pair_rows:
            if r.NutrientName not in seen_n:
                seen_n.add(r.NutrientName)
                nutrients_set.append(r.NutrientName)
            rows_map.setdefault(r.FieldName, set()).add(r.NutrientName)
        matrix_rows = [
            {
                "field": fname,
                "has": {n: (1 if n in nset else 0) for n in nutrients_set},
            }
            for fname, nset in sorted(rows_map.items())
        ]

        # ── Detail table ──────────────────────────────────────────────
        detail_sql = text(f"""
            SELECT TOP 200
                P.PlantName, P.PlantDescription,
                PV.PlantVarietyName, PV.PlantVarietyDescription,
                PV.WaterRequirementMin, PV.WaterRequirementMax,
                PT.PlantType, ST.SoilTexture, PH.PHRange,
                OM.OrganicMatterContent,
                H.Classification AS HumidityClass,
                SL.Classification AS SalinityClass,
                PHZ.Zone
            {base} {where}
            ORDER BY P.PlantName, PV.PlantVarietyName
        """)
        detail_rows = db.execute(detail_sql, params).fetchall()
        crop_summary_rows = [
            {
                "PlantName": r.PlantName,
                "PlantDescription": r.PlantDescription,
                "PlantVarietyName": r.PlantVarietyName,
                "PlantVarietyDescription": r.PlantVarietyDescription,
                "WaterRequirementMin": float(r.WaterRequirementMin) if r.WaterRequirementMin is not None else None,
                "WaterRequirementMax": float(r.WaterRequirementMax) if r.WaterRequirementMax is not None else None,
                "PlantType": r.PlantType,
                "SoilTexture": r.SoilTexture,
                "PHRange": r.PHRange,
                "OrganicMatterContent": r.OrganicMatterContent,
                "HumidityClassification": r.HumidityClass,
                "SalinityClassification": r.SalinityClass,
                "Zone": r.Zone,
            }
            for r in detail_rows
        ]

        # ── Cards ──────────────────────────────────────────────────────
        selection_bits = []
        if field: selection_bits.append(f"Field: {field}")
        if crop: selection_bits.append(f"Crop: {crop}")
        if plantType: selection_bits.append(f"Type: {plantType}")
        if soilTexture: selection_bits.append(f"Soil: {soilTexture}")
        if zone: selection_bits.append(f"Zone: {zone}")
        if phRange: selection_bits.append(f"pH: {phRange}")
        current_selection = " • ".join(selection_bits) if selection_bits else "All fields"

        wr_min = kpis["avgWaterMin"]
        wr_max = kpis["avgWaterMax"]
        if wr_min is not None and wr_max is not None:
            water_range = f"{wr_min} – {wr_max} in/week"
        else:
            water_range = "—"

        return {
            "kpis": kpis,
            "fieldsByPlantType": fields_by_plant_type,
            "fieldsBySoilTexture": fields_by_soil,
            "fieldsBySalinity": fields_by_salinity,
            "fieldsByHumidity": fields_by_humidity,
            "nutrientMatrix": {
                "nutrients": nutrients_set,
                "rows": matrix_rows,
            },
            "cropSummary": crop_summary_rows,
            "currentSelection": current_selection,
            "waterRange": water_range,
        }
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
