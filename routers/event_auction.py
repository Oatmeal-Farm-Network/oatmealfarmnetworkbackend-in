"""
Event Auction (stud auction, silent auction, sale).

Modernized replacement for the classic ASP EventStudAuction.asp / EventSilentAuction.asp.
Organizers configure the auction, add lots (animals, fleeces, items, studs), and close
lots to award winners. Bidders browse lots, place bids, and track their own bids.
"""
from fastapi import APIRouter, Depends, HTTPException
from database import blank_to_none
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db, SessionLocal
from datetime import datetime, date

router = APIRouter()


def ensure_tables(db: Session):
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'OFNEventAuctionConfig')
        CREATE TABLE OFNEventAuctionConfig (
            ConfigID              INT IDENTITY(1,1) PRIMARY KEY,
            EventID               INT NOT NULL UNIQUE,
            AuctionType           NVARCHAR(50) DEFAULT 'Live',   -- Live | Silent | Online | Stud
            Description           NVARCHAR(MAX),
            BuyerPremiumPercent   DECIMAL(5,2) DEFAULT 0,
            MinBidIncrement       DECIMAL(10,2) DEFAULT 10,
            BidOpenDate           DATETIME,
            BidCloseDate          DATETIME,
            PaymentTerms          NVARCHAR(MAX),
            IsActive              BIT DEFAULT 1,
            CreatedDate           DATETIME DEFAULT GETDATE(),
            UpdatedDate           DATETIME DEFAULT GETDATE()
        )
    """))
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'OFNEventAuctionLots')
        CREATE TABLE OFNEventAuctionLots (
            LotID           INT IDENTITY(1,1) PRIMARY KEY,
            EventID         INT NOT NULL,
            LotNumber       NVARCHAR(50),
            LotType         NVARCHAR(50) DEFAULT 'Item',  -- Animal | Fleece | Item | StudService
            Title           NVARCHAR(300) NOT NULL,
            Description     NVARCHAR(MAX),
            PhotoURL        NVARCHAR(500),
            SellerPeopleID  INT,
            SellerBusinessID INT,
            SellerName      NVARCHAR(300),
            AnimalID        INT,
            StartingBid     DECIMAL(10,2) DEFAULT 0,
            ReserveBid      DECIMAL(10,2),
            MinIncrement    DECIMAL(10,2),
            CurrentBid      DECIMAL(10,2),
            WinnerPeopleID  INT,
            WinnerBusinessID INT,
            WinnerBid       DECIMAL(10,2),
            Status          NVARCHAR(50) DEFAULT 'open',   -- open | closed | passed | withdrawn
            ClosedAt        DATETIME,
            DisplayOrder    INT DEFAULT 0,
            CreatedDate     DATETIME DEFAULT GETDATE()
        )
    """))
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'OFNEventAuctionBids')
        CREATE TABLE OFNEventAuctionBids (
            BidID        INT IDENTITY(1,1) PRIMARY KEY,
            LotID        INT NOT NULL,
            EventID      INT NOT NULL,
            PeopleID     INT NOT NULL,
            BusinessID   INT,
            BidAmount    DECIMAL(10,2) NOT NULL,
            BidderName   NVARCHAR(300),
            BidTime      DATETIME DEFAULT GETDATE(),
            IsWinning    BIT DEFAULT 0,
            Notes        NVARCHAR(MAX)
        )
    """))
    db.commit()


try:
    with SessionLocal() as _db:
        ensure_tables(_db)
except Exception as e:
    print(f"[event_auction] Table ensure warning: {e}")


def _bidding_open(cfg: dict) -> bool:
    now = datetime.now()
    if cfg.get("BidOpenDate") and cfg["BidOpenDate"] > now:
        return False
    if cfg.get("BidCloseDate") and cfg["BidCloseDate"] < now:
        return False
    return bool(cfg.get("IsActive", True))


# ---------- CONFIG ----------

@router.get("/api/events/{event_id}/auction/config")
def get_auction_config(event_id: int, db: Session = Depends(get_db)):
    row = db.execute(text("SELECT * FROM OFNEventAuctionConfig WHERE EventID=:eid"),
                    {"eid": event_id}).fetchone()
    if not row:
        return {"configured": False, "EventID": event_id}
    cfg = dict(row._mapping)
    cfg["configured"] = True
    cfg["bidding_open"] = _bidding_open(cfg)
    return cfg


@router.put("/api/events/{event_id}/auction/config")
def put_auction_config(event_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    exists = db.execute(text("SELECT ConfigID FROM OFNEventAuctionConfig WHERE EventID=:eid"),
                       {"eid": event_id}).fetchone()
    params = {
        "eid": event_id,
        "at": body.get("AuctionType") or "Live",
        "d": body.get("Description"),
        "bp": body.get("BuyerPremiumPercent") or 0,
        "mi": body.get("MinBidIncrement") or 10,
        "bo": body.get("BidOpenDate"),
        "bc": body.get("BidCloseDate"),
        "pt": body.get("PaymentTerms"),
        "a": 1 if body.get("IsActive", True) else 0,
    }
    if exists:
        db.execute(text("""
            UPDATE OFNEventAuctionConfig SET
              AuctionType=:at, Description=:d, BuyerPremiumPercent=:bp,
              MinBidIncrement=:mi, BidOpenDate=:bo, BidCloseDate=:bc,
              PaymentTerms=:pt, IsActive=:a, UpdatedDate=GETDATE()
            WHERE EventID=:eid
        """), params)
    else:
        db.execute(text("""
            INSERT INTO OFNEventAuctionConfig
              (EventID, AuctionType, Description, BuyerPremiumPercent, MinBidIncrement,
               BidOpenDate, BidCloseDate, PaymentTerms, IsActive)
            VALUES (:eid, :at, :d, :bp, :mi, :bo, :bc, :pt, :a)
        """), params)
    db.commit()
    return {"ok": True}


# ---------- LOTS ----------

@router.get("/api/events/{event_id}/auction/lots")
def list_lots(event_id: int, db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT l.*, a.AnimalName, a.RegisteredName
        FROM OFNEventAuctionLots l
        LEFT JOIN Animals a ON a.AnimalID = l.AnimalID
        WHERE l.EventID = :eid
        ORDER BY l.DisplayOrder, l.LotNumber, l.LotID
    """), {"eid": event_id}).fetchall()
    return [dict(r._mapping) for r in rows]


@router.post("/api/events/{event_id}/auction/lots")
def add_lot(event_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    r = db.execute(text("""
        INSERT INTO OFNEventAuctionLots
          (EventID, LotNumber, LotType, Title, Description, PhotoURL, SellerPeopleID,
           SellerBusinessID, SellerName, AnimalID, StartingBid, ReserveBid, MinIncrement,
           DisplayOrder)
        VALUES (:eid, :ln, :lt, :t, :d, :p, :sp, :sb, :sn, :a,
                :st, :rs, :mi, :o);
        SELECT SCOPE_IDENTITY() AS NewID;
    """), {
        "eid": event_id, "ln": body.get("LotNumber"),
        "lt": body.get("LotType") or "Item", "t": body.get("Title"),
        "d": body.get("Description"), "p": body.get("PhotoURL"),
        "sp": body.get("SellerPeopleID"), "sb": body.get("SellerBusinessID"),
        "sn": body.get("SellerName"), "a": body.get("AnimalID"),
        "st": body.get("StartingBid") or 0, "rs": body.get("ReserveBid"),
        "mi": body.get("MinIncrement"), "o": body.get("DisplayOrder") or 0,
    })
    new_id = int(r.fetchone()[0])
    db.commit()
    return {"LotID": new_id}


@router.put("/api/events/auction/lots/{lot_id}")
def update_lot(lot_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    db.execute(text("""
        UPDATE OFNEventAuctionLots SET
          LotNumber=:ln, LotType=:lt, Title=:t, Description=:d, PhotoURL=:p,
          SellerPeopleID=:sp, SellerBusinessID=:sb, SellerName=:sn, AnimalID=:a,
          StartingBid=:st, ReserveBid=:rs, MinIncrement=:mi, DisplayOrder=:o,
          Status=:stat
        WHERE LotID=:lid
    """), {
        "lid": lot_id, "ln": body.get("LotNumber"),
        "lt": body.get("LotType") or "Item", "t": body.get("Title"),
        "d": body.get("Description"), "p": body.get("PhotoURL"),
        "sp": body.get("SellerPeopleID"), "sb": body.get("SellerBusinessID"),
        "sn": body.get("SellerName"), "a": body.get("AnimalID"),
        "st": body.get("StartingBid") or 0, "rs": body.get("ReserveBid"),
        "mi": body.get("MinIncrement"), "o": body.get("DisplayOrder") or 0,
        "stat": body.get("Status") or "open",
    })
    db.commit()
    return {"ok": True}


@router.delete("/api/events/auction/lots/{lot_id}")
def delete_lot(lot_id: int, db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM OFNEventAuctionBids WHERE LotID=:l"), {"l": lot_id})
    db.execute(text("DELETE FROM OFNEventAuctionLots WHERE LotID=:l"), {"l": lot_id})
    db.commit()
    return {"ok": True}


@router.post("/api/events/auction/lots/{lot_id}/close")
def close_lot(lot_id: int, db: Session = Depends(get_db)):
    """Award the lot to the highest bidder (if any)."""
    high = db.execute(text("""
        SELECT TOP 1 PeopleID, BusinessID, BidAmount, BidderName
        FROM OFNEventAuctionBids WHERE LotID=:l
        ORDER BY BidAmount DESC, BidTime ASC
    """), {"l": lot_id}).fetchone()
    lot = db.execute(text("SELECT ReserveBid FROM OFNEventAuctionLots WHERE LotID=:l"),
                    {"l": lot_id}).fetchone()
    if not high:
        db.execute(text("""
            UPDATE OFNEventAuctionLots SET Status='passed', ClosedAt=GETDATE() WHERE LotID=:l
        """), {"l": lot_id})
        db.commit()
        return {"closed": True, "winner": None, "status": "passed"}
    h = dict(high._mapping)
    reserve = lot._mapping["ReserveBid"] if lot else None
    if reserve and float(h["BidAmount"]) < float(reserve):
        db.execute(text("""
            UPDATE OFNEventAuctionLots SET Status='passed', ClosedAt=GETDATE() WHERE LotID=:l
        """), {"l": lot_id})
        db.commit()
        return {"closed": True, "winner": None, "status": "passed",
                "reason": "reserve not met", "high_bid": float(h["BidAmount"])}
    db.execute(text("""
        UPDATE OFNEventAuctionLots SET
          WinnerPeopleID=:wp, WinnerBusinessID=:wb, WinnerBid=:wa, Status='closed',
          ClosedAt=GETDATE(), CurrentBid=:wa
        WHERE LotID=:l
    """), {"l": lot_id, "wp": h["PeopleID"], "wb": h["BusinessID"], "wa": h["BidAmount"]})
    db.execute(text("""
        UPDATE OFNEventAuctionBids SET IsWinning=0 WHERE LotID=:l
    """), {"l": lot_id})
    db.execute(text("""
        UPDATE OFNEventAuctionBids SET IsWinning=1
        WHERE LotID=:l AND PeopleID=:p AND BidAmount=:a
    """), {"l": lot_id, "p": h["PeopleID"], "a": h["BidAmount"]})
    db.commit()
    return {"closed": True, "winner": h, "status": "closed"}


# ---------- BIDS ----------

@router.get("/api/events/{event_id}/auction/lots/{lot_id}/bids")
def lot_bids(event_id: int, lot_id: int, db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT * FROM OFNEventAuctionBids
        WHERE EventID=:e AND LotID=:l
        ORDER BY BidAmount DESC, BidTime DESC
    """), {"e": event_id, "l": lot_id}).fetchall()
    return [dict(r._mapping) for r in rows]


@router.post("/api/events/{event_id}/auction/lots/{lot_id}/bid")
def place_bid(event_id: int, lot_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    cfg_row = db.execute(text("SELECT * FROM OFNEventAuctionConfig WHERE EventID=:e"),
                        {"e": event_id}).fetchone()
    if not cfg_row:
        raise HTTPException(400, "Auction not configured")
    cfg = dict(cfg_row._mapping)
    if not _bidding_open(cfg):
        raise HTTPException(400, "Bidding is not currently open")
    lot_row = db.execute(text("SELECT * FROM OFNEventAuctionLots WHERE LotID=:l AND EventID=:e"),
                        {"l": lot_id, "e": event_id}).fetchone()
    if not lot_row:
        raise HTTPException(404, "Lot not found")
    lot = dict(lot_row._mapping)
    if lot.get("Status") != "open":
        raise HTTPException(400, f"Lot is {lot.get('Status')}")
    if not body.get("PeopleID"):
        raise HTTPException(400, "PeopleID required")
    amount = float(body.get("BidAmount") or 0)
    start = float(lot.get("StartingBid") or 0)
    current = float(lot.get("CurrentBid") or 0)
    min_inc = float(lot.get("MinIncrement") or cfg.get("MinBidIncrement") or 0)
    if current == 0:
        if amount < start:
            raise HTTPException(400, f"Minimum opening bid is ${start:.2f}")
    else:
        if amount < current + min_inc:
            raise HTTPException(400, f"Minimum next bid is ${current + min_inc:.2f}")
    db.execute(text("""
        INSERT INTO OFNEventAuctionBids
          (LotID, EventID, PeopleID, BusinessID, BidAmount, BidderName, Notes)
        VALUES (:l, :e, :p, :b, :a, :n, :note)
    """), {
        "l": lot_id, "e": event_id, "p": body.get("PeopleID"),
        "b": body.get("BusinessID"), "a": amount,
        "n": body.get("BidderName"), "note": body.get("Notes"),
    })
    db.execute(text("UPDATE OFNEventAuctionLots SET CurrentBid=:a WHERE LotID=:l"),
              {"a": amount, "l": lot_id})
    db.commit()
    return {"ok": True, "CurrentBid": amount}


@router.get("/api/events/{event_id}/auction/my-bids")
def my_bids(event_id: int, people_id: int, db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT b.BidID, b.BidAmount, b.BidTime, b.IsWinning,
               l.LotID, l.LotNumber, l.Title, l.CurrentBid, l.Status, l.WinnerPeopleID
        FROM OFNEventAuctionBids b
        JOIN OFNEventAuctionLots l ON l.LotID = b.LotID
        WHERE b.EventID=:e AND b.PeopleID=:p
        ORDER BY b.BidTime DESC
    """), {"e": event_id, "p": people_id}).fetchall()
    return [dict(r._mapping) for r in rows]
