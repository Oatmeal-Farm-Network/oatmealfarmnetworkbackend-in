from fastapi import APIRouter, HTTPException
from sqlalchemy import text
from database import get_db
from fastapi import Depends
from sqlalchemy.orm import Session
import time
from routers.translation import translate_list, translate_fields

router = APIRouter(prefix="/api/plant-knowledgebase", tags=["plant-knowledgebase"])

# ── Simple in-memory cache ────────────────────────────────────────
_cache = {}
CACHE_TTL = 300  # 5 minutes

def cache_get(key):
    entry = _cache.get(key)
    if entry and (time.time() - entry["ts"]) < CACHE_TTL:
        return entry["val"]
    return None

def cache_set(key, value):
    _cache[key] = {"val": value, "ts": time.time()}


@router.get("/counts")
def get_plant_counts(db: Session = Depends(get_db)):
    cached = cache_get("counts")
    if cached:
        return cached
    try:
        sql = text("""
            SELECT PT.PlantType, COUNT(PV.PlantVarietyID) AS VarietyCount
            FROM PlantVariety PV
            JOIN Plant P ON PV.PlantID = P.PlantID
            JOIN PlantTypeLookup PT ON P.PlantTypeID = PT.PlantTypeID
            WHERE PT.Edible = 'True'
            GROUP BY PT.PlantType
            ORDER BY PT.PlantType
        """)
        rows = db.execute(sql).fetchall()
        counts = {}
        total = 0
        for row in rows:
            counts[row.PlantType] = row.VarietyCount
            total += row.VarietyCount
        result = {"counts": counts, "total": total}
        cache_set("counts", result)
        return result
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/plants")
def get_plants(plant_type: str = None, lang: str = "en", db: Session = Depends(get_db)):
    cache_key = "plants_" + (plant_type or "all")
    cached = cache_get(cache_key)
    if cached:
        return translate_list(cached, ["plant_description"], lang, db)
    try:
        if plant_type:
            sql = text("""
                SELECT P.PlantID, P.PlantName, P.PlantDescription, P.PlantImage,
                       PT.PlantType, COUNT(PV.PlantVarietyID) AS VarietyCount
                FROM Plant P
                JOIN PlantTypeLookup PT ON P.PlantTypeID = PT.PlantTypeID
                LEFT JOIN PlantVariety PV ON PV.PlantID = P.PlantID AND PV.GrownForFood = 'True'
                WHERE PT.Edible = 'True' AND PT.PlantType = :plant_type
                GROUP BY P.PlantID, P.PlantName, P.PlantDescription, P.PlantImage, PT.PlantType
                ORDER BY P.PlantName
            """)
            rows = db.execute(sql, {"plant_type": plant_type}).fetchall()
        else:
            sql = text("""
                SELECT P.PlantID, P.PlantName, P.PlantDescription, P.PlantImage,
                       PT.PlantType, COUNT(PV.PlantVarietyID) AS VarietyCount
                FROM Plant P
                JOIN PlantTypeLookup PT ON P.PlantTypeID = PT.PlantTypeID
                LEFT JOIN PlantVariety PV ON PV.PlantID = P.PlantID AND PV.GrownForFood = 'True'
                WHERE PT.Edible = 'True'
                GROUP BY P.PlantID, P.PlantName, P.PlantDescription, P.PlantImage, PT.PlantType
                ORDER BY PT.PlantType, P.PlantName
            """)
            rows = db.execute(sql).fetchall()

        result = [
            {
                "plant_id": row.PlantID,
                "plant_name": row.PlantName,
                "plant_description": row.PlantDescription,
                "plant_image": row.PlantImage,
                "plant_type": row.PlantType,
                "variety_count": row.VarietyCount,
            }
            for row in rows
        ]
        cache_set(cache_key, result)
        return translate_list(result, ["plant_description"], lang, db)
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/varietals/{plant_id}")
def get_varietals(plant_id: int, lang: str = "en", db: Session = Depends(get_db)):
    cache_key = "varietals_" + str(plant_id)
    cached = cache_get(cache_key)
    if cached:
        result = dict(cached)
        result["varietals"] = translate_list(result["varietals"], ["plant_variety_description"], lang, db)
        return translate_fields(result, ["plant_description"], lang, db)
    try:
        plant_row = db.execute(
            text("SELECT PlantName, PlantDescription FROM Plant WHERE PlantID = :pid"),
            {"pid": plant_id}
        ).fetchone()

        if not plant_row:
            raise HTTPException(status_code=404, detail="Plant not found")

        sql = text("""
            SELECT PV.PlantVarietyID, PV.PlantVarietyName, PV.PlantVarietyDescription,
                   ST.SoilTexture, PH.PHRange, OM.OrganicMatterContent,
                   SL.SalinityLevel, PHZ.Zone,
                   H.Classification AS HumidityClassification,
                   PV.WaterRequirementMin, PV.WaterRequirementMax,
                   NL.Nutrient AS PrimaryNutrient
            FROM PlantVariety PV
            LEFT JOIN SoilTextureLookup ST ON PV.SoilTextureID = ST.SoilTextureID
            LEFT JOIN PHRangeLookup PH ON PV.PHRangeID = PH.PHRangeID
            LEFT JOIN OrganicMatterLookup OM ON PV.OrganicMatterID = OM.OrganicMatterID
            LEFT JOIN SalinityLookup SL ON PV.SalinityLevelID = SL.SalinityLevelID
            LEFT JOIN PlantHardinessZoneLookup PHZ ON PV.ZoneID = PHZ.ZoneID
            LEFT JOIN HumidityLookup H ON PV.HumidityID = H.HumidityID
            LEFT JOIN NutrientLookup NL ON PV.PlantNutrientID = NL.NutrientID
            WHERE PV.PlantID = :plant_id
            ORDER BY PV.PlantVarietyName
        """)
        rows = db.execute(sql, {"plant_id": plant_id}).fetchall()

        result = {
            "plant_name": plant_row.PlantName,
            "plant_description": plant_row.PlantDescription,
            "varietals": [
                {
                    "plant_variety_id": r.PlantVarietyID,
                    "plant_variety_name": r.PlantVarietyName,
                    "plant_variety_description": r.PlantVarietyDescription,
                    "soil_texture": r.SoilTexture,
                    "ph_range": r.PHRange,
                    "organic_matter": r.OrganicMatterContent,
                    "salinity_level": r.SalinityLevel,
                    "zone": r.Zone,
                    "humidity": r.HumidityClassification,
                    "water_min": r.WaterRequirementMin,
                    "water_max": r.WaterRequirementMax,
                    "primary_nutrient": r.PrimaryNutrient,
                }
                for r in rows
            ]
        }
        cache_set(cache_key, result)
        result = dict(result)
        result["varietals"] = translate_list(result["varietals"], ["plant_variety_description"], lang, db)
        return translate_fields(result, ["plant_description"], lang, db)
    except HTTPException:
        raise
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/varietal-detail/{variety_id}")
def get_varietal_detail(variety_id: int, lang: str = "en", db: Session = Depends(get_db)):
    cache_key = "varietal_detail_" + str(variety_id)
    cached = cache_get(cache_key)
    if cached:
        return translate_fields(cached, ["plant_variety_description"], lang, db)
    try:
        sql = text("""
            SELECT PV.PlantVarietyID, PV.PlantVarietyName, PV.PlantVarietyDescription,
                   PV.PlantVarietyImage, P.PlantName,
                   ST.SoilTexture, ST.Description AS SoilTextureDescription,
                   PH.PHRange, PH.Description AS PHRangeDescription,
                   OM.OrganicMatterContent, OM.Description AS OMDescription,
                   SL.SalinityLevel, SL.Classification AS SalinityClassification,
                   SL.Description AS SalinityDescription, SL.ImpactOnPlants AS SalinityImpact,
                   PHZ.Zone, PHZ.TemperatureStartRange, PHZ.TemperatureEndRange,
                   H.Classification AS HumidityClassification,
                   H.Description AS HumidityDescription, H.ImpactOnPlants AS HumidityImpact,
                   PV.WaterRequirementMin, PV.WaterRequirementMax,
                   NL.Nutrient AS PrimaryNutrientName, NL.Description AS PrimaryNutrientDescription
            FROM PlantVariety PV
            LEFT JOIN Plant P ON PV.PlantID = P.PlantID
            LEFT JOIN SoilTextureLookup ST ON PV.SoilTextureID = ST.SoilTextureID
            LEFT JOIN PHRangeLookup PH ON PV.PHRangeID = PH.PHRangeID
            LEFT JOIN OrganicMatterLookup OM ON PV.OrganicMatterID = OM.OrganicMatterID
            LEFT JOIN SalinityLookup SL ON PV.SalinityLevelID = SL.SalinityLevelID
            LEFT JOIN PlantHardinessZoneLookup PHZ ON PV.ZoneID = PHZ.ZoneID
            LEFT JOIN HumidityLookup H ON PV.HumidityID = H.HumidityID
            LEFT JOIN NutrientLookup NL ON PV.PlantNutrientID = NL.NutrientID
            WHERE PV.PlantVarietyID = :vid
        """)
        row = db.execute(sql, {"vid": variety_id}).fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Varietal not found")

        nutrients_sql = text("""
            SELECT NL.Nutrient AS NutrientName, NL.Description,
                   PNT.NutrientLow, PNT.NutrientID AS NutrientHigh
            FROM PlantNutrient PNT
            JOIN NutrientLookup NL ON PNT.NutrientID = NL.NutrientID
            WHERE PNT.PlantVarietyID = :vid
            ORDER BY NL.Nutrient
        """)
        nutrient_rows = db.execute(nutrients_sql, {"vid": variety_id}).fetchall()

        result = {
            "plant_variety_id": row.PlantVarietyID,
            "plant_variety_name": row.PlantVarietyName,
            "plant_variety_description": row.PlantVarietyDescription,
            "plant_variety_image": row.PlantVarietyImage,
            "plant_name": row.PlantName,
            "soil_texture": row.SoilTexture,
            "soil_texture_description": row.SoilTextureDescription,
            "ph_range": row.PHRange,
            "ph_range_description": row.PHRangeDescription,
            "organic_matter": row.OrganicMatterContent,
            "organic_matter_description": row.OMDescription,
            "salinity_level": row.SalinityLevel,
            "salinity_classification": row.SalinityClassification,
            "salinity_description": row.SalinityDescription,
            "salinity_impact": row.SalinityImpact,
            "zone": row.Zone,
            "temp_start": row.TemperatureStartRange,
            "temp_end": row.TemperatureEndRange,
            "humidity_classification": row.HumidityClassification,
            "humidity_description": row.HumidityDescription,
            "humidity_impact": row.HumidityImpact,
            "water_min": row.WaterRequirementMin,
            "water_max": row.WaterRequirementMax,
            "primary_nutrient_name": row.PrimaryNutrientName,
            "primary_nutrient_description": row.PrimaryNutrientDescription,
            "nutrients": [
                {
                    "nutrient_name": n.NutrientName,
                    "description": n.Description,
                    "nutrient_low": n.NutrientLow,
                    "nutrient_high": n.NutrientHigh,
                }
                for n in nutrient_rows
            ]
        }
        cache_set(cache_key, result)
        return translate_fields(result, ["plant_variety_description"], lang, db)
    except HTTPException:
        raise
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))