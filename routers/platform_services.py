"""
Platform Services — OFN's own marketed offerings (Saige, Pairsley, Rosemarie, and
other platform services).

Public endpoints expose published services for the frontend Services menu and
detail pages. Admin endpoints allow CRUD at oatmeal-ai.com/app/admin/site-management.

Each row is a short DB record (slug, title, tagline, summary, icon, sort order,
published flag). Rich editorial content lives in the React page templates keyed
off the slug, so the DB stays lean and editorial polish lives in code.
"""
import os
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db, SessionLocal

router = APIRouter()


def ensure_tables(db: Session):
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'PlatformServices')
        CREATE TABLE PlatformServices (
            ServiceID       INT IDENTITY(1,1) PRIMARY KEY,
            Slug            NVARCHAR(100) NOT NULL UNIQUE,
            Title           NVARCHAR(200) NOT NULL,
            Tagline         NVARCHAR(300) NULL,
            Summary         NVARCHAR(MAX) NULL,
            IconEmoji       NVARCHAR(20) NULL,
            AccentColor     NVARCHAR(20) NULL,
            Category        NVARCHAR(60) NULL,
            RoutePath       NVARCHAR(200) NULL,
            IsAgent         BIT DEFAULT 0,
            IsPublished     BIT DEFAULT 1,
            SortOrder       INT DEFAULT 100,
            CreatedAt       DATETIME DEFAULT GETDATE(),
            UpdatedAt       DATETIME DEFAULT GETDATE()
        )
    """))
    db.commit()

    # Seed the three AI agents + a handful of starter services on first run.
    count = db.execute(text("SELECT COUNT(*) AS c FROM PlatformServices")).mappings().first()
    if count and count["c"] == 0:
        seeds = [
            ("saige",     "Saige",     "Your AI agricultural assistant",
             "Saige is the Oatmeal Farm Network AI agent for growers and ranchers — crops, livestock, soil, weather, and market intelligence.",
             "🌾", "#3D6B34", "AI Agent", "/platform/saige", 1, 1, 10),
            ("rosemarie", "Rosemarie", "AI assistant for artisan food producers",
             "Rosemarie advises mills, bakers, and artisan food producers — recipes, yields, sourcing, labeling, and small-batch operations.",
             "🌿", "#8B5CF6", "AI Agent", "/platform/rosemarie", 1, 1, 20),
            ("pairsley",  "Pairsley",  "AI agent for restaurants and professional kitchens",
             "Pairsley supports restaurateurs, chefs, and professional kitchens with sourcing, seasonal menus, costing, and vendor relationships.",
             "🍳", "#2f7d4a", "AI Agent", "/platform/pairsley", 1, 1, 30),
            ("website-builder", "Website Builder", "Launch a farm website in minutes",
             "Drag-and-drop website builder with farm-aware widgets — inventory, ranch profile, blog, events, and more.",
             "🖥️", "#3D6B34", "Platform", "/platform/website-builder", 0, 1, 110),
            ("marketplace", "Marketplace", "Sell produce, meat, and processed foods",
             "List farm products once and appear in Farm 2 Table, Products, and Livestock marketplaces. Stripe payouts built in.",
             "🛒", "#A3301E", "Platform", "/platform/marketplace", 0, 1, 120),
            ("events", "Events", "Register, ticket, and run ag events",
             "Turnkey event management for workshops, fiber festivals, livestock shows, auctions, farm tours, and more.",
             "🎪", "#EFAE15", "Platform", "/platform/events", 0, 1, 130),
            ("crop-monitor", "Crop Monitor", "Precision-ag imagery and field health",
             "Satellite and drone imagery with field-level analysis, crop detection, and season-over-season trends.",
             "🛰️", "#2563EB", "Platform", "/platform/crop-monitor", 0, 1, 140),
            ("directory", "Directory", "Find farms, ranches, and ag businesses",
             "The Oatmeal Farm Network directory — searchable by product, livestock breed, region, and more.",
             "📖", "#3D6B34", "Platform", "/platform/directory", 0, 1, 150),
        ]
        for s in seeds:
            db.execute(text("""
                INSERT INTO PlatformServices
                    (Slug, Title, Tagline, Summary, IconEmoji, AccentColor, Category, RoutePath, IsAgent, IsPublished, SortOrder)
                VALUES
                    (:slug, :title, :tagline, :summary, :icon, :accent, :cat, :route, :agent, :pub, :sort)
            """), {
                "slug": s[0], "title": s[1], "tagline": s[2], "summary": s[3],
                "icon": s[4], "accent": s[5], "cat": s[6], "route": s[7],
                "agent": s[8], "pub": s[9], "sort": s[10],
            })
        db.commit()


with SessionLocal() as _db:
    try:
        ensure_tables(_db)
    except Exception as e:
        print(f"PlatformServices table setup error: {e}")


# ─── Models ──────────────────────────────────────────────────────────────────
class PlatformServiceIn(BaseModel):
    Slug: str
    Title: str
    Tagline: Optional[str] = None
    Summary: Optional[str] = None
    IconEmoji: Optional[str] = None
    AccentColor: Optional[str] = None
    Category: Optional[str] = None
    RoutePath: Optional[str] = None
    IsAgent: Optional[bool] = False
    IsPublished: Optional[bool] = True
    SortOrder: Optional[int] = 100


# ─── Admin gate ──────────────────────────────────────────────────────────────
def _is_admin(people_id: Optional[str]) -> bool:
    if not people_id:
        return False
    admins = os.getenv("PLATFORM_ADMIN_IDS", "")
    if not admins:
        return False
    allowed = {p.strip() for p in admins.split(",") if p.strip()}
    return str(people_id) in allowed


def _row_to_dict(r):
    d = dict(r._mapping)
    d["IsAgent"] = bool(d.get("IsAgent"))
    d["IsPublished"] = bool(d.get("IsPublished"))
    return d


# ─── Public endpoints ────────────────────────────────────────────────────────
@router.get("/api/platform-services")
def list_published(db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT ServiceID, Slug, Title, Tagline, Summary, IconEmoji, AccentColor,
               Category, RoutePath, IsAgent, IsPublished, SortOrder, UpdatedAt
        FROM PlatformServices
        WHERE IsPublished = 1
        ORDER BY SortOrder, Title
    """)).fetchall()
    return [_row_to_dict(r) for r in rows]


@router.get("/api/platform-services/by-slug/{slug}")
def get_by_slug(slug: str, db: Session = Depends(get_db)):
    row = db.execute(text("""
        SELECT ServiceID, Slug, Title, Tagline, Summary, IconEmoji, AccentColor,
               Category, RoutePath, IsAgent, IsPublished, SortOrder, UpdatedAt
        FROM PlatformServices
        WHERE Slug = :slug AND IsPublished = 1
    """), {"slug": slug}).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Service not found")
    return _row_to_dict(row)


# ─── Admin endpoints ─────────────────────────────────────────────────────────
from fastapi import Header


@router.get("/admin/platform-services")
def admin_list_services(
    x_people_id: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    if not _is_admin(x_people_id):
        raise HTTPException(status_code=403, detail="Admin only")
    rows = db.execute(text("""
        SELECT ServiceID, Slug, Title, Tagline, Summary, IconEmoji, AccentColor,
               Category, RoutePath, IsAgent, IsPublished, SortOrder, CreatedAt, UpdatedAt
        FROM PlatformServices
        ORDER BY SortOrder, Title
    """)).fetchall()
    return [_row_to_dict(r) for r in rows]


@router.post("/admin/platform-services")
def admin_create_service(
    body: PlatformServiceIn,
    x_people_id: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    if not _is_admin(x_people_id):
        raise HTTPException(status_code=403, detail="Admin only")
    existing = db.execute(text("SELECT ServiceID FROM PlatformServices WHERE Slug = :s"),
                          {"s": body.Slug}).fetchone()
    if existing:
        raise HTTPException(status_code=409, detail="Slug already exists")
    db.execute(text("""
        INSERT INTO PlatformServices
            (Slug, Title, Tagline, Summary, IconEmoji, AccentColor, Category, RoutePath, IsAgent, IsPublished, SortOrder)
        VALUES
            (:slug, :title, :tagline, :summary, :icon, :accent, :cat, :route, :agent, :pub, :sort)
    """), {
        "slug": body.Slug, "title": body.Title, "tagline": body.Tagline, "summary": body.Summary,
        "icon": body.IconEmoji, "accent": body.AccentColor, "cat": body.Category,
        "route": body.RoutePath, "agent": 1 if body.IsAgent else 0,
        "pub": 1 if body.IsPublished else 0, "sort": body.SortOrder or 100,
    })
    db.commit()
    return {"ok": True}


@router.put("/admin/platform-services/{service_id}")
def admin_update_service(
    service_id: int,
    body: PlatformServiceIn,
    x_people_id: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    if not _is_admin(x_people_id):
        raise HTTPException(status_code=403, detail="Admin only")
    db.execute(text("""
        UPDATE PlatformServices SET
            Slug = :slug, Title = :title, Tagline = :tagline, Summary = :summary,
            IconEmoji = :icon, AccentColor = :accent, Category = :cat,
            RoutePath = :route, IsAgent = :agent, IsPublished = :pub,
            SortOrder = :sort, UpdatedAt = GETDATE()
        WHERE ServiceID = :id
    """), {
        "id": service_id,
        "slug": body.Slug, "title": body.Title, "tagline": body.Tagline, "summary": body.Summary,
        "icon": body.IconEmoji, "accent": body.AccentColor, "cat": body.Category,
        "route": body.RoutePath, "agent": 1 if body.IsAgent else 0,
        "pub": 1 if body.IsPublished else 0, "sort": body.SortOrder or 100,
    })
    db.commit()
    return {"ok": True}


@router.delete("/admin/platform-services/{service_id}")
def admin_delete_service(
    service_id: int,
    x_people_id: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    if not _is_admin(x_people_id):
        raise HTTPException(status_code=403, detail="Admin only")
    db.execute(text("DELETE FROM PlatformServices WHERE ServiceID = :id"), {"id": service_id})
    db.commit()
    return {"ok": True}
