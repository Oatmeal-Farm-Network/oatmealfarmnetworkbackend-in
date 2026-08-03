"""
ESG Reports — automated, audit-ready proof of sustainable practices.

Aggregates data we already track (cold-chain breaches, fertilizer/input use,
sourcing transparency, residue testing) with manual ESG metrics the business
records (renewable energy %, fair-wage premiums paid, EU regulation X
compliance, etc.) into a single signed snapshot suitable for auditor review.

Snapshots can be downloaded as JSON, printable HTML, or PDF.

Two adjacent surfaces feed in:
  - The aggregator's existing OFNAggregator* tables (logistics breaches,
    inputs, purchases, farm certifications)
  - A new manual-metrics table (OFNESGMetric) where the business records
    everything we don't track automatically
  - A sensor webhook stub (OFNESGSensorReading) — landing pad for future
    IoT integration; not wired to any device today

Schema:
  OFNESGMetric         Per-business manual metrics with category, value, period, evidence URL
  OFNESGReport         Saved snapshot — period bounds, full metrics JSON, signature
  OFNESGSensorReading  Raw sensor readings (water flow / fertilizer dispenser / cooler temp / etc.)
                       Posted by IoT devices to a webhook; aggregated into reports.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Optional
from datetime import datetime, date, timedelta
import json
from database import get_db, SessionLocal

router = APIRouter()


def ensure_tables(db: Session):
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='OFNESGMetric')
        CREATE TABLE OFNESGMetric (
            MetricID       INT IDENTITY(1,1) PRIMARY KEY,
            BusinessID     INT NOT NULL,
            Category       NVARCHAR(40) DEFAULT 'environmental', -- environmental / social / governance
            MetricKey      NVARCHAR(120) NOT NULL,               -- e.g. "renewable_energy_pct" / "fair_wage_premium_paid"
            Label          NVARCHAR(255) NOT NULL,
            Value          NVARCHAR(255),                         -- string so we can hold "85%", "$12,400", "ISO 14001 certified"
            NumericValue   DECIMAL(18,4),                         -- optional numeric for charting/aggregation
            Unit           NVARCHAR(60),
            PeriodStart    DATE,
            PeriodEnd      DATE,
            EvidenceURL    NVARCHAR(500),                         -- link to certificate / receipt / audit doc
            Notes          NVARCHAR(MAX),
            CreatedDate    DATETIME DEFAULT GETDATE(),
            UpdatedDate    DATETIME DEFAULT GETDATE()
        )
    """))
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='OFNESGReport')
        CREATE TABLE OFNESGReport (
            ReportID       INT IDENTITY(1,1) PRIMARY KEY,
            BusinessID     INT NOT NULL,
            Title          NVARCHAR(255),
            PeriodStart    DATE NOT NULL,
            PeriodEnd      DATE NOT NULL,
            GeneratedDate  DATETIME DEFAULT GETDATE(),
            GeneratedByID  INT,                                   -- PeopleID who clicked Generate
            Signatory      NVARCHAR(255),                         -- person attesting to accuracy
            SignatureDate  DATE,
            ReportJSON     NVARCHAR(MAX) NOT NULL,                -- full snapshot
            Notes          NVARCHAR(MAX)
        )
    """))
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='OFNESGSensorReading')
        CREATE TABLE OFNESGSensorReading (
            ReadingID      BIGINT IDENTITY(1,1) PRIMARY KEY,
            BusinessID     INT NOT NULL,
            SensorID       NVARCHAR(120) NOT NULL,                -- caller-provided device identifier
            SensorType     NVARCHAR(40) NOT NULL,                 -- water / fertilizer / cooler_temp / energy / other
            Value          DECIMAL(18,4),
            Unit           NVARCHAR(40),
            Timestamp      DATETIME NOT NULL,
            ExtraJSON      NVARCHAR(MAX),
            ReceivedDate   DATETIME DEFAULT GETDATE()
        )
    """))
    for ix_name, table, col in [
        ("IX_OFNESGMetric_Biz",         "OFNESGMetric",        "BusinessID"),
        ("IX_OFNESGReport_Biz",         "OFNESGReport",        "BusinessID"),
        ("IX_OFNESGSensorReading_Biz",  "OFNESGSensorReading", "BusinessID"),
        ("IX_OFNESGSensorReading_Time", "OFNESGSensorReading", "Timestamp"),
    ]:
        db.execute(text(f"""
            IF NOT EXISTS (SELECT 1 FROM sys.indexes
                            WHERE name='{ix_name}' AND object_id = OBJECT_ID('{table}'))
            CREATE INDEX {ix_name} ON {table} ({col})
        """))
    db.commit()


try:
    with SessionLocal() as _db:
        ensure_tables(_db)
except Exception as e:
    print(f"[esg_reports] Table ensure warning: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Live aggregation — pulls from existing tables for the requested period
# ─────────────────────────────────────────────────────────────────────────────

def _live_metrics(db: Session, business_id: int, start: date, end: date) -> dict:
    """Compute audit-ready metrics for [start, end] from existing OFN tables.

    Numbers come from real activity records, so the same query reproduces the
    same answer at audit time — no re-derivation needed.
    """
    p = {"bid": business_id, "s": start, "e": end}

    # Sourcing transparency
    farm_count = db.execute(text(
        "SELECT COUNT(*) FROM OFNAggregatorFarm WHERE BusinessID = :bid AND Status = 'active'"
    ), p).scalar() or 0
    farms_certified = db.execute(text(
        "SELECT COUNT(*) FROM OFNAggregatorFarm WHERE BusinessID = :bid "
        "  AND Status = 'active' AND Certification IS NOT NULL AND Certification <> ''"
    ), p).scalar() or 0
    cert_breakdown = db.execute(text(
        "SELECT Certification, COUNT(*) AS N FROM OFNAggregatorFarm "
        "WHERE BusinessID = :bid AND Status = 'active' "
        "  AND Certification IS NOT NULL AND Certification <> '' "
        "GROUP BY Certification ORDER BY N DESC"
    ), p).fetchall()

    # Procurement (period-scoped)
    purchases = db.execute(text(
        "SELECT COUNT(*), ISNULL(SUM(QuantityKg),0), ISNULL(SUM(TotalPaid),0) "
        "FROM OFNAggregatorPurchase "
        "WHERE BusinessID = :bid AND ReceivedDate BETWEEN :s AND :e"
    ), p).fetchone()
    residue_pass = db.execute(text(
        "SELECT COUNT(*) FROM OFNAggregatorPurchase "
        "WHERE BusinessID = :bid AND ReceivedDate BETWEEN :s AND :e "
        "  AND ResidueTestStatus = 'passed'"
    ), p).scalar() or 0
    residue_fail = db.execute(text(
        "SELECT COUNT(*) FROM OFNAggregatorPurchase "
        "WHERE BusinessID = :bid AND ReceivedDate BETWEEN :s AND :e "
        "  AND ResidueTestStatus = 'failed'"
    ), p).scalar() or 0

    # Inputs to farms (saplings / tunnels / fertilizer / training)
    inputs_by_type = db.execute(text(
        "SELECT InputType, COUNT(*) AS N, ISNULL(SUM(TotalCost),0) AS Spend "
        "FROM OFNAggregatorInput "
        "WHERE BusinessID = :bid AND ProvidedDate BETWEEN :s AND :e "
        "GROUP BY InputType ORDER BY Spend DESC"
    ), p).fetchall()

    # Cold chain integrity
    dispatches = db.execute(text(
        "SELECT COUNT(*) FROM OFNAggregatorLogistics "
        "WHERE BusinessID = :bid AND CreatedDate BETWEEN :s AND :e"
    ), p).scalar() or 0
    breaches = db.execute(text(
        "SELECT COUNT(*) FROM OFNAggregatorLogistics "
        "WHERE BusinessID = :bid AND CreatedDate BETWEEN :s AND :e "
        "  AND ColdChainBreach = 1"
    ), p).scalar() or 0

    # Inventory waste signal — items currently quarantined or discarded
    waste = db.execute(text(
        "SELECT COUNT(*), ISNULL(SUM(CurrentKg),0) FROM OFNAggregatorInventory "
        "WHERE BusinessID = :bid AND QCStatus IN ('quarantine','discarded')"
    ), p).fetchone()

    # Sensor data (if anyone's posting to the webhook)
    sensor_summary = db.execute(text(
        "SELECT SensorType, COUNT(*) AS N, ISNULL(AVG(Value),0) AS Avg_, "
        "       ISNULL(MIN(Value),0) AS Min_, ISNULL(MAX(Value),0) AS Max_ "
        "FROM OFNESGSensorReading "
        "WHERE BusinessID = :bid AND Timestamp BETWEEN :s AND :e "
        "GROUP BY SensorType"
    ), p).fetchall()

    purchases_count = int(purchases[0] or 0)
    return {
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "sourcing": {
            "active_farms":           int(farm_count),
            "farms_certified":        int(farms_certified),
            "certified_pct":          round(100.0 * farms_certified / farm_count, 1) if farm_count else 0,
            "certifications":         [dict(r._mapping) for r in cert_breakdown],
        },
        "procurement": {
            "purchase_count": purchases_count,
            "kg_received":    float(purchases[1] or 0),
            "spend":          float(purchases[2] or 0),
            "residue_passed": int(residue_pass),
            "residue_failed": int(residue_fail),
            "residue_pass_rate_pct": (
                round(100.0 * residue_pass / purchases_count, 1) if purchases_count else None
            ),
        },
        "inputs_to_farms": {
            "by_type":     [dict(r._mapping) for r in inputs_by_type],
            "total_spend": float(sum(float(r._mapping["Spend"] or 0) for r in inputs_by_type)),
        },
        "cold_chain": {
            "dispatches":   int(dispatches),
            "breaches":     int(breaches),
            "integrity_pct": round(100.0 * (dispatches - breaches) / dispatches, 1) if dispatches else None,
        },
        "waste": {
            "items_quarantined_or_discarded": int(waste[0] or 0),
            "kg_quarantined_or_discarded":    float(waste[1] or 0),
        },
        "sensors": {
            "by_type": [
                {
                    "sensor_type": r._mapping["SensorType"],
                    "readings":    int(r._mapping["N"]),
                    "avg":         float(r._mapping["Avg_"]),
                    "min":         float(r._mapping["Min_"]),
                    "max":         float(r._mapping["Max_"]),
                }
                for r in sensor_summary
            ],
        },
    }


def _manual_metrics(db: Session, business_id: int, start: date, end: date) -> list:
    """Manual ESG metrics whose period overlaps [start, end]."""
    rows = db.execute(text("""
        SELECT MetricID, Category, MetricKey, Label, Value, NumericValue, Unit,
               PeriodStart, PeriodEnd, EvidenceURL, Notes, UpdatedDate
          FROM OFNESGMetric
         WHERE BusinessID = :bid
           AND (PeriodStart IS NULL OR PeriodStart <= :e)
           AND (PeriodEnd   IS NULL OR PeriodEnd   >= :s)
         ORDER BY Category, Label
    """), {"bid": business_id, "s": start, "e": end}).fetchall()
    return [dict(r._mapping) for r in rows]


def _parse_date(d, default):
    if not d:
        return default
    if isinstance(d, date):
        return d
    return datetime.strptime(str(d)[:10], "%Y-%m-%d").date()


# ─────────────────────────────────────────────────────────────────────────────
# Live snapshot endpoint — preview before saving
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/api/esg/{business_id}/live")
def live_snapshot(business_id: int,
                  start: Optional[str] = Query(None),
                  end:   Optional[str] = Query(None),
                  db: Session = Depends(get_db)):
    today = date.today()
    e = _parse_date(end, today)
    s = _parse_date(start, e - timedelta(days=90))
    return {
        "business_id":     business_id,
        "live":            _live_metrics(db, business_id, s, e),
        "manual_metrics":  _manual_metrics(db, business_id, s, e),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Manual metrics CRUD
# ─────────────────────────────────────────────────────────────────────────────

METRIC_FIELDS = ["Category","MetricKey","Label","Value","NumericValue","Unit",
                 "PeriodStart","PeriodEnd","EvidenceURL","Notes"]


@router.get("/api/esg/{business_id}/metrics")
def list_metrics(business_id: int,
                 category: Optional[str] = None,
                 db: Session = Depends(get_db)):
    where = "WHERE BusinessID = :bid"
    p = {"bid": business_id}
    if category:
        where += " AND Category = :c"; p["c"] = category
    rows = db.execute(text(f"""
        SELECT MetricID, BusinessID, {', '.join(METRIC_FIELDS)}, CreatedDate, UpdatedDate
          FROM OFNESGMetric
          {where}
         ORDER BY Category, Label
    """), p).fetchall()
    return [dict(r._mapping) for r in rows]


@router.post("/api/esg/{business_id}/metrics")
def create_metric(business_id: int, body: dict, db: Session = Depends(get_db)):
    # Blank strings → None so the numeric NumericValue column stores NULL instead of 500-ing.
    body = {k: (None if isinstance(v, str) and v.strip() == "" else v) for k, v in body.items()}
    if not body.get("MetricKey") or not body.get("Label"):
        raise HTTPException(400, "MetricKey and Label are required")
    res = db.execute(text("""
        INSERT INTO OFNESGMetric
            (BusinessID, Category, MetricKey, Label, Value, NumericValue, Unit,
             PeriodStart, PeriodEnd, EvidenceURL, Notes)
        OUTPUT INSERTED.MetricID
        VALUES (:bid, :cat, :mk, :lbl, :v, :nv, :u, :ps, :pe, :ev, :n)
    """), {
        "bid": business_id,
        "cat": body.get("Category", "environmental"),
        "mk":  body["MetricKey"],
        "lbl": body["Label"],
        "v":   body.get("Value"),
        "nv":  body.get("NumericValue"),
        "u":   body.get("Unit"),
        "ps":  body.get("PeriodStart"),
        "pe":  body.get("PeriodEnd"),
        "ev":  body.get("EvidenceURL"),
        "n":   body.get("Notes"),
    }).fetchone()
    db.commit()
    return {"MetricID": int(res.MetricID)}


@router.put("/api/esg/metrics/{metric_id}")
def update_metric(metric_id: int, body: dict, db: Session = Depends(get_db)):
    body = {k: (None if isinstance(v, str) and v.strip() == "" else v) for k, v in body.items()}
    cols = [c for c in METRIC_FIELDS if c in body]
    if cols:
        sets = ", ".join(f"{c} = :{c}" for c in cols) + ", UpdatedDate = GETDATE()"
        params = {c: body[c] for c in cols}
        params["__id"] = metric_id
        db.execute(text(f"UPDATE OFNESGMetric SET {sets} WHERE MetricID = :__id"), params)
        db.commit()
    return {"ok": True}


@router.delete("/api/esg/metrics/{metric_id}")
def delete_metric(metric_id: int, db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM OFNESGMetric WHERE MetricID = :id"), {"id": metric_id})
    db.commit()
    return {"ok": True}


# ─────────────────────────────────────────────────────────────────────────────
# Reports — generate (snapshot) / list / get / download / delete
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/api/esg/{business_id}/reports/generate")
def generate_report(business_id: int, body: dict, db: Session = Depends(get_db)):
    today = date.today()
    period_end   = _parse_date(body.get("PeriodEnd"),   today)
    period_start = _parse_date(body.get("PeriodStart"), period_end - timedelta(days=90))
    if period_end < period_start:
        raise HTTPException(400, "PeriodEnd must be on or after PeriodStart")

    snapshot = {
        "title":   body.get("Title") or f"ESG Report {period_start.isoformat()} → {period_end.isoformat()}",
        "period":  {"start": period_start.isoformat(), "end": period_end.isoformat()},
        "live":    _live_metrics(db, business_id, period_start, period_end),
        "manual_metrics": _manual_metrics(db, business_id, period_start, period_end),
        "generated_at":   datetime.utcnow().isoformat() + "Z",
        "generated_by":   body.get("GeneratedByID"),
        "signatory":      body.get("Signatory"),
        "signature_date": body.get("SignatureDate"),
        "notes":          body.get("Notes"),
    }
    res = db.execute(text("""
        INSERT INTO OFNESGReport
            (BusinessID, Title, PeriodStart, PeriodEnd, GeneratedByID,
             Signatory, SignatureDate, ReportJSON, Notes)
        OUTPUT INSERTED.ReportID
        VALUES (:bid, :t, :ps, :pe, :gby, :sig, :sd, :j, :n)
    """), {
        "bid": business_id,
        "t":   snapshot["title"],
        "ps":  period_start,
        "pe":  period_end,
        "gby": body.get("GeneratedByID"),
        "sig": body.get("Signatory"),
        "sd":  body.get("SignatureDate"),
        "j":   json.dumps(snapshot, default=str),
        "n":   body.get("Notes"),
    }).fetchone()
    db.commit()
    return {"ReportID": int(res.ReportID), "snapshot": snapshot}


@router.get("/api/esg/{business_id}/reports")
def list_reports(business_id: int, db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT ReportID, BusinessID, Title, PeriodStart, PeriodEnd,
               GeneratedDate, GeneratedByID, Signatory, SignatureDate
          FROM OFNESGReport
         WHERE BusinessID = :bid
         ORDER BY GeneratedDate DESC, ReportID DESC
    """), {"bid": business_id}).fetchall()
    return [dict(r._mapping) for r in rows]


def _load_report(db: Session, report_id: int) -> dict:
    row = db.execute(text("""
        SELECT ReportID, BusinessID, Title, PeriodStart, PeriodEnd,
               GeneratedDate, GeneratedByID, Signatory, SignatureDate, ReportJSON, Notes
          FROM OFNESGReport
         WHERE ReportID = :id
    """), {"id": report_id}).fetchone()
    if not row:
        raise HTTPException(404, "Report not found")
    d = dict(row._mapping)
    try:
        d["snapshot"] = json.loads(d.pop("ReportJSON"))
    except Exception:
        d["snapshot"] = {}
    return d


@router.get("/api/esg/reports/{report_id}")
def get_report(report_id: int, db: Session = Depends(get_db)):
    return _load_report(db, report_id)


@router.delete("/api/esg/reports/{report_id}")
def delete_report(report_id: int, db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM OFNESGReport WHERE ReportID = :id"), {"id": report_id})
    db.commit()
    return {"ok": True}


# ─────────────────────────────────────────────────────────────────────────────
# Printable HTML view — also the source for the PDF renderer
# ─────────────────────────────────────────────────────────────────────────────

def _report_html(report: dict) -> str:
    snap = report.get("snapshot") or {}
    live = snap.get("live") or {}
    manual = snap.get("manual_metrics") or []
    src = live.get("sourcing") or {}
    proc = live.get("procurement") or {}
    inputs = live.get("inputs_to_farms") or {}
    cold = live.get("cold_chain") or {}
    waste = live.get("waste") or {}
    sensors = (live.get("sensors") or {}).get("by_type") or []

    def rowf(label, value, sub=""):
        return f"<tr><td class='lbl'>{label}</td><td class='val'>{value}{(' <span class=sub>'+sub+'</span>') if sub else ''}</td></tr>"

    cert_html = "".join(
        f"<li>{c['Certification']}: <strong>{c['N']}</strong> farm(s)</li>"
        for c in src.get("certifications", [])
    ) or "<li class=muted>No certifications recorded.</li>"

    inputs_html = "".join(
        f"<li>{r['InputType']}: <strong>{r['N']}</strong> records · ${float(r['Spend'] or 0):,.0f}</li>"
        for r in inputs.get("by_type", [])
    ) or "<li class=muted>No inputs distributed in this period.</li>"

    sensors_html = "".join(
        f"<li>{r['sensor_type']}: <strong>{r['readings']}</strong> readings · avg {r['avg']:.2f}, range {r['min']:.2f}–{r['max']:.2f}</li>"
        for r in sensors
    ) or "<li class=muted>No sensor data ingested in this period.</li>"

    manual_rows_by_cat = {}
    for m in manual:
        manual_rows_by_cat.setdefault(m.get("Category") or "other", []).append(m)
    manual_html = ""
    for cat in ("environmental", "social", "governance"):
        rows = manual_rows_by_cat.get(cat, [])
        if not rows:
            continue
        manual_html += f"<h3>{cat.title()}</h3><table class='kv'>"
        for m in rows:
            label = m.get("Label", "")
            value = m.get("Value", "")
            unit  = m.get("Unit") or ""
            ev    = m.get("EvidenceURL")
            sub_bits = []
            if unit:
                sub_bits.append(unit)
            if m.get("PeriodStart") or m.get("PeriodEnd"):
                sub_bits.append(f"{(m.get('PeriodStart') or '')} → {(m.get('PeriodEnd') or '')}")
            if ev:
                sub_bits.append(f'<a href="{ev}">evidence</a>')
            manual_html += rowf(label, value, " · ".join(sub_bits))
        manual_html += "</table>"
    if not manual_html:
        manual_html = "<p class=muted>No manual ESG metrics recorded for this period.</p>"

    return f"""<!doctype html>
<html><head><meta charset="utf-8"/>
<title>{report.get('Title', 'ESG Report')}</title>
<style>
  body {{ font-family: 'Helvetica Neue', Arial, sans-serif; color: #222; max-width: 780px; margin: 32px auto; padding: 0 24px; }}
  h1   {{ margin-bottom: 4px; font-size: 22pt; }}
  .meta{{ color: #666; font-size: 10pt; margin-bottom: 24px; }}
  h2   {{ border-bottom: 2px solid #3D6B34; padding-bottom: 4px; margin-top: 28px; font-size: 14pt; color: #2d5226; }}
  h3   {{ margin-top: 18px; font-size: 12pt; color: #444; }}
  table.kv {{ width: 100%; border-collapse: collapse; margin: 8px 0; }}
  table.kv td {{ padding: 4px 8px; border-bottom: 1px solid #eee; font-size: 10pt; vertical-align: top; }}
  table.kv td.lbl {{ width: 55%; color: #444; }}
  table.kv td.val {{ font-weight: 600; }}
  .sub {{ font-weight: 400; color: #888; font-size: 9pt; }}
  ul   {{ font-size: 10pt; line-height: 1.5; }}
  .muted{{ color: #999; }}
  .sig {{ margin-top: 36px; padding-top: 16px; border-top: 1px solid #ccc; font-size: 10pt; color: #444; }}
  .footer {{ margin-top: 24px; font-size: 8.5pt; color: #999; text-align: center; }}
</style>
</head><body>
  <h1>{report.get('Title', 'ESG Report')}</h1>
  <div class="meta">
    Period: {report.get('PeriodStart','')} → {report.get('PeriodEnd','')} ·
    Generated {(report.get('GeneratedDate') or '').isoformat() if hasattr(report.get('GeneratedDate'), 'isoformat') else report.get('GeneratedDate','')}
  </div>

  <h2>Sourcing transparency</h2>
  <table class="kv">
    {rowf("Active partner farms", src.get("active_farms", 0))}
    {rowf("Certified farms", f"{src.get('farms_certified', 0)} ({src.get('certified_pct', 0)}%)")}
  </table>
  <h3>Certification breakdown</h3>
  <ul>{cert_html}</ul>

  <h2>Procurement & residue testing</h2>
  <table class="kv">
    {rowf("Purchase records", proc.get("purchase_count", 0))}
    {rowf("Quantity received", f"{proc.get('kg_received', 0):,.1f} kg")}
    {rowf("Spend", f"${proc.get('spend', 0):,.2f}")}
    {rowf("Residue tests passed", proc.get("residue_passed", 0))}
    {rowf("Residue tests failed", proc.get("residue_failed", 0))}
    {rowf("Residue pass rate", f"{proc.get('residue_pass_rate_pct')}%" if proc.get('residue_pass_rate_pct') is not None else 'n/a')}
  </table>

  <h2>Inputs distributed to farms</h2>
  <ul>{inputs_html}</ul>
  <p class="muted">Total invested in farm inputs: <strong>${(inputs.get('total_spend') or 0):,.2f}</strong></p>

  <h2>Cold chain integrity</h2>
  <table class="kv">
    {rowf("Dispatches logged", cold.get("dispatches", 0))}
    {rowf("Cold-chain breaches", cold.get("breaches", 0))}
    {rowf("Integrity rate", f"{cold.get('integrity_pct')}%" if cold.get('integrity_pct') is not None else 'n/a')}
  </table>

  <h2>Waste signal</h2>
  <table class="kv">
    {rowf("Items quarantined / discarded", waste.get("items_quarantined_or_discarded", 0))}
    {rowf("Kg quarantined / discarded", f"{waste.get('kg_quarantined_or_discarded', 0):,.1f}")}
  </table>

  <h2>Sensor data (IoT-ingested)</h2>
  <ul>{sensors_html}</ul>

  <h2>Manual ESG metrics</h2>
  {manual_html}

  <div class="sig">
    Signatory: <strong>{report.get('Signatory') or '_____________________'}</strong><br>
    Signature date: {report.get('SignatureDate') or '_____________________'}<br>
    Notes: {report.get('Notes') or '—'}
  </div>
  <div class="footer">Generated by Oatmeal AI · ESG Reports module</div>
</body></html>"""


@router.get("/api/esg/reports/{report_id}/html", response_class=Response)
def report_html(report_id: int, db: Session = Depends(get_db)):
    rep = _load_report(db, report_id)
    return Response(content=_report_html(rep), media_type="text/html")


# ─────────────────────────────────────────────────────────────────────────────
# PDF download — reportlab; falls back to HTML if reportlab isn't installed
# ─────────────────────────────────────────────────────────────────────────────

def _report_pdf_bytes(report: dict) -> bytes:
    """Render a paginated PDF using reportlab. Layout mirrors the HTML view
    but is platform-styled rather than browser-rendered."""
    from reportlab.lib.pagesizes import LETTER
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors
    from reportlab.lib.units import inch
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak,
    )
    import io

    snap   = report.get("snapshot") or {}
    live   = snap.get("live") or {}
    manual = snap.get("manual_metrics") or []
    src    = live.get("sourcing") or {}
    proc   = live.get("procurement") or {}
    inputs = live.get("inputs_to_farms") or {}
    cold   = live.get("cold_chain") or {}
    waste  = live.get("waste") or {}
    sensors = (live.get("sensors") or {}).get("by_type") or []

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=LETTER,
                            leftMargin=0.7*inch, rightMargin=0.7*inch,
                            topMargin=0.6*inch, bottomMargin=0.6*inch,
                            title=report.get("Title", "ESG Report"))
    ss = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Title"], fontSize=18, leading=22)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], fontSize=12, textColor=colors.HexColor("#2d5226"),
                        spaceBefore=14, spaceAfter=4)
    body = ss["BodyText"]
    muted = ParagraphStyle("muted", parent=body, textColor=colors.grey, fontSize=9)
    flow = []

    flow.append(Paragraph(report.get("Title", "ESG Report"), h1))
    flow.append(Paragraph(
        f"Period: {report.get('PeriodStart','')} → {report.get('PeriodEnd','')} · "
        f"Generated {(report.get('GeneratedDate').isoformat() if hasattr(report.get('GeneratedDate'), 'isoformat') else report.get('GeneratedDate',''))}",
        muted,
    ))
    flow.append(Spacer(1, 12))

    def kv_table(rows):
        t = Table(rows, colWidths=[3.2*inch, 3.0*inch])
        t.setStyle(TableStyle([
            ("FONTNAME", (0,0), (-1,-1), "Helvetica"),
            ("FONTSIZE", (0,0), (-1,-1), 10),
            ("LINEBELOW", (0,0), (-1,-1), 0.25, colors.lightgrey),
            ("VALIGN",  (0,0), (-1,-1), "TOP"),
            ("BOTTOMPADDING", (0,0), (-1,-1), 4),
            ("TOPPADDING",    (0,0), (-1,-1), 4),
            ("TEXTCOLOR", (0,0), (0,-1), colors.HexColor("#444")),
            ("FONTNAME",  (1,0), (1,-1), "Helvetica-Bold"),
        ]))
        return t

    # Sourcing
    flow.append(Paragraph("Sourcing transparency", h2))
    flow.append(kv_table([
        ["Active partner farms", str(src.get("active_farms", 0))],
        ["Certified farms",      f"{src.get('farms_certified', 0)} ({src.get('certified_pct', 0)}%)"],
    ]))
    if src.get("certifications"):
        flow.append(Spacer(1, 4))
        for c in src["certifications"]:
            flow.append(Paragraph(f"• {c['Certification']}: <b>{c['N']}</b> farm(s)", body))

    # Procurement
    flow.append(Paragraph("Procurement &amp; residue testing", h2))
    flow.append(kv_table([
        ["Purchase records",      str(proc.get("purchase_count", 0))],
        ["Quantity received",     f"{proc.get('kg_received', 0):,.1f} kg"],
        ["Spend",                 f"${proc.get('spend', 0):,.2f}"],
        ["Residue tests passed",  str(proc.get("residue_passed", 0))],
        ["Residue tests failed",  str(proc.get("residue_failed", 0))],
        ["Residue pass rate",     f"{proc.get('residue_pass_rate_pct')}%" if proc.get('residue_pass_rate_pct') is not None else "n/a"],
    ]))

    # Inputs
    flow.append(Paragraph("Inputs distributed to farms", h2))
    if inputs.get("by_type"):
        for r in inputs["by_type"]:
            flow.append(Paragraph(
                f"• {r['InputType']}: <b>{r['N']}</b> records · ${float(r['Spend'] or 0):,.0f}", body,
            ))
        flow.append(Paragraph(
            f"Total invested in farm inputs: <b>${(inputs.get('total_spend') or 0):,.2f}</b>", muted,
        ))
    else:
        flow.append(Paragraph("No inputs distributed in this period.", muted))

    # Cold chain
    flow.append(Paragraph("Cold chain integrity", h2))
    flow.append(kv_table([
        ["Dispatches logged",  str(cold.get("dispatches", 0))],
        ["Cold-chain breaches", str(cold.get("breaches", 0))],
        ["Integrity rate",     f"{cold.get('integrity_pct')}%" if cold.get('integrity_pct') is not None else "n/a"],
    ]))

    # Waste
    flow.append(Paragraph("Waste signal", h2))
    flow.append(kv_table([
        ["Items quarantined / discarded", str(waste.get("items_quarantined_or_discarded", 0))],
        ["Kg quarantined / discarded",    f"{waste.get('kg_quarantined_or_discarded', 0):,.1f}"],
    ]))

    # Sensors
    flow.append(Paragraph("Sensor data (IoT-ingested)", h2))
    if sensors:
        for r in sensors:
            flow.append(Paragraph(
                f"• {r['sensor_type']}: <b>{r['readings']}</b> readings · "
                f"avg {r['avg']:.2f}, range {r['min']:.2f}–{r['max']:.2f}", body,
            ))
    else:
        flow.append(Paragraph("No sensor data ingested in this period.", muted))

    # Manual metrics
    flow.append(Paragraph("Manual ESG metrics", h2))
    if manual:
        for cat in ("environmental", "social", "governance"):
            cat_rows = [m for m in manual if (m.get("Category") or "other") == cat]
            if not cat_rows:
                continue
            flow.append(Paragraph(cat.title(), ParagraphStyle("cat", parent=ss["Heading3"], fontSize=11, spaceBefore=8)))
            kv_rows = []
            for m in cat_rows:
                tail = []
                if m.get("Unit"):        tail.append(m["Unit"])
                if m.get("PeriodStart") or m.get("PeriodEnd"):
                    tail.append(f"{m.get('PeriodStart','')} → {m.get('PeriodEnd','')}")
                if m.get("EvidenceURL"): tail.append("evidence: " + str(m["EvidenceURL"]))
                val = (m.get("Value") or "")
                if tail:
                    val = f"{val}\n({' · '.join(tail)})"
                kv_rows.append([m.get("Label", ""), val])
            flow.append(kv_table(kv_rows))
    else:
        flow.append(Paragraph("No manual ESG metrics recorded for this period.", muted))

    # Signature
    flow.append(Spacer(1, 20))
    flow.append(Paragraph(
        f"<b>Signatory:</b> {report.get('Signatory') or '_____________________'}<br/>"
        f"<b>Signature date:</b> {report.get('SignatureDate') or '_____________________'}<br/>"
        f"<b>Notes:</b> {report.get('Notes') or '—'}",
        body,
    ))
    flow.append(Spacer(1, 12))
    flow.append(Paragraph("Generated by Oatmeal AI · ESG Reports module", muted))

    doc.build(flow)
    return buf.getvalue()


@router.get("/api/esg/reports/{report_id}/pdf")
def report_pdf(report_id: int, db: Session = Depends(get_db)):
    rep = _load_report(db, report_id)
    try:
        pdf = _report_pdf_bytes(rep)
    except ImportError:
        # reportlab not installed in this environment — fall back to HTML so the
        # user still gets the full report and can print-to-PDF in the browser.
        return Response(content=_report_html(rep), media_type="text/html")
    filename = f"esg_report_{report_id}.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ─────────────────────────────────────────────────────────────────────────────
# Sensor webhook stub — landing pad for future IoT integration
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/api/esg/{business_id}/sensor-webhook")
def sensor_webhook(business_id: int, body: dict, db: Session = Depends(get_db)):
    """Accept a sensor reading from any future IoT integration.

    Expected body:
      {
        "sensor_id":   "cooler_03",
        "sensor_type": "cooler_temp",   // water / fertilizer / cooler_temp / energy / other
        "value":       3.7,
        "unit":        "celsius",
        "timestamp":   "2026-04-27T14:32:00Z",   // optional, defaults to now
        "extra":       { ... }                    // optional vendor-specific payload
      }

    Today: nothing posts here. The endpoint exists so that whichever IoT
    vendor (or homemade Pi sensor) you bring online next can write to it
    without any further backend changes — readings will start showing up
    in the ESG live snapshot under `sensors.by_type` automatically.
    """
    if not body.get("sensor_id") or not body.get("sensor_type"):
        raise HTTPException(400, "sensor_id and sensor_type are required")
    ts = body.get("timestamp")
    try:
        ts = datetime.fromisoformat(str(ts).replace("Z", "+00:00")) if ts else datetime.utcnow()
    except Exception:
        ts = datetime.utcnow()
    extra = body.get("extra")
    extra_json = json.dumps(extra) if extra else None
    res = db.execute(text("""
        INSERT INTO OFNESGSensorReading
            (BusinessID, SensorID, SensorType, Value, Unit, Timestamp, ExtraJSON)
        OUTPUT INSERTED.ReadingID
        VALUES (:bid, :sid, :st, :v, :u, :t, :x)
    """), {
        "bid": business_id,
        "sid": body["sensor_id"],
        "st":  body["sensor_type"],
        "v":   body.get("value"),
        "u":   body.get("unit"),
        "t":   ts,
        "x":   extra_json,
    }).fetchone()
    db.commit()
    return {"ReadingID": int(res.ReadingID)}
