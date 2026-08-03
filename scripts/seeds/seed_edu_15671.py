"""Seed education courses for BusinessID=15671."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")

from database import engine
from sqlalchemy import text

COURSES = [
    # Articles
    dict(title="Building a Farm-to-Table Supply Chain",
         category="Marketing & Sales", difficulty="Intermediate", duration=20,
         author="Green Valley Farm", ctype="article", is_free=1,
         description="How to move from commodity selling to direct restaurant and grocery partnerships.",
         body="""## Why Direct Relationships Change Everything

Commodity markets price your product identically to your neighbor's. A farm-to-table supply chain prices your product based on your story, your practices, and your relationships. Premiums of 20-50% over commodity are common for farms with strong direct accounts.

## Identifying Your First Restaurant Partner

Start with 3-5 independently owned restaurants within 30 miles. Avoid chains. Look for menus that already emphasize local or seasonal sourcing - they have customers who expect premium ingredients and owners who understand the value proposition.

Request a meeting with the chef or owner, not the purchasing manager. Bring samples. Chefs make decisions based on taste and reliability, not spreadsheets.

## What Restaurants Need From You

**Consistency:** A chef who builds a menu item around your tomatoes needs to know they will be available every week for the next 10 weeks. Overselling your capacity destroys relationships faster than anything else.

**Communication:** Text or email by Wednesday what will be available the following week, quantities, and price. Chefs plan menus on Thursdays.

**Reliable delivery:** Show up when you say you will, with what you said you would bring, packed cleanly and labeled.

## Pricing Your Product

Start with your cost of production per unit, add a fair labor rate (do not undercount your own time), then add 20-30% margin. Compare the result to what local grocery co-ops charge for similar product - your price should be at or slightly below their retail price, giving the restaurant a margin while still paying you fairly.

Never discount to win a new account. It sets a floor that is nearly impossible to raise later.

## Scaling the Relationship

Once you have proven reliability over one season, offer a seasonal contract: the restaurant commits to purchasing a minimum weekly volume in exchange for price stability and first access to limited items. This gives you planning certainty and gives them supply security."""),

    dict(title="Soil Health Testing: What to Order and Why",
         category="Soil Health", difficulty="Beginner", duration=12,
         author="Green Valley Farm", ctype="article", is_free=1,
         description="Which soil tests give you actionable data, and how to read the results.",
         body="""## The Basic Panel

Every field should have a standard soil test every 2-3 years. A basic panel includes pH, organic matter percentage, and major nutrients (phosphorus, potassium, calcium, magnesium, sulfur). Cost is typically $15-25 per sample through your state extension lab.

**pH** is the single most important number. Most crops perform best between 6.0 and 7.0. Outside that range, nutrients become chemically unavailable even when present in adequate quantities. Correct pH before addressing any other deficiency.

**Organic matter** reflects long-term soil health trajectory. Below 2% is concerning in most climates. Above 4% indicates a healthy, biologically active system.

## When to Add the Micronutrient Panel

Add boron, zinc, manganese, copper, and iron testing when you see unexplained deficiency symptoms, when entering a new crop rotation, or on sandy soils prone to leaching. Micronutrient panels add $20-40 but can diagnose problems that the basic panel misses entirely.

## Biological Testing

Haney test or Solvita CO2 respiration testing measures soil biological activity - how much of your organic matter is being cycled by microbes. This is not a replacement for standard chemistry tests but adds context. A soil with adequate nutrients but low biological activity will underperform.

## How to Pull a Good Sample

Pull 15-20 cores per sample area using a consistent depth (usually 0-6 inches for cropland, 0-4 inches for pasture). Mix cores thoroughly, remove large debris, and fill the sample bag to the indicated line. Label clearly with field ID and sampling date. Submit within 24 hours or refrigerate.

## Reading Your Results

Labs report results in lb/acre or ppm. Your state extension service publishes crop-specific sufficiency ranges. Numbers outside those ranges trigger a recommendation. Do not add nutrients that test in the high or excessive range - you are wasting money and contributing to runoff."""),

    dict(title="Water Quality Basics for Small Farms",
         category="Sustainability", difficulty="Beginner", duration=15,
         author="Green Valley Farm", ctype="article", is_free=1,
         description="Testing, improving, and maintaining water quality for irrigation and livestock.",
         body="""## Why Water Quality Matters

Poor irrigation water quality causes crop damage, equipment scaling, and in some cases food safety issues. Poor livestock water reduces intake, which directly reduces gain and milk production. Testing is cheap relative to the problems it prevents.

## What to Test For

**For irrigation:** pH, electrical conductivity (EC/salinity), sodium adsorption ratio (SAR), bicarbonate, and any contaminants relevant to your local geology (arsenic, nitrate in areas with heavy fertilizer history).

**For livestock:** coliform bacteria, nitrate, pH, hardness, and total dissolved solids. Animals refuse water above certain TDS levels - cattle typically refuse water above 3,000 mg/L TDS.

**For produce wash water:** If you are selling to restaurants or retailers under a food safety plan, your wash water needs to meet potable water standards. Test quarterly at minimum.

## Improving Water Quality

**High EC/salinity:** Reduce irrigation volume per application, increase leaching fraction, shift to more salt-tolerant varieties.

**High sodium (SAR):** Apply gypsum (calcium sulfate) to displace sodium from the soil exchange sites and improve infiltration.

**High bicarbonate:** Acidify water with sulfuric or citric acid to bring pH to 6.0-6.5 before fertigation. This also prevents emitter scaling in drip systems.

**Bacterial contamination:** Shock treat with chlorine or UV filtration. Identify the contamination source (wildlife, upstream runoff, well integrity) and eliminate it.

## Testing Schedule

Test your primary water source annually at minimum. Test more frequently if you notice changes in plant response, animal behavior, or equipment scaling. After flood events, always test before returning to use."""),

    # Videos (with external URLs)
    dict(title="Tractor Maintenance: Pre-Season Checklist",
         category="Equipment", difficulty="Beginner", duration=25,
         author="Green Valley Farm", ctype="video", is_free=1,
         content_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
         description="Walk through a complete pre-season tractor service checklist to prevent breakdowns during peak season.",
         body=None),

    dict(title="Installing Drip Irrigation: Field Layout to First Water",
         category="Equipment", difficulty="Intermediate", duration=40,
         author="Green Valley Farm", ctype="video", is_free=1,
         content_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
         description="End-to-end installation walkthrough for vegetable field drip tape systems.",
         body=None),

    # Courses
    dict(title="Vegetable Production Fundamentals",
         category="Crop Management", difficulty="Beginner", duration=180,
         author="Green Valley Farm", ctype="course", is_free=0,
         description="A 6-module course covering transplant production, fertility, pest management, and harvest for direct-market vegetable farms.",
         body="""## Course Overview

This course covers the full production cycle for direct-market vegetable farms. It is designed for new farmers and farm employees with little prior production experience.

## Module 1: Planning Your Crop Calendar

Successful vegetable production starts with a detailed planting calendar built backward from your market windows. We cover how to calculate days-to-maturity, succession planting intervals, and how to build a planting calendar in a simple spreadsheet.

## Module 2: Transplant Production

Growing healthy transplants is the foundation of high-yield field production. This module covers germination environment, seeding depth, tray selection, fertility for seedlings, and hardening-off protocols before transplanting.

## Module 3: Soil Fertility for Vegetables

Vegetables have high fertility demands and short growing seasons. We cover pre-plant soil preparation, side-dress timing, foliar feeding, and how to read plant symptoms to diagnose in-season deficiencies.

## Module 4: Integrated Pest Management

Pest management in vegetable production focuses on prevention first: row cover, resistant varieties, trap crops, and beneficial insect habitat. This module covers the most common vegetable pests and diseases by crop family and introduces economic threshold decision-making.

## Module 5: Harvest and Post-Harvest Handling

Harvest at the right stage and handle produce correctly from the moment it leaves the plant. We cover cooling methods, wash water sanitation, grading and packing standards, and shelf life management for common vegetables.

## Module 6: Record Keeping and Season Review

A productive season review drives next year's improvement. This module covers what records to keep during the season and how to use them for planning, cost analysis, and certification documentation."""),

    dict(title="Direct Marketing Strategies for Farm Products",
         category="Marketing & Sales", difficulty="Intermediate", duration=120,
         author="Green Valley Farm", ctype="course", is_free=0,
         description="Farmers markets, CSA, online stores, and wholesale accounts — building a multi-channel marketing strategy.",
         body="""## Course Overview

Most farms rely on a single sales channel until a bad market season or a buyer relationship falling apart forces diversification. This course helps you build a deliberate multi-channel strategy before you need it.

## Module 1: Farmers Market Success

Farmers markets remain the highest-margin channel for many small farms, but profitability requires rigorous cost accounting. We cover booth layout, display design, pricing psychology, customer relationship building, and how to calculate your true market profitability including labor.

## Module 2: Building a CSA Program

Community Supported Agriculture shifts cash flow forward and builds committed customer relationships. This module covers CSA structures (full share, partial share, add-on boxes), pricing, member communication, pack list planning, and retention strategies to minimize member attrition year-over-year.

## Module 3: Farm Online Store

E-commerce has lowered the barrier to direct sales beyond your local market. We cover platform selection, photography, product descriptions that convert, shipping logistics for perishables, and how to integrate online sales with your existing production planning.

## Module 4: Restaurant and Retail Accounts

Wholesale accounts offer volume and predictability at lower margins. This module covers prospecting, the first sales call, pricing wholesale accounts relative to your direct channels, invoicing and payment terms, and managing customer expectations around seasonality and availability.

## Module 5: Building Your Marketing Calendar

Tie all channels together into a 12-month marketing calendar that coordinates production planning, harvest timing, and customer communication. A unified calendar prevents the most common failure mode: running out of product at the height of demand."""),

    # Webinar
    dict(title="2025 USDA Grant Programs for Small Farms",
         category="Business", difficulty="Beginner", duration=60,
         author="Green Valley Farm", ctype="webinar", is_free=1,
         content_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
         description="Overview of SARE, EQIP, and specialty crop grants available to farms under 250 acres in 2025.",
         body=None),

    dict(title="Climate-Smart Practices: Carbon Credits and Cost-Share Programs",
         category="Sustainability", difficulty="Intermediate", duration=75,
         author="Green Valley Farm", ctype="webinar", is_free=1,
         content_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
         description="Understanding voluntary carbon markets, USDA Climate-Smart Commodities grants, and on-farm practice requirements.",
         body=None),

    dict(title="Livestock Recordkeeping for USDA Programs",
         category="Livestock", difficulty="Beginner", duration=45,
         author="Green Valley Farm", ctype="article", is_free=1,
         description="What records USDA programs require, how to keep them efficiently, and what software tools help.",
         body="""## Why Records Matter

USDA programs including EQIP, LFP, and ELAP require documentation of herd inventory, birth dates, death losses, and management practices. Poor records have caused farms to lose six-figure payments at audit time. Keeping records correctly from the start costs almost nothing.

## Animal Identification

All cattle in USDA programs must be officially identified. Accepted forms of ID include USDA-approved ear tags (840 tags), brand registration in brand states, and tattoos for certain breeds. Purchase 840 tags before calving season and apply at birth.

## What to Record

**For breeding herds:** Animal ID, birth date, dam ID, sire ID, breed, sex. Record transfers (sales, purchases) with buyer/seller name and date. Record deaths with date and cause.

**For grazing programs:** Date range on each pasture or allotment, approximate head count, forage condition at entry and exit.

**For feed records (LFP):** Purchased feed invoices, feeding dates, quantities fed per animal class.

## Tools That Help

A simple spiral notebook is legally acceptable but hard to organize and easy to lose. Options that work better:

**Spreadsheet:** One tab per year, one row per animal event. Low cost, highly flexible.

**AgriWebb, CattleMax, or Herd Boss:** Purpose-built livestock software with mobile apps for field entry. Cost $20-50/month but dramatically reduce double-entry.

**USDA's LPA (Livestock Inventory Program):** Free program through your FSA office that maintains official records for USDA program purposes.

## Audit Readiness

Keep records for 7 years minimum. Store a backup copy offsite or in cloud storage. When an FSA or NRCS agent requests records, you should be able to pull any animal's complete history within minutes."""),
]

def run():
    bid = 15671
    inserted = 0
    with engine.begin() as conn:
        for c in COURSES:
            conn.execute(text("""
                INSERT INTO EduCourses
                    (BusinessID,Title,Description,Category,Difficulty,DurationMin,
                     AuthorName,ContentType,IsFree,ContentUrl,BodyText,IsPublished)
                VALUES
                    (:bid,:title,:desc,:cat,:diff,:dur,
                     :author,:ctype,:free,:url,:body,1)
            """), {
                "bid": bid,
                "title": c["title"],
                "desc": c["description"],
                "cat": c["category"],
                "diff": c["difficulty"],
                "dur": c["duration"],
                "author": c["author"],
                "ctype": c["ctype"],
                "free": c["is_free"],
                "url": c.get("content_url"),
                "body": c.get("body"),
            })
            inserted += 1
            print(f"  + {c['ctype']:8s} {c['title']}")
    print(f"\nDone — {inserted} courses added for BusinessID={bid}")

if __name__ == "__main__":
    run()
