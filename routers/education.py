"""Educational Content — courses, articles, and enrollment tracking."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db, engine
from typing import Optional
from pydantic import BaseModel

router = APIRouter(prefix="/api/education", tags=["education"])

with engine.begin() as _c:
    _c.execute(text("""
        IF NOT EXISTS (SELECT * FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='EduCourses')
        CREATE TABLE EduCourses (
            CourseID        INT IDENTITY(1,1) PRIMARY KEY,
            BusinessID      INT NULL,
            Title           NVARCHAR(300) NOT NULL,
            Description     NVARCHAR(MAX) NULL,
            Category        VARCHAR(60) NULL,
            Difficulty      VARCHAR(20) NULL,
            DurationMin     INT NULL,
            AuthorName      NVARCHAR(150) NULL,
            ThumbnailUrl    NVARCHAR(500) NULL,
            ContentUrl      NVARCHAR(500) NULL,
            ContentType     VARCHAR(30) NOT NULL DEFAULT 'article',
            IsFree          BIT NOT NULL DEFAULT 1,
            IsPublished     BIT NOT NULL DEFAULT 1,
            ViewCount       INT NOT NULL DEFAULT 0,
            CreatedAt       DATETIME NOT NULL DEFAULT GETDATE()
        )
    """))
    _c.execute(text("""
        IF NOT EXISTS (SELECT * FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='EduEnrollments')
        CREATE TABLE EduEnrollments (
            EnrollmentID    INT IDENTITY(1,1) PRIMARY KEY,
            CourseID        INT NOT NULL,
            PeopleID        INT NOT NULL,
            ProgressPct     INT NOT NULL DEFAULT 0,
            CompletedAt     DATETIME NULL,
            CreatedAt       DATETIME NOT NULL DEFAULT GETDATE(),
            CONSTRAINT UQ_EduEnroll UNIQUE (CourseID, PeopleID)
        )
    """))
    _c.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM sys.columns
                       WHERE object_id=OBJECT_ID('EduCourses') AND name='BodyText')
        ALTER TABLE EduCourses ADD BodyText NVARCHAR(MAX) NULL
    """))
    _c.execute(text("""
        IF NOT EXISTS (SELECT * FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='EduBookmarks')
        CREATE TABLE EduBookmarks (
            BookmarkID      INT IDENTITY(1,1) PRIMARY KEY,
            CourseID        INT NOT NULL,
            PeopleID        INT NOT NULL,
            CreatedAt       DATETIME NOT NULL DEFAULT GETDATE(),
            CONSTRAINT UQ_EduBook UNIQUE (CourseID, PeopleID)
        )
    """))
    # Seed starter content
    _c.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM EduCourses)
        INSERT INTO EduCourses (Title,Category,Difficulty,DurationMin,AuthorName,ContentType,IsFree,Description,BodyText) VALUES
        ('Cover Crop Selection Guide','Soil Health','Beginner',15,'OFN Extension','article',1,
         'How to choose the right cover crops for your region, soil type, and production goals.',
         N'## Why Cover Crops Matter

Cover crops protect bare soil from erosion, fix nitrogen, suppress weeds, and feed soil biology between cash crops. Choosing the wrong species can create more work than it saves, so matching the mix to your goals is critical.

## Common Species and Their Roles

**Legumes (clover, vetch, field peas)** fix atmospheric nitrogen through root nodules. A good stand of crimson clover can contribute 80–120 lb N/acre to the following crop.

**Grasses (cereal rye, oats, triticale)** produce large amounts of biomass, suppress weeds through shading and allelopathy, and protect soil structure over winter.

**Brassicas (radish, turnip, rapeseed)** break compaction with their taproots and scavenge residual nitrogen that would otherwise leach. Daikon radish can penetrate 18 inches of compacted subsoil.

## Matching Species to Your Goals

| Goal | Best Choices |
|------|-------------|
| Nitrogen credit | Crimson clover, hairy vetch, field peas |
| Winter erosion control | Cereal rye, winter triticale |
| Compaction relief | Tillage radish, turnip |
| Weed suppression | Cereal rye, sorghum-sudan |
| Bee forage | Buckwheat, phacelia, red clover |

## Seeding Timing

Plant summer covers immediately after cash crop harvest. Winter covers should go in 4–6 weeks before the first killing frost to establish a stand. In the South, covers can be overseeded into standing corn or beans using high-clearance equipment.

## Termination

Terminate covers 2–3 weeks before planting to allow residue decomposition and avoid nitrogen tie-up from high-carbon species. Cereal rye biomass over 4,000 lb/acre may require rolling-crimping or an additional week of breakdown time.'),

        ('Understanding NDVI and Satellite Imagery','Precision Ag','Intermediate',20,'OFN Extension','article',1,
         'What NDVI means, how to interpret health maps, and when to act on low scores.',
         N'## What Is NDVI?

Normalized Difference Vegetation Index (NDVI) is a mathematical ratio calculated from near-infrared (NIR) and red reflectance measured by satellite sensors. Healthy green plants absorb red light for photosynthesis and reflect NIR strongly; stressed or sparse vegetation does the opposite.

**Formula:** NDVI = (NIR − Red) / (NIR + Red)

Values range from −1.0 to +1.0. In practice, a well-established crop canopy typically falls between 0.6 and 0.9 at peak growth, while bare soil reads 0.1–0.2 and water or cloud shadow can go negative.

## Reading the Map

Most precision ag platforms display NDVI on a color ramp — deep green for high values, yellow for mid-range, red for low. When interpreting your map:

- **Compare fields to themselves over time.** A single snapshot is less useful than a trend. If a zone that was green last season is now yellow, something changed.
- **Look for patterns.** Edge effects, waterways, soil type boundaries, and old fence lines all show up in NDVI. Uniform low values across an entire field suggest a field-wide issue (fertility, drainage, seeding problem). Patchy variation points toward soil variability or pest pressure.
- **Time the imagery correctly.** NDVI peaks at canopy closure and declines naturally as the crop matures. Compare images taken at the same crop growth stage across years for apples-to-apples analysis.

## When to Act on Low Scores

Not every low-NDVI zone requires an immediate response. Use this decision tree:

1. **Is the low zone persistent across multiple dates?** → Likely a soil issue; pull soil cores.
2. **Did it appear suddenly between two images?** → Scout for disease, insects, or hail damage.
3. **Does it align with a soil type boundary?** → Adjust fertility zones and seed populations accordingly.
4. **Is it at field edges?** → Check compaction from headland traffic, drainage tile breaks, or deer pressure.

## Limitations

Cloud cover, smoke, and atmospheric haze degrade image quality. Satellite revisit frequency (3–5 days for Sentinel-2, daily for Planet) determines how quickly you catch a problem. Always ground-truth with physical scouting before making large input decisions based solely on NDVI.'),

        ('Farm Financial Basics: Cash Flow Planning','Business','Beginner',25,'OFN Extension','article',1,
         'Building a simple 12-month cash flow model for your farm operation.',
         N'## Why Cash Flow Matters More Than Profit

A farm can show a paper profit in December while running out of cash in March. Seasonal revenue and year-round expenses create gaps that must be planned for. A 12-month cash flow projection tells you exactly when those gaps occur so you can arrange operating credit before you need it — not during a crisis.

## The Four Building Blocks

**1. Revenue Timing**
List every income source (crop sales, livestock sales, custom work, government payments, direct marketing) and estimate *when the cash will arrive*, not when the sale will occur. Grain stored on-farm generates no cash until it is sold. CSA subscriptions paid in April fund May–October production costs.

**2. Variable Costs**
Inputs (seed, fertilizer, chemicals, feed) typically cluster in spring and fall. Map each purchase to the month you expect to write the check.

**3. Fixed Costs**
Land rent, loan payments, insurance, and utilities are predictable. Place them in the correct month and they will rarely surprise you.

**4. Family Living**
Many farm budgets omit owner withdrawals and family living expenses. Include them. A farm that cannot support the family is not a sustainable business.

## Building the Spreadsheet

Set up 13 columns: one label column, then January through December. Add rows for each revenue and expense category. At the bottom, calculate:
- **Monthly Net Cash Flow** = total receipts − total disbursements
- **Cumulative Cash Balance** = prior month balance + monthly net

Watch for months where the cumulative balance goes negative — those are your borrowing windows. Add an operating line of credit in those cells and calculate interest expense on the draw.

## Stress Testing

Run the projection a second time with commodity prices 15% lower and input costs 10% higher. If the operation stays solvent, you have a meaningful margin of safety. If it does not, identify which line items to cut or which revenue source to accelerate.

## Updating Monthly

A projection is only useful if it tracks against reality. At the end of each month, enter actual receipts and disbursements and note the variance. Recurring variances (always overspending on repairs, consistently receiving grain payments later than projected) improve future accuracy.'),

        ('USDA Organic Certification: Step-by-Step','Certifications','Beginner',30,'OFN Extension','article',1,
         'What you need to do to achieve and maintain USDA organic certification.',
         N'## Is Certification Right for You?

USDA organic certification is required to sell, label, or represent products as organic when annual gross sales exceed $5,000. Below that threshold, a producer may make organic claims without certification but must still follow NOP regulations. Certification is administered by USDA-accredited certifying agents (CAs), not by USDA directly.

## The Three-Year Transition

Land must be managed organically — without prohibited substances — for 36 months before the first certified organic harvest. If you have never applied synthetic pesticides or fertilizers to a field, document that history. If you are transitioning conventionally managed ground, the clock starts on the last application date of any prohibited substance.

## Steps to Certification

**Step 1: Choose a Certifying Agent**
The USDA maintains a searchable list of accredited CAs at ams.usda.gov. Compare fees, response times, and inspector familiarity with your production type. Annual fees typically range from $400 to $2,500 depending on operation size.

**Step 2: Build Your Organic System Plan (OSP)**
The OSP is the core document. It describes:
- Fields, acreage, and crop history
- All inputs (seeds, soil amendments, pest management materials) and their compliance status
- Practices for preventing co-mingling and contamination
- Record-keeping systems

**Step 3: Submit Application and Pay Fees**
Submit your OSP, field maps, and three years of records (or a signed affidavit for land with no prohibited substance history).

**Step 4: On-Site Inspection**
An inspector visits your operation, reviews records, walks fields, and may collect soil or tissue samples. Be prepared to show purchase receipts for all inputs, field activity logs, and sales records.

**Step 5: Certification Decision**
The CA reviews the inspection report and issues a certificate, a notice of noncompliance, or a denial. Most compliant first-time applicants receive certification within 60–90 days of a complete application.

## Annual Renewal

Certification is renewed annually. Submit an updated OSP, pay fees, and schedule your annual inspection. Keep records for 5 years — inspectors may request historical documentation.

## Allowed and Prohibited Substances

The National List (7 CFR Part 205) specifies what is allowed. When in doubt, check the OMRI (Organic Materials Review Institute) database before purchasing any input. A single non-compliant application can result in decertification and loss of the three-year transition period.'),

        ('Rotational Grazing 101','Livestock','Beginner',20,'OFN Extension','article',1,
         'Paddock design, stocking rates, and rest period planning for sustainable grazing.',
         N'## The Core Principle

Rotational grazing mimics the movement patterns of wild herbivores: graze intensively, then move on and allow complete recovery before returning. Continuous grazing lets animals selectively remove their favorite plants over and over, weakening root systems, reducing stand density, and inviting weed pressure. Rotation prevents this by enforcing rest.

## Paddock Design

Divide your total grazing area into a minimum of 4–8 paddocks. More paddocks give you longer rest periods and more flexibility. The goal is to graze each paddock for 3–7 days and then rest it for 21–60 days, depending on the season and forage growth rate.

**Practical layout tips:**
- Locate water and shade in or adjacent to every paddock, or use a central water point with cross-fencing.
- Use temporary electric fence (polywire, step-in posts) for flexibility — paddock size can shift as forage growth rates change.
- Consider topography: steep slopes, wet areas, and sacrifice paddocks (for feeding hay in winter) should be designated separately.

## Stocking Rates

Stocking rate is the single most important variable. Overstocking causes soil compaction, forage destruction, and poor animal performance. Understocking wastes forage and allows coarse, unpalatable growth.

A starting rule of thumb for cool-season grass-based systems:
- 1 animal unit (1,000 lb beef cow + calf) per 1.5–3 acres depending on rainfall and soil productivity
- Adjust annually based on body condition score trends and forage availability

## Timing the Move

Move animals when the forage is grazed to 3–4 inches residual height for most cool-season grasses. Do not wait until paddocks are grazed bare — leaving 3–4 inches of leaf area allows rapid regrowth from stored root carbohydrates.

In high summer growth periods, you may need to clip paddocks that get ahead of the rotation. In drought, extend rest periods and consider destocking rather than forcing animals onto short, stressed forage.

## Monitoring Recovery

Before re-entering a paddock, forage should be back to 8–12 inches for cool-season species or 12–18 inches for warm-season grasses. Use a grazing stick or simple ruler. If paddocks are not recovering fully between rotations, reduce animal numbers or extend rest periods.'),

        ('Crop Scouting Best Practices','Crop Management','Intermediate',18,'OFN Extension','article',1,
         'How to build a scouting program: timing, sampling methods, and record keeping.',
         N'## Why Scout?

Scouting converts field observations into decisions. Without systematic scouting, pest problems compound until they are obvious — and expensive. A structured program catches issues at economic threshold levels, when targeted intervention is still cost-effective, rather than after yield loss has already occurred.

## Building a Scouting Schedule

Scout each field at least once per week during the growing season. Critical windows:

- **Pre-plant through emergence:** Soil compaction, residue breakdown, stand establishment, early-season weed flushes
- **Vegetative stages (V3–V8 in corn, R1–R3 in soybeans):** Aphid colonies, rootworm silk clipping, spider mite hot spots, iron deficiency chlorosis
- **Reproductive stages:** Disease scouting intensifies — gray leaf spot, northern corn leaf blight, white mold, soybean sudden death syndrome
- **Pre-harvest:** Stalk quality, harvest aids timing for soybeans, aflatoxin risk assessment

## Sampling Methods

Walk a consistent pattern — a W or X route across the field — so you cover multiple soil types and management zones. Stop at 10–20 locations per field and examine 10–20 plants per stop. Avoid field edges for your primary count; edges are not representative of field-average pressure.

**For insects:** Count individuals per plant, per leaf, per row foot, or per trap — whichever unit matches the economic threshold table for that pest. Thresholds exist for most major pests and are published by land-grant extension services.

**For disease:** Use a percent-affected-plants or percent-affected-leaf-area rating. Rate the same plant part (e.g., upper canopy leaves) consistently across stops.

**For weeds:** Estimate percent ground cover or plants per square foot. Identify species — some weeds (waterhemp, Palmer amaranth) have much lower economic thresholds than others.

## Record Keeping

Record observations in a field log (paper or digital) immediately. Capture: date, field ID, crop stage, GPS location of notable finds, counts or ratings, and your action decision. Photos tied to GPS points are invaluable for trend analysis. Compare current records to the same week in prior seasons to distinguish unusual pressure from normal background levels.

## When to Call for Help

If you find a pest or symptom you cannot confidently identify, collect a sample in a sealed bag and contact your extension office, certified crop adviser, or the OFN agronomist tools. Misidentification leads to wrong treatments and wasted money.')
    """))
    # Backfill BodyText for rows seeded before this column existed
    _c.execute(text("""
        UPDATE EduCourses SET BodyText = N'## Why Cover Crops Matter

Cover crops protect bare soil from erosion, fix nitrogen, suppress weeds, and feed soil biology between cash crops. Choosing the wrong species can create more work than it saves, so matching the mix to your goals is critical.

## Common Species and Their Roles

**Legumes (clover, vetch, field peas)** fix atmospheric nitrogen through root nodules. A good stand of crimson clover can contribute 80-120 lb N/acre to the following crop.

**Grasses (cereal rye, oats, triticale)** produce large amounts of biomass, suppress weeds through shading and allelopathy, and protect soil structure over winter.

**Brassicas (radish, turnip, rapeseed)** break compaction with their taproots and scavenge residual nitrogen that would otherwise leach. Daikon radish can penetrate 18 inches of compacted subsoil.

## Matching Species to Your Goals

Nitrogen credit: Crimson clover, hairy vetch, field peas. Winter erosion control: Cereal rye, winter triticale. Compaction relief: Tillage radish, turnip. Weed suppression: Cereal rye, sorghum-sudan. Bee forage: Buckwheat, phacelia, red clover.

## Seeding Timing

Plant summer covers immediately after cash crop harvest. Winter covers should go in 4-6 weeks before the first killing frost. In the South, covers can be overseeded into standing corn or beans using high-clearance equipment.

## Termination

Terminate covers 2-3 weeks before planting to allow residue decomposition and avoid nitrogen tie-up from high-carbon species. Cereal rye biomass over 4,000 lb/acre may require rolling-crimping or an additional week of breakdown time.'
        WHERE Title = 'Cover Crop Selection Guide' AND BodyText IS NULL
    """))
    _c.execute(text("""
        UPDATE EduCourses SET BodyText = N'## What Is NDVI?

Normalized Difference Vegetation Index (NDVI) is a ratio calculated from near-infrared (NIR) and red reflectance measured by satellite sensors. Healthy green plants absorb red light for photosynthesis and reflect NIR strongly; stressed or sparse vegetation does the opposite.

Formula: NDVI = (NIR - Red) / (NIR + Red)

Values range from -1.0 to +1.0. A well-established crop canopy typically falls between 0.6 and 0.9 at peak growth, while bare soil reads 0.1-0.2.

## Reading the Map

Most precision ag platforms display NDVI on a color ramp: deep green for high values, yellow for mid-range, red for low. When interpreting your map:

**Compare fields to themselves over time.** A single snapshot is less useful than a trend. If a zone that was green last season is now yellow, something changed.

**Look for patterns.** Edge effects, waterways, soil type boundaries, and old fence lines all show up in NDVI. Uniform low values across an entire field suggest a field-wide issue. Patchy variation points toward soil variability or pest pressure.

**Time the imagery correctly.** NDVI peaks at canopy closure and declines naturally as the crop matures. Compare images taken at the same crop growth stage across years for apples-to-apples analysis.

## When to Act on Low Scores

Not every low-NDVI zone requires an immediate response. Use this decision framework:

Is the low zone persistent across multiple dates? Likely a soil issue - pull soil cores. Did it appear suddenly between two images? Scout for disease, insects, or hail damage. Does it align with a soil type boundary? Adjust fertility zones and seed populations. Is it at field edges? Check compaction from headland traffic, drainage tile breaks, or deer pressure.

## Limitations

Cloud cover, smoke, and atmospheric haze degrade image quality. Satellite revisit frequency (3-5 days for Sentinel-2, daily for Planet) determines how quickly you catch a problem. Always ground-truth with physical scouting before making large input decisions based solely on NDVI.'
        WHERE Title = 'Understanding NDVI and Satellite Imagery' AND BodyText IS NULL
    """))
    _c.execute(text("""
        UPDATE EduCourses SET BodyText = N'## Why Cash Flow Matters More Than Profit

A farm can show a paper profit in December while running out of cash in March. Seasonal revenue and year-round expenses create gaps that must be planned for. A 12-month cash flow projection tells you exactly when those gaps occur so you can arrange operating credit before you need it.

## The Four Building Blocks

**Revenue Timing:** List every income source and estimate when the cash will arrive, not when the sale occurs. Grain stored on-farm generates no cash until it is sold. CSA subscriptions paid in April fund May-October production costs.

**Variable Costs:** Inputs (seed, fertilizer, chemicals, feed) typically cluster in spring and fall. Map each purchase to the month you expect to write the check.

**Fixed Costs:** Land rent, loan payments, insurance, and utilities are predictable. Place them in the correct month and they will rarely surprise you.

**Family Living:** Many farm budgets omit owner withdrawals and family living expenses. Include them. A farm that cannot support the family is not a sustainable business.

## Building the Spreadsheet

Set up 13 columns: one label column, then January through December. Add rows for each revenue and expense category. At the bottom, calculate monthly net cash flow (total receipts minus total disbursements) and cumulative cash balance (prior month balance plus monthly net).

Watch for months where the cumulative balance goes negative - those are your borrowing windows.

## Stress Testing

Run the projection a second time with commodity prices 15% lower and input costs 10% higher. If the operation stays solvent, you have a meaningful margin of safety. If it does not, identify which line items to cut or which revenue source to accelerate.

## Updating Monthly

A projection is only useful if it tracks against reality. At the end of each month, enter actual receipts and disbursements and note the variance. Recurring variances improve future accuracy.'
        WHERE Title = 'Farm Financial Basics: Cash Flow Planning' AND BodyText IS NULL
    """))
    _c.execute(text("""
        UPDATE EduCourses SET BodyText = N'## Is Certification Right for You?

USDA organic certification is required to sell, label, or represent products as organic when annual gross sales exceed $5,000. Certification is administered by USDA-accredited certifying agents (CAs), not by USDA directly.

## The Three-Year Transition

Land must be managed organically - without prohibited substances - for 36 months before the first certified organic harvest. If you have never applied synthetic pesticides or fertilizers to a field, document that history. If you are transitioning conventionally managed ground, the clock starts on the last application date of any prohibited substance.

## Steps to Certification

**Step 1: Choose a Certifying Agent.** The USDA maintains a searchable list of accredited CAs at ams.usda.gov. Compare fees, response times, and inspector familiarity with your production type. Annual fees typically range from $400 to $2,500 depending on operation size.

**Step 2: Build Your Organic System Plan (OSP).** The OSP describes your fields and crop history, all inputs and their compliance status, practices for preventing co-mingling, and your record-keeping systems.

**Step 3: Submit Application and Pay Fees.** Submit your OSP, field maps, and three years of records (or a signed affidavit for land with no prohibited substance history).

**Step 4: On-Site Inspection.** An inspector visits your operation, reviews records, walks fields, and may collect soil or tissue samples.

**Step 5: Certification Decision.** The CA reviews the inspection report and issues a certificate, a notice of noncompliance, or a denial. Most compliant first-time applicants receive certification within 60-90 days.

## Annual Renewal

Certification is renewed annually. Submit an updated OSP, pay fees, and schedule your annual inspection. Keep records for 5 years.

## Allowed and Prohibited Substances

The National List (7 CFR Part 205) specifies what is allowed. Check the OMRI database before purchasing any input. A single non-compliant application can result in decertification.'
        WHERE Title = 'USDA Organic Certification: Step-by-Step' AND BodyText IS NULL
    """))
    _c.execute(text("""
        UPDATE EduCourses SET BodyText = N'## The Core Principle

Rotational grazing mimics the movement patterns of wild herbivores: graze intensively, then move on and allow complete recovery before returning. Continuous grazing lets animals selectively remove their favorite plants over and over, weakening root systems and inviting weed pressure. Rotation prevents this by enforcing rest.

## Paddock Design

Divide your total grazing area into a minimum of 4-8 paddocks. More paddocks give you longer rest periods and more flexibility. The goal is to graze each paddock for 3-7 days and then rest it for 21-60 days, depending on the season and forage growth rate.

**Practical layout tips:** Locate water and shade in or adjacent to every paddock. Use temporary electric fence (polywire, step-in posts) for flexibility - paddock size can shift as forage growth rates change. Consider topography: steep slopes, wet areas, and sacrifice paddocks should be designated separately.

## Stocking Rates

Stocking rate is the single most important variable. Overstocking causes soil compaction, forage destruction, and poor animal performance. Understocking wastes forage and allows coarse, unpalatable growth.

A starting rule of thumb for cool-season grass-based systems: 1 animal unit (1,000 lb beef cow + calf) per 1.5-3 acres depending on rainfall and soil productivity. Adjust annually based on body condition score trends and forage availability.

## Timing the Move

Move animals when the forage is grazed to 3-4 inches residual height for most cool-season grasses. Do not wait until paddocks are grazed bare - leaving 3-4 inches of leaf area allows rapid regrowth from stored root carbohydrates.

## Monitoring Recovery

Before re-entering a paddock, forage should be back to 8-12 inches for cool-season species or 12-18 inches for warm-season grasses. If paddocks are not recovering fully between rotations, reduce animal numbers or extend rest periods.'
        WHERE Title = 'Rotational Grazing 101' AND BodyText IS NULL
    """))
    _c.execute(text("""
        UPDATE EduCourses SET BodyText = N'## Why Scout?

Scouting converts field observations into decisions. Without systematic scouting, pest problems compound until they are obvious and expensive. A structured program catches issues at economic threshold levels, when targeted intervention is still cost-effective, rather than after yield loss has already occurred.

## Building a Scouting Schedule

Scout each field at least once per week during the growing season. Critical windows:

**Pre-plant through emergence:** Soil compaction, residue breakdown, stand establishment, early-season weed flushes.

**Vegetative stages:** Aphid colonies, rootworm silk clipping, spider mite hot spots, iron deficiency chlorosis.

**Reproductive stages:** Disease scouting intensifies - gray leaf spot, northern corn leaf blight, white mold, soybean sudden death syndrome.

**Pre-harvest:** Stalk quality, harvest aids timing for soybeans, aflatoxin risk assessment.

## Sampling Methods

Walk a consistent W or X route across the field so you cover multiple soil types and management zones. Stop at 10-20 locations per field and examine 10-20 plants per stop. Avoid field edges for your primary count - edges are not representative of field-average pressure.

For insects: count individuals per plant, per leaf, or per row foot - whichever unit matches the economic threshold table for that pest.

For disease: use a percent-affected-plants or percent-affected-leaf-area rating. Rate the same plant part consistently across stops.

For weeds: estimate percent ground cover or plants per square foot. Identify species - some weeds have much lower economic thresholds than others.

## Record Keeping

Record observations immediately. Capture: date, field ID, crop stage, GPS location of notable finds, counts or ratings, and your action decision. Photos tied to GPS points are invaluable for trend analysis. Compare current records to the same week in prior seasons.'
        WHERE Title = 'Crop Scouting Best Practices' AND BodyText IS NULL
    """))

CATEGORIES = [
    "Soil Health", "Crop Management", "Livestock", "Precision Ag", "Business",
    "Certifications", "Sustainability", "Marketing & Sales", "Equipment", "General",
]


class CourseCreate(BaseModel):
    title: str
    description: Optional[str] = None
    category: Optional[str] = None
    difficulty: Optional[str] = None
    duration_min: Optional[int] = None
    author_name: Optional[str] = None
    thumbnail_url: Optional[str] = None
    content_url: Optional[str] = None
    content_type: str = 'article'
    is_free: bool = True


def _ser(r): return dict(r._mapping)


@router.get("/categories")
def get_categories():
    return CATEGORIES


@router.get("")
def browse(
    category: Optional[str] = None,
    difficulty: Optional[str] = None,
    q: Optional[str] = None,
    db: Session = Depends(get_db),
):
    filters = ["c.IsPublished=1"]
    params: dict = {}
    if category:
        filters.append("c.Category=:cat"); params["cat"] = category
    if difficulty:
        filters.append("c.Difficulty=:diff"); params["diff"] = difficulty
    if q:
        filters.append("(c.Title LIKE :q OR c.Description LIKE :q OR c.AuthorName LIKE :q)")
        params["q"] = f"%{q}%"
    where = " AND ".join(filters)
    rows = db.execute(text(f"""
        SELECT c.*,
               (SELECT COUNT(*) FROM EduEnrollments e WHERE e.CourseID=c.CourseID) AS EnrollmentCount
        FROM EduCourses c WHERE {where} ORDER BY c.ViewCount DESC, c.CreatedAt DESC
    """), params).fetchall()
    return [_ser(r) for r in rows]


@router.get("/{course_id}")
def get_course(course_id: int, db: Session = Depends(get_db)):
    db.execute(text("UPDATE EduCourses SET ViewCount=ViewCount+1 WHERE CourseID=:id"), {"id": course_id})
    db.commit()
    row = db.execute(text("SELECT * FROM EduCourses WHERE CourseID=:id"), {"id": course_id}).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Course not found")
    return _ser(row)


@router.post("")
def create_course(course: CourseCreate, business_id: Optional[int] = None, db: Session = Depends(get_db)):
    row = db.execute(text("""
        INSERT INTO EduCourses
            (BusinessID,Title,Description,Category,Difficulty,DurationMin,AuthorName,
             ThumbnailUrl,ContentUrl,ContentType,IsFree)
        OUTPUT INSERTED.CourseID
        VALUES (:bid,:title,:desc,:cat,:diff,:dur,:author,:thumb,:content,:ctype,:free)
    """), {
        "bid": business_id, "title": course.title, "desc": course.description,
        "cat": course.category, "diff": course.difficulty, "dur": course.duration_min,
        "author": course.author_name, "thumb": course.thumbnail_url,
        "content": course.content_url, "ctype": course.content_type,
        "free": 1 if course.is_free else 0,
    }).fetchone()
    db.commit()
    return {"course_id": row[0]}


@router.post("/{course_id}/enroll")
def enroll(course_id: int, body: dict, db: Session = Depends(get_db)):
    people_id = body.get("people_id")
    if not people_id:
        raise HTTPException(status_code=400, detail="people_id required")
    try:
        db.execute(text("INSERT INTO EduEnrollments (CourseID,PeopleID) VALUES (:c,:p)"), {"c": course_id, "p": people_id})
        db.commit()
    except Exception:
        db.rollback()
    return {"ok": True}


@router.patch("/{course_id}/progress")
def update_progress(course_id: int, body: dict, db: Session = Depends(get_db)):
    people_id = body.get("people_id")
    pct = int(body.get("progress_pct") or 0)
    completed_at = "GETDATE()" if pct >= 100 else "NULL"
    db.execute(text(f"""
        UPDATE EduEnrollments SET ProgressPct=:pct, CompletedAt={completed_at}
        WHERE CourseID=:c AND PeopleID=:p
    """), {"pct": pct, "c": course_id, "p": people_id})
    db.commit()
    return {"ok": True}


@router.get("/people/{people_id}/enrollments")
def my_enrollments(people_id: int, db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT e.*, c.Title, c.Category, c.Difficulty, c.DurationMin,
               c.ThumbnailUrl, c.ContentUrl, c.ContentType, c.Description,
               c.BodyText, c.AuthorName, c.IsFree
        FROM EduEnrollments e
        JOIN EduCourses c ON c.CourseID=e.CourseID
        WHERE e.PeopleID=:p ORDER BY e.CreatedAt DESC
    """), {"p": people_id}).fetchall()
    return [_ser(r) for r in rows]
