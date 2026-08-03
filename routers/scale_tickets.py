from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from datetime import date, datetime
from dependencies import get_raw_conn, get_current_user

router = APIRouter(prefix="/api/scale-tickets", tags=["scale_tickets"])
_ddl_done = False


def _ensure_tables(db):
    global _ddl_done
    if _ddl_done:
        return
    cur = db.cursor()
    cur.execute("""
    IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='ForwardContract')
    CREATE TABLE ForwardContract (
        ContractID INT IDENTITY PRIMARY KEY,
        BusinessID INT NOT NULL,
        ContractNumber NVARCHAR(60),
        CounterParty NVARCHAR(200) NOT NULL,
        CommodityName NVARCHAR(100) NOT NULL,
        ContractQtyTonnes DECIMAL(12,3) NOT NULL,
        PricePerTonne DECIMAL(12,4) NOT NULL,
        BasisAmount DECIMAL(10,4),
        FuturesMonth NVARCHAR(20),
        DeliveryPeriodStart DATE,
        DeliveryPeriodEnd DATE,
        Status NVARCHAR(30) NOT NULL DEFAULT 'open',
        Notes NVARCHAR(1000),
        CreatedAt DATETIME NOT NULL DEFAULT GETDATE()
    )""")
    cur.execute("""
    IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='ScaleTicket')
    CREATE TABLE ScaleTicket (
        TicketID INT IDENTITY PRIMARY KEY,
        BusinessID INT NOT NULL,
        TicketNumber NVARCHAR(60),
        TicketDate DATE NOT NULL,
        ElevatorName NVARCHAR(200),
        ElevatorLocation NVARCHAR(200),
        CommodityName NVARCHAR(100) NOT NULL,
        GrossWeightKg DECIMAL(12,3) NOT NULL,
        TareWeightKg DECIMAL(12,3) NOT NULL DEFAULT 0,
        NetWeightKg AS (GrossWeightKg - TareWeightKg) PERSISTED,
        MoisturePercent DECIMAL(6,3),
        MoistureDeductKg DECIMAL(12,3) DEFAULT 0,
        TestWeightKgHl DECIMAL(6,2),
        DockagePercent DECIMAL(6,3) DEFAULT 0,
        DockageDeductKg AS (ROUND((GrossWeightKg-TareWeightKg)*DockagePercent/100,3)) PERSISTED,
        FinalNetKg AS (GrossWeightKg - TareWeightKg - ISNULL(MoistureDeductKg,0) - ROUND((GrossWeightKg-TareWeightKg)*DockagePercent/100,3)) PERSISTED,
        FreightCostPerTonne DECIMAL(10,4) DEFAULT 0,
        PricePerTonne DECIMAL(12,4),
        OutgrowerContractID INT,
        ForwardContractID INT,
        LotID INT,
        Notes NVARCHAR(1000),
        CreatedAt DATETIME NOT NULL DEFAULT GETDATE()
    )""")
    cur.execute("""
    IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='ContractDelivery')
    CREATE TABLE ContractDelivery (
        DeliveryID INT IDENTITY PRIMARY KEY,
        ContractID INT NOT NULL,
        TicketID INT NOT NULL,
        BusinessID INT NOT NULL,
        DeliveryDate DATE NOT NULL,
        QuantityKg DECIMAL(12,3) NOT NULL,
        PricePerTonne DECIMAL(12,4),
        Notes NVARCHAR(500),
        CreatedAt DATETIME NOT NULL DEFAULT GETDATE()
    )""")
    db.commit()
    _ddl_done = True


class TicketIn(BaseModel):
    ticket_number: Optional[str] = None
    ticket_date: date
    elevator_name: Optional[str] = None
    elevator_location: Optional[str] = None
    commodity_name: str
    gross_weight_kg: float
    tare_weight_kg: float = 0
    moisture_percent: Optional[float] = None
    moisture_deduct_kg: float = 0
    test_weight_kg_hl: Optional[float] = None
    dockage_percent: float = 0
    freight_cost_per_tonne: float = 0
    price_per_tonne: Optional[float] = None
    outgrower_contract_id: Optional[int] = None
    forward_contract_id: Optional[int] = None
    lot_id: Optional[int] = None
    notes: Optional[str] = None


class ContractIn(BaseModel):
    contract_number: Optional[str] = None
    counter_party: str
    commodity_name: str
    contract_qty_tonnes: float
    price_per_tonne: float
    basis_amount: Optional[float] = None
    futures_month: Optional[str] = None
    delivery_period_start: Optional[date] = None
    delivery_period_end: Optional[date] = None
    notes: Optional[str] = None


class DeliveryIn(BaseModel):
    ticket_id: int
    delivery_date: date
    quantity_kg: float
    price_per_tonne: Optional[float] = None
    notes: Optional[str] = None


@router.get("/tickets")
def list_tickets(
    commodity: Optional[str] = None,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    elevator: Optional[str] = None,
    limit: int = 100,
    db=Depends(get_raw_conn),
    user=Depends(get_current_user),
):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    filters = ["BusinessID=?"]
    params: list = [bid]
    if commodity:
        filters.append("CommodityName=?"); params.append(commodity)
    if from_date:
        filters.append("TicketDate>=?"); params.append(str(from_date))
    if to_date:
        filters.append("TicketDate<=?"); params.append(str(to_date))
    if elevator:
        filters.append("ElevatorName LIKE ?"); params.append(f"%{elevator}%")
    cur.execute(f"""
        SELECT *, ROUND(FinalNetKg/1000,4) AS FinalNetTonnes,
               ROUND(FinalNetKg/1000 * ISNULL(PricePerTonne,0),2) AS GrossRevenue,
               ROUND(FinalNetKg/1000 * FreightCostPerTonne,2) AS FreightCost,
               ROUND(FinalNetKg/1000 * ISNULL(PricePerTonne,0) - FinalNetKg/1000 * FreightCostPerTonne,2) AS NetRevenue
        FROM ScaleTicket WHERE {' AND '.join(filters)}
        ORDER BY TicketDate DESC
        OFFSET 0 ROWS FETCH NEXT ? ROWS ONLY
    """, params + [limit])
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


@router.post("/tickets", status_code=201)
def create_ticket(body: TicketIn, db=Depends(get_raw_conn), user=Depends(get_current_user)):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    cur.execute("""
        INSERT INTO ScaleTicket
            (BusinessID,TicketNumber,TicketDate,ElevatorName,ElevatorLocation,CommodityName,
             GrossWeightKg,TareWeightKg,MoisturePercent,MoistureDeductKg,TestWeightKgHl,
             DockagePercent,FreightCostPerTonne,PricePerTonne,OutgrowerContractID,
             ForwardContractID,LotID,Notes)
        OUTPUT INSERTED.TicketID VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, [bid, body.ticket_number, str(body.ticket_date), body.elevator_name, body.elevator_location,
          body.commodity_name, body.gross_weight_kg, body.tare_weight_kg, body.moisture_percent,
          body.moisture_deduct_kg, body.test_weight_kg_hl, body.dockage_percent,
          body.freight_cost_per_tonne, body.price_per_tonne, body.outgrower_contract_id,
          body.forward_contract_id, body.lot_id, body.notes])
    tid = cur.fetchone()[0]
    db.commit()
    return {"ticket_id": tid}


@router.get("/tickets/{ticket_id}/margin")
def ticket_margin(ticket_id: int, db=Depends(get_raw_conn), user=Depends(get_current_user)):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    cur.execute("""
        SELECT *, ROUND(FinalNetKg/1000,4) AS FinalNetTonnes,
               ROUND(FinalNetKg/1000 * ISNULL(PricePerTonne,0),2) AS GrossRevenue,
               ROUND(FinalNetKg/1000 * FreightCostPerTonne,2) AS FreightCost,
               ROUND(FinalNetKg/1000 * ISNULL(PricePerTonne,0) - FinalNetKg/1000*FreightCostPerTonne,2) AS NetRevenue,
               ROUND(
                 (FinalNetKg/1000 * ISNULL(PricePerTonne,0) - FinalNetKg/1000*FreightCostPerTonne)
                 / NULLIF(FinalNetKg/1000,0), 4
               ) AS NetPerTonne
        FROM ScaleTicket WHERE TicketID=? AND BusinessID=?
    """, [ticket_id, bid])
    row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Ticket not found")
    cols = [c[0] for c in cur.description]
    ticket = dict(zip(cols, row))
    deductions = {
        "moisture_deduct_kg": float(ticket.get("MoistureDeductKg") or 0),
        "dockage_deduct_kg": float(ticket.get("DockageDeductKg") or 0),
        "freight_cost": float(ticket.get("FreightCost") or 0),
    }
    deductions["total_deduct_kg"] = deductions["moisture_deduct_kg"] + deductions["dockage_deduct_kg"]
    return {"ticket": ticket, "deductions": deductions}


@router.get("/summary")
def summary(
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    commodity: Optional[str] = None,
    db=Depends(get_raw_conn),
    user=Depends(get_current_user),
):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    filters = ["BusinessID=?"]
    params: list = [bid]
    if from_date:
        filters.append("TicketDate>=?"); params.append(str(from_date))
    if to_date:
        filters.append("TicketDate<=?"); params.append(str(to_date))
    if commodity:
        filters.append("CommodityName=?"); params.append(commodity)
    cur.execute(f"""
        SELECT CommodityName,
               COUNT(*) AS Tickets,
               ROUND(SUM(FinalNetKg)/1000,3) AS TotalNetTonnes,
               ROUND(AVG(ISNULL(PricePerTonne,0)),4) AS AvgPricePerTonne,
               ROUND(AVG(ISNULL(MoisturePercent,0)),3) AS AvgMoisture,
               ROUND(SUM(FinalNetKg/1000 * ISNULL(PricePerTonne,0)),2) AS TotalGrossRevenue,
               ROUND(SUM(FinalNetKg/1000 * FreightCostPerTonne),2) AS TotalFreight,
               ROUND(SUM(FinalNetKg/1000 * ISNULL(PricePerTonne,0) - FinalNetKg/1000*FreightCostPerTonne),2) AS TotalNetRevenue
        FROM ScaleTicket
        WHERE {' AND '.join(filters)}
        GROUP BY CommodityName ORDER BY TotalNetTonnes DESC
    """, params)
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


@router.get("/contracts")
def list_contracts(commodity: Optional[str] = None, status: Optional[str] = None, db=Depends(get_raw_conn), user=Depends(get_current_user)):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    filters = ["c.BusinessID=?"]
    params: list = [bid]
    if commodity:
        filters.append("c.CommodityName=?"); params.append(commodity)
    if status:
        filters.append("c.Status=?"); params.append(status)
    cur.execute(f"""
        SELECT c.*,
               ISNULL(d.DeliveredTonnes,0) AS DeliveredTonnes,
               ROUND(c.ContractQtyTonnes - ISNULL(d.DeliveredTonnes,0),4) AS RemainingTonnes,
               ROUND(ISNULL(d.DeliveredTonnes,0)/c.ContractQtyTonnes*100,2) AS FillPct
        FROM ForwardContract c
        OUTER APPLY (
            SELECT SUM(QuantityKg)/1000.0 AS DeliveredTonnes
            FROM ContractDelivery WHERE ContractID=c.ContractID
        ) d
        WHERE {' AND '.join(filters)}
        ORDER BY c.DeliveryPeriodEnd DESC
    """, params)
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


@router.post("/contracts", status_code=201)
def create_contract(body: ContractIn, db=Depends(get_raw_conn), user=Depends(get_current_user)):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    cur.execute("""
        INSERT INTO ForwardContract
            (BusinessID,ContractNumber,CounterParty,CommodityName,ContractQtyTonnes,
             PricePerTonne,BasisAmount,FuturesMonth,DeliveryPeriodStart,DeliveryPeriodEnd,Notes)
        OUTPUT INSERTED.ContractID VALUES (?,?,?,?,?,?,?,?,?,?,?)
    """, [bid, body.contract_number, body.counter_party, body.commodity_name,
          body.contract_qty_tonnes, body.price_per_tonne, body.basis_amount, body.futures_month,
          str(body.delivery_period_start) if body.delivery_period_start else None,
          str(body.delivery_period_end) if body.delivery_period_end else None, body.notes])
    cid = cur.fetchone()[0]
    db.commit()
    return {"contract_id": cid}


@router.post("/contracts/{contract_id}/apply-delivery", status_code=201)
def apply_delivery(contract_id: int, body: DeliveryIn, db=Depends(get_raw_conn), user=Depends(get_current_user)):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    cur.execute("SELECT ContractQtyTonnes FROM ForwardContract WHERE ContractID=? AND BusinessID=?", [contract_id, bid])
    row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Contract not found")
    cur.execute("""
        INSERT INTO ContractDelivery (ContractID,TicketID,BusinessID,DeliveryDate,QuantityKg,PricePerTonne,Notes)
        OUTPUT INSERTED.DeliveryID VALUES (?,?,?,?,?,?,?)
    """, [contract_id, body.ticket_id, bid, str(body.delivery_date), body.quantity_kg,
          body.price_per_tonne, body.notes])
    did = cur.fetchone()[0]
    # auto-update contract status
    cur.execute("""
        DECLARE @total DECIMAL(12,3) = (
            SELECT SUM(QuantityKg)/1000 FROM ContractDelivery WHERE ContractID=?
        );
        DECLARE @qty DECIMAL(12,3) = (SELECT ContractQtyTonnes FROM ForwardContract WHERE ContractID=?);
        UPDATE ForwardContract SET Status =
            CASE WHEN @total >= @qty THEN 'filled'
                 WHEN @total > 0 THEN 'partially_filled'
                 ELSE 'open' END
        WHERE ContractID=?
    """, [contract_id, contract_id, contract_id])
    db.commit()
    return {"delivery_id": did}


@router.get("/contracts/{contract_id}/position")
def contract_position(contract_id: int, db=Depends(get_raw_conn), user=Depends(get_current_user)):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    cur.execute("""
        SELECT c.*, ISNULL(d.DeliveredKg,0)/1000.0 AS DeliveredTonnes,
               c.ContractQtyTonnes - ISNULL(d.DeliveredKg,0)/1000.0 AS RemainingTonnes
        FROM ForwardContract c
        OUTER APPLY (SELECT SUM(QuantityKg) AS DeliveredKg FROM ContractDelivery WHERE ContractID=c.ContractID) d
        WHERE c.ContractID=? AND c.BusinessID=?
    """, [contract_id, bid])
    row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Contract not found")
    cols = [c[0] for c in cur.description]
    contract = dict(zip(cols, row))
    cur.execute("""
        SELECT cd.*, st.TicketDate, st.ElevatorName, st.FinalNetKg
        FROM ContractDelivery cd
        LEFT JOIN ScaleTicket st ON st.TicketID=cd.TicketID
        WHERE cd.ContractID=? ORDER BY cd.DeliveryDate
    """, [contract_id])
    cols2 = [c[0] for c in cur.description]
    deliveries = [dict(zip(cols2, r)) for r in cur.fetchall()]
    return {"contract": contract, "deliveries": deliveries}


def _ensure_posting_table(db):
    cur = db.cursor()
    cur.execute("""
    IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='ScaleTicketAccountingPost')
    CREATE TABLE ScaleTicketAccountingPost (
        PostID INT IDENTITY PRIMARY KEY,
        TicketID INT NOT NULL UNIQUE,
        BusinessID INT NOT NULL,
        PostedAt DATETIME NOT NULL DEFAULT GETDATE(),
        PostedBy NVARCHAR(200),
        FinalNetTonnes DECIMAL(12,4) NOT NULL,
        PricePerTonne DECIMAL(12,4) NOT NULL,
        GrossRevenue DECIMAL(14,2) NOT NULL,
        FreightCost DECIMAL(12,2) NOT NULL,
        NetRevenue DECIMAL(14,2) NOT NULL,
        ReferenceNumber NVARCHAR(60) NOT NULL,
        Notes NVARCHAR(500)
    )""")
    db.commit()


@router.post("/tickets/{ticket_id}/post-to-accounting", status_code=201)
def post_to_accounting(
    ticket_id: int,
    notes: Optional[str] = None,
    db=Depends(get_raw_conn),
    user=Depends(get_current_user),
):
    """Post a scale ticket to the accounting ledger as a grain sale revenue entry."""
    _ensure_tables(db)
    _ensure_posting_table(db)
    bid = user["BusinessID"]
    cur = db.cursor()

    # Check not already posted
    cur.execute("SELECT PostID FROM ScaleTicketAccountingPost WHERE TicketID=? AND BusinessID=?", [ticket_id, bid])
    if cur.fetchone():
        raise HTTPException(409, "Ticket already posted to accounting")

    # Get ticket details
    cur.execute("""
        SELECT TicketNumber, TicketDate, CommodityName,
               ROUND(FinalNetKg/1000,4) AS FinalNetTonnes,
               ISNULL(PricePerTonne,0) AS PricePerTonne,
               ROUND(FinalNetKg/1000 * ISNULL(PricePerTonne,0),2) AS GrossRevenue,
               ROUND(FinalNetKg/1000 * FreightCostPerTonne,2) AS FreightCost,
               ROUND(FinalNetKg/1000 * ISNULL(PricePerTonne,0) - FinalNetKg/1000 * FreightCostPerTonne,2) AS NetRevenue
        FROM ScaleTicket WHERE TicketID=? AND BusinessID=?
    """, [ticket_id, bid])
    row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Ticket not found")

    ticket_num, ticket_date, commodity, net_tonnes, price_pt, gross, freight, net = row
    ref = f"GRAIN-{ticket_id:06d}-{datetime.utcnow().strftime('%Y%m%d')}"
    posted_by = user.get("email") or user.get("username", "")

    cur.execute("""
        INSERT INTO ScaleTicketAccountingPost
            (TicketID,BusinessID,PostedBy,FinalNetTonnes,PricePerTonne,GrossRevenue,
             FreightCost,NetRevenue,ReferenceNumber,Notes)
        OUTPUT INSERTED.PostID VALUES (?,?,?,?,?,?,?,?,?,?)
    """, [ticket_id, bid, posted_by, float(net_tonnes or 0), float(price_pt or 0),
          float(gross or 0), float(freight or 0), float(net or 0), ref, notes])
    post_id = cur.fetchone()[0]
    db.commit()
    return {
        "post_id": post_id,
        "reference_number": ref,
        "ticket_id": ticket_id,
        "ticket_number": ticket_num,
        "commodity": commodity,
        "final_net_tonnes": float(net_tonnes or 0),
        "price_per_tonne": float(price_pt or 0),
        "gross_revenue": float(gross or 0),
        "freight_cost": float(freight or 0),
        "net_revenue": float(net or 0),
        "posted_at": datetime.utcnow().isoformat(),
    }


@router.get("/tickets/{ticket_id}/accounting-post")
def get_accounting_post(ticket_id: int, db=Depends(get_raw_conn), user=Depends(get_current_user)):
    """Return accounting post record for a ticket, if it exists."""
    _ensure_posting_table(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    cur.execute("SELECT * FROM ScaleTicketAccountingPost WHERE TicketID=? AND BusinessID=?", [ticket_id, bid])
    row = cur.fetchone()
    if not row:
        return {"posted": False}
    cols = [c[0] for c in cur.description]
    return {"posted": True, **dict(zip(cols, row))}
